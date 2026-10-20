# marine_simulation

Scenario launch files and configs that compose the simulation packages. This file
covers the **demo boats** (Ocean Discovery Day, issues #87 and #88): several
simulated boats at once, each driven by its own gamepad, with no navigation stack.
The older launch files (`sim_robot_launch.py`, `simulator_launch.py`, ...) are
described in the repository's `.agents/README.md`.

## Whole demo display

One command starts everything on the demo computer: the boats, the coverage
scorer, CAMP with the planned layers (its window and map view come back as the
operator last left them), and any other windows on the right screens. `scripts/run_demo.sh` (installed as
`lib/marine_simulation/run_demo.sh`) is the helper's command: it finds this
computer's files and starts the launch manager (`demo_manager.py`, see "Demo launch
manager" below). That is the only way to start the demo.

### Helper card

Keep this on paper next to the computer.

```
TO START THE DEMO
  1. Plug in the four game controllers (the lights on them come on).
  2. Open a terminal. Press the UP ARROW key once, then ENTER.
  3. Wait about two minutes. Do not touch the mouse.
     Expect: the big screen shows the map with the harbour and the survey
     box; the four boats appear near the middle; the second screen stays
     as it was. (The very first time on a computer the map window may be small or
     the view off: click the maximise button in its title bar, set the view to
     taste, close the map window, and start again; from then on it comes back
     the same. Once per computer, if the start prints a WARNING about
     auto-maximize, run the command it shows.)
  4. A controller that does not steer its boat: unplug it, plug it back
     in, wait five seconds. If it still does not work, call the number below.
  5. A message starting THE DEMO DID NOT START says in a sentence what is
     wrong (a map window is already open: close it; a cable is unplugged: plug
     it in). Fix that and press UP ARROW, ENTER again. Anything else strange
     (a window in the wrong place, a frozen map): close the map window, wait
     for the prompt, UP ARROW, ENTER. Still wrong: call.

  6. A second window, rqt ("rqt"), may be open: it shows the coverage score
     and one multibeam profile per boat. It comes up filled in the first time
     on a computer; if you rearrange it, close it and it is remembered.

TO STOP EVERYTHING: close the map window (the big one). Everything else
shuts down by itself; wait until the terminal prompt comes back. (If that does
not work: click the terminal and press CTRL and C together.)

WHO TO CALL:  <NAME - OWNER TO FILL IN>   <PHONE - OWNER TO FILL IN>
```

The up-arrow command is the one typed last, so type it once yourself first:
`~/bin/run_demo.sh` (any copy of `scripts/run_demo.sh`).

### Setting up a computer (once)

1. `sudo apt install wmctrl` (it is `<exec_depend>wmctrl</exec_depend>`, so
   `rosdep install` also gets it). Window placement needs an X11 session: at
   the login screen choose "GNOME on Xorg"; on Wayland the demo refuses to
   start and says so.
2. Create `~/.config/marine_simulation_demo/` holding:
   - `env.bash`: the line(s) that source the workspace `setup.bash`.
   - `joysticks.yaml`: a copy of `config/demo_joysticks.yaml` with this
     computer's by-path device links (see Gamepads below).
   - `layout.yaml`: optional; only for windows that need placing (the installed layout
     places none): a copy of `config/demo_layout.yaml` with the monitor names from
     `xrandr --listmonitors`.
   - `target.json`: optional, the saved CAMP file holding the target survey area
     (see "Target area" below).
3. Rehearse from a cold boot: start the computer, open a terminal, run
   `run_demo.sh`, and check the card above against what appears. This is a
   human check; the tests below cannot do it.

### What the one command does

```bash
export ROS_DOMAIN_ID=42   # run_demo.sh sets 42 unless DEMO_ROS_DOMAIN_ID (0 to 101) is set, e.g. when two people share a host
run_demo.sh                # the helper's command; the options below are passed on
# what it runs, with this computer's files:
ros2 run marine_simulation demo_manager.py \
    --joysticks $HOME/.config/marine_simulation_demo/joysticks.yaml \
    --layout $HOME/.config/marine_simulation_demo/layout.yaml
```

`demo_manager.py` starts five groups under the launch manager: the boats, CAMP (private
settings, emptied tile cache), the target-area publisher, the scorer (its target exists
before it starts) and, once CAMP is up, the window placement. The groups, their rules and the
profiles are in "Demo launch manager" below.

| Option | Default | Meaning |
|---|---|---|
| `--boats a,b` | the whole roster | Comma separated boat names; the scorer and CAMP's layers follow. |
| `--roster FILE` | `config/demo_roster.yaml` | Boat roster: the only place boat names live. |
| `--joysticks FILE` | `config/demo_joysticks.yaml` (`run_demo.sh`: `~/.config/marine_simulation_demo/joysticks.yaml`) | Gamepad bindings of this computer. |
| `--no-joysticks` | off | Do not start the `joy_linux` drivers. |
| `--layout FILE` | `config/demo_layout.yaml` (`run_demo.sh`: `layout.yaml` in the config directory) | Window layout of this computer. |
| `--no-layout` | off | Do not move the windows. |
| `--camp-fresh` | off | Discard the window and map view CAMP saved when it last closed, for this start (see "First start on a computer"). |
| `--rqt-fresh` | off | Import the shipped rqt perspective again (Survey Coverage and one Ping Profile per boat), replacing the one rqt stored, for this start (see "rqt and the coverage plugin"). |
| `--target FILE` | `config/demo_target_polygon_camp.json` (`run_demo.sh`: `target.json` when present) | Saved CAMP `.json` with the target survey area: CAMP opens it and the publisher sends it to the scorer. |
| `--profile NAME` | `demo` | `demo`, `headless` (no CAMP, no placement) or `boats`. |
| `--config FILE` | `config/demo_manager.yaml` | Another manager configuration. |

The CAMP profile and view are `config/demo_camp_profile.conf` and
`config/demo_camp_view.yaml` (an optional override of CAMP's starting view; by default the view
is fitted to the target area, see below).

**Other boats-launch arguments** go after the options in the launch form `name:=value`, to
`run_demo.sh` or `demo_manager.py` alike:

```bash
run_demo.sh tide_speed_factor:=1 current_speed:=0.3
run_demo.sh --boats bluefin,clownfish tide_speed_factor:=0
ros2 run marine_simulation demo_manager.py --profile headless cell_size:=2 ping_interval:=0.5
```

Each name is checked against what `demo_boats_launch.py` itself declares (read from the launch
file, so the list cannot drift), and a name the launch does not declare is refused as `THE
DEMO DID NOT START: tide_speed_fcator:= is not an argument of the boats launch; it has ...`
(exit 2). The five the manager sets itself from its own options (`boats`, `roster_file`,
`enable_joysticks`, `joystick_config`, `lifecycle_guard`) are refused too: use `--boats`,
`--roster`, `--no-joysticks`/`--joysticks`. A name given twice keeps the last value. The
arguments reach only the `boats` group.

**Closing the CAMP window (or CAMP dying) stops everything and the manager exits**, so
the helper stops the demo by closing the map window.

The manager refuses to start, before anything else runs, and prints `THE DEMO DID NOT
START: <reason>` with exit status 2, when: another demo already holds the lock in
`~/.local/state/marine_simulation_demo`; a CAMP is already running (its settings file is the demo's, and
two CAMPs would fight over it); the joystick, layout or target file is not a file; the target file is not a CAMP project
the publisher accepts (`publish_survey_area.py --check FILE`); an extra `name:=value` argument
is unknown or is one the manager sets itself; the layout is
malformed, names a monitor that is not connected, or the session is not X11 or `wmctrl` is
missing (the same `place_windows.py --check` that `run_demo.sh` makes first and reports as
one sentence). `run_demo.sh` itself refuses, with the same phrase and exit status 1, when
this computer's `joysticks.yaml` is missing (`layout.yaml` is optional), the domain override is not
0 to 101, ROS is not set up, or a map window is open. The scorer's parameters are
generated from the roster (so `--boats a,b` scores exactly those boats) into a temporary
directory (`/tmp/demo_manager_*`) the manager removes on exit. The lock does not outlive the manager: after a
`kill -9` the lock is free but the boats and CAMP keep running, and a second `--profile
headless` would start duplicates of the boats (stop the orphans first).

### CAMP starts in a known state

CAMP keeps its view, layer lists and layer settings in a Qt settings file.
The demo gives CAMP its own settings directory (`demo_camp_launch.py`, the manager's `camp` group)
(`XDG_CONFIG_HOME=~/.local/state/marine_simulation_demo/xdg_config`) and writes
that file on every start (from the template, keeping only what CAMP saved of its window
and view, see below), so the operator's own CAMP settings are never read
or changed. The live coverage tile cache, which CAMP keeps outside its settings
file, is moved to `~/.local/state/marine_simulation_demo/live_tile_cache` and emptied
on every start too, so a previous session's tiles are not warm-loaded. Both
directories are guarded: they are only deleted at those exact paths, never through a
symlink, and only when they hold the marker file the demo writes. The file is
`config/demo_camp_profile.conf` (OpenStreetMap as the only background map) plus,
generated at launch:

- **the live coverage layers' colormap and range.** The profile's `[LiveCoverageLayer]` section
  (not a CAMP section: it is copied into every boat's layer) seeds each layer with
  `colormap=viridis` and a **manual** range of -59.4 to -29.4 m, written on every start (what
  the operator changes in CAMP's colormap menu is not kept, only the window and view are). CAMP
  reads these keys per layer in `SonarLiveCacheLayer::readSettings`: `colormap`, `range_mode`
  (`manual`; without it CAMP tracks the data), `range_min`, `range_max`, `visible`,
  `live_enabled`. The numbers are negative because the live layer colours the tiles' `depth`
  band, which is the seabed's WGS84 ellipsoid height in metres, positive up (see the
  `cube_bathymetry` README), not a depth: over 17 m of water at Portsmouth it reads about -46 m.
  The sea surface is at about -29.4 m there (measured from a demo run's tile cache against the
  chart grid), so -29.4 down to -59.4 is 0 to 30 m of water, the Ping Profile's range, with the
  deep end first: viridis then runs dark (deep) to light yellow (shallow), a perceptually uniform
  ramp whose luminance rises monotonically. The surface height is a property of the Portsmouth
  site (geoid separation), so another site needs its own two numbers.

- **what CAMP remembers.** When CAMP closes it saves its window (`MainWindow/geometry`,
  `MainWindow/state`, which include maximised or not) and its map view
  (`MainWindow/mapCenter`, `MainWindow/mapScale` and the `[MapView]` section). On every start
  the previous file, if there is one, is read first and those lines are carried into the new
  one **exactly as CAMP wrote them** (the geometry is a Qt-escaped byte array and is never
  re-encoded). Everything else comes from the template every start, so a layer toggled in CAMP
  resets, and the tile cache is still emptied. **Needs a CAMP with rolker/camp#242** (its
  resize anchor keeps the map centre): without it the window comes back as saved but the view
  shifts when the window is maximized or resized at startup. A view is kept only whole (centre and scale
  together); a saved file that cannot be read makes it a first start, with a note in the log
  (`CAMP window and view from its last run: ...`). `--camp-fresh` discards the saved window and
  view for that start.
- the map view, **only on a first start (nothing saved yet) or with `--camp-fresh`**: `MainWindow/mapCenter`, `MainWindow/mapScale` and the matching
  `MapView/mapView/*` keys. The centre is the middle of the boats' start
  positions (or `lat`/`lon` in `config/demo_camp_view.yaml`), converted with
  CAMP's own Web Mercator formula; the scale is `scale` in that file. By default
  (`camp_view: {}`, as shipped) neither is used: the view is **fitted** to the target
  area, the centre being the middle of the polygon's bounding box and the scale the
  largest that shows all of it with a 12.5 % margin on every side, for the window the
  layout file gives CAMP (its `rect`, or the size of the monitor it is maximised or full
  screen on, read with `xrandr`; 1920x1080 is assumed, and logged, when that cannot be
  read). The map widget is taken as the window minus 15 % of the width for CAMP's side
  panel and 200 px for the bars above it, on purpose a little small. The target is the
  file CAMP opens and the publisher sends to the scorer. Giving `scale` (with optional
  `lat`/`lon`) in the view file overrides the fit and is used exactly as written. The
  chosen view is logged as `CAMP map view: ...` at start. CAMP stores
  the centre in map units, so the value in the settings file is exact and the same
  on every start. What the helper sees can differ: CAMP applies the centre at its
  first window size and the window is then maximised, which may shift the
  map (rolker/camp#242). Check the view at the rehearsal.
- one live coverage layer per roster boat, switched on (`live_enabled` and
  `visible`), keyed by `/<boat>/sensors/mbes/cube_bathymetry`.

Everything else CAMP would restore (chart, raster and vector lists) is left out on purpose,
so exactly these layers show and nothing else. The window size, position and panel
arrangement are CAMP's own, saved and restored as described above; the window layout below
does not place CAMP. The ROS-driven layers (boat
platforms, which come from `/marine/platforms`) need no settings. Colormap and
range of the live layers are CAMP's defaults.

Known limits of this approach:

- OpenStreetMap tiles need internet. Without it the background is blank.
- `XDG_CONFIG_HOME` is changed for the whole CAMP process, not only its settings, so
  anything else CAMP or Qt reads from `~/.config` (platform theme, fonts) is not
  seen; look and feel can differ from the operator's CAMP. Check at the rehearsal.
- The fitted view assumes CAMP's panel and bars take 15 % of the width and 200 px of the
  height; check at the rehearsal that the whole polygon shows with a margin, and set
  `scale` in `config/demo_camp_view.yaml` if it does not.
- The live layer key pattern was read from a real CAMP settings file; the
  rehearsal confirms it matches this graph.
- The file is only the first source of truth for the layers: an operator who
  changes them in CAMP during the demo changes only that run.
- `camp_launch.py` takes no arguments, so `demo_camp_launch.py` starts the CAMP
  executable itself (rolker/camp#240 asks for launch arguments).

### rqt and the coverage plugin

The manager's `rqt` group (`demo_rqt_launch.py`) starts rqt on the shipped perspective
`config/demo.perspective`: **Survey Coverage** (`rqt_coverage/CoveragePlugin`, topic
`coverage_assessment`) and one **Ping Profile** (`rqt_ping_profile/PingProfilePlugin`) per roster
boat, titled with the boat's name, on the full topic `/<boat>/sensors/mbes/detections`, fixed
depth range 0 to 30 m (the range the live coverage layer in CAMP uses, so the two displays
agree; the plugin draws the platform's colour itself). The file is generated from the roster by
`python3 -m marine_simulation.demo_perspective config/demo_roster.yaml config/demo.perspective`,
and `test_demo_perspective.py` fails when it no longer matches the roster. It holds no window
geometry or dock state (those belong to the monitor): rqt lays the docks out itself, and the
operator's arrangement is kept from then on.

How rqt names it (read from `qt_gui` in Jazzy and checked live): `--perspective-file` imports the
file as a **hidden** perspective named `@` plus the file name, `@demo.perspective`; an existing
one of that name is replaced; it is not listed in the Perspectives menu and is not made rqt's
current perspective, but it is saved in `ros.org/rqt_gui.ini` when rqt exits like any other. So
the group starts rqt with `--perspective-file` on a **first start** (the operator's
`ros.org/rqt_gui.ini` holds no `@demo.perspective` yet; a plain `demo` perspective left by an older
version is ignored) or with `--rqt-fresh` (the first start of the group in that session only, like
`--camp-fresh`), and `--perspective @demo.perspective` after, so rqt keeps its geometry and
changes. One log line says which way it was started. rqt runs on the operator's normal settings
(`ros.org/rqt_gui.ini`), not on the demo's wiped-per-start home. `--lock-perspective` is not used
(the menu is needed to rearrange the plugins, and the close button is how the operator closes
the window), and the window is not placed. To get the shipped arrangement back after rearranging,
start once with `--rqt-fresh`. The coverage plugin's default topic
`coverage_assessment` resolves to the scorer's
`/coverage_assessment` (type `marine_interfaces/msg/CoverageAssessment`, transient local), which
the headless run of this branch showed publishing with no namespace, so nothing needs to be set in
its config dialog; the plugin tolerates a scorer that comes up late. rqt has no `requires` and
stops with CAMP; closing rqt by itself does not stop the demo. rqt is started with
`--force-discover` because it caches its plugin list in its settings: without it a plugin package
built after the first rqt start (for example `rqt_ping_profile`) would not appear in the Plugins
menu.

### Setting up the demo computer

A checklist for one computer, the Ubuntu 24.04 desktop with an RTX 5080 and the four GameSir G7 SE
pads that runs the demo at the event, in the order to do it. "Checked" means checked on the dev
host on 2026-10-14; the steps marked **on the machine** depend on the hardware and have to be
checked there. "Setting up a computer (once)" above is the per-user part (the files in
`~/.config/marine_simulation_demo`); this is the machine under it.

1. **X11 session.** The window placement and CAMP's saved geometry need X11 (position
   persistence broke on Wayland). Ubuntu's `61-gdm.rules` makes GDM prefer Xorg once an nvidia
   driver of version 470 or later binds; check at the login screen, with the gear menu, that the
   session is the Xorg one and not Wayland before logging in. Set the display layout **after** landing on X11:
   GNOME keys saved monitor layouts on connector names, and those differ between the two
   sessions (`HDMI-0`, `DP-2` on nvidia X11, `HDMI-1`, `DP-3` on Wayland), so a layout made on
   Wayland is not found on X11. Copy `~/.config/monitors.xml` aside before changing it: mutter
   keeps one backup generation only.
2. **nvidia driver (on the machine).** The dev host runs the 615 open driver; the RTX 5080 may
   need a newer one than that. Install the driver the machine needs and check `nvidia-smi` and
   the Xorg session (step 1) before the kernel work below.
3. **A kernel with the G7 SE fix, and the kernel parameter.** The pads enumerate as
   3537:10a0 and, without the fix, fall back to HID mode: no rumble, and joystick numbers that
   no longer match `config/demo_params.yaml`. The fix is the `r` letter of `usbcore.quirks`
   (`USB_QUIRK_WINDOWS_CONFIG_REQ_SIZE`), in mainline 7.2 and in stable 6.18.45 and 7.1.9
   onward; Ubuntu's 6.8 and HWE kernels do not have it. Checked with mainline 7.2.6 from
   [kernel.ubuntu.com/mainline](https://kernel.ubuntu.com/mainline/): with the parameter below,
   the pads bind `xpad`, rumble works and the joystick numbers match `demo_params.yaml`.
   - `usbcore` is built into the kernel, so `modprobe.d` cannot set it. Put
     `GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT usbcore.quirks=3537:10a0:r"` in
     `/etc/default/grub.d/gamesir-g7se.cfg`, run `sudo update-grub`, reboot, and check
     `cat /proc/cmdline` shows it.
   - The mainline debs do not install on 24.04 as they are. Their maintainer scripts call
     `run-parts` with two directories and Noble's `run-parts` takes one: repack the image,
     headers and modules debs under `fakeroot` (`dpkg-deb -R`, drop the
     `/usr/share/kernel/*.d` argument from the scripts in `DEBIAN/`, `dpkg-deb -b`).
   - The kernel is built with gcc-15 flags, so the nvidia DKMS module fails with the default
     compiler. Build it with gcc-14: `sudo apt install gcc-14`; write
     `override CC = gcc-14` into `/usr/src/linux-headers-<version>/.kernelvariables`;
     `sudo dkms install nvidia/<driver version> -k <kernel version>`; then
     `sudo dpkg --configure -a` (it reruns the initramfs and `update-grub` that the failed
     build skipped). Until that finishes there is no boot entry for the new kernel.
   - Cold-boot check: with all four pads plugged in before power-on, `ls /dev/input/js*`
     shows `js0` to `js3` and `lsusb -t` shows `Driver=xpad` under each pad.
4. **ROS 2 Jazzy and the workspace.** Install ROS 2 Jazzy, clone the workspace and run
   `make build` from its root. `make build` does not install apt packages: install them with
   `rosdep install --from-paths src --ignore-src -y` from the layer directory (it resolves this
   package's `exec_depend`s: `ros-jazzy-joy-linux`, `wmctrl` and the rest).
5. **GNOME auto-maximize.** `gsettings set org.gnome.mutter auto-maximize false` once for the
   demo user (see "First start on a computer").
6. **The per-machine files** in `~/.config/marine_simulation_demo/`: `env.bash` (sources the
   workspace `setup.bash`) and `joysticks.yaml`. The by-path device names hold the PCI address
   of the USB controller, so fill `joysticks.yaml` on this computer with all four pads in their
   final ports (see Gamepads). Or use the plug-order file
   `config/demo_joysticks_plug_order.yaml`, which binds `/dev/input/js0` to `js3` in plug
   order and needs no labelled ports (after #107 merges). The desktop icon comes from
   `install_demo_shortcut.sh` (also after #107 merges).
7. **First starts.** CAMP first (see "First start on a computer"), then rqt: it imports the
   shipped perspective by itself on a first start (see "rqt and the coverage plugin") and shows
   Survey Coverage and the four Ping Profiles; rearrange them once and close rqt. Then the
   **cold-boot check** with all four pads attached at power-on: power the computer off, plug
   the pads in, power on, log in on X11, start the demo, and check the helper card against
   what appears.

### First start on a computer

CAMP has nothing saved on a new computer, so its first window is the default size with the
fitted view. Start the demo (`run_demo.sh`), click the **maximise button in CAMP's title bar**,
set the view the way it should come up (zoom and pan), and **close CAMP**, which stops the demo.
Start it again: CAMP comes back maximised on the same view, and every later start does too.
On a GNOME computer run `gsettings set org.gnome.mutter auto-maximize false` once for the demo
user (undo with `true`): GNOME otherwise maximizes any new window that covers about 80 % of the
work area when it first appears, so a CAMP window you left big but not maximized would come
back maximized, over rqt. `run_demo.sh` prints a one-line warning with this command when the
setting is still `true` (it never changes it, and the demo starts anyway).

To forget it (a different screen, a bad view saved), start once with `--camp-fresh` (it applies to the first start of the CAMP group in that session only; a manager restart of the group keeps what CAMP saved since). If CAMP is killed or crashes it never saves, and the next start generates the view again (the generated profile carries a marker comment that CAMP's own save removes). A computer that already has its own `~/.config/marine_simulation_demo/layout.yaml` with a `camp` entry still places CAMP: delete that entry (an empty `windows: []` is fine; `run_demo.sh` no longer needs the file at all: without `~/.config/marine_simulation_demo/layout.yaml` nothing is placed). The saved
window and view are CAMP's own settings file under
`~/.local/state/marine_simulation_demo/xdg_config/`.

### Window layout

`config/demo_layout.yaml` places no window by default: CAMP is deliberately not placed (it
remembers its own window, see above), and the scoreboard does not exist yet. A layout with no
windows is a no-op: `place_windows.py` exits 0 at once (no session, tool or wait needed) and the
`layout` group finishes cleanly. The file shows how to add an entry for a window that does need
placing. Each entry names a window (by WM_CLASS
and/or title), a monitor (as `xrandr --listmonitors` names it) and either
`maximized: true` (fills the monitor's work area and keeps the title bar with its Close
button, so the operator never needs a keyboard shortcut), `fullscreen: true` (covers the whole
monitor, no title bar) or a `rect` in pixels from that monitor's top left corner; exactly one
of the three. A maximised window counts as in place when it lies on its monitor and covers at
least 85 % of it (a geometry check, like the other two). The
example leaves an entry for the scoreboard (not built yet) as a comment.
`scripts/place_windows.py` waits for the windows (90 s by default, one deadline for
all), takes the newest window that matches, clears its full screen and maximised
state, moves it with `wmctrl` (a maximised window is first moved to a rectangle inside the monitor, never to the monitor's exact size, which mutter takes for a full screen request), checks the geometry (and for a maximised window its `_NET_WM_STATE` with `xprop`: maximised and not full screen) and moves it once more if the
application resized itself, and exits non-zero naming any window it could not
place. It runs as the manager's `layout` group, a **run-once** group: it starts when
CAMP is running, and a clean exit just ends the group (status `STOPPED`, detail
`exited(0)`; nothing else stops). A failure makes the group `FAILED`, logged at ERROR
level, and the launch file prints `*** THE WINDOWS ARE NOT IN PLACE ... ***`; the rest of
the demo keeps running. `launch_manager_proto command start layout` places the windows
again, after `clear-failure layout` when it failed.
`place_windows.py --check --layout FILE` only checks the session, tools, layout
and monitors. A window that is closed and reopened by hand is not placed again
(close the map window to stop and start the demo again instead).

### Target area

The target polygon is drawn in CAMP and saved as a `.json` project file. The demo uses
`config/demo_target_polygon_camp.json` unless `--target FILE` is given (`run_demo.sh` passes
`~/.config/marine_simulation_demo/target.json` when it exists). The same file goes to
two places: CAMP opens it, which shows the outline, and the manager's `target_area` group
runs `publish_survey_area.py` on it, which sends it to the scorer on the latched
`survey_area` topic. The scorer's group `requires` the publisher, so it never starts without a
target; a file the publisher refuses makes `target_area` `FAILED` and the scorer waits,
`BLOCKED`, naming it.

**The demo scores on a 2 m lattice.** The scorer refuses a target area whose bounding box has
more than `max_raster_cells` (1,000,000) lattice cells. The shipped polygon (1.77 km², a box of
about 1408 x 1774 m) is 2.5 million cells at the example's 1 m and about 625,000 at 2 m, so the
generated scorer parameters set `cell_size: 2.0` (`demo_support.DEMO_SCORER_CELL_SIZE`). CUBE
itself keeps mapping at the boats launch's `cell_size` (1 m); this only sets how finely the
scorer rasterises the target. A test fails if the shipped polygon no longer fits, so a larger
polygon (or a smaller scoring cell) is caught in CI and not at the event. For your own
target, check the box: (north-south metres / cell) x (east-west metres / cell) must stay
under 1,000,000.

### Checks

```bash
./simulation_ws/test.sh marine_simulation          # unit tests and lint
# the manager's headless profile (boats, target area, scorer; no CAMP, no windows; needs the
# datum grids and no gamepads):
ros2 run marine_simulation demo_boats_selftest.py --start-launch --demo --boats bluefin,clownfish
```

`--demo` starts `demo_manager.py --profile headless` instead of the boats launch, then
checks the boats as usual and that `coverage_assessment` becomes active and assesses a target
area the self-test publishes itself. Not covered by any test: CAMP's real window class, the
`wmctrl` calls on a live desktop, the `layout` group after a real CAMP is up, the target
file opening in CAMP, the view after the window is maximised, and the cold-boot
rehearsal. `~/.local/state/marine_simulation_demo` stays after the demo ends (settings,
tile cache, lock); it is small and reset on every start, so there is no need to delete it.

## Demo boats

```bash
# keep the demo off other people's ROS graph (any free domain id, 0 to 101)
export ROS_DOMAIN_ID=42

# four boats, a gamepad each: needs the joy_linux driver and a joystick file
# copied and edited for this host (see Gamepads below), because the shipped
# config/demo_joysticks.yaml holds placeholder paths and the launch refuses them
ros2 launch marine_simulation demo_boats_launch.py joystick_config:=$HOME/demo_joysticks.yaml

# no gamepads: drive them with fake joystick messages, or not at all
ros2 launch marine_simulation demo_boats_launch.py enable_joysticks:=false

# check the whole thing without hardware (starts and stops the launch itself)
ros2 run marine_simulation demo_boats_selftest.py --start-launch

# the whole demo (boats, CAMP, target area, scorer, window placement), which stops everything
# when CAMP is closed: run_demo.sh, i.e. the launch manager (see "Demo launch manager" below)
ros2 run marine_simulation demo_manager.py --no-layout
```

The launch starts about 50 processes and other ROS machines on the network
may share the default ROS domain, so run the demo, the self-test and any
`ros2 topic` checks on a private `ROS_DOMAIN_ID` and leave discovery at its
default (see the self-test notes below for why not `ROS_LOCALHOST_ONLY`).

**Host requirement: datum grids.** Each boat's `chart_datum` node loads the
geoid grid `~/data/world/datum/geoid/us_noaa_g2018u0.tif` and the VDatum grids
`~/data/world/datum/vdatum/*_mllw.gtx`.
Without them it only logs a warning and never publishes `<boat>/chart_datum` or
`<boat>/chart_datum_mhhw`, so the rest of the launch would look healthy while
every TF tree stays incomplete. The launch therefore refuses to start when the
geoid grid or a `*_mllw.gtx` file is missing.

One `asv_sim` node simulates every boat. Each boat also has its own namespace,
TF frame prefix and these nodes (the lifecycle ones start from the same per-node
launch files the real boats use): `robot_state_publisher`, `joint_state_publisher`, `mru_transform`,
`sea_surface_estimator`, `chart_datum`, `asv_helm`, `helm_manager`,
`platform_sender`, `mbes_sim`, `detections_to_pointcloud` (in `<boat>/sensors/mbes`),
`cube_bathymetry` (same namespace), `joy_to_helm`, and with joysticks on a
`joy_node` (the `joy_linux` driver). There is no `udp_bridge`, `command_bridge`,
`mission_manager`, nav2 or `s57_grids`.

The venue is Portsmouth Harbour. The simulated multibeams sample the demo truth grid
(see [Demo truth bathymetry](#demo-truth-bathymetry)) when it has been built, and the packaged
5 m chart grid `mbes_sim/data/US5NH02M.tiff` otherwise.

### Launch arguments

| Argument | Default | Meaning |
|---|---|---|
| `boats` | empty (every boat) | Comma separated boat names to run. A boat keeps its roster position, so its pad does not change with the subset. |
| `roster_file` | `config/demo_roster.yaml` | Boat names, platform colours, start poses. |
| `joystick_config` | `config/demo_joysticks.yaml` | Joystick device links; copy and edit per host. |
| `enable_joysticks` | `true` | Start a `joy_linux` driver per boat. `joy_to_helm` runs either way, so `sensor_msgs/Joy` on `<boat>/joy` drives the boat. |
| `enable_nav` | `false` | Reserved. `true` is refused ("not wired yet"). |
| `tide_speed_factor` | `10` | Tide speed multiplier (10 = about a 75 minute cycle, 0 = a frozen tide). |
| `current_speed` | `0.0` | Water current in m/s. `asv_sim` itself defaults to 1.0 m/s toward 090, which drifts an undriven boat east at about 2 knots. |
| `mbes_grid_file` | empty | Ground-truth bathymetry the simulated multibeams sample. Empty means `$MBES_DEMO_GRID`, else `~/data/sim/mbes_truth/portsmouth_demo_utm19n.tif` when it exists, else `mbes_sim/data/US5NH02M.tiff` (the launch prints which and why, on stderr). An explicit path must be a file. |
| `cell_size` | `1.0` | CUBE cell size in metres. |
| `ping_interval` | `0.2` | Seconds between simulated multibeam pings. |
| `beam_count` | `120` | Beams per ping. |
| `lifecycle_guard` | `true` | Run a guard process that takes any boat lifecycle node a lost `change_state` reply left behind to `active` (issue #96). Turn it off when the launch manager runs this launch: it is the one writer then. |

The launch refuses to start (with the reason) when a boat name is unknown or
repeated, a roster value is not a finite number in range, the joystick list does
not match the roster, two boats share a pad (also when two links resolve to one
device), a configured pad is missing or its link resolves to something other than
a `jsN` node (the `-event-joystick` link), `joy_linux` is not installed,
`deadzone` is outside [0, 1) or `autorepeat_rate` is 2 Hz or less, a boolean
argument is anything but `true`/`1`/`yes`/`on` or `false`/`0`/`no`/`off`,
an explicit `mbes_grid_file` (or `$MBES_DEMO_GRID`) is not a file, `cell_size`, `beam_count` or `ping_interval` is
not positive (or not finite), `tide_speed_factor` or `current_speed` is negative
(or not finite; 0 is allowed for both), the datum grids above are missing, or
`enable_nav` is true. It also refuses a truth grid GDAL cannot read or whose CRS is not projected in metres, and prints a warning for every boat whose start position has no water in the grid (the sonar publishes nothing there).

### The roster is the only place boat names live

`config/demo_roster.yaml` lists the boats in controller order: `name`, the colour
of the `pad` that drives it, the platform `color` CAMP draws, and the start pose
(depths from `US5NH02M.tiff` are recorded in the file). The launch derives
everything else from it: namespaces, TF frames (`<name>/base_link`, `<name>/map`,
`<name>/odom`, `<name>/map_tide`, `<name>/chart_datum`, ...), the `asv_sim`
platform (including `mru_frame: <name>/motion_sensor`), and the `platform_sender`
name, which is the tab title in CAMP (CAMP makes one tab per `/marine/platforms`
platform name). To rename a boat, edit the roster. To add a fifth, add a roster
entry and one more device line in the same position in the joystick file.

The first four boats are `bluefin` (blue pad), `clownfish` (orange), `urchin`
(purple) and `beluga` (white).

### Gamepads

The driver is `joy_linux` (`ros-jazzy-joy-linux`, an `exec_depend`; run
`rosdep install` or `make build` on each machine). The SDL based `joy` package
cannot pin four identical pads: its `device_id` is a plug-order index and its
`device_name` is the same for identical pads. `joy_linux` opens a device path, and
a `/dev/input/by-path/` link names a physical USB port, so a boat stays bound to
its port across reboots.

`joy_linux` reads the kernel **joystick** interface, so the link to use ends in
`-joystick`. The link ending in `-event-joystick` is the evdev node and does not
work. Port labelling for the event (first boat first):

| USB port label | Pad | Boat |
|---|---|---|
| 1 | blue | first roster entry |
| 2 | orange | second |
| 3 | purple | third |
| 4 | white | fourth |

`config/demo_joysticks.yaml` lists the links in that order with placeholder
paths. The by-path names contain the PCI address of the USB controller, so make a
copy per machine, fill in its real links and launch with `joystick_config:=<copy>`.

Controls (`joy_to_helm`, configured explicitly in `config/demo_params.yaml`): left
stick up/down is throttle (`axes[1]`), the right stick sideways is rudder
(`axes[3]`, sent as `rudder = -axes[3]`). Throttle is scaled to 35 % unless the
left trigger (`axes[2]`) is pulled below zero, which gives full speed.

#### Pad checklist (first real-pad test is at the dry run)

1. Put the pad in XInput mode (GameSir G7 SE: see its manual for the mode switch) before plugging it in.
2. Plug blue into port 1, orange into 2, purple into 3, white into 4.
3. `ls -l /dev/input/by-path/ | grep -- '-joystick$'` shows one link per pad, each pointing at a `jsN`. Copy those into your `joystick_config`, in boat order.
4. Launch, then `ros2 topic echo --once /<boat>/joy`: `axes` must have 8 entries and `buttons` 11. `joy_to_helm` reads `buttons[9]` and `buttons[10]` on every message and silently ignores a message from a pad that has fewer, so a wrong-mode pad just does not drive.
5. Move each stick and trigger once: throttle on `axes[1]`, rudder on `axes[3]`, the left trigger takes `axes[2]` from 1.0 toward -1.0 (the joy_linux driver reports 0.0 until a trigger is first moved). Confirm right stick right turns the boat to starboard.
6. Drive each boat in turn and confirm it is the boat with the matching colour in CAMP; unplug and replug one pad and confirm it still drives the same boat (unverified until the dry run: `joy_linux` is expected to re-open the device itself, and the launch does not respawn the node).
7. Avoid B and X (buttons 1 and 2): `joy_to_helm` asks for a piloting mode change (standby, autonomous) that nothing handles (there is no `command_bridge`) and stops sending helm until the next heartbeat restores `manual`. A (button 0) asks for `manual`, which the boat is already in, so it does nothing.

### Resetting between rounds

Each boat returns to its start pose, at rest, on `std_msgs/Bool` to
`/asv_sim/<boat>/sim_reset` (or `/asv_sim/sim_reset` for all of them):

```bash
ros2 topic pub --once /asv_sim/sim_reset std_msgs/msg/Bool "{data: true}"
```

`sim_reset` moves the boats only. It does not clear the CUBE grids; emptying them
is a lifecycle cleanup and configure of each boat's `cube_bathymetry` node, a
host procedure that is not part of this launch.

`cube_bathymetry` keeps no state on disk for the demo: `draft_dir` and
`prior_store_dir` are set empty for every boat in `config/demo_params.yaml`. A
round reset that cleans up and reconfigures the CUBE nodes only starts from an
empty grid when nothing is reloaded from disk, so **do not layer `bizzyboat.yaml`
or any other config that sets `draft_dir` or `prior_store_dir` onto the demo**.

### Self-test and graph check

`demo_boats_selftest.py` needs no gamepad. It publishes Xbox-shaped
`sensor_msgs/Joy` (8 axes, 11 buttons) to each `<boat>/joy`, with `joy_to_helm`,
`helm_manager`, `asv_helm` and `asv_sim` in the loop, and checks the node set (one
`asv_sim`, twelve nodes per boat, plus a `joy_node` each with `--joysticks`), every boat's TF frames, the graph
check below, that driving one boat moves only that boat, that with all boats driven
at once an idle boat stays put and only the boats given a rudder turn, and that
every boat's `cube_bathymetry/coverage_catalog` and `coverage_tiles` deliver, and
that `/marine/platforms` carries one platform per boat with the roster's name
and colour (the CAMP tab names and colours). With `--start-launch` it passes
`--boats` and `--roster` on to the launch (`--joysticks` starts the real
`joy_linux` drivers instead of `enable_joysticks:=false`), stops the launch on any
exit including SIGINT and SIGTERM, and fails at once if the launch exits early.
It resets the boats at the end and exits non-zero if a check fails. It needs the
datum grids above: the launch refuses to start without them. Run it on a
private `ROS_DOMAIN_ID` and leave discovery at its default: with
`ROS_LOCALHOST_ONLY=1` (or `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`) a second
process on the machine saw only part of the roughly 50 processes of the four-boat
stack.

`check_multi_boat_graph.py` is the graph part alone, for a launch that is already
running: no duplicate node names, every TF frame has exactly one parent, and no
boat publishes into another boat's namespace (nor a topic outside the boats'
namespaces, other than the shared ones: `/marine/platforms`, `/tf`, `/tf_static`,
`/diagnostics`, `/rosout`, `/parameter_events`, `/clock`). It only looks at
publishers, and it treats the root-namespace `asv_sim` as belonging to no boat, so
a subscription to another boat's topic or a wrong topic published by `asv_sim`
itself is not caught here (the self-test's presence checks cover `asv_sim`'s
per-boat topics).

### The lifecycle guard

Each boat runs nine lifecycle nodes, configured and activated by one-shot chains in the
per-package launch files. Intermittently a chain stops (a `change_state` reply or a
transition event is lost under load) and a node sits in `inactive` for the whole session:
no sonar, no datum frames, a boat that never drives (issue #96). `lifecycle_guard` starts
one extra process, `launch_manager_proto converge`, which reads each boat node's state and
takes it the rest of the way, leaving a node alone until its state has been quiet for three
seconds so that a slow chain is not raced. It prints what it did (`[launch_manager_proto]
/clownfish/joy_to_helm: sending activate from inactive`) and exits 0 once all nodes are
active and no new one has appeared for fifteen seconds, or prints which nodes it could not
fix. It needs `launch_manager_proto` (a dependency of this package).

### Demo truth bathymetry

The 5 m chart grid is derived from charts. The demo samples the best bathymetry we have: the
CCOM GIS "WGOM, LI, SNE Bathymetry and Backscatter Compilation", fetched from its public image
services and mosaicked by `mbes_sim`'s `build_demo_bathy`. The grid is generated, not
committed. Build it once per machine (about 10 seconds, needs network access to
`gis.ccom.unh.edu`):

```bash
ros2 run mbes_sim build_demo_bathy --bbox -70.7405 43.0537 -70.6695 43.0937 \
    --out ~/data/sim/mbes_truth/portsmouth_demo_utm19n.tif
```

The box is `WEST SOUTH EAST NORTH` in degrees, about 5.9 km by 4.6 km. The output is a
UTM 19N GeoTIFF, depth positive down, 2 m cells by default (`--resolution` overrides), tiled
LZW Float32, with `portsmouth_demo_utm19n.tif.provenance.json` beside it (service URLs, every
tile request box, fetch time, checksums, coverage, options). It prints a coverage summary and
the measured difference between the compilation and the chart grid where both exist. An
existing output is refused without `--force`; a failed run leaves nothing behind. `--work-dir`
keeps the fetched tiles so a rerun within 24 hours does not fetch again; `--regional` adds the
16 m regional service as a fill; `--chart-grid` replaces the fill grid.

Fill precedence per cell: 2 m compilation, 4 m compilation, 16 m regional (only with
`--regional`), then the packaged chart grid. The chart grid has no nodata: land and drying
cells are negative depths, which `mbes_sim` does not ping, and they stay negative in the demo
grid. The grid's nodata value (-9999) appears only outside the chart extent, and `mbes_sim`
returns no sounding for such a cell. Each `mbes_sim` node loads the whole grid (about 27 MB
for the box above); keep the box to the demo area.

Sources and attribution: Bathymetry: WGOM, LI, SNE Bathymetry and Backscatter Compilation, UNH
Center for Coastal and Ocean Mapping / Joint Hydrographic Center, via the CCOM GIS image services
`WGOM_LI_SNE_Bathymetry_2m_WMAS`
(`https://gis.ccom.unh.edu/server/rest/services/WGOM-LI-SNE/WGOM_LI_SNE_Bathymetry_2m_WMAS/ImageServer`)
and `WGOM_LI_SNE_BTY_4m_20230922_WMAS_IS`
(`https://gis.ccom.unh.edu/server/rest/services/WGOM-LI-SNE/WGOM_LI_SNE_BTY_4m_20230922_WMAS_IS/ImageServer`).
The services and their portal items state no licence or copyright terms (checked 2026-10-14);
contributing surveys are named by the `WGOM_LI_SNE_Footprints` map service. **Licence statement:
pending, to be requested from CCOM GIS.** The 2 m cell size is the product's, not the source
surveys' (0.5 to 2 m per the footprint layer).

**Vertical datum caveat.** The vertical datum of the compilation is not stated in the service
metadata or its portal item (**confirmation pending from CCOM GIS**). The demo treats it as
comparable to the chart grid (MLLW) so the simulated tide applies the same way, and applies no
correction. The coverage summary reports the measured offset between the two where they overlap
(compilation minus chart; the build on 2026-10-14 gave a median of 0.89 m). It is suitable for
the demo; do not call it survey truth until CCOM GIS confirms the datum.

### Target survey area for the coverage scorer

`coverage_assessment` (in `cube_bathymetry`) scores coverage against target areas
it receives as `marine_interfaces/SurveyArea` on a latched `survey_area` topic
(reliable, transient_local, depth 100). CAMP only sends a survey area out as a mission
plan, which this demo does not run, so `publish_survey_area.py` reads the area from a
saved CAMP project file and publishes it:

```bash
export ROS_DOMAIN_ID=42   # the demo's domain
# the shipped demo polygon (config/demo_target_polygon_camp.json), S-44 Order 1a
ros2 run marine_simulation publish_survey_area.py
# your own file
ros2 run marine_simulation publish_survey_area.py --ros-args -p file:=$HOME/my_target.json
```

To draw a new target: in CAMP add a survey area (its outline is the polygon), then
File > Save. Point `file` at that project file. CAMP's File > Open reads the same file to show the
outline, so one file serves both. The node reads the file once at startup and keeps
running (the latched sample lives in the publisher) so a scorer that starts later still
receives it; to pick up
an edit, restart the node. The stamp is wall-clock time (not the simulation clock, which
reads 0 until `/clock` arrives), and the scorer replaces an area when the same id arrives
again with a newer stamp, so no scorer reset is needed.

Run it in the **root namespace** (as above): the topic is then `/survey_area`, which
is what the scorer's example `coverage_assessment.yaml` subscribes to.

| Parameter | Default | Meaning |
|---|---|---|
| `file` | installed `config/demo_target_polygon_camp.json` | CAMP project file; every `SurveyArea` item in it (nested groups included) is published, its `Waypoint` children are the vertices |
| `topic` | `survey_area` | Relative, so it follows the node's namespace: under a launch namespace it becomes `/<ns>/survey_area`, which the scorer would not hear |
| `area_id` | empty | Empty uses each CAMP item's label (`area0000`, ...); non-empty is accepted only for a file with exactly one area |
| `priority` | `0` | `SurveyArea.priority` (int16, lower is more urgent) |
| `standard_name` | `demo` | `SurveyStandard.name` |
| `standard_a`, `standard_b` | `0.5`, `0.013` | `allowed(depth) = sqrt(a^2 + (b*depth)^2)`; the defaults are IHO S-44 Order 1a |

The node exits with status 1 and a message on stderr when it is given: a missing,
unreadable or non-JSON file, a file with no `SurveyArea`, an area with fewer than 3
distinct vertices (a repeated closing point counts once), more than 10000 vertices, more
than 100 areas (the latched history is 100 deep, so a late scorer would lose the rest; the scorer itself holds only 20 by default, its `max_areas`, and refuses further new ids with an ERROR), a
file over 16 MB or nested too deeply, or a vertex without a finite latitude in [-90, 90] and longitude in
[-180, 180], two areas with one label, an `area_id` for a multi-area file, a priority
outside int16, a parameter of the wrong type, or a standard the scorer would read as "not set" (`a` and `b` both 0, or
either negative or not finite): that would leave the scoreboard at 0 % with no
explanation.

Checked against the scorer's example config by reading both (not yet against a running
graph with the scorer): the scorer's `/survey_area` matches this node's topic in the root
namespace; `cube_bathymetry` publishes a relative `grid` in `<boat>/sensors/mbes`, so
`/<boat>/sensors/mbes/grid` matches `grid_topics`; the demo's TF frames are
`<boat>/map`, `<boat>/map_tide` and `<boat>/base_link`, matching `map_frame`,
`water_surface_frame` and `water_surface_boat_frame`. Starting the scorer and this node
together with the boats is the single demo launch (issue #94).

### Known limits

- The nav stack is not wired (`enable_nav`); there is no bridge or command bridge, so the operator mode buttons do nothing.
- The tide topic `/asv_sim/environment/tide_level` is shared by every boat on purpose.
- `asv_sim`'s `set_pose` service and `sim_reset` topic work per boat (they were both broken before issue #88).
- Four `mbes_sim` nodes each load the whole truth grid (69 MB for the packaged chart grid, about 27 MB for the demo truth grid); expect memory use to scale with the boat count.

### Tests

```bash
source setup.bash && ./simulation_ws/build.sh asv_sim marine_simulation
./simulation_ws/test.sh asv_sim marine_simulation
```

## Demo launch manager

`demo_manager.py` runs the demo under `launch_manager_proto` (issue #97), the prototype of
the persistent launch and lifecycle manager designed in
`unh_marine_autonomy/docs/launch_manager.md`. Since issue #102 it is the only way to start
the demo: `run_demo.sh` calls it. The manager's own README describes the manager; this is
how the demo uses it.

```bash
export ROS_DOMAIN_ID=...                 # a private one
run_demo.sh                                                     # the helper's command
ros2 run marine_simulation demo_manager.py --layout my_layout.yaml   # the same, by hand
ros2 run marine_simulation demo_manager.py --profile headless   # no CAMP, no window placement
ros2 run marine_simulation demo_manager.py --boats bluefin,clownfish --no-joysticks --no-layout
ros2 run launch_manager_proto launch_manager_proto status       # what is it doing?
```

`config/demo_manager.yaml` has five groups and three profiles:

| Group | Launch file | Rule |
|---|---|---|
| `boats` | `demo_boats_launch.py` (with `lifecycle_guard:=false`) | READY when every boat's nine lifecycle nodes are `active`; `follows: [camp]` |
| `camp` | `demo_camp_launch.py` (CAMP on the demo's private settings and an emptied live tile cache, via `marine_simulation.demo_support.camp_actions`; not CAMP's own `camp_launch.py`, which would show the operator's settings and an earlier session's coverage) | `requires: [boats]`, `restart: never`: starts only once the boats are READY |
| `target_area` | `demo_target_area_launch.py` (`publish_survey_area.py`, latched, on the target file) | READY when `/survey_area_publisher` is in the graph; `follows: [camp]` |
| `scorer` | `coverage_assessment_launch.py`, parameters generated from the roster by `demo_support.scorer_parameters` (map frame = the first boat's) | `requires: [boats, target_area]`, `follows: [camp]`, lifecycle node `/coverage_assessment` to `active` |
| `rqt` | `demo_rqt_launch.py` (`rqt --perspective-file config/demo.perspective` on a first start or `--rqt-fresh`, `--perspective @demo.perspective` after; see "rqt and the coverage plugin") | no `requires`, `follows: [camp]`, `restart: never`; a missing `rqt` is a log message, never a failed demo |
| `layout` | `demo_layout_launch.py` (`place_windows.py`, once) | `requires: [camp]`, `follows: [camp]`, `restart: never` (run once, see "Window layout") |

Profiles: `demo` (all five), `headless` (boats, target area and scorer), `boats` (boats
only); `--no-layout` takes `layout` out of every profile. The groups that **follow** CAMP stop
when its window closes and the manager exits, so the terminal returns. Boat names come from
`config/demo_roster.yaml` only; the configuration has placeholders that the script fills in.
The helpers the script and the launch files share (`marine_simulation.roster`,
`marine_simulation.demo_support`) are an installed Python package; nothing is loaded by file
path, and a test pins that.

The manager is the only thing that configures and activates the boats' lifecycle nodes. It
sends every transition itself, checks the state first and again just before sending, and a
lost reply cannot strand a node. A node that the launch's `respawn=True` restarts comes
back `unconfigured` and is repaired. **Group stop and start work** (`launch_manager_proto
command stop boats`, `... start boats`); a stopped group's processes are all gone.

**What a helper sees when something is wrong.** CAMP only opens once the boats are READY. If
a boat cannot be brought up, the terminal shows an ERROR line naming the node (`group boats
FAILED: lifecycle node /clownfish/mbes_sim FAILED: configure failed 5 times: ...`) and
`launch_manager_proto status` shows the same, with `!` marking every node that is not
active. The fix is to close the manager (Ctrl-C) and run it again.

The lifecycle guard of the plain launch is not as loud: a node it cannot fix is reported by
the guard's own last line (`did not converge ... saw N of M expected node(s)`) and by the exit
code of the `lifecycle_guard` process in the launch output, and the rest of the launch keeps
running.

Host-only test of the whole thing (about two minutes, needs the datum grids and a private
domain above 100; it never starts CAMP or any GUI):

```bash
ROS_DOMAIN_ID=173 ./simulation_ws/test.sh marine_simulation    # test_demo_manager_live.py
```
