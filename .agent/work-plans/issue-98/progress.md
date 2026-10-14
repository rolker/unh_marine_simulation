---
issue: 98
---

# Issue #98 — Demo truth bathymetry: reproducible mosaic of the CCOM 4 m compilation for mbes_sim

## Issue Review
**Status**: complete
**When**: 2026-10-14 13:02 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Issue**: #98
**Comment**: (best-effort post follows this entry; not recorded inline)
**Scope verdict**: well-scoped

### Actions
- [ ] Correct the issue's land premise: `US5NH02M.tiff` has no nodata tag and no NaN; land and drying cells are negative "depth" values (min -10, 7.6 M of 17.3 M cells < 0). `mbes_sim` already treats `chart_depth < 0` as no ping. "Nodata only where even the chart grid has none (land)" therefore reduces to: land keeps the chart's negative values; a nodata value appears only outside the chart extent. The plan must state this.
- [ ] Decide how out-of-extent / nodata cells are encoded, since `BathyGrid` has no nodata handling and the per-beam loop uses `getDepth` unfiltered; the plan should add minimal nodata handling to `bathy_grid.py` (small consequence of the new product) or avoid writing a nodata value.
- [ ] Datum: the chart grid is MLLW (mbes_sim adds tide above MLLW) while the 4 m compilation's datum is unstated; the README caveat and the provenance JSON must say so, and a seam check between sources is worth reporting in the coverage summary.
- [ ] Recommendation: pin the host package (mbes_sim owns the grid reader; marine_simulation owns the demo) and the demo-grid location/launch default in the plan; add rosdep keys only if new (GDAL already a dependency; no pip, ADR-0009).
- [ ] Recommendation: README, `.agents/README.md` (inventory, pitfalls), and `.gitignore` for the generated grid land in the same PR (consequences).
