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
