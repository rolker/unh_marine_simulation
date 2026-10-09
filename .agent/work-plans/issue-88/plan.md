# Plan: Four simulated boats at once: multi-platform asv_sim + four per-boat sensor/CUBE chains, joysticks, no nav stack

## Issue

https://github.com/rolker/unh_marine_simulation/issues/88

## Context

Part of #87 (Ocean Discovery Day demo, Oct 23-24). Settled by the owner on 2026-10-09 (checkpoint after the `## Issue Review`
in `progress.md`): (1) the boats are a NEW demo platform in `asv_sim`, four instances; (2) a demo-specific launch composes the
nodes directly, with an off-by-default nav-stack argument; (3) bridge off, joystick mapping by config; (4) the absolute tide
topic is the intended shared topic; (5) `cell_size` / `ping_interval` / `beam_count` become launch arguments; (6) tests plus a
`marine_simulation` README and `.agents/README.md`, verified against the launch source.

Facts the design rests on (read from source, not assumed):
- `asv_sim` is one node (`asv_sim`, root namespace) holding N platforms. Per platform it publishes `<namespace>/position|orientation|velocity`,
  subscribes `<namespace>/throttle|rudder`, and exposes `~/<name>/have_commands|set_pose|sim_reset`. Models are shared by name.
- `sim_robot_launch.py` keeps `asv_helm` OUTSIDE `sim_group`; `no_sim` therefore gates asv_sim + mbes_sim + detections_to_pointcloud + cube together.
  The demo launch does not go through it (decision 2), so that coupling is sidestepped rather than fixed.
- Per boat the CUBE chain needs `mru_transform` (the `<ns>/odom`, `<ns>/map`, `<ns>/base_link` TF), `sea_surface_estimator` (`<ns>/map_tide`) and the URDF
  static TF (`motion_sensor`, `mbes` through a prismatic `mbes_ram` joint, so a `joint_state_publisher` is required, not only `robot_state_publisher`).
- `helm_manager` publishes its heartbeat only when `asv_helm` publishes `status/helm`, and `joy_to_helm` publishes only when the heartbeat says `manual`;
  so `asv_helm` and `helm_manager` are both needed even with no nav stack. `initial_piloting_mode` is read-only and must be set from YAML/launch.
- `joy` 3.3.0 parameters: `device_id`, `device_name`, `deadzone`, `autorepeat_rate`, `sticky_buttons`, `coalesce_interval_ms`. No `/dev/input/js<N>` path.
  Identical controllers share a name, so `device_name` cannot tell four identical pads apart; SDL index order follows enumeration/plug order.
- Frame-name hazards found beyond the review: `chart_datum` and `sea_surface_estimator` default `mhhw_frame` to the UNPREFIXED `chart_datum_mhhw`
  (four boats would publish one child frame under four parents), `sea_surface_estimator` defaults `chart_datum_frame` unprefixed, and `cube_bathymetry`
  defaults `base_link_frame` to `base_link` (`sim_robot_launch.py` sets it only for `detections_to_pointcloud`, so the CA window falls back to the full resident set).
- `asv_sim/config/cw4.yaml` sets `models.cw4.max_bucket_change_rate`, but the declared name is `bucket_change_rate` (`model.py`); the key is silently ignored (value equals the default).

## TF / frame-naming decision

**Per-boat frame prefix = platform name, reusing the `ben_description` xacro with `namespace:=<boat>` from the demo launch** (one `robot_state_publisher` + one
`joint_state_publisher` per boat, in the boat's namespace). `xacro ben_mesh.xacro namespace:=boat1` was run and yields `boat1/base_link`, `boat1/motion_sensor`,
`boat1/mbes_ram`, `boat1/mbes`, so no change to `ben_description` is needed. Every other frame is set explicitly per boat by the launch:
`<b>/odom`, `<b>/map`, `<b>/map_tide`, `<b>/chart_datum`, `<b>/chart_datum_mhhw`, and `asv_sim` `platforms.<b>.mru_frame: <b>/motion_sensor` (`demo_boats.yaml`).
Rejected: (a) fixing `ben_description/launch/publish_state_launch.py` to pass `namespace` (cross-repo; named as a follow-up, would also benefit any non-`ben` boat);
(b) a minimal own URDF (cheaper: three links, one rsp, no jsp; but loses the real MBES lever arm the CUBE error model uses and adds a model to maintain). Fallback to (b)
only if the CPU measurement (step 9) shows the 4x rsp+jsp cost matters. Acceptance for this decision: the graph check (step 7) shows each child frame has exactly one parent.

## Approach

1. **Demo platform in asv_sim** — add `asv_sim/config/demo.yaml` (model `demo`, seeded from the cw4 numbers using the DECLARED parameter names; a comment says the arcade
   values arrive with #87) and `asv_sim/config/demo_boats.yaml` (`platforms.boat1..boat4`: `model: demo`, `mru_frame: <b>/motion_sensor`, distinct `start_lat/lon/heading`).
   Start poses: Ben's Portsmouth position offset on a small grid, each checked for water depth in `US5NH02M.tiff` with a throwaway script; the sampled depths go in the file comment.
   Dynamics stay adjustable: model values are ordinary parameters (`ros2 param set /asv_sim models.demo.<x>`); confirm during step 2 that `Dynamics` sees live changes, else document that a relaunch is needed.
2. **Multi-platform asv_sim test** — `asv_sim/test/test_multi_platform.py` (plain pytest + rclpy, runs under `colcon test`, unlike the launch_test tide file): load both new YAMLs with
   `--params-file`, assert four platforms with distinct start poses and `mru_frame`s, per-platform `set_pose` moves only that boat, a throttle on boat 2 moves only boat 2, `sim_reset` returns
   each to its own start, a platform name missing from the config fails loudly. Fix in the same commit set: the `cw4.yaml` key typo (value unchanged).
3. **`sim_robot_launch.py` arguments** — `cell_size` (default 1.0), `ping_interval` (0.2), `beam_count` (120, equal to the `mbes_sim` declared default; the test reads `mbes_sim.py` so drift is caught),
   replacing the hard-coded 1.0/0.2 and adding `beam_count`. Defaults produce the same resolved parameters as today. Separate commit, flagged for the owner (open question 3): also set `base_link_frame`
   for `cube_bathymetry` to `<ns>/base_link`.
4. **Demo launch config** — `marine_simulation/config/demo_boats.yaml` (prefix-independent values only, node-wildcard keys as the existing configs do): `/**/helm_manager` `output_type: helm`,
   `initial_piloting_mode: manual`; `/**/asv_helm` PID block (values copied from `ben.yaml`, tunable later); `/**/mru_transform` sensor topics `sensors/nav/*`; `/**/platform_sender` nav sources plus footprint
   (CAMP draws it) copied from the ben configs; `/**/joy_to_helm` axes/buttons. `marine_simulation/config/demo_joysticks.yaml`: `boat1: {device_id: 0} ... boat4: {device_id: 3}`, optional `device_name`, `deadzone`.
5. **`marine_simulation/launch/demo_boats_launch.py`** — arguments: `boats` (CSV, default `boat1,boat2,boat3,boat4`), `joystick_config`, `enable_joysticks` (true), `enable_nav` (false), `use_sim_time` (false),
   `tide_speed_factor` (10, as `sim_robot_launch.py`), `mbes_grid_file`, `cell_size`, `ping_interval`, `beam_count`. One `asv_sim` node (demo YAMLs, `platforms` resolved from `boats`, five remaps per boat, as the
   existing OpaqueFunction does). Per boat, in a namespaced group: rsp + jsp (xacro `namespace:=`), `mru_transform_node`, `sea_surface_estimator`, `chart_datum`, `asv_helm`, `helm_manager`, `platform_sender`,
   `mbes_sim`, `detections_to_pointcloud`, `cube_bathymetry` (all frame params set per boat, including the three hazards above), then `joy_node` + `joy_to_helm` (helm remapped to `piloting_mode/manual/helm`).
   No `udp_bridge`, no `command_bridge`, no `s57_grids`. tide remap stays the absolute shared `/asv_sim/environment/tide_level`. Fail-fast checks before launching anything: every name in `boats` exists in the asv_sim
   platform config, names are unique, and (joysticks on) every boat has a joystick entry with no `device_id` used twice — silent cross-wiring is the failure to prevent.
   `enable_nav:=true` additionally includes, per boat, the already-separable `ben_project11/nav2_bringup_launch.py` (namespace args as `ben_core_launch.py` passes them), `mission_manager_launch.py` and `s57_grids_launch.py`,
   with the frames set per boat. Best effort: acceptance is "argument exists, off by default, nodes come up without TF or name collisions"; any gap in `ben_project11` / `unh_marine_autonomy` becomes a named follow-up, not a change there.
6. **Launch tests** — `marine_simulation/test/` (registered with `ament_add_pytest_test`, `ament_cmake_pytest` test_depend): a small helper flattens a launch description for given arguments (runs `OpaqueFunction`s against a
   `LaunchContext`; includes recorded as package/file). `test_sim_robot_launch.py`: argument names/defaults snapshot of the current file, new args' defaults, resolved `cell_size`/`ping_interval`/`beam_count` equal today's literals, overrides propagate.
   `test_demo_boats_launch.py`: loads with defaults; exactly one `asv_sim`; each boat has the expected node set under its namespace; no duplicate fully-qualified names; no `udp_bridge`; nav includes absent by default and present with `enable_nav:=true`;
   per-boat frame params all start with the boat name; fail-fast cases (typo'd boat, missing/duplicate joystick id) raise a clear error; joystick entries become `joy_node` `device_id` per boat.
7. **Graph check tool** — `marine_simulation/scripts/check_multi_boat_graph.py`: against a running launch, asserts no duplicate fully-qualified node names, each boat's expected topics exist, no topic published by two boats, and each TF child frame has exactly one parent
   (samples `/tf` and `/tf_static`). The checking functions are pure and unit-tested. It is the repeatable form of the issue's `ros2 node list` / `ros2 topic list` verification and can be rerun on the event machine.
8. **Docs and packaging** — new `marine_simulation/README.md` (multi-boat invocation, every launch argument with its default, joystick mapping and the replug caveat: unplug all, plug in order, `ros2 run joy joy_enumerate_devices`; the mode-change buttons do nothing because there is no `command_bridge`; how to start CAMP; frame naming; adding a fifth boat) and an `.agents/README.md` update (package/launch table, new configs, the `no_sim` split, the frame-prefix decision, pitfalls found). Every claim is re-checked against the launch source. `marine_simulation/package.xml`: `exec_depend` on `ben_description`, `helm_manager`, `joy`, `joy_to_helm`, `robot_state_publisher`, `joint_state_publisher`, `xacro`, `mission_manager` and `s57_grids` for `enable_nav`; no new rosdep keys expected (dependency policy untouched).
9. **Run and measure** — on this host with `enable_joysticks:=false`, drive each boat by publishing to `/<boat>/piloting_mode/manual/helm`; run the graph check; confirm per-boat `coverage_catalog` / `coverage_tiles`; sample CPU and RSS (script output pasted into the PR, not typed): 1 boat, 4 boats default, 4 boats coarse (`cell_size`, `beam_count`). No gamepad exists on this host: joystick mapping is covered by the unit tests and a README checklist for event setup; the CAMP "all four visible" check is a manual operator step (CAMP tracks platforms by `platform.name`, one tab each).
10. **`enable_nav` smoke** — launch once with `enable_nav:=true` for one boat, record what comes up and what does not; file/name follow-ups.

## Files to Change

| File | Change |
|------|--------|
| `asv_sim/config/demo.yaml`, `demo_boats.yaml` | new demo model + four platform instances |
| `asv_sim/config/cw4.yaml` | fix ignored `max_bucket_change_rate` key (value unchanged) |
| `asv_sim/test/test_multi_platform.py` | new multi-platform test |
| `marine_simulation/launch/sim_robot_launch.py` | `cell_size`, `ping_interval`, `beam_count` args (defaults unchanged); optional cube `base_link_frame` fix |
| `marine_simulation/launch/demo_boats_launch.py` | new demo launch |
| `marine_simulation/config/demo_boats.yaml`, `demo_joysticks.yaml` | new demo configs |
| `marine_simulation/scripts/check_multi_boat_graph.py` | new graph check |
| `marine_simulation/test/*` , `CMakeLists.txt`, `package.xml` | launch tests, test registration, exec/test deps; install `scripts` |
| `marine_simulation/README.md` (new), `.agents/README.md` | docs |

## Real-boat-useful (full standard) versus demo-only (lighter review)

- **Full standard** — `sim_robot_launch.py` argument change and its default-argument test; the cube `base_link_frame` fix; the `cw4.yaml` key fix; the multi-platform `asv_sim` test and any `asv_sim` change it forces;
  `.agents/README.md` and the README sections describing shared behaviour; the graph check tool and its unit tests (reusable for any multi-boat bring-up); the follow-up issue texts.
- **Demo-only (lighter review)** — `demo.yaml`, `demo_boats.yaml` (both), `demo_joysticks.yaml`, `demo_boats_launch.py` and its tests, the `enable_nav` stretch, start-pose choices, the measurements.
  Lighter does not mean untested: the fail-fast validation and the frame-uniqueness check stay, because a mis-wired boat in front of an audience is the failure that matters.

## Principles Self-Check

| Principle | Consideration |
|---|---|
| A change includes its consequences | README, `.agents/README.md`, `package.xml`, test registration and the frame-hazard follow-ups are steps 3, 8 and the follow-up list |
| Test what breaks | Cross-wiring is the failure mode: fail-fast validation, node-set/frame tests, TF single-parent check, per-platform `asv_sim` isolation test |
| Improve incrementally | One PR of atomic commits, ordered so a working demo exists after steps 1, 4, 5; docs/tests follow; no edits in other repos |
| Only what's needed | No arcade parameters, scoring, 3D windows; own URDF, shared bridge, platform-wide `boats` plumbing in other repos all rejected; the graph tool is justified by the issue's own verification item |
| Workspace vs. project separation | All content is project-repo content; nothing proposed for the workspace repo |
| Human control and transparency | Defaults unchanged; nav stack and bridge opt-in or absent; startup refuses ambiguous mappings with a named reason |

## ADR Compliance

| ADR | Triggered | How addressed |
|---|---|---|
| 0008 Follow ROS 2 conventions | Yes | Python launch, declared args with defaults and descriptions, namespaces over name mangling, lifecycle transitions as in existing launches, flake8/pep257/copyright via `ament_lint_auto` |
| 0013 progress.md vocabulary | Yes | `## Plan Authored` entry |
| 0002 Worktree isolation | Yes | Work stays in `feature/issue-88`; `layers/main` untouched |
| 0009 Python package management | No | No new Python packages; test deps are ROS packages |

## Consequences

| If we change... | Also update... | Included in plan? |
|---|---|---|
| `sim_robot_launch.py` args | Launch args table in README; default-arg test | Yes (3, 6, 8) |
| New configs / launch | `.agents/README.md` layout and key-files lists | Yes (8) |
| `package.xml` exec deps | rosdep keys must resolve (ROS packages only) | Yes (8), checked in 9 |
| Unprefixed `mhhw_frame` / `chart_datum_frame` defaults in `mru_transform` | Per-boat override here; default fix upstream | Override yes; upstream follow-up |
| `ben_description` ignores `namespace` | Bypassed by calling xacro directly | Follow-up (ben_description) |
| `ben.yaml` hard-codes `ben/` frames for `chart_datum` / `s57_grids` | `ben_core_launch.py` not multi-instance-safe | Follow-up (ben_project11); demo sets frames in launch |
| `robot_core_launch.py` always starts `mission_manager` | Not needed: demo does not include it | Follow-up only if a mainline manual-only arg is wanted later |

## Documentation & Instruction Impact

- **Stale docs** (must land in this PR): `.agents/README.md` (layout, key files, pitfalls, launch table); new `marine_simulation/README.md`; the repo-root `README.md` gets a one-line pointer if it lists launches.
- **Agent-instruction candidates** (proposals only): the "a launch frame default left unprefixed becomes a collision at the second vehicle" pattern; the `joy` 3.3.0 device-selection facts. Offered for `.agents/README.md` pitfalls/knowledge; the operator decides.

## Open Questions

1. Venue and start poses: default is Ben's Portsmouth position on a small grid with depth checked against `US5NH02M.tiff`; is the demo expected anywhere else (a different bathymetry grid would change the poses)?
2. Controller model(s): `joy_to_helm` defaults (throttle axis 1, rudder axis 3, slow-mode axis 2 scaling throttle by 0.35 when that axis is >= 0) assume a specific pad. Which pads will be used, so the axis map and slow-mode default can be set?
3. Cube `base_link_frame` fix in `sim_robot_launch.py`: it changes existing single-boat behaviour (CA window becomes bounded) although no topic or default argument changes. Include as its own commit, or leave to a later issue?
4. Boat names: `boat1..boat4` (proposed) or themed names? They become namespaces, frame prefixes and CAMP tab titles.

## Estimated Scope

Single PR in this repo with about 9 atomic commits; no changes in other repos. If time presses before the event, steps 1, 4, 5, 9 give a working demo and steps 2, 3, 6, 7, 8 follow in the same PR. Follow-ups to file: `mru_transform` (prefix defaults), `ben_description` (namespace passthrough), `ben_project11` (`ben.yaml` hard-coded prefix, `ben_core_launch.py` nav gate), `unh_marine_autonomy` (manual-only `robot_core_launch.py` argument, only if wanted), plus whatever step 10 finds.
