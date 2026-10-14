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
4. **Target area (#93)**: until it lands, `enable_target_area:=true` is refused with "not available yet" unless `target_area_launch` points at an include-able launch file; when #93 merges, the include replaces the stub, its file argument is `target_area_file`, and the default flips to `true`. `target_area_file` is also handed to CAMP (step 5) so one saved CAMP file serves the scorer and the outline. The branch for #94 is built on `jazzy`; it must not touch #93's files.
5. **CAMP with a known state**: the launch starts the CAMP executable directly (a `Node` with the same package/executable/`workspace/` argument as `camp_launch.py`, plus `target_area_file` as an extra `.json` argument when set) so it can set the environment. At launch time, in an `OpaqueFunction`, it (a) deletes and re-creates a runtime settings root `~/.local/state/marine_simulation_demo/xdg_config/` (not under `$XDG_RUNTIME_DIR`/`/tmp`), (b) copies the committed demo profile `config/demo_camp_profile.conf` to `<root>/UNH-CCOMJHC/CCOMAutonomousMissionPlanner.conf`, (c) sets `XDG_CONFIG_HOME=<root>` for the CAMP process only (`additional_env`). The helper's real CAMP settings are untouched and every run starts from the same profile whatever the previous session did. Rejected alternatives: patching CAMP to take a `--settings` option (needs a camp change, unnecessary), and editing `~/.config` in place (destroys the owner's own CAMP state).
6. **The demo profile** (`config/demo_camp_profile.conf`, plain INI, committed, no binary window blobs): `BackgroundTileLayers` = OpenStreetMap only with `seeded=true`; `GggsTileLayers/dirs`, `GggsRasters/files`, `vectorLayers/files`, `backgrounds/files` empty so no stray overlays from a machine's own history; `MainWindow/mapScale` and `MainWindow/mapCenter` set to Portsmouth Harbour mouth; `MapItem/<live key>/visible=true` and `live_enabled=true` with `colormap` and a manual range chosen for the demo depths; `MapItem/<openstreetmap key>/visible=true`. `MainWindow/geometry` and `state` are left unset (the window manager placement in step 7 decides size and position); dock/panel layout is then CAMP's default, which is acceptable and noted. The profile is produced by capturing a rehearsed CAMP session (tool-assisted: a script `scripts/make_camp_profile.py` extracts only an allow-list of key groups from a given CAMP `.conf` and writes the committed file, so regenerating it is repeatable and it never copies the owner's paths). The scene-coordinate `mapCenter` is the one value to check empirically: restart CAMP twice from the profile and confirm the same view; if the scene origin depends on session state, record that as a gap and file it in rolker/camp rather than papering over it. The live source namespace key (`live:<ns>`) is read from the capture (first live run), not guessed. Layers that ROS drives (platforms from `/marine/platforms`, live coverage tiles) restore their own visibility from the profile; anything found not restored on a cold start is documented in the README known limits or filed in rolker/camp.
7. **Window placement** (`scripts/place_windows.py`, installed to `lib/marine_simulation`, started by the launch as an `ExecuteProcess` when `enable_window_layout` is true): reads a per-machine layout YAML (`config/demo_layout.yaml` ships a generic example; the machine copy is passed as `layout_config:=`, like `demo_joysticks.yaml`). Entries give a window match (WM_CLASS or title substring), a monitor name as reported by `xrandr --listmonitors` (so a rect is relative to the monitor and survives a changed monitor arrangement), an offset/size or `fullscreen: true`. The script polls `wmctrl -lx` until each window appears (bounded timeout, default 60 s), removes maximised/fullscreen state, moves it with `wmctrl -ir <id> -e 0,x,y,w,h` (and adds `fullscreen` where asked), then re-checks the geometry with `wmctrl -lG` and retries once, because CAMP resizes itself after first show. Fail-fast, with the reason on screen: not an X11 session (`XDG_SESSION_TYPE` is not `x11`), `wmctrl` missing, a named monitor absent, malformed layout. A window that never appears is a loud warning plus a non-zero exit, never silent. The monitor lookup and geometry maths are pure functions; the `wmctrl`/`xrandr` calls go through one injectable runner.
8. **Dependencies**: `package.xml` gains `<exec_depend>coverage_assessment</exec_depend>` and `<exec_depend>wmctrl</exec_depend>` (rosdep key resolves to apt, per `.agent/knowledge/dependency_policy.md` case 1; no pip, no local key). `xdotool` is not added. The host installs it with `rosdep install` or `sudo apt install wmctrl`; the README notes it and the launch's preflight names it if missing.
9. **Helper entry point**: `scripts/run_demo.sh` (installed): sets a private `ROS_DOMAIN_ID` default, sources the workspace overlay it is told about, finds the machine files in `~/.config/marine_simulation_demo/{joysticks,layout}.yaml`, and `exec`s the launch. This is what "up arrow, enter" re-runs. Preflight failures print a one-line plain-language message.
10. **Tests** (pytest, matching the existing style): (a) pure functions: scorer params generation from a roster and from a `boats:=` subset, profile seeding (runtime dir recreated, file copied, existing state wiped, user config untouched), layout parsing and refusals, monitor-relative rectangle maths, wmctrl command sequence with a fake runner including the retry; (b) launch-level: the description built with defaults contains the boats include, the CAMP node with `XDG_CONFIG_HOME` set, the scorer include and the placement process; each `enable_*:=false` removes its part; `enable_target_area:=true` is refused until wired; (c) a runtime check added to `demo_boats_selftest.py` behind a flag: with the demo launch started `enable_camp:=false enable_window_layout:=false enable_joysticks:=false`, the `coverage_assessment` lifecycle node reaches `active` and publishes a `coverage_assessment` once a latched area exists (or logs that none yet). Registered in `CMakeLists.txt` like the existing tests; lint (ament) must pass.
11. **Docs**: `marine_simulation/README.md` gets a "Whole demo display" section: the one command, launch arguments table, per-machine files, the CAMP profile (what it fixes, how it is regenerated, how to draw a new target), the layout file, and the one-card helper checklist (what to type, what appears on which screen, replug a pad that does not drive, who to call; the phone number/name is left for the owner, see Open Questions). `.agents/README.md` gets the new launch, scripts and the pitfall that CAMP state is a seeded profile, not the user's config.
12. **Rehearsal** (human, owner): cold boot on the dev laptop, run the one command, confirm every window on the right monitor, the CAMP view and layers, scorer active, pads driving. The result is recorded in the PR; an agent cannot run it. Until it is done the issue's acceptance criterion is not met.

## Files to Change

| File | Change |
|------|--------|
| `marine_simulation/launch/demo_launch.py` | New whole-display launch (steps 1-7) |
| `marine_simulation/config/demo_camp_profile.conf` | Committed CAMP settings profile |
| `marine_simulation/config/demo_layout.yaml` | Example per-machine window layout |
| `marine_simulation/scripts/place_windows.py` | X11 window placement via wmctrl |
| `marine_simulation/scripts/make_camp_profile.py` | Extract an allow-listed profile from a captured CAMP `.conf` |
| `marine_simulation/scripts/run_demo.sh` | Helper one-command wrapper |
| `marine_simulation/scripts/demo_boats_selftest.py` | Optional scorer-active check |
| `marine_simulation/test/test_demo_launch.py`, `test_place_windows.py`, `test_make_camp_profile.py` | New tests |
| `marine_simulation/CMakeLists.txt` | Install new scripts, register tests |
| `marine_simulation/package.xml` | `coverage_assessment`, `wmctrl` exec_depends |
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

- Who is the "who to call" contact and number on the helper card?
- Which monitor holds what on the event machine (CAMP on the 4K screen is assumed; is a second screen used for anything, e.g. the scoreboard later)?
- Should the demo start automatically at login or stay "type one command in a terminal" (the issue says the latter)?
- Should the demo launch also reset CUBE/scorer state between player changes (rounds were dropped, so this plan does not)?
- OK to start the CAMP executable directly (and file a camp issue for launch arguments) rather than wait for `camp_launch.py` to grow them?
- Which live coverage colormap and range for the demo depths (the plan takes the CAMP default until the owner picks)?
- Which `#93` launch/node name and file argument will it expose (the stub assumes a launch file path)?

## Estimated Scope

Single PR (about 12 files), plus a human rehearsal before the issue can close.
