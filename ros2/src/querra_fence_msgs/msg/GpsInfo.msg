std_msgs/Header header
uint8 mode            # gpsd: 0/1 no fix, 2 = 2D, 3 = 3D
string fix            # "none", "2D", "3D"
int16 sats_used
int16 sats_seen
float32 hdop          # NaN if unknown
float32 speed_mps     # NaN if unknown
float32 track_deg     # NaN if unknown
float32 fix_age_s     # seconds since the last 2D/3D fix, NaN if none yet
string device
