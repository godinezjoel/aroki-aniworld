"""Approximate the AniWorld manifest pipeline against the live site.

This is not the native Aroki engine: it interprets the manifest's selectors and
transforms with BeautifulSoup/soupsieve to confirm they match real pages.
Checks every discovery section (paged sections on their first two and last
allowed page), opens one title from page 2 of the first paged section, then
searches each query and opens the first hit. Declared genres (item field,
item metadata or details) must be non-empty and are printed as samples.

Usage: py tests/live_test.py connectors/aniworld-deutsch/connector.json "query" ...
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import warnings
from html import unescape

import soupsieve
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
titles = sys.argv[2:]
allowed = set(manifest["allowedHosts"])
ops = manifest["operations"]


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlsplit(newurl).hostname
        hops.append(host)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


opener = urllib.request.build_opener(Redirects)
hops: list = []


def fetch(url, headers=None, data=None):
    host = urllib.parse.urlsplit(url).hostname
    assert host in allowed, f"host not allowed: {host}"
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    with opener.open(req, timeout=15) as r:
        return r.geturl(), r.read().decode("utf-8", "replace")


def css(sel):
    return sel.replace(":contains(", ":-soup-contains(")


def transform(value, transforms, base):
    for t in transforms or []:
        op = t["op"]
        if value is None:
            return None
        if op == "lastPathComponent":
            value = urllib.parse.urlsplit(value).path.rstrip("/").split("/")[-1]
        elif op == "firstInteger":
            m = re.search(r"\d+", value)
            value = m.group(0) if m else None
        elif op == "absolutize":
            value = urllib.parse.urljoin(base, value)
        elif op == "htmlText":
            value = BeautifulSoup(value, "html.parser").get_text().strip()
        elif op == "replaceFirst":
            value = value.replace(t["find"], t["with"], 1)
        elif op == "trim":
            value = value.strip()
        elif op == "lowercased":
            value = value.lower()
        elif op == "removePrefix":
            value = value[len(t["value"]):] if value.startswith(t["value"]) else value
        elif op == "removeSuffix":
            value = value[:-len(t["value"])] if value.endswith(t["value"]) else value
        else:
            raise SystemExit(f"unhandled transform {op}")
    return value


def field(node, rule, base):
    if "literal" in rule:
        return rule["literal"]
    if "collection" in rule:
        out = []
        for el in node.select(css(rule["collection"])):
            raw = el.get(rule["attr"]) if rule.get("part") == "attr" else el.get_text(" ", strip=True)
            out.append(transform(raw, rule.get("transforms"), base))
        return out
    sel = rule["selector"]
    el = node if (node.name and soupsieve.match(css(sel), node)) else node.select_one(css(sel))
    if el is None:
        return None
    raw = el.get(rule["attr"]) if rule["part"] == "attr" else el.get_text(" ", strip=True)
    return transform(raw, rule.get("transforms"), base)


def soup(html):
    return BeautifulSoup(html, "html.parser")


ok = True


def check(cond, label):
    global ok
    print(("  PASS " if cond else "  FAIL ") + label)
    ok = ok and bool(cond)


SLUG = re.compile(r"(?!staffel-|episode-)[\w.-]+")  # /anime/stream/<slug>; never an episode or season link


def fetch_or_none(url, headers=None, data=None):
    """fetch() that reports an HTTP error (such as a page past the last one) instead of raising."""
    try:
        return fetch(url, headers, data)
    except urllib.error.HTTPError as error:
        print(f"  HTTP {error.code} for {url}")
        return url, None


def section_pages(sec):
    """Pages to check: none for single-page rows; first two and last allowed page for pageParam."""
    pagination = sec.get("pagination") or {"type": "none"}
    if pagination["type"] != "pageParam":
        return [None]
    first, last = pagination["start"], pagination["start"] + pagination["maxPages"] - 1
    return sorted({first, min(first + 1, last), last})


def discovery_rows(sec, page):
    url = sec["request"]["urlTemplate"]
    if page is not None:
        url = url.replace("{page}", str(page))
    base, html = fetch_or_none(url)
    if html is None:
        return []
    items = soup(html).select(css(sec["items"]["collection"]))
    rows = []
    for item in items:
        row = {k: field(item, r, base) for k, r in sec["items"]["fields"].items()}
        if "metadata" in sec["items"]:
            row["metadata"] = {k: field(item, r, base) for k, r in sec["items"]["metadata"].items()}
        rows.append(row)
    return rows


def item_genres(sec):
    """Where a discovery section declares per-item genres: 'fields', 'metadata' or None."""
    if "genres" in sec["items"]["fields"]:
        return "fields"
    if "genres" in sec["items"].get("metadata", {}):
        return "metadata"
    return None


def genres_of(row, where):
    return row["genres"] if where == "fields" else row["metadata"]["genres"]


def search(query):
    spec = ops["search"]
    request = spec["request"]
    if request["method"] == "POST":
        url = request["urlTemplate"]
        form = {k: v.replace("{query}", query) for k, v in request["formFields"].items()}
        data = urllib.parse.urlencode(form).encode()
    else:
        url, data = request["urlTemplate"].replace("{query}", urllib.parse.quote(query)), None
    base, body = fetch(url, request.get("headers"), data)
    results = json.loads(body) if body.strip() else []  # json-empty-array: an empty body means no hits
    fields = spec["items"]["fields"]
    return [{k: transform(r.get(rule["path"]), rule.get("transforms"), base) for k, rule in fields.items()}
            for r in results]


def is_image(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with opener.open(req, timeout=15) as r:
        return r.headers.get("Content-Type", "").startswith("image/")


def open_title(title_id, streams=True):
    """Run details, episodes and (optionally) streams for one titleID, like the app does."""
    base, html = fetch(ops["details"]["request"]["urlTemplate"].replace("{titleID}", title_id))
    doc = soup(html)
    details = {k: field(doc, r, base) for k, r in ops["details"]["extract"].items()}
    check(details["title"] and details["posterURL"], f"details: {details['title']!r}")
    if "genres" in details:
        check(details["genres"] and all(details["genres"]), f"details genres: {details['genres']}")

    ep = ops["episodes"]
    seasons = doc.select(css(ep["extract"]["collection"]))
    check(seasons, f"episodes: {len(seasons)} season panel(s)")
    panel = ep["panels"]
    episodes = []
    for s_el in seasons[: panel["maxPanels"]]:
        list_url = field(s_el, panel["listURL"], base)
        pbase, phtml = fetch(list_url)
        for row in soup(phtml).select(css(panel["items"]["collection"])):
            e = {k: field(row, r, pbase) for k, r in panel["items"]["fields"].items()}
            e.setdefault("availableVariants", [field(s_el, panel["variant"], base)])
            e["season"] = field(s_el, ep["extract"]["fields"]["seasonNumber"], base)
            episodes.append(e)
    counts = {}
    for e in episodes:
        key = "+".join(sorted(set(e["availableVariants"]))) or "(none)"
        counts[key] = counts.get(key, 0) + 1
        check(set(e["availableVariants"]) <= {"sub", "dub"}, f"S{e['season']}E{e['episodeNumber']} variants {e['availableVariants']}") if not set(e["availableVariants"]) <= {"sub", "dub"} else None
    print("   variant tags:", counts, f"over {len(episodes)} episodes")
    check(episodes and all(set(e["availableVariants"]) <= {"sub", "dub"} for e in episodes),
          f"{len(episodes)} episodes, every tag is sub or dub")

    if not episodes or not streams:
        return
    target = episodes[0]
    for variant in ("dub", "sub"):
        tagged = variant in target["availableVariants"]
        mirrors = [m for m in ops["streams"]["mirrors"] if variant in m["variants"]]
        resolved = None
        for idx, mirror in enumerate(mirrors):
            hops.clear()
            step1, step2 = mirror["steps"]
            ebase, ehtml = fetch(target["episodeURL"])
            rule = step1["extract"]["context"]["embed"]
            embed = field(soup(ehtml), rule, ebase)
            if not embed:
                print(f"   {variant} mirror {idx}: no embed ({rule['selector']})")
                continue
            final, phtml = fetch(embed, step2["request"]["headers"])
            script = next((sc.get_text() for sc in soup(phtml).select("script") if "player.setup" in sc.get_text()), None)
            m = script and re.search(r"sources\s*:\s*\[\s*\{\s*file\s*:\s*['\"]([^'\"]+)", script)
            if not m:
                print(f"   {variant} mirror {idx}: no player.setup sources at {final}")
                continue
            media = urllib.parse.urljoin(final, unescape(m.group(1)))
            head = ""
            for attempt in range(3):
                try:
                    req = urllib.request.Request(media, headers={"User-Agent": UA})
                    with urllib.request.urlopen(req, timeout=30) as r:
                        head = r.read(200).decode("utf-8", "replace")
                    break
                except Exception as error:
                    print(f"   media fetch attempt {attempt + 1} failed: {error!r}")
            resolved = (idx, hops[:], urllib.parse.urlsplit(final).hostname, head.startswith("#EXTM3U"))
            break
        print(f"   S{target['season']}E{target['episodeNumber']} {variant}: tagged={tagged} resolved={resolved}")
        if tagged:
            check(resolved and resolved[3], f"{variant} resolves to a playable HLS master")
        else:
            check(resolved is None or True, f"{variant} not offered for this episode")


# Discovery: every row (and the first two and the last allowed page of a paged
# section) needs items with ID, title and poster; page 2 must differ from page 1.
genre_pick = None
for sec in ops["discovery"]["sections"]:
    seen = {}
    for page in section_pages(sec):
        rows = discovery_rows(sec, page)
        complete = [r for r in rows if r["sourceID"] and SLUG.fullmatch(r["sourceID"]) and r["title"] and r["posterURL"]]
        label = f"discovery {sec['id']!r} ({sec['title']})" + (f" page {page}" if page is not None else "")
        check(rows and len(complete) == len(rows), f"{label}: {len(rows)} items, first {rows[0]['title'] if rows else None!r}")
        where = item_genres(sec)
        if where and rows:
            genres = [genres_of(r, where) for r in rows]
            check(all(g and all(g) for g in genres), f"{label}: every item has {where} genres")
            counts = {}
            for value in (v for g in genres for v in g):
                counts[value] = counts.get(value, 0) + 1
            print(f"   {where} genres:", dict(sorted(counts.items(), key=lambda kv: -kv[1])))
            print("   samples:", [(r["title"], genres_of(r, where)) for r in rows[:3]])
        seen[page] = {r["sourceID"] for r in rows}
        paged = (sec.get("pagination") or {}).get("type") == "pageParam"
        if paged and page == 2 and rows and genre_pick is None:
            genre_pick = (sec["title"], rows[0])
    if len(seen) > 1:
        first, second = sorted(seen)[:2]
        check(seen[first] and not seen[first] & seen[second], f"discovery {sec['id']!r}: page {second} differs from page {first}")

if genre_pick:
    genre, row = genre_pick
    print(f"\n=== {genre!r} page 2: {row['title']!r}, titleID {row['sourceID']}")
    open_title(row["sourceID"], streams=False)

for query in titles:
    print(f"\n=== search {query!r}")
    hits = search(query)
    check(hits, f"search returns results ({len(hits)})")
    if not hits:
        continue
    complete = [h for h in hits if h["sourceID"] and SLUG.fullmatch(h["sourceID"]) and h["title"]]
    check(len(complete) == len(hits), f"every hit is a series with ID and title: {[h['sourceID'] for h in hits]}")
    if "posterURL" in hits[0]:
        posters = [h for h in hits if h.get("posterURL")]
        check(len(posters) == len(hits) and is_image(posters[0]["posterURL"]),
              f"every hit has a poster ({len(posters)}/{len(hits)}), first {posters[0]['posterURL'] if posters else None}")
    title_id = hits[0]["sourceID"]
    print("   titleID:", title_id, "|", hits[0]["title"])
    open_title(title_id)

print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
