from glob import glob
from setuptools import setup
pkg = "querra_fence_ros"
setup(
    name=pkg, version="0.1.0", packages=[pkg],
    data_files=[("share/ament_index/resource_index/packages", ["resource/" + pkg]), ("share/" + pkg, ["package.xml"]),
                ("share/" + pkg + "/launch", glob("launch/*.py"))],
    install_requires=["setuptools"], zip_safe=True, maintainer="Cosmin B. Memetea", license="MIT",
    description="QUERRA Fence ROS 2 nodes",
    entry_points={"console_scripts": [
        "hub_camera = querra_fence_ros.hub_camera:main",
        "gpsd_gps = querra_fence_ros.gpsd_gps:main",
        "ld2450 = querra_fence_ros.ld2450:main",
    ]},
)
