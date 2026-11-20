#!/usr/bin/env python3
"""Builds README.<lang>.md from docs/i18n/README.<lang>.tpl.md.

The templates hold the translated prose. The parts that are the same in every language are copied from README.md, so
they cannot drift: the language bar, the two Mermaid diagrams, the PX4 build and run commands and the fence.json
example. Markers: {{LANGBAR}}, {{MERMAID_ROS}}, {{MERMAID_HOW}}, {{BASH_PX4}}, {{BASH_RUN}}, {{JSON}}.

    python3 docs/i18n/build_readmes.py          # from the repository root
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LANGS = [("en", "English", "README.md"), ("pl", "Polski", "README.pl.md"), ("ro", "Română", "README.ro.md"),
         ("pt", "Português", "README.pt.md"), ("de", "Deutsch", "README.de.md"), ("es", "Español", "README.es.md"),
         ("hr", "Hrvatski", "README.hr.md"), ("bg", "Български", "README.bg.md"), ("da", "Dansk", "README.da.md")]


def langbar(cur):
    return " · ".join(("**%s**" % name) if code == cur else "[%s](%s)" % (name, f) for code, name, f in LANGS)


def blocks(md):
    fences = re.findall(r"```(\w*)\n(.*?)```", md, re.S)
    mer = [b for lang, b in fences if lang == "mermaid"]
    bash = [b for lang, b in fences if lang == "bash"]
    js = [b for lang, b in fences if lang == "json"]
    return {"MERMAID_ROS": "```mermaid\n" + mer[0] + "```", "MERMAID_HOW": "```mermaid\n" + mer[1] + "```",
            "BASH_PX4": "```bash\n" + bash[0] + "```", "BASH_RUN": "```bash\n" + bash[1] + "```",
            "JSON": "```json\n" + js[0] + "```"}


def main():
    en = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    parts = blocks(en)
    here = os.path.dirname(os.path.abspath(__file__))
    for code, _, fname in LANGS:
        tpl = os.path.join(here, "README.%s.tpl.md" % code)
        if not os.path.exists(tpl):
            continue
        text = open(tpl, encoding="utf-8").read().replace("{{LANGBAR}}", langbar(code))
        for k, v in parts.items():
            text = text.replace("{{%s}}" % k, v)
        left = re.findall(r"\{\{[A-Z_]+\}\}", text)
        assert not left, (fname, left)
        open(os.path.join(ROOT, fname), "w", encoding="utf-8").write(text)
        print("wrote", fname)


if __name__ == "__main__":
    main()
