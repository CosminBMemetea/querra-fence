"""Trains in sessions with cooling breaks, for a laptop: stops after every N epochs, waits, and resumes.

    python tools/train_with_breaks.py --every 2 --pause 15 [--pause-first 15] -- [tools/train_yolo.py arguments]
    e.g. ... -- --data ~/querra-data/fence_yolo_v5/data.yaml --model ~/querra-data/models/fence-yolo11n-v0.4.pt \\
                --epochs 6 --device cpu --name fence-yolo11n-v0.5

It runs tools/train_yolo.py with the given arguments. When N more epochs are written to results.csv and last.pt is
saved after them, it stops the run with Ctrl+C (SIGINT), waits --pause minutes and continues with --resume, which
keeps the optimizer state, so the result is the same as one uninterrupted run. The last session ends on its own with
the final validation and the ONNX export. Output goes to stdout; it says when each break ends.

Safe to start detached (`( nohup ... & )`): a shell without job control starts background jobs with SIGINT ignored,
and the training child would inherit that and never stop for a break (ground-v0.2 ran epochs 3-8 without one). So the
SIGINT handler is reset before starting the child, and a child that does not stop within STOP_WAIT_S of the signal is
terminated (last.pt is already saved by then).
"""
import argparse
import os
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# seconds; the environment can shorten them (tests/test_train_with_breaks.py)
POLL_S = float(os.environ.get("BREAKS_POLL_S", 10))           # how often results.csv is checked
SETTLE_S = float(os.environ.get("BREAKS_SETTLE_S", 15))       # wait for last.pt to finish writing before the stop
STOP_WAIT_S = float(os.environ.get("BREAKS_STOP_WAIT_S", 120))  # then terminate a run that ignores the stop


def arg(args, name, default=None):
    return args[args.index(name) + 1] if name in args else default


def epochs_done(csv):
    try:
        with open(csv) as f:
            return max(0, sum(1 for line in f if line.strip()) - 1)
    except OSError:
        return 0


def rest(minutes, why):
    if minutes > 0:
        print("[breaks] %s: cooling for %d min, until %s" % (why, minutes, time.strftime("%H:%M", time.localtime(time.time() + 60 * minutes))), flush=True)
        time.sleep(60 * minutes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=int, default=2, help="epochs per session")
    ap.add_argument("--pause", type=float, default=15, help="minutes between sessions")
    ap.add_argument("--pause-first", type=float, default=0, help="minutes to wait before the first session")
    ap.add_argument("train", nargs=argparse.REMAINDER, help="-- then the tools/train_yolo.py arguments")
    a = ap.parse_args()
    signal.signal(signal.SIGINT, signal.default_int_handler)   # undo an inherited SIG_IGN, so the child can be stopped
    targs = a.train[1:] if a.train[:1] == ["--"] else a.train
    run = os.path.join(os.path.expanduser(arg(targs, "--project", "~/querra-data/train")), arg(targs, "--name", "fence-yolo11n"))
    total = int(arg(targs, "--epochs", 25))
    csv, last = os.path.join(run, "results.csv"), os.path.join(run, "weights", "last.pt")
    py = [sys.executable, "-u", os.path.join(ROOT, "tools", "train_yolo.py")]
    rest(a.pause_first, "before training")
    first = True
    while True:
        done = epochs_done(csv)
        if done >= total:
            break
        cmd = py + (targs if first and done == 0 else ["--resume", last, "--data", arg(targs, "--data"), "--device", arg(targs, "--device", "cpu")])
        target = min(total, done + a.every)
        print("[breaks] session: epochs %d-%d of %d" % (done + 1, target, total), flush=True)
        p = subprocess.Popen(cmd)
        first = False
        while p.poll() is None:
            time.sleep(POLL_S)
            if target < total and epochs_done(csv) >= target and os.path.exists(last) and os.path.getmtime(last) > os.path.getmtime(csv):
                time.sleep(SETTLE_S)
                p.send_signal(signal.SIGINT)
                try:
                    p.wait(timeout=STOP_WAIT_S)
                except subprocess.TimeoutExpired:
                    print("[breaks] the run ignored the stop signal; terminating it (last.pt is saved)", flush=True)
                    p.terminate()
                    p.wait()
                break
        if p.returncode not in (0, None) and epochs_done(csv) < target:
            print("[breaks] training stopped with code %s before epoch %d" % (p.returncode, target), flush=True)
            sys.exit(p.returncode)
        if epochs_done(csv) >= total:
            break
        rest(a.pause, "after epoch %d" % epochs_done(csv))
    print("[breaks] done: %d epochs in %s" % (epochs_done(csv), run), flush=True)


if __name__ == "__main__":
    main()
