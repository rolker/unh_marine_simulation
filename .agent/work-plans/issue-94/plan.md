# Plan: Demo: one launch for the whole display (boats, CAMP, scorer, target area) with a fixed window layout and a known CAMP state

## Issue

https://github.com/rolker/unh_marine_simulation/issues/94

## Context

The demo is four commands today (boats, CAMP, scorer, target area from #93). A non-technical helper must run it alone on Oct 23-24 with one command. Facts verified while planning:

- `camp_launch.py` starts the `CCOMAutonomousMissionPlanner` executable with only the `workspace/` directory as argument and exposes no launch arguments. CAMP's `main.cpp` accepts extra arguments: a `*.json` file is opened as a project, a directory sets the workspace, anything else is tried as a background. So the demo launch cannot pass CAMP a project file by including `camp_launch.py`.
- CAMP persists through `QSettings` (organisation `UNH-CCOMJHC`, application `CCOMAutonomousMissionPlanner`; on Linux an INI file at `$XDG_CONFIG_HOME/UNH-CCOMJHC/CCOMAutonomousMissionPlanner.conf`). Restored at start: `MainWindow/geometry`, `MainWindow/state`, `MainWindow/mapScale`, `MainWindow/mapCenter` (a scene-coordinate point, applied on the first event-loop turn), `MapView/mapView/{scale,center}`, `BackgroundTileLayers/*` (seeded to OpenStreetMap only on first run, sentinel `seeded`), `GggsTileLayers/dirs`, `GggsRasters/files`, `vectorLayers/files`, `backgrounds/files`, and per-layer `MapItem/<settingsKey>/{visible,opacity}`. The live coverage layer's key is `live:<sanitized source namespace>`; it defaults to `visible=false` and `live_enabled=false`, so a clean profile shows no live coverage. CAMP writes window/view state on close and layer state when it changes, so a normal session drifts the profile.
- Neither `wmctrl` nor `xdotool` is installed on the dev host (`which` finds neither; both are in Ubuntu, rosdep resolves `wmctrl` and `xdotool` to apt). The session is X11 with three monitors (`xrandr --listmonitors`: HDMI-0 3840x2160, DP-2 1920x1200, eDP-1-1 1920x1080).
- The scorer package has `coverage_assessment_launch.py` (configures at process start, activates once; arguments `namespace`, `params_file`). Its example yaml hard-codes the four boat names and `bluefin/map` frames. `demo_boats_launch.py` reads the roster, which README declares the only place boat names live.
- `demo_boats_launch.py` is not an importable package (tests load it by path with importlib); it already has the fail-fast helper functions and a selftest that starts it.

## Approach

1. **New launch `marine_simulation/launch/demo_launch.py`** — one entry point. Arguments: `boats`, `roster_file`, `joystick_config` (passed through to the boats launch), `layout_config`, `camp_profile`, `target_area_file`, and switches `enable_boats`, `enable_camp`, `enable_scorer`, `enable_target_area`, `enable_window_layout` (all `true` except `enable_target_area`, default `false` until #93 lands; each parsed with the boats launch's `parse_bool`). The switches make the launch testable headless and let the helper run a subset in an emergency.
2. **Boats**: `IncludeLaunchDescription` of `demo_boats_launch.py`, forwarding `boats`, `roster_file`, `joystick_config` and the existing optional arguments untouched. Nothing duplicated.
3. **Scorer**: in an `OpaqueFunction`, load the roster (reuse `load_roster`/`select_boats` by importlib-loading the sibling launch file, same pattern the tests use) and write a generated params file under the demo runtime directory from the installed `coverage_assessment.yaml` example: `grid_topics` and `source_names` from the selected boats, `map_frame`/`water_surface_frame`/`water_surface_boat_frame` from the first selected boat (`<boat>/map`, `<boat>/map_tide`, `<boat>/base_link`), `survey_area_topic` unchanged. Then include `coverage_assessment_launch.py` with `params_file:=<generated>` so its configure-once-then-activate logic is reused, not copied. No boat name appears in a new file.
4. **Target area (#93)**: #93 is being implemented in parallel as `scripts/publish_survey_area.py` in this package (node `survey_area_publisher`, root namespace, topic `/survey_area`, parameter `file` for the CAMP json, plus `standard_a`/`standard_b`/`standard_name`, `area_id`, `priority`); it has no launch file. Until it lands, `enable_target_area:=true` is refused with "not installed (comes with #93)" (the check is whether `lib/marine_simulation/publish_survey_area.py` exists); when it is installed the same switch adds a plain `Node(package='marine_simulation', executable='publish_survey_area.py', name='survey_area_publisher', parameters=[{'file': target_area_file}])`. `target_area_file` is also handed to CAMP (step 5) so one saved CAMP file serves the scorer and the outline. The default of `enable_target_area` and of `target_area_file` flips once #93 commits its demo polygon. This branch adds none of #93's files.
5. **CAMP with a known state**: the launch starts the CAMP executable directly (a `Node` with the same package/executable/`workspace/` argument as `camp_launch.py`, plus `target_area_file` as an extra `.json` argument when set) so it can set the environment; rolker/camp#240 asks for launch arguments on `camp_launch.py` so this copy can go. At launch time, in an `OpaqueFunction`, it (a) deletes and re-creates a runtime settings root `~/.local/state/marine_simulation_demo/xdg_config/` (not under `$XDG_RUNTIME_DIR`/`/tmp`); the delete is guarded: it refuses unless the path is exactly that directory under the home directory, is not a symlink and either is empty or carries the marker file the launch writes into it (Qt writes other files there, such as `QtProject.conf`, so "contains only UNH-CCOMJHC" would fail on the second start); a test covers a wrong path, a symlink, a stray file and a plain file; CAMP's live tile cache (kept outside the settings file) is moved to `<state>/live_tile_cache` through the generated profile (`LiveTileCache/cache_dir`) and reset by the same guard on every start, (b) writes the generated profile to `<root>/UNH-CCOMJHC/CCOMAutonomousMissionPlanner.conf`, (c) sets `XDG_CONFIG_HOME=<root>` for the CAMP process only (`additional_env`). The helper's real CAMP settings are untouched and every run starts from the same profile whatever the previous session did. Rejected alternatives: patching CAMP to take a `--settings` option (needs a camp change, unnecessary), and editing `~/.config` in place (destroys the owner's own CAMP state).
6. **The demo profile** is generated at launch from three inputs: the committed `config/demo_camp_profile.conf` (plain INI: OpenStreetMap as the only background, `seeded=true`, its presentation keys; it may not set `[MainWindow]` or `[MapView]`), `config/demo_camp_view.yaml` (`scale`, optional `lat`/`lon`; default centre is the mean of the selected boats' start positions) and the roster (one live coverage layer per boat: `MapItem/live%3A%252F<boat>%252Fsensors%252Fmbes%252Fcube_bathymetry/{live_enabled,visible}=true`, key pattern read from a real CAMP settings file; colormap and range stay CAMP's defaults). The map view is written as `MainWindow/mapCenter`+`mapScale` and `MapView/mapView/center`+`scale`, same values in both (MainWindow's deferred restore runs after the map view's own and wins by code reading). Reading `camp_map/map_view/web_mercator.cpp` showed the scene is Web Mercator metres, not session state, so the centre is computed from lat/lon with CAMP's own formula and encoded with `qt_point_variant`, which reproduces Qt's INI encoding of a `QPointF` and is pinned against Qt-written samples and (when PyQt5 is present) 300 random points. Window geometry and state are left unset (placement is step 7); panel arrangement is CAMP's default. Layers that ROS drives (platforms from `/marine/platforms`) need no settings. Nothing owner-specific is copied, so the planned `make_camp_profile.py` capture tool was dropped.
7. **Window placement** (`scripts/place_windows.py`, installed to `lib/marine_simulation`, started by the launch as an `ExecuteProcess` when `enable_window_layout` is true): reads a per-machine layout YAML (`config/demo_layout.yaml` ships an example showing CAMP full screen on the big display, the second display reserved for the scoreboard with nothing placed, and the one-display variant; the machine copy is passed as `layout_config:=`, like `demo_joysticks.yaml`). Entries give a window match (WM_CLASS and/or title substring), a monitor name as reported by `xrandr --listmonitors` (so a rect is relative to the monitor and survives a changed monitor arrangement), and either `fullscreen: true` or a `rect`. The script polls `wmctrl -lx` until each window appears (one bounded deadline for the whole layout, default 60 s), removes maximised/fullscreen state, moves it with `wmctrl -ir <id> -e 0,x,y,w,h` (and adds `fullscreen` where asked), then re-checks the geometry with `wmctrl -lG` and retries once, because CAMP resizes itself after first show. Windows are found by class/title and the newest match is used; `wmctrl -b` takes at most two properties, so full screen and maximised state are cleared by two calls with a pause before the move. Fail-fast, with the reason on screen: `place_windows.py --check` (session, tools, layout, monitors; used by `run_demo.sh`) and the launch itself run the same checks before starting anything (not an X11 session, `wmctrl` missing, malformed layout, a named monitor absent); a window that never appears is a loud problem line plus a non-zero exit, never silent. The monitor lookup and geometry maths are pure functions; the `wmctrl`/`xrandr` calls go through one injectable runner. Not run against a live desktop in this phase (no `wmctrl`; the owner's desktop is off limits).
8. **Dependencies**: `package.xml` gains `<exec_depend>coverage_assessment</exec_depend>`, `<exec_depend>wmctrl</exec_depend>` (rosdep key resolves to apt, per `.agent/knowledge/dependency_policy.md` case 1; no pip, no local key) and `<exec_depend>geographic_msgs</exec_depend>` (the selftest). `xdotool` is not added. The owner installs `wmctrl` with apt on this host; the README and the launch preflight name it.
9. **Helper entry point**: `scripts/run_demo.sh` (installed): sources `~/.config/marine_simulation_demo/env.bash` if present, requires `ros2` afterwards, sets a private `ROS_DOMAIN_ID` default (42, unless already set), requires `joysticks.yaml` and `layout.yaml` in that directory (the optional `target.json` is passed as `target_area_file`), and `exec`s the launch with any extra arguments. This is what "up arrow, enter" re-runs. Every refusal prints one "THE DEMO DID NOT START: ..." line in plain words and starts nothing; the layout is checked with `place_windows.py --check` first, an open CAMP stops the demo, `ROS_DOMAIN_ID` is always 42 (`DEMO_ROS_DOMAIN_ID` overrides), and `joysticks.yaml` / `layout.yaml` are only required when their feature is on.
10. **Tests** (pytest, matching the existing style): (a) pure functions: Qt value encoder against Qt-written samples, scorer params generation from a roster and from a `boats:=` subset, profile building and seeding (runtime dir recreated, state wiped, user config untouched, guarded delete), layout parsing and refusals, monitor-relative rectangle maths, wmctrl command sequence with a fake runner including the retry and the late window, `run_demo.sh` with a fake `ros2`; (b) launch-level: the description built with defaults contains the boats include, the CAMP node with `XDG_CONFIG_HOME` set, the scorer include; each `enable_*:=false` removes its part; `enable_target_area:=true` is refused until wired; (c) a runtime check added to `demo_boats_selftest.py` behind `--start-launch --demo`: with the demo launch started `enable_camp:=false enable_window_layout:=false enable_joysticks:=false`, the `coverage_assessment` lifecycle node reaches `active`; the selftest itself publishes a small `SurveyArea` (latched, transient_local, around the roster start poses) and checks that a `coverage_assessment` message arrives for it, so the check does not depend on #93. Registered in `CMakeLists.txt` like the existing tests; lint (ament) must pass.
11. **Docs**: `marine_simulation/README.md` gets a "Whole demo display" section: the one command, launch arguments table, per-machine files, the CAMP profile (what it fixes, how it is regenerated, how to draw a new target), the layout file, and the one-card helper checklist (what to type, what appears on which screen, replug a pad that does not drive, who to call; the phone number/name is left for the owner, see Open Questions). `.agents/README.md` gets the new launch, scripts and the pitfall that CAMP state is a seeded profile, not the user's config.
12. **Review round 1 additions** (2026-10-14): the launch refuses to start next to a running CAMP or under a second demo (flock on the state directory), checks and absolutises `target_area_file` whenever it is given, validates the view settings, and prints a banner when window placement exits non-zero.
13. **Closing CAMP stops the demo** (owner requirement added 2026-10-14, after review-plan): with `enable_camp` true, `OnProcessExit(target_action=<CAMP node>)` emits `Shutdown`, so closing the map window (or CAMP dying) stops the boats, the scorer and the placement process. Covered by a launch-level test that binds the handler to the CAMP action and checks the Shutdown event; documented as "to stop everything, close the map window" in the helper card.
14. **Rehearsal** (human, owner): cold boot on the dev laptop, run the one command, confirm every window on the right monitor, the CAMP view and layers, scorer active, pads driving. The result is recorded in the PR; an agent cannot run it. The placement process exiting normally must not stop the launch (use no `on_exit` shutdown handler); only a non-zero exit is logged loudly. Until it is done the issue's acceptance criterion is not met.

## Files to Change

| File | Change |
|------|--------|
| `marine_simulation/launch/demo_launch.py` | New whole-display launch (steps 1-7) |
| `marine_simulation/config/demo_camp_profile.conf` | Fixed part of the CAMP settings profile |
| `marine_simulation/config/demo_camp_view.yaml` | CAMP starting scale (and optional centre) |
| `marine_simulation/config/demo_layout.yaml` | Example per-machine window layout |
| `marine_simulation/scripts/place_windows.py` | X11 window placement via wmctrl |
| `marine_simulation/scripts/run_demo.sh` | Helper one-command wrapper |
| `marine_simulation/scripts/demo_boats_selftest.py` | `--demo`: launch the whole display, check the scorer |
| `marine_simulation/test/test_demo_launch.py`, `test_place_windows.py`, `test_run_demo.py`, `test_demo_boats_selftest.py` | New and extended tests |
| `marine_simulation/CMakeLists.txt` | Install new scripts, register tests |
| `marine_simulation/package.xml` | `coverage_assessment`, `wmctrl`, `geographic_msgs` exec_depends |
| `marine_simulation/README.md`, `.agents/README.md` | Docs (step 11) |

## Principles Self-Check

| Principle | Consideration |
|---|---|
| Human control and transparency | Preflight failures name the cause in plain words; the CAMP profile and layout are visible committed files; helper's own CAMP config untouched. |
| Enforcement over documentation | The one-command wrapper and fail-fast checks replace a checklist the helper could get wrong. |
| A change includes its consequences | README, `.agents/README.md`, `package.xml`, CMake install and tests are in the plan. |
| Capture decisions | Profile-via-`XDG_CONFIG_HOME` choice and rejected alternatives recorded here; no ADR (design still evolving). |
| Improve the system, not just the output | Reuses roster loading and the scorer's own launch; no duplicated boat names. |

## ADR Compliance

| ADR | Triggered | How addressed |
|---|---|---|
| 0008 follow ROS 2 conventions | Yes | Launch arguments, exec_depends, installed scripts under `lib/<pkg>`, ament lint. |
| 0009 Python package management | Yes | No pip; `wmctrl` via rosdep/apt, scripts use stdlib and `python3-yaml` already declared. |
| 0017 AGENTS.md in project repos | No | Existing `.agents/README.md` updated only. |
| 0018 local-first CI | Partly | Pre-push `ci_local` full-scope attestation is the merge gate; not run in this planning phase. |

## Consequences

| If we change... | Also update... | Included in plan? |
|---|---|---|
| New launch/scripts/config | `CMakeLists.txt` install, README, `.agents/README.md` | Yes |
| New exec_depends | `package.xml` | Yes |
| Boat names in scorer params | Roster stays single source | Yes (generated) |
| #93 lands | Flip `enable_target_area` default, replace stub | Yes (one follow-up edit after #93 merges) |
| CAMP-side gaps found (launch arguments, mapCenter reproducibility) | rolker/camp issue, referenced from the README | Conditional |

## Documentation & Instruction Impact

- **Stale docs** (must land in this PR): `marine_simulation/README.md` (four-launch workflow becomes one command; its "scorer is not part of the demo" statement in the cube README is on the cube side and noted for a cube follow-up), `.agents/README.md` (inventory, key files, pitfalls).
- **Agent-instruction candidates** (proposals only): CAMP persists all state through `QSettings` and `XDG_CONFIG_HOME` redirects it, so tests and demos can seed a known state without touching the user's config; may belong in `.agent/knowledge/` after a second use.

## Open Questions

Answered by the owner (via the coordinator) after review-plan; recorded here with how each landed:

- Helper-card contact: a clearly marked placeholder (`<NAME - OWNER TO FILL IN>`, `<PHONE - OWNER TO FILL IN>`) is in the README card. **Owner still has to fill it in.**
- Monitors: CAMP on the 4K screen, the second screen reserved for a later scoreboard with nothing placed there now; the shipped example layout shows both (and the one-display variant).
- Autostart: none; one typed command in a terminal.
- Reset between players: none.
- CAMP executable started directly from the demo launch; rolker/camp#240 asks for `camp_launch.py` launch arguments.
- Live coverage colormap and range: CAMP's defaults for now.
- #93's node: `scripts/publish_survey_area.py`, node `survey_area_publisher`, parameter `file` (step 4); this branch does not add its files.
- `wmctrl`: the owner installs it with apt; live placement checks stay "not run" until then.

Still open for the owner:

- The starting `scale` in `config/demo_camp_view.yaml` is a guess (1.0); tune at the rehearsal.
- Confirm at the rehearsal that CAMP's WM_CLASS contains `CCOMAutonomousMissionPlanner` (`wmctrl -lx`) and that the live layer key pattern matches the graph.
- The `enable_target_area` / `target_area_file` defaults flip once #93 lands and commits its demo polygon.

## Implementation Notes

- 2026-10-14, owner requirement (arrived during implementation): closing the CAMP window must shut the whole launch down (step 13).
- The CAMP centre may shift when the window is made full screen after CAMP has applied it (found in review round 1 by reading the camp source; rolker/camp#242). Not fixable here; the README makes it a rehearsal check.
- The profile is generated rather than captured: CAMP's scene is Web Mercator metres, so the view centre is exact and reproducible, and the live layer keys come from the roster. This replaced the planned `make_camp_profile.py` capture tool.
- The settings-directory delete guard uses a marker file instead of "contains only UNH-CCOMJHC", because Qt writes other files into `XDG_CONFIG_HOME`.
- The launch loads `demo_boats_launch.py` and `place_windows.py` by path (a launch file is not an importable module), the same way the existing tests do.

## Estimated Scope

Single PR (about 12 files; if it grows, split window placement and the CAMP profile from the launch), plus a human rehearsal before the issue can close. The PR body uses "Part of #94" unless the rehearsal has been done, because the issue's acceptance test is the cold-boot rehearsal.
