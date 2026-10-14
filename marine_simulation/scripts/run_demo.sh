#!/usr/bin/env bash
# Start the whole demo display with one command.
#
#   run_demo.sh [extra launch arguments, e.g. boats:=bluefin,clownfish]
#
# Reads the files of this machine from $DEMO_CONFIG_DIR (default
# ~/.config/marine_simulation_demo):
#   env.bash       sources the ROS workspace (optional when ros2 is already on PATH)
#   joysticks.yaml the gamepad device links of this host (required)
#   layout.yaml    where the windows go on this host (required)
#   target.json    the saved CAMP file holding the target area (optional)
# then launches marine_simulation demo_launch.py on a private ROS domain. When
# something is missing it says what, in plain words, and starts nothing.
#
# Copy-and-edit examples of the two yaml files are installed in
# share/marine_simulation/config (demo_joysticks.yaml, demo_layout.yaml).

CONFIG_DIR=${DEMO_CONFIG_DIR:-$HOME/.config/marine_simulation_demo}

die() {
    printf 'THE DEMO DID NOT START: %s\n' "$*" >&2
    exit 1
}

if [ -f "$CONFIG_DIR/env.bash" ]; then
    # shellcheck disable=SC1091
    source "$CONFIG_DIR/env.bash" || die "$CONFIG_DIR/env.bash failed"
fi
command -v ros2 > /dev/null 2>&1 ||
    die "ROS is not set up. Create $CONFIG_DIR/env.bash with the line that sources the workspace setup.bash."

# A private domain keeps the demo off other people's ROS graph on the network.
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-42}

for name in joysticks.yaml layout.yaml; do
    [ -f "$CONFIG_DIR/$name" ] ||
        die "$CONFIG_DIR/$name is missing. Copy the example from the marine_simulation config directory and edit it for this computer."
done

args=("joystick_config:=$CONFIG_DIR/joysticks.yaml" "layout_config:=$CONFIG_DIR/layout.yaml")
if [ -f "$CONFIG_DIR/target.json" ]; then
    args+=("target_area_file:=$CONFIG_DIR/target.json")
fi

exec ros2 launch marine_simulation demo_launch.py "${args[@]}" "$@"
