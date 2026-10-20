# asv_sim
ROS Nodes that simulates a generic ASV.

## Stepping and numerical robustness

`Dynamics.update()` accepts any gap since the previous update.

- Drag (cubic in the speed, sign-preserving) and the jet model's yaw damping
  are integrated implicitly, so a step can at most bring the speed or yaw
  rate to rest, never past it. A long step cannot diverge. At the node's
  0.05 s step the terminal speed under constant thrust is exactly the same
  as with the earlier explicit scheme (`max_speed`), and the acceleration
  transient differs by up to about 2 % where the speed curve bends.
- A gap longer than `max_step` is integrated as equal sub-steps of at most
  `max_step` seconds. At most `max_substeps` sub-steps are taken per update;
  the rest of a longer gap is dropped, with a warning that the platform fell
  behind (logged at most once every 5 s). Noise is applied in every sub-step,
  as it would be for the same number of ordinary updates.
- If a state value (speed, yaw rate, position, heading, rpm, rudder angle)
  is not finite after an update, or the arithmetic fails, the platform is
  logged at ERROR level by name, reset to rest at its last finite position
  and the node carries on. The node does not exit on a numerical excursion.

Model parameters (`models.<name>.<key>`, set in the model YAML):

| Key | Default | Range | Meaning |
|-----|---------|-------|---------|
| `max_step` | `0.1` s | 0.001 to 10 | Longest time step integrated in one go |
| `max_substeps` | `100` | 1 to 10000 | Most sub-steps per update; the default covers a 10 s gap, a longer one is dropped with a warning |

## Contact: boats block each other and the bottom

Boats are indestructible. A contact only keeps a boat from getting any
further into what it touches: no damage, no penalty, no reset. Implemented in
`asv_sim/collision.py` and called by `Dynamics` once per integration
sub-step (after the position and the current are applied, before course and
speed over ground are computed), so a long stalled gap is resolved step by
step and a boat cannot tunnel through a shore or another hull.

- **Boat to boat.** The hull is a capsule of the model's `length` and `beam`.
  A boat that would overlap another is moved out along the contact normal by
  the overlap, so boats touch and slide but never pass through each other, and
  backing away is always free. Only the boat being stepped moves; the other
  boat is untouched. Two boats put on top of each other (`set_pose`, a roster)
  are pushed apart on their next step.
- **Boat to bottom.** Needs `collision.grid_file`. Hull clearance is the least,
  over the centre, bow, stern, port and starboard points, of grid depth plus
  tide minus `draft`. Land (negative or zero depth) is graded by its height;
  no-data cells and positions off the grid are the void, a wall. A step that would take the boat into
  negative clearance, shallower than where it is, loses the part of its motion
  that points shallower; if that is not enough it stays where it was. A boat
  that already is aground (a low tide, a `set_pose` onto the shallows) may
  move anywhere that is not shallower, so it can always get out. A boat in
  the void can only move through the void or into water, never onto land or
  a shoal, and a warning names it once. A turn that would swing the hull
  onto land is put back (heading restored, yaw rate zeroed). Between a boat
  and the shore the shore wins: the boat is kept out of the land and may
  overlap the other boat for that step. The datum
  caveat of the demo grid (CCOM does not state it; it is treated as MLLW, as
  the sonar does) applies. Wave heave, roll and pitch are ignored.
- **Long hops.** A step longer than half a beam (a long `max_step`, a fast
  current) is checked in pieces of at most that length, so a thin hull or
  shore cannot be jumped.
- **Speed.** A boat moving into the obstacle keeps only the part of its speed
  that is along the hull axis and across the contact: `speed * (1 - cos^2)`
  of the angle between its heading and the contact normal. Head on it stops,
  at a glancing angle it keeps sliding, reversing is free. Heading, rpm and
  rudder are not changed.
- **Event.** `~/collisions` (`asv_sim_msgs/msg/Collision`, reliable) gets one
  message per contact onset, not one per step; a contact is over after one
  second without overlap (a boat that touches, backs off and touches again
  within a second is one event). The topic is not latched: a subscriber that
  starts later does not see earlier events. The node also logs one INFO line.
  `closing_speed` is the closing speed of the attempted motion, current
  included.
- **More obstacle sources.** `Collisions.sources` is a list of objects with
  `correct(step, lat, lon)`; boats and terrain are two of them. Another source
  (for example charted objects, issue #113) is appended to the list.

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `collision.boats` | `true` | Boats block each other; `false` lets them pass through |
| `collision.grid_file` | `''` | Bathymetry GeoTIFF (as `mbes_sim.bathy_grid` reads it); empty: no terrain collision. Read once at start; an unreadable file stops the node |
| `models.<name>.length` | `4.0` m | Hull length (0.01 to 1000); must not be less than `beam` |
| `models.<name>.beam` | `1.7` m | Hull width |
| `models.<name>.draft` | `0.4` m | Keel depth; the boat grounds where the water is shallower |

`collision.grid_file` is loaded whole into memory (about 27 MB for the demo
truth grid, 69 MB for the chart grid); do not point it at a multi-gigabyte
compilation.

The defaults are the C-Worker 4 (`cw4.yaml`). `coastal_surveyor`, `drix` and
`echoboat240` use them without having been checked against those boats.
