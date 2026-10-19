---
issue: 104
---

# Issue #104 — Demo rqt launch: pass --force-discover so a rebuilt tree's new plugins show up

## Implementation
**Status**: complete
**When**: 2026-10-19 11:27 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

**Branch**: feature/issue-104 (not pushed)

### What was built
- `demo_rqt_launch.py` runs `rqt --force-discover --perspective <name>`; test and READMEs updated.

### Verification
- `./simulation_ws/test.sh launch_manager_proto marine_simulation mbes_sim`: no failure in a file this change touches; the remaining failures are the baseline lint in files it does not touch.
