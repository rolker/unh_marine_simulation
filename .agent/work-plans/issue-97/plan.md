# Plan: Prototype the launch/lifecycle manager as the demo's launch system — milestone 1

## Issue

https://github.com/rolker/unh_marine_simulation/issues/97 (closes the bug record #96; part of #87; #94 whole-display launch stays the fallback, untouched)

## Context

Intermittently a boat's lifecycle node never leaves `inactive` because the `change_state` reply was lost and the launch's one-shot `ChangeState` chain never retries (#96). The design in `unh_marine_autonomy/docs/launch_manager.md` (Proposed, uma#327) answers it with "converge, do not command" inside a persistent manager built on `ros2launch_session`. This milestone builds the smallest slice of that design that fixes #96 and runs the demo: a convergence core, groups/desired state/one profile on one shared `LaunchService`, a minimal status/command surface and a status CLI, and a stop-propagation rule so closing CAMP ends the demo. Review-issue (progress.md) flagged six items the plan must decide; each is answered below.

## Approach

1. **Package layout (marine-free boundary).** New ament_python package `launch_manager_proto/` at the repo root, deps only `rclpy`, `launch`, `launch_ros`, `lifecycle_msgs`, `std_msgs`, `ros2launch_session`, `python3-yaml` (no `marine_*`, no `ament_index` lookups of marine packages). Modules, each importable without the others where possible:
   - `lifecycle_core.py` — pure Python, no rclpy: the convergence state machine over an injected `Backend` (`get_state(node)`, `change_state(node, transition)`) and an injected clock. Fully unit-testable.
   - `lifecycle_rclpy.py` — the `Backend` over rclpy async service clients (`<node>/get_state`, `<node>/change_state`), node discovery from the graph, per-call timeouts.
   - `config.py` — YAML load and validation (acyclic `requires`, profiles name known groups, a profile naming a group with unsatisfied `requires` is rejected at load, as the design says).
   - `manager.py` — the manager node and group runner. `cli.py` — `status`, `command` and `converge` (standalone guard) subcommands, one `launch_manager_proto` console script.
   Demo-specific content lives only in `marine_simulation`: `config/demo_manager.yaml` (groups, profiles) and `launch/demo_manager_launch.py` (builds the boat regex from `demo_roster.yaml`, starts the manager). Moving out later is `git mv launch_manager_proto` plus renaming; a test greps the package for `marine` to keep the boundary honest.

2. **Convergence semantics (the core).** Per managed node, per tick, and decisions use `get_state` only; a `change_state` reply is advisory, never trusted for correctness.
   - Observed states: `unconfigured`, `inactive`, `active`, `finalized`, the transitional ids (`configuring`, `activating`, `deactivating`, `cleaningup`, `shuttingdown`, `errorprocessing`), and `unknown` (service absent or `get_state` timed out).
   - `on_target`: observed == target. Transitional states are **in flight**: neither on target nor drift; the manager sends nothing and waits, bounded by `inflight_timeout` (default 15 s), after which the node is reported `STUCK` (still sends nothing; a request into a transition in flight is what the design warns against). `unknown` never causes a command (cannot compare), only a retry of `get_state` and a report; a node expected but never seen within `appear_timeout` is `MISSING`.
   - Off target and settled: choose the next single hop (target active: `unconfigured`->configure, `inactive`->activate; target inactive: `active`->deactivate, `unconfigured`->configure; target unconfigured: `active`->deactivate, `inactive`->cleanup). One hop per tick, then re-read.
   - `finalized` is terminal for lifecycle repair: node reported `FINALIZED`, no command (process respawn is ladder step 2, deferred).
   - **Settle delay**: first command to a node waits `settle` (default 2 s) after it was first seen, so `autostart=True` launch files get to go first. When both race, the later request is refused by the node and the next read shows the truth; harmless by construction and covered by a test with a node that accepts two transitions back-to-back.
   - **Retry ladder** (per node, per from-state): after sending a transition, wait `reply_timeout` (5 s) for the reply, then **poll `get_state`** regardless. If the state advanced past the from-state the transition counts as done even if the reply never came (this is exactly #96). If not advanced, or the reply said `success=false`, that is one failed attempt; wait the next `backoff` entry ([0.5, 1, 2, 5, 5]), re-read, and re-send only if still off target. `max_attempts` (5) per from-state; exhausted -> node `FAILED` with the last reason, sticky until `CLEAR_FAILURE` or the next time the desired state is rewritten. Counters reset when the node is observed on target. Per-node reports carry attempts used, last result, reason. The manager's own clients may hit the same discovery race that causes #96 (request delivered, reply not yet matched), which is why correctness rests on `get_state` polling and not on any single reply.

3. **Lost-reply detection and testing.** Detection is the get_state poll above. Tests use a `FakeLifecycleNode` (plain rclpy node serving the real `lifecycle_msgs` `get_state`/`change_state` services, so the wire path is the real one) with fault knobs: `lose_reply_on=[n,...]` (performs the transition, then holds the response longer than `reply_timeout` so the client discards it: a lost reply as the manager sees it), `ignore_request_on=[n]` (request never acted on), `fail_transition_on=[n]` (returns `success=false`), `stay_in_transition_s` (reports `configuring` for a while), `finalized_after`. Pure-core tests drive the same scenarios on a fake backend with a fake clock (fast, exhaustive); the rclpy suite repeats the headline cases through real services (lost configure reply -> reaches active; ignored request -> retried; both exhausted -> FAILED).

4. **Groups, desired state, one profile, one LaunchService.** Config keys implemented: `manager` {`name`, `default_profile`, `status_period`, `exit_when_all_stopped`}; per group {`launch` {package,file} + `arguments` (declared and type-checked as in the design), `requires`, `follows`, `lifecycle` {`match` regex or `nodes`, `expect`, `target`}, `ready` {`lifecycle_active`, `nodes`, `timeout`}, `restart` (`never`/`on-failure`; this milestone treats both the same except for clean exit, see step 7 and Deferred: a dead process in a `READY` group goes `FAILED` with the cause, there is no automatic group restart), `shutdown` {timeout}}; `profiles`. The main thread runs the single `LaunchService` with `shutdown_when_idle=False`; rclpy spins on a worker thread. Each group's description is injected with `LaunchSession.from_service`; the context is held open by a per-group holder thread blocked on a stop event so leaving it never tears down the shared service (the design's hazard). Profile `demo` bulk-writes desired state once at start; `profile_actual` is derived (name or `custom`). No persistence. Lifecycle convergence for a group is active only while its desired state is `RUNNING` and its launch has started; it is suspended (no commands, no MISSING) once the group is `STOPPING`/`STOPPED`, so the manager never fights a shutdown or reports nodes of a stopped group as lost. Group states implemented: STOPPED, BLOCKED, STARTING, READY, DEGRADED, FAILED, STOPPING with `BLOCKED` pointing at the blocker.

5. **Scoped group stop: spike first, time-boxed to a few hours.** Attribution idea: wrap each group's description in `SetEnvironmentVariable('LAUNCH_MANAGER_GROUP', name)`; on `OnProcessStart` read the child's `/proc/<pid>/environ` to attribute pid -> group (not racy, the tag exists at spawn), then stop a group with one `ShutdownProcess` per pid (`matches_pid`). Gate: if a group can be stopped and restarted cleanly in the test, per-group `STOP`/`START` ship; if not, milestone ships the issue's all-or-nothing behaviour (STOP of everything via `LaunchService.shutdown()`), per-group `STOP`/`START` are answered `REJECTED: scoped stop not supported`, and the finding goes into the package README (it feeds the design's open item and the `ros2launch_session` scoped-shutdown option 2). Either way the issue's required behaviour is met.

6. **Status/command interface: plain `std_msgs/String` carrying versioned JSON, no new interfaces package yet.** Why: the design's message sketch is explicitly unsettled on three points (single ack slot, `force`, stale commands); a .msg package would freeze them and add a rosidl build to a prototype meant to be thrown into a new repo. JSON field names mirror `ManagerStatus`/`GroupStatus`/`Command` one-to-one (documented in the README) so converting to real messages is mechanical, and `schema: 1` is in every message. `~/status` is a full snapshot at `status_period` plus on change: manager name, `profile_actual`, `profiles_available`, groups [{name, desired, state, detail, state_since, blocked_by, lifecycle: {target, nodes: {name: {state, attempts, last_result, reason}}}}], and `acks`: the last 8 request results (`request_id`, `ACCEPTED`/`REJECTED`, detail), which resolves the one-ack-slot item at no cost. `~/command` carries `request_id`, `type` in {`SET_PROFILE`, `START`, `STOP`, `CLEAR_FAILURE`}, `profile`, `groups`; repeated `request_id` is a no-op. No `force`, `RESTART`, `SET_LIFECYCLE`, `RELOAD_CONFIG`. `launch_manager_proto status` prints a table from one snapshot (`--watch`, `--json`).

7. **"Closing CAMP stops the demo" as a dependency rule.** `requires` keeps the design meaning (must be READY before start). Add one new key, `follows: [groups]`: this group's desired state is written `STOPPED` when a followed group that had started leaves `RUNNING` **not at the manager's request**. In the demo: `camp`: `restart: never`, `requires: [boats]`; `boats`, `scorer`: `follows: [camp]`. A clean exit of a `restart: never` group is an operator decision: its desired state becomes `STOPPED` (detail `exited(0)`, WARN-level in the report), which pins that design open item for the prototype. `manager.exit_when_all_stopped: true` (demo) ends the manager process once everything is stopped, so `run_demo`-style wrappers return. Recorded as a deviation from the design in the README, with the `follows` semantics.

8. **Standalone guard (item 1 usable on its own, fixes #96 for the #94 fallback).** `launch_manager_proto converge --match REGEX --target active --expect N --timeout S` runs the same core without groups, exits 0 when all matched nodes are on target (and at least `N` seen), nonzero with the per-node report otherwise. `demo_boats_launch.py` gains an argument `lifecycle_guard` that appends a `launch_manager_proto` guard process (boat regex from the roster); default decided in Open Questions. **One writer rule**: a group launched by the manager must not also run the guard, or two convergence loops (guard and manager) drive the same nodes; `demo_manager.yaml` passes `lifecycle_guard:=false` to the `boats` group, and a launch test asserts the guard process is absent in the managed case and present in the plain `demo_boats_launch.py` case. No other repo's launch files change; `LifecycleNode(autostart=True)` stays as is.

9. **Tests** (pytest, `ament_add_pytest_test`). (a) core unit tests: every transition table row for the three targets, in-flight wait and STUCK, unknown never commands, settle delay, lost reply (state advanced), ignored request, `success=false`, exhausted -> FAILED, counter reset, finalized, MISSING. (b) rclpy tests with `FakeLifecycleNode` on a private domain (random `ROS_DOMAIN_ID`): lost configure reply, ignored request, two fake boats converging in parallel. (c) config tests: cycles, unknown group, unsatisfied `requires`, undeclared argument, type coercion. (d) launch-level, runs in CI: manager + a small synthetic launch file of fake lifecycle nodes (one with a lost first configure reply) reaches `READY`; `STOP` ends it; a followed group exiting stops the others and the manager exits. (e) launch-level, **host-only** (needs datum grids under `~/data/world/datum`, ~1 min, ~50 processes, private domain): `demo_manager_launch.py` with the camp-less `boats` profile reaches all-active for bluefin and clownfish and the existing `demo_boats_selftest.py` checks pass against it. It is skipped with an explicit reason string when the grids or `ROS_DOMAIN_ID` are absent, and run by hand before the PR with the result recorded in progress.md. (e2) the rclpy tests also cover suspension: stopping a group with nodes still being converged sends no further commands. (f) a boundary test: no `marine` string in `launch_manager_proto` sources or `package.xml`.

10. **Docs and cleanup in the same PR.** `launch_manager_proto/README.md` (what it is, layout, config schema as implemented, deviations from the design, deferrals, how to move out); `marine_simulation/README.md` demo section (how to start with the manager, the CAMP-closes-demo behaviour, `status`); `.agents/README.md` package inventory, layout tree, build line, and the pitfall that `from_service` closing tears down the shared service; comment on #96 linking the fix after merge.

## Deferred (explicitly, from the design's open items and scope)

Output retention and any output channel; stale-command/reordering defence; `force`; sticky-`FAILED` on link groups; `delegate` lifecycle (Nav2); readiness predicates beyond `lifecycle_active`/`nodes`/none (`topics`, `tcp_port`, `output`); ladder steps 2-3 (respawn budget, group restart; a group with `restart: on-failure` whose processes die goes `FAILED` with the cause in this milestone); `RESTART`, `SET_LIFECYCLE`, `RELOAD_CONFIG`; services, diagnostics, own interfaces package; front ends; persistence; cross-host; declared-argument ranges beyond type checks; the `autostart` versus non-active target conflict (documented, not detected).

## Files to Change

| File | Change |
|------|--------|
| `launch_manager_proto/{package.xml,setup.py,setup.cfg,resource/launch_manager_proto,README.md}` | New ament_python package, BSD header, deps listed in step 1 |
| `launch_manager_proto/launch_manager_proto/{lifecycle_core,lifecycle_rclpy,config,manager,cli}.py` | Core, rclpy backend, config, manager, CLI |
| `launch_manager_proto/test/*` incl. `fake_lifecycle_node.py` | Tests (a)-(f) |
| `marine_simulation/config/demo_manager.yaml`, `marine_simulation/launch/demo_manager_launch.py` | Demo groups, profiles `demo` and `boats`, roster-derived boat regex |
| `marine_simulation/launch/demo_boats_launch.py`, `marine_simulation/test/test_demo_boats_launch.py` | `lifecycle_guard` argument and its test |
| `marine_simulation/package.xml`, `marine_simulation/CMakeLists.txt` | exec_depend on `launch_manager_proto`; install, pytest registration |
| `marine_simulation/README.md`, `.agents/README.md` | Docs per step 10 |

## Principles Self-Check

| Principle | Consideration |
|---|---|
| Only what's needed | JSON strings instead of a msgs package; deferred list is long and explicit; target table small but complete because it is a few lines |
| Test what breaks | The failure that exists (lost reply) is reproduced deterministically; races, in-flight and exhaustion are tested |
| Workspace vs. project separation | Core has no marine dependency, enforced by a test; demo specifics only in `marine_simulation` config |
| A change includes its consequences | READMEs, inventory, package.xml, CMake in the same PR |
| Improve incrementally | One milestone, fallback #94 untouched, no edits in other repos |
| Human control and transparency | Per-node report with reason and attempts; a stuck or failed node is named, never silent (the #96 failure mode) |
| Enforcement over documentation | Boundary and schema-version rules are tests, not prose |

## ADR Compliance

| ADR | Triggered | How addressed |
|---|---|---|
| 0008 ROS 2 conventions | Yes | ament_python layout, license headers, flake8 config of this repo (D213 style), package.xml deps |
| 0009 Python packages | Yes | PyYAML via `python3-yaml`; no pip |
| 0013 progress.md vocabulary | Yes | Plan Authored / Plan Review / Implementation entries |
| 0001 ADRs | No | The design doc declares deliberately no ADR while the design evolves |

## Consequences

| If we change... | Also update... | Included in plan? |
|---|---|---|
| New package in the repo | `.agents/README.md` inventory/layout/build line | Yes |
| `demo_boats_launch.py` arguments | `marine_simulation/README.md`, launch test | Yes |
| Package parameters/topics (`~/status`, `~/command`) | Package README | Yes |
| Design deviations (`follows`, JSON wire, ack ring, clean-exit rule) | `unh_marine_autonomy/docs/launch_manager.md` | No — other repo; listed under Open Questions |

## Documentation & Instruction Impact

- **Stale docs** (must land in this PR): `marine_simulation/README.md` (demo start section), `.agents/README.md` (inventory, layout, build, pitfall list), new `launch_manager_proto/README.md`.
- **Agent-instruction candidates** (proposals only): the `from_service` context-manager teardown hazard and the env-tag process attribution (if the spike works) may merit a `.agent/knowledge/` note or an `ros2launch_session` README entry.

## Open Questions

- Should `lifecycle_guard` default to on in `demo_boats_launch.py` (fixes #96 for the #94 fallback immediately) or off until the manager is the demo launch?
- Is JSON-in-`std_msgs/String` acceptable for the prototype wire format, with real messages when the repo is created?
- When CAMP is closed, should the whole demo stop and the manager exit (plan), or only the boats/scorer with the manager staying up?
- Should the target-area publisher (#93) get a stub group in the demo profile now, or wait until #93 lands? Plan: no stub, config comment only.
- If the scoped-stop spike fails, is "per-group STOP/START REJECTED, all-or-nothing only" acceptable for this milestone? (Plan says yes, per the issue.)
- Package name: keep `launch_manager_proto` and rename to `ros2launch_manager` at move time?
- Should the design doc in unh_marine_autonomy be updated with the deviations by a follow-up there, or only recorded in this package's README?

## Estimated Scope

Single PR, about 8-10 atomic commits (core+tests, rclpy backend+tests, config, manager, scoped-stop spike result, CLI, demo config/launch, guard, docs). Large for one PR but one milestone; if the spike or the launch-level tests overrun, the scoped-stop and group-restart pieces are the first to cut (already deferrable).
