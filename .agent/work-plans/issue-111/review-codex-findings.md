### Findings

| # | Severity | File | Line | Finding |
|---|----------|------|------|---------|
| 1 | must-fix | `asv_sim/asv_sim/model.py` | 174 | Valid small hulls cannot load. Parameters are declared individually, with `length` first, so configuring length `1.0` and beam `0.5` rejects the length against the undeclared beam’s default `1.7`. Validate the complete initial hull configuration rather than comparing partially declared overrides with defaults. |
| 2 | must-fix | `asv_sim/asv_sim/collision.py` | 235 | Terrain clearance at both positions uses the **new** heading. A turn that sweeps the bow onto land therefore makes `before` already grounded; if translation is zero or does not worsen clearance, the step is accepted without contact. Preserve the previous orientation and resolve rotational penetration as well as translation. |
| 3 | must-fix | `asv_sim/asv_sim/collision.py` | 315 | Terrain correction can undo boat separation. Sources run once in order, and terrain can restore `step.prev` after boats pushed the vessel out of an overlap. A planar reproduction with a boat beside shore ends at the original overlapping position. Validate the final position against all sources and resolve competing constraints together. |
| 4 | must-fix | `asv_sim/asv_sim/collision.py` | 105 | For intersecting capsule axes, the sum of radii is not the displacement needed to separate the hulls. Two perpendicular `20 × 1 m` hulls at the same centre still intersect after all three correction passes: the centre moves only 3 m along the other hull’s axis. Compute a valid separating translation; the existing crossing test checks only normal length, not actual separation. |
| 5 | must-fix | `asv_sim/asv_sim/collision.py` | 166 | Collision detection checks only the endpoint, so substeps do not guarantee prevention of tunnelling. With supported `max_step=10`, a boat can cross another hull and finish clear of it; small hulls can also be skipped at the default timestep. Terrain has the same endpoint-only limitation. Use swept collision checks or bound displacement by obstacle and hull dimensions. |

### Summary

The implementation covers ordinary approaches but does not reliably enforce nonpenetration during rotation, intersecting-hull recovery, or combined contacts. Geometry probes confirmed several failures; ROS runtime validation was blocked by logging writes in the read-only environment.
--- Review complete ---
