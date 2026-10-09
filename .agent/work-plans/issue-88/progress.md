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

## Implementation
**Status**: complete
**When**: 2026-10-09 (PR one of the revised plan)
**By**: Claude Sonnet

**Plan**: `.agent/work-plans/issue-88/plan.md` (synced in place; rationale in its Implementation Notes)
**Branch**: feature/issue-88

### Commits
- 491fce1 feat(asv_sim): add the demo model for the four-boat demo
- 1c1dd4e fix(asv_sim): sim_reset and set_pose crash; add in-process multi-platform test
- ffea729 feat(marine_simulation): demo launch for four simulated boats
- 5c07eed feat(marine_simulation): multi-boat graph check
- 717efdf feat(marine_simulation): self-test with fake joystick input; launch fail-fast tests
- 232266b docs(marine_simulation): demo boats README with pad checklist; agent guide update

### Results
- `asv_sim`: 20 tests, 0 failures, 1 skipped (5 new in-process multi-platform tests).
- `marine_simulation`: 34 new pytest tests pass (27 launch fail-fast/roster/joystick, 7 graph check). The package lint still shows the 8 failures that exist at baseline (copyright, flake8 I100, pep257 D213 in `bizzyboat_massabesic_launch.py`, `gazebo_*_launch.py`, `simulator_launch.py`); no failure in a file this issue added. Package total 88 tests (baseline 76), same 8 failures.
- Four-boat self-test on the dev host (16 CPUs, 31 GB): 15 of 15 checks pass, run three times; 50 nodes, 0 duplicate names, one `asv_sim`, 12 nodes per boat; all nine frames per boat; every TF child frame has one parent; no cross-boat topic; driving one boat moved only that boat (15 m vs 0.0 to 0.1 m for the others); per-boat `cube_bathymetry/coverage_catalog` and `coverage_tiles` deliver.
- `joy_linux` is not installed on the dev host (apt candidate 3.3.0); the launch and tests do not need it (`enable_joysticks:=false`). The joystick path is untested on hardware.

### Deviations from the owner decisions / findings
- [ ] `joy_linux` reads the js API: by-path link must end `-joystick`, not `-event-joystick`.
- [ ] Two pre-existing `asv_sim` bugs fixed (`sim_reset` crashed, `set_pose` never matched `SetPose.srv`); `asv_sim` defaults to a 1 m/s current, the demo sets 0.
- [ ] launch_ros `SetParameter`/`SetRemap` leak across `GroupAction`s once an outer scope holds a list; the demo uses scoped subclasses. The real single-vehicle launches DO leak (corrected after pre-push review round 1: `sim_robot_launch.py`'s top-level `use_sim_time` creates the outer list, and the cube's `base_link_frame=ben/base_link` arrives only through the leak), so a follow-up that scopes them must be coupled with an explicit cube `base_link_frame` (PR two keeps that commit).
- [ ] ROS discovery with `ROS_LOCALHOST_ONLY=1` was incomplete for the ~50-process stack (observed twice).
- [ ] PR two: cube `base_link_frame` in `sim_robot_launch.py`, `cw4.yaml` key, measurements (host recorded: 16 CPUs, 31 GB), deferred items.

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-09 14:44 -04:00
**By**: Claude Code Agent (Claude Sonnet)
**Verdict**: changes-requested

**Branch**: feature/issue-88 at `6be5e05`
**Mode**: pre-push
**Depth**: Deep (reason: 1970 changed lines, 15 files outside .agent/)
**Must-fix**: 8 | **Suggestions**: 12
**Round**: 1 | **Ship**: continue — 8 must-fix, all with a precise fix; two are correctness (set_pose / roster NaN freezes the shared asv_sim; flaky and sign-blind set_pose test). One address-findings round, then a light re-check, should be enough.

Specialists: static analysis (ament_flake8 / pep257 / xmllint / lint_cmake clean on all new files; yamllint style notes only), governance, plan drift, Claude adversarial Lens A + Lens B (fresh sub-agents), cross-model (gemini + codex, both EXIT=0), local model off. Live four-boat self-test re-run here on a private ROS_DOMAIN_ID: 15 of 15 pass, nothing left running. Build + test: asv_sim 20 tests, 0 failures, 1 skipped (copyright, pre-existing skip); marine_simulation 88 per colcon (68 in the xunit files), 8 failures, all in files this branch did not touch (copyright bizzyboat_massabesic_launch.py; flake8 I100 simulator_launch.py:43; pep257 D213 in bizzyboat_massabesic_launch.py, gazebo_ben_launch.py, gazebo_simulator_launch.py; plus the 3 CTest wrappers of those).

### Findings
- [x] (must-fix) set_pose accepts NaN/inf/out-of-range lat-lon and zero-norm quaternion and replies success=True; NaN makes geodesic.direct loop forever (reproduced, timeout exit 124), freezing the one shared asv_sim for all boats — validate, return success=False, add a test — `asv_sim/asv_sim/platform.py:168`
- [x] (must-fix) _number() lets NaN through (both range comparisons are False), so a roster with .nan start lat/lon/heading passes fail-fast and hangs asv_sim at first update — add math.isfinite and a test — `marine_simulation/launch/demo_boats_launch.py:125`
- [x] (must-fix) test_set_pose_heading_is_a_compass_heading cannot catch a yaw-sign error (heading 90 = yaw 0) and the abs(north) < east/3 bound fails about 3 percent of runs on correct code (model noise); use heading 0 or 200 and a looser or seeded check — `asv_sim/test/test_multi_platform.py:174`
- [x] (must-fix) demo_boats_selftest --start-launch starts the 50-process launch before rclpy.init()/SelfTest(), outside try/finally; a constructor failure leaks the whole stack (and the next try then has two asv_sim) — `marine_simulation/scripts/demo_boats_selftest.py:333`
- [x] (must-fix) assign_joysticks only checks os.path.exists: an -event-joystick link (the very name the owner first gave) passes and joy_linux then reads garbage silently; duplicate detection compares strings, not realpath — require the resolved target to match js<N> and dedupe on realpath — `marine_simulation/launch/demo_boats_launch.py:207`
- [x] (must-fix) enable_joysticks / enable_nav parsing is lenient: anything outside true/1/yes/on means off, so enable_joysticks:=ture starts four boats with no pads and no message; parse strictly and raise — `marine_simulation/launch/demo_boats_launch.py:437`
- [x] (must-fix) .agents/README.md pitfalls are wrong on two counts: "Single-vehicle launches never notice" and "sim_robot_launch.py still leaves the cube's unset". Captured the real sim_robot_launch.py: a top-level SetParameter makes the outer list exist, so its groups leak (sonar_frame_id, ping_interval, grid_file reach d2p and cube; sea_surface_frame reaches chart_datum and nav2), and cube_bathymetry gets base_link_frame=ben/base_link only through that leak. Fix the text, plan.md Facts / PR two, and the Implementation entry — `.agents/README.md` (SetParameter/SetRemap and Frame-defaults bullets)
- [x] (must-fix) README pad checklist item 7 says A, B and X request a mode change; A does not (joy_to_helm only publishes when the request differs from the current state, already manual) — only B and X stall — `marine_simulation/README.md:105`
- [x] (suggestion) No unit test pins ScopedSetParameter / ScopedSetRemap (the reason the subclasses exist); a 15-line LaunchService test over two sibling GroupActions with an outer list would — `marine_simulation/test/test_demo_boats_launch.py`
- [x] (suggestion) Pitfall bullet says use the scoped classes "for any launch" but they live inside the demo launch (not importable) and SetParametersFromFile has no scoped version; ScopedSetRemap only matters once an outer ros_remaps list exists — `.agents/README.md`
- [x] (suggestion) chart_datum defaults its geoid and VDatum grids to ~/data/world/datum; if absent it only warns, then <boat>/chart_datum and chart_datum_mhhw never appear (self-test fails after 90 s, launch looks fine). Document the requirement and preflight it — `marine_simulation/README.md`, `demo_boats_launch.py:334`
- [x] (suggestion) Self-test: --start-launch does not forward --boats/--roster, hard-codes enable_joysticks:=false (so --joysticks can never pass), does not notice an early launch exit, ignores SIGTERM; platform_sender / /marine/platforms (the CAMP tab names and colours) is not checked — `demo_boats_selftest.py:298,333`
- [x] (suggestion) Graph check blind spots: a single boat publishing an unprefixed non-shared topic is not flagged (needs two boats), publishers in the root namespace (asv_sim) and all subscribers are invisible, joy_linux may publish an absolute /diagnostics — say so in the docstring or tighten — `marine_simulation/scripts/check_multi_boat_graph.py:98`
- [x] (suggestion) Unvalidated inputs: autorepeat_rate <= 2 Hz stops a held stick (asv_sim zeroes commands after 0.5 s), deadzone outside [0,1), mbes_grid_file path, cell_size / beam_count / ping_interval positivity, installed joy_linux (raw PackageNotFound after boats have started) — `demo_boats_launch.py:430-442`
- [x] (suggestion) Name pattern uses re.match with $ (accepts a trailing newline) — use fullmatch; FRAME_SUFFIXES is unused (self-test has its own BOAT_FRAMES) — `demo_boats_launch.py:73,76,150`
- [x] (suggestion) set_pose heading not normalised (negative for yaw > 90 degrees; cosmetic, dynamics fix it at first step); reset_callback ignores Bool.data — `asv_sim/asv_sim/platform.py:161,182`
- [x] (suggestion) Test hygiene: all test platforms share model demo (so a model mix-up passes); sim_reset test never asserts the boats left start first; Rig() built outside try so a failed AsvSim() leaves rclpy initialised for later tests; roster test name promises depth check it does not do — `asv_sim/test/test_multi_platform.py:146,193`, `test_demo_boats_launch.py:86`
- [x] (suggestion) package.xml lacks explicit exec_depends for what the scripts import (rclpy, sensor_msgs, std_msgs, tf2_msgs, marine_interfaces, ament_index_python) — `marine_simulation/package.xml`
- [x] (suggestion) README: sim_reset does not clear CUBE (the cleanup/configure cycle is a host procedure, say so); advise a private ROS_DOMAIN_ID for the demo itself; the first example fails until demo_joysticks.yaml is copied and edited — `marine_simulation/README.md:12,107`
- [x] (suggestion) joy_linux 3.3.0 source (fetched, tag 3.3.0) appears to re-open the device after loss, so respawn is probably unnecessary, but the replug step in the checklist is still unverified until the dry run — `marine_simulation/launch/demo_boats_launch.py:398` (no change needed: the demo's joy node has no respawn; the replug step stays unverified until the dry run, now stated in the README)

### Follow-up issue (not a change here)
- [ ] launch_ros SetParameter/SetRemap/SetParametersFromFile extend the context list in place; sim_robot_launch.py (top-level use_sim_time SetParameter, then nested groups) and any launch with an outer list leak group values to later nodes. The cube's base_link_frame is correct today only through the leak, so the scoped fix and the explicit cube base_link_frame (PR two) must land together. Reproduction scripts: robotcap.py approach (patch Node.execute, print global_params).

## Implementation
**Status**: complete
**When**: 2026-10-09 15:12 -04:00
**By**: Claude Sonnet

**Branch**: feature/issue-88 at `e474252`
**Addressed**: Local Review (Pre-Push) round 1 of 2026-10-09 14:44 -04:00 at `6be5e05` (8 must-fix, 12 suggestions; the follow-up-issue item stays open for the host)
**Commits**: 67cb53e, f6fcb0c, 5a950db, 5b484ce, 9aabce6, 708de1b, 65ad4a9, e474252

### Actions
- [x] set_pose refuses non-finite values, latitude outside [-90, 90], longitude outside [-180, 180] and a zero-length quaternion with success=False; test per case — `asv_sim/asv_sim/platform.py`
- [x] _number() requires math.isfinite; tests for .nan/inf in the roster — `marine_simulation/launch/demo_boats_launch.py`
- [x] heading test uses heading 0 with north > 2 m and |east| < north/2; three full runs passed — `asv_sim/test/test_multi_platform.py`
- [x] --start-launch starts the stack last, inside the try/finally — `marine_simulation/scripts/demo_boats_selftest.py`
- [x] joystick links must resolve to js<N> and be distinct on realpath — `demo_boats_launch.py`
- [x] boolean arguments parse strictly and raise — `demo_boats_launch.py`
- [x] .agents/README.md, plan.md (Facts, PR two, Implementation Notes) and the earlier Implementation entry corrected: the real launches DO leak and the cube's base_link_frame arrives only through the leak, so the scoped follow-up must be coupled with an explicit cube base_link_frame — `.agents/README.md`, `.agent/work-plans/issue-88/plan.md`
- [x] README pad item 7: only B and X stall — `marine_simulation/README.md`
- [x] LaunchService test pins ScopedSetParameter and ScopedSetRemap (and that the stock classes leak) — `test_demo_boats_launch.py`
- [x] pitfall precise: scoped classes live in the demo launch, no scoped SetParametersFromFile, remaps leak only once an outer list exists — `.agents/README.md`
- [x] datum grids documented and preflighted — `README.md`, `demo_boats_launch.py`
- [x] self-test forwards --boats/--roster/--joysticks, stops on SIGTERM, notices an early launch exit, checks /marine/platforms names and colours — `demo_boats_selftest.py`
- [x] graph check: single-boat unprefixed topic now flagged (/diagnostics added to the shared list); other blind spots documented — `check_multi_boat_graph.py`
- [x] validation of autorepeat_rate (> 2 Hz), deadzone, mbes_grid_file, cell_size, beam_count, ping_interval, tide_speed_factor, current_speed, joy_linux installed — `demo_boats_launch.py`
- [x] fullmatch for the name regex; FRAME_SUFFIXES removed — `demo_boats_launch.py`
- [x] set_pose heading normalised to [0, 360); sim_reset honours Bool.data — `platform.py`
- [x] test hygiene: second model, sim_reset asserts the boats left start, rig built inside try (and a failed constructor shuts rclpy down), roster test renamed — `test_multi_platform.py`, `test_demo_boats_launch.py`
- [x] explicit exec_depends — `marine_simulation/package.xml`
- [x] README: sim_reset does not clear CUBE, private ROS_DOMAIN_ID, first example needs the joystick file — `marine_simulation/README.md`
- [x] joy_linux respawn — nothing to change: the demo's joy node has no respawn; replug stays unverified until the dry run (README says so) (deferred: no behaviour change wanted) — `demo_boats_launch.py`

### Results
- `asv_sim`: 33 tests, 0 failures, 1 skipped (copyright, pre-existing). `marine_simulation`: 102 pytest tests pass (87 launch, 9 graph, 6 self-test helpers); colcon total 172 tests, 8 failures, all in files this branch does not touch (copyright bizzyboat_massabesic_launch.py; flake8 I100 simulator_launch.py:43; pep257 D213 bizzyboat_massabesic_launch.py, gazebo_ben_launch.py, gazebo_simulator_launch.py; plus the 3 CTest wrappers).
- Four-boat self-test (private ROS_DOMAIN_ID, default discovery): the first run, on a quiet host, passed 16 of 16 (including the new platforms check and the stricter graph check). Three later runs on the final head, on a loaded host (load average 5 to 15, another worktree running tests), passed 12, 12 and 15 of 16; the failing checks differ each time (a boat's chart_datum frames, one boat not moving, one boat's CUBE coverage). Causes seen in the logs: (1) `mbes_sim` exits with code 1 at startup when its first odometry arrives before the TF frame exists, because `marine_autonomy/nav.py` `positionLatLon` calls `get_logger().error(e)` with an exception object (TypeError inside the except handler, line 314); launch respawns it but nobody re-runs configure/activate, so that boat's sonar and CUBE stay inactive; (2) launch_ros lifecycle_event_manager abandons a change_state wait ("Abandoning wait for the '/<boat>/<node>/change_state' service response"), leaving one lifecycle node unconfigured. Neither is touched by this round; both predate it and both widen with host load. Needs a decision before the dry run (see the report).

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-09 15:30 -04:00
**By**: Claude Code Agent (Claude Sonnet)
**Verdict**: changes-requested

**Branch**: feature/issue-88 at `d07d0ef`
**Mode**: pre-push
**Depth**: Deep (reason: 1970 changed lines, 15 files outside .agent/); round 2 scaled down to the fixes since 22d4405
**Must-fix**: 2 | **Suggestions**: 4
**Round**: 2 | **Ship**: recommended — must-fix fell from 8 to 2, both precise mechanical fixes (a try/finally reorder and a quaternion normalisation); address them and ship, no third full round.

All twenty round-1 fixes were checked against the committed code and tests: eighteen hold. Two of the "fixed" items do not fully hold (the SIGTERM handling in the self-test, and set_pose still being able to hang the node on a quaternion input), which are the two must-fix items below. Specialists: static analysis (colcon ament_flake8, pep257, copyright, xmllint, lint_cmake clean on every file this branch added), governance and plan drift (read directly: plan, README and .agents/README.md are in sync with the code; test_demo_boats_selftest.py is in the plan's file table), Claude adversarial Lens A + Lens B (one fresh sub-agent, Sonnet), cross-model (codex EXIT=0; gemini EXIT=1, agy print timeout at 420 s, no findings), local model off. Both must-fix items were reproduced here, not only reported.
Build and test: asv_sim 33 tests, 0 failures, 1 skipped (copyright, pre-existing). marine_simulation 172 per colcon, 8 failures, all in files this branch did not touch (same 8 as round 1); pytest files: 87 launch, 9 graph, 6 self-test helpers, all pass.
Self-test: `demo_boats_selftest.py --start-launch` on private ROS_DOMAIN_ID 55, default discovery, host load about 2 at start: 16 of 16 pass, nothing left running. The pre-existing startup race (mbes_sim exit / abandoned change_state wait) did not occur on this run and the branch does not widen it; the self-test already names the failing check and boat when it does occur.

### Findings
- [ ] (must-fix) Self-test leaks the whole launch on SIGINT/SIGTERM: rclpy.init() installs its own signal handlers that shut the context down, so the `finally` in main() hits `rclpy.shutdown()` -> RCLError ("rcl_shutdown already called", reproduced on jazzy with both signals) and `stop_launch(proc)` never runs; the launch is in its own session so Ctrl-C does not reach it either. Round 1's "stops on SIGTERM" claim does not hold. Stop the launch in its own inner `finally` (first), use `rclpy.try_shutdown()`, guard `test.close()` — `marine_simulation/scripts/demo_boats_selftest.py:452` (cross-confirmed: Lens B and codex)
- [ ] (must-fix) set_pose validates the quaternion length but not its scale: a non-unit quaternion gives a wrong heading ((0,0,1,1) stores 333.4 instead of 0, reproduced) and a finite huge one ((1e308,1e308,1e308,-1e308)) passes, the norm overflows, yaw is NaN, the heading is stored and the geodesic solver hangs the one shared asv_sim, the very failure round 1's fix was for. Normalise (scale by the max component first), then require a finite heading before touching the dynamics, and add tests for (0,0,1,1) and the 1e308 case — `asv_sim/asv_sim/platform.py:197` (cross-confirmed: Lens A and codex)
- [ ] (suggestion) stop_launch only escalates to SIGKILL on timeout or ProcessLookupError; when the leader exits on SIGINT (or had already exited, the LaunchExited path) surviving children get only SIGINT, and a second Ctrl-C during the wait skips the kill. Always `killpg(SIGKILL)` after the wait and swallow ProcessLookupError — `marine_simulation/scripts/demo_boats_selftest.py:389`
- [ ] (suggestion) tide_speed_factor 0 is refused as not positive, but 0 is meaningful (asv_sim multiplies each constituent speed by it: a frozen tide, a sensible "no tide" demo setting); allow low=0.0 and update the README refusal list — `marine_simulation/launch/demo_boats_launch.py:565`
- [ ] (suggestion) Extra launch_args after `--start-launch` can contain `enable_joysticks:=`, `boats:=` or `roster_file:=`, which silently override the flags the self-test derived its expectations from (later argument wins), so it then checks the wrong node set; reject those prefixes in main() — `marine_simulation/scripts/demo_boats_selftest.py:417`
- [ ] (suggestion) test_the_stock_actions_do_leak... is a canary that will fail the build when launch_ros fixes its in-place list mutation; say so in the assert message (or xfail) so the failure reads as "delete the scoped subclasses", not as a regression — `marine_simulation/test/test_demo_boats_launch.py:376`

### Round-1 verification
- [x] All eight round-1 must-fix items and eleven of twelve suggestions hold in the committed code and tests (NaN roster, strict booleans, js<N> and realpath joystick checks, README/.agents corrections, heading test, datum preflight, graph check, package.xml, README items); the twelfth (joy_linux respawn) was a deliberate no-change, now documented.
- [x] check_datum_grids paths match mru_transform's chart_datum_launch.py defaults exactly; mbes_grid_file default is absolute, consistent with mbes_sim; no false refusal of a valid run found other than tide_speed_factor 0 above.
