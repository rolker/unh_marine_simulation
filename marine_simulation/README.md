# marine_simulation

Scenario launch files and configs that compose the simulation packages. This file
covers the **demo boats** (Ocean Discovery Day, issues #87 and #88): several
simulated boats at once, each driven by its own gamepad, with no navigation stack.
The older launch files (`sim_robot_launch.py`, `simulator_launch.py`, ...) are
described in the repository's `.agents/README.md`.

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

The venue is Portsmouth Harbour (the packaged `mbes_sim/data/US5NH02M.tiff` grid).

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
| `mbes_grid_file` | `mbes_sim/data/US5NH02M.tiff` | Ground-truth bathymetry the simulated multibeams sample. |
| `cell_size` | `1.0` | CUBE cell size in metres. |
| `ping_interval` | `0.2` | Seconds between simulated multibeam pings. |
| `beam_count` | `120` | Beams per ping. |

The launch refuses to start (with the reason) when a boat name is unknown or
repeated, a roster value is not a finite number in range, the joystick list does
not match the roster, two boats share a pad (also when two links resolve to one
device), a configured pad is missing or its link resolves to something other than
a `jsN` node (the `-event-joystick` link), `joy_linux` is not installed,
`deadzone` is outside [0, 1) or `autorepeat_rate` is 2 Hz or less, a boolean
argument is anything but `true`/`1`/`yes`/`on` or `false`/`0`/`no`/`off`,
`mbes_grid_file` is not a file, `cell_size`, `beam_count` or `ping_interval` is
not positive (or not finite), `tide_speed_factor` or `current_speed` is negative
(or not finite; 0 is allowed for both), the datum grids above are missing, or
`enable_nav` is true.

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
- Four `mbes_sim` nodes each load the 69 MB grid; expect memory use to scale with the boat count.

### Tests

```bash
source setup.bash && ./simulation_ws/build.sh asv_sim marine_simulation
./simulation_ws/test.sh asv_sim marine_simulation
```
