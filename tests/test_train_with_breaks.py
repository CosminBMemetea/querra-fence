"""tools/train_with_breaks.py stops the training for every cooling break, also when it was started detached.

A shell without job control starts `( nohup ... & )` with SIGINT ignored, and the training inherited that: on
2026-11-26 ground-v0.2 ran epochs 3-8 without a break. These tests start the script the same way, with a stand-in
trainer, and with the waits shortened through the environment."""
import os
import shutil
import signal
import subprocess
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FAKE_TRAINER = textwrap.dedent("""
    # Stands in for tools/train_yolo.py: one "epoch" per FAKE_EPOCH_S, a results.csv row and last.pt after each.
    import os, signal, sys, time
    if os.environ.get("FAKE_IGNORES_SIGINT"):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    a = sys.argv
    run = os.path.join(a[a.index("--project") + 1] if "--project" in a else os.environ["FAKE_PROJECT"], "t")
    os.makedirs(os.path.join(run, "weights"), exist_ok=True)
    csv = os.path.join(run, "results.csv")
    if not os.path.exists(csv):
        open(csv, "w").write("epoch\\n")
    done = sum(1 for line in open(csv) if line.strip()) - 1
    try:
        for e in range(done + 1, 4):
            time.sleep(float(os.environ.get("FAKE_EPOCH_S", 0.4)))
            open(csv, "a").write("%d\\n" % e)
            time.sleep(0.05)
            open(os.path.join(run, "weights", "last.pt"), "w").write(str(e))
        print("fake: finished", flush=True)
    except KeyboardInterrupt:
        print("fake: stopped by SIGINT", flush=True)
""")


def run_detached(tmp_path, **env):
    tools = tmp_path / "tools"
    tools.mkdir()
    shutil.copy(os.path.join(ROOT, "tools", "train_with_breaks.py"), tools)
    (tools / "train_yolo.py").write_text(FAKE_TRAINER)
    e = dict(os.environ, BREAKS_POLL_S="0.1", BREAKS_SETTLE_S="0.1", FAKE_PROJECT=str(tmp_path / "runs"), **env)
    p = subprocess.run([sys.executable, str(tools / "train_with_breaks.py"), "--every", "1", "--pause", "0.002", "--",
                        "--project", str(tmp_path / "runs"), "--name", "t", "--epochs", "3", "--data", "x.yaml"],
                       env=e, capture_output=True, text=True, timeout=60,
                       preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_IGN))   # as '( nohup ... & )'
    return p.stdout + p.stderr


def test_a_detached_run_still_takes_every_break(tmp_path):
    out = run_detached(tmp_path)
    assert "after epoch 1: cooling" in out and "after epoch 2: cooling" in out
    assert out.count("fake: stopped by SIGINT") == 2
    assert "done: 3 epochs" in out


def test_a_run_that_ignores_the_stop_is_terminated_and_resumed(tmp_path):
    # epochs of 1 s, so the run is terminated before it writes the next one
    out = run_detached(tmp_path, FAKE_IGNORES_SIGINT="1", BREAKS_STOP_WAIT_S="0.3", FAKE_EPOCH_S="1.0")
    assert out.count("ignored the stop signal; terminating it") == 2
    assert "after epoch 2: cooling" in out and "done: 3 epochs" in out
