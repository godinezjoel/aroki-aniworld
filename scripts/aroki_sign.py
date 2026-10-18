#!/usr/bin/env python3
"""Sign and publish this Aroki collection with your own Ed25519 key.

Signature scheme (verified against every signature in kas021/AROKI-Connectors):
- manifest signature: Ed25519 over the manifest file's exact bytes
- index/artwork signature: Ed25519 over the document without its "signature"
  field, encoded as compact JSON with sorted keys and unescaped slashes
- publicKey: the raw 32-byte Ed25519 public key, base64

Commands:
  keygen   create a new private key (never commit it)
  publish  copy manifests to immutable release paths, sign, write index.json
           and artwork.json, then verify everything
  verify   verify index.json / artwork.json and every referenced manifest

The private key is read from AROKI_SIGNING_KEY (base64 of the 32-byte seed) or
from the PEM file at AROKI_SIGNING_KEY_FILE, default ~/.aroki/aniworld-signing-key.pem.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEY_FILE = Path.home() / ".aroki" / "aniworld-signing-key.pem"
INDEX_FIELDS = ("contentRating", "contentType", "familyID", "id", "language", "minimumAppVersion",
                "name", "releaseNotes", "releaseTrack", "status", "version")
COLLECTION = json.loads((ROOT / "collection.json").read_text(encoding="utf-8"))


def canonical(document: dict) -> bytes:
    body = {key: value for key, value in document.items() if key != "signature"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def public_bytes(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def fingerprint(raw_public_key: bytes) -> str:
    digest = hashlib.sha256(raw_public_key).hexdigest().upper()
    return ":".join(digest[i:i + 4] for i in range(0, 32, 4))


def key_file() -> Path:
    return Path(os.environ.get("AROKI_SIGNING_KEY_FILE", DEFAULT_KEY_FILE)).expanduser()


def load_private_key() -> Ed25519PrivateKey:
    seed = os.environ.get("AROKI_SIGNING_KEY")
    if seed:
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(seed))
    path = key_file()
    if not path.is_file():
        raise SystemExit(f"ERROR: no signing key at {path}. Run: py scripts/aroki_sign.py keygen")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("ERROR: signing key is not Ed25519")
    return key


def write_json(path: Path, document: dict) -> None:
    path.write_bytes((json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))


def cmd_keygen(args: argparse.Namespace) -> None:
    path = key_file()
    if path.exists() and not args.force:
        raise SystemExit(f"ERROR: {path} already exists; refusing to overwrite (use --force to replace it)")
    try:
        path.resolve().relative_to(ROOT)
        raise SystemExit("ERROR: keep the private key outside the repository")
    except ValueError:
        pass
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    raw = public_bytes(key.public_key())
    seed = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                             serialization.NoEncryption())
    print(f"WROTE private key: {path}  (back it up; never commit it)")
    print(f"publicKey:   {b64(raw)}")
    print(f"fingerprint: {fingerprint(raw)}")
    if args.show_secret:
        print(f"AROKI_SIGNING_KEY (GitHub secret value): {b64(seed)}")


def entry_for(manifest_path: Path, key: Ed25519PrivateKey) -> dict:
    raw = manifest_path.read_bytes()
    if b"\r" in raw:
        raise SystemExit(f"ERROR: {manifest_path} has CRLF line endings")
    manifest = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    release = ROOT / "connectors" / manifest["id"] / "releases" / digest / "connector.json"
    if release.exists() and release.read_bytes() != raw:
        raise SystemExit(f"ERROR: {release} exists with different bytes")
    release.parent.mkdir(parents=True, exist_ok=True)
    release.write_bytes(raw)
    entry = {field: manifest[field] for field in INDEX_FIELDS}
    entry["manifest"] = {
        "path": release.relative_to(ROOT).as_posix(),
        "sha256": digest,
        "signature": b64(key.sign(raw)),
    }
    return entry


def signed(document: dict, key: Ed25519PrivateKey) -> dict:
    document["signature"] = b64(key.sign(canonical(document)))
    return document


def cmd_publish(args: argparse.Namespace) -> None:
    key = load_private_key()
    raw_public = public_bytes(key.public_key())
    generated_at = args.generated_at or int(time.time())
    entries = [entry_for(ROOT / "connectors" / cid / "connector.json", key) for cid in COLLECTION["connectors"]]
    header = {
        "enabled": True,
        "generatedAt": generated_at,
        "name": COLLECTION["name"],
        "publicKey": b64(raw_public),
        "repositoryID": COLLECTION["repositoryID"],
        "schemaVersion": 1,
    }
    write_json(ROOT / "index.json", signed({"connectors": entries, **header}, key))

    artwork_entries = []
    for entry in entries:
        logo = COLLECTION.get("logos", {}).get(entry["id"])
        if logo:
            data = (ROOT / logo).read_bytes()
            entry = {**entry, "icon": {"path": logo, "sha256": hashlib.sha256(data).hexdigest()}}
        artwork_entries.append(entry)
    write_json(ROOT / "artwork.json", signed({"connectors": artwork_entries, **header}, key))
    print(f"WROTE: index.json and artwork.json with {len(entries)} signed connector(s)")
    print(f"fingerprint: {fingerprint(raw_public)}")
    verify_all()


def verify_document(path: Path) -> int:
    document = json.loads(path.read_bytes())
    strict = path.parent == ROOT  # extra publishing rules for this repository only
    public = Ed25519PublicKey.from_public_bytes(base64.b64decode(document["publicKey"]))
    try:
        public.verify(base64.b64decode(document["signature"]), canonical(document))
    except InvalidSignature:
        raise SystemExit(f"FAIL: {path.name} signature")
    for entry in document["connectors"]:
        descriptor = entry["manifest"]
        raw = (path.parent / descriptor["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
            raise SystemExit(f"FAIL: {entry['id']} sha256")
        if strict and not re.fullmatch(r"connectors/[a-z0-9-]+/releases/[0-9a-f]{64}/connector\.json",
                                       descriptor["path"]):
            raise SystemExit(f"FAIL: {entry['id']} manifest path is not an immutable release path")
        try:
            public.verify(base64.b64decode(descriptor["signature"]), raw)
        except InvalidSignature:
            raise SystemExit(f"FAIL: {entry['id']} manifest signature")
        manifest = json.loads(raw)
        for field in INDEX_FIELDS if strict else ():
            if manifest.get(field) != entry[field]:
                raise SystemExit(f"FAIL: {entry['id']} index field {field} differs from manifest")
        icon = entry.get("icon")
        if icon and hashlib.sha256((path.parent / icon["path"]).read_bytes()).hexdigest() != icon["sha256"]:
            raise SystemExit(f"FAIL: {entry['id']} icon sha256")
    print(f"PASS: {path.name} ({len(document['connectors'])} connector(s)) signature, hashes and manifests verify")
    return len(document["connectors"])


def verify_all() -> None:
    verify_document(ROOT / "index.json")
    if (ROOT / "artwork.json").exists():
        verify_document(ROOT / "artwork.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    keygen = sub.add_parser("keygen")
    keygen.add_argument("--force", action="store_true")
    keygen.add_argument("--show-secret", action="store_true", help="also print the seed for a GitHub secret")
    publish = sub.add_parser("publish")
    publish.add_argument("--generated-at", type=int)
    verify = sub.add_parser("verify")
    verify.add_argument("documents", nargs="*", type=Path)
    args = parser.parse_args()
    if args.command == "keygen":
        cmd_keygen(args)
    elif args.command == "publish":
        cmd_publish(args)
    elif args.documents:
        for document in args.documents:
            verify_document(document.resolve())
    else:
        verify_all()


if __name__ == "__main__":
    main()
