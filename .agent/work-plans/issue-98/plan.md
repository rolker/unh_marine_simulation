# Plan: Demo truth bathymetry: reproducible mosaic of the CCOM 4 m compilation for mbes_sim

## Issue

https://github.com/rolker/unh_marine_simulation/issues/98

## Context

`mbes_sim` samples one GeoTIFF (`BathyGrid`: band 1, nearest cell, value returned as depth, positive down). The packaged `US5NH02M.tiff` is UTM 19N, 5 m, 3316 x 5210, Float32, **no nodata tag and no NaN**: land and drying cells are negative "depths" (min -10, 7.6 M of 17.3 M cells below 0) and `mbes_sim` already skips the ping where `chart_depth < 0`. The demo (`demo_boats_launch.py`) takes `mbes_grid_file`, default the packaged grid, and refuses a path that is not a file.

Verified 2026-10-14 against the CCOM GIS (the only network used):
- 4 m service `WGOM_LI_SNE_BTY_4m_20230922_WMAS_IS`: EPSG:3857, 4 m service pixels (about 2.9 m on the ground at 43 N), F32, nodata -99999, max 15000 x 4100 px, values are elevations. Service `copyrightText`, `description` and metadata `idCredit`/`useLimit` are all empty; the portal item (id e1c5a6d0420e475f9ac26dfdc62a6b14) has a title and a one-line snippet and no description, licence or credits. The vertical datum is stated nowhere.
- 16 m service `WGOM_LI_SNE_Regional_Bathymetry_16m_WMAS_IS`: same limits, elevations (negative at the demo), nodata 3.4e38 which the exported GeoTIFF does **not** carry as a tag (the stats show 3.4e38 values), so it must be masked by value.

## Approach

1. **Host: `mbes_sim`, as a library module plus a console script.** `mbes_sim` already owns `BathyGrid`, the chart grid and the `python3-gdal` dependency, and the product is "a grid `BathyGrid` can read"; `marine_simulation` only consumes it. New `mbes_sim/mbes_sim/demo_bathy.py` with pure functions (tiling maths, mosaic/fill, provenance, coverage) and a `main()` registered in `setup.py` as `build_demo_bathy`. `marine_simulation` gets only the launch default and the README command.
2. **Dependencies.** Fetch uses stdlib `urllib` (no `requests`, no pip). GDAL python (already `python3-gdal`) for warp/VRT/write; add `python3-numpy` (rosdep, already pulled in transitively, now declared) and `test_depend` `python3-pytest`. No new rosdep key needs to be defined.
3. **Request tiling (pure, tested).** Work in service pixels: snap the lat/lon box (EPSG:4326, `--bbox W S E N`, plus a small margin for warp edges) to the service grid (origin xmax-side `-8254538.50001078 / 5636075.25001255`, step 4 m, 16 m for the regional service), then cut into tiles of at most `--tile-px` (default 2048, hard cap 4100 high / 15000 wide) that abut exactly, so no service-side resampling or seams. `exportImage` per tile with `format=tiff&pixelType=F32&bboxSR=3857&imageSR=3857&noData=<service nodata>&noDataInterpretation=esriNoDataMatchAny` (fallback: mask by value). Requests are sequential with a User-Agent, 60 s timeout, up to 5 attempts with exponential backoff plus jitter on timeouts, connection errors, HTTP 429/5xx **and** HTTP 200 whose body is not a TIFF (ArcGIS returns JSON errors with 200); a tile that exhausts retries fails the whole run (no partial product). Tiles are cached in `--work-dir` (default a temp dir, kept on failure) so a rerun resumes.
4. **Mosaic and fill (pure on arrays/rasters, tested).** Build a VRT of tiles per service; warp each to the output grid (UTM 19N, EPSG:32619, `--resolution` default 4 m, origin snapped to a multiple of the resolution, extent = bbox projected) with bilinear and the source nodata masked so nodata never bleeds into valid cells. Negate the elevations (`depth = -elevation`; intertidal and dry cells come out as small negative depths, same convention as the chart's land). Fill precedence per cell: (1) 4 m compilation, (2) 16 m regional if `--regional` (off by default), (3) packaged chart grid resampled bilinear (path overridable with `--chart-grid`), else nodata. Because the chart grid has no nodata, land cells keep the chart's negative values and the output nodata (-9999, declared in the file) appears only outside the chart extent. Seam check: report the median and 5th/95th percentile of (compilation depth - chart depth) where both are valid, as the datum/vintage indicator.
5. **Output.** Float32, EPSG:32619, tiled 256 LZW with predictor 3, band 1 positive depth, nodata -9999, plus `<out>.provenance.json` (service URLs, per-tile request boxes and pixel sizes, fetch date from the system clock, service nodata values, option set, chart-grid path and SHA-256, output SHA-256, coverage counts, seam statistics, tool version). Stdout coverage summary: cells per source (4 m / 16 m / chart / nodata) with percentages, depth range, count of negative (land or drying) cells.
6. **Reader consequences in `bathy_grid.py` (same PR, with tests).** (a) Read the band nodata and return `None` for cells equal to it or NaN, so a nodata cell can never become a sounding; (b) reject negative indices (currently `int(yi)` below -1 wraps to the far edge of the array on the left and top). Behavior for the packaged grid is unchanged (no nodata tag).
7. **Demo wiring in `marine_simulation`.** `demo_boats_launch.py`: `mbes_grid_file` default becomes empty meaning "auto". A pure `resolve_mbes_grid(arg, env, default_path, chart_path)` returns `(path, message)`: an explicit argument wins and must be a file (existing fail-fast kept); else `$MBES_DEMO_GRID`, else the default demo location `~/data/sim/mbes_truth/portsmouth_demo_4m_utm19n.tif` if it is a file; otherwise the packaged chart grid with a clear printed message ("demo truth grid not found at <path>; falling back to the 5 m chart grid; build it with `ros2 run mbes_sim build_demo_bathy ...`"). The chosen file and why are printed at launch. Grid is never committed: `.gitignore` entry for `*.provenance.json` is not needed (output lives outside the repo); the command writes under `~/data`.
8. **Tests, no network.** `mbes_sim/test/test_demo_bathy.py` on synthetic rasters written with GDAL (EPSG:3857 inputs, a small fake chart grid in UTM): negation sign; fill precedence per cell (4 m beats 16 m beats chart); regional off by default; land cells keep the chart's negative values; nodata only outside the chart extent; output CRS EPSG:32619, resolution, origin snapping, tiled/LZW, declared nodata; 16 m masking by value (3.4e38); tiling maths (exact abutment, caps 15000 x 4100, one-pixel and exact-multiple edge cases, snapping to the service grid); retry logic against a fake opener (success after 429, JSON-with-200 retried, exhaustion fails the run, no partial output); provenance content and coverage counts; `BathyGrid` nodata and negative-index tests. `marine_simulation/test/test_demo_boats_launch.py`: resolver cases (explicit, env, default present, fallback message, explicit missing file still fails). One network test (`@pytest.mark.skipif` on a 5 s probe of the service `?f=json`) fetches a single 200 x 200 px tile, checks it is a GeoTIFF with the declared nodata, and runs the fill on it.
9. **Docs.** `marine_simulation/README.md` (demo section and the argument table row for `mbes_grid_file`): source, attribution, datum caveat, the exact build command, where the grid lands, the fallback, memory note (each of four `mbes_sim` nodes loads the whole array: keep the box to the demo area). `.agents/README.md`: inventory/layout line for `demo_bathy.py`, the "69 MB grid" note, and two pitfalls (chart grid has no nodata; 16 m nodata is value-only).
   - Attribution text for the README and provenance: "Bathymetry: WGOM, LI, SNE Bathymetry and Backscatter Compilation, UNH Center for Coastal and Ocean Mapping / Joint Hydrographic Center, via the CCOM GIS image service WGOM_LI_SNE_BTY_4m_20230922_WMAS_IS (https://gis.ccom.unh.edu/server/rest/services/WGOM-LI-SNE/WGOM_LI_SNE_BTY_4m_20230922_WMAS_IS/ImageServer). The service and its portal item state no licence or copyright terms (checked 2026-10-14); contributing surveys are named by the WGOM_LI_SNE_Footprints map service."
   - Datum caveat text: "The vertical datum of the CCOM compilation is not stated in the service metadata or its portal item. The demo treats it as comparable to the chart grid (MLLW) so the simulated tide applies the same way; the coverage summary reports the measured offset between the two where they overlap. It is suitable for the demo and not to be called survey truth until CCOM GIS confirms the datum."

## Files to Change

| File | Change |
|------|--------|
| `mbes_sim/mbes_sim/demo_bathy.py` | New: tiling, fetch with retry, mosaic/fill, provenance, coverage, `main()` |
| `mbes_sim/mbes_sim/bathy_grid.py` | Nodata and negative-index handling |
| `mbes_sim/setup.py`, `mbes_sim/package.xml` | `build_demo_bathy` entry point; `python3-numpy`; test deps |
| `mbes_sim/test/test_demo_bathy.py` | New tests (offline + one skipped-offline network test) |
| `marine_simulation/launch/demo_boats_launch.py` | Auto grid resolution with fallback message |
| `marine_simulation/test/test_demo_boats_launch.py` | Resolver tests |
| `marine_simulation/README.md`, `.agents/README.md` | Source, attribution, datum caveat, command, fallback, pitfalls |

## Principles Self-Check

| Principle | Consideration |
|---|---|
| A change includes its consequences | Reader nodata/index fix, launch default, README and agent guide land together |
| Test what breaks | Fill precedence, land, nodata, retry and tiling edges tested; network test skipped offline |
| Only what's needed | stdlib HTTP, no cache layer beyond resume tiles, 16 m fill opt-in, per-beam sampling left to #75 |
| Human control and transparency | Launch prints which grid it uses and why; provenance JSON records every request |
| Workspace vs. project separation | All changes in the project repo |

## ADR Compliance

| ADR | Triggered | How addressed |
|---|---|---|
| 0008 ROS 2 conventions | Yes | `ament_python` entry point, `package.xml` deps declared, launch conventions kept |
| 0009 Python packages | Yes | No pip; apt/rosdep keys only |
| 0013 progress.md | Yes | Plan Authored entry written |
| 0017 / ADR-0018 | Yes | Project-repo PR uses local-first CI attestation at merge |

## Consequences

| If we change... | Also update... | Included in plan? |
|---|---|---|
| Launch argument default (`mbes_grid_file`) | `marine_simulation/README.md` table, launch tests | Yes |
| `bathy_grid.py` behavior | tests, `.agents/README.md` pitfalls | Yes |
| New package files / entry point | `package.xml`, `setup.py`, `.agents/README.md` inventory | Yes |

## Documentation & Instruction Impact

- **Stale docs** (must land in this PR): `marine_simulation/README.md` (`mbes_grid_file` row, venue sentence, memory note) and `.agents/README.md` (inventory, "69 MB grid" note); both updated here.
- **Agent-instruction candidates** (proposals only): pitfall that ArcGIS `exportImage` can return HTTP 200 with a JSON error body, and that the chart grid encodes land as negative depth with no nodata.

## Open Questions

- Demo box: which lat/lon box is the "demo polygon" (the packaged chart extent is 16.6 x 26 km, about 108 MB at 4 m, loaded by each of four nodes)? Plan assumes the owner supplies it for the README command.
- Default grid location: `~/data/sim/mbes_truth/portsmouth_demo_4m_utm19n.tif` proposed; or under `~/data/world/` per the one-collection rule?
- Attribution/licence: service and portal item state none; is the proposed wording acceptable, and should CCOM GIS be asked for a licence statement and the vertical datum?
- Datum: treat as MLLW-comparable (proposed), or apply an offset once CCOM GIS answers?
- Output nodata value -9999 outside the chart extent (needs the reader change in step 6), versus clipping the product to the chart extent so no nodata is written at all.
- Is `python3-numpy` acceptable as a declared dependency (already transitive)?

## Estimated Scope

Single PR, about 400 lines of code plus tests and docs.
