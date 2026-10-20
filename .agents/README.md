# Agent Guide: unh_marine_simulation

> ROS 2 packages for simulating marine autonomous surface vehicles (ASVs), including dynamics, sensors, helm controllers, and Gazebo world generation.

## Package Inventory

| Package | Language | Description |
|---------|----------|-------------|
| `asv_sim` | Python | ASV dynamics simulator with configurable platform models and environment |
| `asv_sim_msgs` | C++ (msg gen) | Service definitions for the ASV simulator (`SetPose`) |
| `asv_helm` | C++ | Converts Twist/Helm commands to throttle and rudder outputs |
| `vrx_project11` | C++ | WAM-V differential-thrust helm with nav2 integration |
| `mbes_sim` | Python | Multibeam echosounder simulator using bathymetry grids |
| `marine_charts_to_gazebo_world` | Python | Generates Gazebo Harmonic SDF worlds from S57 ENC chart data |
| `portsmouth_nh_gazebo` | Python | Pre-configured Gazebo world for Portsmouth NH harbor |
| `launch_manager_proto` | Python | Prototype persistent launch and lifecycle manager (convergence loop, groups, profiles, status/command); **no marine dependency**, the seed of the future `ros2launch_manager` repository; see `launch_manager_proto/README.md` |
| `marine_simulation` | CMake (config, launch, scripts) | Aggregation package with scenario launch files, configs, and the multi-boat demo (launch, roster, self-test, graph check, `demo_manager.py` and its configuration) plus the whole display, started by one command (`run_demo.sh` runs `demo_manager.py`, which runs the boats, CAMP, the target-area publisher, the scorer and the window placement as manager groups); the shared helpers are an installed Python package (`marine_simulation.roster`, `marine_simulation.demo_support`); see `marine_simulation/README.md` |

## Repository Layout

```
unh_marine_simulation/
├── asv_sim/                           # ASV dynamics simulator
│   ├── asv_sim/                       #   Python module (dynamics, environment, model, platform)
│   ├── config/                        #   Platform configs (ben.yaml, cw4.yaml, drix.yaml, demo.yaml, ...)
│   └── test/                          #   Linting, tide tests, test_multi_platform.py (in-process)
├── asv_sim_msgs/                      # Service definitions
│   └── srv/SetPose.srv
├── asv_helm/                          # Helm controller (Twist → throttle/rudder)
│   └── src/asv_helm_node.cpp
├── vrx_project11/                     # WAM-V platform integration
│   ├── src/wamv_helm.cpp
│   ├── launch/                        #   7 launch files (sim, nav, operator)
│   ├── config/                        #   nav2_params.yaml, wamv.yaml
│   └── urdf/                          #   WAM-V URDF model
├── mbes_sim/                          # Multibeam sonar simulator
│   ├── mbes_sim/mbes_sim.py
│   ├── mbes_sim/bathy_grid.py        #   Nearest-cell GDAL lookup (None off the grid / on nodata)
│   ├── mbes_sim/demo_bathy.py        #   `build_demo_bathy`: CCOM 2 m/4 m compilation -> demo truth grid
│   ├── test/                         #   pytest: bathy_grid, demo_bathy (fake image service)
│   └── data/US5NH02M.tiff            #   Chart bathymetry grid (69 MB)
├── marine_charts_to_gazebo_world/     # Chart-to-Gazebo converter
│   └── marine_charts_to_gazebo_world/ #   generate_world, s57_reader, terrain, heightmap, ...
├── portsmouth_nh_gazebo/              # Portsmouth NH Gazebo world
│   ├── config/                        #   portsmouth.yaml, isles_of_shoals.yaml, ...
│   └── launch/                        #   harbor_launch.py, isles_of_shoals_launch.py, ...
├── launch_manager_proto/              # Launch/lifecycle manager prototype (generic, issue #97)
│   ├── launch_manager_proto/          #   lifecycle_core, lifecycle_rclpy, config, manager_core, manager, cli
│   └── test/                          #   fakes + fake lifecycle node, core/config/process tests
└── marine_simulation/                 # Scenario launch files
    ├── marine_simulation/             #   installed Python package: roster.py (boats), demo_perspective.py (the rqt perspective and how rqt starts on it), demo_support.py (CAMP settings, demo lock, scorer parameters, CAMP/placement/publisher actions)
    ├── launch/                        #   sim_test, sim_demo, sim_drix, demo_boats_launch.py, and the manager's groups: demo_camp_launch.py, demo_target_area_launch.py, demo_layout_launch.py, ...
    ├── config/                        #   bob_platform.yaml, udp_bridge.yaml, demo_roster/params/joysticks/layout/manager.yaml, demo.perspective (rqt, generated from the roster), demo_camp_profile.conf, demo_camp_view.yaml (optional view override; default = fit to the target), demo_target_polygon_camp.json
    ├── scripts/                       #   demo_boats_selftest.py, check_multi_boat_graph.py, demo_manager.py, place_windows.py, run_demo.sh, publish_survey_area.py
    ├── test/                          #   pytest: boats launch fail-fast checks, demo_support helpers, graph check, demo manager and its groups, run_demo.sh, survey-area publisher
    └── README.md                      #   demo boats: arguments, pad checklist, reset notes
```

## Architecture Overview

The repo provides a three-level simulation architecture:

1. **Physics simulation** (`asv_sim`) — Dynamics engine that models thrust, drag,
   rudder response, and environmental forces (current, wind). Each platform is
   configured via YAML files that define propulsion type (jet/prop), mass, drag
   coefficients, and maximum RPM.

2. **Sensor simulation** (`mbes_sim`) — Multibeam echosounder that generates sonar
   detections from a bathymetry grid, publishing `SonarDetections` and `PointCloud2`.

3. **3D visualization** (`marine_charts_to_gazebo_world`, `portsmouth_nh_gazebo`) —
   Generates Gazebo Harmonic worlds from S57 ENC chart data and ETOPO bathymetry.

**Helm controllers** (`asv_helm`, `vrx_project11/wamv_helm`) convert high-level
velocity commands (`cmd_vel`) into platform-specific actuator outputs (throttle/rudder
or differential thrust).

**Scenario launch files** in `marine_simulation` compose these components into
complete simulation setups with platform-specific configs from external repos
(`ben_project11`, `drix_project11`).

Data flow: `cmd_vel` → helm → `throttle`/`rudder` → `asv_sim` → position/orientation → `mbes_sim` → sonar data

## Key Files to Read First

1. `asv_sim/asv_sim/asv_sim_node.py` — Main simulator node; creates platforms from config
2. `asv_sim/config/ben.yaml` — Platform-instance configuration (model reference, frame, initial pose); see `cw4.yaml` for model-level dynamics parameters
3. `asv_helm/src/asv_helm_node.cpp` — Helm controller showing Twist-to-actuator conversion
4. `asv_sim_msgs/srv/SetPose.srv` — Service interface for resetting platform position
5. `marine_simulation/launch/sim_robot_launch.py` — Robot simulation launch file (dynamics, helm, sensors)
6. `mbes_sim/mbes_sim/mbes_sim.py` — Sonar simulator showing lifecycle node pattern
7. `marine_simulation/launch/demo_boats_launch.py` — Several boats at once: per-boat namespace groups built from `config/demo_roster.yaml`, one shared `asv_sim`
8. `marine_simulation/scripts/demo_manager.py` — The one start command for the whole demo display (`scripts/run_demo.sh` calls it): fills `config/demo_manager.yaml` from the roster and runs the groups boats, camp (`demo_camp_launch.py`, CAMP on a settings file generated on every start), target_area (`demo_target_area_launch.py`), scorer, rqt (`demo_rqt_launch.py`: `rqt --force-discover` on the shipped `config/demo.perspective` (Survey Coverage plus one Ping Profile per boat, generated from the roster by `marine_simulation.demo_perspective`): imported with `--perspective-file` on a first start or `--rqt-fresh`, started by the name rqt gives an import, the hidden `@demo.perspective`, after; on the operator's persistent rqt settings, not placed, `follows: [camp]`, `restart: never`) and layout (`demo_layout_launch.py`, `scripts/place_windows.py` once)

## Build & Test

```bash
# From the layer workspace directory (layers/main/simulation_ws/)
colcon build --packages-select asv_sim asv_sim_msgs asv_helm vrx_project11 mbes_sim marine_charts_to_gazebo_world portsmouth_nh_gazebo launch_manager_proto marine_simulation

# Testing requires setup.bash in the same shell
source ../../../.agent/scripts/setup.bash && colcon test --packages-select asv_sim && colcon test-result --verbose
```

Known build issues:
- `mbes_sim` includes a 69 MB chart bathymetry TIFF (`data/US5NH02M.tiff`); initial clone is large
- `marine_charts_to_gazebo_world` requires GDAL (`python3-gdal`) and may fail to build if GDAL headers are missing
- `portsmouth_nh_gazebo` downloads ETOPO data on first launch and caches it in `~/.cache/marine_charts_to_gazebo_world/`
- `vrx_project11` depends on `marine_interfaces` and `marine_autonomy` from the core layer

## Cross-Layer Dependencies

| Package | Depends On | Layer | What It Imports |
|---------|-----------|-------|-----------------|
| `asv_helm` | `marine_interfaces` | core | `marine_interfaces/msg/Helm`, `marine_interfaces/msg/Heartbeat` |
| `asv_helm` | `marine_autonomy` | core | Build-time (C++ headers, PID controller) and runtime dependency |
| `vrx_project11` | `marine_interfaces` | core | `marine_interfaces/msg/Heartbeat` |
| `vrx_project11` | `marine_autonomy` | core | Runtime dependency |
| `mbes_sim` | `marine_acoustic_msgs` | underlay | `marine_acoustic_msgs/msg/SonarDetections` |
| `mbes_sim` | `marine_autonomy` | core | `marine_autonomy.nav`, `marine_autonomy.geodesic` |
| `marine_simulation` | `cube_bathymetry` | sensors | Runtime (rviz plugin) |
| `launch_manager_proto` | `ros2launch_session` | underlay | `LaunchSession.from_service()` (one shared `LaunchService`); no marine package, enforced by `test_boundary.py` |
| `marine_simulation` (whole display, `demo_manager.py`) | `camp`, `coverage_assessment`, `geographic_msgs`, `wmctrl` (apt) | ui / sensors / system | Runtime: CAMP executable, scorer launch and example config, window placement with `wmctrl` |
| `marine_simulation` (demo boats) | `ben_description`, `helm_manager`, `joy_to_helm`, `marine_autonomy`, `mru_transform`, `cube_bathymetry` | platforms / core / sensors | Runtime: URDF xacro, per-node launch files, `joy_linux` driver from apt (`ros-jazzy-joy-linux`) |

## Common Pitfalls

- **Default branch is `jazzy`**, not `main`. Always verify with `gh repo view --json defaultBranchRef`.
- **Platform configs are name-sensitive**: `asv_sim` reads a `platforms` parameter (list of names) and looks for matching YAML files. A typo in the platform name causes a silent failure.
- **Lifecycle nodes**: `mbes_sim` uses ROS 2 lifecycle — it must be configured and activated before it publishes data. Launch files handle this, but manual testing requires explicit state transitions.
- **Coordinate frame**: `asv_sim` publishes in geographic coordinates (lat/lon via `NavSatFix`), not in a local frame. Consumers must handle the geographic-to-local transform.
- **S57 ENC data**: `marine_charts_to_gazebo_world` and `portsmouth_nh_gazebo` require S57 ENC chart data. Set `ROS_S57_ENC_ROOT` environment variable to the ENC data directory, or the world generation will produce a flat terrain.
- **`asv_sim` has a default current of 1.0 m/s toward 090.** `environment.current.speed` defaults to 1.0, so an undriven boat drifts east at about 2 knots unless a launch sets it to 0 (`demo_boats_launch.py` does, via `current_speed`; `sim_robot_launch.py` does not).
- **An unknown `asv_sim` platform name is not an error.** `Platform` declares defaults for every key, so a name with no config becomes a `default`-model boat at 0,0. Only `demo_boats_launch.py` checks names against its roster.
- **`SetParameter`, `SetRemap` and `SetParametersFromFile` append to the context's list in place, and a `GroupAction` only copies the dict that holds it.** Once an enclosing scope already holds the list, a value set inside one group survives the group and lands on every later node. `global_params` exists as soon as any top-level `SetParameter` ran (`sim_robot_launch.py` starts with `use_sim_time`), so the real single-vehicle launches **do** leak (found by capturing the parameters each node received): `sonar_frame_id`, `ping_interval` and `grid_file` from the mbes_sim group reach `detections_to_pointcloud` and the cube, and `sea_surface_frame` reaches `chart_datum` and nav2. `ros_remaps` leaks the same way, but only once an enclosing scope already holds a `ros_remaps` list; a first `SetRemap` inside a group creates the list in the group's own copy and discards it. The demo launch avoids all of this with copy-on-write `ScopedSetParameter` / `ScopedSetRemap`, which are defined in `marine_simulation/launch/demo_boats_launch.py` (a launch file, not importable from elsewhere; the roster functions it uses live in the importable `marine_simulation.roster`) and pinned by a `LaunchService` test in `test_demo_boats_launch.py`. There is no scoped `SetParametersFromFile`; the demo uses one, unscoped, at the top level only. Use scoped classes in any launch that builds more than one namespaced group, and never rely on a leak: see the next bullet.
- **Frame defaults that are not prefixed collide at the second vehicle.** `chart_datum` and `sea_surface_estimator` default `mhhw_frame` to `chart_datum_mhhw`, `sea_surface_estimator` defaults `chart_datum_frame` to `chart_datum`, and `cube_bathymetry` defaults `base_link_frame` to `base_link`. The demo launch sets all of them per boat. `sim_robot_launch.py` never sets the cube's `base_link_frame`: `cube_bathymetry` gets `ben/base_link` only because the leak above carries the `detections_to_pointcloud` group's `base_link_frame` into it. So fixing the leak in the real launches must be done together with an explicit cube `base_link_frame`, or the cube falls back to `base_link` (follow-up issue; plan PR two keeps the explicit cube parameter as its own commit).
- **`joy_linux` reads `/dev/input/jsN`, not evdev.** Bind a pad to a USB port with the by-path link ending `-joystick` (not `-event-joystick`); the launch refuses a link that does not resolve to a `jsN` node. `joy` (SDL) cannot tell identical pads apart. `joy_to_helm` silently ignores a pad that reports fewer than 11 buttons.
- **The demo needs the datum grids on the host.** `chart_datum` loads `~/data/world/datum/geoid/us_noaa_g2018u0.tif` and `vdatum/*_mllw.gtx`; if they are absent it only warns and `<boat>/chart_datum` never appears, so `demo_boats_launch.py` checks for them and refuses to start.
- **A four-boat stack (about 50 processes) is not fully discoverable with `ROS_LOCALHOST_ONLY=1`.** Observed: a second process saw only part of the graph. Use default discovery on a private `ROS_DOMAIN_ID` for the self-test.
- **Empty string parameters cannot be `-p` overrides** (`Failed to parse global arguments`); put them in a parameter file (the demo's `draft_dir` / `prior_store_dir` for `cube_bathymetry`).
- **`marine_simulation` lint was already failing** (copyright, flake8 I100, pep257 D213 in `bizzyboat_massabesic_launch.py`, `gazebo_*_launch.py`, `simulator_launch.py`); new files there follow the D213 style (summary on the second line).
- **A Python (`rclpy`) lifecycle node dies on a transition that is invalid for its state.** `Transition is not registered` escapes the service callback and the process exits 1 (C++ nodes just answer `success=false`). Two writers on one node therefore kill it: a `launch_ros` autostart chain plus anything else. Inside `launch_manager_proto` the manager is the only writer (it does not register launch_ros's `ChangeState` handler for groups with a `lifecycle` section) and re-reads right before every request; the standalone `converge` guard coexists with a launch's chains by waiting for the state to be quiet, which narrows the race but cannot close it.
- **`LaunchSession.from_service()` shuts the whole shared `LaunchService` down when its `with` block exits**, so a manager holds each group's context open (one thread per group) until it exits itself. `LaunchService.run()` must be on the main thread, `shutdown_when_idle=False` or an all-stopped manager exits, and `rclpy.init()` must be given `SignalHandlerOptions.NO` or its SIGINT handler replaces launch's and ctrl-c stops nothing. launch leaves SIGTERM at its default disposition (it records a handler, installs none), so a plain `kill` orphans every process unless the program installs its own.
- **Restarting a launch description in the same `LaunchService` leaves the old one's event handlers registered**, and `launch_ros` lifecycle chains subscribe by node name, so the old chains answer the new processes. `launch_manager_proto` records handlers by the `LAUNCH_MANAGER_GROUP` environment tag and unregisters them when a group has stopped, except `OnShutdown` ones (launch_ros registers the handler that stops its adapter thread from whichever group first needs the adapter; removing it hangs the process at exit).
- **Never leave processes of a test behind.** Use `kill` on a pid or process group you started, never `pkill -f`; the live check (`marine_simulation/test/test_demo_manager_live.py`) refuses to run without a private `ROS_DOMAIN_ID` above 100, and a SIGKILLed manager orphans its children (they keep the node names, and a second launch then sees duplicates).
- **CAMP's state in the demo is a generated settings file, not the operator's.** `demo_camp_launch.py` (the manager's `camp` group, via `marine_simulation.demo_support.camp_actions`) starts CAMP with `XDG_CONFIG_HOME=~/.local/state/marine_simulation_demo/xdg_config` and rewrites `UNH-CCOMJHC/CCOMAutonomousMissionPlanner.conf` there on every start from `config/demo_camp_profile.conf` plus one live coverage layer per roster boat, and the view: **CAMP's own saved window and view win** (`demo_support.carry_over` copies `MainWindow/geometry|state|mapCenter|mapScale` and `[MapView]` from the previous file as raw lines, byte for byte; the geometry is a Qt-escaped byte array, never re-encoded), and the generated fitted view is only the first-start default (or `--camp-fresh`, a flag of `demo_manager.py`, argument `camp_fresh` of `demo_camp_launch.py`; honoured once per manager process, so a restart of the camp group keeps what CAMP saved since; `seed_camp_settings` puts the old file back when the write after the reset fails). The faithful view restore needs a CAMP with rolker/camp#242 (resize anchor keeps the centre): without it the window restores but the view shifts when it is maximized or resized at startup. GNOME's `org.gnome.mutter auto-maximize` (default true) maximizes a new window covering ~80 % of the work area, so a saved big window can come back maximized over rqt; `run_demo.sh` warns (never changes it) and the README tells the operator to set it false once. The demo does not place CAMP's window (the shipped `demo_layout.yaml` has no windows; a layout with none is a clean no-op), because CAMP restores its own and a resize from outside fights its deferred view restore (camp#242). A CAMP setting that is not carried or in the template is not restored (no chart lists). The template's `[LiveCoverageLayer]` section (colormap `viridis`, manual range -59.4 to -29.4) is copied into every boat's live layer: the tiles' `depth` band is the WGS84 ellipsoid height, **positive up**, so a depth range of 0 to 30 m at Portsmouth is -59.4 to -29.4 (`range_min` is the deep end). The map centre is a Qt `QPointF` in Web Mercator metres; `qt_point_variant` writes Qt's own INI encoding of it and is pinned against Qt-written samples. Its directory is deleted on every start, so `reset_settings_root` refuses anything but that exact path (no symlink, marker file present).
- **`camp_launch.py` takes no arguments.** `demo_camp_launch.py` therefore starts the `CCOMAutonomousMissionPlanner` executable directly (rolker/camp#240 asks for launch arguments); keep the two in step until that lands.
- **Window placement needs X11 and `wmctrl`, and cannot be tested here.** `place_windows.py` is tested with a fake `wmctrl`; the real WM_CLASS of CAMP and the `wmctrl -e` behaviour on the owner's window manager are checked at the rehearsal. `demo_manager.py` refuses to start (before any group runs) on Wayland, without `wmctrl`, or with a layout naming a monitor that is not connected, by running `place_windows.py --check`.
- **Extra boats-launch arguments go through `name:=value` after the manager's options** (`run_demo.sh tide_speed_factor:=1`). `demo_manager.py` checks each name against the `DeclareLaunchArgument`s of `demo_boats_launch.py` (`demo_support.declared_launch_arguments`, read at run time) and refuses an unknown one, or one the `boats` group in `demo_manager.yaml` already sets (`boats`, `roster_file`, `enable_joysticks`, `joystick_config`, `lifecycle_guard`), with `THE DEMO DID NOT START` and exit 2. They reach only the `boats` group. The old `demo_launch.py` forwarded any `name:=value` to every included launch without checking.
- **Scorer parameters are generated from the roster**, from the example `coverage_assessment.yaml` installed by the cube repo, into a temporary directory `/tmp/demo_manager_*` that `demo_manager.py` removes on exit. Do not copy the example into this repo: its boat names would become a second roster. `demo_manager.py` reuses `marine_simulation.demo_support.scorer_parameters` (it does not keep its own copy): without the first boat's `map_frame` the scorer waits forever for a plain `map` frame and never assesses.
- **Closing the CAMP window stops the whole demo** (`follows: [camp]` on boats, target_area, scorer and layout in `demo_manager.yaml`; the manager then exits). A second demo is refused by a flock on `~/.local/state/marine_simulation_demo/lock` that `demo_manager.py` takes once for the process lifetime (the launch files its groups run never take it: a lock per group start would be refused on a restart); a CAMP already running is refused by a process scan before any group starts. CAMP's live tile cache is redirected into the same state directory and emptied each start, because it lives outside the QSettings file.
- **Maximised mode never sends a monitor-sized `wmctrl -e`, and checks `_NET_WM_STATE` with `xprop`.** wmctrl -lG offsets a decorated window by its frame once more, so the check takes `_NET_FRAME_EXTENTS` (same xprop call) out of the reported rectangle before the bounds test. mutter treats a client resized to exactly the monitor's geometry as full screen (no title bar) and then ignores the maximise, while the window still covers 100 % of the monitor; so the window goes to a centred half-size rectangle first and is accepted only when maximised and not full screen (found at the live run; the fake desktop in `test_place_windows.py` reproduces the heuristic).
- **`wmctrl -b` reads at most two properties after `add`/`remove`/`toggle`.** A four-property clear silently left `maximized_horz` set; the fake `wmctrl` in `test_place_windows.py` now rejects such a call.
- **The packaged chart grid `US5NH02M.tiff` has no nodata tag and no NaN.** Land and drying cells are negative "depths" (minimum -10), and `mbes_sim` does not ping where `chart_depth < 0`. `build_demo_bathy` keeps that convention: its -9999 nodata appears only outside the chart extent, and `BathyGrid.getDepth` returns `None` there.
- **CCOM GIS 2 m and 16 m image services mark nodata as 3.4e38 by VALUE** (the exported GeoTIFF carries no nodata tag); the 4 m service uses -99999. `demo_bathy` masks anything beyond +-1e4 m. ArcGIS also answers some errors with HTTP 200 and a JSON body, so the fetch checks for a TIFF header and retries.
- **The demo truth grid is generated, not committed** (`ros2 run mbes_sim build_demo_bathy`, see `marine_simulation/README.md`); `demo_boats_launch.py` falls back to the chart grid with a printed message when it is absent.
- **`survey_area` is latched: a publisher must be transient_local, and `ros2 topic echo` needs `--qos-durability transient_local --qos-reliability reliable` to see it.** `publish_survey_area.py` (CAMP project file to `marine_interfaces/SurveyArea`, for the `coverage_assessment` scorer) uses reliable, transient_local, depth 100; a volatile publisher never reaches the scorer. Run it in the root namespace so the topic is `/survey_area`. It reads the file once; restart it to pick up an edit. A standard with `a = b = 0` means "not set" to the scorer (0 % meeting), so the node refuses it.
- **A run-once group (`layout`) is `restart: never`, not a failure when it ends.** A clean exit of the last process of a `restart: never` group sets the group `STOPPED` (detail `exited(0)`), stops only the groups that `follow` it (nothing follows `layout`), and `command start layout` runs it again; a non-zero exit is `FAILED` and logged at ERROR but does not stop the demo. The same rule closes CAMP: the difference is only who `follows` it. Never make a long-running group `restart: never` without checking who follows it, or its normal exit will not be reported as a failure.
- **The helpers the manager and the group launch files share are an installed Python package (`marine_simulation.roster`, `marine_simulation.demo_support`), installed with `ament_python_install_package`.** Import them normally. Do not load them (or `demo_boats_launch.py`) with `importlib.util.spec_from_file_location`: a test (`test_nothing_that_ships_loads_a_module_by_file_path`) fails on it, and a lock kept in a module that is loaded afresh by path on every group start is lost.
- **The target polygon goes to two places from one `--target` file.** CAMP opens it (the outline) and `target_area` publishes it to the scorer; by default both use the installed `config/demo_target_polygon_camp.json`. `survey_area` stays latched, see the earlier bullet.
- **The scorer refuses a target area over `max_raster_cells` (1,000,000 lattice cells, bounding box), so the demo scores at 2 m.** The shipped polygon is 2.5 million cells at the example's `cell_size: 1.0` (`Rejecting SurveyArea 'area0000': polygon spans 2.49846e+06 lattice cells`; found at the first live CAMP run, never by the selftest's small area) and about 625,000 at 2 m. `demo_support.scorer_parameters` therefore overrides `cell_size` with `DEMO_SCORER_CELL_SIZE = 2.0` (named, not an edit of the copied example); CUBE still maps at 1 m. `test_the_shipped_target_polygon_fits_the_scorers_raster_limit` fails when a polygon or cell size no longer fits. A rejected area publishes no assessment at all and the scorer stays `active`, so look for the log line.
- **`asv_sim` integrates drag and yaw damping implicitly and sub-steps long gaps (issue #84).** The explicit scheme this replaced overshot through zero once `dt * drag_coefficient * speed^2 / mass` exceeded about 2 (always after a multi-second stall), grew each step until `speed ** 3` overflowed, and killed the node. Do not go back to `speed += a * dt` with `a` computed from the start-of-step drag. A non-finite state value resets that one platform to rest and logs an ERROR naming it; look for `became nan` in the log if a boat sits still after a stall.

### `asv_sim` stepping parameters (verified against `asv_sim/model.py`)

| Parameter | Type | Default | Range | Effect |
|-----------|------|---------|-------|--------|
| `models.<name>.max_step` | double, s | `0.1` | 0.001 to 10 | Longest step integrated in one go; a longer gap is split into equal sub-steps no longer than this |
| `models.<name>.max_substeps` | int | `100` | 1 to 10000 | Most sub-steps per update; beyond `max_substeps * max_step` seconds the remainder of a gap is dropped, with a warning (at most one per 5 s per platform) |
