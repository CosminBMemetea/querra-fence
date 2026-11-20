"""Release notes for the GitHub releases, kept in docs/release-notes/<tag>.md. The first line is "# <tag> · <title>".

    python3 tools/release_notes.py                     # check every notes file
    python3 tools/release_notes.py --apply [TAG ...]   # gh release edit: title and notes (every tag by default)
    python3 tools/release_notes.py --verify            # compare the GitHub releases with the files

Checks: every release tag has a file and every file a tag; the title starts with the tag; the sections of its track
are present (platform vX.Y.Z or model model-vX.Y, see ml/README.md); no {{placeholder}} is left; images from
raw.githubusercontent.com are pinned to a commit or tag, not to main. --verify also checks that every file attached to
a release is listed in its Files table. Tags are never moved.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTES = os.path.join(ROOT, "docs", "release-notes")
TRACKS = {
    "platform": (re.compile(r"^v\d+\.\d+\.\d+$"), ["**Models:**", "## Highlights", "## Install or run", "## Known limits"]),
    "model": (re.compile(r"^model-v\d+\.\d+$"), ["## What changed", "## Scores", "## In flight on the Jetson",
                                                  "## Known limits", "## Files"]),
}


def run(*cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def track(tag):
    return next((name for name, (rx, _) in TRACKS.items() if rx.match(tag)), None)


def tag_key(tag):
    return (tag.startswith("model-"), [int(x) for x in re.findall(r"\d+", tag)])


def read(tag):
    with open(os.path.join(NOTES, tag + ".md"), encoding="utf-8") as f:
        first, body = f.readline().rstrip("\n"), f.read().strip("\n") + "\n"
    return first[2:] if first.startswith("# ") else None, body


def check():
    tags = sorted((t for t in run("git", "tag").stdout.split() if track(t)), key=tag_key)
    files = sorted(f[:-3] for f in os.listdir(NOTES) if f.endswith(".md"))
    errs = ["%s: no notes file" % t for t in tags if t not in files]
    errs += ["%s.md: no such tag" % f for f in files if f not in tags and track(f)]
    for t in tags:
        if t not in files:
            continue
        title, body = read(t)
        if not title or not title.startswith(t + " · "):
            errs.append("%s: first line must be '# %s · <title>'" % (t, t))
        for sec in TRACKS[track(t)][1]:
            if sec not in body:
                errs.append("%s: missing %s" % (t, sec))
        if "{{" in body:
            errs.append("%s: placeholder left: %s" % (t, re.search(r"\{\{[^}]*\}\}", body).group(0)))
        for url in re.findall(r"https://raw\.githubusercontent\.com/[^/]+/[^/]+/main/[^\s)\"']+", body):
            errs.append("%s: image not pinned to a commit: %s" % (t, url))
    return tags, errs


def apply(tags):
    for t in tags:
        title, body = read(t)
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(body)
        r = run("gh", "release", "edit", t, "--title", title, "--notes-file", f.name)
        os.unlink(f.name)
        print("%-4s %-11s %s" % ("ok" if r.returncode == 0 else "FAIL", t, title if r.returncode == 0 else r.stderr.strip()))
        if r.returncode:
            return False
    return True


def verify(tags):
    bad = 0
    for t in tags:
        r = run("gh", "release", "view", t, "--json", "name,body,assets")
        if r.returncode:
            print("FAIL %-11s %s" % (t, r.stderr.strip())); bad += 1
            continue
        gh = json.loads(r.stdout)
        title, body = read(t)
        probs = []
        if gh["name"] != title:
            probs.append("title on GitHub: %r" % gh["name"])
        if gh["body"].strip() != body.strip():
            probs.append("notes differ")
        files = body.split("## Files", 1)[1] if "## Files" in body else ""
        probs += ["attached file not in the Files table: " + a["name"] for a in gh["assets"] if "`%s`" % a["name"] not in files]
        bad += bool(probs)
        print("%-4s %-11s %s" % ("ok" if not probs else "DIFF", t, "; ".join(probs) or title))
    return bad == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", nargs="*", metavar="TAG", help="edit these releases on GitHub (all when none given)")
    ap.add_argument("--verify", action="store_true", help="compare GitHub with the files")
    a = ap.parse_args()
    tags, errs = check()
    for e in errs:
        print("error:", e)
    if errs:
        sys.exit(1)
    if a.apply is not None:
        sys.exit(0 if apply(a.apply or tags) else 1)
    if a.verify:
        sys.exit(0 if verify(tags) else 1)
    print("%d release notes checked: %s" % (len(tags), ", ".join(tags)))


if __name__ == "__main__":
    main()
