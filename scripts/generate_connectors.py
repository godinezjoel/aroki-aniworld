#!/usr/bin/env python3
"""Generate the AniWorld connector sources from the Aroki-accepted 0.3.2 manifest.

Aroki rejects unknown keys, so both connectors keep the exact key structure of
the published kas021 AniWorld 0.3.2 manifest and only change values:

- aniworld-deutsch: German Dub first; falls back to German-subtitle and then
  English-subtitle mirrors when an episode has no German audio.
- aniworld-omu:     Original audio with German subtitles, English fallback.

AniWorld hoster language keys: 1 = German audio, 2 = English subtitles,
3 = German subtitles.

Usage: py scripts/generate_connectors.py templates/aniworld-0.3.2.json
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANG_KEYS = {"de-dub": "1", "en-sub": "2", "de-sub": "3"}


def vidmoly_mirror(template: dict, lang_key: str, variant: str) -> dict:
    mirror = copy.deepcopy(template)
    mirror["variants"] = [variant]
    mirror["steps"][0]["extract"]["context"]["embed"]["selector"] = (
        f"li[data-lang-key='{lang_key}'][data-link-target]:has(h4:contains(Vidmoly))"
    )
    return mirror


def build(base: dict, *, connector_id: str, name: str, version: str, language: str,
          variant: str, order: list[str], section_title: str, notes: str) -> dict:
    manifest = copy.deepcopy(base)
    manifest["id"] = manifest["familyID"] = connector_id
    manifest["name"] = name
    manifest["version"] = version
    manifest["language"] = language
    manifest["operations"]["episodes"]["panels"]["variant"] = {"literal": variant}
    template = base["operations"]["streams"]["mirrors"][0]
    manifest["operations"]["streams"]["mirrors"] = [
        vidmoly_mirror(template, LANG_KEYS[key], variant) for key in order
    ]
    manifest["operations"]["discovery"]["sections"][0]["title"] = section_title
    manifest["releaseNotes"] = notes
    return manifest


def main() -> None:
    base = json.loads(Path(sys.argv[1]).read_bytes())
    if base.get("version") != "0.3.2" or base.get("id") != "aniworld-expansion":
        raise SystemExit("expected the kas021 aniworld-expansion 0.3.2 manifest as template")

    connectors = [
        build(
            base,
            connector_id="aniworld-deutsch",
            name="AniWorld Deutsch",
            version="1.0.0",
            language="de",
            variant="dub",
            order=["de-dub", "de-sub", "en-sub"],
            section_title="AniWorld Deutsch",
            notes=(
                "German Dub first. If an episode has no German audio, playback falls back to "
                "Japanese audio with German subtitles, then English subtitles. Streams via Vidmoly."
            ),
        ),
        build(
            base,
            connector_id="aniworld-omu",
            name="AniWorld OmU",
            version="1.0.0",
            language="mul",
            variant="sub",
            order=["de-sub", "en-sub"],
            section_title="AniWorld OmU",
            notes=(
                "Original audio (mostly Japanese) with German subtitles, English-subtitle fallback. "
                "Use AniWorld Deutsch for German Dub. Streams via Vidmoly."
            ),
        ),
    ]
    for manifest in connectors:
        path = ROOT / "connectors" / manifest["id"] / "connector.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        print(f"WROTE: {path.relative_to(ROOT)} ({manifest['version']})")


if __name__ == "__main__":
    main()
