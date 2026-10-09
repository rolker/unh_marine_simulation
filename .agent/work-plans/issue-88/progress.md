---
issue: 88
---

# Issue #88 — Four simulated boats at once: multi-platform asv_sim + four per-boat sensor/CUBE chains, joysticks, no nav stack

## Issue Review
**Status**: complete
**When**: 2026-10-09 12:58 -04:00
**By**: Claude Code Agent (Claude Sonnet)

**Issue**: #88
**Comment**: (best-effort post follows this entry; not recorded inline)
**Scope verdict**: needs-more-detail

Parent umbrella: #87. The helm_manager `initial_piloting_mode` parameter has MERGED (unh_marine_autonomy PR#401, 2026-10-09), so work item 5 is no longer blocked.

### Actions
- [ ] Action needed: `no_sim:=true` in `sim_robot_launch.py` gates the whole `sim_group` (asv_sim + mbes_sim + detections_to_pointcloud + cube_bathymetry), so work items 1-2 as written give four boats with no sensors/CUBE. Add a separate argument (or split the group) so only the `asv_sim` node is skipped; `tide_speed_factor` is applied only to that node.
- [ ] Action needed: nav2 is included unconditionally by `ben_core_launch.py` (ben_project11) and `mission_manager` by `robot_core_launch.py` (unh_marine_autonomy); `sim_robot_launch.py` cannot gate them alone. Plan the cross-repo argument plumbing (sub-issues "Part of #88" or an explicit stacked-PR set).
- [ ] Action needed: `sim_robot_launch.py` defaults `enable_bridge` to true, so four stacks would start four `udp_bridge` nodes on port 4200; pass `enable_bridge:=false` from the multi-boat launch.
- [ ] Action needed: `ben_description/launch/publish_state_launch.py` does not pass `namespace` to xacro (links stay `ben/...`), and `asv_sim/config/ben.yaml` hard-codes `mru_frame: ben/motion_sensor`; settle platform/frame naming (or fix the description launch) before the TF check.
- [ ] Action needed: tests - a launch-load/default-argument test and a multi-platform `asv_sim` test (Test what breaks); README and `.agents/README.md` updates ride in the same PR.
- [ ] Recommendation: reword work item 4 - with one shared `asv_sim`, the absolute `/asv_sim/environment/tide_level` remap is the intended shared topic, not a collision.
- [ ] Recommendation: joystick mapping - installed `joy` is 3.3.0 (SDL, selects by device index/name, not `/dev/input/js<N>`); `joy_node` + `joy_to_helm` only exist inside `operator_core_launch.py`'s `operator_joystick` group, so a per-boat joystick snippet is needed; document or key by name/GUID since SDL index order is not stable across replug.
- [ ] Recommendation: expose `cell_size` (hard-coded 1.0), `ping_interval` (hard-coded 0.2) and `beam_count` as launch arguments with current values as defaults, for work item 6.
- [ ] Recommendation: `initial_piloting_mode` is read-only and defaults empty; set it via a layered config file or scoped SetParameter (helm_manager_launch.py has no passthrough).
- [ ] Recommendation: `marine_simulation` has no README (only the repo-root README.md); decide where the acceptance-criterion docs go.

## Plan Authored
**Status**: complete
**When**: 2026-10-09 13:12 -04:00
**By**: Claude Code Agent (Claude Sonnet)

**Plan**: `.agent/work-plans/issue-88/plan.md` at `0189fd8`
**Branch**: feature/issue-88 at `0189fd8`
**Phases**: single

### Open questions
- [ ] Venue and start poses: default is Ben's Portsmouth position on a small grid with depth checked against US5NH02M.tiff; is the demo anywhere else?
- [ ] Which controller models will be used, so the joy_to_helm axis map and slow-mode default can be set?
- [ ] Include the cube base_link_frame fix in sim_robot_launch.py (changes existing single-boat behaviour) as its own commit, or leave it to a later issue?
- [ ] Boat names: boat1..boat4 (proposed) or themed names (they become namespaces, frame prefixes, CAMP tab titles)?

## Plan Review
**Status**: complete
**When**: 2026-10-09 13:17 -04:00
**By**: Claude Code Agent (Claude Sonnet)

**Plan**: `.agent/work-plans/issue-88/plan.md` at `0189fd8`
**PR**: PR-less
**Verdict**: changes-requested

Independent fresh-context review (dispatch header present). Dimensions: Scope = Concern (ten steps / nine commits is too much for the 2026-10-16 dry run; cut list below); Issue alignment = Good; File targeting = Needs work (same basename `demo_boats.yaml` in two packages; package.xml/CMake consequences incomplete); Consequences = Needs work; Documentation impact = Good; Principle alignment = Needs work (Only what's needed); ADR compliance = Good (0008 triggered); ROS conventions = Needs work (hand-copied wiring). Cut/defer list: DEFER step 3's three new `sim_robot_launch.py` args plus `test_sim_robot_launch.py` (keep only the host-approved cube `base_link_frame` commit); CUT the launch-flattening helper in step 6 (keep pure-function tests of the fail-fast validation); SLIM step 7 to a lean script (TF single-parent + topic cross-publisher check, 2-3 unit tests); DEFER step 10 and the real per-boat nav includes in step 5 until after the dry run; CUT the `use_sim_time` argument. Suggest two PRs: A = steps 1, 2, 4, 5, 9 plus minimal README (lands by ~10-12 so #87 items 2-6 can build on it), B = the rest.

### Findings
- [ ] (must-fix) Boat names are not config-only: they are hard-coded in the launch `boats` default, in the two YAMLs (incl. `mru_frame: <b>/motion_sensor`), in tests and README; derive the boat list from one file (e.g. the `demo_joysticks.yaml` keys or the asv_sim platform list), have the launch set `mru_frame` from the name, and parametrise tests/README off the config — `plan.md:43-61`
- [ ] (must-fix) Step 9 drives boats by publishing to `/<boat>/piloting_mode/manual/helm`, which bypasses `joy_to_helm` (axis map, heartbeat-learned manual mode, lifecycle activation); with no pad here, publish Xbox-shaped fake `sensor_msgs/Joy` (8 axes, 11 buttons) to each `/<boat>/joy` with `joy_to_helm` running, and gate only `joy_node` on `enable_joysticks` — `plan.md:71`
- [ ] (must-fix) The first real-pad test is at the dry run, so make it an explicit README/event checklist item: `joy_to_helm` swallows `IndexError` silently (`joy_to_helm.py:224`; reads `buttons[9]`/`[10]` every message), so a pad with fewer than 11 buttons or the wrong axis order just does not drive; defaults (throttle 1, rudder 3, slow-mode 2) match raw `joy_node` XInput ordering, so G7 SE must be in XInput mode; check `ros2 topic echo --once /boatN/joy` — `plan.md:135`
- [ ] (must-fix) Step 5 hand-copies the wiring of `robot_core_launch.py`/`sim_robot_launch.py` without listing it: asv_helm remaps (`helm`, `cmd_vel`, `throttle`, `rudder`, `have_commands` to `/asv_sim/<b>/have_commands`), helm_manager (`out/helm`, `heartbeat`, `status/helm` to `marine/...`), platform_sender `name`, and the `ros_namespace`-driven lifecycle configure/activate; prefer including the existing per-node launch files inside a per-boat `PushROSNamespace` group (as the originals do) and list the remaps in the plan, or helm/heartbeat/joystick will be silently dead — `plan.md:56-60`
- [ ] (suggestion) Drop the step 6 launch-flattening helper: emulating `PushROSNamespace`/`GroupAction` scoping to check "node set per namespace" is brittle and re-implements launch; the live graph check (step 7) is the real test of cross-wiring, and the validation can be unit-tested as pure functions — `plan.md:64-67`
- [ ] (suggestion) Defer the three new `sim_robot_launch.py` arguments and their snapshot test: the demo launch has its own `cell_size`/`ping_interval`/`beam_count`, so the event does not need them and they touch a real-boat launch file; keep the cube `base_link_frame` fix as its own commit — `plan.md:50-52`
- [ ] (suggestion) Defer step 10 and the real per-boat nav2/`mission_manager`/`s57_grids` includes (owner calls it an unlikely stretch); until then ship `enable_nav` declared, default off, failing fast with "not wired yet" if set true rather than shipping a best-effort path nobody has run — `plan.md:62-63,72`
- [ ] (suggestion) Slim step 7: keep the TF single-parent check (it is the only thing that finds frame defaults nobody listed) and the cross-publisher topic check, run it in step 9, and skip event-machine-rerun polish and extensive unit tests; `earth` stays a legitimately shared parent, so check one parent per child, not one child per parent — `plan.md:68-69`
- [ ] (suggestion) `asv_sim/config/demo_boats.yaml` and `marine_simulation/config/demo_boats.yaml` share a basename in two packages; rename one (e.g. `demo_platforms.yaml` / `demo_boats_params.yaml`) to avoid mis-edits on the day — `plan.md:43-55`
- [ ] (suggestion) Step 2's "platform name missing from the config fails loudly" is not true of `asv_sim` today (`platform.py` declares defaults, so a typo gives a model `default` boat at 0,0), so either it forces an `asv_sim` code change not listed in the plan or it belongs only to the launch fail-fast check; drop it from the asv_sim test unless a change is intended — `plan.md:47-49`
- [ ] (suggestion) Build the step 2 test in-process (rclpy `parameter_overrides` + bounded `spin_once` loops) rather than via a launched subprocess, to keep it fast and non-flaky under `colcon test` — `plan.md:47`
- [ ] (suggestion) Set `joy_node` `deadzone` explicitly in `demo_joysticks.yaml` (the packaged `joy-params.yaml` ships 0.5, which makes half the stick dead for children) and check how `joy_node` behaves with no pad present before relying on `enable_joysticks:=true` — `plan.md:55`
- [ ] (suggestion) The model copy `demo.yaml` duplicates cw4 numbers before any arcade values exist; referencing `cw4` until #87's arcade set lands avoids a second copy to keep in sync (owner may keep it; low severity) — `plan.md:43`
- [ ] (suggestion) Consequence gaps: `CMakeLists.txt` needs `install(PROGRAMS scripts/...)` and, only if launch tests stay, `ament_cmake_pytest` test_depend; `mission_manager`/`s57_grids` exec_depends only if `enable_nav` is really wired; the repo-root `README.md` is a two-line stub, so drop the "pointer if it lists launches" item — `plan.md:70,129`
- [ ] (suggestion) Record the measurement host in step 9 (CPU count, RAM): the dev host is only a proxy for the event machine, so repeat the 4-boat run on the event machine at the dry run — `plan.md:71`
- [ ] (suggestion) Real-boat split: the `cw4.yaml` key fix, `base_link_frame` fix and multi-platform asv_sim test are the only items useful off the demo; the graph check is reusable but small; everything else is correctly marked demo-only — `plan.md:88-93`

## Plan Authored
**Status**: complete
**When**: 2026-10-09 (revision after the Plan Review at 88c1ddf)
**By**: Claude Sonnet

**Plan**: `.agent/work-plans/issue-88/plan.md` at `1e3a7c0`
**Branch**: feature/issue-88 at `1e3a7c0`
**Phases**: two PRs (PR one = demo platform + launch + self-test + README; PR two = cube/cw4 fixes, measurements, deferred items)

Revision after the Plan Review (changes-requested, 88c1ddf). All four must-fixes applied: one roster file holds the boat names and the launch derives namespaces, frame prefixes, `mru_frame` and platform colour from it; the self-test publishes Xbox-shaped fake `Joy` (8 axes, 11 buttons) to each boat's `joy` with `joy_to_helm` running and only the joystick driver gated by `enable_joysticks`; an explicit pad checklist (silent `IndexError`, XInput axis order, G7 SE XInput mode, `ros2 topic echo --once`); per-boat groups include the existing per-node launch files in a namespace push, with every remap listed in a table. Reviewer cuts applied (new `sim_robot_launch.py` args and snapshot test, launch-flattening helper, real nav includes, `use_sim_time` all deferred or cut; `enable_nav` ships declared, off, refusing with "not wired yet"; graph check slimmed). Owner decisions of 2026-10-09 applied: names bluefin/clownfish/urchin/beluga in pad order blue/orange/purple/white, platform colours match, `joy_linux` bound to a physical USB port.

### Open questions
- [ ] `joy_linux` opens `dev` with the js API (`/dev/input/jsN`, per its upstream source), so the by-path link must be the `...-joystick` one, not the `...-event-joystick` one named in the owner decision; the plan uses `...-joystick` and sets `dev_ff` empty. Needs a real-pad check at the dry run.
