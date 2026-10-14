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
- `./simulation_ws/test.sh launch_manager_proto marine_simulation`: 314 tests, 0 errors, 8 failures, 2 skipped. All 8 failures are the lint that was already failing in files this work does not touch (copyright of `bizzyboat_massabesic_launch.py`, flake8 I100 in `simulator_launch.py`, pep257 D213 in three launch files). Every `launch_manager_proto` test passes; the two skips are the host-only live test and the check that each launch file named in the configuration exists, which skips only the packages missing from this layer's path (`camp`, in ui_ws) after checking the rest.
- Host-only (`ROS_DOMAIN_ID=173`, no CAMP, no GUI): `test_demo_manager_live.py` 1 passed in 72.52s: boats READY under the manager, `demo_boats_selftest.py` passes against them, the group is stopped and restarted without losing a process, ctrl-c on the manager alone leaves nothing in the graph.
- Plain launch with the guard, `demo_boats_selftest.py --start-launch --boats bluefin,clownfish` on `ROS_DOMAIN_ID=176`: 5 of 5 runs passed (the issue recorded 4 of 6 without it); in 2 of the 5 the guard repaired one node that a lost reply had left in `inactive`.
- `pre-commit run --from-ref 4324569 --to-ref HEAD` (flake8): passed.

### Open items
- [ ] The `demo` profile (with CAMP) was not run: no GUI on the owner's desktop. `follows` is covered by the process test with a stand-in group and the unit tests.
- [ ] Reconcile `demo_manager.py` with the #94 whole-display launch when that lands (scorer parameter generation overlaps).
- [ ] rolker/unh_marine_autonomy#410 carries the design-document updates.

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-14 14:17 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)
**Verdict**: changes-requested

**Branch**: feature/issue-97 at `0c34207`
**Mode**: pre-push
**Depth**: Deep (reason: 6079 lines changed in 41 files, new package with concurrency and signal handling)
**Must-fix**: 9 | **Suggestions**: 19
**Round**: 1 | **Ship**: continue — several must-fix are real defects in shutdown and command handling (two independent confirmations each)

Specialists: static analysis (flake8 via pre-commit, clean), governance and plan drift (lead), Claude adversarial Lens A and Lens B (fresh subagents), cross-model Gemini and Codex (both ran). Raw cross-model findings kept in the main workspace scratchpad (.agent/scratchpad/launch_manager_97/review_round1/).

### Findings
- [x] (must-fix) F1 A malformed `~/command` (non-string `profile`) raises TypeError out of the subscription callback and silently ends the rclpy thread; the manager keeps running unmanaged. Also guard `_tick`/`_on_command`, make spinner death fatal — `manager_core.py:259`, `manager.py` (4 sources)
- [x] (must-fix) F2 `CLEAR_FAILURE` in a profile with no other running group makes every group STOPPED, so `exit_when_all_stopped` ends the manager before the operator can START — `manager_core.py` finished (Gemini; matches the README retry advice)
- [x] (must-fix) F3 Every start leaks a holder thread and a `LaunchSession` whose output/process collectors keep every line of every process forever (unbounded memory in a persistent manager) — `manager.py` LaunchRunner.start (Gemini, Codex)
- [x] (must-fix) F4 Convergence keeps sending transitions while the launch service shuts down, and groups can still start; suspend everything on shutdown — `manager_core.py` on_shutdown (Codex repro, Lens B)
- [x] (must-fix) F5 `demo_manager.py --roster` is never forwarded to the boats launch (`roster_file`), so names/poses disagree with the expected nodes and the scorer — `demo_manager.py`, `demo_manager.yaml` (Codex)
- [x] (must-fix) F6 `ament_index_python` is imported but not declared in package.xml — `launch_manager_proto/package.xml` (Gemini)
- [x] (must-fix) F7 `on_finished` (`service.shutdown`) is a silent no-op when it fires before the launch loop runs, but `_finished` is set, so an empty-profile manager never exits — `manager.py` _tick (Lens B)
- [x] (must-fix) F8 `_drop_converger` does not suspend, so a read in flight can still send transitions for a stopped group — `manager_core.py` (Gemini)
- [x] (must-fix) F9 A node never seen within `appear_timeout` (30 s) fails the group immediately, ignoring the group's `ready.timeout` (the scorer group has 60 s) — `manager_core.py` _BAD_NODE_STATUS (Lens A)
- [x] (suggestion) F10 STOP while the launch is still spawning processes marks the group STOPPED at once and drops its handlers; give a starting group a short grace — `manager_core.py` (Codex)
- [x] (suggestion) F11 `confirm_state` is not cleared on reaching target or on a state change; a later request can skip the confirming re-read — `lifecycle_core.py` (Lens A)
- [x] (suggestion) F12 A read in flight across `suspend()`/`resume()` is accepted as the new run's first observation (generation counter) — `lifecycle_core.py` (Lens A)
- [x] (suggestion) F13 Status is republished at the poll rate because reasons embed changing numbers (`retry in 0.4 s`) — `lifecycle_core.py`, `manager.py` _publish (Lens A, Gemini)
- [x] (suggestion) F14 Config accepts what can never become ready: `expect` greater than an explicit node list, empty `match`, duplicate `nodes`, `ready.nodes` without a leading slash — `config.py` (Lens A, Gemini)
- [x] (suggestion) F15 `${KEY}` placeholders only work for `expect`; numeric and boolean fields reject the text — `config.py` (Gemini)
- [x] (suggestion) F16 `converge` CLI: misleading defaults/help for `--expect`/`--quiet-period`, and the early-failure break ignores MISSING nodes — `cli.py` (Lens A, Gemini)
- [x] (suggestion) F17 `status`/`command` CLIs crash with KeyError on a snapshot without `acks` — `cli.py` (Lens B, Gemini)
- [x] (suggestion) F18 SIGHUP is unhandled (closing the terminal orphans the groups) — `manager.py` (Lens B)
- [x] (suggestion) F19 `terminate_leftovers` can signal a recycled pid; verify the group tag in /proc/<pid>/environ first — `manager.py` (Lens B, Gemini)
- [x] (suggestion) F20 `stop()`/`group_stopped()` can raise on a closing loop and kill the rclpy thread; wrap them — `manager.py` (Lens B)
- [x] (suggestion) F21 The live test's CTest registration has the default 60 s timeout — `marine_simulation/CMakeLists.txt` (Lens B)
- [x] (suggestion) F22 `demo_manager.py` leaks a /tmp directory per run and per refused run — `demo_manager.py` (Lens B)
- [x] (suggestion) F23 Reject `..` and absolute paths in `launch: {package, file}`; state in the README that the config and command topic are trusted — `config.py`, README (Lens B)
- [x] (suggestion) F24 `_stop_all_issued` is never reset when a group is started again after a stop-everything (non-scoped runner only) — `manager_core.py` (Lens A)
- [x] (suggestion) F25 `destroy_node()` may run while the spinner thread is still alive after the join timeout — `manager.py` run_manager (Gemini)
- [x] (suggestion) F26 A guard that cannot fix the boats is only visible as a process exit line; document, no code (deferred) — `demo_boats_launch.py` (Lens B) (addressed in docs only: marine_simulation README says how quiet the plain-launch guard is)
- [x] (suggestion) F27 `follows` with a runner that cannot stop one group fails the followers (non-scoped runner only; the shipped runner is scoped) — `manager_core.py` (Lens A) (deferred) (deferred: only a runner that cannot stop one group is affected; the shipped LaunchRunner can, and the failure is loud, FAILED with the reason)
- [x] (suggestion) F28 A node stuck in a transition after READY leaves the group DEGRADED, never FAILED (visible in status; by design) (Gemini) (deferred) (deferred: visible as DEGRADED with the node and its state in status; making it FAILED would turn a slow transition into a sticky failure)

Dismissed after checking: Gemini's shared-environment race between groups (the launch loop visits one description at a time, on one thread); Gemini's `ChangeState` probe only matching transition 1 (launch_ros's handler matches every `ChangeState` event); command-topic flooding and authentication (the manager is a trusted-network design like udp_bridge; stated in the README).

## Implementation
**Status**: complete
**When**: 2026-10-14 14:28 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Branch**: feature/issue-97 at `0c51b5d` (not pushed)
**Addressed**: `## Local Review (Pre-Push)` round 1 (branch at `0c34207`): 28 findings, 9 must-fix
**Commits**: `f2d5ce1` (core), `cd22486` (manager process), `6897c9c` (config and CLI), `09459aa` (demo starter), README commit, `0c51b5d` (boxes checked)

### Actions
- [x] F1 non-string profile / any exception in a command rejected; bad tick or command logged and survived; dead executor shuts the service down — `manager_core.py`, `manager.py`
- [x] F2 CLEAR_FAILURE keeps an all-stopped manager alive until START or SET_PROFILE — `manager_core.py`
- [x] F3 groups use a session without the unbounded collectors; holder threads end with the group — `manager.py`
- [x] F4 nothing converges or starts during shutdown — `manager_core.py`
- [x] F5 `--roster` forwarded to the boats launch — `demo_manager.py`, `demo_manager.yaml`
- [x] F6 `ament_index_python` declared, plus a test that every import is declared — `package.xml`, `test_boundary.py`
- [x] F7 finished-shutdown retried until the loop runs — `manager.py`
- [x] F8 dropped converger suspended first — `manager_core.py`
- [x] F9 never-seen node no longer fails the group before its ready timeout — `manager_core.py`
- [x] F10 – F25 as listed in the review entry (start grace, confirm reset, generation counter, stable reasons, config validation, placeholder scalars, CLI fixes, SIGHUP, pid tag check, exception guards, CTest timeout, temp directory, launch path bounds, stop-all flag, node destroy)
- [x] F26 addressed in the README only — `marine_simulation/README.md`
- [x] F27 deferred (deferred: only a runner that cannot stop one group is affected; the shipped LaunchRunner can, and the failure is loud) — `manager_core.py`
- [x] F28 deferred (deferred: a node stuck after READY shows as DEGRADED with its state; a sticky FAILED would punish a slow transition) — `manager_core.py`

### Verification
- `./simulation_ws/test.sh launch_manager_proto marine_simulation`: 357 tests, 0 errors, 8 failures, 2 skipped. The same 8 pre-existing marine_simulation lint failures in files this work does not touch; every launch_manager_proto test passes.
- Host-only on `ROS_DOMAIN_ID=173`: `test_demo_manager_live.py` 1 passed in 70.40s. Plain launch with the guard, `demo_boats_selftest.py --start-launch --boats bluefin,clownfish` on 176: exit 0, 12 PASS.

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-14 14:37 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)
**Verdict**: approved

**Branch**: feature/issue-97 at `3741e5a`
**Mode**: pre-push
**Depth**: Deep (reason: whole diff still 6000+ lines; this round re-read the fix delta of 20 files)
**Must-fix**: 3 (all fixed in `3741e5a`) | **Suggestions**: 14 (10 fixed, 4 deferred with reasons)
**Round**: 2 | **Ship**: recommended — must-fix fell from 9 to 3, all mechanical and fixed; the remaining open items are visible-by-design deferrals

Specialists: Claude adversarial Lens A and Lens B on the fix delta (fresh subagents), Gemini on the whole diff. Codex was unavailable (usage limit reached); noted, not retried. The findings below were fixed before this entry was written, so the boxes are checked against `3741e5a`. A third independent read was not run.

### Findings
- [x] (must-fix) G1 START or SET_PROFILE during the stop grace released a group whose launch was still spawning, then launched it a second time — `manager_core.py` _step STOPPING branch (Lens A)
- [x] (must-fix) G2 with a runner that cannot stop one group, a stop-everything during the grace never issued `stop_all` once the late process appeared (state was already STOPPING) — `manager_core.py` _step_stopped (Lens A)
- [x] (must-fix) G3 the SIGTERM/SIGHUP handler called `shutdown()`, which holds a lock while waiting for the loop the handler runs on: deadlock against a shutdown from the manager thread — `manager.py` (Lens B)
- [x] (suggestion) G4 the grace path did not suspend the converger — `manager_core.py` (Lens A)
- [x] (suggestion) G5 a signal before the loop starts was swallowed — `manager.py` (Lens B)
- [x] (suggestion) G6 the signal comment overstated an orderly stop; launch's own SIGTERM handler cancels the run — `manager.py` (Lens B)
- [x] (suggestion) G7 the core was not told about a shutdown on the cancel path — `manager.py` (Lens B)
- [x] (suggestion) G8 the /proc tag check matched a substring and not the attributed group — `manager.py` (Lens B)
- [x] (suggestion) G9 close() could stall five seconds per stuck holder thread — `manager.py` (Lens B)
- [x] (suggestion) G10 `converge.settle` accepted nan and inf — `config.py` (Lens A, Lens B)
- [x] (suggestion) G11 a vacuous assertion; the property the holder threads rely on (leaving a group session never shuts the service down) is now tested on the real class — `test_launch_runner.py` (Lens B)
- [x] (suggestion) G12 `_hold_open` never lapsed or cleared by STOP — `manager_core.py`, README (Lens A, Gemini)
- [x] (suggestion) G13 a late-spawned process after the grace is stopped but its launch_ros handlers stay registered until the next stop — `manager_core.py` (Lens B) (deferred: acceptable for a prototype; the processes are stopped, only handlers linger; no code)
- [x] (suggestion) G14 a node seen before and now silent leaves the group DEGRADED with "no answer to get_state", never FAILED — `lifecycle_core.py` (Gemini) (deferred: a dead process fails or respawns through the exit events; a visible but unresponsive one is shown with its reason)
- [x] (suggestion) G15 a followed group that crashes does not stop its followers (Gemini) (deferred: the documented rule, only a clean close cascades)
- [x] (suggestion) G16 `will_respawn` reads launch's private fields (Gemini, Lens B) (deferred: failing safe, pinned by a test against the installed launch)
- [x] (suggestion) G17 a single missed `node_visible` tick degrades a group (Gemini) (deferred: only `ready.nodes` is affected and the demo does not use it)

Dismissed after checking: Gemini's claim that stopping one group shuts the shared LaunchService down (`_GroupSession` keeps no process collectors, so the exit path never calls shutdown; now a test), the shared-environment race (the launch loop visits one description at a time) and non-thread-safe `emit_event` (launch documents it as thread-safe).

## Implementation
**Status**: complete
**When**: 2026-10-14 14:46 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Branch**: feature/issue-97 at `449f2ee` (not pushed)
**Addressed**: `## Local Review (Pre-Push)` round 2 (G1 - G17; fixed in the same pass that produced the entry)
**Commits**: `3741e5a` (round 2 fixes), `449f2ee` (test flake: a forked child shows its parent's environment until exec)

### Actions
- [x] G1 – G3 (must-fix) start grace and its START/STOP interactions, signal handler without the service lock — `manager_core.py`, `manager.py`
- [x] G4 – G12 suspend in the grace, signal before the loop, honest comment, shutdown told on every exit path, exact group tag, one join budget, finite settle, real-class session test, hold lapse
- [x] G13 – G17 deferred with reasons in the review entry (late spawn handlers, silent node, crash cascade, private launch fields, discovery debounce)

### Verification
- `./simulation_ws/test.sh launch_manager_proto marine_simulation`: 364 tests, 0 errors, 8 failures, 2 skipped. The 8 are the pre-existing marine_simulation lint in files this work does not touch; every launch_manager_proto test passes.
- Host-only on `ROS_DOMAIN_ID=173`: `test_demo_manager_live.py` 1 passed in 72.17s. Plain launch with the guard on 176: `demo_boats_selftest.py --start-launch --boats bluefin,clownfish` exit 0, 12 PASS. No process of this worktree was left running afterwards.
