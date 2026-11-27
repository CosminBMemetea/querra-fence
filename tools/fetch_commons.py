"""Openly licensed photos from Wikimedia Commons categories, with their author and licence, for real-image test sets.

    python3 tools/fetch_commons.py OUT --cat "Pasture electric fences" --cat "Electric fences by country" \
        --depth 3 --exclude border --exclude camp --width 1280

Walks the categories (subcategories to --depth), keeps photos (JPEG, PNG) whose licence is free to reuse (public
domain, CC0, CC BY, CC BY-SA), and saves each as a thumbnail --width pixels wide in OUT/images, with OUT/manifest.json:
per file the Commons page, author, licence and its URL, and the original size. CC BY and CC BY-SA require credit:
the manifest is that credit. Nothing is executed from the downloads; they are images only, checked by their header.

Categories and files whose title or description contains an --exclude word (case-insensitive) are skipped, and so
are files listed under "skipped" in the manifest (taken out by hand: they are never fetched again). The requests carry a generic
client name and are sequential, as Wikimedia's API etiquette asks.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://commons.wikimedia.org/w/api.php"
UA = "querra-fence-dataset-tool/0.1 (research)"
PAUSE = float(os.environ.get("COMMONS_PAUSE", 2.0))   # seconds before every request: one at a time, slowly
FREE = re.compile(r"^(public domain|pd\b|pd-|cc0|cc by(-sa)? [\d.]+|cc by(-sa)?$|cc-by(-sa)?-[\d.]+)", re.I)
MAGIC = {b"\xff\xd8\xff": ".jpg", b"\x89PNG": ".png"}


def fetch(url, tries=5, limit=None):
    """GET with a pause before each request, and the server's Retry-After (or a growing wait) on 429 and 5xx."""
    for k in range(tries):
        time.sleep(PAUSE)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                return r.read(limit) if limit else r.read()
        except urllib.error.HTTPError as e:
            if k == tries - 1 or (e.code != 429 and e.code < 500):
                raise
            wait = e.headers.get("Retry-After", "")
            wait = min(300, int(wait)) if wait.isdigit() else 30 * (k + 1)
            print("  HTTP %d, waiting %d s" % (e.code, wait), file=sys.stderr, flush=True)
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError):
            if k == tries - 1:
                raise
            time.sleep(10 * (k + 1))


def get(params):
    url = API + "?" + urllib.parse.urlencode(dict(params, format="json", formatversion=2, maxlag=5))
    for k in range(5):
        d = json.loads(fetch(url))
        if d.get("error", {}).get("code") != "maxlag":     # the servers are busy: wait, as the API asks
            return d
        time.sleep(5 * (k + 1))
    raise RuntimeError("Commons stayed busy (maxlag)")


def members(cat, kind):
    out, cont = [], {}
    while True:
        d = get(dict(action="query", list="categorymembers", cmtitle="Category:" + cat, cmtype=kind, cmlimit=500, **cont))
        out += [m["title"] for m in d["query"]["categorymembers"]]
        if "continue" not in d:
            return out
        cont = {"cmcontinue": d["continue"]["cmcontinue"]}


def walk(cats, depth, excluded):
    seen, files, frontier = set(), {}, [(c, 0) for c in cats]
    while frontier:
        cat, lvl = frontier.pop(0)
        if cat in seen or excluded(cat):
            continue
        seen.add(cat)
        for t in members(cat, "file"):
            if not excluded(t) and t.lower().endswith((".jpg", ".jpeg", ".png")):
                files.setdefault(t, cat)
        if lvl < depth:
            frontier += [(s.split(":", 1)[1], lvl + 1) for s in members(cat, "subcat")]
    return files, seen


def text(v):
    return re.sub(r"<[^>]+>", "", v or "").strip()


def info(titles, width):
    out = {}
    for k in range(0, len(titles), 50):
        d = get(dict(action="query", prop="imageinfo", titles="|".join(titles[k:k + 50]), iiprop="url|size|mime|extmetadata",
                     iiurlwidth=width, iiextmetadatafilter="LicenseShortName|LicenseUrl|Artist|ImageDescription|DateTimeOriginal"))
        for p in d["query"]["pages"]:
            if p.get("imageinfo"):
                out[p["title"]] = p["imageinfo"][0]
    return out


def safe(title):
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", title.split(":", 1)[1].rsplit(".", 1)[0])[:80].strip("._-")
    return stem or "file"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--cat", action="append", required=True, help="a category name, without 'Category:' (repeatable)")
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--exclude", action="append", default=[], help="skip categories and files with this word in the title")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--max", type=int, default=1000)
    ap.add_argument("--list", action="store_true", help="only list what would be fetched")
    a = ap.parse_args()
    words = [w.lower() for w in a.exclude]
    excluded = lambda t: any(w in t.lower() for w in words)
    files, cats = walk(a.cat, a.depth, excluded)
    meta = info(sorted(files), a.width)
    keep, refused = [], {}
    for t in sorted(meta):
        m, em = meta[t], meta[t].get("extmetadata", {})
        lic = text(em.get("LicenseShortName", {}).get("value"))
        if excluded(text(em.get("ImageDescription", {}).get("value"))):
            refused["excluded by description"] = refused.get("excluded by description", 0) + 1
            continue
        if not FREE.match(lic) or m.get("mime") not in ("image/jpeg", "image/png"):
            refused[lic or m.get("mime") or "?"] = refused.get(lic or m.get("mime") or "?", 0) + 1
            continue
        keep.append((t, m, em, lic))
    print("%d categories, %d photos, %d with a free licence; refused: %s" % (len(cats), len(meta), len(keep), refused))
    if a.list:
        for t, m, _, lic in keep[:a.max]:
            print("  %-70s %-14s %dx%d  (%s)" % (t[:70], lic, m["width"], m["height"], files[t]))
        return
    os.makedirs(os.path.join(a.out, "images"), exist_ok=True)
    mpath = os.path.join(a.out, "manifest.json")
    manifest = json.load(open(mpath)) if os.path.exists(mpath) else {"source": "Wikimedia Commons", "files": {}}
    manifest.update(categories=a.cat, depth=a.depth, exclude=a.exclude, width=a.width,
                    command="tools/fetch_commons.py " + " ".join(sys.argv[1:]))
    names = {v["commons"]: k for k, v in manifest["files"].items()}
    names.update({t: None for t in manifest.get("skipped", [])})
    n = 0
    for t, m, em, lic in keep[:a.max]:
        if t in names:
            continue
        name = next((safe(t) + x for x in (".jpg", ".png") if safe(t) + x not in manifest["files"]
                     and os.path.exists(os.path.join(a.out, "images", safe(t) + x))), None)
        if name:                                  # on disk from a run that stopped before saving its manifest
            with open(os.path.join(a.out, "images", name), "rb") as fh:
                ok = any(fh.read(4).startswith(mg) for mg in MAGIC)
            if not ok:
                name = None
        if not name:
            url = m.get("thumburl") or m["url"]
            try:
                data = fetch(url, limit=30_000_000)
            except Exception as e:
                print("  skipped %s: %s" % (t, type(e).__name__))
                continue
            ext = next((x for mg, x in MAGIC.items() if data.startswith(mg)), None)
            if not ext:
                print("  skipped %s: not a JPEG or PNG" % t)
                continue
            name = safe(t) + ext
            while name in manifest["files"]:
                name = name.replace(ext, "_" + ext)
            with open(os.path.join(a.out, "images", name), "wb") as fh:
                fh.write(data)
            n += 1
        manifest["files"][name] = {
            "commons": t, "page": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(t.replace(" ", "_")),
            "category": files[t], "license": lic, "license_url": text(em.get("LicenseUrl", {}).get("value")),
            "author": text(em.get("Artist", {}).get("value"))[:200], "original_size": [m["width"], m["height"]],
            "description": text(em.get("ImageDescription", {}).get("value"))[:300]}
        json.dump(manifest, open(mpath, "w"), indent=1, ensure_ascii=False)
        if n and n % 25 == 0:
            print("  %d fetched" % n, flush=True)
    json.dump(manifest, open(mpath, "w"), indent=1, ensure_ascii=False)
    print("%d new photos in %s (%d in the manifest)" % (n, os.path.join(a.out, "images"), len(manifest["files"])))


if __name__ == "__main__":
    main()
