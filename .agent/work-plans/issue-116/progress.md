---
issue: 116
---

# Issue #116 — Demo at four boats: Fast DDS discovery server + nav2 composition

## Issue Review
**Status**: complete
**When**: 2026-10-21 09:42 -04:00
**By**: Claude Sonnet 5.5

**Issue**: #116
**Comment**: (not posted; the operator chose both changes himself)
**Scope verdict**: well-scoped, one PR, two independent switches

### Actions
- [ ] Finding: `ben_project11`'s composed branch (`navigation_launch.py` with `use_composition: True`) does not match its own non-composed branch: it composes an extra, unconfigured `bt_navigator` beside `bt_task_navigator` (the manager would see a stray lifecycle node), leaves out `manda_coverage` (the lifecycle manager waits for it forever), and gives `collision_monitor` an extra cmd_vel remap. Passing `use_composition: True` to it is therefore not enough; the plan adds a demo-owned composed bring-up in this repo (same node set and remaps as the non-composed branch, checked by a test) and leaves `ben_project11` untouched.
- [ ] Finding: `manda_coverage` registers no rclcpp component, so it stays its own process: each boat's 11 nav2 processes (ten servers and the lifecycle manager) become 2, the container and manda_coverage.
- [ ] Finding: the `DEMO_ZMQ_PORT_OFFSET` shim (`src/demo_zmq_ports.c`) is on the unmerged #112 Stage 2 branch, not on `jazzy`. The composed launch is included from the same `nav_actions` group, so the shim's environment will cover the container once #112 merges; a test pins that the composed include stays inside that group.
- [ ] Watch: ROS_DISCOVERY_SERVER with plain clients: `ros2 node list`, the manager's own graph and the self-test only see everything as a super client; the daemon must be restarted with the variables set. The manager node and the self-test get ROS_SUPER_CLIENT for their own participant only, never the children.
- [ ] Watch: a stale discovery server on the port would fail the group; the manager checks the port is free and refuses with the reason.
- [ ] Consequences: README (discovery server, super client, numbers), `.agents/README.md`, package.xml exec_depend, tests for the new launch arguments and group.

## Plan Authored
**Status**: complete
**When**: 2026-10-21 09:43 -04:00
**By**: Claude Sonnet 5.5

**Plan**: `.agent/work-plans/issue-116/plan.md` at `483792f`
**Branch**: feature/issue-116
**Phases**: single (review-plan skipped on the operator's call)

### Open questions
- [ ] Fix ben_project11's composed branch upstream instead of keeping a demo-owned copy?
- [ ] ZeroMQ shim is on the unmerged #112 branch, not jazzy; this branch does not depend on it

## Implementation
**Status**: complete (live proof of the discovery server FAILED; composition worked)
**When**: 2026-10-21 10:49 -04:00
**By**: Claude Sonnet 5.5

### Done
- Composition: `demo_nav2_composed_launch.py` (one `nav2_container` per boat, same nodes/params/remaps as the non-composed stack, manda_coverage stays a process); `nav_composition` launch argument, default true; test compares the node table with ben_project11's launch file. ben's own composed branch is NOT usable (extra bt_navigator, no manda_coverage, other collision_monitor remap).
- Discovery server: `demo_discovery_server_launch.py`, `discovery` manager group, `--discovery-server` (opt in), port 11811 + domain, port-free preflight, super client for manager node (`run_manager(node_environment=)`), self-test and graph check. run_demo.sh: opt in (`--discovery-server` / DEMO_DISCOVERY_SERVER=1).
- Merged origin/jazzy (PR #117) and resolved conflicts; Stage 3 handoff paragraph added to the #112 plan.
- Tests: 1183 run in marine_simulation + launch_manager_proto, only the 8 baseline lint failures in untouched launch files.

### Live runs (one run each on the dev laptop, NOT benchmarks; pickerel is the real measurement)
- composition off, no server: all 40 nav2 nodes active 113 s, 101 processes, 4.9 cores, 12.0 GB, late joiner got latched survey area after 37 s.
- composition on, no server: 28 s, 65 processes, 3.4 cores, 8.3 GB, survey area after 2.6 s.
- server on (composition on and off; server on 127.0.0.1 or all interfaces; all processes super client): nav2 never came up (costmap lacks base_link to map_tide transform; lifecycle replies lost; platform_send died). Four boats without nav and two boats through the server were fine. Cause not found.
- Not observed live: the ZeroMQ shim inside a container; controller rate. Nothing left running (pgrep clean).

### Open questions
- [ ] Why nav2 loses its transforms through the discovery server (plain clients vs the server; may be a jazzy Fast DDS issue)? Server stays opt-in.
- [ ] Fix ben_project11's composed branch upstream?

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-21 10:58 -04:00
**By**: Claude Sonnet 5.5
**Verdict**: approved (must-fixes fixed in the follow-up commit)

**Branch**: feature/issue-116 at `09eb581` (fixes after)
**Mode**: pre-push
**Depth**: Standard (reason: new launch/manager behaviour, 1254 added lines); static analysis via the ament lint run, two Claude passes (Lens A, B), cross-model gemini + codex
**Must-fix**: 6 found, 6 fixed | **Suggestions**: 5 fixed, rest declined
**Round**: 1 | **Ship**: recommended — all must-fixes fixed and tests green (1185 run, only the 8 baseline lint failures of untouched launch files)

### Findings
- [x] (must-fix) discovery group claimed a restart the manager does not implement; now restart: never and the comment says a dead server fails the group — `config/demo_manager.yaml`
- [x] (must-fix) test asserted the default value of restart — `test/test_demo_manager.py`
- [x] (must-fix) a ROS_SUPER_CLIENT exported in the caller's shell reached every group; now scrubbed — `scripts/demo_manager.py`
- [x] (must-fix) graph checker kept a conflicting ROS_SUPER_CLIENT; now set unconditionally — `scripts/check_multi_boat_graph.py`
- [x] (must-fix) target_area and rqt now require discovery — `config/demo_manager.yaml`
- [x] (must-fix/suggestion, 3 reviewers) preflight for a missing fastdds tool — `demo_support.py`
- [x] (suggestion) unused log_level parameter removed, COMPOSED block moved below NAV2_COSTMAPS, README crash note, test asserts a match for ben's lifecycle_nodes
- [ ] (declined) composition on by default: the operator chose it for the demo; README notes the failure mode and the way back
- [ ] (declined) scrub an operator-exported ROS_DISCOVERY_SERVER when --discovery-server is absent: kept as a deliberate way to use an external server
- [ ] (declined) unscoped SetParameter use_sim_time in the composed launch mirrors ben's navigation_launch; behaviour seen live
- [ ] (declined) orphan server risk: no server survived any manager stop in the live runs (pgrep clean); only my own harness' terminate left one
