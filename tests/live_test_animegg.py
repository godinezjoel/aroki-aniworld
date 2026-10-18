#!/usr/bin/env python3
"""Approximate the AnimeGG English Dub manifest against the live site.

Interprets the manifest's own selectors, templates and transforms with
BeautifulSoup. Not the native Aroki engine: only the app can confirm playback.

Usage: py tests/live_test_animegg.py connectors/animegg-english-dub/connector.json "query" ...
"""

import json
import re
import sys
import urllib.parse
import urllib.request
import warnings

import soupsieve
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
ops = manifest["operations"]
allowed = manifest["allowedHosts"]
ok = True


def host_allowed(url):
    host = urllib.parse.urlsplit(url).hostname
    return any(host == h or (h.startswith("*.") and host.endswith(h[1:])) for h in allowed)


def fetch(url, headers=None, extra=None):
    assert host_allowed(url), f"host not allowed: {url}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {}), **(extra or {})})
    response = urllib.request.urlopen(req, timeout=30)
    assert host_allowed(response.geturl()), f"redirected outside allowedHosts: {response.geturl()}"
    return response


def html(request, values):
    url = request["urlTemplate"]
    for key, value in values.items():
        url = url.replace("{" + key + "}", urllib.parse.quote(value, safe="/-"))
    response = fetch(url, request.get("headers"))
    return response.geturl(), BeautifulSoup(response.read().decode("utf-8", "replace"), "html.parser")


def transform(value, transforms, base):
    for t in transforms or []:
        if value is None:
            return None
        op = t["op"]
        if op == "removePrefix":
            value = value[len(t["value"]):] if value.startswith(t["value"]) else value
        elif op == "trim":
            value = value.strip()
        elif op == "lowercased":
            value = value.lower()
        elif op == "replaceFirst":
            value = value.replace(t["find"], t["with"], 1)
        elif op == "firstInteger":
            m = re.search(r"\d+", value)
            value = m.group(0) if m else None
        elif op == "absolutize":
            value = urllib.parse.urljoin(base, value)
        else:
            raise SystemExit(f"unhandled transform {op}")
    return value


def field(node, rule, base, variant=""):
    if "collection" in rule:
        return [transform(el.get_text(" ", strip=True), rule.get("transforms"), base)
                for el in node.select(rule["collection"])]
    selector = rule["selector"].replace("{variant}", variant)
    el = node if (node.name and soupsieve.match(selector, node)) else node.select_one(selector)
    if el is None:
        return None
    raw = el.get(rule["attr"]) if rule.get("part") == "attr" else el.get_text(" ", strip=True)
    return transform(raw, rule.get("transforms"), base)


def check(cond, label):
    global ok
    print(("  PASS " if cond else "  FAIL ") + label)
    ok = ok and bool(cond)


for section in ops["discovery"]["sections"]:
    base, doc = html(section["request"], {})
    items = doc.select(section["items"]["collection"])
    check(items, f"discovery {section['id']}: {len(items)} items")

for query in sys.argv[2:]:
    print(f"\n=== {query!r}")
    base, doc = html(ops["search"]["request"], {"query": query})
    hits = [{k: field(item, r, base) for k, r in ops["search"]["items"]["fields"].items()}
            for item in doc.select(ops["search"]["items"]["collection"])]
    check(hits, f"search: {len(hits)} result(s), first {hits[0]['title'] if hits else None!r}")
    if not hits:
        continue
    title_id = hits[0]["sourceID"]
    base, doc = html(ops["details"]["request"], {"titleID": title_id})
    check(field(doc, ops["details"]["extract"]["title"], base), f"details for {title_id}")
    base, doc = html(ops["episodes"]["request"], {"titleID": title_id})
    rule = ops["episodes"]["extract"]
    episodes = [{k: field(item, r, base) for k, r in rule["fields"].items()} for item in doc.select(rule["collection"])]
    all_rows = len(doc.select(rule["collection"].split(":has(")[0]))
    check(all(e["availableVariants"] == ["dub"] for e in episodes),
          f"episodes: {len(episodes)} dubbed of {all_rows} listed on the site, all tagged ['dub']")
    if not episodes:
        print("  (no English dub for this title; nothing listed)")
        continue
    episode = episodes[0]
    context = {"episodeID": episode["episodeID"]}
    url = None
    for step in ops["streams"]["steps"]:
        base, doc = html(step["request"], context)
        extract = step["extract"]
        if "context" in extract:
            for name, r in extract["context"].items():
                context[name] = field(doc, r, base, variant="dub")
            check(all(context.values()), f"E{episode['episodeNumber']} dub embed: {context}")
            if not all(context.values()):
                break
        else:
            url = field(doc, extract["fields"]["url"], base)
    if url:
        response = fetch(url, ops["streams"].get("playbackHeaders"), {"Range": "bytes=0-15"})
        head = response.read(12)
        check(response.status in (200, 206) and b"ftyp" in head,
              f"media {response.status} {response.headers.get('Content-Type')} from "
              f"{urllib.parse.urlsplit(response.geturl()).hostname}")

print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
