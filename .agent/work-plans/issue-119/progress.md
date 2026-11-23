---
issue: 119
---

# Issue #119 — Build on ROS 2 Rolling: port asv_sim_msgs, asv_helm, asv_sim and mbes_sim, and add CI

## Issue Review
**Status**: complete
**When**: 2026-11-23 12:18 -05:00
**By**: Claude Code Agent (claude-sonnet-5-5)

**Issue**: #119

### Scope Assessment

**Well-scoped?** Yes. Four small packages, one fix per cause, CI in separate commits; the "not in scope" list and the left-alone list are explicit. The cause list is incomplete in one place (cause 11, below) and wrong in one place (the `geodesy` statement in the CI section); both change what the issue asks for, in the direction of exactly the four packages' needs.
**Right repo?** Yes. Every file named is in this repository; the fixes need nothing from other repositories, which are already ported (`marine_autonomy` and `marine_interfaces` on `rolling` and `jazzy`).
**Serves**: none. This repository records no goals and has no design document. The work serves rolker/unh_marine_autonomy#415 (the Rolling port) and the reduced simulator of #120.
**Design picture?** No change. No design document exists here; nothing changes how the parts fit.
**Dependencies**: none open. #120 waits for this issue. #415 lists the causes.

### What the cause list missed or got wrong

Checked against the source at `423ff56` (read only; nothing built).

1. **Cause 11, the only complete list I can give** (declared versus imported or included). Keys resolve with rosdep on noble and resolute for `python3-transforms3d`, `python3-gdal`, `python3-yaml`, `python3-numpy` and for the ROS keys below (`marine_acoustic_msgs`, `sensor_msgs_py`, `lifecycle_msgs`, `launch_ros`, `tf_transformations`), read from the local rosdep cache for jazzy and rolling.
   - `asv_helm/package.xml` (format 2): `src/asv_helm_node.cpp:7-9` includes `rclcpp_lifecycle` and `std_msgs`, neither declared. `geometry_msgs`, `nav_msgs`, `marine_interfaces`, `marine_autonomy`, `rclcpp` are declared and used.
   - `mbes_sim/package.xml`: `mbes_sim/mbes_sim.py:16-18` imports `std_msgs` (undeclared); `launch/mbes_sim_launch.py:1-8` imports `launch`, `launch_ros` and `lifecycle_msgs` (undeclared; they need `exec_depend`). `geographic_msgs` is declared and not used by any source (harmless). `python3-gdal` is declared as `depend`; `marine_autonomy` (imported at `mbes_sim.py:24`) is declared.
   - `asv_sim/package.xml`: `test/test_multi_platform.py:31` imports `yaml` (no `python3-yaml` test_depend); `rcl_interfaces` is imported in `environment.py`, `model.py`, `platform.py`, `asv_sim_node.py` and not declared (comes with `rclpy`; low risk); `launch/*_launch.xml` need `launch_xml` and `launch_ros` at run time (undeclared); `launch` is used by the tests and only `launch_testing`, `launch_ros` are declared. `python3-transforms3d` is declared as `depend` and `python3-gdal` as `exec_depend` (`charts.py` and `collision.py` import `osgeo` lazily): both are right and both resolve on noble and resolute. `doc/conf.py` imports `catkin_pkg` (documentation build only, not declared; leave alone).
   - `asv_sim_msgs/package.xml`: its declared set matches `CMakeLists.txt`; only the element order (cause 9) is wrong.
2. **Cause 5 (`logger.warn`)**: none in these four packages. Only `.warning` is used (`asv_sim/dynamics.py:237`, `asv_sim/collision.py:634`). I found no other removed rclpy API: `mbes_sim` uses `rclpy.lifecycle.Node`, `create_lifecycle_publisher`, `LifecyclePublisher`, `TransitionCallbackReturn`, all present on Rolling. (Not run on Jazzy; imports read only.)
3. **The CI section is wrong about `geodesy`.** `marine_autonomy` does not need it: `marine_autonomy/package.xml` and `CMakeLists.txt` never mention `geodesy` (a search of `marine_autonomy` and `marine_interfaces` finds no use), and neither do the four packages (`asv_sim` has its own `geodesic.py`). In rolker/unh_marine_autonomy's workflow `geodesy` is built for `marine_sidescan_mosaic`, `marine_survey_index` and `bathymetry_layer`, which these packages do not need. What `marine_autonomy` needs from source is only `marine_interfaces`, from the same repository.
4. **Cause 1 detail**: `marine_autonomy` exports a target (`marine_autonomy::marine_autonomy`, `ament_export_targets` at `CMakeLists.txt:59`, present on the `jazzy` branch too), so `target_link_libraries` can name it. `marine_interfaces` messages and `rclcpp_lifecycle` are used by `asv_helm_node.cpp` and `marine_autonomy/pid.h` (which includes `rclcpp_lifecycle` and `marine_interfaces` message headers), so the fix must link those too or the include dirs are lost. The plan should name the targets and build both branches' forms.
5. **Cause 4**: confirmed in `asv_sim/setup.py:30` and `mbes_sim/setup.py:13`.
6. **Cause 9**: confirmed: `<test_depend>` precedes nothing wrong except that it follows `<member_of_group>` (line 20), as the issue says.

### Facts for the flake8 decision (no recommendation)

- **Raised by** `flake8-builtins`, check `A005` ("the module is shadowing a Python builtin module"), reported at line 1 column 1 of the file named like a standard-library module (`platform.py`; the error is `pkg/platform.py:1:2` in a scratch run). On this machine: `python3-flake8-builtins` 3.1.0 with flake8 7.3.0, `ament_flake8` 0.21.4 (Rolling), Python 3.14. The plugin builds the list from `sys.stdlib_module_names`. `A005` is not raised for the other modules in `asv_sim/asv_sim`.
- **Jazzy**: not established. The repository's `.pre-commit-config.yaml` pins `flake8-builtins==2.1.0`, which as far as I know does not have `A005` (it is not verified, no noble package index is readable here); Jazzy's `python3-flake8-builtins` on noble is probably that line too. If so, Jazzy's `test_flake8` passes and only Rolling's fails; only the Jazzy CI job can show it.
- **Which config applies**: `ament_flake8` passes its own `ament_flake8.ini` to flake8 with `--config`, so the repository's `.flake8` (identical ignore list, used by pre-commit only) and `asv_sim/setup.cfg` do not apply to `test_flake8.py`. Its command line takes only `--config`, `--linelength`, `--exclude` and paths.
- **Remedy 1, rename `asv_sim/asv_sim/platform.py`**: the only import is `asv_sim/asv_sim/asv_sim_node.py:12` (`import asv_sim.platform`) and its use at `:41` (`asv_sim.platform.Platform(...)`). No test, launch file, config, entry point or other package imports the module (searched the repository). Text mentions: a comment in `asv_sim/config/bizzyboat.yaml:10`, `asv_sim/config/environment.yaml:16`, and `.agents/README.md` lists modules including `platform`. The module name then differs from `jazzy` until the backport (by hand, as planned); out-of-tree code importing `asv_sim.platform` would break (none found in this workspace).
- **Remedy 2, exempt the check**: tested with `ament_flake8` on a scratch file: a file-level `# flake8: noqa: A005` comment inside `platform.py` (second line, after the shebang; a trailing `# noqa` on line 1 would corrupt the shebang) turns the failure into a pass, and only for that file and that code. A `.flake8` or `setup.cfg` entry cannot do it (not read). A package-wide alternative is passing `--config` to a package-local copy of the ament ini from `asv_sim/test/test_flake8.py` with `builtins-allowed-modules = platform` or `per-file-ignores`, which copies the whole ament configuration and so affects every file of the package, and is a bigger change. The `noqa` form touches one line in one file and works unchanged on Jazzy.

### CI: what is built from source for `marine_autonomy`

- `marine_autonomy` (package.xml, `rolling` at `ec4fd5d7`, same on `origin/jazzy`) depends on: `libboost-dev`, `geographic_msgs`, `geometry_msgs`, `marine_interfaces`, `nav_msgs`, `rclpy`, `rclcpp`, `rclcpp_lifecycle`, `tf2`, `tf2_geometry_msgs`, `tf_transformations`, `tf2_ros`; test: `ament_cmake_gtest`, `ament_cmake_pytest`, `ament_lint_auto`, `ament_lint_common`. All of those are rosdep keys that resolve on noble (jazzy) and resolute (rolling), including `libboost-dev`, `tf_transformations` and `marine_acoustic_msgs` (needed by `marine_interfaces`).
- The only source packages needed are therefore **`marine_autonomy` and `marine_interfaces`**, on both distros, from rolker/unh_marine_autonomy: a sparse clone of the branch matching the distro (as in rolker/mru_transform's workflow for `marine_vertical_datum`, with `sparse-checkout set marine_autonomy marine_interfaces`). **No `geodesy`, no `geographic_info` clone.**
- `rosdep install --ignore-src -y --from-paths` over `colcon list --packages-up-to` of the four packages, no `-r`; test step without sourcing `install/setup.bash`, as in the model workflows.

### Principle Alignment

| Principle | Status | Notes |
|---|---|---|
| A change includes its consequences | Watch | The dependency declarations (cause 11) and the one-fix-per-commit rule: declaring a missing key is a separate fix per package. Docs that name `platform.py` (`.agents/README.md` layout, two YAML comments) change only if the owner picks the rename. |
| Only what's needed | OK | Four of nine packages and the follow-up issues for what is left alone are the owner's decision. The `geodesy` clone is not needed (see above) and should not be added. |
| Small steps; step back when they stop converging | OK | Small, separate fixes on `rolling`, backported by hand. |
| Test what breaks | Watch | Cause 4 makes `colcon test` run no Python test at all; a CI that passes with zero Python tests would not show it. The CI should fail when `asv_sim` or `mbes_sim` ran no test. |
| Verify before claiming | Watch | Jazzy is checked by CI only; the PR should say that nothing was run on Jazzy locally and name what the Jazzy job did run. |
| Name the rule before bending it | OK | The lint rule is named and the decision goes to the owner at the plan checkpoint. The velocity frame is left alone as instructed. |

### ADR Applicability

| ADR | Triggered | Notes |
|---|---|---|
| 0013 `progress.md` entries | Yes | This entry; the plan and later entries go in `.agent/work-plans/issue-119/`. |
| 0002 Worktree isolation | Yes | Work is in the issue's worktree. |
| 0004, 0005 Enforcement | Yes | The new workflow is the first CI of this repository, authoritative over the local checks. |
| 0017 Design document | No | No design document in this repository. |

### Consequences

- A rename of `platform.py` would also update `.agents/README.md` and the two YAML comments; an exemption updates nothing else.
- The first CI workflow should be named in `.agents/README.md` (it lists layout and tests).

### Recommendations

- Correct the CI statement before planning: `marine_autonomy` needs no `geodesy`; the workflow needs only a sparse clone of rolker/unh_marine_autonomy (`marine_autonomy`, `marine_interfaces`, branch per distro), with no `geographic_info` clone (narrows the CI scope).
- Widen cause 11 to the list above: `asv_helm` (`rclcpp_lifecycle`, `std_msgs`), `mbes_sim` (`std_msgs`, `launch`, `launch_ros`, `lifecycle_msgs`), `asv_sim` (`python3-yaml` test, `launch`, `launch_xml`, `launch_ros`, `rcl_interfaces`), one commit per package (within scope; it is what cause 11 says to check).
- In the plan, give the owner the flake8 facts above (what raises `A005`, whose config applies, what each remedy touches) and no default; the Jazzy behavior is unverified and only the Jazzy job will show it (within scope).
- Make the CI fail when `asv_sim` or `mbes_sim` ran no Python test, so cause 4 cannot come back unnoticed (within scope; it is the issue's "counts not zero" condition made checkable).
- For cause 1, name the link targets in the plan (`marine_autonomy::marine_autonomy` plus the message and `rclcpp_lifecycle` targets the header needs) and check the form builds on both distros (within scope).

### Actions
- [ ] Correct the CI statement before planning: `marine_autonomy` needs no `geodesy`; the workflow needs only a sparse clone of rolker/unh_marine_autonomy (`marine_autonomy`, `marine_interfaces`, branch per distro), with no `geographic_info` clone (narrows the CI scope).
- [ ] Widen cause 11 to the list above: `asv_helm` (`rclcpp_lifecycle`, `std_msgs`), `mbes_sim` (`std_msgs`, `launch`, `launch_ros`, `lifecycle_msgs`), `asv_sim` (`python3-yaml` test, `launch`, `launch_xml`, `launch_ros`, `rcl_interfaces`), one commit per package (within scope; it is what cause 11 says to check).
- [ ] In the plan, give the owner the flake8 facts above (what raises `A005`, whose config applies, what each remedy touches) and no default; the Jazzy behavior is unverified and only the Jazzy job will show it (within scope).
- [ ] Make the CI fail when `asv_sim` or `mbes_sim` ran no Python test, so cause 4 cannot come back unnoticed (within scope; it is the issue's "counts not zero" condition made checkable).
- [ ] For cause 1, name the link targets in the plan (`marine_autonomy::marine_autonomy` plus the message and `rclcpp_lifecycle` targets the header needs) and check the form builds on both distros (within scope).

## Checkpoint
**Status**: complete
**When**: 2026-11-23 12:19 -05:00
**By**: Claude Code Agent (claude-fable-5-2)
**Decided-by**: host (the Issue Review found the issue well-scoped; its actions correct or extend the cause list inside the same four packages, and the one that narrows the CI work is a correction of a wrong statement in the issue)
**After**: issue-actions
**Decision**: proceed

Read: the Issue Review of 119 (well-scoped, right repository, no design change). Its actions go to the planner as inputs:

- CI correction: `marine_autonomy` and `marine_interfaces` need no `geodesy`; the workflow needs only a sparse clone of rolker/unh_marine_autonomy for those two packages (branch per distro) and no `geographic_info` clone. The issue's sentence saying otherwise is wrong.
- Cause 11, the full list, one commit per package, each key confirmed before it is declared: `asv_helm` (`rclcpp_lifecycle`, `std_msgs`); `mbes_sim` (`std_msgs`, `launch`, `launch_ros`, `lifecycle_msgs`); `asv_sim` (`python3-yaml` for a test, `rcl_interfaces`, `launch_xml`, `launch_ros`).
- Cause 1: the link fix names `marine_autonomy::marine_autonomy` and the message and `rclcpp_lifecycle` targets `pid.h` needs.
- CI fails when `asv_sim` or `mbes_sim` ran no Python test, so cause 4 cannot return unnoticed.
- The flake8 `A005` failure: the review's facts (raised by `flake8-builtins` 3.1.0 on this machine; not established for Jazzy; `ament_flake8` ignores the repository's own flake8 config; a rename touches one import; a file-level `# flake8: noqa: A005` on line 2 of `platform.py` exempts that one file and code) go to the owner, who decides; the host is asking him now and passes his answer to the planner.

## Plan Authored
**Status**: complete
**When**: 2026-11-23 12:52 -05:00
**By**: Claude Code Agent (claude-sonnet-5-5)
**Plan**: `.agent/work-plans/issue-119/plan.md` at `1d7d704`

Nine commits on `rolling` (causes 1, 11 x3, 4, 9, the owner-chosen rename of `platform.py` to `sim_platform.py`, a first CI workflow with a Python test-count guard, and a docs line), all backported by hand. Planned from a measured baseline and a scratch copy: 251 tests, 0 failures, 1 skipped; 290 repeat runs with no intermittent failure; the Rolling job rehearsed in a clean environment; Jazzy facts by reading only.

## Plan Review
**Status**: complete
**When**: 2026-11-23 12:58 -05:00
**By**: Claude Code Agent (claude-opus-5-5)
**Verdict**: ready

**Issue**: #119 — Build on ROS 2 Rolling: port asv_sim_msgs, asv_helm, asv_sim and mbes_sim, and add CI
**Plan**: `.agent/work-plans/issue-119/plan.md` at `1d7d704`
**Branch**: `feature/issue-119`

### Evaluation

| Dimension | Verdict | Notes |
|---|---|---|
| Scope | Good | Four packages, nine small commits, CI separate; the five other packages and the velocity block are left alone as the owner set. |
| Issue alignment | Good | Every row of the issue's cause table is covered; the issue review's five recommendations are all taken (no `geodesy`, widened cause 11, A005 facts to the owner, test-count guard, named link targets). Serves: "none recorded (no goals or design document in this repository); the work serves #415 and #120" — acceptable for a project with no goals written down. |
| File targeting | Good | Rename: the only importer is `asv_sim/asv_sim/asv_sim_node.py:12,41`; no test, launch file, entry point or other package imports `asv_sim.platform` (searched this repository, `/home/roland/project11/rolling/*/src`, every remote branch ahead of `origin/jazzy`, `git log --all`). Text mentions are the two YAML comments and `.agents/README.md`, all in the patch. |
| Consequences | Good | Rename, workflow and agent guide covered. One unrecorded consequence of upstream behaviour: finding 1. |
| Principle alignment | Good | Each fix has a check that fails without it (build, `xmllint`, `test_flake8`, the guard, strict `rosdep` plus no overlay in the test step). Verify before claiming: Jazzy and the GitHub jobs are stated as unrun. |
| ADR compliance | Good | 0013 (entries), 0002 (worktree), 0004/0005 (first workflow is the authority). |
| ROS conventions | Good | Modern CMake targets as in `helm_manager`; `marine_autonomy::marine_autonomy` exists with the same `CMakeLists.txt` on `origin/jazzy` and `origin/rolling` (ALIAS :25, `ament_export_targets` :59, include dir installed so `marine_autonomy/pid.h` resolves); dependency kinds match use (`launch_xml`/`launch_ros`/`lifecycle_msgs` exec, `python3-yaml`/`launch` test). |

### Findings

1. **[Consequences]** (minor) — `test_tide_integration.py` runs under `colcon test` only because of an upstream bug. `asv_sim/test/conftest.py` sets `collect_ignore = ['test_tide_integration.py']` and the file's docstring says it must run under `launch_test`; but `launch_testing`'s `pytest_ignore_collect` hook is `tryfirst` and returns `False` in the released versions (Rolling 3.10.3 installed here, Jazzy 3.4.13 per rosdistro), which overrides `collect_ignore` (checked: `pytest --collect-only` here collects 163 including it). ros2/launch#1048 fixes that (on `rolling` 2026-10-26, backported to `jazzy` 2026-11-02, not yet released on either). After the next sync the `asv_sim` count drops from 163 to 162 on both jobs and the tide integration test then runs nowhere in CI (an `ament_python` package registers no `launch_test`); the guard will not notice (count still > 0). Resolution: say this in the PR text next to the 251/163 counts, and list it in the follow-up issue. No code change here.
2. **[Principle alignment]** (minor) — Wall-clock tests: the plan should name which tests are timing-sensitive instead of "these tests use the wall clock". From reading them: `test_dynamics_stability`, `test_tide_model` and `test_collision` drive the model with explicit timestamps and create nodes only for parameters (no wall clock, no messaging). `test_multi_platform` is wall-clock (8 s / 6 s / 18 s drives on `time.monotonic`) but in one process with one executor (no cross-process discovery), and the dynamics sub-step any gap up to `max_substeps` 100 × `max_step` 0.1 s, so CPU starvation on a 4-core runner is unlikely to change distances. `test_tide_integration` is the fragile one: a separate launched process, cross-process DDS discovery, a 5 s collection window that starts at `ReadyToTest` (emitted at launch, before the node is up), needing more than 5 messages and a 0.5 m range, and `test_tide_varies` reuses data from the previous test. No test sets `ROS_DOMAIN_ID` (harmless on a GitHub job VM; matters on a shared machine). On a runner, `colcon test` also runs `mbes_sim`'s GDAL tests and the lints concurrently with it. Resolution: state this in the plan/PR so a first-run failure of `test_tide_integration` is read correctly.
3. **[Consequences]** (minor) — The PR text's advice for pending patches against `platform.py` ("a patch needs `--directory`/hand edit") is wrong about `--directory`: it prepends a path and cannot map `platform.py` to `sim_platform.py` (`git apply --directory=x` → `x/platform.py: No such file or directory`). Checked on a throwaway repository: plain `git am` fails, `git am -3` applies the edit to `sim_platform.py` (rename detection), as does `git cherry-pick`. Resolution: say "`git cherry-pick` or `git am -3`" instead.
4. **[ROS conventions]** (nit) — The guard reads colcon's `pytest.xml`; colcon writes a placeholder there before running pytest (`tests="1" errors="1"`), so if pytest dies before writing results the guard reports "1 tests" and passes. The Test step fails in that case, so there is no false pass of the job and no false failure; only the guard's message is misleading. Subtracting `errors` would make it exact; optional. Root element (`testsuites` or `testsuite`) and attribute names are handled; a skipped-only suite fails, as intended; a package run by `unittest` writes no `pytest.xml` and fails, as intended.
5. **[Issue alignment]** (nit) — "`colcon-core` 0.15.2 (noble)": the CI container gets `python3-colcon-core` with `ros-dev-tools` from packages.ros.org, not Ubuntu's 0.15.2. The conclusion holds either way (0.15.2 already maps `extras_require` `test`, as does 0.21.3 here, `package_augmentation/python.py`).

### Summary

The plan is sound and ready: the rename is a pure 100 % move plus the one importer and three text mentions; cause 4's form matches `joy_to_helm`, `command_bridge` and `marine_web_view` in rolker/unh_marine_autonomy and colcon maps it to pytest on both distros; the workflow matches `mru_transform`'s working shape and every rosdep key of the six-package closure resolves for noble and resolute (and is installed here for resolute); nothing touches or tests the velocity block. The findings are PR-text and follow-up items, none blocks implementation.

### Recommended Actions

- [ ] PR text: say `test_tide_integration` currently runs only because of the `launch_testing` collect-ignore bug (ros2/launch#1048) and that the count will drop to 162 when it is released; add it to the follow-up issue.
- [ ] Plan/PR: name `test_tide_integration` as the timing- and discovery-sensitive test and `test_multi_platform` as wall-clock but in-process; the rest are clock-free.
- [ ] PR text: replace "`--directory`/hand edit" with "`git cherry-pick` or `git am -3`".
- [ ] Optional: subtract `errors` in the guard.

## Checkpoint
**Status**: complete
**When**: 2026-11-23 13:03 -05:00
**By**: Claude Code Agent (claude-fable-5-2)
**Decided-by**: host (the plan review's verdict is ready; its five findings are minor or nits and each is a wording or one-line correction the implementer applies; none changes scope or an owner decision)
**After**: plan
**Decision**: proceed

Read: the Plan Review at `1d7d704`, verdict ready, five findings. The implementer applies them as follows. F1: the pull request text and the follow-up issue draft say that `test_tide_integration.py` runs under `colcon test` only because released `launch_testing` overrides `collect_ignore` (fixed upstream by ros2/launch#1048, not yet released), so after a sync the `asv_sim` count drops from 163 to 162 and that test then runs nowhere in CI; no code change. F2: the plan and pull request text name which tests are timing-sensitive (`test_multi_platform` wall-clock in one process; `test_tide_integration` the fragile one: a launched process, cross-process discovery, a 5 s window) so a first-run failure is read correctly; the simulator and its tests are not changed for it. F3: the advice for pending work on `platform.py` says `git cherry-pick` or `git am -3`, not `--directory`. F4: the test-count guard subtracts `errors` as well as `skipped`, so colcon's placeholder file cannot read as one test. F5: the colcon-core version wording is corrected. Decisions: the module is renamed to `sim_platform.py` (owner: "Rename the module"; the name is the planner's) and the rename is backported to `jazzy` with the other commits, although Jazzy's lint does not need it, so both branches carry the same code (the owner may veto before the backport). The lint finding is #415 cause 15. The velocity block is neither changed nor asserted.
