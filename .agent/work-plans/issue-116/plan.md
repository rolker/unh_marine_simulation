# Plan: Demo at four boats: Fast DDS discovery server + nav2 composition to cut DDS discovery cost

## Issue

https://github.com/rolker/unh_marine_simulation/issues/116

## Context

Four boats with nav is about 100 processes on one computer, each a Fast DDS participant with peer-to-peer discovery. The issue measured 40 to 60 s late-joiner discovery and 2 of 4 nav2 bring-up failures. Two switches are to be tried and measured: a Fast DDS discovery server, and nav2 composition per boat. Issue review findings that shape the plan: `ben_project11`'s composed branch is out of step with its own non-composed branch (stray `bt_navigator`, no `manda_coverage`, different collision_monitor remap), so the composed bring-up is demo-owned; `manda_coverage` is not a component; the ZeroMQ shim is on the unmerged #112 branch, not on `jazzy`.

## Approach

1. **Discovery server group** — `launch/demo_discovery_server_launch.py` runs `fastdds discovery -i 0 -l 127.0.0.1 -p <port>`; `demo_manager.yaml` gets a `discovery` group (restart on-failure) that `boats` requires and every profile lists. Port = 11811 + ROS_DOMAIN_ID (`demo_support.discovery_server_port`), so two demos on one host do not collide.
2. **Switch** — `demo_manager.py --discovery-server/--no-discovery-server` (default off: plain peer-to-peer, boat-side launches unaffected). On, the manager exports `ROS_DISCOVERY_SERVER=127.0.0.1:<port>` for itself and every group, refuses a taken port, and gives only its own rclpy node `ROS_SUPER_CLIENT=TRUE` (`run_manager(node_environment=...)`, restored before any group starts). Off, `discovery` is removed from the profiles and from `boats.requires`. `run_demo.sh` passes `--discovery-server` by default, `--no-discovery-server` or `DEMO_DISCOVERY_SERVER=0` turns it off, and it prints the CLI recipe.
3. **Graph readers** — `demo_boats_selftest.py` (`--discovery-server`, or `ROS_DISCOVERY_SERVER` already set) and `check_multi_boat_graph.py` set `ROS_SUPER_CLIENT=TRUE` for their own participant (`demo_support.enable_super_client`); the self-test keeps it out of the launch it starts.
4. **Composed nav2** — `launch/demo_nav2_composed_launch.py`: `component_container_isolated` named `nav2_container` in the boat's namespace, the ten nav2 components loaded with the same parameters and remaps as ben's non-composed branch, `manda_coverage` as its own lifecycle node, the lifecycle manager as a component. The node table lives in `demo_nav.py` and a test checks it against `NAV2_SERVERS` and, when installed, against ben's `navigation_launch.py`. `demo_boats_launch.py` gets `nav_composition` (default true: the demo only); `nav_actions` includes the composed launch inside the same group, so the namespace push, `bond_timeout` and (after #112) the ZeroMQ shim environment still apply. `nav_composition:=false` is the "before" measurement.
5. **Tests, README, `.agents/README.md`, package.xml** — launch-argument tests for both switches, config tests for the group and the profile rewrite, port and super-client helpers, README sections with the measured numbers once the live runs are done.

## Files to Change

| File | Change |
|------|--------|
| `marine_simulation/launch/demo_discovery_server_launch.py` | new: the server process |
| `marine_simulation/launch/demo_nav2_composed_launch.py` | new: composed nav2 bring-up |
| `marine_simulation/launch/demo_boats_launch.py` | `nav_composition` argument, `nav_actions` switch |
| `marine_simulation/config/demo_manager.yaml` | `discovery` group, requires, profiles |
| `marine_simulation/scripts/demo_manager.py` | switch, env, port check, profile rewrite |
| `launch_manager_proto/launch_manager_proto/manager.py` | `run_manager(node_environment=)` |
| `marine_simulation/marine_simulation/demo_support.py`, `demo_nav.py` | port, super client, component table |
| `marine_simulation/scripts/run_demo.sh`, `demo_boats_selftest.py`, `check_multi_boat_graph.py` | switch and super client |
| `marine_simulation/test/*`, `README.md`, `.agents/README.md`, `package.xml`, `CMakeLists.txt` | tests, docs, exec_depend, install |

## Principles Self-Check

| Principle | Consideration |
|---|---|
| Real-boat launches unchanged | `ben_project11` is not touched; composition and the server are demo-only and off by default outside `run_demo.sh` |
| Fail loud | a taken port, a missing `fastdds` or a composed node table that drifts from ben's list is an error or a failing test |
| Measure, do not assume | numbers before (both switches off) and after, four-boat nav, written into the README |

## ADR Compliance

| ADR | Triggered | How addressed |
|---|---|---|
| none in this repo covers launch switches | No | n/a |

## Consequences

| If we change... | Also update... | Included in plan? |
|---|---|---|
| demo launch arguments | README, `.agents/README.md` parameter notes | Yes |
| manager configuration | config tests, launch_manager_proto test of `run_manager` | Yes |
| nav2 node set | `demo_nav.NAV2_SERVERS`, lifecycle expectations | Yes (unchanged names) |

## Documentation & Instruction Impact

- **Stale docs** (must land in this PR): README run section, nav section ("Composition is off"), `.agents/README.md`; `demo_nav_actions` docstring.
- **Agent-instruction candidates** (proposals only): ben_project11's composed branch is out of step with its non-composed one (propose an issue there).

## Open Questions

- Should ben_project11's composed branch be fixed upstream instead of keeping a demo copy (would also serve the real boat)?
- The ZeroMQ shim is on the #112 branch; this branch does not depend on it.

## Estimated Scope

Single PR.
