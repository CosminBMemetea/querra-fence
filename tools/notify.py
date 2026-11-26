"""Set up phone alerts and test them (docs/phone-alerts.md). Standard library only.

  python3 tools/notify.py setup ntfy        a private random topic for the ntfy app (no account needed)
  python3 tools/notify.py setup telegram    your Telegram bot: asks for its token, then finds your chat
  python3 tools/notify.py status            which backends are set up (no secrets shown)
  python3 tools/notify.py test              a test alert with a photo to every backend that is set up

The settings go to ~/.config/querra/notify.json (or $QUERRA_NOTIFY), readable only by you, never into git. Run the
same on the Jetson's host to give the robot its phone link: ros.sh mounts that file into the ROS 2 container, and
notify:=true turns the alerts on. The ntfy topic and the bot token are secrets: anyone who has them can read (topic)
or send (token) your alerts, so they are shown only at setup, on your own screen.
"""
import argparse
import getpass
import json
import os
import secrets
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ros2", "src", "querra_fence_ros"))
from querra_fence_ros import notify  # noqa: E402   (the robot's own module: one copy of the logic)

TEST_PHOTO = os.path.join(ROOT, "ml", "runs", "ground-v0.1", "patrol-faults.jpg")
SIM_HOME = (47.397742, 8.545594)        # PX4's simulated home; a test must not carry your real position


def save(path, cfg):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(cfg, f, indent=1)
    os.replace(tmp, path)


def setup_ntfy(path, cfg, a):
    topic = "querra-" + secrets.token_urlsafe(18).replace("_", "-").lower()
    cfg["ntfy"] = {"topic": topic, "server": a.server}
    save(path, cfg)
    print("Saved to %s (only you can read it).\n" % path)
    print("On the phone: install the ntfy app (Google Play, F-Droid or the App Store), tap +, and subscribe to")
    print("\n    %s\n" % topic)
    if a.server.rstrip("/") != "https://ntfy.sh":
        print("with 'Use another server' set to %s." % a.server)
    else:
        print("on the default server, ntfy.sh. Or open %s/%s in a browser." % (a.server.rstrip("/"), topic))
    print("Anyone who knows this name can read the alerts: keep it to yourself.")
    print("Then: python3 tools/notify.py test")


def setup_telegram(path, cfg, a):
    print("1. In Telegram, talk to @BotFather: /newbot, pick a name. It answers with a token.")
    token = getpass.getpass("2. Paste the token here (it is not shown): ").strip()
    tg = notify.Telegram(token, "")
    try:
        me = tg.call("getMe", {})
    except notify.SendError as e:
        sys.exit("Telegram refused the token: %s" % e)
    print("3. Open https://t.me/%s and press Start (or send it any message). Waiting up to 2 minutes..." % me["username"])
    chat, who, offset, t0 = None, "you", None, time.time()
    while chat is None and time.time() - t0 < 120:
        for u in tg.call("getUpdates", {"timeout": 10, **({"offset": offset} if offset else {})}) or []:
            offset = u["update_id"] + 1
            m = u.get("message") or {}
            if m.get("date", 0) >= t0 - 5 and m.get("chat", {}).get("id"):      # only messages sent from now on
                chat = m["chat"]["id"]
                who = m["chat"].get("first_name") or m["chat"].get("title") or "you"
    if chat is None:
        sys.exit("No message reached the bot. Run setup again and press Start in the chat with it.")
    cfg["telegram"] = {"bot_token": token, "chat_id": chat, "location": True}
    save(path, cfg)
    notify.Telegram(token, chat).call("sendMessage", {"chat_id": chat, "text": "Querra fence: this chat now gets the alerts."})
    print("Linked to %s's chat. Saved to %s (only you can read it).\nThen: python3 tools/notify.py test" % (who, path))


def status(path, cfg):
    print("settings: %s%s" % (path, "" if cfg else " (none yet: python3 tools/notify.py setup ntfy|telegram)"))
    if not cfg:
        return
    n = cfg.get("ntfy") or {}
    t = cfg.get("telegram") or {}
    print("ntfy:     %s" % ("topic set, server %s" % n.get("server", "https://ntfy.sh") if n.get("topic") else "not set up"))
    print("telegram: %s" % ("bot and chat set%s" % (", map pins on" if t.get("location", True) else "")
                            if t.get("bot_token") and t.get("chat_id") else "not set up"))
    print("rate:     %s at once, then one every %s s (alerts that wait go out together)" % (cfg.get("burst", 5), cfg.get("refill_s", 300)))
    mode = os.stat(path).st_mode & 0o777
    if mode & 0o077:
        print("warning: %s is readable by others (mode %o): chmod 600 it" % (path, mode))


def test(cfg, a):
    n = notify.Notifier(cfg, log=print)
    if not n.backends:
        sys.exit("No backend set up: python3 tools/notify.py setup ntfy (or telegram)")
    photo = open(a.photo, "rb").read() if a.photo else None
    n.alert({"source": "test", "class": "wire_break", "id": 0, "conf": 0.91, "frames": 5, "lat": SIM_HOME[0],
             "lon": SIM_HOME[1], "time": time.time(), "note": "A test from tools/notify.py, at the simulator's home."}, photo)
    n.close()
    for name, _ in n.sent:
        print("sent by %s" % name)
    sys.exit(1 if n.failed else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="settings file (default %s)" % notify.config_path())
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("backend", choices=("ntfy", "telegram"))
    s.add_argument("--server", default="https://ntfy.sh", help="ntfy server (your own, or the public ntfy.sh)")
    sub.add_parser("status")
    t = sub.add_parser("test")
    t.add_argument("--photo", default=TEST_PHOTO if os.path.exists(TEST_PHOTO) else None, help="JPEG to attach")
    a = ap.parse_args()
    path = notify.config_path(a.config)
    cfg = notify.load_config(path) or {}
    if a.cmd == "setup":
        (setup_ntfy if a.backend == "ntfy" else setup_telegram)(path, cfg, a)
    elif a.cmd == "status":
        status(path, cfg)
    else:
        test(cfg, a)


if __name__ == "__main__":
    main()
