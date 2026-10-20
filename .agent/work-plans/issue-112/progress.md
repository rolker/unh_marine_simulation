---
issue: 112
---

# Issue #112 — Demo boats: nav stack per boat, and a joystick watchdog that switches an idle or pad-less boat to an autonomous survey of its section

## Issue Review
**Status**: complete
**When**: 2026-10-20 11:37 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Issue**: #112
**Comment**: (best-effort post follows this entry; not recorded inline)
**Scope verdict**: needs-splitting

### Actions
- [ ] Split delivery into three stages, each its own PR under #112 (nav stack + self-test; watchdog + section mission; attract mode + polish). The issue's "Done when" list spans all three and the event (Ocean Discovery Day) is close.
- [ ] Correct four premises in the issue text before planning on them (all verified against source): (1) the demo does NOT set a shared map origin (no `map_origin_latitude/longitude` anywhere in this repo; mru_transform#49 added the capability only, each boat's `<boat>/map` is anchored at its own first fix); (2) `mission_manager/track_patterns.py` has only an expanding-box and a racetrack pattern, and `multibeam_coverage_adapter.py` only computes a coverage path and never drives, so neither is a ready-made "survey of a section"; (3) pad idleness cannot be read from Joy timestamps because the demo runs `joy_linux` with `autorepeat_rate: 10` (a Joy message every 100 ms with no input), so idleness is a property of the message content; (4) `joy_to_helm` sends its mode buttons to `marine/send_command`, which nothing receives in the demo (no command_bridge), so the pad cannot change the mode today and the watchdog is the only mode writer.
- [ ] Decide where the watchdog lives with the shared-interface consequence written down (new node in this repo recommended; a `joy_to_helm`/`helm_manager` feature would put idle-to-autonomous on real boats).
- [ ] The launch manager's `boats` lifecycle group matches `^/(boat)/` and would also drive nav2's self-managed lifecycle nodes (second writer); the plan has to exclude them.
- [ ] Name the schedule risk: the event is 2026-10-23/24; `enable_nav` must stay off by default until a rehearsal passes.

## Plan Authored
**Status**: complete
**When**: 2026-10-20 11:40 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Plan**: `.agent/work-plans/issue-112/plan.md` at `127f042`
**Branch**: feature/issue-112 at `127f042`
**Phases**: 3 (nav stack per boat; watchdog and section mission; attract mode and polish)

### Open questions
- [ ] Staging: three PRs, nav default off until rehearsed, or stages 1+2 combined for the event?
- [ ] Watchdog home: new node in this repo (recommended) or a joy_to_helm/helm_manager feature?
- [ ] Mission kind: pre-planned lines (recommended) or SurveyArea through manda_coverage?
- [ ] Pad buttons: keep inert (no command_bridge) or add command_bridge_receiver per boat?
- [ ] Hand-back: pause with override hover and resume (recommended) or restart the section?
- [ ] Chart layer: drop it (recommended) or run s57_grids per boat?
- [ ] Shared map origin: leave per-boat (recommended) or set one?
- [ ] On completion of a section: repeat (recommended) or hold?

## Plan Review
**Status**: complete
**When**: 2026-10-20 11:50 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Plan**: `.agent/work-plans/issue-112/plan.md` at `127f042`
**PR**: PR-less
**Verdict**: changes-requested

Checked against source: ben_project11 `nav2_bringup_launch.py`, `navigation_launch.py`, `nav2_params.yaml`, `ben_core_launch.py`; mission_manager `camp_interface.py`, `mission_manager.py`, `mission_manager_launch.py`; `marine_autonomy/nav.py`; helm_manager `helm_manager.cpp`; joy_to_helm `joy_to_helm.py`; asv_helm / asv_sim `platform.py`; `run_tasks.xml`; launch_manager_proto `config.py`, `lifecycle_rclpy.py`; the demo launch, params, manager yaml, selftest and graph check. Most of the plan's factual claims hold (nav2 namespace push, lifecycle list, parseMission shape, replace_task/override/cancel_override, piloting_mode topic and heartbeat key, send_command, BT dispatch and failed-line handling, no existing exclude option, autorepeat).

### Findings
- [ ] (must-fix) mission_manager is launched outside any namespace push: `mission_manager_launch.py` declares its `LifecycleNode` with `namespace=''` and does not push one, so step 1's "second GroupAction outside the boat's PushROSNamespace" puts it at `/mission_manager`, one node for all boats. Only `nav2_bringup_launch.py` pushes its own namespace. The group needs `PushROSNamespace(<boat>)` for mission_manager and none for nav2 — `plan.md:32`
- [ ] (must-fix) mission_manager dies on a mission sent before TF `earth -> <boat>/map` exists: `EarthTransforms.geoToPose` returns `None` on a failed lookup (`marine_autonomy/nav.py:186-194`) and `parseMission` appends it to `poses` (`camp_interface.py`, Waypoint branch); the exception leaves `executor.spin()` (`mission_manager.py` main catches only KeyboardInterrupt/ExternalShutdown), the process exits and respawns unconfigured (5 s). The "resend every 5 s" LOADING loop would repeat that. Gate the first send on the boat's TF/first fix (e.g. a fix on `sensors/nav/position` plus a delay, or lookup via the watchdog's own tf buffer) and back off — `plan.md:45`
- [ ] (must-fix) The existing self-test scenarios and the watchdog conflict: `demo_boats_selftest.py` drives one boat with fake Joy and expects the others to stay still (`check_solo`), but boats that receive no Joy are `pad_missing` and go autonomous after 10 s when nav+watchdog are on. State that the old scenarios run with `enable_watchdog:=false` (or nav off) and only the new scenarios enable it; also `test_demo_boats_selftest.py:142` (`overridden_launch_args([... 'enable_nav:=true'])`) and `README.md:495,757` must change, not only `test_demo_boats_launch.py:343-355` — `plan.md:36,96`
- [ ] (must-fix) `mission_tasks` is not a stable "mission state" feed: it is published only from navigator feedback/done (`camp_interface.py` navigatorFeedback/navigatorDone). Every `replace_task` (clearTasks then add = two goals), `override`, `cancel_override` sends a new goal without cancelling the old one (`mission_manager.py` updateNavigator, cancel code commented out), and the old goal's done callback publishes `navigatorDone` with `current_navigation_task=''` and the preempted result's task list, which can be empty or stale, and clears `self.goal_handle`. The watchdog's `lines done/failed` and COMPLETE detection must tolerate empty/transient lists and count a line done only once a `done` flag was seen (monotone latch), or `lines_done not decreasing` in the live test fails spuriously and a transient empty list could read as COMPLETE/repeat — `plan.md:45,49`
- [ ] (suggestion) `exclude` may not be needed: `launch_manager_proto` matches with `re.search` (`lifecycle_rclpy.py:70-84`) and `converge --match` takes the same regex, so a negative lookahead (`^/(boats)/(?!controller_server|smoother_server|planner_server|behavior_server|manda_coverage|velocity_smoother|collision_monitor|bt_task_navigator|waypoint_follower|docking_server|local_costmap|global_costmap)`) already excludes nav2 with no schema/CLI/README change in `launch_manager_proto`. `exclude` is cleaner and readable; decide deliberately, noting it widens the generic package for one demo need. Either way the exclusion list has to include the costmap lifecycle nodes `<boat>/local_costmap/local_costmap` and `<boat>/global_costmap/global_costmap` (the plan says "costmap nodes"; make it exact and pin it) — `plan.md:34`
- [ ] (suggestion) Halving the global costmap resolution (1.0 -> 2.0 m) changes SmacHybrid's discretisation: `minimum_turning_radius: 5.0` becomes 2.5 cells, `analytic_expansion_max_length`/`lookup_table_size` stay in metres (`nav2_params.yaml:156-178`). Shrinking only the size (e.g. 2400 x 2400 at 1.0 m, 5.8 M cells instead of 25 M) keeps the planner behaviour Ben is tuned for; if resolution does change, make it a measured decision in Stage 1 (the lead-in transit uses this planner, `run_tasks.xml` TransitAndSurveyLine) — `plan.md:33`
- [ ] (suggestion) nav2 failure is silent under the plan: `use_respawn: False` and nav2's `lifecycle_manager_navigation` tears the whole stack down on a bond break or one node failing to activate (all ten, including manda_coverage and docking_server, must come up), while the manager does not own those nodes. The watchdog then sits `AUTONOMOUS` with the mission never acknowledged. Define a watchdog state for "navigator unavailable" (capped resend, visible in `demo_watchdog/state`, no endless loop), and have the Stage 1 self-test assert the lifecycle_manager's nodes are active at the end, not only at the start — `plan.md:37,45,106`
- [ ] (suggestion) `/survey_area` is published only by the manager's `target_area` group, which the `boats` profile (selftest) and a boats-only launch do not run. The watchdog needs a defined fallback (a `target_area_file` parameter or the shipped polygon path) and a defined behaviour when no area ever arrives (stay manual/hover, state `NO_AREA`), and the self-test scenario must start its own publisher or pass the file — `plan.md:41,49`
- [ ] (suggestion) mission_manager's command subscription is `depth 1` (`camp_interface.py` on_configure) and its callbacks block up to 2 s in `wait_for_server` (`mission_manager.py` updateNavigator). Two commands in quick succession (`override hover` then `cancel_override` on a tap-and-release, or `replace_task` right after another) can drop the first. Rate-limit command sends to the same boat (the plan only rate-limits mode re-publishes) and treat a lost command as "verify by mission_tasks, resend" — `plan.md:47`
- [ ] (suggestion) mission_manager can respawn (`mission_manager_launch.py` `respawn=True`, 5 s) with an empty task list while the watchdog believes `RUNNING`; add a "mission_tasks silent for N s -> LOADING" rule. Likewise helm_manager's mode: reconcile is planned, good — `plan.md:45-46`
- [ ] (suggestion) Pin in the live check that a nav-driven boat actually moves at the commanded speed: with `output_type: helm` the autonomous Twist becomes throttle = v / `max_speed` (2.75) and rudder = -wz / `max_yaw_speed` (0.5) (`helm_manager.cpp` update(TwistStamped); `demo_params.yaml`), open loop; nav2's `max_velocity [2.75 .. 0.45]` then gives rudder up to 0.9. The 4-knot demo speed (2.06 m/s) is throttle 0.75 whatever speed asv_sim gives; the CrabbingPathFollower's PID and the 0.5 m / 10 s progress checker (`nav2_params.yaml:40-45`) are tuned for the real boat, so a slow sim boat could be marked failed per line — `plan.md:24,106`
- [ ] (suggestion) The graph check only inspects publishers outside boat namespaces; nav2's bond topic is the likeliest unprefixed publisher (nav2 and mission_manager message topics were not enumerated). Run `check_multi_boat_graph.py` with nav on in Stage 1 and add to `SHARED_TOPICS` only on purpose; also add the nav node set (`BOAT_NODES`, `demo_boats_selftest.py:90`) per `--nav` and `MIN_LIFECYCLE_NODES_PER_BOAT` vs `LIFECYCLE_NODES_PER_BOAT` (`demo_manager.py:71`, `demo_boats_launch.py:99`, `test_demo_manager.py:193`) — the plan covers the counts but not these two constants being kept equal when nav adds mission_manager — `plan.md:34,64`
- [ ] (suggestion) The demo's own comments must change with the new writer: `demo_params.yaml` ("Nothing else can change the mode") and `README.md:757`; the pad's button 0/1/2 presses make `joy_to_helm` set its own local state and publish to the unconnected `marine/send_command` (`joy_to_helm.py` joystickCallback), harmless but a button is also "activity" in the watchdog rule, which is the intended hand-back — mention it in the README helper card — `plan.md:102`
- [ ] (suggestion) Unverified here (no source for the binary driver): that `joy_linux` stops publishing when the pad disconnects and keeps autorepeating a neutral state otherwise. The plan relies on both (`pad_lost_timeout`, "autorepeat copies are never activity"); put one bench check with a real pad (unplug/replug, stick held) in the Stage 2 rehearsal list — `plan.md:21,43-44`
- [ ] (suggestion) Items checked and found correct, no change needed: nav2 `use_composition` default is `True` in `nav2_bringup_launch.py` and the plan's `False` is right; helm_manager heartbeat is driven by `marine/status/helm`, which asv_sim's 20 Hz `have_commands` feeds through asv_helm (`platform.py` update, `asv_helm_node.cpp`), so the heartbeat and the hand-back reach joy_to_helm within about 50 ms; collision_monitor sits unused in the chain (velocity_smoother remaps its output straight to `piloting_mode/autonomous/cmd_vel`, `navigation_launch.py`), so its unprefixed `base_footprint` and missing `scan` source do not stop the boat; `ben_project11` is already an exec_depend. Not run: nothing was launched.
