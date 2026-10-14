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
| `marine_simulation` | CMake (config, launch, scripts) | Aggregation package with scenario launch files, configs, and the multi-boat demo (launch, roster, self-test, graph check); see `marine_simulation/README.md` |

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
└── marine_simulation/                 # Scenario launch files
    ├── launch/                        #   sim_test, sim_demo, sim_drix, demo_boats_launch.py, ...
    ├── config/                        #   bob_platform.yaml, udp_bridge.yaml, demo_roster/params/joysticks.yaml
    ├── scripts/                       #   demo_boats_selftest.py, check_multi_boat_graph.py
    ├── test/                          #   pytest: demo launch fail-fast checks, graph check
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

## Build & Test

```bash
# From the layer workspace directory (layers/main/simulation_ws/)
colcon build --packages-select asv_sim asv_sim_msgs asv_helm vrx_project11 mbes_sim marine_charts_to_gazebo_world portsmouth_nh_gazebo marine_simulation

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
- **The packaged chart grid `US5NH02M.tiff` has no nodata tag and no NaN.** Land and drying cells are negative "depths" (minimum -10), and `mbes_sim` does not ping where `chart_depth < 0`. `build_demo_bathy` keeps that convention: its -9999 nodata appears only outside the chart extent, and `BathyGrid.getDepth` returns `None` there.
- **CCOM GIS 2 m and 16 m image services mark nodata as 3.4e38 by VALUE** (the exported GeoTIFF carries no nodata tag); the 4 m service uses -99999. `demo_bathy` masks anything beyond +-1e4 m. ArcGIS also answers some errors with HTTP 200 and a JSON body, so the fetch checks for a TIFF header and retries.
- **The demo truth grid is generated, not committed** (`ros2 run mbes_sim build_demo_bathy`, see `marine_simulation/README.md`); `demo_boats_launch.py` falls back to the chart grid with a printed message when it is absent.
