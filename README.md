# AniWorld Deutsch for AROKI

A signed AROKI collection with two AniWorld video connectors. German Dub is
the priority; Japanese audio with subtitles is the fallback.

| Connector | ID | Plays |
|---|---|---|
| **AniWorld Deutsch** | `aniworld-deutsch` | German Dub first. If an episode has no German audio, falls back to Japanese audio with German subtitles, then English subtitles. |
| **AniWorld OmU** | `aniworld-omu` | Original audio (mostly Japanese) with German subtitles, English-subtitle fallback. |
| **AnimeGG English Dub** | `animegg-english-dub` | English Dub only. Lists only episodes AnimeGG marks as dubbed. Use it when an episode has no German Dub. |

AniWorld itself has no English Dub (its English option is Japanese audio with
English subtitles), so English Dub comes from AnimeGG. That connector is
derived from kas021's Aroki-accepted AnimeGG `1.1.1` manifest
(`templates/animegg-1.1.1.json`) with value-only changes, and works on any
AROKI version. AnimeGG often lists titles under their Japanese names
(for example *Ore dake Level Up na Ken* for Solo Leveling); searching the
English name usually still finds them.

The AniWorld connectors require AROKI `2.0.36` or newer. They are derived from the AniWorld
`0.3.2` manifest published in
[kas021/AROKI-Connectors](https://github.com/kas021/AROKI-Connectors) and use
only keys from that manifest, because AROKI rejects unknown manifest keys
(for example `availableVariants` inside episode panels). Streams resolve
through AniWorld's Vidmoly mirror; other AniWorld hosters need executable
code and cannot be described declaratively.

AniWorld Deutsch labels every episode as Dub. Episodes without German audio
still play, using the subtitle fallback.

Both AniWorld connectors share the same discovery and search. Their search
and genre sections reuse shapes from two other Aroki-accepted kas021
manifests, AniPM and AniKoto, with values changed only:

- **Home rows:** Neu auf AniWorld (`/neu`), Beliebt auf AniWorld
  (`/beliebte-animes`, `semantic: popular`) and the front page.
- **Browse genres:** twelve main AniWorld genres (`semantic: genre`), paged
  through `/genre/<slug>/<page>`, 30 titles per page in AniWorld's alphabetical
  order. The list and per-genre page limits are `GENRES` in
  `scripts/generate_connectors.py`. A limit is the genre's page count, at most
  25, because pages past the last one return HTTP 404; the largest genres
  therefore end partway through the alphabet (Action and Komödie around K).
- **Search:** `/ajax/seriesSearch`, the endpoint behind AniWorld's own header
  search. It returns series only (no episodes, voice actors or forum posts),
  each with a poster, up to 15 hits.

## Add it in AROKI

1. **Profile → Sources → Add verified repository**.
2. Enter `godinezjoel/aroki-aniworld` and tap **Add verified sources**.
3. Check the signing key AROKI shows against this collection's key:
   - `publicKey`: `3ZGNhvnQ1GGtYG0p31WlnPURvjJN719BEVE+/uMUlmc=`
   - SHA-256 fingerprint (first 128 bits): `7FB9:3B20:4E5D:F07E:524D:E752:1DB4:384C`
4. Choose **AniWorld Deutsch** (or **AniWorld OmU**) as the active source.

If your build only offers a URL field, use
`https://raw.githubusercontent.com/godinezjoel/aroki-aniworld/main/index.json`.

## Repository layout

- `connectors/<id>/connector.json`: editable source manifest.
- `connectors/<id>/releases/<sha256>/connector.json`: immutable published copy
  that `index.json` points to. Never edit or delete published releases.
- `index.json`: signed collection index (`publicKey`, per-manifest
  `signature`, document `signature`).
- `artwork.json` + `logos/`: signed optional logo sidecar.
- `collection.json`: repository ID, name, connector order and logos.
- `templates/aniworld-0.3.2.json`: the accepted kas021 manifest used as the
  structural template.

## Signing scheme

Same as kas021/AROKI-Connectors, checked by `tests/test_signing_scheme.py`
against kas021's published index:

- Manifest signature: Ed25519 over the manifest file's exact bytes.
- Index and artwork signature: Ed25519 over the document without its
  `signature` field, as compact JSON with sorted keys and unescaped slashes.

The private key lives outside the repository at
`%USERPROFILE%\.aroki\aniworld-signing-key.pem`. **Back it up.** If it is lost,
a new key must be generated and AROKI will ask you to trust the new key.

## Making a change (Windows)

```powershell
py -m pip install -r requirements.txt
# edit scripts/generate_connectors.py (or connectors/<id>/connector.json), then:
py scripts/generate_connectors.py templates/aniworld-0.3.2.json
# bump "version" for every changed connector before publishing
py scripts/validate_connector.py aniworld-deutsch
py scripts/validate_connector.py aniworld-omu
py scripts/validate_connector.py animegg-english-dub
py tests/live_test.py connectors/aniworld-deutsch/connector.json "one punch man"
py tests/live_test_animegg.py connectors/animegg-english-dub/connector.json "solo leveling"
py scripts/aroki_sign.py publish
git add -A
git commit -m "Publish AniWorld update"
git push
```

`py tests/live_test.py` approximates the manifest against the live site with
BeautifulSoup. It is not the native AROKI engine: only the app can confirm
that a manifest is accepted and plays.

Use only content you are entitled to access.
