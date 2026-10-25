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
- genre sections: semantic "genre" with pageParam pagination (AniKoto 0.3.x)

Temporary Find a Niche test connectors (aniworld-test-a ... -d) are copies of
aniworld-deutsch, each declaring genres in one candidate way; see NICHE_TESTS.

Usage: py scripts/generate_connectors.py templates/aniworld-0.3.2.json
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANG_KEYS = {"de-dub": "1", "en-sub": "2", "de-sub": "3"}

# Main genres from AniWorld's own genre list (front page, ul.homeContentGenresList),
# in the site's order and spelling. Left out: language tags (Ger, GerSub, EngSub),
# adult or content flags, compound sub-genres (Actiondrama, Romantische Komoedie,
# ...) and genres with only a handful of titles.
# Genre pages list 30 titles per page, alphabetically, at /genre/<slug>/<page>;
# a page past the last one is HTTP 404. maxPages is the genre's page count on
# 2026-10-25, capped at 25 (the largest maxPages in an accepted manifest), so the
# app never asks for a page that does not exist.
GENRES = (
    ("abenteuer", "Abenteuer", 23),
    ("action", "Action", 25),
    ("alltagsleben", "Alltagsleben", 25),
    ("drama", "Drama", 25),
    ("fantasy", "Fantasy", 25),
    ("horror", "Horror", 5),
    ("komoedie", "Komödie", 25),
    ("mecha", "Mecha", 4),
    ("mystery", "Mystery", 11),
    ("romanze", "Romanze", 25),
    ("scifi", "Scifi", 16),
    ("sport", "Sport", 5),
)

# --- Temporary Find a Niche test connectors -------------------------------------
# AROKI's Find a Niche says "This collection has not declared genre metadata yet"
# for AniWorld Deutsch 1.4.0 (genre sections) and AnimeGG (details genres only).
# Each test connector is a copy of aniworld-deutsch with the 12 genre sections
# dropped, a paged All list, and one candidate genre declaration.
#
# All list: /genre/ger/<page> is AniWorld's German Dub list, alphabetical, 30 cards
# per page with posters; 35 pages (1034 titles) on 2026-10-25, page 36 is HTTP 404.
# maxPages 25 (the largest in an accepted manifest) reaches 750 titles, # to "S".
ALL_LIST = ("https://aniworld.to/genre/ger/{page}", 25)
# Every AniWorld list card (/neu, /beliebte-animes, /genre/..., /katalog/...) names
# its main genre in <small>, e.g. <small>Abenteuer</small>. One value per card,
# never padded with whitespace, so no transform: exactly the {collection} shape of
# AniKage 0.3.0's items.metadata.genres.
CARD_GENRE = {"collection": "small"}
# Title pages list all genres (plus the language tags Ger, GerSub, EngSub).
# Shape of kas021's details genres (DonghuaWorld, AniKoto).
DETAILS_GENRES = {"collection": "div.genres li a[itemprop=genre]"}
# letter, what it declares (for the release notes), item metadata, item field, details
NICHE_TESTS = (
    ("a", "each Browse item's main genre as items.metadata.genres (the shape of kas021's "
          "AniKage 0.3.0 and DonghuaWorld 1.1.1)", True, False, False),
    ("b", "each Browse item's main genre as an item field, items.fields.genres", False, True, False),
    ("c", "each Browse item's main genre as items.metadata.genres, plus all genres of the title "
          "page as details genres", True, False, True),
    ("d", "no item genres; all genres of the title page as details genres together with a paged "
          "All catalogue (only already-accepted keys)", False, False, True),
)


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
    manifest["operations"]["search"] = search_with_posters(base)
    manifest["operations"]["discovery"]["sections"] = discovery_sections(base, section_title)
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


def discovery_sections(base: dict, home_title: str) -> list[dict]:
    """Home rows (new, popular, front page), then one Browse section per genre.

    All sections reuse the accepted front-page section; only id, title, semantic,
    URL and pagination values change. The item selector matches AniWorld's cover
    cards on /neu, /beliebte-animes, /genre/<slug>/<page> and the front page, so
    every section yields the same sourceID (the /anime/stream/<slug> slug).
    /neu and /beliebte-animes are single pages; genre pages paginate.
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
    for slug, title, max_pages in GENRES:
        row = copy.deepcopy(home)
        row["id"], row["title"], row["semantic"] = f"genre-{slug}", title, "genre"
        row["request"]["urlTemplate"] = f"https://aniworld.to/genre/{slug}/{{page}}"
        row["pagination"] = {"type": "pageParam", "start": 1, "maxPages": max_pages}
        rows.append(row)
    return rows


def niche_sections(deutsch: dict) -> list[dict]:
    """Neu and Beliebt as in aniworld-deutsch, then a paged All list instead of the front page."""
    rows = {row["id"]: row for row in deutsch["operations"]["discovery"]["sections"]}
    all_row = copy.deepcopy(rows["home"])
    all_row["id"], all_row["title"] = "all", "Alle Animes mit German Dub"
    url, max_pages = ALL_LIST
    all_row["request"]["urlTemplate"] = url
    all_row["pagination"] = {"type": "pageParam", "start": 1, "maxPages": max_pages}
    return [copy.deepcopy(rows["new"]), copy.deepcopy(rows["popular"]), all_row]


def build_niche_test(deutsch: dict, letter: str, declares: str, *, item_metadata: bool,
                     item_field: bool, details_genres: bool) -> dict:
    """Temporary copy of aniworld-deutsch with one candidate genre declaration."""
    manifest = copy.deepcopy(deutsch)
    manifest["id"] = manifest["familyID"] = f"aniworld-test-{letter}"
    manifest["name"] = f"AniWorld Test {letter.upper()}"
    manifest["version"] = "0.1.0"
    sections = niche_sections(deutsch)
    for row in sections:
        if item_metadata:
            row["items"]["metadata"] = {"genres": copy.deepcopy(CARD_GENRE)}
        if item_field:
            row["items"]["fields"]["genres"] = copy.deepcopy(CARD_GENRE)
    manifest["operations"]["discovery"]["sections"] = sections
    if details_genres:
        manifest["operations"]["details"]["extract"]["genres"] = copy.deepcopy(DETAILS_GENRES)
    manifest["releaseNotes"] = (
        f"TEMPORARY TEST, will be removed. Find a Niche test {letter.upper()}: declares {declares}. "
        f"Browse All pages through AniWorld's German Dub list ({ALL_LIST[1]} pages). "
        "Playback, search and details as AniWorld Deutsch 1.4.0."
    )
    return manifest


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
            version="1.4.0",
            language="de",
            variant="dub",
            order=["de-dub", "de-sub", "en-sub"],
            section_title="AniWorld Deutsch",
            notes=(
                "German Dub first. If an episode has no German audio, playback falls back to "
                "Japanese audio with German subtitles, then English subtitles. Streams via Vidmoly. "
                "Search shows posters; Browse has AniWorld's popular titles and main genres."
            ),
        ),
        build(
            base,
            connector_id="aniworld-omu",
            name="AniWorld OmU",
            version="1.4.0",
            language="mul",
            variant="sub",
            order=["de-sub", "en-sub"],
            section_title="AniWorld OmU",
            notes=(
                "Original audio (mostly Japanese) with German subtitles, English-subtitle fallback. "
                "Use AniWorld Deutsch for German Dub. Streams via Vidmoly. "
                "Search shows posters; Browse has AniWorld's popular titles and main genres."
            ),
        ),
        build_english_dub(animegg),
    ]
    connectors += [
        build_niche_test(connectors[0], letter, declares, item_metadata=metadata,
                         item_field=field, details_genres=details)
        for letter, declares, metadata, field, details in NICHE_TESTS
    ]
    for manifest in connectors:
        path = ROOT / "connectors" / manifest["id"] / "connector.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        print(f"WROTE: {path.relative_to(ROOT)} ({manifest['version']})")


if __name__ == "__main__":
    main()
