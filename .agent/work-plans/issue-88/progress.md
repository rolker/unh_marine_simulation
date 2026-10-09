---
issue: 88
---

# Issue #88 — Four simulated boats at once: multi-platform asv_sim + four per-boat sensor/CUBE chains, joysticks, no nav stack

## Issue Review
**Status**: complete
**When**: 2026-10-09 12:58 -04:00
**By**: Claude Code Agent (Claude Sonnet)

**Issue**: #88
**Comment**: (best-effort post follows this entry; not recorded inline)
**Scope verdict**: needs-more-detail

Parent umbrella: #87. The helm_manager `initial_piloting_mode` parameter has MERGED (unh_marine_autonomy PR#401, 2026-10-09), so work item 5 is no longer blocked.

### Actions
- [ ] Action needed: `no_sim:=true` in `sim_robot_launch.py` gates the whole `sim_group` (asv_sim + mbes_sim + detections_to_pointcloud + cube_bathymetry), so work items 1-2 as written give four boats with no sensors/CUBE. Add a separate argument (or split the group) so only the `asv_sim` node is skipped; `tide_speed_factor` is applied only to that node.
- [ ] Action needed: nav2 is included unconditionally by `ben_core_launch.py` (ben_project11) and `mission_manager` by `robot_core_launch.py` (unh_marine_autonomy); `sim_robot_launch.py` cannot gate them alone. Plan the cross-repo argument plumbing (sub-issues "Part of #88" or an explicit stacked-PR set).
- [ ] Action needed: `sim_robot_launch.py` defaults `enable_bridge` to true, so four stacks would start four `udp_bridge` nodes on port 4200; pass `enable_bridge:=false` from the multi-boat launch.
- [ ] Action needed: `ben_description/launch/publish_state_launch.py` does not pass `namespace` to xacro (links stay `ben/...`), and `asv_sim/config/ben.yaml` hard-codes `mru_frame: ben/motion_sensor`; settle platform/frame naming (or fix the description launch) before the TF check.
- [ ] Action needed: tests - a launch-load/default-argument test and a multi-platform `asv_sim` test (Test what breaks); README and `.agents/README.md` updates ride in the same PR.
- [ ] Recommendation: reword work item 4 - with one shared `asv_sim`, the absolute `/asv_sim/environment/tide_level` remap is the intended shared topic, not a collision.
- [ ] Recommendation: joystick mapping - installed `joy` is 3.3.0 (SDL, selects by device index/name, not `/dev/input/js<N>`); `joy_node` + `joy_to_helm` only exist inside `operator_core_launch.py`'s `operator_joystick` group, so a per-boat joystick snippet is needed; document or key by name/GUID since SDL index order is not stable across replug.
- [ ] Recommendation: expose `cell_size` (hard-coded 1.0), `ping_interval` (hard-coded 0.2) and `beam_count` as launch arguments with current values as defaults, for work item 6.
- [ ] Recommendation: `initial_piloting_mode` is read-only and defaults empty; set it via a layered config file or scoped SetParameter (helm_manager_launch.py has no passthrough).
- [ ] Recommendation: `marine_simulation` has no README (only the repo-root README.md); decide where the acceptance-criterion docs go.
