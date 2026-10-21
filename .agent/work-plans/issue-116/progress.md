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
