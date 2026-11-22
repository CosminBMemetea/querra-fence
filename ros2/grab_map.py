#!/usr/bin/env python3
"""Save slam_toolbox's occupancy grid (/map) once, compressed. Runs inside the ROS container while SLAM runs:

  docker exec querra-ros bash -lc 'source /ws/install/setup.bash && python3 /ws/grab_map.py /ws/maps/grid_latest.npz'

Writes "grid" (int8, -1 unknown, 0-100 occupied), "res", "ox", "oy" (the grid's origin in its frame) and "frame".
tools/ugv_slam_map.sh calls it and draws the map against the true forest.
"""
import sys
import time

import numpy as np
import rclpy
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile

out = sys.argv[1] if len(sys.argv) > 1 else "/ws/maps/grid_latest.npz"
rclpy.init()
n = Node("grab_map")
got = []
n.create_subscription(OccupancyGrid, "/map", got.append, QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
t0 = time.time()
while not got and time.time() - t0 < 30:
    rclpy.spin_once(n, timeout_sec=0.5)
if not got:
    sys.exit("no /map within 30 s: is SLAM running (./ros.sh ugv ... slam:=mapping or slam:=localization)?")
m = got[-1]
grid = np.frombuffer(bytes(m.data), dtype=np.int8).reshape(m.info.height, m.info.width)
np.savez_compressed(out, grid=grid, res=m.info.resolution, ox=m.info.origin.position.x, oy=m.info.origin.position.y,
                    frame=m.header.frame_id)
print("saved %s: %d x %d cells at %.3f m, frame %s" % (out, m.info.width, m.info.height, m.info.resolution, m.header.frame_id))
