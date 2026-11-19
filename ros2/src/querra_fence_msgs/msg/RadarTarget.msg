# One LD2450 target. Sensor frame: x left/right (mm), y straight ahead (mm).
uint8 slot            # 1..3
float32 x_m           # left/right, metres, as reported by the sensor
float32 y_m           # distance straight ahead, metres
float32 speed_mps     # sensor speed sign (cm/s from the sensor, converted to m/s)
float32 distance_m    # hypot(x, y)
float32 angle_deg     # atan2(x, y), 0 = straight ahead
float32 resolution_m
