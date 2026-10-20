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

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-20 12:44 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)
**Verdict**: changes-requested

**Branch**: feature/issue-111 at `503a01a`
**Mode**: pre-push
**Depth**: Deep (reason: 1438 lines in 24 files, new safety-relevant simulation logic; static analysis passed via pre-commit)
**Must-fix**: 7 | **Suggestions**: 6
**Round**: 1 | **Ship**: continue — must-fix included real design/correctness defects (a node hang, tunnelling, heading handling)
**Sources**: 2 Claude adversarial passes (Sonnet, Lens A and Lens B), Codex; Gemini timed out (420 s) and gave no review. Governance and plan drift checked by the lead.

### Findings
- [x] (must-fix, A+B+Codex) length/beam validator rejected a short boat at declare time because beam still had its default — `asv_sim/model.py`
- [x] (must-fix, A+Codex) terrain clearance compared old position at the new heading, so a turn onto land was accepted — `collision.py TerrainSource.correct`
- [x] (must-fix, A+B) -10 m clamp let a boat in the void or on high ground move anywhere, and a void boat could sail onto land — `collision.py`
- [x] (must-fix, A+Codex) terrain correction could undo the boat push (wedge); sources ran once — `collision.py Collisions.resolve`
- [x] (must-fix, Codex) capsule push for crossing axes did not separate the hulls — `collision.py capsule_penetration`
- [x] (must-fix, Codex) endpoint-only checks tunnel with a long max_step — `collision.py`
- [x] (must-fix, B) geodesic.inverse called for every far boat does not terminate for near-antipodal points (node hang) — `collision.py BoatSource`
- [x] (suggestion, B) emit failure left the boat half corrected; report after correction — `collision.py`
- [x] (suggestion, B) tide read for every boat even without terrain — `collision.py`
- [x] (suggestion, A) closing speed ignored the current — `collision.py`
- [x] (suggestion, A) weak never-damaged test assertion — `test_collision.py`
- [x] (suggestion, A+B) docs: one event per contact semantics, not latched, memory size of the grid — READMEs, message
- [ ] (suggestion, A) multi-contact corner speed is a product of reductions, not a projection — `collision.py` (accepted, documented as order dependent)

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-20 12:44 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)
**Verdict**: approved

**Branch**: feature/issue-111 at `5e9cba3`
**Mode**: pre-push
**Depth**: Light (reduced second round on the fix commits; one Claude adversarial pass, Sonnet)
**Must-fix**: 1 | **Suggestions**: 5
**Round**: 2 | **Ship**: recommended — the one must-fix was mechanical and is fixed with a test that fails on the old code; no design question remains

### Findings
- [x] (must-fix) every contact rewrote the heading from the hop interpolation (de-normalised across 2*pi) and zeroed yaw_rate — `collision.py Collisions.resolve`
- [x] (suggestion) speed projection used the heading before a revert — `collision.py`
- [x] (suggestion) MAX_HOPS cap bit silently; now warns once — `collision.py`
- [x] (suggestion) always-acceptable candidate and dead return made explicit — `collision.py`
- [ ] (suggestion) terrain frame rebuilt per hop and per pass (cost only, measured 0.1 ms per call) — `collision.py`
- [ ] (suggestion) hop azimuth is taken at the start of the step, approximate over very long drifts — `collision.py`

## Implementation
**Status**: complete
**When**: 2026-10-20 12:44 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Branch**: feature/issue-111 at `79fa385`
**Plan**: `.agent/work-plans/issue-111/plan.md`, kept in sync (Implementation Notes at its end)

### Verification
- asv_sim pytest: 128 passed, 1 skipped (the launch_test integration file is ignored by plain pytest); test_collision.py 54 of them
- colcon test, all 11 simulation packages: 1205 tests; failures are only the baseline lint ones in untouched files (marine_simulation launch copyright/flake8/pep257, portsmouth_nh_gazebo flake8/pep257) plus asv_sim_msgs xmllint on package.xml element order, which fails identically on the file before this branch
- demo_boats_selftest.py --start-launch --boats bluefin,clownfish with terrain collision on (demo truth grid): 12 of 12 checks passed
- headless run of the real demo grid, one boat at six headings from the bluefin start: stops at the shore or slides along it, ends in 0.65 m to 2.4 m of water at tide 0

- test_set_pose_heading_is_a_compass_heading was noise-flaky before this branch (yaw noise random-walks the heading: median 12.6 deg, 12 % of runs beyond the 26.6 deg bound after 5 s, measured over 1000 runs); now runs with dynamics noise 0 and a tighter bound, 30 of 30 passes

### Open questions
- [ ] No open questions.
