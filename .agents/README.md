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
| `marine_simulation` | CMake (config, launch, scripts) | Aggregation package with scenario launch files, configs, and the multi-boat demo (launch, roster, self-test, graph check, `demo_manager.py` and its configuration) plus the whole-display launch (`demo_launch.py`, window placement, helper wrapper); see `marine_simulation/README.md` |

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
    ├── launch/                        #   sim_test, sim_demo, sim_drix, demo_boats_launch.py, demo_launch.py (whole display), demo_camp_launch.py (CAMP for the manager), ...
    ├── config/                        #   bob_platform.yaml, udp_bridge.yaml, demo_roster/params/joysticks/layout/manager.yaml, demo_camp_profile.conf, demo_camp_view.yaml, demo_target_polygon_camp.json
    ├── scripts/                       #   demo_boats_selftest.py, check_multi_boat_graph.py, demo_manager.py, place_windows.py, run_demo.sh, publish_survey_area.py
    ├── test/                          #   pytest: demo launch fail-fast checks, graph check, demo manager, survey-area publisher
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
8. `marine_simulation/launch/demo_launch.py` — The whole demo display in one launch: includes the boats launch and the scorer's own launch, starts CAMP on a settings file generated on every start, and runs `scripts/place_windows.py`

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
| `marine_simulation` (whole display) | `camp`, `coverage_assessment`, `geographic_msgs`, `wmctrl` (apt) | ui / sensors / system | Runtime: CAMP executable, scorer launch and example config, window placement with `wmctrl` |
| `marine_simulation` (demo boats) | `ben_description`, `helm_manager`, `joy_to_helm`, `marine_autonomy`, `mru_transform`, `cube_bathymetry` | platforms / core / sensors | Runtime: URDF xacro, per-node launch files, `joy_linux` driver from apt (`ros-jazzy-joy-linux`) |

## Common Pitfalls

- **Default branch is `jazzy`**, not `main`. Always verify with `gh repo view --json defaultBranchRef`.
- **Platform configs are name-sensitive**: `asv_sim` reads a `platforms` parameter (list of names) and looks for matching YAML files. A typo in the platform name causes a silent failure.
- **Lifecycle nodes**: `mbes_sim` uses ROS 2 lifecycle — it must be configured and activated before it publishes data. Launch files handle this, but manual testing requires explicit state transitions.
- **Coordinate frame**: `asv_sim` publishes in geographic coordinates (lat/lon via `NavSatFix`), not in a local frame. Consumers must handle the geographic-to-local transform.
- **S57 ENC data**: `marine_charts_to_gazebo_world` and `portsmouth_nh_gazebo` require S57 ENC chart data. Set `ROS_S57_ENC_ROOT` environment variable to the ENC data directory, or the world generation will produce a flat terrain.
- **`asv_sim` has a default current of 1.0 m/s toward 090.** `environment.current.speed` defaults to 1.0, so an undriven boat drifts east at about 2 knots unless a launch sets it to 0 (`demo_boats_launch.py` does, via `current_speed`; `sim_robot_launch.py` does not).
- **An unknown `asv_sim` platform name is not an error.** `Platform` declares defaults for every key, so a name with no config becomes a `default`-model boat at 0,0. Only `demo_boats_launch.py` checks names against its roster.
- **`SetParameter`, `SetRemap` and `SetParametersFromFile` append to the context's list in place, and a `GroupAction` only copies the dict that holds it.** Once an enclosing scope already holds the list, a value set inside one group survives the group and lands on every later node. `global_params` exists as soon as any top-level `SetParameter` ran (`sim_robot_launch.py` starts with `use_sim_time`), so the real single-vehicle launches **do** leak (found by capturing the parameters each node received): `sonar_frame_id`, `ping_interval` and `grid_file` from the mbes_sim group reach `detections_to_pointcloud` and the cube, and `sea_surface_frame` reaches `chart_datum` and nav2. `ros_remaps` leaks the same way, but only once an enclosing scope already holds a `ros_remaps` list; a first `SetRemap` inside a group creates the list in the group's own copy and discards it. The demo launch avoids all of this with copy-on-write `ScopedSetParameter` / `ScopedSetRemap`, which are defined in `marine_simulation/launch/demo_boats_launch.py` (loaded by path, not importable from elsewhere) and pinned by a `LaunchService` test in `test_demo_boats_launch.py`. There is no scoped `SetParametersFromFile`; the demo uses one, unscoped, at the top level only. Use scoped classes in any launch that builds more than one namespaced group, and never rely on a leak: see the next bullet.
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
- **CAMP's state in the demo is a generated settings file, not the operator's.** `demo_launch.py` starts CAMP with `XDG_CONFIG_HOME=~/.local/state/marine_simulation_demo/xdg_config` and rewrites `UNH-CCOMJHC/CCOMAutonomousMissionPlanner.conf` there on every start from `config/demo_camp_profile.conf` plus a generated view and one live coverage layer per roster boat. A CAMP setting that is not in that file is not restored (no chart lists, no window geometry). The map centre is a Qt `QPointF` in Web Mercator metres; `qt_point_variant` writes Qt's own INI encoding of it and is pinned against Qt-written samples. Its directory is deleted on every start, so `reset_settings_root` refuses anything but that exact path (no symlink, marker file present).
- **`camp_launch.py` takes no arguments.** The demo launch therefore starts the `CCOMAutonomousMissionPlanner` executable directly (rolker/camp#240 asks for launch arguments); keep the two in step until that lands.
- **Window placement needs X11 and `wmctrl`, and cannot be tested here.** `place_windows.py` is tested with a fake `wmctrl`; the real WM_CLASS of CAMP and the `wmctrl -e` behaviour on the owner's window manager are checked at the rehearsal. The launch refuses to start on Wayland or without `wmctrl`.
- **Arguments typed on the command line reach included launch files even when the outer launch does not declare them** (checked with `ros2 launch`): `demo_launch.py tide_speed_factor:=1` works without redeclaring it.
- **Scorer parameters are generated from the roster**, from the example `coverage_assessment.yaml` installed by the cube repo, into `~/.local/state/marine_simulation_demo/run/`. Do not copy the example into this repo: its boat names would become a second roster. `demo_manager.py` reuses `demo_launch.scorer_parameters` (it does not keep its own copy): without the first boat's `map_frame` the scorer waits forever for a plain `map` frame and never assesses.
- **Closing the CAMP window stops the whole demo launch** (`OnProcessExit` -> `Shutdown` bound to the CAMP node when `enable_camp` is true). A second demo, or a CAMP already running, is refused at launch (flock on `~/.local/state/marine_simulation_demo/lock`; process scan); CAMP's live tile cache is redirected into the same state directory and emptied each start, because it lives outside the QSettings file.
- **`wmctrl -b` reads at most two properties after `add`/`remove`/`toggle`.** A four-property clear silently left `maximized_horz` set; the fake `wmctrl` in `test_place_windows.py` now rejects such a call.
- **The packaged chart grid `US5NH02M.tiff` has no nodata tag and no NaN.** Land and drying cells are negative "depths" (minimum -10), and `mbes_sim` does not ping where `chart_depth < 0`. `build_demo_bathy` keeps that convention: its -9999 nodata appears only outside the chart extent, and `BathyGrid.getDepth` returns `None` there.
- **CCOM GIS 2 m and 16 m image services mark nodata as 3.4e38 by VALUE** (the exported GeoTIFF carries no nodata tag); the 4 m service uses -99999. `demo_bathy` masks anything beyond +-1e4 m. ArcGIS also answers some errors with HTTP 200 and a JSON body, so the fetch checks for a TIFF header and retries.
- **The demo truth grid is generated, not committed** (`ros2 run mbes_sim build_demo_bathy`, see `marine_simulation/README.md`); `demo_boats_launch.py` falls back to the chart grid with a printed message when it is absent.
- **`survey_area` is latched: a publisher must be transient_local, and `ros2 topic echo` needs `--qos-durability transient_local --qos-reliability reliable` to see it.** `publish_survey_area.py` (CAMP project file to `marine_interfaces/SurveyArea`, for the `coverage_assessment` scorer) uses reliable, transient_local, depth 100; a volatile publisher never reaches the scorer. Run it in the root namespace so the topic is `/survey_area`. It reads the file once; restart it to pick up an edit. A standard with `a = b = 0` means "not set" to the scorer (0 % meeting), so the node refuses it.
