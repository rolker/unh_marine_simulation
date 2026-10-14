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

## Plan Authored
**Status**: complete
**When**: 2026-10-14 13:03 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Plan**: `.agent/work-plans/issue-98/plan.md` at `14041a3`
**Branch**: feature/issue-98 at `14041a3`
**Phases**: single

### Open questions
- [ ] Demo lat/lon box for the README command
- [ ] Default grid location (`~/data/sim/mbes_truth/` vs `~/data/world/`)
- [ ] Attribution/licence wording; ask CCOM GIS for licence and vertical datum
- [ ] Datum treated as MLLW-comparable until answered
- [ ] Nodata -9999 outside chart extent vs clip to chart extent
- [ ] Declare python3-numpy

## Plan Review
**Status**: complete
**When**: 2026-10-14 13:04 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5) (in-context — author self-review)

**Plan**: `.agent/work-plans/issue-98/plan.md` at `963aae2` (must-fix items folded in at `10fe76b`)
**PR**: PR-less
Independence uncertain: the same session authored the plan and no dispatch header is in context.
**Verdict**: approve-with-suggestions

### Findings
- [x] (must-fix) Service grid origin was written ambiguously and assumed aligned; read the origin from the service JSON and use the geotransform each returned tile carries, failing on mismatch — `plan.md` Approach 3 (folded in)
- [x] (must-fix) Output must be written atomically (`.partial` then rename) and refused over an existing file without `--force`, since the launch auto-default would otherwise pick up a half-written grid — `plan.md` Approach 5 (folded in)
- [x] (must-fix) Test list lacked a no-nodata-bleed warp test, a returned-geotransform mismatch test and an atomic-write test — `plan.md` Approach 8 (folded in)
- [x] (must-fix) Approach 7 carried a garbled `.gitignore` sentence; replaced with the real policy — `plan.md` Approach 7 (folded in)
- [x] (suggestion) Tile cache keyed by service/box/size/type and expired at 24 h so one product never mixes fetch dates — `plan.md` Approach 3 (folded in)
- [ ] (suggestion) Resolve the six Open Questions with the owner before implementation; the demo box and grid location gate the README command

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-14 13:34 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)
**Verdict**: changes-requested

**Branch**: feature/issue-98 at `c0127b9`
**Mode**: pre-push
**Depth**: Deep (reason: about 1700 changed lines, new tool plus launch change; two disjoint-lens Claude adversarial passes, governance and plan drift read by the lead; cross-model 5e off because the task limits network use to the CCOM GIS service and the GitHub API; static analysis = the repo flake8 hook, clean)
**Must-fix**: 3 | **Suggestions**: 9
**Round**: 1 | **Ship**: continue — three real defects (leaked temp dir, unretried read errors, header-only tile validation) need a second read after the fix

### Findings
- [ ] (must-fix) Temp work dir leaks on every failed run (cross-confirmed Lens A + B) — `mbes_sim/mbes_sim/demo_bathy.py:build`
- [ ] (must-fix) fetch_with_retry misses IncompleteRead/HTTPException/SSLError/OSError and service_info reads pixelSizeY outside its try; a short read is a traceback, not a retry (cross-confirmed) — `demo_bathy.py:fetch_with_retry, service_info`
- [ ] (must-fix) check_tile validates only the header: a truncated tile is cached for 24 h and later fails with an uncaught RuntimeError; data type never checked — `demo_bathy.py:check_tile`
- [ ] (suggestion) Validate server-supplied step/extent, cap body size and tile count — `demo_bathy.py:service_info, fetch_tiles`
- [ ] (suggestion) 400M-cell cap lets a typo bbox ask for 10-15 GB of memory — `demo_bathy.py:build`
- [ ] (suggestion) Fixed partial file names and world-writable work dirs: use unique partials — `demo_bathy.py:build, fetch_tiles`
- [ ] (suggestion) Provenance renamed before the grid; rename the grid first — `demo_bathy.py:build`
- [ ] (suggestion) Launch silently uses an unreadable/unprojected or wrong grid and prints the chart fallback only on stdout — `marine_simulation/launch/demo_boats_launch.py:resolve_mbes_grid`
- [ ] (suggestion) nodata compare must be float32-safe and a NaN position must not raise — `mbes_sim/mbes_sim/bathy_grid.py:getDepth`
- [ ] (suggestion) Beams over dry cells give zero or negative ranges; skip them — `mbes_sim/mbes_sim/mbes_sim.py:191`
- [ ] (suggestion) Tests do not pin absolute georeferencing (half-pixel shift would pass) — `mbes_sim/test/test_demo_bathy.py`
- [ ] (suggestion) Copyright header absent on new mbes_sim files (matches the package's existing files; deferred) — `mbes_sim/mbes_sim/demo_bathy.py`

## Implementation
**Status**: complete
**When**: 2026-10-14 13:38 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Branch**: feature/issue-98 at `b83bd26`
**Addressed**: Local Review (Pre-Push) round 1 (3 must-fix, 9 suggestions); deferred: copyright headers on new mbes_sim files (the package's existing files carry none)
**Commits**: 26b6fe7, 9564f6b, 574a42f, 80a1244, 28fb3b4, 6d5e114, c0127b9, 84d492a, c17b531, 1092d76, b83bd26

### Actions
- [x] Temp work dir removed on every exit path — `mbes_sim/mbes_sim/demo_bathy.py` (test: failed and successful runs)
- [x] Retry IncompleteRead, SSL and OSError reads; pixelSizeY read inside the try — `demo_bathy.py`
- [x] check_tile reads the band end to end and requires Float32; a poisoned cached tile is fetched again — `demo_bathy.py`
- [x] Service step, extent and non-finite values validated; body, tile and cell caps (50 M cells) — `demo_bathy.py`
- [x] Unique 0644 partials, grid renamed before provenance — `demo_bathy.py`
- [x] Launch refuses an unreadable or unprojected grid, warns per boat without water, prints on stderr — `marine_simulation/launch/demo_boats_launch.py`
- [x] nodata compared as float32, non-finite position gives None; getWaterDepth skips dry beams — `bathy_grid.py`, `mbes_sim.py`
- [x] Georeferencing ramp test — `mbes_sim/test/test_demo_bathy.py`
- [ ] Copyright headers on the new files — deferred, the package carries none today

### Results
- Build: `Finished <<< mbes_sim [4.66s]`, `Finished <<< marine_simulation [0.11s]`, `Summary: 2 packages finished [5.04s]`
- Tests: `Summary: 238 tests, 0 errors, 8 failures, 0 skipped`. mbes_sim pytest: 83 passed (54 demo_bathy incl. one network test, 14 bathy_grid). marine_simulation: 150 tests. The 8 failures are the baseline lint failures in files this issue does not touch (copyright `bizzyboat_massabesic_launch.py`, flake8 I100 `simulator_launch.py`, pep257 D213 `bizzyboat_massabesic_launch.py`, `gazebo_ben_launch.py`, `gazebo_simulator_launch.py`).
- Real build (2026-10-14, box W -70.7405 S 43.0537 E -70.6695 N 43.0937, 2936 x 2281 cells at 2 m), output `~/data/sim/mbes_truth/portsmouth_demo_utm19n.tif`, sha256 `6168c0317d43a4e3cef901b3e1d80a71a66781dc8ab6f9a5cbdb992426600c73` (a rebuild with --force reproduced it):
```
2m_compilation: 4 tile(s) of up to 2048 px
4m_compilation: 1 tile(s) of up to 2048 px
coverage (6697016 cells):
  2m_compilation      2645002   39.50 %
  4m_compilation        15821    0.24 %
  chart_grid          4036193   60.27 %
  nodata                    0    0.00 %
depth range: -3.30 .. 24.74 m (positive down)
negative-depth (land or drying) cells: 4064815
compilation minus chart where both exist (2660823 cells): median 0.89 m, 5th -0.23 m, 95th 3.41 m, mean 1.16 m
```
