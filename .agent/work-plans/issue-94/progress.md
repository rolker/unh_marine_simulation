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
