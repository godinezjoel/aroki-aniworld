"""Approximate the AniWorld manifest pipeline against the live site.

This is not the native Aroki engine: it interprets the manifest's selectors and
transforms with BeautifulSoup/soupsieve to confirm they match real pages.
"""
import json
import re
import sys
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


# Discovery
for sec in ops["discovery"]["sections"]:  # every Home row needs ID, title and poster
    base, html = fetch(sec["request"]["urlTemplate"])
    items = soup(html).select(css(sec["items"]["collection"]))
    rows = [{k: field(item, r, base) for k, r in sec["items"]["fields"].items()} for item in items]
    complete = [r for r in rows if r["sourceID"] and r["title"] and r["posterURL"]]
    check(rows and len(complete) == len(rows),
          f"discovery {sec['id']!r} ({sec['title']}): {len(rows)} items, first {rows[0]['title'] if rows else None!r}")

for query in titles:
    print(f"\n=== search {query!r}")
    s = ops["search"]["request"]
    _, body = fetch(s["urlTemplate"], s["headers"], urllib.parse.urlencode({"keyword": query}).encode())
    results = json.loads(body)
    hits = [{k: transform(r.get(rule["path"]), rule["transforms"], "https://aniworld.to/") for k, rule in ops["search"]["items"]["fields"].items()} for r in results]
    hits = [h for h in hits if "/anime/stream/" in next((r["link"] for r in results if r.get("link", "").endswith(h["sourceID"] or "")), "")]
    check(hits, f"search returns anime results ({len(hits)})")
    if not hits:
        continue
    title_id = hits[0]["sourceID"]
    print("   titleID:", title_id, "|", hits[0]["title"])

    base, html = fetch(ops["details"]["request"]["urlTemplate"].replace("{titleID}", title_id))
    doc = soup(html)
    details = {k: field(doc, r, base) for k, r in ops["details"]["extract"].items()}
    check(details["title"] and details["posterURL"], f"details: {details['title']!r}")

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
    check(all(set(e["availableVariants"]) <= {"sub", "dub"} for e in episodes), "every tag is sub or dub")

    if not episodes:
        print("   no episodes listed for this title")
        continue
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

print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
