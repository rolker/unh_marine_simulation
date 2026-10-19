---
issue: 102
---

# Issue #102 — Demo: one start command — the launch manager runs window placement and the target-area publisher; retire demo_launch.py as a start path

## Plan Authored
**Status**: complete
**When**: 2026-10-15 14:23 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Plan**: `.agent/work-plans/issue-102/plan.md`
**Branch**: feature/issue-102 (not pushed)
**Phases**: single

### Open questions
- [ ] CAMP opens the shipped demo polygon by default (also the published target). Confirm in the CAMP run that it loads and shows the outline.

## Implementation
**Status**: complete
**When**: 2026-10-15 14:46 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Branch**: feature/issue-102 (not pushed)

### What was built
- `marine_simulation.roster` and `marine_simulation.demo_support` (installed package); `demo_launch.py` deleted.
- Manager groups `target_area` and `layout` (run once), new `demo_manager.py` options and preflight, `run_demo.sh` starts the manager, docs.

### Verification
- `./simulation_ws/test.sh launch_manager_proto marine_simulation mbes_sim`: 835 tests, 0 errors, 8 failures (the baseline lint in files this work does not touch), 1 skipped (host-only live test).
- Host-only (ROS_DOMAIN_ID=174, no CAMP, no GUI): `test_demo_manager_live.py` 1 passed in 74 s, now also asserting `target_area` and `scorer` READY.
- `demo_boats_selftest.py --start-launch --demo --boats bluefin,clownfish` (ROS_DOMAIN_ID=175, manager headless profile with the real publisher running): 14 of 14 checks passed, including the scorer assessing the self-test's own area.

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-15 14:46 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)
**Verdict**: approved

**Branch**: feature/issue-102
**Mode**: pre-push
**Depth**: Standard-equivalent (static flake8, two fresh Claude adversarial subagents with disjoint lenses A and B; Gemini/Codex cross-model not run, local model off)
**Must-fix**: 0 | **Suggestions**: 9 (all fixed)
**Round**: 1 | **Ship**: recommended - no must-fix

### Findings
- [x] (suggestion) A1 missing/unreadable --roster gave a traceback; ~ not expanded - `demo_manager.py`
- [x] (suggestion) A2 argparse abbreviations bypass run_demo.sh's option scan (also B2 for the self-test guard) - `allow_abbrev=False`
- [x] (suggestion) A3 empty `--layout=` etc. silently replaced by a default - `run_demo.sh` now refuses
- [x] (suggestion) A5 OSError from the lock directory gave a traceback - `demo_manager.py`
- [x] (suggestion) A6 selftest --demo now also has the real publisher: verified live, 14 of 14
- [x] (suggestion) B1 manager's layout check ignored DEMO_PLACE_WINDOWS - now honoured
- [x] (suggestion) B3 tests could import an installed copy - `test/conftest.py`
- [x] (suggestion) B4 lock does not outlive the manager - README sentence
- [ ] (suggestion, not done) A4 shell gates layout/CAMP on --profile only, so a custom --config with another default profile is mis-gated; documented here, the manager's own preflight remains authoritative
- [ ] (note) profile_actual reads `custom` after the layout group finished; cosmetic

## Review Fixes (Round 2)
**Status**: complete
**When**: 2026-10-15 14:59 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Branch**: feature/issue-102 (not pushed)

### Done
- [x] Owner request: extra `name:=value` boats-launch arguments through `run_demo.sh` / `demo_manager.py`, validated against the arguments `demo_boats_launch.py` declares (read at run time), manager-owned names refused.
- [x] Scorer-parameter location corrected in `.agents/README.md` (a `demo_manager_*` temp dir, removed on exit).
- [x] Empty option values (`--roster`, `--joysticks`, `--layout`, `--target`, `--config`, `--profile`) rejected by the manager itself.
- [x] Target file content checked in preflight (`publish_survey_area.py --check`); a malformed file is refused before anything starts.
- [x] `DEMO_ROS_DOMAIN_ID=0000` means domain 0.

### Verification
- `./simulation_ws/test.sh launch_manager_proto marine_simulation mbes_sim`: 890 tests, 0 errors, 8 failures (baseline lint), 1 skipped (host-only live test).
- Live headless test, ROS_DOMAIN_ID=174: 1 passed in 75 s; no processes left.

## Implementation
**Status**: complete
**When**: 2026-10-19 08:50 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Branch**: feature/issue-102 (not pushed beyond 273c2a9)

### Done
- [x] Fitted CAMP view: the starting view is fitted to the target polygon's bounding box (12.5 % margin, window from the layout's CAMP rect or its monitor via xrandr, 1920x1080 fallback, logged); `demo_camp_view.yaml` with a `scale` is an exact override; no target file falls back to the boats' centre at scale 1.0.
- [x] Pre-push review of the delta since de6e0ff (Claude adversarial: 11 suggestions; codex: 2 must-fix; gemini timed out at 420 s). Fixed: CAMP entry matched like place_windows, named layout-file errors, empty layout path, standalone launch without a target, clamp test, stray print removed.
- [ ] Not done: antimeridian/latitude guard (unreachable for the demo), one shared xrandr parser with place_windows, note on logical vs physical pixels under desktop scaling.

### Verification
- Full suite: 938 tests, 0 errors, 8 failures (the baseline lint), 1 skipped.
- Headless demo (ROS_DOMAIN_ID=88, 85 s): publisher sent area0000, scorer configured at cell_size=2 m, "Assessments: 36 published", no Rejecting, no process left.

## Implementation
**Status**: complete
**When**: 2026-10-19 09:30 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Branch**: feature/issue-102 (not pushed beyond 273c2a9)

### Done
- [x] Live-run defect: CAMP's title bar was off screen because place_windows sent a monitor-sized `wmctrl -e`, which mutter takes for full screen (the later maximise is ignored). Maximized mode now moves to the centred half-size rectangle first and is accepted only when `_NET_WM_STATE` (xprop) has both maximized flags and no fullscreen; the fake desktop reproduces the heuristic; a missing xprop is named; `--check` probes xprop for maximized layouts.
- [ ] Not verifiable without a live window: that mutter ends up MAXIMIZED with the title bar from this exact sequence (the host reproduced it by hand on an xterm).

### Verification
- Full suite: 944 tests, 0 errors, 8 failures (the baseline lint), 1 skipped.

## Implementation
**Status**: complete
**When**: 2026-10-19 10:05 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Branch**: feature/issue-102 (not pushed beyond 273c2a9)

### Done
- [x] Second live run: mutter maximized CAMP correctly (3774x2091+66+346, frame 0,0,37,0) but place_windows rejected it, because wmctrl -lG offsets the top by the frame once more. The check now takes `_NET_FRAME_EXTENTS` out (one xprop call with the state), judges the monitor by the window centre, and the failure says state, coverage or position. Tests: the exact live geometry accepted and logged, the same size on DP-2 rejected, FULLSCREEN still rejected.
- [ ] View-fit scale/centre problem left to the host's live diagnosis (not touched).

### Verification
- Full suite: 949 tests, 0 errors, 8 failures (baseline lint), 1 skipped.
