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
