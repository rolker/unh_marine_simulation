---
issue: 97
---

# Issue #97 — Prototype the launch/lifecycle manager in this repo as the demo's launch system — milestone 1

## Issue Review
**Status**: complete
**When**: 2026-10-14 12:27 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Issue**: #97
**Comment**: (best-effort post follows this entry; not recorded inline)
**Scope verdict**: well-scoped (large; one PR only if the plan cuts hard to the listed items)

### Actions
- [ ] Action needed: pin the marine-free boundary as a concrete package layout (new package, deps limited to rclpy/launch/launch_ros/lifecycle_msgs/ros2launch_session; demo config in marine_simulation) so the later move is a `git mv` (issue asks for this; "or a sibling package" leaves it open).
- [ ] Action needed: decide the interface shape for `~/status` / `~/command` in the plan (own msgs vs std_msgs strings). The design says own interfaces package with no marine_interfaces dependency; a prototype that is meant to be moved must not leak a throwaway wire format into the real repo unannounced.
- [ ] Action needed: item 1 requires the convergence loop to be usable standalone (post-launch guard for demo_boats_launch.py) AND inside the manager. Plan must make the core a library plus a thin node/CLI so both entry points share one code path.
- [ ] Action needed: the "lost change_state reply" test (item 6) needs a deterministic fake; plan must say how a lost reply is injected and detected (get_state polling) rather than relying on the field race.
- [ ] Action needed: item 5 ("closing CAMP stops the demo") must be a `requires`-style dependency rule, but the design's `requires` means "must be READY before start" only; stop-propagation is a new semantic. Plan must define it (e.g. a `stops_with` / `bound_to` key) and record it as a deviation from the design.
- [ ] Action needed: launch-level test (item 6) needs the datum grids and ~50 processes; plan must say what runs in CI/ci_local versus on the dev host only (mark host-only tests, do not skip silently).
- [ ] Recommendation: state which design open items are deferred (output channel, stale-command reordering, ack slot, force field, sticky FAILED on link groups, scoped group shutdown beyond all-or-nothing, delegate, readiness predicates beyond nodes/lifecycle_active).
- [ ] Recommendation: consequences to land in the same PR: marine_simulation README (demo section), .agents/README.md package inventory and layout, package.xml exec_depend changes, and a note on #96 linking the fix.
- [ ] Recommendation: ADR-0008 conventions apply (license headers, ament_python layout, flake8 config incl. D213 style already used here); no ADR needed (design doc says deliberately none).

## Plan Authored
**Status**: complete
**When**: 2026-10-14 12:29 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Plan**: `.agent/work-plans/issue-97/plan.md` at `78861da`
**Branch**: feature/issue-97 at `78861da`
**Phases**: single

### Open questions
- [ ] lifecycle_guard default on in demo_boats_launch.py?
- [ ] JSON in std_msgs/String acceptable for the prototype wire format?
- [ ] Closing CAMP stops the whole demo and exits the manager?
- [ ] Target-area publisher (#93) stub group now or later?
- [ ] Scoped-stop spike fails: accept all-or-nothing with per-group STOP/START rejected?
- [ ] Package name launch_manager_proto, rename at move time?
- [ ] Record design deviations in the uma design doc via follow-up, or only in this README?
