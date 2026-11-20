#!/usr/bin/env python3
"""Relays PX4 SITL's uXRCE-DDS client to an agent on another machine (phase 3: the Jetson).

PX4 SITL's client sends to UXRCE_DDS_AG_IP, which is 127.0.0.1 by default. Rather than changing PX4 parameters, this
listens on 127.0.0.1:8888 on the Mac and forwards every datagram to AGENT:8888 (the micro-ROS agent in the Jetson's
ROS 2 container), and the agent's replies back to the client. PX4 itself is not modified.

    python3 tools/uxrce_relay.py 192.168.1.163          # or the Jetson's hostname, e.g. mmx-desktop.local
    python3 tools/uxrce_relay.py JETSON --port 8888 --listen 127.0.0.1

Start it before or after PX4; the client keeps retrying until the agent answers. Ctrl+C stops it.
start.sh exports ROS_DOMAIN_ID=42 so PX4 joins the same DDS domain as the Jetson's ROS 2 nodes.
"""
import argparse
import selectors
import socket
import time


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("agent", help="agent host (the Jetson)")
    ap.add_argument("--port", type=int, default=8888, help="agent UDP port (default 8888)")
    ap.add_argument("--listen", default="127.0.0.1", help="local address PX4 sends to (default 127.0.0.1)")
    ap.add_argument("--listen-port", type=int, help="local port PX4 sends to (default: same as --port; "
                                                     "PX4_UXRCE_DDS_PORT changes it on the PX4 side)")
    a = ap.parse_args()

    agent = (socket.gethostbyname(a.agent), a.port)
    lport = a.listen_port or a.port
    local = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    local.bind((a.listen, lport))
    remote = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    remote.bind(("0.0.0.0", 0))
    sel = selectors.DefaultSelector()
    sel.register(local, selectors.EVENT_READ, "up")
    sel.register(remote, selectors.EVENT_READ, "down")
    client, up, down, t_log = None, 0, 0, time.monotonic()
    print(f"[uxrce-relay] PX4 -> {a.listen}:{lport} -> agent {agent[0]}:{agent[1]}", flush=True)
    try:
        while True:
            for key, _ in sel.select(timeout=1.0):
                if key.data == "up":
                    data, src = local.recvfrom(65535)
                    if client != src:
                        print(f"[uxrce-relay] PX4 client at {src[0]}:{src[1]}", flush=True)
                        client = src
                    remote.sendto(data, agent); up += 1
                else:
                    data, src = remote.recvfrom(65535)
                    if src[0] == agent[0] and client:
                        local.sendto(data, client); down += 1
            if time.monotonic() - t_log > 30:
                t_log = time.monotonic()
                print(f"[uxrce-relay] {up} datagrams to the agent, {down} back to PX4", flush=True)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
