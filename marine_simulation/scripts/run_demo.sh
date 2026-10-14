#!/usr/bin/env bash
# Start the whole demo display with one command.
#
#   run_demo.sh [extra launch arguments, e.g. boats:=bluefin,clownfish]
#
# Reads the files of this machine from $DEMO_CONFIG_DIR (default
# ~/.config/marine_simulation_demo):
#   env.bash       sources the ROS workspace (optional when ros2 is already on PATH)
#   joysticks.yaml the gamepad device links of this host (required unless
#                  enable_joysticks:=false is given)
#   layout.yaml    where the windows go on this host (required unless
#                  enable_window_layout:=false is given)
#   target.json    the saved CAMP file holding the target area (optional)
# then checks that the display can be laid out, and launches marine_simulation
# demo_launch.py on a private ROS domain (42, or $DEMO_ROS_DOMAIN_ID). When
# something is missing it says what, in plain words, and starts nothing.
#
# Copy-and-edit examples of the two yaml files are installed in
# share/marine_simulation/config (demo_joysticks.yaml, demo_layout.yaml).

die() {
    printf 'THE DEMO DID NOT START: %s\n' "$*" >&2
    exit 1
}

[ -n "${HOME:-}" ] || die "HOME is not set."
CONFIG_DIR=${DEMO_CONFIG_DIR:-$HOME/.config/marine_simulation_demo}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if [ -f "$CONFIG_DIR/env.bash" ]; then
    # shellcheck disable=SC1091
    source "$CONFIG_DIR/env.bash" || die "$CONFIG_DIR/env.bash failed"
fi
command -v ros2 > /dev/null 2>&1 ||
    die "ROS is not set up. Create $CONFIG_DIR/env.bash with the line that sources the workspace setup.bash."

# A private domain keeps the demo off other people's ROS graph on the network. An
# exported ROS_DOMAIN_ID is deliberately not used: lab computers often share one.
export ROS_DOMAIN_ID=${DEMO_ROS_DOMAIN_ID:-42}

switched_off() { # switched_off <switch> <args...>
    local switch=$1 arg
    shift
    for arg in "$@"; do
        case "$arg" in
            "$switch:=false" | "$switch:=0" | "$switch:=no" | "$switch:=off") return 0 ;;
        esac
    done
    return 1
}

args=()
if ! switched_off enable_joysticks "$@"; then
    [ -f "$CONFIG_DIR/joysticks.yaml" ] ||
        die "$CONFIG_DIR/joysticks.yaml is missing. Copy the example from the marine_simulation config directory and edit it for this computer."
    args+=("joystick_config:=$CONFIG_DIR/joysticks.yaml")
fi
if ! switched_off enable_window_layout "$@"; then
    [ -f "$CONFIG_DIR/layout.yaml" ] ||
        die "$CONFIG_DIR/layout.yaml is missing. Copy the example from the marine_simulation config directory and edit it for this computer."
    checker=${DEMO_PLACE_WINDOWS:-$SCRIPT_DIR/place_windows.py}
    problem=$("$checker" --check --layout "$CONFIG_DIR/layout.yaml" 2>&1) ||
        die "the windows cannot be laid out: ${problem#place_windows: }"
    args+=("layout_config:=$CONFIG_DIR/layout.yaml")
fi
if ! switched_off enable_camp "$@" && command -v pgrep > /dev/null 2>&1 &&
    pgrep -x CCOMAutonomousM > /dev/null 2>&1; then
    die "a map window (CAMP) is already open. Close it, then start the demo again."
fi
if [ -f "$CONFIG_DIR/target.json" ]; then
    args+=("target_area_file:=$CONFIG_DIR/target.json")
fi

echo "Starting the demo on ROS domain $ROS_DOMAIN_ID. To stop everything, close the map window."
exec ros2 launch marine_simulation demo_launch.py "${args[@]}" "$@"
