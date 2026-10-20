---
issue: 107
---

# Issue #107 — Demo: desktop shortcut to start it, and a plug-order joystick mode (js0..js3, any number of pads)

## Local Review (Pre-Push)
**Status**: complete
**When**: 2026-10-20 (pre-push)
**By**: Claude Code Agent (Claude Sonnet 5.5)
**Verdict**: approved

**Branch**: feature/issue-107
**Mode**: pre-push
**Depth**: Standard (reason: new installer script plus launch change, ~680 lines)
**Must-fix**: 3 (all fixed) | **Suggestions**: 0
**Round**: 1 | **Ship**: recommended — all must-fixes fixed with tests; gemini timed out (7m), codex ran, own read found nothing further

### Findings
- [x] (must-fix) env.bash check inherited the caller's PATH, so a ROS terminal hid a bad env.bash — `marine_simulation/scripts/install_demo_shortcut.sh`
- [x] (must-fix) Exec value did not escape `%` or double backslashes per the Desktop Entry spec; tests now decode like a launcher — `marine_simulation/scripts/install_demo_shortcut.sh`
- [x] (must-fix) DEMO_CONFIG_DIR used at install was not carried by the icon — `marine_simulation/scripts/install_demo_shortcut.sh`
