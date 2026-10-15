# Plan: One start command — the launch manager runs window placement and the target-area publisher; retire demo_launch.py

## Issue

https://github.com/rolker/unh_marine_simulation/issues/102 (part of #87; follows #94 / PR #100 and #97 / PR #101; #94 stays open for the rehearsal)

## Context

After #100 and #101 the demo has two start paths, each lacking what the other has. `run_demo.sh` runs `demo_launch.py` (window placement and the target-area publisher, but the plain launch_ros start-up that races as in #96); `demo_manager.py` is the launch manager (the #96 fix, `follows: [camp]`) without placement or the publisher, and it loads `demo_launch.py` and `demo_boats_launch.py` **by file path** to reuse their helpers. The owner decided (2026-10-15): the manager is the engine, `run_demo.sh` starts it, `demo_launch.py` stops being a start path, the shared helpers become an importable module, and README / `.agents/README.md` / helper card describe exactly one command.

## Approach

1. **Importable helpers: a Python package inside `marine_simulation`.** `marine_simulation` is an ament_cmake package with no Python package today; add `marine_simulation/marine_simulation/` (installed with `ament_python_install_package`, `ament_cmake_python` buildtool dependency). Two modules:
   - `roster.py`: `Boat`, `load_roster`, `select_boats`, `parse_bool`, the name rules (moved out of `demo_boats_launch.py`, which imports them back so its tests and its callers are unchanged). Needed because the manager and `demo_support` use the roster, and "nothing is loaded by file path" includes `demo_boats_launch.py`.
   - `demo_support.py`: everything `demo_launch.py` held that is not a start path: CAMP settings profile (`build_profile`, `qt_point_variant`, `load_view`, ...), the state directory / reset / `acquire_demo_lock`, `running_camp_pids` / `refuse_running_camp`, `scorer_parameters`, `camp_node` / `camp_actions`, `placement_process` / `placement_exit`, `require_file`.
   `demo_camp_launch.py`, the new launch files and `demo_manager.py` import these normally. A test scans `launch/` and `scripts/` for `spec_from_file_location` so a load-by-path cannot come back. Window-placement preflight runs the installed `place_windows.py --check` as a subprocess (it is a script, not a module), exactly what `run_demo.sh` already does, instead of importing it by path.
2. **Window placement and the polygon publisher are manager groups.** A group is one launch file, so two small launch files are added: `demo_target_area_launch.py` (the `publish_survey_area.py` node, `file` = the target area) and `demo_layout_launch.py` (`place_windows.py` via `ExecuteProcess` plus the conspicuous "THE WINDOWS ARE NOT IN PLACE" message on a non-zero exit, moved from `demo_launch.py`).
   ```
   target_area  follows [camp]            restart on-failure   (long-running latched publisher)
   scorer       requires [boats, target_area], follows [camp]
   layout       requires [camp], follows [camp], restart never (run-once)
   profiles     demo: boats camp scorer target_area layout
                headless: boats scorer target_area     boats: boats
   ```
   Why groups fit: the scorer must not start before its target exists (`requires` is that rule), the publisher must stop with CAMP (`follows`), and placement must wait for CAMP's process (`requires: [camp]`; place_windows itself waits up to 90 s for the window). **Run-once semantics checked against `manager_core`:** a clean exit of the last process of a `restart: never` group sets the group STOPPED and its desired state STOPPED; it is not a failure and only groups that *follow that group* are stopped (nothing follows `layout`); a non-zero exit is FAILED, named in the ERROR log and `status`, and does not stop the demo (the launch file also prints the conspicuous message); `command start layout` re-places the windows. The only wart is the detail text "closed by the operator", which is wrong for a finished one-shot; it becomes the neutral `exited(0)` and a `manager_core` test pins the run-once behaviour. One convergence loop stays: nothing is added to the manager core.
3. **Defaults.** The target area defaults to the installed `config/demo_target_polygon_camp.json` (what `publish_survey_area.py` already defaults to), so the scorer always has a target and the same file is given to CAMP to show the outline; `--target FILE` replaces it (run_demo.sh passes `~/.config/marine_simulation_demo/target.json` when present). Before #102 the publisher was off unless asked; the issue's acceptance ("scorer with the polygon published") makes it part of the demo. `--layout` / `--joysticks` default to the installed examples like the old launch; `run_demo.sh` still requires the machine's own files.
4. **`demo_manager.py` arguments.** Adds `--joysticks FILE`, `--layout FILE`, `--no-layout`, `--target FILE` (the boats group gains a `joystick_config` argument; the layout and target groups get theirs through new placeholders). Preflight before anything starts, each refusal printed as "THE DEMO DID NOT START: ..." and exit 2: the named files exist, `place_windows.py --check` passes when the effective profile has `layout`, no CAMP is already running when it has `camp` (the launch checks again at the group's start). The demo lock is taken as now.
5. **`run_demo.sh` runs the manager.** Same machine-file lookup, domain handling (`DEMO_ROS_DOMAIN_ID`, range check), layout check, CAMP-open check and "THE DEMO DID NOT START" messages; the arguments after it are the manager's (`--boats a,b`, `--no-joysticks`, `--no-layout`, `--profile ...`) instead of launch arguments, and it execs the manager script directly (not through the `ros2 run` wrapper, which would take signals meant for the manager). The manager already prints the refusal phrase on its own refusals; `exec` means nothing is printed twice.
6. **Delete.** `launch/demo_launch.py`, `test/test_demo_launch.py` (its helper tests move to `test_demo_support.py`), the CMake `test_demo_launch` registration. `demo_boats_selftest.py --demo` (which started `demo_launch.py`) starts `demo_manager.py --profile headless` instead. No opt-in path remains.
7. **Docs.** `marine_simulation/README.md`, `.agents/README.md` (layout tree, inventory line, key files, pitfalls: lock/settings text now about the manager, the new package, group semantics), the helper card (the README section helpers copy from).

## Steps (one atomic commit each)

1. Plan and progress record.
2. `roster.py`, `demo_support.py` and the package install; `demo_boats_launch.py`, `demo_launch.py`, `demo_camp_launch.py`, `demo_manager.py` import them; helper tests move to `test_demo_support.py`.
3. `manager_core`: neutral clean-exit detail and the run-once tests.
4. Target-area and layout launch files, the new groups and profiles, the manager's new arguments and preflight, their tests.
5. `run_demo.sh` starts the manager; `test_run_demo.py`; selftest `--demo` re-pointed.
6. Delete `demo_launch.py`, its start-path tests and registrations; no-load-by-path test.
7. Documentation.
8. Review rounds and their fixes (each its own commit).

## Tests

- `test_demo_support.py`: the moved helpers (profile, Qt encodings, reset guards, lock, scorer parameters, CAMP-running scan, placement exit message, `camp_actions` seeding); `roster` re-export identity test.
- `test_demo_manager.py`: group wiring (publisher and placement present; scorer requires the publisher; layout requires and follows camp, `restart: never`; publisher follows camp; profiles), the placeholders, argument handling and every preflight refusal, the two new launch files (nodes, parameters, arguments), the no-load-by-path scan.
- `test_manager_core.py` and `test_launch_manager.py` (real manager process, a run-once fixture): a clean exit of a run-once group is not a failure, stops nothing, can be started again; a non-zero exit fails only that group.
- `test_run_demo.py`: invokes the manager, passes the machine files as flags, keeps the domain / config / CAMP-open checks.
- `test_demo_boats_selftest.py`: `--demo` builds the manager command.
- Host-only `test_demo_manager_live.py` (headless profile): additionally asserts `target_area` and `scorer` READY. Not run here: CAMP and `place_windows` (no GUI).

## Consequences

| If we change... | Also update... | Included? |
|---|---|---|
| Helpers move to an installed Python package | `CMakeLists.txt`, `package.xml` (`ament_cmake_python`), `.agents/README.md` layout | Yes |
| `demo_launch.py` removed | README start section, `.agents/README.md` inventory / key files / pitfalls, selftest `--demo`, CMake tests | Yes |
| `run_demo.sh` arguments become manager flags | `test_run_demo.py`, README helper card | Yes |
| New groups in `demo_manager.yaml` | placeholder test, `.agents/README.md` parameter notes, README group table | Yes |

## Open items for the host's CAMP run

CAMP now opens the shipped demo polygon by default (it is also the published target); window placement and the real `CAMP` exit are only exercised there.

## Implementation Notes

- `ament_cmake_python` package `marine_simulation.roster` was added next to `demo_support` because `demo_boats_launch.py` (a launch file) held the roster functions the manager needs; it re-imports them.
- `place_windows.py` stays a script; the manager's preflight runs `place_windows.py --check` as a subprocess instead of importing it.
- `demo_boats_selftest.py --demo` now starts `demo_manager.py --profile headless`.
- Defaults changed on purpose: the publisher is always part of the demo and CAMP opens the same target file (installed demo polygon by default).
