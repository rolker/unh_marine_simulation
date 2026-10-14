---
issue: 97
---

# Issue #97 — Prototype the launch/lifecycle manager in this repo as the demo's launch system — milestone 1

## Issue Review
**Status**: complete
**When**: 2026-10-14 12:27 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Issue**: #97
**Comment**: (best-effort post follows this entry; not recorded inline)
**Scope verdict**: well-scoped (large; one PR only if the plan cuts hard to the listed items)

### Actions
- [ ] Action needed: pin the marine-free boundary as a concrete package layout (new package, deps limited to rclpy/launch/launch_ros/lifecycle_msgs/ros2launch_session; demo config in marine_simulation) so the later move is a `git mv` (issue asks for this; "or a sibling package" leaves it open).
- [ ] Action needed: decide the interface shape for `~/status` / `~/command` in the plan (own msgs vs std_msgs strings). The design says own interfaces package with no marine_interfaces dependency; a prototype that is meant to be moved must not leak a throwaway wire format into the real repo unannounced.
- [ ] Action needed: item 1 requires the convergence loop to be usable standalone (post-launch guard for demo_boats_launch.py) AND inside the manager. Plan must make the core a library plus a thin node/CLI so both entry points share one code path.
- [ ] Action needed: the "lost change_state reply" test (item 6) needs a deterministic fake; plan must say how a lost reply is injected and detected (get_state polling) rather than relying on the field race.
- [ ] Action needed: item 5 ("closing CAMP stops the demo") must be a `requires`-style dependency rule, but the design's `requires` means "must be READY before start" only; stop-propagation is a new semantic. Plan must define it (e.g. a `stops_with` / `bound_to` key) and record it as a deviation from the design.
- [ ] Action needed: launch-level test (item 6) needs the datum grids and ~50 processes; plan must say what runs in CI/ci_local versus on the dev host only (mark host-only tests, do not skip silently).
- [ ] Recommendation: state which design open items are deferred (output channel, stale-command reordering, ack slot, force field, sticky FAILED on link groups, scoped group shutdown beyond all-or-nothing, delegate, readiness predicates beyond nodes/lifecycle_active).
- [ ] Recommendation: consequences to land in the same PR: marine_simulation README (demo section), .agents/README.md package inventory and layout, package.xml exec_depend changes, and a note on #96 linking the fix.
- [ ] Recommendation: ADR-0008 conventions apply (license headers, ament_python layout, flake8 config incl. D213 style already used here); no ADR needed (design doc says deliberately none).

## Plan Authored
**Status**: complete
**When**: 2026-10-14 12:29 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Plan**: `.agent/work-plans/issue-97/plan.md` at `78861da`
**Branch**: feature/issue-97 at `78861da`
**Phases**: single

### Open questions
- [ ] lifecycle_guard default on in demo_boats_launch.py?
- [ ] JSON in std_msgs/String acceptable for the prototype wire format?
- [ ] Closing CAMP stops the whole demo and exits the manager?
- [ ] Target-area publisher (#93) stub group now or later?
- [ ] Scoped-stop spike fails: accept all-or-nothing with per-group STOP/START rejected?
- [ ] Package name launch_manager_proto, rename at move time?
- [ ] Record design deviations in the uma design doc via follow-up, or only in this README?

## Plan Review
**Status**: complete
**When**: 2026-10-14 12:29 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5) (in-context — author self-review)

**Plan**: `.agent/work-plans/issue-97/plan.md` at `14c09c1`
**PR**: PR-less
Independence uncertain: this review ran in the same context that authored the plan (no fresh dispatch), and the By model string matches the author's.
**Verdict**: changes-requested (must-fix items folded into the plan in the same commit; ready for implementation once re-read)

### Findings
- [x] (must-fix) Step 4 said `restart: on-failure` means group restart while the Deferred list says there is no group restart; contradictory. Folded in: both behave the same except clean exit; dead process -> FAILED with cause.
- [x] (must-fix) Step 8 guard plus the manager would be two convergence loops driving the same nodes. Folded in: one-writer rule, `lifecycle_guard:=false` for the managed boats group, test in both directions.
- [x] (must-fix) Convergence after a group stops was unspecified (would fight shutdown, report MISSING). Folded in: convergence suspended unless desired RUNNING and launch started; test (e2).
- [ ] (suggestion) New package should carry a LICENSE file and the ament lint tests (copyright/flake8/pep257) like marine_simulation; list in Files to Change.
- [ ] (suggestion) The scorer's node name/namespace is not verified in the plan; confirm the coverage_assessment_node naming before writing its match regex.
- [ ] (suggestion) If boats go FAILED, camp stays BLOCKED with no CAMP window; say in the README what a helper sees (status CLI) and consider a log line naming the failed node.
- [ ] (suggestion) Scope is above the 10-file guideline; cut order (scoped stop, then guard, then host-only test) is already stated and acceptable.

## Implementation
**Status**: complete
**When**: 2026-10-14 14:09 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Branch**: feature/issue-97 at `7e11203` (not pushed)
**Plan**: `.agent/work-plans/issue-97/plan.md`, brought in line with the built code (see its Implementation Notes)

### What was built
- `launch_manager_proto`: convergence core, rclpy backend, configuration, groups/profiles/`requires`/`follows`, manager node on one shared LaunchService, scoped group stop, CLI (`manager`, `status`, `command`, `converge`).
- `marine_simulation`: `demo_manager.py` + `config/demo_manager.yaml` (groups boats, camp, scorer; profiles demo, headless, boats), `lifecycle_guard` in `demo_boats_launch.py` (default on).
- Docs: `launch_manager_proto/README.md`, `marine_simulation/README.md`, `.agents/README.md`.

### Verification
- `./simulation_ws/test.sh launch_manager_proto marine_simulation`: 314 tests, 0 errors, 8 failures, 2 skipped. All 8 failures are the lint that was already failing in files this work does not touch (copyright of `bizzyboat_massabesic_launch.py`, flake8 I100 in `simulator_launch.py`, pep257 D213 in three launch files). Every `launch_manager_proto` test passes; the two skips are the host-only live test and one pre-existing skip.
- Host-only (`ROS_DOMAIN_ID=173`, no CAMP, no GUI): `test_demo_manager_live.py` 1 passed in 72.52s: boats READY under the manager, `demo_boats_selftest.py` passes against them, the group is stopped and restarted without losing a process, ctrl-c on the manager alone leaves nothing in the graph.
- Plain launch with the guard, `demo_boats_selftest.py --start-launch --boats bluefin,clownfish` on `ROS_DOMAIN_ID=176`: 5 of 5 runs passed (the issue recorded 4 of 6 without it); in 2 of the 5 the guard repaired one node that a lost reply had left in `inactive`.
- `pre-commit run --from-ref 4324569 --to-ref HEAD` (flake8): passed.

### Open items
- [ ] The `demo` profile (with CAMP) was not run: no GUI on the owner's desktop. `follows` is covered by the process test with a stand-in group and the unit tests.
- [ ] Reconcile `demo_manager.py` with the #94 whole-display launch when that lands (scorer parameter generation overlaps).
- [ ] rolker/unh_marine_autonomy#410 carries the design-document updates.
