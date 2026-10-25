#!/usr/bin/env python3
"""Generate the AniWorld connector sources from the Aroki-accepted 0.3.2 manifest.

Aroki rejects unknown keys, so both connectors keep the exact key structure of
the published kas021 AniWorld 0.3.2 manifest and only change values:

- aniworld-deutsch: German Dub first; falls back to German-subtitle and then
  English-subtitle mirrors when an episode has no German audio.
- aniworld-omu:     Original audio with German subtitles, English fallback.

AniWorld hoster language keys: 1 = German audio, 2 = English subtitles,
3 = German subtitles.

Shapes taken from other Aroki-accepted kas021 manifests (values changed only):
- search: GET JSON search with a posterURL path + absolutize (AniPM 0.1.2)
- paged All list: pageParam pagination (AniKoto 0.3.x)
- item genres: items.metadata.genres (AniKage 0.3.0)
- title genres: operations.details.extract.genres (DonghuaWorld, AniKoto)

Item and title genres together are what AROKI's Find a Niche accepted as
"declared genre metadata" (test connector C, 2026-10-25).

Usage: py scripts/generate_connectors.py templates/aniworld-0.3.2.json
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANG_KEYS = {"de-dub": "1", "en-sub": "2", "de-sub": "3"}

# All lists: AniWorld's language lists, alphabetical, 30 cards per page with
# posters, at /genre/<slug>/<page>; a page past the last one is HTTP 404. maxPages
# 25 is the largest in an accepted manifest. On 2026-10-25:
# - ger (German Dub): 35 pages, 1034 titles; 25 pages reach # to "S".
# - gersub (German subtitles): 78 pages; 25 pages reach # to "G".
ALL_GERMAN_DUB = ("https://aniworld.to/genre/ger/{page}", 25)
ALL_GERMAN_SUB = ("https://aniworld.to/genre/gersub/{page}", 25)
# Every AniWorld list card (/neu, /beliebte-animes, /genre/..., /katalog/...) names
# its main genre in <small>, e.g. <small>Abenteuer</small>. One value per card,
# never padded with whitespace, so no transform: exactly the {collection} shape of
# AniKage 0.3.0's items.metadata.genres. A handful of new GerSub titles carry the
# language tag "GerSub" as main genre until AniWorld assigns one; none in ger.
CARD_GENRE = {"collection": "small"}
# Title pages list all genres plus the language tags Ger, GerSub and EngSub, which
# link to /genre/ger, /genre/gersub and /genre/engsub. No other genre slug starts
# with "ger" or "engsub", and :not([href*=...]) is an accepted selector form.
DETAILS_GENRES = {
    "collection": "div.genres li a[itemprop=genre]"
                  ":not([href*='/genre/ger']):not([href*='/genre/engsub'])"
}


def vidmoly_mirror(template: dict, lang_key: str, variant: str) -> dict:
    mirror = copy.deepcopy(template)
    mirror["variants"] = [variant]
    mirror["steps"][0]["extract"]["context"]["embed"]["selector"] = (
        f"li[data-lang-key='{lang_key}'][data-link-target]:has(h4:contains(Vidmoly))"
    )
    return mirror


def build(base: dict, *, connector_id: str, name: str, version: str, language: str,
          variant: str, order: list[str], all_title: str, all_list: tuple[str, int],
          notes: str) -> dict:
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
    manifest["operations"]["search"] = search_with_posters(base)
    manifest["operations"]["discovery"]["sections"] = discovery_sections(base, all_title, all_list)
    manifest["operations"]["details"]["extract"]["genres"] = copy.deepcopy(DETAILS_GENRES)
    manifest["releaseNotes"] = notes
    return manifest


def search_with_posters(base: dict) -> dict:
    """Search through /ajax/seriesSearch, the endpoint of AniWorld's own header search.

    Unlike the POST /ajax/search of 0.3.2, it returns only series (no episodes,
    actors or forum posts) and includes each series' cover. Same response format
    (it answers [] for no match); GET request shaped like AniKoto's and AniPM's.
    """
    search = copy.deepcopy(base["operations"]["search"])
    request = search["request"]
    request["method"] = "GET"
    request["urlTemplate"] = "https://aniworld.to/ajax/seriesSearch?keyword={query}"
    del request["formFields"]
    fields = search["items"]["fields"]
    fields["title"]["path"] = "name"
    fields["posterURL"] = {"path": "cover", "transforms": [{"op": "absolutize"}]}
    return search


def discovery_sections(base: dict, all_title: str, all_list: tuple[str, int]) -> list[dict]:
    """Neu, Beliebt and a paged All list, each item with its main genre.

    All sections reuse the accepted front-page section; only id, title, semantic,
    URL and pagination values change, plus the item genres. The item selector
    matches AniWorld's cover cards on /neu, /beliebte-animes and /genre/<slug>/<page>,
    so every section yields the same sourceID (the /anime/stream/<slug> slug).
    /neu and /beliebte-animes are single pages; the All list paginates.
    """
    home = base["operations"]["discovery"]["sections"][0]
    url, max_pages = all_list
    rows = []
    for row_id, title, semantic, url_template in (
        ("new", "Neu auf AniWorld", "recent", "https://aniworld.to/neu"),
        ("popular", "Beliebt auf AniWorld", "popular", "https://aniworld.to/beliebte-animes"),
        ("all", all_title, "all", url),
    ):
        row = copy.deepcopy(home)
        row["id"], row["title"], row["semantic"] = row_id, title, semantic
        row["request"]["urlTemplate"] = url_template
        if semantic == "all":
            row["pagination"] = {"type": "pageParam", "start": 1, "maxPages": max_pages}
        row["items"]["metadata"] = {"genres": copy.deepcopy(CARD_GENRE)}
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
            version="1.5.0",
            language="de",
            variant="dub",
            order=["de-dub", "de-sub", "en-sub"],
            all_title="Alle Animes mit German Dub",
            all_list=ALL_GERMAN_DUB,
            notes=(
                "German Dub first. If an episode has no German audio, playback falls back to "
                "Japanese audio with German subtitles, then English subtitles. Streams via Vidmoly. "
                "Search shows posters. Browse All lists AniWorld's German Dub titles (750, # to S), "
                "and every title declares its genres for Find a Niche."
            ),
        ),
        build(
            base,
            connector_id="aniworld-omu",
            name="AniWorld OmU",
            version="1.5.0",
            language="mul",
            variant="sub",
            order=["de-sub", "en-sub"],
            all_title="Alle Animes mit deutschen Untertiteln",
            all_list=ALL_GERMAN_SUB,
            notes=(
                "Original audio (mostly Japanese) with German subtitles, English-subtitle fallback. "
                "Use AniWorld Deutsch for German Dub. Streams via Vidmoly. Search shows posters. "
                "Browse All lists AniWorld's German-subtitle titles (750, # to G), and every title "
                "declares its genres for Find a Niche."
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
