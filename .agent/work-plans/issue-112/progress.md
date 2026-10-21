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

## Plan Revised
**Status**: complete
**When**: 2026-10-20 11:47 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

Folded the four must-fix findings of the plan review (mission_manager namespace, TF gate before the first mission send, selftest and watchdog conflict, unstable mission_tasks feed) and the other findings (exclude vs lookahead, costmap resolution kept, NAVIGATOR_UNAVAILABLE and NO_AREA states, send rate limit, doc and test line references) into plan.md.

## Plan Revised
**Status**: complete
**When**: 2026-10-20 12:00 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

Roland's decisions folded into plan.md. Deliberate simplification (decision 5): hand-back is **restart the section, not pause/resume**. The `override hover` / `cancel_override` mechanics and the remaining-lines bookkeeping are dropped; a hand-over to autonomy clears and sends the whole section from the first line, and a takeover sends manual then `clear_tasks`. Stages 1 and 2 go now, nav stays off by default until rehearsed; no collision avoidance (issue 111 covers contact).

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-20 13:20 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)
**Verdict**: approved

**Branch**: feature/issue-112 at `6040844`
**Mode**: pre-push
**Depth**: Standard (reason: launch files and the lifecycle manager, about 700 lines of code and tests)
**Must-fix**: 2 (both fixed) | **Suggestions**: 9 (8 fixed, 1 documented)
**Round**: 2 | **Ship**: recommended — round 1 found two must-fix items in the self-test, both fixed with a unit test and the live self-test rerun; the second round was reduced to the fix commits

### Findings
- [x] (must-fix) A survey line the navigator recorded failed (`SetTaskFailed` also marks it done) could pass the mission check; now `line_reached` rejects a failed status and needs the end of the line — `marine_simulation/scripts/demo_boats_selftest.py` (codex, confirmed by the live four-boat failure where the line was marked done after 18 m)
- [x] (must-fix) Returning to manual and clearing the mission ran only on normal completion; now in a `finally` — `demo_boats_selftest.py` check_nav_mission (codex)
- [x] (suggestion) mission command repeated every 15 s clears and re-sends the tasks; now every 60 s — `demo_boats_selftest.py` (Lens A)
- [x] (suggestion) `autonomous` published once; now with each command — `demo_boats_selftest.py` (Lens A)
- [x] (suggestion) check timeouts not honoured when nav2 is down — `demo_boats_selftest.py` (Lens A)
- [x] (suggestion) default startup timeout too short with `--nav`; now 240 s — `demo_boats_selftest.py` (Lens A)
- [x] (suggestion) `converge` did not validate its regular expressions — `launch_manager_proto/cli.py` (Lens A)
- [x] (suggestion) params file written before checks that can refuse the start — `demo_boats_launch.py` (Lens A)
- [x] (suggestion) `write_params` trusted any file under the hashed name and could leave a temporary — `demo_nav.py` (Lens B)
- [x] (suggestion) README: manager READY does not cover nav2; the standalone guard does not cover a respawned mission_manager — `marine_simulation/README.md` (Lens B; documented, not changed)
- [ ] (suggestion) keep the standalone guard alive for the nav case or add a read-only nav2 state check to READY — `demo_boats_launch.py` (Lens B; left open: the manager path is the demo's, Stage 2's watchdog will see an unavailable navigator)

Specialists: static analysis (pre-commit flake8 on every commit, passed), governance (ADR-0008 headers present, ADR-0009 no new dependency, ADR-0013 entries, consequences: README, .agents/README.md, plan, tests done), plan drift (resolution/size delta, SurveyPattern self-test and the `check_multi_boat_graph.py` no-change are recorded in the plan), two Claude adversarial passes (Lens A, Lens B), cross-model (codex ran; gemini failed: headless tool denial, exit 1).

## Implementation
**Status**: complete
**When**: 2026-10-20 13:25 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Branch**: feature/issue-112 at `bb1847d`
**Stage**: 1 of 3 (nav stack per boat; Stage 2 watchdog and section missions, Stage 3 attract mode and polish follow)

### Evidence
- Suite (marine_simulation and launch_manager_proto): 918 tests, 8 failures, the same 8 lint failures in untouched launch files as the baseline (882 tests, 8 failures before the work).
- Self-test `--nav` through the launch (2 boats) 17 of 17; through the launch manager `--demo --nav` (2 boats) 19 of 19 on the final code; four boats through the manager 23 of 23 (before the last self-test fixes, which only touch the self-test); no nav, four boats 16 of 16.
- Per-boat nav2 lifecycle nodes pinned from the headless run: controller_server, smoother_server, planner_server, behavior_server, manda_coverage, velocity_smoother, collision_monitor, bt_task_navigator, waypoint_follower, docking_server, local_costmap/local_costmap, global_costmap/global_costmap (24 for two boats, 48 for four, all active before and after the mission); `lifecycle_manager_navigation` is a plain node; the manager owns ten lifecycle nodes per boat (nine and `mission_manager`).
- Load, 16 core dev computer: 2 boats 26 processes 2.1 GB (no nav) vs 50 processes 4.4 GB (nav); 4 boats 50 processes 4.5 GB vs about 100 processes 11 GB, saturating the 16 cores for about 100 s while starting. At nav2's defaults one of four boats' bring-up aborted on its 4 s bond timeout and a planner missed the 10 s acknowledge timeout on the 5.8 M-cell global costmap; `bond_timeout` 30 s and a 2 m, 2400 m global costmap fixed both (`ros2 param get` showed 30.0 on the lifecycle manager).
- Not verified: the event computer's load; the Stage 2 watchdog (not built); nav2 behaviour at the first mission line after a very loaded start beyond the above.

## Implementation
**Status**: in-progress
**When**: 2026-10-20 14:58 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Branch**: feature/issue-112 at `319afb6`
**Stage**: 2 of 3 — checkpoint 2026-10-20 15:00 (no PR yet)

### Done
- survey_sections.py (equal-area bands, boustrophedon lines, CAMP SurveyPattern), watchdog_core.py (state machine, fake-Joy tests), scripts/demo_watchdog.py, launch arguments and demo values, selftests `--watchdog pad` and `--watchdog attract`, README and .agents/README.md, plan notes; jazzy (collision, PR 114) merged in.
- Suite (marine_simulation, launch_manager_proto): 1035 tests, the same 8 lint failures in untouched launch files (cpplint and uncrustify pass on the new C file; cppcheck skipped, not installed).
- Live (headless, through the manager, collision on): `--watchdog pad` 21 of 21 (2 boats); `--watchdog attract` 17 of 17 (2 boats) and 23 of 23 (4 boats, about 105 processes, 12 GB, 6 cores settled, 15 cores for the first two minutes).
- Review round 1 ran (static, Claude Lens A and Lens B, codex; gemini failed on headless tool denial). NOT yet addressed.

### Not done (exact next step: fix the must-fix items, add a test each, rerun the two selftests, reduced second round, then open the PR)
- must-fix (watchdog_core.py): (1) an area that is set but cannot be split makes the core retry every 100 ms tick (delete the NO_AREA to NOT_LOADED lines in `_autonomous_tick`; test must count calls); (2) takeover skips clear_tasks when the state is NOT_LOADED while mission_manager still holds a plan (on_area, repeat, resends, tf_settle, command_gap): track a may-be-loaded flag set in `_send`; (3) self-test pad scenario: the pad goes silent after the single active message for longer than pad_lost_timeout (3 s), so the final check can pass on reason pad_missing; keep publishing the rest pad and assert reason idle; (4) codex: standby latch is cleared when entering autonomy (a standby helm is overridden by the idle timeout), and README claims otherwise; (5) codex: a button held when the pad appears becomes its baseline (buttons should count independent of the learned baseline); (6) codex: with no area the core still announces autonomous (plan says stay manual until an area exists).
- suggestions: resume the rest-pad publishing; keep the first baseline across a short Joy gap; log when navigator_unavailable flips; all-lines-failed section should back off, not repeat every 10 s; compare SurveyArea stamps; cap steps and lines in survey_sections; guard the C shim offset overflow; own_tasks prefix match (ben_s1 vs ben_s10); rename Section.heading (it is the maths angle); --watchdog needs --demo (refuse early); a --watchdog/--no-watchdog option on demo_manager.py.
- Collision: nothing special was added; the documented behaviour (nav2's progress checker aborts a held boat's line after about a minute and the navigator goes to the next line) is from the mechanism and the Stage 1 logs, NOT observed live with a boat held by a charted object.

### Live-run facts
- Only one boat per computer could ever run a navigator goal: marine_nav_bt_task_navigator opens a BT::Groot2Publisher with fixed ZeroMQ ports (1667 and 1668) on every goal, and the second boat's goal failed with "Address already in use". src/demo_zmq_ports.c is an LD_PRELOAD shim that moves each boat's nav2 ZeroMQ binds by ten ports per boat (DEMO_ZMQ_PORT_OFFSET); an upstream parameter for the port would retire it (proposed issue for unh_marine_navigation, not filed).
- Smac hybrid could not plan the 700 m transit to a section's first line over the empty costmap; the demo uses NavFn on a 3200 m, 2 m global costmap.
- A 14 minute four-boat attract run through the manager was inconclusive: it started with FastDDS shared-memory port errors while review jobs ran, one boat's state topic never appeared and another stayed LOADING (nav not acknowledging); not diagnosed. The short four-boat runs passed.

## Implementation
**Status**: complete
**When**: 2026-10-21 09:50 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Branch**: feature/issue-112 (Stage 2 of 3; no PR yet, nothing pushed)
**Stage**: 2 of 3 finished: the six must-fix findings of review round 1, the long-run diagnosis, and the cheap suggestions. Stage 3 (attract polish, rehearsal) is a later PR.

### Must-fix findings (each has a unit test that failed before the fix)
1. Area set but unsplittable retried every 100 ms tick: the NO_AREA to NOT_LOADED lines are gone, the state waits for `on_area`; `test_an_area_that_cannot_be_split_is_asked_once_not_every_tick` counts the mission calls (1, was ~100).
2. Takeover skipped `clear_tasks` in NOT_LOADED while mission_manager still held a plan: `_may_be_loaded` is set in `_send`, cleared by the clear; `test_takeover_clears_a_plan_mission_manager_may_still_hold`.
3. Self-test pad scenario: the pad went silent after its one active message for longer than `pad_lost_timeout`, so the last check could pass on `pad_missing`. `touch_pad()` keeps the rest pad publishing and the last check asserts reason `idle`; `test_touching_the_pad_leaves_it_sending_at_rest`.
4. Standby latch was cleared on entering autonomy. Decision: the code follows the plan ("a heartbeat of standby is respected, the watchdog stays out until the next activity") and the README (which already said so); a standby helm is now never overridden by idle or pad-lost, nothing is announced or sent while it holds; `test_a_standby_helm_is_not_overridden_by_the_idle_timeout`.
5. A button held when the pad appears became its baseline: any pressed button (or a button change) is activity whatever the learned baseline, including in the message that shows the pad; `test_a_button_held_as_the_pad_appears_takes_the_boat` (3 buttons), `test_a_button_held_on_a_pad_that_was_already_there_stays_activity`.
6. With no area the core announced autonomous. Decision: the plan says "keeps the boat manual", the README said "hovers"; the code and README now follow the plan: `desired_mode()` is `manual` in NO_AREA and `autonomous` is announced when an area arrives; `test_no_area_is_a_state_and_the_boat_stays_manual_until_there_is_one`.

### Long-run failure (the 14 minute run that ended NO_AREA, one state topic missing, one boat LOADING)
The logs of that run are gone; reproduced twice at four boats through the manager (headless, `--no-joysticks`, private domains 147 and 161, nothing else running) and read against the code. The cause is load, not the watchdog logic:
- NO_AREA and the missing state topic are discovery latency. About 100 processes of four boats on one computer make DDS discovery slow: a late joiner needed 40 to 60 s to see the other participants (a monitor started after the boats had no state topics for 40 s and no area for 60 s). The area is a latched sample that arrives only when the publisher is discovered, so each watchdog sat in NO_AREA (`area=False`) for 30 to 70 s after it started, while another process had already received the area; under yesterday's concurrent review jobs and FastDDS shared-memory errors that wait is plausibly far longer. The code paths read clean: transient-local depth 100 on both sides matches, the `target_area` group publishes once at start and keeps its node, the watchdog compared no stamps (now it does).
- The LOADING boat is a nav2 bring-up failure under that load, seen on bluefin (first in the roster) in 2 of 4 four-boat runs today: once nav2's lifecycle manager aborted ("planner_server/get_state service client: async_send_request failed", after "failed to send response to .../get_state (timeout)" warnings), once its manager sat forever in "Configuring collision_monitor" (a lost service reply). The boat's nav2 stays inactive, the watchdog resends every 15 s (generation 30+) and, after 120 s, the state says `navigator_unavailable`, which is the intended signal. The other two four-boat runs had all 48 nav2 nodes active (23 of 23).
- Fixes: the node logs "no target area after 30 s" and subscribes to `/survey_area` again every 30 s while there is none (in the final long run three boats got their area 2 to 17 s after that); the state carries `has_area`; stamps are compared (`AreaBook`, tested), and `test_demo_watchdog.py` runs the node in process. Also found live and fixed: a section repeated after a long survey was flagged `navigator_unavailable` at once (the wait was counted from the first send ever); `test_a_repeat_long_after_the_first_send_is_not_flagged_as_an_unavailable_navigator`.
- Evidence of the final-code 9 minute four-boat attract run (domain 161): t=40 s three watchdogs AUTONOMOUS/pad_missing, mission NO_AREA, has_area false (the fourth had no state topic yet); t=80 s all four has_area true (the monitor's own latched subscription had the area at t=40 s); t=120 s all LOADING generation 3 (nav2 still coming up); t=160 s all RUNNING generation 4; t=320 s bluefin lines 3/6 (all failed), t=360 s bluefin COMPLETE 6/6 with 6 failed; t=480 to 560 s bluefin generation 5 (repeat), 5 of 6 failed; the other three still RUNNING at 0 lines done at 560 s. Survey area received by all 4 (log lines "target area 'area0000': 10 vertices" for each). Boats were still 230 to 1500 m from their line starts at 9 minutes (the machine runs the controllers at 2.6 to 4 Hz instead of 5, and `Failed to make progress` ended bluefin's lines): the four-boat demo on this computer does not finish a section in ten minutes, and a section with every line failed now backs off.

### Suggestions
Done (own commits where the files differ): rest-pad publishing resumed (with 3); first rest state kept across a Joy gap of under 60 s (`BASELINE_KEEP_SECONDS`); `navigator_unavailable` flips logged; all-lines-failed section backs off (`failed_repeat_delay` 120 s, in `demo_params.yaml`); SurveyArea stamps compared; steps (200000), lines (500) and boats (64) capped in survey_sections; the C shim refuses an offset outside plus or minus 65535 before adding it (the new test cases pass without the fix too, since the sums cannot misbehave on this platform; it removes the signed-overflow undefined behaviour); `own_task` matches the generation number whole (ben_s1 against ben_s10); `Section.heading` renamed `angle_deg` (the maths angle); `--watchdog` of the self-test needs `--demo --start-launch` and is refused before anything starts; `--watchdog/--no-watchdog` on `demo_manager.py` (the boats group's `enable_watchdog` is now the manager's own, so `enable_watchdog:=` is refused as an extra argument, like `enable_nav`). Skipped: none. Commits: the core fixes and the core suggestions share one commit (same file).

### Evidence
- Suite (marine_simulation and launch_manager_proto): 1077 tests, 8 failures, the same 8 lint failures in untouched launch files as the baseline (1035 tests, 8 failures at the checkpoint).
- Self-tests through the manager, headless, private domains: `--watchdog pad` two boats 21 of 21; `--watchdog attract` two boats 17 of 17; four boats 23 of 23 on the second run, 19 of 23 on the first (bluefin's nav2 hung in bring-up, see above; the watchdog behaved: its section stayed LOADING and flagged).
- No processes left (`pgrep` for asv_sim, demo_, nav2, mission_manager is empty).

### Open questions for Roland (not done: they change launch behaviour seen by other launches)
- nav2 bring-up robustness with four boats (about 1 in 2 on this computer): stagger the boats' nav2 start, reduce DDS participants, or have the watchdog/launch reset and start `lifecycle_manager_navigation` again (`manage_nodes` RESET then STARTUP) when `navigator_unavailable`. A hung manager cannot answer that service, so only the first two are certain.
- Boats are slow to reach their first line at four boats (700 m transit, controllers below rate); is the demo meant to be run with fewer boats on this computer?

### Deferred
- The ZeroMQ port shim upstream issue (a parameter for the Groot port in unh_marine_navigation) stays unfiled. Stage 3 is a later PR. A real pad bench check and the collision behaviour of a held boat are still not observed live.

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-21 09:34 -04:00
**By**: Claude Code Agent (Claude Sonnet)
**Verdict**: changes-requested

**Branch**: feature/issue-112 at `49864e8`
**Mode**: pre-push
**Depth**: Deep (reason: ~2950 changed lines, 24 files, new LD_PRELOAD C shim and launch changes)
**Must-fix**: 2 | **Suggestions**: 9
**Round**: 2 | **Ship**: recommended — all six round-1 must-fixes hold (each has a test, suite 1077 tests with the same 8 baseline lint failures); 2 mechanical must-fixes remain, down from 6

### Findings
- [x] (must-fix) a respawned watchdog (`respawn=True`) restarts `generation` at 0, so it reuses task ids `<boat>_s1_*` that mission_manager may still report (stale feedback taken as acknowledgement or completion), and a pad touch in BOOT after the respawn sends no manual and no clear_tasks (`_may_be_loaded` is False); seed the generation or label from a start-time nonce and clear tasks once at start-up or on the first takeover — `marine_simulation/marine_simulation/watchdog_core.py:148` (also `scripts/demo_watchdog.py:160`, `launch/demo_boats_launch.py:537`) (cross-confirmed: codex x2, Claude Lens B, Lens A)
- [x] (must-fix) `test/test_demo_watchdog.py` is not registered with `ament_add_pytest_test`, so colcon/ctest never runs the node-level area tests — `marine_simulation/CMakeLists.txt:39` (gemini, codex; verified)
- [x] (suggestion) an area change that leaves the new area unsplittable (NO_AREA) sends no clear_tasks while the old mission may still be loaded — `watchdog_core.py:247` (gemini, Lens A)
- [x] (suggestion) the clear_tasks of a takeover is sent once on a volatile publisher; repeat it once or twice or until tasks report empty — `watchdog_core.py:_take_over` (Lens B)
- [x] (suggestion) make_mission only converts ValueError/SectionError; any other exception (NaN vertices) kills the spin and a respawn loop follows; treat as NO_AREA — `scripts/demo_watchdog.py:147` (Lens B)
- [x] (suggestion) the section's edge margin only shortens segment ends along the line, so perpendicular clearance is less than edge_margin at oblique boundaries; plan said inset — `survey_sections.py:201` (codex)
- [x] (suggestion) survey_sections validation does not reject NaN/inf spacing, edge_margin, min_length, speed — `survey_sections.py:242` (gemini)
- [x] (suggestion) `_last_activity or now` treats epoch 0.0 as unset; use `is None` — `watchdog_core.py:276` (Lens A)
- [x] (suggestion) `autonomous` can be announced in the tick where the send then finds the area unsplittable; plan before announcing — `watchdog_core.py:280` (codex)
- [x] (suggestion) C shim: only zmq_bind is shifted (comment it), set errno=ENOSYS when dlsym fails — `src/demo_zmq_ports.c:79` (Lens A, Lens B)
- [x] (suggestion) unused `baseline_buttons` parameter in is_active — `watchdog_core.py:103` (gemini)

Specialists: static (pre-commit clean per commits; suite run, baseline failures only), governance (README and .agents/README.md updated; ADR-0008/0009 ok), plan drift (pad_lost_timeout vs autorepeat validation and --nav default flip are plan items not in the diff; Stage 3), Claude adversarial Lens A and Lens B, cross-model gemini and codex both ran (exit 0). Local Ollama not used.


## Implementation
**Status**: complete
**When**: 2026-10-21 10:05 -04:00
**By**: Claude Code Agent (Claude Sonnet)

**Branch**: feature/issue-112 at `67b76a8`
**Addressed**: Local Review (Pre-Push) round 2, 2026-10-21 09:34
**Commits**: 4228b7f 84c8383 6efa5e4 edfac39 e4947ae f1c4b73 ebd818f 67b76a8

### Actions
- [x] (must-fix) respawned watchdog reused task ids and sent no clear in BOOT — task labels are `<boat>_<nonce>_s<n>` (nonce = process start time), the core sends `clear_tasks` 1 s after start or at the first touch (also in BOOT); tests: a respawned core does not accept feedback with the previous instance's ids, first takeover from BOOT sends clear_tasks, start-up clear — `watchdog_core.py`, `scripts/demo_watchdog.py` (e4947ae); the self-test's `own_task` was updated to match the nonce (67b76a8)
- [x] (must-fix) test_demo_watchdog.py registered with `ament_add_pytest_test` — `CMakeLists.txt` (4228b7f); `test.sh` shows its tests in the results
- [x] (suggestion) unsplittable area change sends clear_tasks — `_send` error path (e4947ae)
- [x] (suggestion) takeover's clear_tasks resend — two repeats at `command_gap`, cancelled when the boat goes autonomous (e4947ae)
- [x] (suggestion) make_mission turns any planning exception into ValueError (NO_AREA), tests with NaN/inf/degenerate rings (e4947ae)
- [x] (suggestion) edge margin inset square to the boundary (`margin / sin(angle)`), test with an oblique side (6efa5e4)
- [x] (suggestion) NaN/inf refused for spacing, margin, min length, heading and speed (84c8383)
- [x] (suggestion) `_last_activity` / `_completed_at` use `is None` (e4947ae)
- [x] (suggestion) no `autonomous` announcement in the tick that finds the area unsplittable — planning runs before the announcement (e4947ae) (partly: when the send is held back by the TF settle or the command gap, `autonomous` is still announced first; waiting for the plan would delay the mode change by seconds, a design choice left as it was and noted in plan.md)
- [x] (suggestion) C shim: errno=ENOSYS when dlsym fails, test; comment says only zmq_bind is shifted because Groot2Publisher binds both its sockets and never connects (edfac39)
- [x] (suggestion) unused `baseline_buttons` removed from `is_active` (e4947ae)

### Verification
Full suite (`./simulation_ws/test.sh marine_simulation`): 1117 tests, 8 failures (the same 8 baseline lint failures in untouched launch files), 2 skipped. A new C416 flake8 in my own test was fixed (ebd818f). Self-test through the manager on ROS_DOMAIN_ID 137/138, bluefin+clownfish, headless: `--watchdog pad` exit 0 (all PASS: idle to autonomous, section taken, touch to manual with mission cleared, idle again generation 2 from line 0), `--watchdog attract` exit 0 (both boats autonomous, own missions, driving). A first pad run failed because the self-test's own task matcher did not know the nonce; fixed and rerun. No asv_sim/nav2/mission_manager/demo_manager processes left. README, `.agents/README.md` and plan.md "Implementation Notes (Stage 2)" updated.
