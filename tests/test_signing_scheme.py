#!/usr/bin/env python3
"""Prove scripts/aroki_sign.py uses the same signature scheme Aroki accepts.

Downloads kas021/AROKI-Connectors at a pinned commit (an index the app already
trusts) and checks it with this repository's verifier, then round-trips a
throwaway key through sign -> verify. Needs network access.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "https://raw.githubusercontent.com/kas021/AROKI-Connectors/62c9b7d047da4bcf6d4d35e6ac4f80e3b5bd0698/"

spec = importlib.util.spec_from_file_location("aroki_sign", ROOT / "scripts" / "aroki_sign.py")
aroki_sign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aroki_sign)


def fetch(path: str) -> bytes:
    with urllib.request.urlopen(UPSTREAM + path, timeout=30) as response:
        return response.read()


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name in ("index.json", "artwork.json"):
            raw = fetch(name)
            (tmp / name).write_bytes(raw)
            for entry in json.loads(raw)["connectors"]:
                for path in (entry["manifest"]["path"], entry.get("icon", {}).get("path")):
                    if path and not (tmp / path).exists():
                        (tmp / path).parent.mkdir(parents=True, exist_ok=True)
                        (tmp / path).write_bytes(fetch(path))
            count = aroki_sign.verify_document(tmp / name)
            assert count > 0

        key = aroki_sign.Ed25519PrivateKey.generate()
        document = aroki_sign.signed({"connectors": [], "name": "t", "publicKey": aroki_sign.b64(
            aroki_sign.public_bytes(key.public_key())), "schemaVersion": 1}, key)
        tampered = dict(document, name="changed")
        public = key.public_key()
        public.verify(aroki_sign.base64.b64decode(document["signature"]), aroki_sign.canonical(document))
        try:
            public.verify(aroki_sign.base64.b64decode(document["signature"]), aroki_sign.canonical(tampered))
            raise AssertionError("tampered document verified")
        except aroki_sign.InvalidSignature:
            pass
    print("PASS: signing scheme matches kas021's Aroki-trusted index and artwork")


if __name__ == "__main__":
    sys.exit(main())
