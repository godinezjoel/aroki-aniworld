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
    manifest["operations"]["discovery"]["sections"] = discovery_sections(base, section_title)
    manifest["releaseNotes"] = notes
    return manifest


def discovery_sections(base: dict, home_title: str) -> list[dict]:
    """Home rows: new and popular list pages, then the full front page.

    All rows reuse the accepted front-page section; only id, title, semantic
    and URL change. The item selector matches AniWorld's cover cards on /neu
    and /beliebte-animes as well as on the front page.
    """
    home = base["operations"]["discovery"]["sections"][0]
    rows = []
    for row_id, title, semantic, path in (
        ("new", "Neu auf AniWorld", "recent", "/neu"),
        ("popular", "Beliebt auf AniWorld", "popular", "/beliebte-animes"),
        ("home", home_title, "all", "/"),
    ):
        row = copy.deepcopy(home)
        row["id"], row["title"], row["semantic"] = row_id, title, semantic
        row["request"]["urlTemplate"] = "https://aniworld.to" + path
        rows.append(row)
    return rows


def build_english_dub(base: dict) -> dict:
    """English Dub only, from kas021's AnimeGG 1.1.1 (per-episode Sub/Dub, MP4 via vidcache)."""
    manifest = copy.deepcopy(base)
    manifest["id"] = manifest["familyID"] = "animegg-english-dub"
    manifest["name"] = "AnimeGG English Dub"
    manifest["version"] = "1.0.0"
    manifest["releaseTrack"] = "beta"
    manifest["attribution"]["author"] = "godinezjoel"
    manifest["authorization"] = {
        "basis": "personal",
        "note": "Experimental declarative connector. Use only content you are entitled to access; "
                "no third-party content or distribution rights are supplied.",
    }
    episodes = manifest["operations"]["episodes"]["extract"]
    episodes["collection"] = "ul.newmanga > li > div:has(span.btn-dubbed)"
    variants = episodes["fields"]["availableVariants"]
    variants["collection"] = "span.btn-dubbed"
    variants["transforms"] = [
        {"op": "lowercased"},
        {"op": "replaceFirst", "find": "dubbed", "with": "dub"},
    ]
    manifest["operations"]["streams"]["variants"] = ["dub"]
    manifest["releaseNotes"] = (
        "English Dub from AnimeGG. Lists only episodes AnimeGG marks as dubbed and plays the English "
        "audio track. Use AniWorld Deutsch for German Dub and AniWorld OmU for subtitles."
    )
    return manifest


def main() -> None:
    base = json.loads(Path(sys.argv[1]).read_bytes())
    if base.get("version") != "0.3.2" or base.get("id") != "aniworld-expansion":
        raise SystemExit("expected the kas021 aniworld-expansion 0.3.2 manifest as template")
    animegg = json.loads((ROOT / "templates" / "animegg-1.1.1.json").read_bytes())
    if animegg.get("version") != "1.1.1" or animegg.get("id") != "animegg":
        raise SystemExit("expected the kas021 animegg 1.1.1 manifest in templates/")

    connectors = [
        build(
            base,
            connector_id="aniworld-deutsch",
            name="AniWorld Deutsch",
            version="1.1.0",
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
            version="1.1.0",
            language="mul",
            variant="sub",
            order=["de-sub", "en-sub"],
            section_title="AniWorld OmU",
            notes=(
                "Original audio (mostly Japanese) with German subtitles, English-subtitle fallback. "
                "Use AniWorld Deutsch for German Dub. Streams via Vidmoly."
            ),
        ),
        build_english_dub(animegg),
    ]
    for manifest in connectors:
        path = ROOT / "connectors" / manifest["id"] / "connector.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        print(f"WROTE: {path.relative_to(ROOT)} ({manifest['version']})")


if __name__ == "__main__":
    main()
