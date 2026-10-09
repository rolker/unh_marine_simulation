# Plan: Four simulated boats at once: multi-platform asv_sim + four per-boat sensor/CUBE chains, joysticks, no nav stack

## Issue

https://github.com/rolker/unh_marine_simulation/issues/88

## Context

Part of #87 (Ocean Discovery Day demo, Oct 23-24). Settled by the owner on 2026-10-09 (checkpoint after the `## Issue Review`
in `progress.md`, then again after the `## Plan Review`): (1) the boats are a NEW demo platform in `asv_sim`, four instances;
(2) a demo-specific launch composes the nodes directly; the nav stack stays includable only as a fail-fast `enable_nav` switch
(declared, default off, refuses with "not wired yet" if set); (3) bridge off, joystick mapping by config; (4) the absolute tide
topic is the intended shared topic; (5) tests plus a `marine_simulation` README and `.agents/README.md`, verified against the
launch source; (6) venue is Portsmouth Harbour (the packaged `US5NH02M.tiff` grid), start poses near Ben's position and depth-checked;
(7) controllers are Xbox-layout pads (GameSir G7 SE, wired, XInput mode); (8) boat names are tied to the controller colours, in this order:
`bluefin` (blue), `clownfish` (orange), `urchin` (purple), `beluga` (white); each boat's `platform_sender` `color` matches its pad so CAMP tabs match;
names stay config-only; (9) controller assignment must survive reboots: use the `joy_linux` driver bound to a physical USB port by a
`/dev/input/by-path/` link, not `joy`'s plug-order `device_id`.

Facts the design rests on (read from source, not assumed):
- `asv_sim` is one node (`asv_sim`, root namespace) holding N platforms. Per platform it publishes `<namespace>/position|orientation|velocity`,
  subscribes `<namespace>/throttle|rudder`, and exposes `~/<name>/have_commands|set_pose|sim_reset`. Models are shared by name. `Platform` declares
  defaults for every key, so a platform name that has no config silently becomes a `default`-model boat at 0,0 (the launch fail-fast check, not `asv_sim`, guards typos).
- `sim_robot_launch.py` keeps `asv_helm` OUTSIDE `sim_group`; `no_sim` therefore gates asv_sim + mbes_sim + detections_to_pointcloud + cube together; it also runs
  `mbes_sim` in the root namespace (one `/mbes_sim`). The demo launch does not go through it, so both are sidestepped rather than fixed.
- Per boat the CUBE chain needs `mru_transform` (the `<b>/odom`, `<b>/map`, `<b>/base_link` TF), `sea_surface_estimator` (`<b>/map_tide`) and the URDF static TF
  (`motion_sensor`, `mbes` through a prismatic `mbes_ram` joint, so a `joint_state_publisher` is required, not only `robot_state_publisher`).
- `helm_manager` publishes its heartbeat only when `asv_helm` publishes `status/helm`, and `joy_to_helm` publishes only when the heartbeat says `manual`; so `asv_helm`
  and `helm_manager` are both needed even with no nav stack. `initial_piloting_mode` is read-only and must be set from YAML/launch; `helm_manager` adds its standby/manual/autonomous modes itself (the `piloting_modes` lists in `marine_autonomy/config/robot.yaml` are not read by the node), so only `output_type` and `initial_piloting_mode` are set.
- `joy_to_helm` reads `buttons[0..2]` and `buttons[9]`/`[10]` on every message and swallows `IndexError` silently (`joy_to_helm.py`, `except IndexError: pass`), so a pad that
  reports fewer than 11 buttons just does not drive. Defaults (throttle axis 1, rudder axis 3, slow-mode axis 2: throttle is scaled by 0.35 unless axis 2 < 0) match the
  `js`-API (xpad) ordering of 8 axes and 11 buttons. Pressing buttons 0/1/2 makes `joy_to_helm` request a mode change on `marine/send_command` (nobody listens: no `command_bridge`)
  and set its own state until the next heartbeat re-asserts `manual`, so those buttons cause a brief stall, not a mode change.
- `joy` 3.3.0 (the only joystick driver installed on the dev host) selects by SDL `device_id`/`device_name`: a plug-order index and a shared name for identical pads, so it cannot
  pin four identical pads. `joy_linux` 3.3.0 (apt candidate `ros-jazzy-joy-linux`, not installed on the dev host) has a `dev` parameter. Per its source (fetched, not run here)
  it opens `dev` with the **js API** (`/dev/input/jsN`, `struct js_event`), NOT evdev: an `eventN` path would not produce valid data. So the by-path link to use is the
  `...-joystick` one (resolves to `jsN`), not the `...-event-joystick` one (resolves to `eventN`) the owner first named; `dev_ff` (force feedback, the only evdev use) is set to empty.
  `joy_linux` also: `autorepeat_rate` code default 20 Hz vs README 0.0 (set explicitly), default `deadzone` 0.05, axis sign inverted so pushing a stick forward is positive,
  triggers read 0.0 until first moved (so slow mode is on at start, which is what we want), then +1 released / -1 pressed.
- `ben_description`'s `publish_state_launch.py` does not pass `namespace` to xacro (links stay `ben/...`), so the demo launch starts `robot_state_publisher` + `joint_state_publisher`
  itself with `xacro ben_mesh.xacro namespace:=<boat>` (verified: yields `<boat>/base_link`, `/motion_sensor`, `/mbes_ram`, `/mbes`).
- Frame-name hazards found beyond the review: `chart_datum` and `sea_surface_estimator` default `mhhw_frame` to the UNPREFIXED `chart_datum_mhhw` (four boats would publish one child frame
  under four parents), `sea_surface_estimator` defaults `chart_datum_frame` unprefixed, and `cube_bathymetry` defaults `base_link_frame` to `base_link`. The demo launch sets all per boat.
  `sim_robot_launch.py` never sets the cube's `base_link_frame`: the cube gets `ben/base_link` only because of the launch_ros leak (below, Implementation Notes), so PR two's explicit
  cube `base_link_frame` is what makes the real launch correct, and any later scoping of that launch depends on it.
- `asv_sim/config/cw4.yaml` sets `models.cw4.max_bucket_change_rate`, but the declared name is `bucket_change_rate` (`model.py`); the key is silently ignored (value equals the default). PR two.
- `/marine/platforms` (`platform_sender`), `/tf`, `/tf_static`, `/rosout`, `/parameter_events` are legitimately shared topics; `earth` is a legitimately shared TF parent.

## Boat naming: one roster file

The boat names exist in exactly one place: `marine_simulation/config/demo_roster.yaml`, an ordered list of boats (`name`, `pad` colour label, platform `color` rgb, start pose).
Everything else is derived from it by the launch: namespaces, frame prefixes (`<name>/...`, including `asv_sim` `platforms.<name>.mru_frame: <name>/motion_sensor`),
the `asv_sim` platform parameters, the `platform_sender` name and colour. Joystick bindings are an ORDERED list of device paths in `demo_joysticks.yaml` that pairs with the
roster by position (index i = pad i), so renaming a boat touches the roster only. Tests and README parametrise off the roster rather than quoting the names.
The `boats` launch argument selects a subset by name (default: all); a boat keeps its roster position, so its pad binding does not move when the subset changes.

## TF / frame-naming decision

**Per-boat frame prefix = boat name, reusing the `ben_description` xacro with `namespace:=<boat>`** (one `robot_state_publisher` + one `joint_state_publisher` per boat, in the boat's namespace).
Every other frame is set explicitly per boat by the launch: `<b>/odom`, `<b>/map`, `<b>/map_tide`, `<b>/chart_datum`, `<b>/chart_datum_mhhw`, `<b>/base_link_north_up`.
Rejected: (a) fixing `ben_description/launch/publish_state_launch.py` to pass `namespace` (cross-repo; follow-up); (b) a minimal own URDF (loses the real MBES lever arm the CUBE error model uses;
fallback only if the CPU measurement in PR two says 4x rsp+jsp matters). Acceptance for this decision: the self-test's TF check shows each child frame has exactly one parent.

## Wiring the demo launch copies from the originals (listed so nothing is silently dead)

Each boat is a `GroupAction` with `PushROSNamespace(<boat>)` that includes the EXISTING per-node launch files (which do the lifecycle configure/activate through `ros_namespace`), not hand-copied nodes, plus these remaps:

| Node (launch file included) | Remaps / parameters set by the demo launch |
|---|---|
| `asv_sim` (one node, root ns) | per boat `<b>/position->`, `<b>/orientation->`, `<b>/velocity->` `<b>/sensors/nav/{position,orientation,velocity}`, `<b>/throttle->`/`<b>/rudder->` `<b>/control/{throttle,rudder}`; params `platforms` (list), `platforms.<b>.{model,start_lat,start_lon,start_heading,mru_frame}`, `environment.tide.speed_factor` |
| `asv_helm` (`asv_helm_launch.py`) | `helm->marine/control/helm`, `cmd_vel->marine/control/cmd_vel`, `throttle->control/throttle`, `rudder->control/rudder`, `have_commands->/asv_sim/<b>/have_commands`; its own `marine/status/helm` heartbeat; no PID block (only used for `cmd_vel`, which nothing publishes without the nav stack) |
| `helm_manager` (`helm_manager_launch.py`) | `out/helm->marine/control/helm`, `out/cmd_vel->marine/control/cmd_vel`, `heartbeat->marine/heartbeat`, `status/helm->marine/status/helm`; `output_type: helm`, `initial_piloting_mode: manual` |
| `platform_sender` (`platform_sender_launch.py`, `name:=<b>`) | `color.{red,green,blue}` from the roster; nav sources `sensors/nav/*` |
| `mru_transform_node` | `base_frame/map_frame/odom_frame` = `<b>/base_link|map|odom`; sensor topics `sensors/nav/*` |
| `sea_surface_estimator` (launch file) | `sea_surface_frame=<b>/map_tide`, `chart_datum_frame=<b>/chart_datum`, `mhhw_frame=<b>/chart_datum_mhhw` |
| `chart_datum` (launch file) | `map_frame=<b>/map`, `chart_datum_frame`, `mhhw_frame`, `base_frame=<b>/base_link` |
| `mbes_sim` (`mbes_sim_launch.py`) | `detections->/<b>/sensors/mbes/detections`, `soundings->/<b>/sensors/mbes/original_soundings`, `odom->/<b>/odom`, `tide_level->/asv_sim/environment/tide_level`; `sonar_frame_id=<b>/mbes`, `grid_file`, `ping_interval`, `beam_count` |
| `detections_to_pointcloud` (ns `<b>/sensors/mbes`) | `odom->/<b>/odom`; `base_link_frame=<b>/base_link`, `level_frame=<b>/base_link_north_up`, `tide_frame=<b>/map_tide` |
| `cube_bathymetry` (ns `<b>/sensors/mbes`) | `map_frame=<b>/map`, `base_link_frame=<b>/base_link`, `cell_size`; `draft_dir` and `prior_store_dir` set explicitly EMPTY in `demo_params.yaml` (an empty string cannot be a `-p` override; host requirement: the between-rounds reset is a lifecycle cleanup/configure cycle that only starts from an empty grid when nothing reloads from disk; never layer `bizzyboat.yaml` or any config that sets them; README reset notes say so) |
| `joy_linux_node` (named `joy_node`) | `dev=<by-path ...-joystick link for pad i>`, `dev_ff=''`, `deadzone`, `autorepeat_rate` from `demo_joysticks.yaml`; publishes `<b>/joy` |
| `joy_to_helm` (`joy_to_helm_launch.py`) | `helm->piloting_mode/manual/helm`; axes/buttons explicit in `demo_params.yaml` |

Not started: `udp_bridge`, `command_bridge`, `mission_manager`, nav2, `s57_grids`.

## Approach (PR one)

1. **Demo model in asv_sim** — `asv_sim/config/demo.yaml`: model `demo` seeded from the cw4 numbers with the DECLARED parameter names (`bucket_change_rate`, not `max_bucket_change_rate`); a comment says the arcade values arrive with #87.
   Model values are ordinary parameters; confirm `Dynamics` sees live changes (`ros2 param set /asv_sim models.demo.<x>`), else document that a relaunch is needed. No platform instances in `asv_sim` config: the launch emits them from the roster.
2. **Multi-platform asv_sim test and the two service bugs it found** — `asv_sim/test/test_multi_platform.py`, IN-PROCESS (rclpy node from `--params-file`s, a driver node, bounded `spin_once` loops; no subprocess), run by `colcon test` (plain pytest). Uses synthetic platform names, not the demo roster, and switches the current off.
   Asserts: N platforms with distinct start poses and `mru_frame`s; `set_pose` on one platform moves only that one and its orientation is read as a compass heading; throttle on one platform moves only that one; `sim_reset` returns each to its own start; every key in `demo.yaml` is a declared `Model` parameter (catches the cw4-style typo class).
   The test found two crashes in `asv_sim/platform.py` that predate this issue, fixed in the same PR (real-boat-useful, full standard): `sim_reset` called `.value` on plain floats (`AttributeError`), and the `set_pose` service callback still used an old request shape (`req.point`, `req.nav`, returned a bool) so it never matched `SetPose.srv` (`GeoPoseStamped pose` -> `bool success`); it now reads `req.pose.pose` (orientation quaternion as ENU yaw, converted to compass heading) and fills `success`.
   Found while writing it: `asv_sim` defaults to a **1 m/s current toward 090** (`environment.current.speed`), so an undriven boat drifts east at about 2 knots. The demo launch therefore sets the current to 0 by default through a `current_speed` launch argument (step 4).
   No "missing platform fails" test (not true of `asv_sim`).
3. **Roster, parameters, joystick config** — `marine_simulation/config/demo_roster.yaml` (four boats in controller order; start poses = Ben's Portsmouth position offset on a small grid, each checked for water depth in `US5NH02M.tiff` with a throwaway script, depths in the file comment),
   `demo_params.yaml` (prefix-independent node-wildcard values from the table), `demo_joysticks.yaml` (ordered by-path list, `deadzone` set explicitly low for young drivers, `autorepeat_rate`, the port labelling, and a note that the paths are per host).
4. **`marine_simulation/launch/demo_boats_launch.py`** — arguments: `boats` (CSV subset; default all roster boats), `roster_file`, `joystick_config`, `enable_joysticks` (true), `enable_nav` (false; true raises "not wired yet"), `tide_speed_factor` (10), `current_speed` (0.0 m/s; the `asv_sim` default of 1.0 would drift every boat), `mbes_grid_file`, `cell_size` (1.0), `ping_interval` (0.2), `beam_count` (120).
   No `use_sim_time` argument. Pure module-level functions (roster loading, subset selection, joystick assignment, `enable_nav` refusal) hold the fail-fast checks; the launch description is assembled from them in an `OpaqueFunction`. Fail-fast before anything launches: unknown/duplicate names, malformed roster entry, a joystick list that does not match the roster length or repeats a path,
   with joysticks on a configured device that does not exist (named boat/pad/path), and `enable_nav`. Silent cross-wiring is the failure to prevent.
   Per-boat parameters and remaps use `ScopedSetParameter` / `ScopedSetRemap` (copy-on-write subclasses of the launch_ros actions): see Implementation Notes. `draft_dir` / `prior_store_dir` for `cube_bathymetry` are stated empty in `demo_params.yaml`.
5. **Self-test and graph check** — `marine_simulation/scripts/check_multi_boat_graph.py` (pure functions + small rclpy CLI): no duplicate fully-qualified node names; each TF child frame has exactly one parent (samples `/tf` and `/tf_static`; `earth` may parent several); no topic owned by one boat (first namespace segment) published by another boat's nodes, nor a non-boat topic published by nodes of two boats outside the shared allow-list.
   `marine_simulation/scripts/demo_boats_selftest.py`: runs against a running `demo_boats_launch.py enable_joysticks:=false` (or starts it with `--start-launch`), publishes Xbox-shaped fake `sensor_msgs/Joy` (8 axes, 11 buttons) to each `/<boat>/joy` with `joy_to_helm` running (only the joystick DRIVER is gated by `enable_joysticks`), checks the expected node set per boat (and exactly one `asv_sim`), the expected frames per boat (waiting for them: the datum and tide frames appear tens of seconds after the nodes), the graph check, that
   driving each boat in turn (after a `sim_reset` of all boats, so coasting does not blur the result) moves only that boat, that with all four driven at once one boat left idle stays put while the others move and only the ones given a rudder bend, and that every boat's `coverage_catalog` / `coverage_tiles` appear; the boats are reset at the end. Scripts are installed by `CMakeLists.txt` (`install(PROGRAMS ...)`).
6. **Unit tests** — `marine_simulation/test/` (`ament_add_pytest_test`, `ament_cmake_pytest` test_depend; modules loaded by file path): `test_demo_boats_launch.py` (roster loading and validation, subset selection, joystick assignment incl. duplicate/length/missing-device, `enable_nav` refusal, roster names not hard-coded in the launch file) and `test_check_multi_boat_graph.py` (two or three tests per check on synthetic data), plus a test that `demo_params.yaml` keeps `draft_dir` / `prior_store_dir` empty. No launch-flattening helper.
7. **Docs and packaging** — new `marine_simulation/README.md` (invocation, every launch argument with its default, the pad checklist below, port labelling, frame naming, how to rename a boat or add a fifth, what the mode-change buttons do) and `.agents/README.md` update (layout, key files, pitfalls found). Every claim re-checked against the launch source.
   `marine_simulation/package.xml`: `exec_depend` on `ben_description`, `helm_manager`, `joy_linux` (rosdep key `joy_linux` -> `ros-jazzy-joy-linux`; needs `rosdep install`/`make build` on the dev host and the event machine), `joy_to_helm`, `robot_state_publisher`, `joint_state_publisher`, `xacro`; `test_depend` `ament_cmake_pytest`.
   `mission_manager`/`s57_grids` are NOT added (`enable_nav` is not wired).
8. **Run and report** — four boats on the dev host with fake Joy; report node list uniqueness, per-boat coverage topics, TF single-parent result, host (`nproc`, RAM).

## Pad checklist (goes in the README; first real-pad test is at the dry run, so it is explicit)

1. Pad in XInput mode (G7 SE: the mode switch/button combination in the GameSir manual) BEFORE plugging in; it must enumerate as an Xbox-class pad.
2. Plug the blue pad into labelled port 1, orange 2, purple 3, white 4; the label-to-USB-port map is the by-path name, which differs per host (even per front/rear port); record it in `demo_joysticks.yaml` for the host.
3. `ls -l /dev/input/by-path/ | grep -- '-joystick$'` shows one `...-joystick` link per pad (the `-event-joystick` links are the evdev nodes; not those); each must resolve to a `jsN`.
4. `ros2 topic echo --once /<boat>/joy` after launching: `axes` has 8 entries and `buttons` has 11. A pad reporting fewer buttons makes `joy_to_helm` silently ignore it (it reads `buttons[9]` and `[10]`).
5. Move each stick and trigger once: left stick up = `axes[1]` positive (throttle), right stick left/right = `axes[3]` (rudder), left trigger = `axes[2]` goes from 1.0 toward -1.0 (full speed; otherwise throttle is scaled to 0.35).
6. Drive each boat in turn and confirm it is the boat with the matching colour in CAMP; unplug/replug one pad and confirm it still drives the same boat.
7. Do not press B or X: `joy_to_helm` requests a mode change nobody handles and stalls until the next heartbeat. A asks for `manual`, which the boat is already in, so it does nothing.

## PR two (separate PR; "Part of #88", closes it)

- `sim_robot_launch.py` cube `base_link_frame` set explicitly (own commit, host-approved: changes existing single-boat CA-window behaviour; today the value arrives only through the leak, so this must land before, or together with, any scoped fix of that launch) and `asv_sim/config/cw4.yaml` `max_bucket_change_rate` -> `bucket_change_rate` key fix (value unchanged).
- Multi-platform measurements (1 boat, 4 boats default, 4 boats coarse; CPU and RSS, script output pasted; host recorded) and the repeat on the event machine at the dry run.
- Follow-up issue (not PR two): scope `SetParameter`/`SetRemap`/`SetParametersFromFile` in `sim_robot_launch.py` and the other launches with an outer list; it must be coupled with the explicit cube `base_link_frame` above, because the leak is what currently feeds the cube.
- Deferred: the `cell_size`/`ping_interval`/`beam_count` arguments on `sim_robot_launch.py` and a snapshot test; real nav includes (`nav2`, `mission_manager`, `s57_grids`) behind `enable_nav` and its smoke test; launch-flattening tests; follow-ups: `mru_transform` (prefix defaults), `ben_description` (namespace passthrough), `ben_project11` (`ben.yaml` hard-coded prefix, `ben_core_launch.py` nav gate), `unh_marine_autonomy` (manual-only `robot_core_launch.py` argument, if wanted).

## Files to Change (PR one)

| File | Change |
|------|--------|
| `asv_sim/config/demo.yaml` | new demo model |
| `asv_sim/asv_sim/platform.py` | fix `sim_reset` (`.value` on floats) and `set_pose` (request shape, response) |
| `asv_sim/test/test_multi_platform.py` | new in-process multi-platform test |
| `marine_simulation/config/demo_roster.yaml`, `demo_params.yaml`, `demo_joysticks.yaml` | new roster, node parameters, joystick bindings |
| `marine_simulation/launch/demo_boats_launch.py` | new demo launch |
| `marine_simulation/scripts/check_multi_boat_graph.py`, `demo_boats_selftest.py` | graph check and self-test |
| `marine_simulation/test/test_demo_boats_launch.py`, `test_check_multi_boat_graph.py`, `test_demo_boats_selftest.py` | unit tests |
| `marine_simulation/CMakeLists.txt`, `package.xml` | install scripts, test registration, exec/test deps |
| `marine_simulation/README.md` (new), `.agents/README.md` | docs |

## Real-boat-useful (full standard) versus demo-only (lighter review)

- **Full standard** — the multi-platform `asv_sim` test and any `asv_sim` change it forces; `.agents/README.md` and the README sections describing shared behaviour; the graph check and its unit tests (reusable for any multi-boat bring-up); PR two's `sim_robot_launch.py` and `cw4.yaml` fixes.
- **Demo-only (lighter review)** — `demo.yaml`, roster, params, joystick config, `demo_boats_launch.py`, the self-test, start-pose choices. Lighter does not mean untested: the fail-fast validation and the frame-uniqueness check stay.

## Principles Self-Check

| Principle | Consideration |
|---|---|
| A change includes its consequences | README, `.agents/README.md`, `package.xml`, CMake install/test registration and the frame-hazard follow-ups are step 7 and the PR two list |
| Test what breaks | Cross-wiring is the failure mode: fail-fast validation, the TF single-parent and cross-publisher checks, the per-platform `asv_sim` isolation test, and a self-test that drives boats through the real `joy_to_helm` |
| Improve incrementally | Two PRs; PR one is a working demo platform; no edits in other repos; real-boat launch file untouched until PR two |
| Only what's needed | No arcade parameters, scoring, 3D windows; no launch-flattening helper; no `use_sim_time`; nav not wired; own URDF, shared bridge rejected |
| Workspace vs. project separation | All content is project-repo content |
| Human control and transparency | Defaults of existing launches unchanged; nav stack and bridge absent; startup refuses ambiguous joystick mappings with a named reason |

## ADR Compliance

| ADR | Triggered | How addressed |
|---|---|---|
| 0008 Follow ROS 2 conventions | Yes | Python launch, declared args with defaults and descriptions, namespaces over name mangling, existing lifecycle launch files reused, flake8/pep257/copyright via `ament_lint_auto` |
| 0013 progress.md vocabulary | Yes | `## Plan Authored` / `## Implementation` entries |
| 0002 Worktree isolation | Yes | Work stays in `feature/issue-88`; `layers/main` untouched |
| 0009 Python package management | No | No new Python packages; `joy_linux` is a ROS apt package via rosdep |

## Consequences

| If we change... | Also update... | Included in plan? |
|---|---|---|
| New launch / configs | `.agents/README.md` layout and key-files lists, new README | Yes (7) |
| `package.xml` exec deps (`joy_linux`) | rosdep must install it on the dev host and event machine; the self-test does not need it | Yes (7), reported in hand-back |
| Unprefixed `mhhw_frame` / `chart_datum_frame` defaults in `mru_transform` | Per-boat override here; default fix upstream | Override yes; upstream follow-up |
| `ben_description` ignores `namespace` | Bypassed by calling xacro directly | Follow-up (ben_description) |
| `sim_robot_launch.py` cube `base_link_frame` | Changes existing behaviour | PR two |

## Documentation & Instruction Impact

- **Stale docs** (must land in PR one): `.agents/README.md` (layout, key files, pitfalls, launch table); new `marine_simulation/README.md`. The repo-root `README.md` is a two-line stub and gets no change.
- **Agent-instruction candidates** (proposals only): the "a launch frame default left unprefixed becomes a collision at the second vehicle" pattern; `joy_linux` uses the js API (`...-joystick` by-path link, not `...-event-joystick`). Offered for `.agents/README.md` pitfalls/knowledge; the operator decides.

## Open Questions

None blocking. Carried forward for the owner: the by-path link is `...-joystick` (js), not `...-event-joystick` as first named (see Facts); the label-to-USB-port map is per host and must be recorded at the dry run.

## Estimated Scope

PR one: about 8 atomic commits in this repo, none in other repos, aiming to land by about 2026-10-12 so #87 items 2-6 can build on it. PR two follows after the dry run (2026-10-16).

## Implementation Notes

- **Scoped actions.** `launch_ros` `SetParameter` / `SetRemap` / `SetParametersFromFile` append to the context's existing `global_params` / `ros_remaps` list IN PLACE, so once an outer scope owns the list a nested `GroupAction`'s values survive the end of the group and land on the next boat's nodes (seen: boat two's `chart_datum` got boat one's frames and died). The demo launch uses copy-on-write subclasses (`ScopedSetParameter`, `ScopedSetRemap`) so each boat's group really is a scope; there is no scoped `SetParametersFromFile`, and the remaps list leaks only once an outer `ros_remaps` list exists. The existing single-boat launches DO leak, they just have one vehicle to hide it: `sim_robot_launch.py` starts with a top-level `use_sim_time` `SetParameter`, which creates the outer list, so `sonar_frame_id`, `ping_interval` and `grid_file` from the mbes_sim group reach `detections_to_pointcloud` and the cube, `sea_surface_frame` reaches `chart_datum` and nav2, and the cube's `base_link_frame` (`ben/base_link`) arrives only through the leak. Scoping those launches therefore needs the explicit cube `base_link_frame` first (PR two). Pre-push review round 1 found this; the first draft of this note and of `.agents/README.md` claimed the opposite.
- **`joy_linux` device.** `dev` is opened with the js API, so the by-path link ending in `-joystick` is the right one (host-confirmed); `dev_ff` is empty because the only evdev use is force feedback.
- **ROS discovery for the test.** The four-boat stack is about 50 processes. With `ROS_LOCALHOST_ONLY=1` or `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` a second process on this host saw only part of the graph (no Python node, not even `asv_sim`, for minutes); with the default range it saw everything. Run the self-test with default discovery, on a private `ROS_DOMAIN_ID`.
- **Empty `draft_dir`.** An empty string cannot be a `-p` command-line override (`Failed to parse global arguments`), which is why the cube's two disk parameters live in the parameter file, not in a `SetParameter`.
- **Throttle is not proportional.** The `asv_sim` jet model runs at about 2 m/s at 0.3 throttle, so a self-test that ranks boats by throttle fails; the idle-boat form is what proves independence.
- **Round 1 review fixes (address-findings).** `set_pose` refuses non-finite values, out-of-range latitude/longitude and a zero-length quaternion (a NaN position hangs `geodesic.direct` inside the one shared node), normalises the stored heading, and `sim_reset` ignores `false`. The launch checks finiteness, parses booleans strictly, requires joystick links to resolve to distinct `jsN` nodes, and refuses to start without the datum grids `chart_datum` needs (`~/data/world/datum/geoid/us_noaa_g2018u0.tif`, `vdatum/*_mllw.gtx`), without `joy_linux` (when joysticks are on), or with a `deadzone`/`autorepeat_rate`/`mbes_grid_file`/`cell_size`/`beam_count`/`ping_interval` that cannot work. The self-test starts its launch last, inside the `try`, forwards `--boats`/`--roster`/`--joysticks`, stops on SIGTERM, notices an early launch exit and checks `/marine/platforms` names and colours. The graph check also flags a single boat publishing an unprefixed topic and documents what it cannot see. The demo's `joy_linux` node has no `respawn`; joy_linux 3.3.0 is expected to re-open a lost device itself, still unverified until the dry run.
