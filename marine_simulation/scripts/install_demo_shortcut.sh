#!/usr/bin/env bash
# Put an icon on this user's desktop that starts the demo with a double click.
#
#   install_demo_shortcut.sh [--name NAME] [run_demo.sh options]
#
# The icon runs the run_demo.sh beside this script in a terminal window, with --hold,
# so the window stays until ENTER is pressed and the last message (THE DEMO DID NOT
# START: ...) can be read. Any other options are baked into the shortcut, e.g.
#   install_demo_shortcut.sh --joysticks ~/.config/marine_simulation_demo/joysticks.yaml
# (not needed: run_demo.sh reads that file by itself). --name sets the icon's label
# (default "Ocean Discovery Day Demo").
#
# A double click starts with no workspace sourced, so this refuses to install until
# $DEMO_CONFIG_DIR/env.bash (default ~/.config/marine_simulation_demo/env.bash) exists
# and puts ros2 on the PATH; run_demo.sh sources it first. The file goes to the desktop
# directory (xdg-user-dir DESKTOP, else ~/Desktop) and is marked executable and, for
# GNOME, trusted (gio metadata::trusted), so it launches without an "allow launching"
# question. Run it again after moving the workspace: the shortcut holds the full path.

die() {
    printf 'THE SHORTCUT WAS NOT INSTALLED: %s\n' "$*" >&2
    exit 1
}

[ -n "${HOME:-}" ] || die "HOME is not set."
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CONFIG_DIR=${DEMO_CONFIG_DIR:-$HOME/.config/marine_simulation_demo}
RUN_DEMO=${DEMO_RUN_DEMO:-$SCRIPT_DIR/run_demo.sh}
[ -x "$RUN_DEMO" ] || die "$RUN_DEMO is not there or not executable; install the package first."

name="Ocean Discovery Day Demo"
options=()
while [ $# -gt 0 ]; do
    case "$1" in
        --name)
            [ $# -gt 1 ] && [ -n "$2" ] || die "--name needs a non-empty value."
            name=$2
            shift 2
            ;;
        --name=*)
            name=${1#--name=}
            [ -n "$name" ] || die "--name needs a non-empty value."
            shift
            ;;
        --hold) shift ;; # always on in the shortcut
        -h | --help)
            sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            options+=("$1")
            shift
            ;;
    esac
done

# The double click comes with no ROS on the PATH: env.bash has to provide it.
[ -f "$CONFIG_DIR/env.bash" ] ||
    die "$CONFIG_DIR/env.bash is missing. Put the line that sources the workspace setup.bash in it, e.g.
  mkdir -p $CONFIG_DIR && echo 'source /path/to/workspace/setup.bash' > $CONFIG_DIR/env.bash"
env -i HOME="$HOME" PATH="${PATH:-/usr/bin:/bin}" bash -c \
    'source "$1" > /dev/null 2>&1 && command -v ros2 > /dev/null 2>&1' _ "$CONFIG_DIR/env.bash" ||
    die "$CONFIG_DIR/env.bash does not put ros2 on the PATH; it must source the workspace setup.bash."

if command -v xdg-user-dir > /dev/null 2>&1; then
    desktop=$(xdg-user-dir DESKTOP 2> /dev/null) || desktop=
fi
[ -n "${desktop:-}" ] || desktop=$HOME/Desktop
[ -d "$desktop" ] || die "the desktop directory $desktop does not exist."

desktop_quote() { # one Exec argument, quoted as the Desktop Entry specification asks
    local s=$1
    s=${s//\\/\\\\}
    s=${s//\"/\\\"}
    s=${s//\`/\\\`}
    s=${s//\$/\\\$}
    printf '"%s"' "$s"
}

exec_line=$(desktop_quote "$RUN_DEMO")
for option in --hold "${options[@]}"; do
    exec_line="$exec_line $(desktop_quote "$option")"
done
case "$name" in
    *$'\n'*) die "the name must be one line." ;;
esac

file=$desktop/marine_simulation_demo.desktop
cat > "$file" <<ENTRY || die "cannot write $file."
[Desktop Entry]
Type=Application
Version=1.0
Name=$name
Comment=Start the boat demo: the boats, the map and the score. Close the map window to stop everything.
Exec=$exec_line
Path=$HOME
Terminal=true
Icon=input-gaming
Categories=Education;Science;
ENTRY
chmod +x "$file" || die "cannot make $file executable."
trusted=
if command -v gio > /dev/null 2>&1; then
    if gio set "$file" metadata::trusted true 2> /dev/null; then
        trusted=" and marked trusted"
    else
        trusted=" (gio could not mark it trusted: the first double click may ask to allow launching)"
    fi
fi
echo "Installed $file: \"$name\" runs $RUN_DEMO --hold${options:+ ${options[*]}} in a terminal$trusted."
