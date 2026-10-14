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
| `mbes_grid_file` | empty | Ground-truth bathymetry the simulated multibeams sample. Empty means `$MBES_DEMO_GRID`, else `~/data/sim/mbes_truth/portsmouth_demo_utm19n.tif` when it exists, else `mbes_sim/data/US5NH02M.tiff` (the launch prints which and why). An explicit path must be a file. |
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
an explicit `mbes_grid_file` (or `$MBES_DEMO_GRID`) is not a file, `cell_size`, `beam_count` or `ping_interval` is
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
