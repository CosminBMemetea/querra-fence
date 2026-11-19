# A confirmed fence fault: N of the last M detector frames saw this class at the same ground spot.
std_msgs/Header header
uint32 id
string class_name         # wire_break, fallen_post, branch
float64 latitude
float64 longitude
float32 max_conf
uint32 frames             # frames that supported the confirmation
uint32 sightings          # all sightings merged into this alert so far
bool is_new               # true the first time, false for updates
