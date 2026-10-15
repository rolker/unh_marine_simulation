---
issue: 94
---

# Issue #94 — Demo: one launch for the whole display (boats, CAMP, scorer, target area) with a fixed window layout and a known CAMP state

## Issue Review
**Status**: complete
**When**: 2026-10-14 10:02 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Issue**: #94
**Comment**: (best-effort post follows this entry; not recorded inline)
**Scope verdict**: well-scoped

### Actions
- [ ] Watch: `camp_launch.py` takes no launch arguments and no environment hook, so item 2 cannot be a plain include if the launch must pass CAMP a project file or a settings location; plan starts the CAMP executable from the demo launch (same executable and workspace argument) and optionally files a camp issue for launch arguments.
- [ ] Watch: neither `wmctrl` nor `xdotool` is installed on the dev host; both have rosdep keys (apt) so the dependency is a normal `<exec_depend>`, never pip.
- [ ] Watch: the scorer's example config names the four boats literally; the roster is the only place boat names live (README), so the demo launch should generate the scorer parameters from the roster (also honours `boats:=`).
- [ ] Watch: CAMP's live coverage layer defaults to `visible=false` and `live_enabled=false` and CAMP persists `MainWindow/mapCenter` in scene coordinates, so a seeded settings profile must set these explicitly; verify the scene-coordinate centre is reproducible across sessions.
- [ ] Watch: item 4 depends on #93 (being worked in parallel); keep it behind a launch argument until it lands.
- [ ] Consequences: README helper card, `.agents/README.md` inventory/pitfalls, `package.xml` exec_depends (camp already there; add coverage_assessment, wmctrl), CMake install of new dirs/scripts and tests.
- [ ] The acceptance test (cold boot, one command) is a human rehearsal on the dev laptop and cannot be run by an agent.

## Plan Authored
**Status**: complete
**When**: 2026-10-14 10:03 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Plan**: `.agent/work-plans/issue-94/plan.md` at `a9bf24f`
**Branch**: feature/issue-94 at `a9bf24f`
**Phases**: single

### Open questions
- [ ] Contact name/number for the helper card
- [ ] Monitor assignment on the event machine
- [ ] Autostart at login or one typed command
- [ ] Reset of CUBE/scorer between players (not in plan)
- [ ] OK to start CAMP directly and file a camp issue for launch arguments
- [ ] Live coverage colormap and range
- [ ] Name of the target-area launch/node from #93

## Plan Review
**Status**: complete
**When**: 2026-10-14 10:03 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5) (in-context — author self-review)

**Plan**: `.agent/work-plans/issue-94/plan.md` at `a9bf24f`
**PR**: PR-less
Independence uncertain: this context wrote the plan and no fresh dispatch intervened; same model string as the plan author.
**Verdict**: changes-requested (must-fix items folded into the plan in the next commit)

### Findings
- [x] (must-fix) The runtime settings directory is deleted and re-created on every launch; guard the delete (exact path under home, not a symlink, expected contents) and test it — plan.md step 5
- [x] (must-fix) CAMP persists the view in two places (`MainWindow/mapScale`+`mapCenter` and `MapView/mapView/scale`+`center`); the profile must set both and the first implementation task must establish which wins — plan.md step 6
- [x] (must-fix) The selftest scorer check depended on a survey area that #93 does not provide yet; the selftest publishes its own `SurveyArea` — plan.md step 10(c)
- [ ] (suggestion) Placement process must not shut the launch down when it exits normally — folded into step 12 text
- [ ] (suggestion) 12 files is at the edge of one PR; split placement/profile from the launch if it grows — folded into Estimated Scope
- [ ] (suggestion) PR body should say "Part of #94", not a closing keyword, until the cold-boot rehearsal is done — folded into Estimated Scope
- [ ] (suggestion) The live coverage layer key `live:<ns>` for four boats may be several layers; capture before writing the profile (open question already listed)

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-14 10:45 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)
**Verdict**: changes-requested

**Branch**: feature/issue-94 at `ccd8654`
**Mode**: pre-push
**Depth**: Deep (reason: 2400+ added lines, new launch, process control and deletion code)
**Must-fix**: 6 | **Suggestions**: 12
**Round**: 1 | **Ship**: continue — real defects found, two independent sources agree on three; Gemini arm timed out (7 min), Codex and two Claude lenses ran

### Findings
- [x] (must-fix) `wmctrl -b` takes two properties; the four-property clear leaves maximized_horz set (Claude A, Codex) — `marine_simulation/scripts/place_windows.py:243`
- [x] (must-fix) `target_area_file` is only validated when enable_target_area is true; a typo reaches CAMP unrefused and the README claim is false (Claude A, Codex) — `marine_simulation/launch/demo_launch.py:467`
- [x] (must-fix) A CAMP already running is found first by the window match and placed instead of the demo's; refuse to start when one runs and prefer the newest matching window (Claude B, Claude A, Codex) — `marine_simulation/scripts/place_windows.py:226`
- [x] (must-fix) Fail-fast refusals (Wayland, no wmctrl, monitor unplugged) reach the helper as a Python traceback; run_demo.sh must check them first in plain words (Claude B) — `marine_simulation/scripts/run_demo.sh:42`
- [x] (must-fix) The live tile cache is kept outside the reset settings directory, so a previous session's tiles can be warm-loaded; the README claim is false (Claude A) — `marine_simulation/launch/demo_launch.py:254`
- [x] (must-fix) CAMP restores its centre at its first window size and placement then resizes it, so the view may shift; cannot verify without running CAMP (Claude A) — `marine_simulation/launch/demo_launch.py:480` (deferred: not fixable in this repo; filed rolker/camp#242, README says the view must be checked at the rehearsal)
- [x] (suggestion) No lock: a second launch deletes the first one's settings directory (Claude B, Claude A) — `marine_simulation/launch/demo_launch.py:254`
- [x] (suggestion) Placement failure is a stderr line only; add a banner on non-zero exit, longer default wait, final pass after the deadline (Claude B, Claude A) — `marine_simulation/scripts/place_windows.py:284`
- [x] (suggestion) parse_monitors drops a monitor with several output names (Claude A) — `marine_simulation/scripts/place_windows.py:68`
- [x] (suggestion) load_view does not check types or ranges (Claude A) — `marine_simulation/launch/demo_launch.py:227`
- [x] (suggestion) check_session refuses an X11 session whose XDG_SESSION_TYPE is unset (Claude A) — `marine_simulation/scripts/place_windows.py:338`
- [x] (suggestion) Pause between clearing window state and moving it (Claude A) — `marine_simulation/scripts/place_windows.py:243`
- [x] (suggestion) Tests: realistic wmctrl lines (title with spaces, desktop -1, negative offsets), exact poll count for the single deadline (Claude A) — `marine_simulation/test/test_place_windows.py:1`
- [x] (suggestion) run_demo.sh requires joysticks.yaml and layout.yaml even when the matching feature is switched off (Claude A) — `marine_simulation/scripts/run_demo.sh:35`
- [x] (suggestion) run_demo.sh keeps an already exported ROS_DOMAIN_ID, so the domain is not private; also check HOME (Claude B) — `marine_simulation/scripts/run_demo.sh:29`
- [x] (suggestion) Pass the target file to CAMP as an absolute path (Claude B) — `marine_simulation/launch/demo_launch.py:480`
- [x] (suggestion) README: XDG_CONFIG_HOME change also hides other CAMP config; placement is one-shot; state directory persists (Claude B, Claude A) — `marine_simulation/README.md:1`
- [x] (suggestion) Harden reset_settings_root (symlinked parents, temp-file write for scorer params, scorer exit banner) (Claude B) — `marine_simulation/launch/demo_launch.py:254` (deferred: directory mode 0o700 done; the rest is low risk behind the marker and lock rules, and a scorer crash is visible in the output; no respawn is deliberate)

## Implementation
**Status**: complete (pending owner rehearsal)
**When**: 2026-10-14 11:25 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Commits**: 0d5594b..e56e7b3 (review round 1 fixes, on top of the first implementation commits cd45492..8570d23)

### What was done
- One launch for the whole demo display (demo_launch.py), run_demo.sh, place_windows.py, per-machine layout, docs; round-1 review fixes in 0d5594b..e56e7b3.
- Owner requirement met and tested (dae53c0): closing CAMP shuts the whole launch down.

### Deferrals
- View may shift when placement resizes CAMP after it restored its centre: not fixable in this repo, filed rolker/camp#242; README says to check the view at the rehearsal.
- Reset-guard hardening beyond directory mode 0o700 (symlinked parents, temp-file write for scorer params, scorer exit banner): low risk behind the marker and lock rules; a scorer crash is visible in the output.

### CAMP issues filed
- rolker/camp#240
- rolker/camp#242

### Live self-test (ROS_DOMAIN_ID=88, two boats)
- demo run 1 (earlier agent): 14 of 14 passed.
- demo runs 2, 4, 5 (clean): 13/14 (clownfish CUBE coverage 0 messages), 13/14 (bluefin chart_datum frames missing), 11/14 (platform, motion); each failing log shows a launch_ros lifecycle "Abandoning wait for ... change_state service response" at shutdown. Run 3 was contaminated by two runs sharing the domain and is not counted.
- The unmodified boats self-test (no --demo) fails the same way: 4 of 6 runs passed all 12 checks (demo_launch without the scorer: 2 of 3) (failures: missing chart_datum frames; platforms never appeared). So the flake is pre-existing in the boats launch (lifecycle service responses lost), not caused by this branch. Not fixed here; needs its own issue.
- Placement live checks (wmctrl not installed, no CAMP started): not run.

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-14 11:33 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)
**Verdict**: changes-requested

**Branch**: feature/issue-94 at `b833a03`
**Mode**: pre-push
**Depth**: Deep (reason: 2400+ added lines, launch and process control code)
**Must-fix**: 4 | **Suggestions**: 6
**Round**: 2 | **Ship**: recommended after the fixes — all four must-fix items are small and mechanical; two Claude lenses found no must-fix, Codex and Gemini found these (one Gemini must-fix, package.xml camp, is false: exec_depend camp is at package.xml:27)

### Findings
- [x] (must-fix) run_demo.sh copied to ~/bin (as the README says) cannot find place_windows.py; resolve it from the installed package when not beside the script (Codex, Gemini) — `marine_simulation/scripts/run_demo.sh:61` (fixed 5852025)
- [x] (must-fix) timeout_seconds accepts .nan and .inf, so placement can wait forever; require a finite number (Codex) — `marine_simulation/scripts/place_windows.py:166` (fixed 8a939c4)
- [x] (must-fix) run_demo.sh demands and checks the default layout.yaml/joysticks.yaml even when joystick_config:= or layout_config:= is given on the command line (Codex, Claude A) — `marine_simulation/scripts/run_demo.sh:41` (fixed 5852025)
- [x] (must-fix) settle(): a window that vanishes between listing and the wmctrl call raises LayoutError out of place_all and aborts the remaining windows (Gemini) — `marine_simulation/scripts/place_windows.py:356` (fixed 8a939c4)
- [x] (suggestion) switched_off matches only lowercase values; the launch accepts any case (Gemini, Claude A) — `marine_simulation/scripts/run_demo.sh:46` (fixed 5852025)
- [x] (suggestion) place_all promises one more look after the deadline but breaks without listing again (Claude A) — `marine_simulation/scripts/place_windows.py:323` (fixed 8a939c4)
- [x] (suggestion) state and run directories use the umask default, not 0o700 (Claude B) — `marine_simulation/launch/demo_launch.py:acquire_demo_lock` (fixed, see the commit "private state directories")
- [x] (suggestion) fixed ROS domain 42 is shared by two users on one host, DEMO_ROS_DOMAIN_ID is not range-checked (Claude B) — `marine_simulation/scripts/run_demo.sh:29` (deferred, then done after round 3 by owner decision: 42 stays the default, DEMO_ROS_DOMAIN_ID overrides and is now range-checked 0 to 101, see 4e8151a)
- [x] (suggestion) tilde paths in layout_config/camp_profile/camp_view_config are not expanded (Gemini) — `marine_simulation/launch/demo_launch.py:529` (deferred: run_demo.sh now expands ~ for the files it checks; the launch gets absolute paths from it, direct ros2 launch users type full paths)
- [x] (suggestion) view_center divides by len(boats) without an empty check (Gemini) — `marine_simulation/launch/demo_launch.py:243` (fixed, see the commit "private state directories")

## Implementation
**Status**: complete
**When**: 2026-10-14 11:35 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Branch**: feature/issue-94 at `3c069e7`
**Addressed**: Local Review (Pre-Push), round 2
**Commits**: 5852025, 8a939c4, 154a72e

### Actions
- [x] run_demo.sh finds place_windows.py from a copy in ~/bin — `marine_simulation/scripts/run_demo.sh:61`
- [x] timeout_seconds must be finite — `marine_simulation/scripts/place_windows.py:166`
- [x] layout/joystick files given on the command line replace the defaults — `marine_simulation/scripts/run_demo.sh:41`
- [x] a window that closes mid-placement is a named problem, not an abort — `marine_simulation/scripts/place_windows.py:356`
- [x] switches read in any letter case; one look after the deadline; private state directories; empty-fleet guard
- [x] fixed ROS domain 42 on shared hosts, tilde paths in direct launches — `marine_simulation/scripts/run_demo.sh:29` (deferred: needs an owner decision / low risk, see the review entry)

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-14 11:43 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)
**Verdict**: approved

**Branch**: feature/issue-94 at `6b32167`
**Mode**: pre-push
**Depth**: Deep (reason: launch and process control code), reduced re-review of the round 2 fixes: Codex and one Claude pass (Gemini timed out at 420 s)
**Must-fix**: 0 | **Suggestions**: 5
**Round**: 3 | **Ship**: recommended — Codex's three must-fix items were fixed in 477727f and 6b32167; only suggestions remain

### Findings
- [ ] (suggestion) a window that vanishes during settle is not looked for again within the timeout (Codex) — `marine_simulation/scripts/place_windows.py:323`
- [ ] (suggestion) mode 0o700 only applies to a newly created state directory; an existing 0755 one stays (Claude) — `marine_simulation/launch/demo_launch.py:354`
- [ ] (suggestion) the top-of-loop list_windows in place_all can still abort every placement on a wmctrl failure (Claude) — `marine_simulation/scripts/place_windows.py:313`
- [ ] (suggestion) no test for DEMO_PLACE_WINDOWS precedence or the "package not found" branch (Claude) — `marine_simulation/test/test_run_demo.py:1`
- [ ] (suggestion) fixed ROS domain 42 on shared hosts (carried from round 2, deferred) — `marine_simulation/scripts/run_demo.sh:29`

## Implementation
**Status**: complete
**When**: 2026-10-15 (merge-up and publication)
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Branch**: feature/issue-94
**Addressed**: Local Review (Pre-Push), round 3 deferred item (ROS domain)

**Merge-up**: `7ab5a64` merges origin/jazzy (PR #95 demo polygon, PR #99 truth bathymetry). Conflicts, both sides kept: `.agents/README.md` (tree block merged: place_windows.py, run_demo.sh, publish_survey_area.py, demo_target_polygon_camp.json, survey-area test; the pitfalls from both sides kept) and `marine_simulation/CMakeLists.txt` (installs and pytest registrations from both). `marine_simulation/README.md` auto-merged.

**Domain override** (`4e8151a`): 42 stays the default; `DEMO_ROS_DOMAIN_ID` already existed and wins. Added a check (whole number 0 to 101, leading zero not octal, empty means default) with a plain stop message, a test for default, override, boundaries and rejections, and README wording.

**Tests**: `./simulation_ws/test.sh marine_simulation mbes_sim`: `Summary: 485 tests, 0 errors, 8 failures, 0 skipped`; the 8 are the pre-existing lint failures (copyright 1, flake8 I100 1, pep257 D213 3 in bizzyboat_massabesic_launch.py, gazebo_ben_launch.py, gazebo_simulator_launch.py; flake8 in simulator_launch.py), none in this issue's files.

**Still owed**: cold-boot rehearsal on the demo machine.
