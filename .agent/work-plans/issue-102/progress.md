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
