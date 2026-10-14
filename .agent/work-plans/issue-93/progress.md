---
issue: 93
---

# Issue #93 — Demo: publish the target survey polygon from a saved CAMP file to the coverage scorer

## Issue Review
**Status**: complete
**When**: 2026-10-14 10:01 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Issue**: #93
**Comment**: (best-effort post follows this entry; not recorded inline)
**Scope verdict**: well-scoped

### Actions
- [ ] Pin the message facts the issue leaves open: `SurveyStandard` holds `name`, `a`, `b` (not-set = a=b=0, which scores zero meeting); the demo default must be a set standard or the scoreboard reads 0%.
- [ ] Topic name: scorer example yaml uses absolute `/survey_area`; scorer default is relative `survey_area`. Default the node to `survey_area` but make the demo wiring resolve to the same topic the scorer subscribes to (global namespace or explicit remap); record the check in the README.
- [ ] Scorer-side frame/topic check (`bluefin/map`, `<boat>/sensors/mbes/grid`) against the running graph: file any mismatch against cube#164, do not patch here.
- [ ] Decide node form (plain Python script installed to lib/, like the existing demo scripts, vs a new package). Recommendation: script in marine_simulation, parse logic in an importable module so tests need no ROS graph for the refusals.
- [ ] Update `.agents/README.md` (package inventory/layout, new dependency) and `marine_simulation/README.md`; add `marine_interfaces` already present as exec_depend (verify).
