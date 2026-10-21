#!/usr/bin/env bash
# Start the whole demo display with one command: the launch manager (demo_manager.py).
#
#   run_demo.sh [demo_manager.py options, e.g. --boats bluefin,clownfish]
#
# Reads the files of this machine from $DEMO_CONFIG_DIR (default
# ~/.config/marine_simulation_demo):
#   env.bash       sources the ROS workspace (optional when ros2 is already on PATH)
#   joysticks.yaml the gamepad device links of this host (required unless
#                  --no-joysticks is given)
#   layout.yaml    where the windows go on this host (optional: without it nothing
#                  is placed; CAMP and rqt remember their own windows)
#   target.json    the saved CAMP file holding the target area (optional; the installed
#                  demo polygon is used without it)
# then checks that the display can be laid out and starts demo_manager.py, which brings up
# the boats, CAMP, the target-area publisher, the scorer and the window placement, on a
# private ROS domain (42, or $DEMO_ROS_DOMAIN_ID). When something is missing it says what,
# in plain words, and starts nothing. Closing the map window stops everything.
#
# Options after the script name go to demo_manager.py (--help lists them), and so do extra
# boats-launch arguments in the launch form, e.g. tide_speed_factor:=1 (checked there). The
# ones that name this machine's files (--joysticks FILE, --layout FILE, --target FILE)
# replace the files above. One option is this script's own: --hold waits for ENTER
# before the script ends, so a terminal that closes with it (the desktop shortcut
# install_demo_shortcut.sh makes) keeps the last message readable.
#
# Discovery: plain peer-to-peer, as always. --discovery-server (or DEMO_DISCOVERY_SERVER=1) makes
# every demo process find the others through one Fast DDS discovery server instead (a group the
# manager starts first; ROS_DISCOVERY_SERVER is for this demo's processes only, port 11811 + the
# ROS domain), an experiment of issue 116 that is OFF by default: on the dev laptop with four
# boats and the navigation stack it left nav2 without its transforms (see the README).
# --no-discovery-server undoes an earlier option. The ros2 command line of another terminal
# then needs, to see the whole graph:
#   export ROS_DOMAIN_ID=<the domain above> ROS_DISCOVERY_SERVER=127.0.0.1:<11811 + domain> \
#          ROS_SUPER_CLIENT=TRUE; ros2 daemon stop
# (run_demo.sh prints these lines with the numbers filled in).
#
# Copy-and-edit examples of the yaml files are installed in share/marine_simulation/config
# (demo_joysticks.yaml for labelled ports, demo_joysticks_plug_order.yaml for any pads
# in plug order, demo_layout.yaml).

hold=1
for arg in "$@"; do
    [ "$arg" = --hold ] && hold=0
done

finish() { # finish <status>: with --hold, wait for ENTER first (stdin is the terminal)
    if [ "$hold" -eq 0 ]; then
        printf '\nPress ENTER to close this window.\n' >&2
        read -r _ || true
    fi
    exit "$1"
}

die() {
    printf 'THE DEMO DID NOT START: %s\n' "$*" >&2
    finish 1
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
# When two people run the demo on one host, one of them sets DEMO_ROS_DOMAIN_ID.
domain=${DEMO_ROS_DOMAIN_ID:-42}
[[ "$domain" =~ ^[0-9]+$ ]] && [ "${#domain}" -le 18 ] && [ "$((10#$domain))" -le 101 ] ||
    die "DEMO_ROS_DOMAIN_ID is '$domain'; it must be a whole number from 0 to 101."
export ROS_DOMAIN_ID=$((10#$domain))

manager_tool() { # the manager: beside this script, else in the installed package
    if [ -n "${DEMO_MANAGER:-}" ]; then
        printf '%s\n' "$DEMO_MANAGER"
    elif [ -x "$SCRIPT_DIR/demo_manager.py" ]; then
        printf '%s\n' "$SCRIPT_DIR/demo_manager.py"
    else
        local prefix
        prefix=$(ros2 pkg prefix marine_simulation 2> /dev/null) ||
            die "the marine_simulation package is not found; is the workspace sourced in $CONFIG_DIR/env.bash?"
        printf '%s\n' "$prefix/lib/marine_simulation/demo_manager.py"
    fi
}

place_windows_tool() { # where the checker is: beside this script, else in the installed package
    if [ -n "${DEMO_PLACE_WINDOWS:-}" ]; then
        printf '%s\n' "$DEMO_PLACE_WINDOWS"
    elif [ -x "$SCRIPT_DIR/place_windows.py" ]; then
        printf '%s\n' "$SCRIPT_DIR/place_windows.py"
    else
        local prefix
        prefix=$(ros2 pkg prefix marine_simulation 2> /dev/null) ||
            die "the marine_simulation package is not found; is the workspace sourced in $CONFIG_DIR/env.bash?"
        printf '%s\n' "$prefix/lib/marine_simulation/place_windows.py"
    fi
}

warn_auto_maximize() { # a one-line warning, never an error, never changes the setting
    local gsettings=${DEMO_GSETTINGS:-gsettings} value
    command -v "$gsettings" > /dev/null 2>&1 || return 0
    value=$("$gsettings" get org.gnome.mutter auto-maximize 2> /dev/null) || return 0
    if [ "$value" = true ]; then
        echo "WARNING: GNOME maximizes any big new window, so CAMP may not come back as you left it. Once, run: gsettings set org.gnome.mutter auto-maximize false" >&2
    fi
}

expand_tilde() { # expand_tilde <path>: a leading ~ is this user's home
    case "$1" in
        "~") printf '%s\n' "$HOME" ;;
        "~/"*) printf '%s\n' "$HOME/${1#"~/"}" ;;
        *) printf '%s\n' "$1" ;;
    esac
}

# Read the options that decide which of this machine's files are needed; everything is passed
# on to the manager, with ~ expanded in the three file options. The manager has the last word
# on what an option means; this only decides which files must exist.
passed=()
no_joysticks=1 no_layout=1 want_help=1
discovery_server=1
[ "${DEMO_DISCOVERY_SERVER:-0}" = 1 ] && discovery_server=0
profile=
given_joysticks= given_layout= given_target=
while [ $# -gt 0 ]; do
    arg=$1
    shift
    case "$arg" in
        --joysticks | --layout | --target | --profile)
            [ $# -gt 0 ] || die "$arg needs a value."
            value=$1
            shift
            ;;
        --joysticks=* | --layout=* | --target=* | --profile=*)
            value=${arg#*=}
            arg=${arg%%=*}
            ;;
        *) value= ;;
    esac
    case "$arg" in
        --joysticks | --layout | --target | --profile)
            [ -n "$value" ] || die "$arg needs a non-empty value."
            ;;
    esac
    case "$arg" in
        --hold) continue ;; # this script's own, read above
        --no-discovery-server) discovery_server=1 ;;
        --discovery-server) discovery_server=0 ;;
        --no-joysticks) no_joysticks=0 ;;
        --no-layout) no_layout=0 ;;
        -h | --help) want_help=0 ;;
        --profile) profile=$value ;;
        --joysticks) given_joysticks=$(expand_tilde "$value") value=$given_joysticks ;;
        --layout) given_layout=$(expand_tilde "$value") value=$given_layout ;;
        --target) given_target=$(expand_tilde "$value") value=$given_target ;;
    esac
    case "$arg" in
        --joysticks | --layout | --target | --profile) passed+=("$arg" "$value") ;;
        *) passed+=("$arg") ;;
    esac
done

# Only the full demo (the default profile) has a map window to place and close.
display=1
{ [ -z "$profile" ] || [ "$profile" = demo ]; } && display=0

args=()
if [ "$want_help" -ne 0 ]; then
    if [ "$no_joysticks" -ne 0 ]; then
        if [ -n "$given_joysticks" ]; then
            [ -f "$given_joysticks" ] || die "the joystick file $given_joysticks is missing."
        else
            [ -f "$CONFIG_DIR/joysticks.yaml" ] ||
                die "$CONFIG_DIR/joysticks.yaml is missing. Copy the example from the marine_simulation config directory and edit it for this computer."
            args+=(--joysticks "$CONFIG_DIR/joysticks.yaml")
        fi
    fi
    if [ "$display" -eq 0 ] && [ "$no_layout" -ne 0 ]; then
        layout=
        if [ -n "$given_layout" ]; then
            layout=$given_layout
            [ -f "$layout" ] || die "the layout file $layout is missing."
        elif [ -f "$CONFIG_DIR/layout.yaml" ]; then
            layout=$CONFIG_DIR/layout.yaml
            args+=(--layout "$layout")
        fi
        # No layout.yaml on this computer means nothing to place (the installed layout places
        # no window: CAMP remembers its own).
        if [ -n "$layout" ]; then
            checker=$(place_windows_tool) || exit 1
            problem=$("$checker" --check --layout "$layout" 2>&1) ||
                die "the windows cannot be laid out: ${problem#place_windows: }"
        fi
    fi
    if [ "$display" -eq 0 ]; then
        warn_auto_maximize
    fi
    if [ "$display" -eq 0 ] && command -v pgrep > /dev/null 2>&1 &&
        pgrep -x CCOMAutonomousM > /dev/null 2>&1; then
        die "a map window (CAMP) is already open. Close it, then start the demo again."
    fi
    if [ -z "$given_target" ] && [ -f "$CONFIG_DIR/target.json" ]; then
        args+=(--target "$CONFIG_DIR/target.json")
    fi
    if [ "$display" -eq 0 ]; then
        echo "Starting the demo on ROS domain $ROS_DOMAIN_ID. To stop everything, close the map window."
    else
        echo "Starting the demo on ROS domain $ROS_DOMAIN_ID (profile $profile). To stop everything, press Ctrl-C."
    fi
    if [ "$discovery_server" -eq 0 ]; then
        echo "Discovery goes through a Fast DDS discovery server on 127.0.0.1:$((11811 + ROS_DOMAIN_ID)). To use the ros2 command line on this demo from another terminal: export ROS_DOMAIN_ID=$ROS_DOMAIN_ID ROS_DISCOVERY_SERVER=127.0.0.1:$((11811 + ROS_DOMAIN_ID)) ROS_SUPER_CLIENT=TRUE; ros2 daemon stop"
    fi
fi

# the switch is the manager's own option; the manager sets ROS_DISCOVERY_SERVER for the demo's
# processes only, so nothing here is exported to the caller's shell
if [ "$discovery_server" -eq 0 ] && [ "$want_help" -ne 0 ]; then
    args+=(--discovery-server)
fi

manager=$(manager_tool) || finish 1
if [ "$hold" -eq 0 ]; then
    "$manager" "${args[@]}" "${passed[@]}"
    finish $?
fi
exec "$manager" "${args[@]}" "${passed[@]}"
