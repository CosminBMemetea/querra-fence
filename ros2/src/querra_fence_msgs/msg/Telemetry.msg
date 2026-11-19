# Vehicle state needed to place detections on the ground (from the simulator, PX4 later, or gpsd).
std_msgs/Header header
float64 latitude          # NaN if unknown
float64 longitude
float32 altitude_m        # above ground (sim: relative altitude); NaN if unknown
float32 heading_deg       # 0 = north, clockwise; NaN if unknown
float32 speed_mps
string phase              # e.g. takeoff, inspection, return (sim) or field
string source             # sim, gpsd, px4
