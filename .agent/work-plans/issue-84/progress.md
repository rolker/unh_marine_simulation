---
issue: 84
---

# Issue #84 — asv_sim: unbounded speed integration overflows in dynamics.py drag calc, killing the node mid-session

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-19
**By**: Claude Code Agent (Claude Sonnet 5.5)
**Verdict**: approved

**Branch**: feature/issue-84
**Mode**: pre-push
**Depth**: Standard (dynamics rewrite, new parameters); 2 Claude adversarial lenses (Sonnet) + codex; gemini timed out
**Must-fix**: 0 open (5 found, fixed) | **Suggestions**: 4 open
**Round**: 1 | **Ship**: recommended — all must-fix addressed in the last commit

### Findings
- [x] (must-fix) frozen-coefficient drag oscillates from rest at long steps; now a monotone Newton solve — `asv_sim/asv_sim/dynamics.py`
- [x] (must-fix) acceleration not in the finite-state check (published in IMU) — `dynamics.py`
- [x] (must-fix) rclpy logger raises on one call site at two severities; escapes from the recovery path — `dynamics.py:_log`
- [x] (must-fix) NaN environment current hangs geodesic.direct — `dynamics.py:_step`
- [x] (suggestion) environment wave/tide calls unguarded — `dynamics.py:update`
- [ ] (suggestion) prop propulsion thrust term (-k v^2) is still explicit; stability there rests on max_step — `dynamics.py`
- [ ] (suggestion) `except (ArithmeticError, ValueError)` also swallows config bugs; only logged every 5 s — `dynamics.py:update`
- [ ] (suggestion) max_step 0.001 with max_substeps 10000 could starve the node timer; product not bounded — `model.py`
- [ ] (suggestion) geodesic.direct/inverse have unbounded loops on pathological input — `geodesic.py`
