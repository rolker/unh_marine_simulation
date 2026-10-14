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

## Plan Authored
**Status**: complete
**When**: 2026-10-14 10:02 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Plan**: `.agent/work-plans/issue-93/plan.md` at `1f872be`
**Branch**: feature/issue-93 at `1f872be`
**Phases**: single

### Open questions
- [ ] Demo SurveyStandard values (S-44 Order 1a proposed, or looser arcade standard)
- [ ] Publisher runs in the root namespace so the topic is /survey_area
- [ ] Area id with several areas in the file: CAMP label vs explicit id
- [ ] Keep spinning after publishing (plan) vs exit

## Plan Review
**Status**: complete
**When**: 2026-10-14 10:02 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5) (in-context — author self-review)

**Plan**: `.agent/work-plans/issue-93/plan.md` at `76c6348`
**PR**: PR-less
**Verdict**: approve-with-suggestions

Independence uncertain: same context that authored the plan; no fresh dispatch.

### Findings
- [x] (must-fix) Step 1 put the parser in an importable module, but marine_simulation is ament_cmake with no Python module install; keep the pure functions in the script and load it by path in tests, as check_multi_boat_graph.py does. Folded into the plan.
- [x] (suggestion) area_id semantics ambiguous with several areas; label by default, explicit id only for a single-area file. Folded in.
- [x] (suggestion) State the stamp clock (sim time under use_sim_time). Folded in.
- [ ] (suggestion) Implementer verifies the geographic_msgs exec_depend need and the late-subscriber QoS test is not flaky (timeouts) before relying on it.

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-14 10:34 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)
**Verdict**: changes-requested

**Branch**: feature/issue-93 at `a0481dc`
**Mode**: pre-push
**Depth**: Standard (reason: new node + ~290-line script + tests, 715 lines changed)
**Must-fix**: 5 | **Suggestions**: 10
**Round**: 1 | **Ship**: continue — five concrete defects, three confirmed by two or more readers; fix then re-review once

### Findings
- [ ] (must-fix) stamp read before /clock under use_sim_time is 0, so a restart after an edit is ignored by the scorer (gemini, codex, Lens A) — `marine_simulation/scripts/publish_survey_area.py:251`
- [ ] (must-fix) more than 100 areas silently evicted from the depth-100 latched history (codex, Lens A, Lens B) — `marine_simulation/scripts/publish_survey_area.py:219`
- [ ] (must-fix) module-level importorskip skips the ROS-free parser tests too (codex, Lens A) — `marine_simulation/test/test_publish_survey_area.py:191`
- [ ] (must-fix) deeply nested JSON raises RecursionError, not a refusal; recursive _items overflows (Lens B) — `marine_simulation/scripts/publish_survey_area.py:77`
- [ ] (must-fix) script committed non-executable (gemini; verify) — `marine_simulation/scripts/publish_survey_area.py:1`
- [ ] (suggestion) wrong-type parameters (standard_a:=1) die with a traceback instead of the refusal path (Lens A, Lens B) — `marine_simulation/scripts/publish_survey_area.py:238`
- [ ] (suggestion) ExternalShutdownException on SIGTERM not caught (gemini, Lens B) — `marine_simulation/scripts/publish_survey_area.py:275`
- [ ] (suggestion) at least 3 distinct vertices, not 3 entries (Lens A, gemini) — `marine_simulation/scripts/publish_survey_area.py:124`
- [ ] (suggestion) non-list children raises TypeError; no file size cap; vertex cap (gemini, Lens B) — `marine_simulation/scripts/publish_survey_area.py:78`
- [ ] (suggestion) expand ~ in file parameter (gemini) — `marine_simulation/scripts/publish_survey_area.py:133`
- [ ] (suggestion) volatile-subscriber test passes vacuously; fixed domain 87 and deprecated ROS_LOCALHOST_ONLY; grep-only install test (Lens A) — `marine_simulation/test/test_publish_survey_area.py:183`
- [ ] (suggestion) fallback label can collide with a user label (Lens B) — `marine_simulation/scripts/publish_survey_area.py:103`
- [ ] (suggestion) relative topic under a launch namespace; document (Lens B) — `marine_simulation/README.md`
- [ ] (suggestion) README claim that CAMP opens the same file is not checked against CAMP source (Lens A) — `marine_simulation/README.md`
- [ ] (false positive, dropped) GeoPolygon import source: SurveyArea.msg uses marine_interfaces/GeoPolygon (gemini) — `marine_simulation/scripts/publish_survey_area.py:204`
