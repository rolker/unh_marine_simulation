# A boat touched something it cannot pass: another boat or the bottom.
# Published once per contact onset (not once per simulation step) on
# asv_sim's ~/collisions (reliable, not latched: a subscriber that starts
# later does not see earlier events). Boats are indestructible; this only
# reports. A contact is over after one second without overlap.

std_msgs/Header header

# The boat that was blocked.
string platform

uint8 KIND_BOAT = 0
uint8 KIND_TERRAIN = 1
uint8 kind

# Name of the other boat for KIND_BOAT; empty for KIND_TERRAIN.
string other

# Where the blocked boat is, degrees.
float64 latitude
float64 longitude

# Speed in m/s at which the boat was closing on the obstacle before the
# contact stopped it.
float32 closing_speed

# KIND_TERRAIN: water depth (grid depth plus tide) in metres under the
# hull centre at the place the boat tried to go; NaN where there is no
# water or no data. KIND_BOAT: NaN.
float32 water_depth
