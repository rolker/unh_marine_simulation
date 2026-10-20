---
issue: 111
---

# Issue #111 — asv_sim: boats collide with terrain and with each other (block passage; boats indestructible for now)

## Issue Review
**Status**: complete
**When**: 2026-10-20 11:31 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Issue**: #111
**Comment**: (best-effort post follows this entry; not recorded inline)
**Scope verdict**: well-scoped

### Actions
- [ ] Watch: the grid is read by a second process (asv_sim) beside each mbes_sim; the demo truth grid is 27 MB at 2 m, the chart grid 69 MB. Plan must say how it is shared (import of mbes_sim.bathy_grid, one load in the one asv_sim node) and what happens when no grid is configured (collision off, say so loudly).
- [ ] Watch: boat velocity is a body-forward speed plus a current drift applied to position, not a velocity vector in state. "Zero the velocity component" needs a definition against the integration in dynamics.py (issue #84 sub-stepping).
- [ ] Watch: datum caveat from #98 (CCOM compilation datum unstated, treated as MLLW) applies to grounding depth as well; note it in the docs.
- [ ] Recommendation: land/nodata = wall, no-grid = no collision; keep all later consequences (damage, reset) out of scope as the issue says.
- [ ] Consequences: asv_sim parameter table in .agents/README.md, asv_sim/README, demo roster/launch, marine_simulation README, package.xml deps, new tests.

## Plan Authored
**Status**: complete
**When**: 2026-10-20 11:33 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Plan**: `.agent/work-plans/issue-111/plan.md` at `637b6db`
**Branch**: feature/issue-111 at `637b6db`
**Phases**: single

### Open questions
- [ ] Footprint values for models other than demo/cw4 (unverified defaults 4.0 x 1.7 x 0.4)
- [ ] Collision default on only where a grid is passed (demo); sim_robot_launch stays off
- [ ] Wave heave/roll/pitch ignored for clearance

## Plan Review
**Status**: complete
**When**: 2026-10-20 11:33 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5) (in-context — author self-review)

**Plan**: `.agent/work-plans/issue-111/plan.md` at `637b6db`
**PR**: PR-less
Independence uncertain: this review ran in the same context that authored the plan, with no fresh dispatch.
**Verdict**: approve-with-suggestions

### Findings
- [x] (must-fix) contact code ran inside the except-and-reset-to-rest region of Dynamics.update; hook now has its own try/except, logged, uncorrected step kept — plan.md step 2
- [x] (must-fix) asv_sim_msgs needs a std_msgs dependency (CMake + package.xml) — Files table
- [x] (suggestion) length >= beam needs a pre-set validator, Model has only post-set callbacks — step 4
- [x] (suggestion) contact-end timer must use the node clock, not wall time — step 8
- [ ] (suggestion) other models' footprints stay unverified defaults — Open Questions
- [ ] (suggestion) wave heave/roll/pitch ignored for clearance — Open Questions
