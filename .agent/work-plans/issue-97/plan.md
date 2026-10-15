# Plan: Prototype the launch/lifecycle manager as the demo's launch system — milestone 1

## Issue

https://github.com/rolker/unh_marine_simulation/issues/97 (closes the bug record #96; part of #87; #94 whole-display launch stays the fallback, untouched)

## Context

Intermittently a boat's lifecycle node never leaves `inactive` because the `change_state` reply was lost and the launch's one-shot `ChangeState` chain never retries (#96). The design in `unh_marine_autonomy/docs/launch_manager.md` (Proposed, uma#327) answers it with "converge, do not command" inside a persistent manager built on `ros2launch_session`. This milestone builds the smallest slice of that design that fixes #96 and runs the demo: a convergence core, groups/desired state/one profile on one shared `LaunchService`, a minimal status/command surface and a status CLI, and a stop-propagation rule so closing CAMP ends the demo. Review-issue (progress.md) flagged six items the plan must decide; each is answered below.

## Approach

1. **Package layout (marine-free boundary).** New ament_python package `launch_manager_proto/` at the repo root, deps only `rclpy`, `launch`, `launch_ros`, `lifecycle_msgs`, `std_msgs`, `ros2launch_session`, `python3-yaml` (plus `ament_index_python` for resolving launch files). Modules: `lifecycle_core.py` (pure Python convergence state machine over an injected `Backend` and clock), `lifecycle_rclpy.py` (the backend: `get_state`/`change_state` clients with deadlines, graph discovery), `config.py` (YAML, `${placeholder}` substitution, validation), `manager_core.py` (pure Python groups, desired state, profiles, `requires`, `follows`, commands, status), `manager.py` (the manager node, the shared `LaunchService`, process attribution, scoped stop), `cli.py` (`manager`, `status`, `command`, `converge`; one `launch_manager_proto` console script). Demo specifics only in `marine_simulation`: `config/demo_manager.yaml` and `scripts/demo_manager.py` (builds the placeholder values and the scorer parameters from `demo_roster.yaml`, then calls `run_manager`). `test_boundary.py` checks imports and `package.xml` against a generic allowlist and forbids marine package names, so moving out is `git mv` plus a rename.

2. **Convergence semantics (the core).** Per managed node, per tick; decisions use `get_state` only, a `change_state` reply is advisory.
   - Observed states: `unconfigured`, `inactive`, `active`, `finalized`, the transitional ids, and `unknown` (no answer).
   - On target: nothing, counters reset. Transitional states are **in flight**: nothing is sent, `STUCK` after `inflight_timeout` (15 s) and still nothing is sent. `unknown` never commands; a node never seen within `appear_timeout` is `MISSING`. `finalized` is reported, not commanded.
   - Off target and settled: one hop (target active: `unconfigured`->configure, `inactive`->activate; target inactive: `active`->deactivate, `unconfigured`->configure; target unconfigured: `active`->deactivate, `inactive`->cleanup), then re-read.
   - **Settle and confirm.** A request is sent only when the state has been *unchanged* for `settle` seconds (not merely since first seen) **and** a second read taken right before still shows the same state. Reason: `rclpy.lifecycle` nodes die on a transition that is invalid for their state (`Transition is not registered` escapes the service callback; found live), so a stale decision kills a Python node. Every request sent is logged with its attempt number.
   - **Retry ladder** (per node, per from-state): after sending, wait for the reply or `reply_timeout`, then **poll `get_state`** regardless. A state that moved off the from-state means the transition happened whatever the reply said (the lost reply of #96). A state that did not move, or `success=false`, is one failed attempt; wait the next `backoff` entry, re-read, re-send only if still off target. `max_attempts` (5) per from-state, then `FAILED` with the reason, sticky until `CLEAR_FAILURE`. Counters reset on target.

3. **Lost-reply detection and testing.** `FakeLifecycleNode` (a plain rclpy node serving the real `lifecycle_msgs` services, `test/fake_lifecycle_node.py`) with fault knobs `lose_reply_on` (performs the transition, holds the response past `reply_timeout`), `ignore_request_on`, refuse, transition duration; the same scenarios run on a fake backend with a virtual clock in `test_lifecycle_core.py`, and through real services in `test_lifecycle_rclpy.py` (lost configure reply reaches active; ignored request retried; exhausted budget `FAILED`; a stock rclpy lifecycle node; discovery).

4. **Groups, desired state, one profile, one LaunchService.** Config: `manager` {`name`, `default_profile`, `status_period`, `exit_when_all_stopped`, `converge`}; per group {`launch` ({package,file} or {path}), `arguments` (declared defaults), `requires`, `follows`, `lifecycle` {`match` or `nodes`, `expect`, `target`}, `ready` {`nodes`, `timeout`}, `restart`, `description`}; `profiles`. The main thread runs the single `LaunchService` (`shutdown_when_idle=False`); one single-threaded rclpy executor thread runs everything else, so the core needs no locks (process events cross through a queue). Each group is injected with `LaunchSession.from_service`, its context held open by a thread until the manager exits. Profile bulk-writes desired state once; `profile_actual` derived. Convergence is suspended once a group is stopping; a stopped group reports no lifecycle nodes. **The manager is the only lifecycle writer in a group with a `lifecycle` section:** launch_ros's per-node `ChangeState` handler is not registered inside the manager's service (see Implementation Notes). Respawning processes are repaired, not failed.

5. **Scoped group stop: the spike succeeded.** Each group's description is wrapped in a scoped `GroupAction` with `SetEnvironmentVariable(LAUNCH_MANAGER_GROUP)`; process events carry the tag in `event.env`; stopping a group emits one `ShutdownProcess(matches_pid)` per attributed pid, once each, repeated on later ticks for late starters. A group restarts with fresh processes once its recorded event handlers are unregistered (`OnShutdown` handlers excepted). So per-group `STOP`/`START`/`SET_PROFILE` subsets ship. The mechanism belongs in `ros2launch_session` as a scoped-shutdown call; not changed here. (The core still gates on `runner.supports_scoped_stop`; with a runner that lacks it, per-group stops are `REJECTED` and only stop-everything works.)

6. **Status/command interface: plain `std_msgs/String` carrying versioned JSON** (owner-approved for the prototype). Full snapshot every `status_period` and on change, an `acks` ring of the last 8 results, commands `SET_PROFILE`, `START`, `STOP`, `CLEAR_FAILURE`, repeated `request_id` a no-op. Field names mirror the design's messages. CLI: `status` (table, `--json`), `command`, `converge`.

7. **"Closing CAMP stops the demo" as a dependency rule.** `requires` keeps its design meaning. New key `follows`: a group is stopped when a followed group closes cleanly. Demo: `camp` has `restart: never`, `requires: [boats]`; `boats` and `scorer` follow it. A clean exit of the last process of a `restart: never` group is an operator decision (desired `STOPPED`); under `on-failure` it is a failure; a crash does not cascade. `exit_when_all_stopped` ends the manager.

8. **Standalone guard (fixes #96 for the #94 fallback).** `launch_manager_proto converge --match REGEX --expect N --settle S --quiet-period Q` runs the same core without groups. `demo_boats_launch.py` gains `lifecycle_guard` (default **true**, owner decision) that starts it; the manager passes `lifecycle_guard:=false` (one writer). The guard coexists with the launch's own chains, so it waits for a quiet state; that narrows the race with a slow chain, it cannot close it.

9. **Tests.** `test_lifecycle_core.py`, `test_config.py`, `test_manager_core.py` (fake runner and graph), `test_launch_runner.py` (pid attribution, leftovers, handler bookkeeping, respawn), `test_boundary.py`; `test_lifecycle_rclpy.py` (real services); `test_launch_manager.py` (the real manager process with fake lifecycle nodes that lose replies: READY, `requires`, `follows`, ctrl-c and SIGTERM on the manager alone, per-group stop and restart, the guard, the status CLI); in `marine_simulation`: `test_demo_manager.py` (configuration with the roster), guard tests in `test_demo_boats_launch.py`, and the host-only `test_demo_manager_live.py` (boats under the manager, `demo_boats_selftest.py` against them, stop and restart of the group, ctrl-c, nothing left in the graph; skipped with a reason unless `ROS_DOMAIN_ID` is a private domain above 100 and the datum grids exist).

10. **Docs in the same PR.** `launch_manager_proto/README.md`, the `marine_simulation/README.md` sections, `.agents/README.md`.

## Deferred (explicitly, from the design's open items and scope)

Output retention and any output channel; stale-command/reordering defence; `force`; sticky-`FAILED` on link groups; `delegate` lifecycle (Nav2); readiness predicates beyond node presence and lifecycle; `exec:` groups; per-group `environment`, `restart_defaults`, `shutdown` timeouts; automatic group restart and the respawn/retry budgets (a dead process fails the group with its cause); `RESTART`, `SET_LIFECYCLE`, `RELOAD_CONFIG`; services, diagnostics, own interfaces package; front ends; persistence; cross-host; arguments carried by commands; the `autostart` versus non-`active` target conflict (does not arise: the manager is the only writer in its groups). The target-area publisher (#93) is a comment in the configuration, not a group.

## Files to Change

| File | Change |
|------|--------|
| `launch_manager_proto/{package.xml,setup.py,setup.cfg,LICENSE,resource/*,README.md}` | New ament_python package |
| `launch_manager_proto/launch_manager_proto/{lifecycle_core,lifecycle_rclpy,config,manager_core,manager,cli}.py` | Core, rclpy backend, configuration, manager logic, manager node and runner, CLI |
| `launch_manager_proto/test/*` | Fakes, fake lifecycle node, unit, rclpy, process and boundary tests, ament lint tests |
| `marine_simulation/config/demo_manager.yaml`, `marine_simulation/scripts/demo_manager.py` | Demo groups and profiles; starter filling placeholders from the roster |
| `marine_simulation/launch/demo_boats_launch.py` | `lifecycle_guard` argument and `lifecycle_guard_command` |
| `marine_simulation/test/{test_demo_manager,test_demo_manager_live}.py`, `test_demo_boats_launch.py` | Configuration tests, host-only live test, guard tests |
| `marine_simulation/{package.xml,CMakeLists.txt,README.md}`, `.agents/README.md` | Dependencies, install and test registration, docs |

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

Answered by the owner (2026-10-14): `lifecycle_guard` defaults on; JSON in `std_msgs/String` accepted; closing CAMP stops the whole demo and the manager exits; no stub group for #93; all-or-nothing is acceptable if the spike fails (it did not); keep the name `launch_manager_proto`; record deviations in the package README and file a follow-up for the design document (rolker/unh_marine_autonomy#410).

Still open for the owner:
- The `demo` profile (with CAMP) was not run: a CAMP window on the owner's desktop was off limits. The `headless` profile and the fake-launch `follows` test cover everything but CAMP's own exit code.
- `demo_manager.py` does not yet replace #94's whole-display launch; the two should be reconciled when #94 lands (scorer parameter generation overlaps).

## Estimated Scope

Single PR, about 8-10 atomic commits (core+tests, rclpy backend+tests, config, manager, scoped-stop spike result, CLI, demo config/launch, guard, docs). Large for one PR but one milestone; if the spike or the launch-level tests overrun, the scoped-stop and group-restart pieces are the first to cut (already deferrable).

## Implementation Notes

Rationale-bearing pivots from the plan as first written:

- **Sole writer.** The plan had the manager coexisting with launch autostart behind a settle delay. Live, a slow launch_ros chain still sent its unconditional `configure` after the manager had configured the node, and rclpy kills the node on that second request. Inside the manager's `LaunchService`, the `ChangeState` handler launch_ros registers per lifecycle node is not registered for groups with a `lifecycle` section. Measured live: 38 transitions per start, all by the manager, no node lost over four restarts; with coexistence a cold start had already lost `platform_sender`.
- **Handler cleanup on stop.** The spike's "restarts cleanly" needed the group's event handlers unregistered (and `OnShutdown` handlers kept); without it a restarted group's Python nodes all died, and with the `OnShutdown` handler removed the process could not exit.
- **Signals.** `SignalHandlerOptions.NO` for rclpy; own SIGTERM handler (launch installs none); leftover processes stopped by pid.
- **`demo_manager.py` instead of `demo_manager_launch.py`.** The manager is a long-running process that owns its own `LaunchService`; wrapping it in `ros2 launch` would put one service inside another's child for nothing.
- **`shutdown` timeouts dropped.** Nothing applied them; launch's per-process defaults rule.
