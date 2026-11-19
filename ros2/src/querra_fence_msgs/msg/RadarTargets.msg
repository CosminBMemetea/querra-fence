std_msgs/Header header
bool connected        # ld2450-radar service reports the sensor connected
bool demo             # service runs in --demo mode (simulated targets)
float32 fps
uint64 frames
uint64 bad
string error
RadarTarget[] targets # only occupied slots
