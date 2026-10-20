---
issue: 108
---

# Issue #108 — Demo on a fresh computer: rqt perspective, CAMP range/colormap, machine set-up

## Implementation
**Status**: complete
**When**: 2026-10-20 10:35 -04:00
**By**: Claude Code Agent (Claude Sonnet 5.5)

### Done
- [x] rqt perspective: generated per boat set, imported on a first start or --rqt-fresh (commits 10c1e9b, 25025e4)
- [x] CAMP live layers seeded with viridis and a fixed manual range (fa6c725)
- [x] README "Setting up the demo computer" checklist (eac9c85)

### Evidence
- rqt imports `--perspective-file` as the hidden perspective "@<basename>" (qt_gui main.py and perspective_manager.py, Jazzy); not listed in the menu, not made current, saved on exit.
- Live offscreen run (empty XDG_CONFIG_HOME, QT_QPA_PLATFORM=offscreen, 15 s each): run 1 imported demo-5a8b03a2.perspective, the saved rqt_gui.ini held 5 plugin instances (1 Survey Coverage, 4 Ping Profile); run 2 started by name "@demo-5a8b03a2.perspective" (log line "starting on the stored perspective") and kept the operator's edit of a dock title.
- Live layer "depth" band = WGS84 ellipsoid height, positive up: tile cache of an earlier demo run read -48..-43 m over about 17 m of water; water surface about -29.4 m (407 cells vs chart depth, sd 0.6). So 0 to 30 m of water = range -59.4..-29.4 (range_min = deep end). Colormap viridis: perceptually uniform, monotonic luminance, dark deep to light shallow; from marine_colormap's 8 palettes (grayscale, bronze, thermal, viridis, turbo, quality, oleron, hypsometric).
- Tests: 663 run, 8 failures = the pre-existing lint failures in untouched files; all new and existing pytest targets pass.
- Not verified: window layout of the five docks (no screen), rtx 5080 / nvidia driver steps, kernel steps on the event machine; no Qt render of the colormap.
- Review (pre-push, Standard): Codex 1 must-fix (perspective ignored --boats/--roster) fixed in 25025e4; two Claude passes suggestions only (unreadable ini fallback, stale stored perspective, 0-30 wording) fixed; Gemini timed out (420 s).
