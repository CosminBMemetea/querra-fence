"""Charts for the model registry, drawn from ml/models.json and the git tags (needs matplotlib).

    python tools/model_charts.py          # writes the images below

docs/img/model-evolution.png                  every model on the same benchmark, four panels
docs/img/model-evolution/model-vX.Y.png       the same chart with one model highlighted (for its release notes)
docs/img/release-map.png                      platform and model releases over time, and which model each platform used

Release titles for the map come from docs/release-notes/<tag>.md (first line: "# <tag> · <title>").
"""
import json
import os
import subprocess
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "docs", "img")
SURF, INK, INK2, MUTED, GRID, BAND = "#fcfcfb", "#0b0b0b", "#52514e", "#8c8b84", "#e2e1dc", "#eeede8"
CLASSIC, RICH, MODEL = "#2a78d6", "#eb6834", "#1baf7a"     # categorical slots 1, 2, 3 of the validated palette
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9.5, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.titlecolor": INK, "axes.titlesize": 10.5,
                     "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlepad": 8})


def load():
    with open(os.path.join(ROOT, "ml", "models.json")) as f:
        return sorted(json.load(f)["models"], key=lambda m: [int(x) for x in m["id"][7:].split(".")])


def style(ax):
    ax.set_facecolor(SURF)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    ax.grid(axis="y", color=GRID, lw=0.7)
    ax.set_axisbelow(True)


def evolution(models, highlight=None, out=None):
    ids = [m["id"] for m in models]
    x = list(range(len(models)))
    hi = ids.index(highlight) if highlight else None
    fig, axs = plt.subplots(2, 2, figsize=(10.4, 7.0), dpi=130)
    fig.patch.set_facecolor(SURF)
    get = lambda m, k: m["scores"].get(k)

    def band(ax):
        if hi is not None:
            ax.axvspan(hi - 0.42, hi + 0.42, color=BAND, zorder=0)

    def series(ax, key_c, key_r):
        for key, col, mk, name in ((key_c, CLASSIC, "o", "classic look"), (key_r, RICH, "s", "rich look")):
            pts = [(i, get(m, key)) for i, m in enumerate(models) if get(m, key) is not None]
            ax.plot(*zip(*pts), color=col, lw=2, marker=mk, ms=7.5, mec=SURF, mew=1.5, zorder=3, label=name)
            for i, v in pts:
                if i in (0, len(models) - 1) or i == hi:
                    ax.annotate("%.2f" % v, (i, v), xytext=(0, 8 if col == CLASSIC else -15), textcoords="offset points",
                                ha="center", fontsize=8.5, color=INK2)
        ax.set_ylim(0, 1.08)

    a = axs[0][0]; style(a); band(a)
    series(a, "test_classic_mAP50", "test_rich_mAP50")
    a.set_title("Held-out test farms: mAP50, all classes")
    a = axs[0][1]; style(a); band(a)
    series(a, "test_classic_wire_break_recall", "test_rich_wire_break_recall")
    a.set_title("Held-out test farms: broken wires found (recall)")

    a = axs[1][0]; style(a); band(a)
    vals = [(m.get("mission_replay") or {}).get("false_alerts") for m in models]
    for i, v in enumerate(vals):
        if v is None:
            continue
        a.bar(i, v, width=0.5, color=CLASSIC, zorder=3)
        found = (models[i].get("mission_replay") or {}).get("faults_found", "").replace(" of ", "/")
        a.annotate("%d\n(%s)" % (v, found), (i, v), xytext=(0, 3), textcoords="offset points", ha="center",
                   fontsize=7.5, color=INK2)
    a.set_ylim(0, max(v for v in vals if v is not None) * 1.35)
    a.yaxis.set_major_locator(MaxNLocator(integer=True))
    a.set_title("Recorded classic mission: false alerts (faults found)")

    a = axs[1][1]; style(a); band(a)
    top = 1
    for i, m in enumerate(models):
        live = m.get("live") or {}
        flown = [(look, live[look]) for look in ("classic", "rich") if "false_alerts" in live.get(look, {})]
        if not flown:
            a.annotate("no confirmed\nlive flight", (i, 0.3), ha="center", fontsize=8, color=MUTED)
            continue
        for look, lv in flown:
            dx, col = (-0.16, CLASSIC) if look == "classic" else (0.16, RICH)
            v = lv["false_alerts"]; top = max(top, v)
            a.bar(i + dx, v, width=0.26, color=col, zorder=3, edgecolor=SURF, linewidth=1)
            a.annotate("%d\n(%s)" % (v, lv["faults_found"].replace(" of ", "/")), (i + dx, v), xytext=(0, 3),
                       textcoords="offset points", ha="center", fontsize=7.5, color=INK2)
    a.set_ylim(0, top * 1.45)
    a.yaxis.set_major_locator(MaxNLocator(integer=True))
    a.set_title("Live flight on the Jetson: false alerts (faults found)")

    labels = ["%s\n%s" % (m["id"], "\n".join(textwrap.wrap(m.get("summary", ""), 15))) for m in models]
    for row in axs:
        for a in row:
            a.set_xticks(x)
            a.set_xticklabels(labels, fontsize=8.5)
            a.set_xlim(-0.6, len(models) - 0.4)
            if hi is not None:
                a.get_xticklabels()[hi].set_fontweight("bold")
                a.get_xticklabels()[hi].set_color(INK)
    fig.suptitle("Fence detector: how each model scored", x=0.012, ha="left", fontsize=13.5, fontweight="bold", color=INK)
    fig.text(0.012, 0.935, "Same benchmark for every model: held-out farms in both world looks, the recorded mission\n"
             "replayed through the live 5-of-8 confirmation, and live flights on the Jetson (ml/README.md)",
             fontsize=9, color=INK2, va="top")
    handles = [Line2D([], [], color=CLASSIC, lw=2, marker="o", ms=7, mec=SURF, label="classic look"),
               Line2D([], [], color=RICH, lw=2, marker="s", ms=7, mec=SURF, label="rich look")]
    fig.legend(handles=handles, loc="upper right", bbox_to_anchor=(0.99, 0.985), frameon=False, ncol=2, fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.9), h_pad=2.0, w_pad=2.0)
    fig.savefig(out, facecolor=SURF)
    plt.close(fig)


def git(*a):
    return subprocess.run(["git", "-C", ROOT] + list(a), capture_output=True, text=True, check=True).stdout.strip()


def title(tag):
    p = os.path.join(ROOT, "docs", "release-notes", tag + ".md")
    if os.path.exists(p):
        first = open(p).readline().strip().lstrip("# ")
        return first.split(" · ", 1)[1] if " · " in first else first
    return ""


def release_map(models, out):
    tags = [t for t in git("tag").split() if t.startswith("v") or t.startswith("model-v")]
    when = {t: int(git("log", "-1", "--format=%ct", t + "^{commit}")) for t in tags}
    tags.sort(key=lambda t: when[t])
    xs = {t: i for i, t in enumerate(tags)}
    fig, ax = plt.subplots(figsize=(16, 5.0), dpi=120)
    fig.patch.set_facecolor(SURF); ax.set_facecolor(SURF)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks([]); ax.set_yticks([])
    PY, MY = 1.0, 0.0
    plat = [t for t in tags if t.startswith("v")]
    mods = [t for t in tags if t.startswith("model-")]
    ax.plot([xs[plat[0]], xs[plat[-1]]], [PY, PY], color=GRID, lw=3, zorder=1, solid_capstyle="round")
    ax.plot([xs[mods[0]], xs[mods[-1]]], [MY, MY], color=GRID, lw=3, zorder=1, solid_capstyle="round")
    ax.text(-0.9, PY, "Platform", ha="right", va="center", fontsize=10.5, fontweight="bold", color=INK)
    ax.text(-0.9, MY, "Models", ha="right", va="center", fontsize=10.5, fontweight="bold", color=INK)
    for t in plat:
        ax.scatter(xs[t], PY, s=95, color=INK2, zorder=3, edgecolor=SURF, linewidth=1.5)
        ax.text(xs[t], PY + 0.1, t, ha="center", va="bottom", fontsize=9, fontweight="bold", color=INK)
        ax.text(xs[t], PY + 0.26, "\n".join(textwrap.wrap(title(t), 14)[:6]), ha="center", va="bottom", fontsize=7.3, color=INK2)
    for t in mods:
        m = next((m for m in models if m["id"] == t), {})
        ax.scatter(xs[t], MY, s=110, marker="D", color=MODEL, zorder=3, edgecolor=SURF, linewidth=1.5)
        ax.text(xs[t], MY - 0.1, t.replace("model-", ""), ha="center", va="top", fontsize=9, fontweight="bold", color=INK)
        ax.text(xs[t], MY - 0.25, "\n".join(textwrap.wrap(m.get("summary", ""), 12)), ha="center", va="top", fontsize=7.6, color=INK2)
    # which model each platform release used: bands under the platform lane, a dotted link from the model release
    # a role runs from its *_from platform release to its *_until release (the next model's), or to today
    lanes = [("default", "default detector", 0.62), ("live_sim", "live simulation", 0.45)]
    end = xs[plat[-1]] + 0.45
    for m in models:
        for key, what, y in lanes:
            pf = m.get("platform") or {}
            start, until = pf.get(key + "_from"), pf.get(key + "_until")
            if not start or start not in xs:
                continue
            stop = xs[until] - 0.08 if until in xs else end
            ax.plot([xs[start], stop], [y, y], color=MODEL, lw=5, solid_capstyle="butt", zorder=2,
                    alpha=0.85 if until is None else 0.45)
            near_end = stop - xs[start] < 3
            ax.text(stop if near_end else xs[start] + 0.08, y + 0.05, "%s: %s" % (what, m["id"]), fontsize=8, color=INK,
                    va="bottom", ha="right" if near_end else "left")
            ax.plot([xs[m["id"]], xs[start]], [MY + 0.07, y - 0.02], color=MODEL, lw=1.2, ls=(0, (2, 2)), zorder=1)
    # day separators
    days = {}
    for t in tags:
        days.setdefault(git("log", "-1", "--format=%cd", "--date=format:%b %d", t + "^{commit}"), []).append(xs[t])
    for k, (day, pos) in enumerate(sorted(days.items(), key=lambda kv: min(kv[1]))):
        if k:
            ax.plot([min(pos) - 0.5] * 2, [-0.75, 1.15], color=GRID, lw=1, ls=(0, (4, 3)), zorder=0)
        ax.text((min(pos) + max(pos)) / 2, -0.82, day, ha="center", fontsize=8.5, color=MUTED)
    ax.set_xlim(-2.4, len(tags) - 0.3)
    ax.set_ylim(-0.9, 2.2)
    ax.set_title("Releases: the platform and the fence detector models", fontsize=13.5, pad=10)
    fig.tight_layout()
    fig.savefig(out, facecolor=SURF)
    plt.close(fig)


def main():
    models = load()
    os.makedirs(os.path.join(IMG, "model-evolution"), exist_ok=True)
    evolution(models, out=os.path.join(IMG, "model-evolution.png"))
    for m in models:
        evolution(models, highlight=m["id"], out=os.path.join(IMG, "model-evolution", m["id"] + ".png"))
    release_map(models, os.path.join(IMG, "release-map.png"))
    print("wrote docs/img/model-evolution.png, docs/img/model-evolution/*.png, docs/img/release-map.png")


if __name__ == "__main__":
    main()
