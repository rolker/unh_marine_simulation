### Findings

| # | Severity | File | Line | Finding |
|---|----------|------|------|---------|
| 1 | must-fix | `asv_sim/asv_sim/collision.py` | 456 | Keying contacts by class discards collision normals when several objects or segments share a class. Reproduced with two perpendicular `SLCONS` walls: a boat moving directly into one wall retains its full 2 m/s because the other wall’s perpendicular normal overwrites the blocking normal. Changing only the second wall’s class makes speed correctly become zero. Preserve all physical contact normals through resolution; deduplicate only event reporting. |
| 2 | must-fix | `marine_simulation/test/test_demo_boats_launch.py` | 545 | The existing assertion still requires the old four-argument call and fails against the new five-argument call; confirmed by running this test. Additionally, `_setup_context` omits `charted_objects`, so tests calling `launch_setup` directly encounter a missing launch configuration. Update both the assertion and launch-context fixture, with explicit chart enable/disable coverage. |

### Summary

The implementation broadly follows the plan, but loses physical contact information when obstacles share a class and breaks existing launch tests. The contact bug was reproduced independently, and the stale assertion was confirmed with pytest; the full suite could not run under the read-only filesystem restrictions.
--- Review complete ---
