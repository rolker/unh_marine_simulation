# Plan: Demo: publish the target survey polygon from a saved CAMP file to the coverage scorer

## Issue

https://github.com/rolker/unh_marine_simulation/issues/93

## Context

The coverage scorer (`coverage_assessment`, cube#164) takes target areas as
`marine_interfaces/SurveyArea` on a latched topic (`survey_area`, reliable,
transient_local, depth 100; a volatile publisher is refused with an ERROR).
Nothing in the demo produces that message. The polygon is a saved CAMP project
file: a `Group` root whose `children` hold a `SurveyArea` item whose `children`
are `Waypoint` items with `latitude`/`longitude` (demo file: 10 vertices,
verified). Message facts (read from source): `SurveyArea{id, stamp, GeoPolygon
polygon (geographic_msgs/GeoPoint[] points, ring closed implicitly), SurveyStandard
standard, int16 priority}`; `SurveyStandard{name, a, b}` with
`allowed = sqrt(a^2 + (b*depth)^2)`; a = b = 0 means "not set" and nothing meets it,
so the demo default must be a set standard.

## Approach

1. **Pure parsing functions inside the script, no ROS import at module level** -- in
   `scripts/publish_survey_area.py` (the repo's pattern: `check_multi_boat_graph.py`
   keeps its pure checks in the script and the tests load it by path with
   `importlib`; the ament_cmake package has no Python module install, so a separate
   importable module would need `ament_python_install_package`, which is not worth it).
   `load_survey_areas(path)` returns a list of `(label, [(lat, lon), ...])`. Walks
   `children` recursively (a `SurveyArea` may sit in nested `Group`s), takes `Waypoint`
   children of each `SurveyArea` in order, and raises one `SurveyAreaFileError` with a
   plain message for: missing/unreadable file, invalid JSON, no `SurveyArea` item,
   fewer than 3 vertices, a vertex missing `latitude`/`longitude`, non-numeric,
   non-finite or out-of-range lat/lon, and duplicate area ids. `rclpy` and message
   imports happen inside the node class/`main`, so the parser tests need no ROS.
2. **Publisher node** — `scripts/publish_survey_area.py` (installed to
   `lib/marine_simulation`, like the existing demo scripts; the package is
   ament_cmake, so no new package). A plain `rclpy` node, name `survey_area_publisher`.
   Parameters: `file` (default: the installed `config/demo_target_polygon_camp.json`
   resolved through `ament_index`), `topic` (default `survey_area`, relative so it
   resolves in the node's namespace), `area_id` (default empty = use each CAMP item's label, e.g. `area0000`; a
   non-empty `area_id` is valid only when the file holds exactly one area, else refused), `priority` (int, 0), `standard_name`
   (`demo`), `standard_a`, `standard_b` (demo default: IHO S-44 Order 1a, a = 0.5,
   b = 0.013, so the scoreboard is meaningful; values to be confirmed, see Open
   Questions). Standard params validated: finite and >= 0 and not both zero (refuse
   rather than silently publishing "not set", the scorer would score 0% meeting).
   Publishes one `SurveyArea` per area once, `stamp` = node clock now (simulation time
   when `use_sim_time` is set; the scorer only compares stamps of the same id), QoS
   `RELIABLE + TRANSIENT_LOCAL + KEEP_LAST depth 100` (the scorer's). On a refusal it
   logs a clear ERROR and exits non-zero (fail fast, a demo operator sees it).
   Stays spinning so the latched samples survive for late-joining scorers.
3. **Re-publish on file change is out of scope**; restart the node (documented). The
   scorer replaces a held area on a repeat of the same id with a newer stamp, so a
   restart with an edited file works without resetting the scorer.
4. **Demo polygon** — copy `.agent/scratchpad/outreach_web_camp/demo_target_polygon_camp.json`
   to `marine_simulation/config/demo_target_polygon_camp.json` unchanged (CAMP opens
   the same file, plan item 7), installed by the existing `install(DIRECTORY config)`.
5. **Tests** (`test/test_publish_survey_area.py`):
   - parser: the shipped demo file gives 10 vertices, inside lat/lon bounds, and the
     ring is not repeated; a nested-group fixture; every refusal in step 1.
   - node: build the message from a fixture (pure function, `build_survey_areas`),
     and a real-rclpy test on a private `ROS_DOMAIN_ID`/localhost: a *late* subscriber
     with the scorer's QoS (transient_local depth 100) receives the sample (this is
     the contract that matters); a volatile subscriber does not (documents why);
     the standard refusal; the exit status on a bad file.
   - A test reads `coverage_assessment`'s declared QoS from the cube README only by
     comment; no cross-repo import (no dependency on cube).
6. **README + guide** — `marine_simulation/README.md`: new "Target survey area"
   section: draw a `SurveyArea` in CAMP, File > Save, run
   `ros2 run marine_simulation publish_survey_area.py --ros-args -p file:=...`,
   restart to reload, the standard parameters, and the one-file-two-consumers note.
   `.agents/README.md`: inventory/layout line and a pitfall for the namespace/QoS.
7. **Scorer-side check (no code)** — compare the cube example
   `config/coverage_assessment.yaml` against the demo launch: topic names
   (`/survey_area` absolute vs this node's relative default; `/<boat>/sensors/mbes/grid`
   against the remaps in `demo_boats_launch.py`), `map_frame: bluefin/map`,
   `water_surface_frame: bluefin/map_tide`. Verified so far by reading: frames use
   `boat.frame('map')`. Run against a live graph only if the demo is runnable on the
   implementing host; otherwise record as unverified in the PR. File any mismatch on
   cube#164 as a comment/issue, do not edit it here.
8. **Live smoke** — with the scorer node and a demo graph up, confirm one
   `ros2 topic echo --qos-durability transient_local /survey_area` shows the area and
   the scorer log reports the area accepted (no QoS ERROR). Record in the PR.

## Files to Change

| File | Change |
|------|--------|
| `marine_simulation/scripts/publish_survey_area.py` | Pure parser + refusals + message builder, and the rclpy node with parameters and latched publisher |
| `marine_simulation/config/demo_target_polygon_camp.json` | The demo polygon (from scratchpad) |
| `marine_simulation/CMakeLists.txt` | Install the script (and python module), register new pytest tests |
| `marine_simulation/package.xml` | Add `geographic_msgs`, `builtin_interfaces` exec_depend if used directly (`marine_interfaces`, `rclpy` already present) |
| `marine_simulation/test/test_publish_survey_area.py` | New tests |
| `marine_simulation/README.md` | Target survey area section |
| `.agents/README.md` | Layout/inventory line, pitfall |

## Principles Self-Check

| Principle | Consideration |
|---|---|
| A change includes its consequences | README, `.agents/README.md`, package.xml and CMake in the same PR |
| Test what breaks | Tests target the real failure (volatile QoS never delivers; unset standard scores 0), plus every file refusal |
| Only what's needed | One script + one pure module; no file watching, no new package, no launch wiring (#94) |
| Workspace vs. project separation | Nothing in the workspace repo; all in the project repo |
| Improve incrementally | Single small PR; scorer-side mismatches go to cube#164 |

## ADR Compliance

| ADR | Triggered | How addressed |
|---|---|---|
| 0008 ROS 2 conventions | Yes | Params declared with types, exec_depends listed, flake8/pep257/copyright linters pass (new files use the D213 style the repo's README prescribes) |
| 0009 Python packages | No | Stdlib `json` only |
| 0013 progress.md | Yes | Entries written per phase |

## Consequences

| If we change... | Also update... | Included in plan? |
|---|---|---|
| Package parameters, topics (new node) | `marine_simulation/README.md` and `.agents/README.md` | Yes |
| New script installed | `CMakeLists.txt` install + `package.xml` deps | Yes |
| Demo graph gains a root-namespace publisher of `/survey_area` | `check_multi_boat_graph.py` allows root nodes to publish anywhere; self-test expectations unchanged until #94 launches it | Yes (verify, no code change expected) |

## Documentation & Instruction Impact

- **Stale docs** (must land in this PR): `marine_simulation/README.md` (new section) and `.agents/README.md` (package inventory/layout; the scorer is "not part of the demo launch" statement stays true).
- **Agent-instruction candidates** (proposals only): a pitfall that a latched topic needs transient_local on the publisher and that `ros2 topic echo` needs `--qos-durability transient_local` to see it. Proposed for `.agents/README.md`, operator decides.

## Open Questions

All four answered by the owner (relayed 2026-10-14):

- Standard: IHO S-44 Order 1a, a = 0.5, b = 0.013, named `demo`, both parameters.
- The publisher runs in the root namespace, so the topic is `/survey_area`.
- Area id: the CAMP label by default; explicit `area_id` only for a single-area file.
- The node keeps spinning after publishing.

## Estimated Scope

Single PR, about 400 lines including tests and docs.

## Deviations from the plan

- The late-subscriber test uses the node's own `latched_qos()` plus an inline volatile profile; it does not read the cube README (the README-QoS test in step 5 was dropped as a cross-repo coupling with no value).
- Step 8 live smoke ran against the node alone on a private domain (`ros2 topic echo` with transient_local showed the area; refusals exit 1); no scorer was started, so "scorer accepts the area" is not verified here.
- Step 7 was done by reading source (cube `grid` publisher, demo frames); no live-graph check.
- `make_node` is the testable core and `main` only handles the exit status; `priority` outside int16 is also refused.
