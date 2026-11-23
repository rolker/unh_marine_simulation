# Plan: Build on ROS 2 Rolling: port asv_sim_msgs, asv_helm, asv_sim and mbes_sim, and add CI

## Issue

https://github.com/rolker/unh_marine_simulation/issues/119 (part of rolker/unh_marine_autonomy#415; #120 follows and is not planned here)

## Context

Four packages of nine are ported. The five others (`marine_simulation`, `launch_manager_proto`, `marine_charts_to_gazebo_world`, `portsmouth_nh_gazebo`, `vrx_project11`) stay as they are, and **no colcon command runs without a package selector**. Work goes to a new PR into `rolling` (origin `rolling` = `423ff56` = `jazzy`), then a hand backport to `jazzy`.

**Baseline, measured** (worktree `build.sh --continue-on-error --packages-up-to asv_sim_msgs asv_helm asv_sim mbes_sim`, then `test.sh --packages-select` what built; Rolling, Python 3.14, setuptools 78.1):

| Package | First diagnostic | Python tests run |
|---|---|---|
| `asv_helm` | build fails, `CMakeLists.txt:20`: `Unknown CMake command "ament_target_dependencies".` | none (no tests; not built) |
| `asv_sim_msgs` | builds; `xmllint` fails: `package.xml:20: Element 'test_depend': This element is not expected. Expected is one of ( member_of_group, export ).` | none |
| `asv_sim` | builds, stderr `Unknown distribution option: 'tests_require'`; test exits 5: `Ran 0 tests ... NO TESTS RAN` | **0** |
| `mbes_sim` | the same two lines | **0** |

Behind each, on a scratch copy outside the repository (fixes applied one at a time, all deleted afterwards): the `asv_helm` link line is the only build failure; with the `setup.py` fix **163 `asv_sim` tests (1 skipped) and 84 `mbes_sim` tests run**, and then the first remaining failure is `asv_sim/test/test_flake8.py`: `./asv_sim/platform.py:1:2: A005 the module is shadowing a Python builtin module "platform"`. With all fixes below: `Summary: 251 tests, 0 errors, 0 failures, 1 skipped` (the skip is `test_copyright.py`, marked skip in the repository).

**Repeated runs on the finished scratch copy** (own `ROS_DOMAIN_ID` 151 to 220, 12 processes at once on a 20-core machine, `pytest -x`): `asv_sim` whole suite 20 of 20 passed (162 passed, 1 skipped each), `mbes_sim` whole suite 20 of 20 (84 each); as separate processes 50 of 50 each for `test_multi_platform.py` (35 tests), `test_collision.py` (54), `test_dynamics_stability.py` (29), `test_tide_model.py` (10) and `test_tide_integration.py` (1, the launch-testing file, which pytest does run here). **No intermittent failure in 290 runs.** Not covered: a Jazzy machine, the `launch_test` runner (the file ran through pytest), a slower shared CI runner (these tests use the wall clock; first CI runs will show whether they hold up).

> **Corrected 2026-11-23 (plan review findings 1 and 2).** `test_tide_integration.py` runs under pytest and `colcon test` only because released `launch_testing` (Rolling 3.10.3, Jazzy 3.4.13) has a `tryfirst` `pytest_ignore_collect` hook that returns `False` and so overrides `collect_ignore = ['test_tide_integration.py']` in `asv_sim/test/conftest.py`. ros2/launch#1048 fixes that (merged, not yet released on either distro); after the next sync the `asv_sim` count drops from 163 to 162 and that test runs nowhere in CI (an `ament_python` package registers no `launch_test`); the guard does not notice (the count stays above 0). Which tests depend on time: `test_dynamics_stability`, `test_tide_model` and `test_collision` drive the model with explicit timestamps (no wall clock, no messaging); `test_multi_platform` is wall-clock (8 s, 6 s and 18 s drives on `time.monotonic`) but in one process with one executor; `test_tide_integration` is the fragile one (a launched process, cross-process DDS discovery, a 5 s collection window that starts at `ReadyToTest`, more than 5 messages and a 0.5 m range needed). No test sets `ROS_DOMAIN_ID`.

## Owner's decision on the lint failure (2026-11-23)

Shown both remedies (a file-level `# flake8: noqa: A005`, or renaming the module), asked "How should the port deal with the `platform.py` lint failure?", the owner answered: **"Rename the module"**.

## Approach (commits on the feature branch; one fix per commit; each names its #415 cause in the message)

1. **Cause 1, `asv_helm/CMakeLists.txt`** *(backport; with step 2)* — add `find_package(rclcpp_lifecycle REQUIRED)` and `find_package(std_msgs REQUIRED)`; replace line 20 with `target_link_libraries(${PROJECT_NAME} ${geometry_msgs_TARGETS} ${nav_msgs_TARGETS} ${marine_interfaces_TARGETS} ${std_msgs_TARGETS} marine_autonomy::marine_autonomy rclcpp::rclcpp rclcpp_lifecycle::rclcpp_lifecycle)`. The message targets and `rclcpp_lifecycle` are there because `asv_helm_node.cpp` and `marine_autonomy/pid.h` include their headers and `marine_autonomy::marine_autonomy` does not carry the message targets. The same form is in `helm_manager` (`rolker/unh_marine_autonomy`, read on `origin/jazzy` and `rolling`), and `marine_autonomy::marine_autonomy` is linked by six store packages on `rolling`. Scratch: builds, binary starts, its `NEEDED` libraries are rclcpp, rclcpp_lifecycle and the four message typesupports.
2. **Cause 11, `asv_helm/package.xml`** *(backport; travels with 1)* — `<depend>rclcpp_lifecycle</depend>`, `<depend>std_msgs</depend>`.
3. **Cause 4, `asv_sim/setup.py:30` and `mbes_sim/setup.py:13`** *(backport)* — `extras_require={'test': ['pytest']}` in place of `tests_require=['pytest']`.
4. **Cause 9, `asv_sim_msgs/package.xml`** *(backport)* — move the two `<test_depend>` lines above `<member_of_group>`. `ament_xmllint` passes on all four packages afterwards.
5. **Cause 11, `mbes_sim/package.xml`** *(backport)* — `<depend>std_msgs</depend>` (`mbes_sim.py:16-18`); `<exec_depend>` `launch`, `launch_ros`, `lifecycle_msgs` (`launch/mbes_sim_launch.py:1-8`).
6. **Cause 11, `asv_sim/package.xml`** *(backport)* — `<depend>rcl_interfaces</depend>`; `<exec_depend>` `launch_xml`, `launch_ros` (`launch/*_launch.xml`); `<test_depend>` `python3-yaml` (`test_multi_platform.py:31`), `launch` (`test_tide_integration.py:16`). `asv_sim_msgs` needs nothing more (declared set equals `CMakeLists.txt`). Left undeclared on purpose: `catkin_pkg` (`doc/conf.py`, documentation build only).
7. **The rename** *(backport; see below)*.
8. **CI** *(backport)* — `.github/workflows/ci.yml`, tested draft in `ci.yml.draft` next to this plan.
9. **Docs** *(backport)* — `.agents/README.md`: name the workflow (Build & Test, layout tree).

All keys were run through `rosdep keys` / `rosdep resolve` for jazzy/noble and rolling/resolute (cache of 2026-11-10): the 41 keys of the six-package closure all resolve, 0 unresolved, for each distro. `code-fixes.patch` is the scratch run's steps 1 to 7 and 9 as `git format-patch` (subjects provisional; use it to see the exact text, not to apply blindly).

### The rename (step 7), its own commit, `git mv`

`asv_sim/asv_sim/platform.py` becomes **`asv_sim/asv_sim/sim_platform.py`**: the module holds `Platform`, the simulated vehicle platform (publishers, services, noise, per-vehicle state), and `sim_platform` is in neither `sys.stdlib_module_names` of Python 3.14 here nor any 3.12 name (3.12's list is a subset of 3.14's plus modules removed in 3.13, none of them named so); Rolling's `test_flake8` then passes. Git records it as a 100 percent rename. Files touched: `asv_sim/asv_sim/asv_sim_node.py` (line 12 `import asv_sim.sim_platform`, line 41 `asv_sim.sim_platform.Platform(...)`), `asv_sim/config/bizzyboat.yaml:10` and `asv_sim/config/environment.yaml:16` (comments), `.agents/README.md:24` (module list; its `Platform` class mentions stay). **No class, function or symbol name changes**; entry point `asv_sim = asv_sim.asv_sim_node:main`, ROS names and parameters are unchanged. A search of this repository, `/home/roland/project11/rolling/*/src` and the other worktrees finds no other import of `asv_sim.platform`. Historical records under `.agent/work-plans/` that say `platform.py` are not edited. No remote branch touches the file (checked `git branch -r --no-merged origin/jazzy`). **For the PR text:** the file was renamed from `asv_sim/asv_sim/platform.py` to `asv_sim/asv_sim/sim_platform.py`; pending work (the demo import) that edits `platform.py` must be re-applied to the new path (`git cherry-pick` follows the rename for a clean base; a patch needs `--directory`/hand edit). *(Corrected 2026-11-23, plan review finding 3: `--directory` only prepends a path and cannot map `platform.py` to `sim_platform.py`; carry pending work with `git cherry-pick` or `git am -3`, which follow the rename; plain `git am` fails.)*

## Jazzy facts, by reading (nothing was run on Jazzy; this machine has Rolling only)

- `${<msgs>_TARGETS}`: `ament_cmake_export_targets-extras.cmake.in` on `jazzy` sets `<pkg>_TARGETS`; `rosidl_generate_interfaces.cmake` on `jazzy` calls `ament_export_targets` (line 161). `rclcpp::rclcpp` and `rclcpp_lifecycle::rclcpp_lifecycle` are used on `origin/jazzy` by `helm_manager`; `marine_autonomy::marine_autonomy` exists there (ALIAS at line 25, `ament_export_targets` at line 59 of `marine_autonomy/CMakeLists.txt`).
- `extras_require={'test': [...]}`: `colcon-core` 0.15.2 (noble) maps `extras_require.test` to test dependencies (`package_augmentation/python.py`); noble's setuptools is 68.1.2, which accepts it. *(Corrected 2026-11-23, plan review finding 5: the CI container gets `python3-colcon-core` with `ros-dev-tools` from packages.ros.org, not Ubuntu's 0.15.2; both 0.15.2 and the 0.21.3 here map `extras_require` `test`, so the conclusion holds.)* `marine_control`'s Jazzy CI is green with the same form (#415).
- rclpy (`jazzy`, 7.1.13) has everything the four packages use that could differ: `Node.add_on_set_parameters_callback` and `add_post_set_parameters_callback`, `rclpy.lifecycle.Node/State/LifecyclePublisher/TransitionCallbackReturn`, `create_lifecycle_publisher`, `rclpy.executors.ExternalShutdownException`, `rclpy.constants.S_TO_NS`, `rclpy.time.Duration`. No `logger.warn` in the four packages (cause 5 absent).
- Lint: `ament_flake8` 0.17.5 (Jazzy) and 0.21.4 (Rolling) ship the same `ament_flake8.ini`. **A005 first appears in `flake8-builtins` 2.3.0 (2024-03-29); noble has 2.1.0-1, so Jazzy's `test_flake8` never raised it and the rename is parity, not a Jazzy fix**; Rolling has 3.1.0. Other plugins differ (noble: flake8 7.0.0, import-order 0.18.2, comprehensions 3.14.0; Rolling: 7.3.0, 0.19.2, 3.17.0): code that passes the newer set could in theory fail an older one; only the Jazzy job shows it. `ament_pep257` is 0.17.5 on `jazzy` and 0.21.4 here; pydocstyle is 6.3.0 on noble and on this machine. `test_copyright.py` is skipped.
- Jazzy's CMake and the repository's `cmake_minimum_required` need no change.

## CI (steps 8 and 9)

One file `.github/workflows/ci.yml`, the same on both branches, triggers `push` and `pull_request` on `[rolling, jazzy]`; jobs `jazzy` (`ros:jazzy-ros-core`) and `rolling` (`ros:rolling-ros-core`, `if: (github.base_ref || github.ref_name) != 'jazzy'`), shaped like `mru_transform`'s. Per job: apt and `ros-dev-tools git`; checkout; rosdep init and update; workspace `../ws/src` with the checkout symlinked; sparse clone of `rolker/unh_marine_autonomy` (branch = distro, `sparse-checkout set marine_autonomy marine_interfaces`); `rosdep install --ignore-src -y --from-paths $(colcon list --base-paths src --paths-only --packages-up-to asv_sim_msgs asv_helm asv_sim mbes_sim)` without `-r`, list checked non-empty; `colcon build --packages-up-to` the four; `colcon test --packages-select` the four, `--return-code-on-test-failure`, no `install/setup.bash` sourced; `colcon test-result --verbose`; every build and test step `shell: bash` with `source /opt/ros/<distro>/setup.bash`. **No `geodesy` and no `geographic_info` clone** (the issue text is wrong on this): `marine_autonomy`, `marine_interfaces` and the four packages mention neither in any CMake, `package.xml` or source file; the closure is six packages and builds without it.

**Test-count guard**, step "Python tests ran" (`if: always()`): reads `build/asv_sim/pytest.xml` and `build/mbes_sim/pytest.xml` (colcon writes them only when it runs pytest), sums `tests` and `skipped` over the `testsuite` elements, and fails if a file is missing, unparsable or `tests - skipped <= 0`. *(Corrected 2026-11-23, plan review finding 4: it also sums `errors` and fails if `tests - skipped - errors <= 0`, because colcon writes a placeholder `pytest.xml` with `tests="1" errors="1"` before pytest runs.)* Tried on the scratch copy: normal run prints `asv_sim ... 163 tests, 1 skipped` and `mbes_sim ... 84 tests, 0 skipped`, exit 0; with `tests_require` put back in both `setup.py` files the job fails twice, at "Test" (colcon exits 5, `NO TESTS RAN`; so on Rolling the test step already fails without the guard) and at the guard, which names the missing file; with no `build` folder it fails. The guard's value is the named cause and the case of pytest running but collecting nothing.

**Rehearsal of the Rolling job**, `env -i` (only `HOME`, `PATH=/usr/bin:/bin`, `ROS_DOMAIN_ID=199` and the image's `ROS_DISTRO/ROS_VERSION/ROS_PYTHON_VERSION`), `/opt/ros/rolling/setup.bash` sourced only inside the build and test steps, the workflow's own `run:` blocks executed from the YAML, workspace laid out as the workflow lays it (`work/repo`, `work/ws/src/unh_marine_simulation`, sparse clone from GitHub `rolling`): every step rc=0, build 24 s (6 packages), test 150 s, `Summary: 251 tests, 0 errors, 0 failures, 1 skipped`. Not rehearsable here: apt, `rosdep init/update`, the container, and the real `rosdep install` (run as `--simulate`; everything was already installed, so resolution was checked separately, above). The Jazzy job could not be run at all. **Estimates, not measured on GitHub**: about 7 to 10 minutes per job (image pull, apt and `ros-dev-tools` 1 to 2 min, rosdep with `python3-gdal` and numpy 2 to 3 min, build under 1 min, tests 3 min because `asv_sim`'s node tests run on the wall clock); the two jobs run in parallel.

## Left alone and tracked (one follow-up issue; owner's rule: a port makes no big changes)

- `asv_helm/CMakeLists.txt:1` `cmake_minimum_required(VERSION 3.5.1)` and `asv_sim_msgs/CMakeLists.txt:1` (3.8): CMake 4.2 deprecation warning for both.
- The velocity block of `sim_platform.py` (formerly `platform.py`): east and north components in a message stamped with `mru_frame`. The owner is checking it; **no change and no test of either reading here.**
- The five unported packages; `asv_sim/doc/*.rst` (lists modules that do not exist, `coastal_surveyor`, `cw4`, and no `sim_platform`) and `doc/conf.py` importing undeclared `catkin_pkg`; `mbes_sim/package.xml` declares `geographic_msgs` that no source uses; `asv_sim_msgs/package.xml` description is still "TODO: Package description"; `asv_helm` and `mbes_sim` are package format 2 with license `BSD`; `asv_sim/test/test_copyright.py` is skipped; `asv_helm` and `asv_sim_msgs` have no unit tests; `.pre-commit-config.yaml` pins `flake8-builtins==2.1.0` and `.flake8` is not read by `ament_flake8`, so pre-commit cannot see what Rolling's `test_flake8` sees.

## Backport to `jazzy` (by hand, `git cherry-pick -x`, in this order)

Steps 1 to 9, all of them: the workflow is carried by both branches (the Rolling job skips itself on `jazzy`); the issue's `.agent/work-plans/issue-119/` records stay on `rolling` only. Together: **1 with 2** (the CMake `find_package` lines need the declared keys), **3 before relying on the guard** (the guard is step 8), and **8 with 9**. `jazzy` is `423ff56`, the base of this branch, so nothing diverges unless work lands on `jazzy` first. The rename (step 7) cherry-picks cleanly on a 100 percent rename; if `platform.py` was edited on `jazzy` meanwhile, git's rename detection carries the edit across, but a patch made from another branch will not. Step 7 is not needed on Jazzy to pass lint (noble's plugin has no A005); it is backported so the module has one name on both branches.

## What this code is for, and what is not verified

The four packages are the simulator, not vehicle software: `asv_sim` is the vehicle model and its sensors and `asv_sim_msgs` its services and messages, `mbes_sim` the simulated multibeam, `asv_helm` turns helm or velocity commands into throttle and rudder for the simulated vehicle. Depending on them: the multi-boat demo in `marine_simulation`, the reduced simulator of #120 (this issue's reason to exist), and developers' sim runs. Behaviour-neutral argument per change: 1 changes how the same libraries and include directories are named (the binary links the same message typesupports, starts, runs until killed); 2, 5, 6 only add dependency declarations (rosdep and build order, no code); 3 changes test discovery only; 4 reorders XML; 7 renames a module with no symbol changes and one importer. **Not verified**: no simulator run and no helm command driven through `asv_helm` (#120 does that); nothing was run on Jazzy locally; the GitHub jobs have not run (the PR's own Jazzy job, which builds the `rolling` branch's code on Jazzy, is the first Jazzy evidence, and the PR should say so).

## Principles Self-Check

| Principle | Consideration |
|---|---|
| A change includes its consequences | Rename updates its two comments and the agent guide in the same commit; CI is named in the guide. |
| Only what's needed | No `geodesy`; nothing beyond the causes and the rename; the rest is tracked. |
| Test what breaks | The guard makes "no Python test ran" a named failure. |
| Verify before claiming | Baseline, scratch results, rehearsal and 290 repeats are measured; Jazzy and the GitHub jobs are stated as unrun. |
| Name the rule before bending it | A005 named; owner's choice quoted. |

## ADR Compliance

| ADR | Triggered | How addressed |
|---|---|---|
| 0013 progress entries | Yes | `## Plan Authored` appended through the persistence step. |
| 0002 worktree isolation | Yes | Work in the issue's worktree; scratch outside it, deleted. |
| 0004, 0005 enforcement | Yes | The first workflow is the authority over local checks. |

## Serves / Design Picture

Serves: none recorded (no goals or design document in this repository); the work serves #415 and #120. No change to the design picture.

## Consequences

| If we change... | Also update... | Included? |
|---|---|---|
| `platform.py` name | `asv_sim_node.py`, two YAML comments, `.agents/README.md` | Yes |
| Workflow | `.agents/README.md` (Build & Test, layout) | Yes |
| Any of this on `rolling` | `jazzy` by hand | Yes, listed above |

## Open Questions

- Backport the rename to `jazzy` (recommended, one module name on both branches) or keep it Rolling-only (not needed for Jazzy lint)?
- Whether to add `workflow_dispatch` or a repeat-run job for the wall-clock tests if CI shows flakiness (recommended: wait for the first runs, no change now).

## Estimated Scope

One PR into `rolling` (`Part of #119`; the owner closes the issue after the backport): about 9 commits plus these records. PR text must say: what each commit fixes and its #415 cause; the rename (old name `asv_sim/asv_sim/platform.py`, new name `asv_sim/asv_sim/sim_platform.py`, no symbol change, re-apply pending edits to the new path); that no simulator run was made and nothing was run on Jazzy locally; the counts (251 tests, 0 failures, 1 skipped; Python tests 163 and 84 against 0 before); the repeat-run result; what is left alone, with the follow-up issue.
