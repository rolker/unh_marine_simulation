# launch_manager_proto

A prototype of the persistent launch and lifecycle manager designed in
`unh_marine_autonomy/docs/launch_manager.md` (rolker/unh_marine_autonomy#327). It is the
demo's launch system for Ocean Discovery Day (rolker/unh_marine_simulation#97, umbrella #87)
and the seed of the real `ros2launch_manager` repository: **nothing in this package depends
on a marine package**, and a test (`test_boundary.py`) keeps it that way, so moving it out
is a `git mv` plus a rename. Platform specifics live in a configuration file; the demo's is
`marine_simulation/config/demo_manager.yaml`.

It does two things.

1. **Converges lifecycle nodes.** For every managed lifecycle node it reads the state,
   compares it with the target and takes one safe step. It never sends a transition without
   looking first, treats `configuring` / `activating` as in flight, and a lost
   `change_state` reply costs nothing, because the next read shows the node moved. This is
   the fix for rolker/unh_marine_simulation#96, where a lost reply left a boat's node in
   `inactive` for the whole session.
2. **Runs launch files as groups.** Per-group desired state (`RUNNING` / `STOPPED`) is the
   single source of truth; profiles bulk-write it once; groups start when the groups they
   `require` are READY; one group can follow another (closing CAMP stops the demo); status
   and commands travel over two topics.

## Quick start

```bash
# the demo (boats, CAMP, scorer); --profile headless leaves CAMP out
ros2 run marine_simulation demo_manager.py

ros2 run launch_manager_proto launch_manager_proto status
ros2 run launch_manager_proto launch_manager_proto command stop camp
ros2 run launch_manager_proto launch_manager_proto command set-profile headless
ros2 run launch_manager_proto launch_manager_proto command clear-failure boats

# your own configuration; ${KEY} placeholders are filled from --set KEY=VALUE
ros2 run launch_manager_proto launch_manager_proto manager --config my.yaml --set boats=a,b

# the convergence loop alone, as a guard after a launch you do not manage
ros2 run launch_manager_proto launch_manager_proto converge --match '^/(a|b)/' --expect 18
```

Run on a private `ROS_DOMAIN_ID`. `kill -USR1 <pid>` makes the manager print every thread's
stack, which is how a hung shutdown is diagnosed. Ctrl-C and SIGTERM (what systemd sends)
both stop every group and exit.

## Layout

| Module | What it is | ROS |
|---|---|---|
| `lifecycle_core.py` | The convergence state machine, a retry ladder, injected backend and clock | none |
| `lifecycle_rclpy.py` | The backend: `get_state` / `change_state` clients with deadlines, graph discovery | rclpy |
| `config.py` | YAML loading, `${placeholder}` substitution, validation | none |
| `manager_core.py` | Groups, desired state, profiles, `requires`, `follows`, commands, status | none |
| `manager.py` | The manager node, the shared `LaunchService`, process attribution, stopping | rclpy, launch |
| `cli.py` | `manager`, `status`, `command`, `converge` | rclpy |

`lifecycle_core.py` and `manager_core.py` are pure Python and are tested exhaustively on
fake backends and a virtual clock (`test/fakes.py`); `test/fake_lifecycle_node.py` is a node
that speaks the real `lifecycle_msgs` services and loses replies on request.

## Convergence

Per node, per tick (everything keyed on `get_state`; a `change_state` reply is advisory):

| Observed | The loop |
|---|---|
| on target | nothing; counters reset |
| `configuring`, `activating`, `deactivating`, `cleaningup`, `shuttingdown`, `errorprocessing` | in flight: sends nothing, waits; `STUCK` after `inflight_timeout` (still sends nothing) |
| no answer | never commands (nothing to compare); `MISSING` if never seen within `appear_timeout` |
| `finalized` | reported `FINALIZED`; the process has to be replaced |
| otherwise | one hop toward the target (`active`: configure, activate; `inactive`: configure or deactivate; `unconfigured`: deactivate, cleanup) |

Before sending, the state must have been **unchanged for `settle` seconds** and a **second
read right before the request** must still show the same state. After sending, the loop
waits for the reply or `reply_timeout`, then reads again regardless: a state that moved off
the starting state means the transition happened, whatever the reply said (a lost reply);
a state that did not, or a `success=false`, is one failed attempt. A failed attempt waits
the next `backoff` entry and sends again only if the node is still where it was.
`max_attempts` per from-state, then the node is `FAILED` with the reason, until
`CLEAR_FAILURE` or a new target. Defaults, in seconds: `poll_period` 0.5, `query_timeout`
2, `reply_timeout` 5, `inflight_timeout` 15, `appear_timeout` 30, `settle` 2, `backoff`
[0.5, 1, 2, 5, 5], `max_attempts` 5. Every request sent is logged with its attempt number.

### Why a request is never sent from a stale read, and why the manager is the only writer

`rclpy.lifecycle` nodes do not answer a transition that is invalid for their current state
with `success=false`. The exception escapes the service callback and the **process dies**
(`RCLError: Failed to trigger lifecycle state machine transition: Transition is not
registered`). Most of the demo's lifecycle nodes are Python (`joy_to_helm`, `mbes_sim`,
`platform_sender`), so two writers racing on one node kill it. Found live while building
this: a slow `launch_ros` autostart chain sent its unconditional `configure` after the loop
had already configured the node.

* In a group with a `lifecycle` section, **the `ChangeState` handler `launch_ros` registers
  per lifecycle node is not registered** inside the manager's `LaunchService`. The per-package
  launch files keep their `LifecycleNode(autostart=True)` chains and still emit their events;
  nothing acts on them. Run standalone with `ros2 launch` they behave exactly as before.
* The standalone guard (`converge`), which has to coexist with a launch's own chain,
  therefore waits for the state to be quiet (`--settle`, `--quiet-period`) and re-reads
  before every request. That narrows the race; it cannot close it.

## Configuration

One YAML file per manager. `${KEY}` is replaced from `--set KEY=VALUE` before validation;
an unknown placeholder is an error. Every problem in a file is reported at once.

```yaml
manager:
  name: demo_manager            # node name; topics are /<name>/status and /<name>/command
  default_profile: demo         # written once at start; nothing is persisted
  status_period: 1.0
  exit_when_all_stopped: true   # the process ends when every group is stopped
  converge: {settle: 1.0, ...}  # any of the knobs above
groups:
  boats:
    launch: {package: marine_simulation, file: demo_boats_launch.py}   # or {path: /abs/file}
    arguments: {boats: {type: string, default: ''}}   # declared, typed, defaults only
    requires: [other]           # must be READY before this group starts
    follows: [camp]             # stop this group when camp closes (see below)
    lifecycle: {match: '^/(a|b)/', expect: 18, target: active}   # or nodes: [/a, /b]
    ready: {nodes: [/x], timeout: 180}
    restart: on-failure         # or never
    description: one line for the status table
profiles:
  demo: [boats, camp, scorer]   # groups set RUNNING; every other group is STOPPED
```

A profile that names a group without the groups it `requires`, a dependency or `follows`
cycle, an unknown key, a bad regular expression, a declared argument whose default does not
match its type: all rejected at load. `launch` is a launch file of an installed package
(`<share>/launch/<file>`) or a path.

### Group states

`STOPPED`, `BLOCKED` (a required group is not READY; `blocked_by` names it), `STARTING`,
`READY` (a process is running, every expected lifecycle node is on target, the `ready.nodes`
are in the graph), `DEGRADED` (was READY; a node drifted or a required group left READY;
the detail says which), `FAILED` (sticky), `STOPPING`. `FAILED` names its cause: a lifecycle
node that ran out of attempts, a process that exited non-zero, a launch file that could not
be injected, or `not ready after N s` with what was missing. The manager logs it at ERROR
level with the node or process name, and `status` shows it. Dependents of a FAILED group
stay `BLOCKED` and point at it; groups that are already running are not torn down.

Process exits: a **respawning** process (`respawn=True`, which is how `helm_manager` is
launched) is not a failure; it comes back `unconfigured` and the loop repairs it. A clean
exit of one process among several is a note. A non-zero exit fails the group. When the last
process of a `restart: never` group exits cleanly (CAMP closed by its window), that is an
operator decision: the group's desired state becomes `STOPPED` and the groups that `follow`
it are stopped. The same rule makes a **run-once group** (a window placement, a setup step: `restart:
never`, nothing follows it): it ends `STOPPED` with detail `exited(0)`, no group is stopped, a
non-zero exit is a `FAILED` group that leaves the others running, and `command start <group>`
runs it again. The same exit under `restart: on-failure` is a failure, because automatic
restart is not implemented.

### What a helper sees when the boats go FAILED

`ros2 run launch_manager_proto launch_manager_proto status`:

```
manager demo_manager   profile demo   (profiles: boats, demo, headless)
  boats   FAILED   -> RUNNING   lifecycle node /clownfish/mbes_sim FAILED: configure failed 5 times: ...
   ! /clownfish/mbes_sim: inactive (FAILED) - configure failed 5 times: ...
  camp    BLOCKED  -> RUNNING   waiting for boats (FAILED)
```

CAMP does not start until the boats are READY, so a boat that cannot be brought up shows up
here, in the terminal's ERROR line (`group boats FAILED: ... /clownfish/mbes_sim ...`) and as
a CAMP that never opens, instead of as a boat that silently does not work. To retry:
`command clear-failure boats`, then `command start boats` (or close the manager and run it
again). After a `CLEAR_FAILURE` an all-stopped manager waits for the `START` instead of
exiting, even with `exit_when_all_stopped`; the wait ends with a `START`, `SET_PROFILE` or
`STOP`, or after five minutes. A `STOP` sent while a group's launch is still starting is held
for up to three seconds until its processes show up, so that nothing is left running.

## Trust

The configuration file is a code-execution boundary (a group runs any launch file, a
`launch: {path: ...}` any file on the host); `{package, file}` cannot leave the package's
launch directory. The command topic is unauthenticated: anything on the ROS domain can stop
and start the groups, as with the udp_bridge design this follows. Run the manager on a
private domain, or behind whatever restricts the domain, and edit the configuration only as
the user who runs it. A command that is not valid is answered `REJECTED` and never stops the
manager.

## Control surface (plain strings, versioned JSON)

`<name>/status` (`std_msgs/String`, a **full snapshot** every `status_period` and on every
change; never deltas):

```
{"schema": 1, "manager": "demo_manager", "profile_actual": "demo" | "custom",
 "profiles_available": [...], "acks": [{"request_id", "result", "detail"}, ... last 8],
 "groups": [{"name", "desired", "state", "detail", "state_since", "blocked_by": [...],
             "processes", "description",
             "lifecycle": {"target", "nodes": {"/n": {"state", "status", "attempts",
                                                       "last_result", "reason"}}}}]}
```

`<name>/command` (`std_msgs/String`, JSON): `{"request_id": "...", "type": "SET_PROFILE" |
"START" | "STOP" | "CLEAR_FAILURE", "profile": "...", "groups": [...]}`. A repeated
`request_id` is a no-op that returns the first answer; the result (`ACCEPTED` / `REJECTED`
and why) appears in `acks` of the next snapshots, and the CLI re-sends until it sees it.
`profile_actual` is derived: the profile whose group set equals what is RUNNING, else
`custom`. The field names mirror the design's `ManagerStatus` / `GroupStatus` / `Command`,
so turning this into real messages is mechanical.

## Stopping one group (the spike's result)

`LaunchService` allows one per process and `LaunchSession.from_service()` shuts the whole
shared service down when its `with` block exits, so each group's context is held open by a
thread until the manager exits. To stop **one** group: the group's description is wrapped in
a scoped `GroupAction` that sets `LAUNCH_MANAGER_GROUP=<name>`, so every `ProcessStarted` /
`ProcessExited` event carries the group in `event.env` (no guessing from pids or names); the
runner keeps the pids per group and emits one `ShutdownProcess(matches_pid(pid))` per pid,
once each, repeating on later ticks for processes that were still starting. `launch` then
runs its own SIGINT, SIGTERM, SIGKILL escalation. A group stopped this way restarts with
fresh processes. Two things had to be added for a restart to work: the group's recorded
event handlers are unregistered when it has stopped (otherwise the old `launch_ros` chains
answer the new processes), and `OnShutdown` handlers are exempt from that, because
`launch_ros` registers the handler that stops its adapter thread from whichever group needs
it first.

Groups are injected through a subclass of `LaunchSession` that leaves out the output and
process collectors `ros2launch_session` normally installs around every injection: they keep
every line of every process forever, which a test that lives minutes can afford and a manager
that lives days cannot. A group's holder thread ends when the group has stopped.

This belongs in `ros2launch_session` as a scoped-shutdown call (the design's option 2): the
attribution tag, the per-pid shutdown and the handler cleanup are launch mechanics, not
manager logic. It is not changed in this package's PR.

## Deviations from the design document

| Design | Here | Why |
|---|---|---|
| Own `ros2launch_manager_msgs` package | JSON in `std_msgs/String` | The sketch is unsettled on three points; real messages when the repository exists |
| One ack slot (open item) | The last 8 results in the snapshot | Costs nothing |
| `autostart` and the manager coexist | The manager is the only writer in a lifecycle group | rclpy kills a node on a second, invalid request (above) |
| `ready.lifecycle_active` | READY always includes lifecycle at target, plus `lifecycle.expect` | One rule instead of two |
| `lifecycle.nodes` only | `lifecycle.match` (regular expression over the graph) and `expect` | A boat's node list is not worth writing out |
| `requires` only | `follows`: stop this group when a followed group closes cleanly | Closing CAMP stops the demo |
| `launch: {package, file}` | also `{path}` | Tests and bench files |
| `CLEAR_FAILURE` leaves desired `RUNNING` (open item) | It sets desired `STOPPED`; `START` tries again | No immediate walk back into a crash loop |
| `START` on a group whose `requires` are not READY (open item) | `BLOCKED` until they are | |
| A clean exit while desired `RUNNING` (open item) | `restart: never`: closed, desired `STOPPED`; `on-failure`: `FAILED` | |
| Declared arguments arrive with a command | Declared with defaults only; commands carry none | Out of scope |

## Not implemented (deferred)

Output retention and an output channel; stale-command (reordering) defence and `force`;
sticky `FAILED` on link-carrying groups; `lifecycle: {delegate: ...}`; readiness predicates
other than node presence and lifecycle (`topics`, `tcp_port`, `output`); `exec:` groups;
per-group `environment` and `restart_defaults`; the respawn and group-restart budgets (a
group never restarts by itself; `start_attempts`, `retry_limit`, `retry_window`,
`respawn_max_retries`); `shutdown` timeouts (launch's per-process defaults apply);
`RESTART`, `SET_LIFECYCLE`, `RELOAD_CONFIG`; services; diagnostics; front ends; `log_dir`;
persistence; cross-host. The `autostart` versus non-`active` target conflict is documented
(the manager is the only writer, so it does not arise here), not detected.

## Tests

```bash
./simulation_ws/build.sh launch_manager_proto && ./simulation_ws/test.sh launch_manager_proto
```

All of them run on a private `ROS_DOMAIN_ID` they pick themselves (above 100). The fake
lifecycle nodes lose a configure reply, ignore a request, refuse a transition; the process
tests start the real manager with `launch_manager_proto/test/fixtures/` launch files and
check that it reaches READY, that closing the `closer` group stops the rest, that ctrl-c and
SIGTERM on the manager alone leave no process behind, and that one group stops and restarts.
The end-to-end check with the real boats is host-only:
`marine_simulation/test/test_demo_manager_live.py`.
