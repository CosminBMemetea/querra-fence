#!/usr/bin/env python3
"""CPU use of a set of processes over a time window, from /proc (no dependencies). Used by ./ros.sh cpu [SECONDS].

  python3 cpu_usage.py SECONDS PID [PID ...]

Prints each process's CPU in % of one core (100% = one full core), named after the node it runs (not the Python
interpreter), the sum, and how busy the whole board was.
"""
import os
import sys
import time


def name(pid):
    try:
        args = [a.decode(errors="replace") for a in open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0") if a]
    except OSError:
        return None
    for a in args:                                   # the node, not the interpreter or the shell
        b = os.path.basename(a)
        if b and not b.startswith("python") and b not in ("bash", "sh", "ros2", "-c", "-lc"):
            return b
    return os.path.basename(args[0]) if args else None


def ticks(pid):
    try:
        f = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
        return int(f[11]) + int(f[12])               # utime + stime
    except (OSError, IndexError, ValueError):
        return None


def board():
    f = list(map(int, open("/proc/stat").readline().split()[1:]))
    return sum(f), f[3] + f[4]                       # all, idle + iowait


def main():
    secs, pids = float(sys.argv[1]), sys.argv[2:]
    hz = os.sysconf("SC_CLK_TCK")
    names = {p: name(p) for p in pids}
    t0, c0, w0 = {p: ticks(p) for p in pids}, board(), time.time()
    time.sleep(secs)
    t1, c1, dt = {p: ticks(p) for p in pids}, board(), time.time() - w0
    use = {}
    for p in pids:
        if t0[p] is None or t1[p] is None:
            continue
        n = names[p] or p
        use[n] = use.get(n, 0.0) + 100.0 * (t1[p] - t0[p]) / hz / dt
    busy = 100.0 * (1 - (c1[1] - c0[1]) / max(1, c1[0] - c0[0]))
    print(f"CPU over {dt:.0f} s, in % of one core ({os.cpu_count()} cores; the board was {busy:.0f}% busy overall):")
    for n, v in sorted(use.items(), key=lambda kv: -kv[1]):
        if v >= 0.5:
            print(f"  {v:6.1f}%  {n}")
    print(f"  {sum(use.values()):6.1f}%  all processes in the container")


if __name__ == "__main__":
    main()
