# Adversarial Code Review

## Your Role

You are an independent adversarial reviewer. Your job is to find issues that
other reviewers missed: edge cases, security implications, incorrect
assumptions, subtle bugs, and logic errors.

Review the diff below with fresh eyes. Do not assume previous reviewers caught
everything. Focus on:

- **Edge cases**: What inputs or states could break this code?
- **Security**: Are there injection, auth, or data exposure risks?
- **Assumptions**: What does the code assume that might not hold?
- **Subtle bugs**: Off-by-one, race conditions, resource leaks, null/undefined
- **Logic errors**: Does the code actually do what the PR title claims?

## PR Under Review

**Title**: Local branch feature/issue-111 at c574b3e
**Branch**: feature/issue-111
**Base**: origin/jazzy
**HEAD**: c574b3e

## Diff

````diff
diff --git a/.agents/README.md b/.agents/README.md
index 9be3c8d..3174e74 100644
--- a/.agents/README.md
+++ b/.agents/README.md
@@ -7,7 +7,7 @@
 | Package | Language | Description |
 |---------|----------|-------------|
 | `asv_sim` | Python | ASV dynamics simulator with configurable platform models and environment |
-| `asv_sim_msgs` | C++ (msg gen) | Service definitions for the ASV simulator (`SetPose`) |
+| `asv_sim_msgs` | C++ (msg gen) | Service and message definitions for the ASV simulator (`SetPose`, `Collision`) |
 | `asv_helm` | C++ | Converts Twist/Helm commands to throttle and rudder outputs |
 | `vrx_project11` | C++ | WAM-V differential-thrust helm with nav2 integration |
 | `mbes_sim` | Python | Multibeam echosounder simulator using bathymetry grids |
@@ -21,10 +21,11 @@
 ```
 unh_marine_simulation/
 ├── asv_sim/                           # ASV dynamics simulator
-│   ├── asv_sim/                       #   Python module (dynamics, environment, model, platform)
+│   ├── asv_sim/                       #   Python module (dynamics, environment, model, platform, collision)
 │   ├── config/                        #   Platform configs (ben.yaml, cw4.yaml, drix.yaml, demo.yaml, ...)
 │   └── test/                          #   Linting, tide tests, test_multi_platform.py (in-process)
-├── asv_sim_msgs/                      # Service definitions
+├── asv_sim_msgs/                      # Service and message definitions
+│   ├── msg/Collision.msg
 │   └── srv/SetPose.srv
 ├── asv_helm/                          # Helm controller (Twist → throttle/rudder)
 │   └── src/asv_helm_node.cpp
@@ -167,3 +168,17 @@ Known build issues:
 |-----------|------|---------|-------|--------|
 | `models.<name>.max_step` | double, s | `0.1` | 0.001 to 10 | Longest step integrated in one go; a longer gap is split into equal sub-steps no longer than this |
 | `models.<name>.max_substeps` | int | `100` | 1 to 10000 | Most sub-steps per update; beyond `max_substeps * max_step` seconds the remainder of a gap is dropped, with a warning (at most one per 5 s per platform) |
+
+- **`asv_sim` boats block each other and the bottom (issue #111); contact is resolved inside `Dynamics`, once per integration sub-step, never from the node's update loop.** `Dynamics._step` calls `asv_sim.collision.Collisions.resolve` right after the position and the current are applied; a pass over the platforms after the whole update would tunnel through a shore or a hull after a stalled gap (up to 27 m at top speed in one update). Contact code runs in its own try/except (`Dynamics._resolve_contact`): a bug there is logged once per 5 s and the integrated step stands, it must never look like a numerical excursion (that resets the boat to rest). Boats are indestructible: only position and speed are corrected. Terrain collision exists only when `collision.grid_file` is set (the demo passes the sonars' grid); without it, boats block each other but nothing stops them at a shore. Land, nodata and off-grid cells are walls; a boat that starts aground may move anywhere not shallower. A new obstacle source (charted objects, issue #113) is an object with `correct(step, lat, lon)` appended to `Collisions.sources`. Dynamics noise (`thrust_noise`, `yaw_rate_noise`) makes a head-on meeting glancing, so two boats slide past each other; tests that want an exact stop set the noise to 0.
+
+### `asv_sim` contact parameters (verified against `asv_sim/asv_sim_node.py` and `asv_sim/model.py`)
+
+| Parameter | Type | Default | Range | Effect |
+|-----------|------|---------|-------|--------|
+| `collision.boats` | bool | `true` | | Boats block each other; `false` lets them pass through |
+| `collision.grid_file` | string | `''` | | Bathymetry GeoTIFF read once at start with `mbes_sim.bathy_grid.BathyGrid`; empty means no terrain collision; an unreadable file raises at start |
+| `models.<name>.length` | double, m | `4.0` | 0.01 to 1000, not less than `beam` | Hull length (capsule footprint) |
+| `models.<name>.beam` | double, m | `1.7` | 0.01 to 1000, not more than `length` | Hull width |
+| `models.<name>.draft` | double, m | `0.4` | 0.01 to 1000 | The boat grounds where grid depth + tide is less than this |
+
+Topic: `/asv_sim/collisions` (`asv_sim_msgs/msg/Collision`, reliable, depth 10), one message per contact onset.
diff --git a/asv_sim/README.md b/asv_sim/README.md
index daf904e..12bf5b7 100644
--- a/asv_sim/README.md
+++ b/asv_sim/README.md
@@ -27,3 +27,51 @@ Model parameters (`models.<name>.<key>`, set in the model YAML):
 |-----|---------|-------|---------|
 | `max_step` | `0.1` s | 0.001 to 10 | Longest time step integrated in one go |
 | `max_substeps` | `100` | 1 to 10000 | Most sub-steps per update; the default covers a 10 s gap, a longer one is dropped with a warning |
+
+## Contact: boats block each other and the bottom
+
+Boats are indestructible. A contact only keeps a boat from getting any
+further into what it touches: no damage, no penalty, no reset. Implemented in
+`asv_sim/collision.py` and called by `Dynamics` once per integration
+sub-step (after the position and the current are applied, before course and
+speed over ground are computed), so a long stalled gap is resolved step by
+step and a boat cannot tunnel through a shore or another hull.
+
+- **Boat to boat.** The hull is a capsule of the model's `length` and `beam`.
+  A boat that would overlap another is moved out along the contact normal by
+  the overlap, so boats touch and slide but never pass through each other, and
+  backing away is always free. Only the boat being stepped moves; the other
+  boat is untouched. Two boats put on top of each other (`set_pose`, a roster)
+  are pushed apart on their next step.
+- **Boat to bottom.** Needs `collision.grid_file`. Hull clearance is the least,
+  over the centre, bow, stern, port and starboard points, of grid depth plus
+  tide minus `draft`. Land (negative or zero depth), no-data cells and
+  positions off the grid are walls. A step that would take the boat into
+  negative clearance, shallower than where it is, loses the part of its motion
+  that points shallower; if that is not enough it stays where it was. A boat
+  that already is aground (a low tide, a `set_pose` onto the shallows) may
+  move anywhere that is not shallower, so it can always get out. The datum
+  caveat of the demo grid (CCOM does not state it; it is treated as MLLW, as
+  the sonar does) applies. Wave heave, roll and pitch are ignored.
+- **Speed.** A boat moving into the obstacle keeps only the part of its speed
+  that is along the hull axis and across the contact: `speed * (1 - cos^2)`
+  of the angle between its heading and the contact normal. Head on it stops,
+  at a glancing angle it keeps sliding, reversing is free. Heading, rpm and
+  rudder are not changed.
+- **Event.** `~/collisions` (`asv_sim_msgs/msg/Collision`, reliable) gets one
+  message per contact onset, not one per step; a contact is over after one
+  second without overlap. The node also logs one INFO line.
+- **More obstacle sources.** `Collisions.sources` is a list of objects with
+  `correct(step, lat, lon)`; boats and terrain are two of them. Another source
+  (for example charted objects, issue #113) is appended to the list.
+
+| Parameter | Default | Meaning |
+|-----------|---------|---------|
+| `collision.boats` | `true` | Boats block each other; `false` lets them pass through |
+| `collision.grid_file` | `''` | Bathymetry GeoTIFF (as `mbes_sim.bathy_grid` reads it); empty: no terrain collision. Read once at start; an unreadable file stops the node |
+| `models.<name>.length` | `4.0` m | Hull length (0.01 to 1000); must not be less than `beam` |
+| `models.<name>.beam` | `1.7` m | Hull width |
+| `models.<name>.draft` | `0.4` m | Keel depth; the boat grounds where the water is shallower |
+
+The defaults are the C-Worker 4 (`cw4.yaml`). `coastal_surveyor`, `drix` and
+`echoboat240` use them without having been checked against those boats.
diff --git a/asv_sim/asv_sim/asv_sim_node.py b/asv_sim/asv_sim/asv_sim_node.py
index ce58980..88f18cf 100755
--- a/asv_sim/asv_sim/asv_sim_node.py
+++ b/asv_sim/asv_sim/asv_sim_node.py
@@ -5,13 +5,17 @@
 # University of New Hampshire
 # Copyright 2017, All rights reserved.
 
+import asv_sim.collision
 import asv_sim.dynamics
 import asv_sim.environment
 import asv_sim.model
 import asv_sim.platform
+from asv_sim_msgs.msg import Collision
 from rcl_interfaces.msg import ParameterDescriptor
 import rclpy
 import rclpy.node
+from rclpy.qos import QoSProfile
+from rclpy.qos import ReliabilityPolicy
 from std_msgs.msg import Bool
 from std_msgs.msg import Float64
 
@@ -29,6 +33,8 @@ class AsvSim(rclpy.node.Node):
 
         self.environment = asv_sim.environment.Environment(self)
 
+        self.collisions = self._createCollisions()
+
         self.platforms = []
         for platform_name in self.platforms_param.value:
             self.platforms.append(
@@ -43,6 +49,51 @@ class AsvSim(rclpy.node.Node):
         self.update_timer = self.create_timer(0.05, self.update)
         self.nav_time = self.create_timer(0.2, self.updateNav)
 
+    def _createCollisions(self) -> asv_sim.collision.Collisions:
+        """Read the ``collision.*`` parameters and build the resolver.
+
+        An unreadable ``collision.grid_file`` raises: a simulation that
+        silently ran without its terrain would be the worse failure.
+        """
+        boats = self.declare_parameter(
+            'collision.boats', True,
+            ParameterDescriptor(
+                description='Boats block each other (no interpenetration, '
+                'sliding allowed). False lets them pass through.')).value
+        grid_file = self.declare_parameter(
+            'collision.grid_file', '',
+            ParameterDescriptor(
+                description='Bathymetry GeoTIFF (band 1, positive depth, '
+                'as read by mbes_sim.bathy_grid). Empty: no terrain '
+                'collision. Read once at start.')).value
+        grid = None
+        if grid_file:
+            from mbes_sim.bathy_grid import BathyGrid
+            grid = BathyGrid(grid_file)
+            self.get_logger().info(
+                'terrain collision on: {}'.format(grid_file))
+        else:
+            self.get_logger().info(
+                'terrain collision off: collision.grid_file is not set')
+        self.collision_publisher = self.create_publisher(
+            Collision, '~/collisions',
+            QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
+        return asv_sim.collision.Collisions(
+            grid=grid, boats=boats, emit=self._publishCollision,
+            logger=self.get_logger())
+
+    def _publishCollision(self, event: dict) -> None:
+        msg = Collision()
+        msg.header.stamp = event['stamp'].to_msg()
+        msg.platform = event['platform']
+        msg.kind = event['kind']
+        msg.other = event['other']
+        msg.latitude = event['latitude']
+        msg.longitude = event['longitude']
+        msg.closing_speed = float(event['closing_speed'])
+        msg.water_depth = float(event['water_depth'])
+        self.collision_publisher.publish(msg)
+
     def getModel(self, model_name: str) -> asv_sim.model.Model:
         if model_name not in self.models:
             self.models[model_name] = asv_sim.model.Model(model_name, self)
diff --git a/asv_sim/asv_sim/collision.py b/asv_sim/asv_sim/collision.py
new file mode 100644
index 0000000..72d03f8
--- /dev/null
+++ b/asv_sim/asv_sim/collision.py
@@ -0,0 +1,360 @@
+"""Contact resolution for ``asv_sim`` (issue #111): blocking only.
+
+Boats are indestructible. A contact only keeps a boat from getting any
+further into whatever it touches: no damage, no penalty, no reset.
+
+The resolver is called by :class:`asv_sim.dynamics.Dynamics` once per
+integration sub-step, right after the boat's position (its own motion plus
+the current) has been advanced, so a long stalled gap is resolved step by
+step and a boat cannot tunnel through a shore or a hull.
+
+What a boat can touch is a list of *obstacle sources*. Each source has
+``correct(step, lat, lon)``, returning the (possibly corrected) position and
+the list of :class:`Contact` it made. Boats and terrain are the two sources
+here; another one (charted objects, issue #113) is added by appending an
+object with the same method to ``Collisions.sources``, nothing in
+:meth:`Collisions.resolve` changes.
+
+All distances are metres in a local east/north frame; headings are compass
+radians (clockwise from north), as in ``Dynamics``.
+"""
+
+from collections import namedtuple
+import math
+
+from . import geodesic
+
+# What a boat that is on land, on a nodata cell or off the grid is treated
+# as drawing against: a fixed depth of water far below any draft.
+WALL_CLEARANCE = -10.0
+
+# A contact that has not been seen for this long (node clock) is over; the
+# next one is a new event.
+CONTACT_RELEASE_NS = 1000000000
+
+# Contact kinds (the values of asv_sim_msgs/msg/Collision).
+KIND_BOAT = 0
+KIND_TERRAIN = 1
+
+# A contact: kind, name of the other boat ('' for terrain), unit normal
+# (east, north) pointing away from the obstacle, velocity (east, north) of
+# the obstacle, and the water depth under the hull centre (NaN: none).
+Contact = namedtuple(
+    'Contact', ['kind', 'other', 'normal', 'other_velocity', 'water_depth'])
+
+
+def segment_closest(p0, p1, q0, q1):
+    """Return the closest points of segments p0-p1 and q0-q1 (2-D tuples)."""
+    d1 = (p1[0] - p0[0], p1[1] - p0[1])
+    d2 = (q1[0] - q0[0], q1[1] - q0[1])
+    r = (p0[0] - q0[0], p0[1] - q0[1])
+    a = d1[0] * d1[0] + d1[1] * d1[1]
+    e = d2[0] * d2[0] + d2[1] * d2[1]
+    f = d2[0] * r[0] + d2[1] * r[1]
+    eps = 1e-12
+    if a <= eps and e <= eps:
+        return p0, q0
+    if a <= eps:
+        s = 0.0
+        t = min(1.0, max(0.0, f / e))
+    else:
+        c = d1[0] * r[0] + d1[1] * r[1]
+        if e <= eps:
+            t = 0.0
+            s = min(1.0, max(0.0, -c / a))
+        else:
+            b = d1[0] * d2[0] + d1[1] * d2[1]
+            denom = a * e - b * b
+            s = min(1.0, max(0.0, (b * f - c * e) / denom)) \
+                if denom > eps else 0.0
+            t = (b * s + f) / e
+            if t < 0.0:
+                t = 0.0
+                s = min(1.0, max(0.0, -c / a))
+            elif t > 1.0:
+                t = 1.0
+                s = min(1.0, max(0.0, (b - c) / a))
+    return ((p0[0] + d1[0] * s, p0[1] + d1[1] * s),
+            (q0[0] + d2[0] * t, q0[1] + d2[1] * t))
+
+
+def capsule_axis(centre, heading, length, beam):
+    """Return the end points of a hull capsule's axis and its radius."""
+    half = max(0.0, (length - beam) / 2.0)
+    direction = (math.sin(heading), math.cos(heading))
+    return ((centre[0] - direction[0] * half, centre[1] - direction[1] * half),
+            (centre[0] + direction[0] * half, centre[1] + direction[1] * half),
+            beam / 2.0)
+
+
+def capsule_penetration(a, b):
+    """Return ``(depth, normal)`` of two overlapping capsules, else ``None``.
+
+    :param a: ``(axis_start, axis_end, radius)`` of the first capsule.
+    :param b: the same for the second.
+    :return: Overlap depth in metres and the unit vector pointing from ``b``
+        to ``a`` (the direction to move ``a`` to separate them).
+    """
+    pa, pb = segment_closest(a[0], a[1], b[0], b[1])
+    dx = pa[0] - pb[0]
+    dy = pa[1] - pb[1]
+    distance = math.hypot(dx, dy)
+    depth = a[2] + b[2] - distance
+    if depth <= 0.0:
+        return None
+    if distance < 1e-9:
+        # Axes cross: any direction separates them; take the one from b's
+        # centre to a's, else east.
+        cx = (a[0][0] + a[1][0] - b[0][0] - b[1][0]) / 2.0
+        cy = (a[0][1] + a[1][1] - b[0][1] - b[1][1]) / 2.0
+        norm = math.hypot(cx, cy)
+        return (depth, (cx / norm, cy / norm) if norm > 1e-9 else (1.0, 0.0))
+    return depth, (dx / distance, dy / distance)
+
+
+def offset_en(lat0, lon0, lat1, lon1):
+    """Return the (east, north) metres from point 0 to point 1 (radians)."""
+    azimuth, distance = geodesic.inverse(lon0, lat0, lon1, lat1)
+    return distance * math.sin(azimuth), distance * math.cos(azimuth)
+
+
+def move_en(lat, lon, east, north):
+    """Return ``(lat, lon)`` in radians after moving by (east, north) m."""
+    distance = math.hypot(east, north)
+    if distance == 0.0:
+        return lat, lon
+    lon2, lat2 = geodesic.direct(
+        lon, lat, math.atan2(east, north), distance)
+    return lat2, lon2
+
+
+class _Step:
+    """The boat being stepped and where it was and is."""
+
+    def __init__(self, dyn, prev, tide):
+        self.dyn = dyn
+        self.prev = prev        # (lat, lon) radians before the sub-step
+        self.heading = dyn.heading
+        self.tide = tide
+        model = dyn.model
+        self.length = model.length
+        self.beam = model.beam
+        self.draft = model.draft
+
+
+class BoatSource:
+    """Other boats: no interpenetration, tangential motion is kept."""
+
+    def __init__(self, collisions):
+        self.collisions = collisions
+
+    def correct(self, step, lat, lon):
+        contacts = {}
+        others = [d for d in self.collisions.dynamics.values()
+                  if d is not step.dyn]
+        # A push away from one boat can push into another: a few passes.
+        for _ in range(3):
+            moved = False
+            for other in others:
+                east, north = offset_en(lat, lon, other.latitude,
+                                        other.longitude)
+                mine = capsule_axis(
+                    (0.0, 0.0), step.heading, step.length, step.beam)
+                theirs = capsule_axis(
+                    (east, north), other.heading, other.model.length,
+                    other.model.beam)
+                hit = capsule_penetration(mine, theirs)
+                if hit is None:
+                    continue
+                depth, normal = hit
+                lat, lon = move_en(
+                    lat, lon, normal[0] * depth, normal[1] * depth)
+                velocity = (other.speed * math.sin(other.heading),
+                            other.speed * math.cos(other.heading))
+                contacts[other.name] = Contact(
+                    KIND_BOAT, other.name, normal, velocity, math.nan)
+                moved = True
+            if not moved:
+                break
+        return lat, lon, list(contacts.values())
+
+
+class TerrainSource:
+    """The sea floor: a boat cannot get shallower than its draft allows.
+
+    Clearance is the least, over five hull points (centre, bow, stern, port,
+    starboard), of grid depth plus tide minus draft. Land, nodata cells and
+    positions off the grid count as :data:`WALL_CLEARANCE`.
+    """
+
+    def __init__(self, grid):
+        self.grid = grid
+        self.cell = max(1.0, abs(grid.geoTransform[1]))
+
+    def _frame(self, lat, lon):
+        """Return the grid position and the grid vectors of 1 m east/north."""
+        x0, y0 = self.grid.getXY(math.degrees(lat), math.degrees(lon))
+        lat_e, lon_e = move_en(lat, lon, 1.0, 0.0)
+        lat_n, lon_n = move_en(lat, lon, 0.0, 1.0)
+        xe, ye = self.grid.getXY(math.degrees(lat_e), math.degrees(lon_e))
+        xn, yn = self.grid.getXY(math.degrees(lat_n), math.degrees(lon_n))
+        return (x0, y0, xe - x0, ye - y0, xn - x0, yn - y0)
+
+    def _depth(self, frame, east, north, tide):
+        """Return water depth above the sea floor at an offset, or None."""
+        x = frame[0] + east * frame[2] + north * frame[4]
+        y = frame[1] + east * frame[3] + north * frame[5]
+        depth = self.grid.getDepth(x, y)
+        if depth is None:
+            return None
+        return float(depth) + tide
+
+    def clearance(self, frame, east, north, step):
+        """Return the hull clearance with the boat centred at an offset."""
+        direction = (math.sin(step.heading), math.cos(step.heading))
+        right = (direction[1], -direction[0])
+        half_length = step.length / 2.0
+        half_beam = step.beam / 2.0
+        points = (
+            (0.0, 0.0),
+            (direction[0] * half_length, direction[1] * half_length),
+            (-direction[0] * half_length, -direction[1] * half_length),
+            (right[0] * half_beam, right[1] * half_beam),
+            (-right[0] * half_beam, -right[1] * half_beam))
+        least = math.inf
+        for de, dn in points:
+            depth = self._depth(frame, east + de, north + dn, step.tide)
+            value = (WALL_CLEARANCE if depth is None
+                     else max(WALL_CLEARANCE, depth - step.draft))
+            least = min(least, value)
+        return least
+
+    def correct(self, step, lat, lon):
+        frame = self._frame(*step.prev)
+        east, north = offset_en(step.prev[0], step.prev[1], lat, lon)
+        before = self.clearance(frame, 0.0, 0.0, step)
+        after = self.clearance(frame, east, north, step)
+        # Aground already is not a reason to stay: a boat may go anywhere
+        # that is not shallower than where it is.
+        if after >= 0.0 or after >= before:
+            return lat, lon, []
+
+        h = self.cell
+        ge = (self.clearance(frame, east + h, north, step)
+              - self.clearance(frame, east - h, north, step))
+        gn = (self.clearance(frame, east, north + h, step)
+              - self.clearance(frame, east, north - h, step))
+        norm = math.hypot(ge, gn)
+        speed = math.hypot(east, north)
+        if norm > 0.0:
+            normal = (ge / norm, gn / norm)
+        elif speed > 0.0:
+            normal = (-east / speed, -north / speed)
+        else:
+            normal = (-math.sin(step.heading), -math.cos(step.heading))
+
+        depth = self._depth(frame, east, north, step.tide)
+        contact = Contact(KIND_TERRAIN, '', normal, (0.0, 0.0),
+                          math.nan if depth is None else depth)
+        along = east * normal[0] + north * normal[1]
+        if norm > 0.0 and along < 0.0:
+            slid = (east - along * normal[0], north - along * normal[1])
+            clearance = self.clearance(frame, slid[0], slid[1], step)
+            if clearance >= 0.0 or clearance >= before:
+                new_lat, new_lon = move_en(
+                    step.prev[0], step.prev[1], slid[0], slid[1])
+                return new_lat, new_lon, [contact]
+        return step.prev[0], step.prev[1], [contact]
+
+
+class Collisions:
+    """Resolve contacts for every registered boat.
+
+    :param grid: A ``mbes_sim.bathy_grid.BathyGrid`` (or anything with
+        ``getXY``, ``getDepth`` and ``geoTransform``), or ``None`` for no
+        terrain.
+    :param boats: ``False`` lets boats pass through each other.
+    :param emit: Called with one dict per contact onset.
+    :param logger: Object with ``info`` and ``warning``.
+    """
+
+    def __init__(self, grid=None, boats=True, emit=None, logger=None):
+        self.dynamics = {}
+        self.emit = emit
+        self.logger = logger
+        self.sources = []
+        if boats:
+            self.sources.append(BoatSource(self))
+        if grid is not None:
+            self.sources.append(TerrainSource(grid))
+        self._last_seen = {}
+
+    def register(self, dyn):
+        """Add a boat; its ``name`` must be unique."""
+        self.dynamics[dyn.name] = dyn
+
+    def resolve(self, dyn, last_lat, last_lon, timestamp, delta_t):
+        """Correct ``dyn`` after a sub-step that took it from ``last``.
+
+        Position, speed and acceleration of ``dyn`` are changed in place;
+        nothing else is.
+        """
+        if not self.sources or not delta_t:
+            return
+        if not all(math.isfinite(v) for v in (
+                dyn.latitude, dyn.longitude, dyn.heading, dyn.speed,
+                last_lat, last_lon)):
+            return
+        tide = 0.0
+        if dyn.environment is not None:
+            tide = dyn.environment.getTide(timestamp)
+        step = _Step(dyn, (last_lat, last_lon), tide)
+
+        lat, lon = dyn.latitude, dyn.longitude
+        contacts = []
+        for source in self.sources:
+            lat, lon, found = source.correct(step, lat, lon)
+            contacts.extend(found)
+        if not contacts:
+            return
+        if not all(math.isfinite(v) for v in (lat, lon)):
+            raise ArithmeticError('contact moved the boat to a non-finite '
+                                  'position')
+
+        forward = (math.sin(dyn.heading), math.cos(dyn.heading))
+        velocity = (dyn.speed * forward[0], dyn.speed * forward[1])
+        speed0 = dyn.speed
+        for contact in contacts:
+            normal = contact.normal
+            relative = (velocity[0] - contact.other_velocity[0],
+                        velocity[1] - contact.other_velocity[1])
+            closing = max(0.0, -(relative[0] * normal[0]
+                                 + relative[1] * normal[1]))
+            along = forward[0] * normal[0] + forward[1] * normal[1]
+            if dyn.speed * along < 0.0:
+                dyn.speed *= 1.0 - along * along
+            self._report(dyn, contact, closing, lat, lon, timestamp)
+        dyn.latitude, dyn.longitude = lat, lon
+        dyn.a += (dyn.speed - speed0) / delta_t
+
+    def _report(self, dyn, contact, closing, lat, lon, timestamp):
+        key = (dyn.name, contact.kind, contact.other)
+        now = timestamp.nanoseconds
+        last = self._last_seen.get(key)
+        self._last_seen[key] = now
+        if last is not None and now - last <= CONTACT_RELEASE_NS:
+            return
+        if self.logger is not None:
+            what = ('boat ' + contact.other if contact.kind == KIND_BOAT
+                    else 'the bottom or shore')
+            self.logger.info(
+                'asv_sim platform {!r} touched {} at {:.1f} m/s'.format(
+                    dyn.name, what, closing))
+        if self.emit is not None:
+            self.emit({
+                'stamp': timestamp, 'platform': dyn.name,
+                'kind': contact.kind, 'other': contact.other,
+                'latitude': math.degrees(lat),
+                'longitude': math.degrees(lon),
+                'closing_speed': closing,
+                'water_depth': contact.water_depth})
diff --git a/asv_sim/asv_sim/dynamics.py b/asv_sim/asv_sim/dynamics.py
index 2a98b5e..c1c02e1 100644
--- a/asv_sim/asv_sim/dynamics.py
+++ b/asv_sim/asv_sim/dynamics.py
@@ -39,15 +39,19 @@ class Dynamics(object):
 
     def __init__(self, mdl: model.Model,
                  env: environment.Environment = None, start=None,
-                 name='', logger=None):
+                 name='', logger=None, contact=None):
         """Initialize the simulation with a model and optional environment.
 
         :param name: Platform name, used in log messages.
         :param logger: Object with ``warning`` and ``error`` methods (an
             rclpy logger or a ``logging.Logger``). Defaults to the
             ``asv_sim.dynamics`` Python logger.
+        :param contact: Optional ``asv_sim.collision.Collisions``; after each
+            integration sub-step it keeps the boat out of whatever it would
+            otherwise have moved into. ``None``: nothing blocks the boat.
         """
         self.name = name
+        self.contact = contact
         self.logger = logger or logging.getLogger('asv_sim.dynamics')
         self._last_logged = {}
         # Portsmouth, New Hampshire, cod rock
@@ -197,6 +201,25 @@ class Dynamics(object):
 
         return diagnostics
 
+    def _resolve_contact(self, last_lat, last_long, delta_t):
+        """Let the contact resolver correct the sub-step just taken.
+
+        A failure in contact code must not look like a numerical excursion
+        (which resets the boat to rest) or end the node: it is logged and
+        the uncorrected step stands.
+        """
+        if self.contact is None:
+            return
+        try:
+            self.contact.resolve(
+                self, last_lat, last_long, self.last_update, delta_t)
+        except Exception as e:  # noqa: B902 - contact must never end the node
+            self._log(
+                'error', 'contact',
+                'asv_sim platform {!r}: contact resolution failed ({}: {}); '
+                'the step is kept as integrated'.format(
+                    self.name, type(e).__name__, e))
+
     def _log(self, level, key, message):
         """Log at most once per ``_LOG_INTERVAL`` seconds for each key."""
         now = time.monotonic()
@@ -541,6 +564,7 @@ class Dynamics(object):
                         self.longitude, self.latitude,
                         current_direction, current_speed * delta_t)
             self._require_finite()
+            self._resolve_contact(last_lat, last_long, delta_t)
             self.cog, self.sog = geodesic.inverse(
                 last_long, last_lat, self.longitude, self.latitude)
             self.sog /= delta_t
diff --git a/asv_sim/asv_sim/model.py b/asv_sim/asv_sim/model.py
index 4fbafbb..b290176 100644
--- a/asv_sim/asv_sim/model.py
+++ b/asv_sim/asv_sim/model.py
@@ -7,15 +7,23 @@ from rcl_interfaces.msg import FloatingPointRange
 from rcl_interfaces.msg import IntegerRange
 from rcl_interfaces.msg import Parameter
 from rcl_interfaces.msg import ParameterDescriptor
+from rcl_interfaces.msg import SetParametersResult
 import rclpy.node
 
 
+# Hull defaults: the C-Worker 4 (4 m long, 1.7 m wide, 0.4 m draft; cw4.yaml).
+DEFAULT_LENGTH = 4.0
+DEFAULT_BEAM = 1.7
+DEFAULT_DRAFT = 0.4
+
+
 class Model:
 
     def __init__(self, name: str, node: rclpy.node.Node):
         self.name = name
         self.parameters_ready = False
 
+        node.add_on_set_parameters_callback(self.validateParameters)
         node.add_post_set_parameters_callback(self.updateParameters)
 
         node.declare_parameter(
@@ -139,12 +147,40 @@ class Model:
                 integer_range=[IntegerRange(
                     from_value=1, to_value=10000, step=1)]))
 
+        for key, default, text in (
+                ('length', DEFAULT_LENGTH, 'Hull length in metres; with '
+                 'beam it sets the contact footprint (a capsule)'),
+                ('beam', DEFAULT_BEAM, 'Hull width in metres'),
+                ('draft', DEFAULT_DRAFT, 'Depth of the keel below the '
+                 'water line in metres; the boat grounds where the water '
+                 'is shallower')):
+            node.declare_parameter(
+                self.ns(key), default,
+                ParameterDescriptor(
+                    description=text,
+                    floating_point_range=[FloatingPointRange(
+                        from_value=0.01, to_value=1000.0, step=0.0)]))
+
         self.parameters_ready = True
         self.update_coefficients()
 
     def ns(self, key: str) -> str:
         return 'models.' + self.name + '.' + key
 
+    def validateParameters(self, parameters: List[Parameter]):
+        """Refuse a hull longer than it is wide the wrong way round."""
+        values = {p.name: p.value for p in parameters}
+        length = values.get(
+            self.ns('length'), getattr(self, 'length', DEFAULT_LENGTH))
+        beam = values.get(
+            self.ns('beam'), getattr(self, 'beam', DEFAULT_BEAM))
+        if length < beam:
+            return SetParametersResult(
+                successful=False,
+                reason='models.{}: length {} is shorter than beam {}'.format(
+                    self.name, length, beam))
+        return SetParametersResult(successful=True)
+
     def updateParameters(self, parameters: List[Parameter]):
         need_update = False
         for param in parameters:
@@ -209,6 +245,12 @@ class Model:
             if param.name == self.ns('drag_noise'):
                 self.drag_noise = param.value
                 need_update = True
+            if param.name == self.ns('length'):
+                self.length = param.value
+            if param.name == self.ns('beam'):
+                self.beam = param.value
+            if param.name == self.ns('draft'):
+                self.draft = param.value
             if param.name == self.ns('max_step'):
                 self.max_step = param.value
             if param.name == self.ns('max_substeps'):
diff --git a/asv_sim/asv_sim/platform.py b/asv_sim/asv_sim/platform.py
index efdcb84..298bb10 100644
--- a/asv_sim/asv_sim/platform.py
+++ b/asv_sim/asv_sim/platform.py
@@ -92,7 +92,8 @@ class Platform:
 
         self.dynamics = asv_sim.dynamics.Dynamics(
             self.model, node.environment, start, name=self.name,
-            logger=node.get_logger())
+            logger=node.get_logger(), contact=node.collisions)
+        node.collisions.register(self.dynamics)
 
         self.diag_publishers = {}
         self.have_commands_pub = node.create_publisher(
diff --git a/asv_sim/config/coastal_surveyor.yaml b/asv_sim/config/coastal_surveyor.yaml
index 4dcd7bf..b6b6e71 100644
--- a/asv_sim/config/coastal_surveyor.yaml
+++ b/asv_sim/config/coastal_surveyor.yaml
@@ -23,3 +23,6 @@ asv_sim:
     models.coastal_surveyor.max_rudder_angle:     30.0
     models.coastal_surveyor.rudder_distance:      6.0
     models.coastal_surveyor.rudder_coefficient:   0.25
+
+    # models.<name>.length, beam and draft (contact footprint, issue #111) are not
+    # set here: the 4.0 x 1.7 x 0.4 m defaults apply and are NOT verified for this boat.
diff --git a/asv_sim/config/cw4.yaml b/asv_sim/config/cw4.yaml
index e242853..aa342f7 100644
--- a/asv_sim/config/cw4.yaml
+++ b/asv_sim/config/cw4.yaml
@@ -33,3 +33,8 @@ asv_sim:
     models.cw4.max_rudder_change_rate: 30.0
     models.cw4.max_turn_rate:          25.0
     models.cw4.rudder_distance:        2.0
+
+    # Contact footprint and draft (issue #111), from the notes at the top.
+    models.cw4.length:                 4.0
+    models.cw4.beam:                   1.7
+    models.cw4.draft:                  0.4
diff --git a/asv_sim/config/demo.yaml b/asv_sim/config/demo.yaml
index 5ea3aba..57c900e 100644
--- a/asv_sim/config/demo.yaml
+++ b/asv_sim/config/demo.yaml
@@ -30,3 +30,9 @@ asv_sim:
     models.demo.max_rudder_change_rate: 30.0
     models.demo.max_turn_rate:          25.0
     models.demo.rudder_distance:        2.0
+
+    # Contact footprint and draft (issue #111): the C-Worker 4 hull, as in
+    # cw4.yaml. A boat grounds where grid depth + tide is less than the draft.
+    models.demo.length:                 4.0
+    models.demo.beam:                   1.7
+    models.demo.draft:                  0.4
diff --git a/asv_sim/config/drix.yaml b/asv_sim/config/drix.yaml
index 844f395..ce6ca63 100644
--- a/asv_sim/config/drix.yaml
+++ b/asv_sim/config/drix.yaml
@@ -37,3 +37,6 @@ asv_sim:
     models.drix.max_rudder_angle:       30.0
     models.drix.max_rudder_change_rate: 90.0
     models.drix.rudder_coefficient:     0.25
+
+    # models.<name>.length, beam and draft (contact footprint, issue #111) are not
+    # set here: the 4.0 x 1.7 x 0.4 m defaults apply and are NOT verified for this boat.
diff --git a/asv_sim/config/echoboat240.yaml b/asv_sim/config/echoboat240.yaml
index 9d089a2..ddcf612 100644
--- a/asv_sim/config/echoboat240.yaml
+++ b/asv_sim/config/echoboat240.yaml
@@ -68,3 +68,6 @@ asv_sim:
     models.echoboat240.thrust_noise:        0.1
     models.echoboat240.yaw_rate_noise:      0.1
     models.echoboat240.drag_noise:          0.1
+
+    # models.<name>.length, beam and draft (contact footprint, issue #111) are not
+    # set here: the 4.0 x 1.7 x 0.4 m defaults apply and are NOT verified for this boat.
diff --git a/asv_sim/package.xml b/asv_sim/package.xml
index 47a1bf2..bc5c7be 100644
--- a/asv_sim/package.xml
+++ b/asv_sim/package.xml
@@ -13,11 +13,15 @@
   <depend>sensor_msgs</depend>
   <depend>std_msgs</depend>
   <depend>python3-transforms3d</depend>
+  <!-- Only needed when collision.grid_file is set (BathyGrid reader). -->
+  <exec_depend>mbes_sim</exec_depend>
 
   <test_depend>ament_copyright</test_depend>
   <test_depend>ament_flake8</test_depend>
   <test_depend>ament_pep257</test_depend>
   <test_depend>python3-pytest</test_depend>
+  <test_depend>python3-gdal</test_depend>
+  <test_depend>python3-numpy</test_depend>
   <test_depend>launch_testing</test_depend>
   <test_depend>launch_testing_ros</test_depend>
   <test_depend>launch_ros</test_depend>
diff --git a/asv_sim/test/synthetic_grid.py b/asv_sim/test/synthetic_grid.py
new file mode 100644
index 0000000..779b8f7
--- /dev/null
+++ b/asv_sim/test/synthetic_grid.py
@@ -0,0 +1,59 @@
+"""A synthetic bathymetry GeoTIFF for the collision tests (issue #111).
+
+UTM 19N, 2 m cells, 600 m square, built around an origin near Portsmouth
+Harbour:
+
+- water 10 m deep west of a straight shore at ``SHORE_EAST`` m east of the
+  origin (grid east, a degree or so off true east: UTM grid convergence);
+- land (depth -2 m) east of it, with a 1 m deep shelf from ``SHELF_EAST``;
+- nodata (-9999) north of ``NODATA_NORTH`` m.
+"""
+
+import math
+
+import numpy as np
+from osgeo import gdal
+from osgeo import osr
+
+# Portsmouth Harbour (the demo's start area).
+LAT0 = 43.0743
+LON0 = -70.7108
+CELL = 2.0
+SHORE_EAST = 50.0
+SHELF_EAST = 30.0
+NODATA_NORTH = 120.0
+HALF = 300.0
+
+
+def write_grid(path):
+    """Write the grid to ``path``; return the (lat, lon) of its origin."""
+    gdal.UseExceptions()
+    geographic = osr.SpatialReference()
+    geographic.SetWellKnownGeogCS('WGS84')
+    utm = osr.SpatialReference()
+    utm.ImportFromEPSG(32619)
+    forward = osr.CoordinateTransformation(geographic, utm)
+    inverse = osr.CoordinateTransformation(utm, geographic)
+    x0, y0 = forward.TransformPoint(LAT0, LON0)[:2]
+    x0 = math.floor(x0 / CELL) * CELL
+    y0 = math.floor(y0 / CELL) * CELL
+    lat, lon = inverse.TransformPoint(x0, y0)[:2]
+
+    count = int(2 * HALF / CELL)
+    east = CELL * (np.arange(count) + 0.5) - HALF
+    north = HALF - CELL * (np.arange(count) + 0.5)
+    e, n = np.meshgrid(east, north)
+    data = np.full(e.shape, 10.0, dtype=np.float32)
+    data[(e >= SHELF_EAST) & (e < SHORE_EAST)] = 1.0
+    data[e >= SHORE_EAST] = -2.0
+    data[n >= NODATA_NORTH] = -9999.0
+
+    dataset = gdal.GetDriverByName('GTiff').Create(
+        path, count, count, 1, gdal.GDT_Float32)
+    dataset.SetGeoTransform((x0 - HALF, CELL, 0.0, y0 + HALF, 0.0, -CELL))
+    dataset.SetProjection(utm.ExportToWkt())
+    band = dataset.GetRasterBand(1)
+    band.SetNoDataValue(-9999.0)
+    band.WriteArray(data)
+    dataset.FlushCache()
+    return lat, lon
diff --git a/asv_sim/test/test_collision.py b/asv_sim/test/test_collision.py
new file mode 100644
index 0000000..1511cc1
--- /dev/null
+++ b/asv_sim/test/test_collision.py
@@ -0,0 +1,484 @@
+"""Contact resolution of ``asv_sim`` (issue #111): blocking only.
+
+Pure geometry, then ``Dynamics`` with a ``Collisions`` resolver on a
+synthetic bathymetry GeoTIFF (UTM 19N, 2 m cells) built here:
+
+- water 10 m deep west of a straight shore at 50 m east of the grid origin;
+- land (depth -2 m) east of it, with a 1 m deep shelf from 30 to 50 m east
+  of the origin;
+- no data north of 120 m.
+
+The grid is a few degrees off true north (UTM grid convergence, 1.2 degrees
+at Portsmouth), so distances to the shore are checked to a cell and a bit.
+
+Runs under plain pytest (``colcon test``); no launch_test runner needed.
+"""
+
+import math
+
+from asv_sim import collision
+from asv_sim import dynamics
+from asv_sim import model
+import pytest
+import rclpy
+import rclpy.node
+from rclpy.parameter import Parameter
+from rclpy.time import Time
+import synthetic_grid
+
+SHORE_EAST = synthetic_grid.SHORE_EAST
+SHELF_EAST = synthetic_grid.SHELF_EAST
+NODATA_NORTH = synthetic_grid.NODATA_NORTH
+TOL = 3.0          # a cell, plus the grid's rotation over the run
+DEFAULT_HULL = (4.0, 1.7, 0.4)
+
+
+class Recorder:
+    """Stand-in for a logger: keeps (level, message) pairs."""
+
+    def __init__(self):
+        self.records = []
+
+    def info(self, message):
+        self.records.append(('info', message))
+
+    def warning(self, message):
+        self.records.append(('warning', message))
+
+    def error(self, message):
+        self.records.append(('error', message))
+
+    def at(self, level):
+        return [m for lv, m in self.records if lv == level]
+
+
+class Tide:
+    """Environment stand-in: a settable tide and nothing else."""
+
+    def __init__(self, level=0.0):
+        self.level = level
+
+    def getTide(self, timestamp):  # noqa: N802
+        return self.level
+
+    def getCurrent(self, lat, lon, apply_noise):  # noqa: N802
+        return None
+
+    def getWaves(self, timestamp):  # noqa: N802
+        return {'heave': 0.0, 'roll': 0.0, 'pitch': 0.0}
+
+    def getEllipsoidalAltitude(self, timestamp):  # noqa: N802
+        return 0.0
+
+
+def ns(seconds):
+    return Time(nanoseconds=int(round(seconds * 1e9)))
+
+
+@pytest.fixture
+def mdl():
+    rclpy.init()
+    node = rclpy.node.Node('collision_test')
+    try:
+        yield model.Model('demo', node)
+    finally:
+        node.destroy_node()
+        rclpy.shutdown()
+
+
+@pytest.fixture(scope='module')
+def origin_and_grid(tmp_path_factory):
+    path = str(tmp_path_factory.mktemp('grid') / 'truth.tif')
+    lat, lon = synthetic_grid.write_grid(path)
+    return lat, lon, path
+
+
+@pytest.fixture
+def world(origin_and_grid):
+    from mbes_sim.bathy_grid import BathyGrid
+    lat, lon, path = origin_and_grid
+    return lat, lon, BathyGrid(path)
+
+
+class Rig:
+    """Boats on the synthetic grid, stepped by hand."""
+
+    def __init__(self, mdl, world, boats=True, terrain=True, tide=0.0):
+        self.lat0, self.lon0, grid = world
+        self.mdl = mdl
+        self.log = Recorder()
+        self.events = []
+        self.collisions = collision.Collisions(
+            grid=grid if terrain else None, boats=boats,
+            emit=self.events.append, logger=self.log)
+        self.env = Tide(tide)
+        self.boats = {}
+        self.frozen = {}
+        self.t = 0.0
+
+    def add(self, name, east, north, heading, frozen=False):
+        """Add a boat; a frozen one stays put (a moored target)."""
+        d = dynamics.Dynamics(
+            self.mdl, self.env, name=name, logger=self.log,
+            contact=self.collisions)
+        self.collisions.register(d)
+        self.place(d, east, north, heading)
+        self.boats[name] = d
+        if frozen:
+            self.frozen[name] = (d.latitude, d.longitude)
+        return d
+
+    def place(self, d, east, north, heading):
+        lat, lon = collision.move_en(
+            math.radians(self.lat0), math.radians(self.lon0), east, north)
+        d.set(math.degrees(lat), math.degrees(lon), heading)
+        d.last_update = None
+
+    def en(self, d):
+        return collision.offset_en(
+            math.radians(self.lat0), math.radians(self.lon0),
+            d.latitude, d.longitude)
+
+    def run(self, seconds, throttles, step=0.05, watch=None):
+        """Step every boat; ``throttles`` maps name to throttle.
+
+        :param watch: Called after every step.
+        """
+        steps = int(round(seconds / step))
+        for _ in range(steps):
+            self.t += step
+            for name, d in self.boats.items():
+                d.update(throttles.get(name, 0.0), 0.0, ns(self.t),
+                         apply_noise=False)
+                if name in self.frozen:
+                    d.speed = 0.0
+                    d.latitude, d.longitude = self.frozen[name]
+            if watch is not None:
+                watch()
+
+
+def overlap(a, b):
+    """Return the capsule overlap in metres of two ``Dynamics`` (0: none)."""
+    east, north = collision.offset_en(
+        a.latitude, a.longitude, b.latitude, b.longitude)
+    hit = collision.capsule_penetration(
+        collision.capsule_axis((0.0, 0.0), a.heading, a.model.length,
+                               a.model.beam),
+        collision.capsule_axis((east, north), b.heading, b.model.length,
+                               b.model.beam))
+    return 0.0 if hit is None else hit[0]
+
+
+# geometry ------------------------------------------------------------------
+
+def test_capsules_side_by_side_overlap_by_the_missing_gap():
+    a = collision.capsule_axis((0.0, 0.0), 0.0, 4.0, 1.7)
+    b = collision.capsule_axis((1.0, 0.0), 0.0, 4.0, 1.7)
+    depth, normal = collision.capsule_penetration(a, b)
+    assert depth == pytest.approx(0.7)
+    assert normal == pytest.approx((-1.0, 0.0))
+
+
+@pytest.mark.parametrize('gap, depth', [(3.0, 1.0), (4.0, None),
+                                        (5.0, None)])
+def test_capsules_end_to_end_touch_at_the_length(gap, depth):
+    a = collision.capsule_axis((0.0, 0.0), 0.0, 4.0, 1.7)
+    b = collision.capsule_axis((0.0, gap), 0.0, 4.0, 1.7)
+    hit = collision.capsule_penetration(a, b)
+    if depth is None:
+        assert hit is None
+    else:
+        assert hit[0] == pytest.approx(depth)
+        assert hit[1] == pytest.approx((0.0, -1.0))
+
+
+def test_capsules_with_crossing_axes_still_separate():
+    a = collision.capsule_axis((0.0, 0.0), 0.0, 4.0, 1.7)
+    b = collision.capsule_axis((0.0, 0.0), math.pi / 2, 4.0, 1.7)
+    depth, normal = collision.capsule_penetration(a, b)
+    assert depth == pytest.approx(1.7)
+    assert math.hypot(*normal) == pytest.approx(1.0)
+
+
+def test_degenerate_segments_do_not_divide_by_zero():
+    point = ((1.0, 1.0), (1.0, 1.0))
+    assert collision.segment_closest(
+        point[0], point[1], (0.0, 0.0), (0.0, 0.0)) == (
+        (1.0, 1.0), (0.0, 0.0))
+    near, far = collision.segment_closest(
+        (0.0, 0.0), (0.0, 0.0), (1.0, -1.0), (1.0, 1.0))
+    assert near == (0.0, 0.0) and far == pytest.approx((1.0, 0.0))
+
+
+# boat to boat --------------------------------------------------------------
+
+def test_boats_driven_at_each_other_never_overlap_and_stop_touching(
+        mdl, world):
+    rig = Rig(mdl, world, terrain=False)
+    a = rig.add('a', -15.0, 0.0, 90.0)
+    b = rig.add('b', 15.0, 0.0, 270.0)
+    worst = [0.0]
+
+    def watch():
+        worst[0] = max(worst[0], overlap(a, b))
+
+    rig.run(30.0, {'a': 1.0, 'b': 1.0}, watch=watch)
+    assert worst[0] < 0.05
+    ea, na = rig.en(a)
+    eb, nb = rig.en(b)
+    # bow to bow: two lengths of hull between the centres at least
+    assert math.hypot(eb - ea, nb - na) == pytest.approx(4.0, abs=0.1)
+    assert abs(a.speed) < 0.2 and abs(b.speed) < 0.2
+
+
+def test_a_boat_can_always_back_out_of_contact(mdl, world):
+    rig = Rig(mdl, world, terrain=False)
+    a = rig.add('a', -8.0, 0.0, 90.0)
+    b = rig.add('b', 0.0, 0.0, 90.0, frozen=True)
+    rig.run(10.0, {'a': 1.0})
+    before = math.hypot(*[x - y for x, y in zip(rig.en(a), rig.en(b))])
+    rig.run(10.0, {'a': -1.0})
+    after = math.hypot(*[x - y for x, y in zip(rig.en(a), rig.en(b))])
+    assert after > before + 3.0
+    assert overlap(a, b) == 0.0
+
+
+def test_the_other_boat_is_not_moved_by_a_contact(mdl, world):
+    rig = Rig(mdl, world, terrain=False)
+    rig.add('a', -8.0, 0.0, 90.0)
+    b = rig.add('b', 0.0, 0.0, 90.0)
+    rig.run(10.0, {'a': 1.0})
+    # the same boat alone (idle thrust creeps it forward either way)
+    twin = Rig(mdl, world, terrain=False)
+    twin_b = twin.add('b', 0.0, 0.0, 90.0)
+    twin.run(10.0, {})
+    assert rig.en(b) == pytest.approx(twin.en(twin_b), abs=1e-6)
+
+
+def test_boats_placed_on_top_of_each_other_are_pushed_apart(mdl, world):
+    rig = Rig(mdl, world, terrain=False)
+    a = rig.add('a', 0.0, 0.0, 0.0)
+    b = rig.add('b', 0.3, 0.0, 0.0)
+    rig.run(1.0, {})
+    assert overlap(a, b) < 1e-6 and overlap(b, a) < 1e-6
+    assert rig.events and rig.events[0]['kind'] == collision.KIND_BOAT
+
+
+def test_boats_pass_through_each_other_when_boats_are_off(mdl, world):
+    rig = Rig(mdl, world, boats=False, terrain=False)
+    a = rig.add('a', -8.0, 0.0, 90.0)
+    rig.add('b', 0.0, 0.0, 90.0)
+    rig.run(10.0, {'a': 1.0})
+    assert rig.en(a)[0] > 3.0
+    assert not rig.events
+
+
+def test_a_stalled_gap_does_not_tunnel_through_a_boat(mdl, world):
+    rig = Rig(mdl, world, terrain=False)
+    a = rig.add('a', -20.0, 0.0, 90.0)
+    b = rig.add('b', 0.0, 0.0, 90.0, frozen=True)
+    a.speed = 2.75
+    a.update(1.0, 0.0, ns(0.0), apply_noise=False)
+    a.update(1.0, 0.0, ns(10.0), apply_noise=False)
+    assert rig.en(a)[0] < rig.en(b)[0]
+    assert overlap(a, b) < 0.05
+
+
+# terrain -------------------------------------------------------------------
+
+def bow_east(rig, d):
+    return rig.en(d)[0] + d.model.length / 2.0
+
+
+def test_a_boat_driven_at_the_shore_stops_at_it(mdl, world):
+    rig = Rig(mdl, world)
+    a = rig.add('a', 0.0, 0.0, 90.0)
+    rig.run(40.0, {'a': 1.0})
+    assert bow_east(rig, a) <= SHORE_EAST + TOL
+    assert bow_east(rig, a) >= SHELF_EAST + 10.0
+    assert abs(a.speed) < 0.3
+
+
+def test_a_boat_at_forty_five_degrees_slides_along_the_shore(mdl, world):
+    rig = Rig(mdl, world)
+    a = rig.add('a', 0.0, 0.0, 45.0)
+    rig.run(30.0, {'a': 1.0})
+    east, north = rig.en(a)
+    assert north > 15.0
+    assert east + 2.0 <= SHORE_EAST + TOL
+
+
+def test_a_boat_that_hit_the_shore_can_back_off(mdl, world):
+    rig = Rig(mdl, world)
+    a = rig.add('a', 0.0, 0.0, 90.0)
+    rig.run(40.0, {'a': 1.0})
+    stuck = rig.en(a)[0]
+    rig.run(10.0, {'a': -1.0})
+    assert rig.en(a)[0] < stuck - 3.0
+
+
+def test_no_data_is_a_wall(mdl, world):
+    rig = Rig(mdl, world)
+    a = rig.add('a', 0.0, 0.0, 0.0)
+    rig.run(60.0, {'a': 1.0})
+    assert rig.en(a)[1] + 2.0 <= NODATA_NORTH + TOL
+
+
+def test_a_boat_off_the_grid_cannot_go_further_off_it(mdl, world):
+    rig = Rig(mdl, world)
+    a = rig.add('a', 0.0, 0.0, 270.0)
+    rig.run(120.0, {'a': 1.0})
+    # the grid ends 300 m west of the origin
+    assert rig.en(a)[0] - 2.0 >= -300.0 - TOL
+
+
+def test_a_boat_that_starts_aground_may_leave_but_not_go_shallower(
+        mdl, world):
+    rig = Rig(mdl, world)
+    a = rig.add('a', 60.0, 0.0, 270.0)
+    rig.run(40.0, {'a': 1.0})
+    assert rig.en(a)[0] < SHORE_EAST - 5.0
+
+    b = rig.add('b', 60.0, 20.0, 90.0)
+    here = rig.en(b)[0]
+    rig.run(10.0, {'b': 1.0})
+    assert rig.en(b)[0] >= here
+
+
+def test_low_tide_grounds_a_boat_on_the_shelf_and_high_tide_frees_it(
+        mdl, world):
+    rig = Rig(mdl, world, tide=-0.8)
+    a = rig.add('a', 0.0, 0.0, 90.0)
+    rig.run(40.0, {'a': 1.0})
+    assert bow_east(rig, a) <= SHELF_EAST + TOL
+    rig.env.level = 0.0
+    rig.run(20.0, {'a': 1.0})
+    assert bow_east(rig, a) > SHELF_EAST + 8.0
+
+
+def test_draft_decides_where_a_boat_grounds(mdl, world):
+    mdl.draft = 1.5
+    rig = Rig(mdl, world)
+    a = rig.add('a', 0.0, 0.0, 90.0)
+    rig.run(40.0, {'a': 1.0})
+    assert bow_east(rig, a) <= SHELF_EAST + TOL
+
+
+def test_a_stalled_gap_does_not_tunnel_through_the_shore(mdl, world):
+    rig = Rig(mdl, world)
+    a = rig.add('a', 25.0, 0.0, 90.0)
+    a.speed = 2.75
+    a.update(1.0, 0.0, ns(0.0), apply_noise=False)
+    a.update(1.0, 0.0, ns(10.0), apply_noise=False)
+    assert bow_east(rig, a) <= SHORE_EAST + TOL
+
+
+def test_nothing_blocks_a_boat_without_a_resolver(mdl, world):
+    d = dynamics.Dynamics(mdl, Tide(), name='free', logger=Recorder())
+    d.set(world[0], world[1], 90.0)
+    d.speed = 2.0
+    run_to = 0.0
+    d.update(1.0, 0.0, ns(run_to), apply_noise=False)
+    for i in range(1, 400):
+        d.update(1.0, 0.0, ns(i * 0.05), apply_noise=False)
+    assert d.speed > 2.0
+
+
+def test_a_boat_is_never_damaged_or_reset(mdl, world):
+    rig = Rig(mdl, world)
+    a = rig.add('a', 0.0, 0.0, 90.0)
+    rig.run(40.0, {'a': 1.0})
+    stuck = rig.en(a)
+    rig.run(5.0, {'a': 1.0})
+    # still where it was, still able to move when told to
+    assert rig.en(a) == pytest.approx(stuck, abs=0.2)
+    rig.run(5.0, {'a': -1.0})
+    assert rig.en(a)[0] < stuck[0]
+    assert not rig.log.at('error')
+
+
+# events --------------------------------------------------------------------
+
+def test_one_event_per_contact_not_one_per_step(mdl, world):
+    rig = Rig(mdl, world)
+    rig.add('a', 0.0, 0.0, 90.0)
+    rig.run(40.0, {'a': 1.0})
+    terrain = [e for e in rig.events if e['kind'] == collision.KIND_TERRAIN]
+    assert len(terrain) == 1
+    event = terrain[0]
+    assert event['platform'] == 'a' and event['other'] == ''
+    assert event['closing_speed'] > 0.0
+    assert math.isfinite(event['latitude'])
+    assert len(rig.log.at('info')) == 1
+
+
+def test_a_second_contact_after_separating_is_a_second_event(mdl, world):
+    rig = Rig(mdl, world)
+    rig.add('a', 0.0, 0.0, 90.0)
+    rig.run(40.0, {'a': 1.0})
+    rig.run(8.0, {'a': -1.0})
+    rig.run(20.0, {'a': 1.0})
+    assert len(rig.events) == 2
+
+
+def test_a_boat_contact_names_the_other_boat(mdl, world):
+    rig = Rig(mdl, world, terrain=False)
+    rig.add('a', -8.0, 0.0, 90.0)
+    rig.add('b', 0.0, 0.0, 90.0, frozen=True)
+    rig.run(10.0, {'a': 1.0})
+    assert len(rig.events) == 1
+    assert rig.events[0]['other'] == 'b'
+    assert rig.events[0]['kind'] == collision.KIND_BOAT
+
+
+# robustness ----------------------------------------------------------------
+
+class Broken:
+
+    def resolve(self, *args):
+        raise ValueError('contact bug')
+
+
+def test_a_failure_in_contact_code_is_logged_and_does_not_reset_the_boat(
+        mdl):
+    log = Recorder()
+    d = dynamics.Dynamics(mdl, name='boat', logger=log, contact=Broken())
+    d.update(1.0, 0.0, ns(0.0), apply_noise=False)
+    for i in range(1, 100):
+        d.update(1.0, 0.0, ns(i * 0.05), apply_noise=False)
+    assert d.speed > 0.1
+    errors = log.at('error')
+    assert len(errors) == 1 and 'contact resolution failed' in errors[0]
+
+
+def test_a_boat_with_a_non_finite_position_is_left_alone(mdl, world):
+    rig = Rig(mdl, world)
+    a = rig.add('a', 0.0, 0.0, 90.0)
+    a.latitude = math.nan
+    rig.collisions.resolve(a, 0.7, -1.2, ns(1.0), 0.05)
+    assert math.isnan(a.latitude)
+
+
+# parameters ----------------------------------------------------------------
+
+def test_the_hull_defaults_are_the_cworker_4(mdl):
+    assert (mdl.length, mdl.beam, mdl.draft) == DEFAULT_HULL
+
+
+def test_a_hull_shorter_than_it_is_wide_is_refused():
+    rclpy.init()
+    node = rclpy.node.Node('collision_param_test')
+    try:
+        mdl = model.Model('demo', node)
+        for name, value in (('length', 1.0), ('beam', 5.0),
+                            ('draft', 0.0), ('beam', -1.0)):
+            result = node.set_parameters(
+                [Parameter('models.demo.' + name, value=value)])[0]
+            assert not result.successful, (name, value)
+        assert (mdl.length, mdl.beam) == DEFAULT_HULL[:2]
+        assert node.set_parameters(
+            [Parameter('models.demo.length', value=6.0)])[0].successful
+        assert mdl.length == 6.0
+    finally:
+        node.destroy_node()
+        rclpy.shutdown()
diff --git a/asv_sim/test/test_multi_platform.py b/asv_sim/test/test_multi_platform.py
index a293e78..0ded76c 100644
--- a/asv_sim/test/test_multi_platform.py
+++ b/asv_sim/test/test_multi_platform.py
@@ -19,6 +19,7 @@ import pathlib
 import time
 
 from asv_sim.asv_sim_node import AsvSim
+from asv_sim_msgs.msg import Collision
 from asv_sim_msgs.srv import SetPose
 import pytest
 import rclpy
@@ -26,6 +27,7 @@ from rclpy.executors import SingleThreadedExecutor
 from sensor_msgs.msg import NavSatFix
 from std_msgs.msg import Bool
 from std_msgs.msg import Float32
+import synthetic_grid
 import yaml
 
 DEMO_CONFIG = pathlib.Path(__file__).resolve().parents[1] / 'config' / 'demo.yaml'
@@ -44,10 +46,11 @@ MODELS = {'alpha': 'demo', 'bravo': 'demo', 'charlie': 'demo_fast'}
 FAST_MAX_SPEED = 4.0
 
 
-def _write_platform_file(path):
+def _write_platform_file(path, extra=None):
     # asv_sim defaults to a 1 m/s current; drift would swamp the isolation
     # checks, so switch it off.
     params = {'platforms': list(PLATFORMS), 'environment.current.speed': 0.0}
+    params.update(extra or {})
     demo = yaml.safe_load(DEMO_CONFIG.read_text())['asv_sim']['ros__parameters']
     for key, value in demo.items():
         params[key.replace('models.demo.', 'models.demo_fast.', 1)] = value
@@ -71,9 +74,9 @@ def _metres(a, b):
 class Rig:
     """The node under test, a driver node and the spin helper."""
 
-    def __init__(self, tmp_path):
+    def __init__(self, tmp_path, extra=None):
         platform_file = tmp_path / 'platforms.yaml'
-        _write_platform_file(platform_file)
+        _write_platform_file(platform_file, extra)
         rclpy.init(args=[
             '--ros-args',
             '--params-file', str(DEMO_CONFIG),
@@ -95,6 +98,9 @@ class Rig:
         self.executor.add_node(self.driver)
 
         self.fixes = {}
+        self.collisions = []
+        self.driver.create_subscription(
+            Collision, '/asv_sim/collisions', self.collisions.append, 10)
         self.throttle_pubs = {}
         self.reset_pubs = {}
         self.pose_clients = {}
@@ -336,3 +342,108 @@ def test_demo_config_keys_are_declared_model_parameters(rig):
     assert keys
     undeclared = [k for k in keys if not rig.sim.has_parameter(k)]
     assert undeclared == []
+
+
+# contact (issue #111) -------------------------------------------------------
+
+# Dynamics noise would turn a head-on meeting into a glancing one that slides
+# past; the contact tests want it exact.
+NO_NOISE = {'models.demo.%s_noise' % k: 0.0
+            for k in ('thrust', 'yaw_rate', 'drag')}
+
+
+@pytest.fixture
+def quiet_rig(tmp_path):
+    r = None
+    try:
+        r = Rig(tmp_path, NO_NOISE)
+        r.wait_for_fixes()
+        yield r
+    finally:
+        if r is not None:
+            r.close()
+
+
+def _east_of(lat, lon, metres):
+    return lat, lon + metres / (111320.0 * math.cos(math.radians(lat)))
+
+
+def _drive_both(rig, seconds, a_throttle, b_throttle):
+    deadline = time.monotonic() + seconds
+    while time.monotonic() < deadline:
+        rig.throttle_pubs['alpha'].publish(Float32(data=a_throttle))
+        rig.throttle_pubs['bravo'].publish(Float32(data=b_throttle))
+        rig.executor.spin_once(timeout_sec=0.05)
+
+
+def test_boats_block_each_other_through_the_node_and_report_it(quiet_rig):
+    rig = quiet_rig
+    lat, lon = 43.0700, -70.7100
+    rig.set_pose('alpha', lat, lon, 90.0)
+    rig.set_pose('bravo', *_east_of(lat, lon, 14.0), 270.0)
+    _drive_both(rig, 8.0, 1.0, 1.0)
+    rig.spin(0.5)
+    alpha = rig.fresh_fix('alpha')
+    bravo = rig.fresh_fix('bravo')
+    gap = _metres(alpha, bravo)
+    # bow to bow: the hulls are 4 m long, so the centres stay 4 m apart
+    assert 3.6 < gap < 4.6, gap
+    events = [(e.platform, e.other) for e in rig.collisions]
+    assert events and set(events) <= {('alpha', 'bravo'), ('bravo', 'alpha')}
+    assert all(e.kind == Collision.KIND_BOAT for e in rig.collisions)
+    assert len(rig.collisions) <= 4, 'one event per contact, not per step'
+
+
+def test_a_boat_can_back_out_through_the_node(quiet_rig):
+    rig = quiet_rig
+    lat, lon = 43.0700, -70.7100
+    rig.set_pose('alpha', lat, lon, 90.0)
+    rig.set_pose('bravo', *_east_of(lat, lon, 14.0), 270.0)
+    _drive_both(rig, 8.0, 1.0, 1.0)
+    before = _metres(rig.fresh_fix('alpha'), rig.fresh_fix('bravo'))
+    _drive_both(rig, 6.0, -1.0, -1.0)
+    after = _metres(rig.fresh_fix('alpha'), rig.fresh_fix('bravo'))
+    assert after > before + 3.0
+
+
+def test_collision_boats_false_lets_boats_pass(tmp_path):
+    r = Rig(tmp_path, dict(NO_NOISE, **{'collision.boats': False}))
+    try:
+        r.wait_for_fixes()
+        lat, lon = 43.0700, -70.7100
+        r.set_pose('alpha', lat, lon, 90.0)
+        r.set_pose('bravo', *_east_of(lat, lon, 14.0), 270.0)
+        _drive_both(r, 8.0, 1.0, 1.0)
+        r.spin(0.5)
+        alpha = r.fresh_fix('alpha')
+        bravo = r.fresh_fix('bravo')
+        assert alpha[1] > bravo[1], 'they passed through each other'
+        assert r.collisions == []
+    finally:
+        r.close()
+
+
+def test_an_unreadable_collision_grid_refuses_to_start(tmp_path):
+    with pytest.raises(Exception):  # noqa: B017 - the GDAL error type
+        Rig(tmp_path, {'collision.grid_file': str(tmp_path / 'absent.tif')})
+    assert not rclpy.ok()
+
+
+def test_the_grid_stops_a_boat_at_the_shore_through_the_node(tmp_path):
+    grid = str(tmp_path / 'truth.tif')
+    lat, lon = synthetic_grid.write_grid(grid)
+    r = Rig(tmp_path, dict(NO_NOISE, **{'collision.grid_file': grid}))
+    try:
+        r.wait_for_fixes()
+        r.set_pose('alpha', *_east_of(lat, lon, 20.0), 90.0)
+        r.drive('alpha', 1.0, 18.0)
+        r.spin(0.5)
+        east = r.fresh_fix('alpha')
+        distance = _metres((lat, lon), east)
+        # the shore is 50 m east of the origin; the bow is 2 m ahead of the
+        # reference point, the grid is a degree off true east
+        assert 40.0 < distance < 51.5, distance  # 20 m start + run
+        kinds = {e.kind for e in r.collisions}
+        assert kinds == {Collision.KIND_TERRAIN}
+    finally:
+        r.close()
diff --git a/asv_sim_msgs/CMakeLists.txt b/asv_sim_msgs/CMakeLists.txt
index e90c863..9de1dc8 100644
--- a/asv_sim_msgs/CMakeLists.txt
+++ b/asv_sim_msgs/CMakeLists.txt
@@ -11,10 +11,12 @@ endif()
 find_package(ament_cmake REQUIRED)
 find_package(geographic_msgs REQUIRED)
 find_package(rosidl_default_generators REQUIRED)
+find_package(std_msgs REQUIRED)
 
 rosidl_generate_interfaces(${PROJECT_NAME}
+  "msg/Collision.msg"
   "srv/SetPose.srv"
-  DEPENDENCIES geographic_msgs
+  DEPENDENCIES geographic_msgs std_msgs
 )
 
 if(BUILD_TESTING)
diff --git a/asv_sim_msgs/msg/Collision.msg b/asv_sim_msgs/msg/Collision.msg
new file mode 100644
index 0000000..ece6c4a
--- /dev/null
+++ b/asv_sim_msgs/msg/Collision.msg
@@ -0,0 +1,28 @@
+# A boat touched something it cannot pass: another boat or the bottom.
+# Published once per contact onset (not once per simulation step) on
+# asv_sim's ~/collisions. Boats are indestructible; this only reports.
+
+std_msgs/Header header
+
+# The boat that was blocked.
+string platform
+
+uint8 KIND_BOAT = 0
+uint8 KIND_TERRAIN = 1
+uint8 kind
+
+# Name of the other boat for KIND_BOAT; empty for KIND_TERRAIN.
+string other
+
+# Where the blocked boat is, degrees.
+float64 latitude
+float64 longitude
+
+# Speed in m/s at which the boat was closing on the obstacle before the
+# contact stopped it.
+float32 closing_speed
+
+# KIND_TERRAIN: water depth (grid depth plus tide) in metres under the
+# hull centre at the place the boat tried to go; NaN where there is no
+# water or no data. KIND_BOAT: NaN.
+float32 water_depth
diff --git a/asv_sim_msgs/package.xml b/asv_sim_msgs/package.xml
index aff63a4..768df88 100644
--- a/asv_sim_msgs/package.xml
+++ b/asv_sim_msgs/package.xml
@@ -11,6 +11,7 @@
   <buildtool_depend>rosidl_default_generators</buildtool_depend>
 
   <depend>geographic_msgs</depend>
+  <depend>std_msgs</depend>
 
   <exec_depend>rosidl_default_runtime</exec_depend>
 
diff --git a/marine_simulation/README.md b/marine_simulation/README.md
index 0d5386e..6c8ee31 100644
--- a/marine_simulation/README.md
+++ b/marine_simulation/README.md
@@ -752,12 +752,27 @@ namespace; `cube_bathymetry` publishes a relative `grid` in `<boat>/sensors/mbes
 `water_surface_frame` and `water_surface_boat_frame`. Starting the scorer and this node
 together with the boats is the single demo launch (issue #94).
 
+### Boats block each other and the shallows
+
+The demo boats cannot pass through each other and cannot go where the water is
+shallower than their draft (0.4 m) at the current tide: land and no-data cells
+of the truth grid are walls. They are indestructible; a contact only stops
+them, and they can back away. The launch hands `asv_sim` the same grid file the
+sonars sample (`collision.grid_file`). `demo.yaml` gives the `demo` model a
+4.0 x 1.7 m hull, 0.4 m draft. The demo tide is sped up (`tide_speed_factor`),
+so the shallows move in and out within a round; at low water a boat can be
+aground and must back out. Contacts are announced on `/asv_sim/collisions`
+(`asv_sim_msgs/msg/Collision`). To let boats pass through each other, start
+`asv_sim` with `collision.boats:=false` (not a launch argument yet; set it in a
+copy of `demo.yaml`). Charted objects (piers, buoys, rocks) are not obstacles
+yet (issue #113). Details: `asv_sim/README.md`.
+
 ### Known limits
 
 - The nav stack is not wired (`enable_nav`); there is no bridge or command bridge, so the operator mode buttons do nothing.
 - The tide topic `/asv_sim/environment/tide_level` is shared by every boat on purpose.
 - `asv_sim`'s `set_pose` service and `sim_reset` topic work per boat (they were both broken before issue #88).
-- Four `mbes_sim` nodes each load the whole truth grid (69 MB for the packaged chart grid, about 27 MB for the demo truth grid); expect memory use to scale with the boat count.
+- Four `mbes_sim` nodes and `asv_sim` each load the whole truth grid (69 MB for the packaged chart grid, about 27 MB for the demo truth grid); expect memory use to scale with the boat count.
 
 ### Tests
 
diff --git a/marine_simulation/launch/demo_boats_launch.py b/marine_simulation/launch/demo_boats_launch.py
index 00ab2de..e08cacc 100644
--- a/marine_simulation/launch/demo_boats_launch.py
+++ b/marine_simulation/launch/demo_boats_launch.py
@@ -316,13 +316,21 @@ def refuse_enable_nav(enable_nav: str) -> None:
 
 
 def asv_sim_parameters(
-        boats: Sequence[Boat], tide_speed_factor: float, current_speed: float) -> dict:
-    """Return the ``asv_sim`` parameters for the selected boats."""
+        boats: Sequence[Boat], tide_speed_factor: float, current_speed: float,
+        grid_file: str = '') -> dict:
+    """
+    Return the ``asv_sim`` parameters for the selected boats.
+
+    ``grid_file`` is the bathymetry the sonars sample; ``asv_sim`` grounds the boats on it
+    (empty: boats still block each other but the sea floor and shore do not stop them).
+    """
     params = {
         'platforms': [b.name for b in boats],
         'environment.tide.speed_factor': tide_speed_factor,
         'environment.current.speed': current_speed,
     }
+    if grid_file:
+        params['collision.grid_file'] = grid_file
     for b in boats:
         prefix = 'platforms.%s.' % b.name
         params[prefix + 'model'] = 'demo'
@@ -615,7 +623,7 @@ def launch_setup(context, *args, **kwargs):
             package='asv_sim', executable='asv_sim', name='asv_sim', emulate_tty=True,
             parameters=[
                 PathJoinSubstitution([FindPackageShare('asv_sim'), 'config', 'demo.yaml']),
-                asv_sim_parameters(boats, tide_speed_factor, current_speed),
+                asv_sim_parameters(boats, tide_speed_factor, current_speed, mbes_grid_file),
             ],
             remappings=asv_sim_remappings(boats)),
     ]
diff --git a/marine_simulation/test/test_demo_boats_launch.py b/marine_simulation/test/test_demo_boats_launch.py
index c15f3e3..f569479 100644
--- a/marine_simulation/test/test_demo_boats_launch.py
+++ b/marine_simulation/test/test_demo_boats_launch.py
@@ -527,6 +527,18 @@ def test_asv_sim_parameters_are_derived_from_the_roster(roster):
         assert params['platforms.%s.model' % b.name] == 'demo'
 
 
+def test_asv_sim_grounds_the_boats_on_the_sonar_grid_when_there_is_one(roster):
+    params = demo.asv_sim_parameters(roster, 10.0, 0.0, '/data/truth.tif')
+    assert params['collision.grid_file'] == '/data/truth.tif'
+    # no grid: the key is left out (asv_sim then keeps terrain collision off)
+    assert 'collision.grid_file' not in demo.asv_sim_parameters(roster, 10.0, 0.0)
+
+
+def test_the_launch_hands_asv_sim_the_grid_the_sonars_use():
+    text = LAUNCH.read_text()
+    assert 'asv_sim_parameters(boats, tide_speed_factor, current_speed, mbes_grid_file)' in text
+
+
 def test_asv_sim_remappings_are_five_per_boat_and_stay_in_the_boats_namespace(roster):
     remaps = demo.asv_sim_remappings(roster)
     assert len(remaps) == 5 * len(roster)
````

## Plan Context

Below is the `## Approach` section of the plan this change is meant
to implement. It is context, not the subject of the review: flag
divergences between the diff and this plan, but do not review the
plan itself.

```markdown

Approved by Roland 2026-10-20 with all ten recommendations, boat-to-boat collision ON by default for every asv_sim launch (terrain stays grid-gated). Charted objects (piers, buoys, rocks awash, wrecks) are not in this PR: follow-up #113.

1. **New `asv_sim/asv_sim/collision.py`** holds all contact logic so `dynamics.py` only gains one hook. Pure functions (no ROS): capsule distance, offset helpers; `BoatSource` and `TerrainSource` classes; a `Collisions` object (owned by the node, created before the platforms) registers each platform's `Dynamics` and resolves contacts; it is the only thing that touches the grid and the event callback (the node turns events into `Collision` messages).

   **Adding an obstacle source later (#113).** `Collisions.resolve` does not know what a boat can hit: it runs the list `Collisions.sources`, each an object with `correct(step, lat, lon)` that takes the position the previous source left and returns the corrected position plus a list of `Contact` tuples (kind, name of what was hit, unit normal pointing away from it, velocity of the obstacle, water depth). `resolve` then applies the same speed rule and the same one-event-per-onset bookkeeping to every contact. Charted objects become a third class beside `BoatSource` and `TerrainSource` (points and polygons from the ENC in lat/lon, a distance test against the hull capsule giving a normal and a depth) that is appended to the list when its data are configured; it needs a new `kind` value in `Collision.msg` and nothing in the resolver or in `Dynamics` changes. Sources run in list order, so the later one corrects the earlier one's result; the order boats, terrain, charted objects is kept.
2. **Where it sits in the integration.** `Dynamics.__init__` takes an optional `contact` object. `_step` calls `contact.resolve(self, last_lat, last_long, timestamp)` once per **sub-step**, right after the position (own motion plus current) is applied and before `cog/sog` are computed, so `sog`/`cog` report the motion actually achieved and a long stalled gap (up to `max_step * max_substeps` = 10 s, 27 m at top speed) is resolved step by step instead of tunnelling through a shore or a hull. Not called when `delta_t is None` (first update, after `set`). `Dynamics.update` wraps the sub-steps in `except (ArithmeticError, ValueError)` that resets the boat to rest, so the hook is called inside its own try/except: a failure in contact code is logged (throttled, `_log`) and the step keeps the uncorrected position; contact code must never reset a boat or end the node. No contact object (the default in `Dynamics` tests) keeps today's behaviour exactly. `set_pose`/`sim_reset` are never blocked; they can place a boat anywhere (including aground) and the next step only stops it getting shallower.
3. **Grid (a).** New node parameter `collision.grid_file` (string, default `''` = terrain collision off, logged once at INFO). Read once at start with `mbes_sim.bathy_grid.BathyGrid` (lazy import so `asv_sim` still runs without `mbes_sim` when no grid is set; `exec_depend mbes_sim`, no cycle: `mbes_sim` does not depend on `asv_sim`). An unreadable file raises at start (a sim silently without terrain is the failure to avoid); live change is not supported. The demo launch passes the same resolved `mbes_grid_file` it gives the sonars, so one truth file drives sonar and grounding. One more copy of the array in the `asv_sim` process (27 MB demo, 69 MB chart). Tide: `Environment.getTide(timestamp)` per update; water depth = grid depth (MLLW, positive down) + tide, the same sum `mbes_sim` uses. The #98 datum caveat (CCOM compilation datum unstated, treated as MLLW) applies and goes in the README.
4. **Footprint and draft (b).** Model parameters `models.<m>.length` (4.0 m), `.beam` (1.7 m), `.draft` (0.4 m), validated: a `floating_point_range` descriptor for > 0 and an `add_on_set_parameters_callback` that rejects a set with `length < beam` (refused with a reason, not clamped; the existing `Model` only has post-set callbacks, so this is the one pre-set validator). The hull is a capsule: axis segment of half-length `(length - beam)/2` along `heading` through the reference position, radius `beam/2` (the position is the model's reference point; no offset parameter, the 0.5 m reference offset on Ben is below the other errors here). `cw4.yaml` and `demo.yaml` carry the values; other model files keep the defaults and get a comment saying the size is unverified.
5. **Boat to boat (c).** A boat resolves only itself, against the *current* positions of the others (they are treated as fixed for that sub-step; each boat gets its own turn in its own update, at most one tick stale). For each other boat: capsule-to-capsule closest points (segments in a local metric frame at the pair, from `geodesic.inverse`); if `distance < r_a + r_b` the stepping boat is moved along the contact normal (other to self) by the penetration, which removes interpenetration and keeps the tangential displacement, so boats touch and slide but cannot pass, and reverse is always free because a move away produces no penetration. Contact that begins overlapped (placed on top of each other by `set_pose`/roster) pushes the stepping boat out by the full penetration on its next step. Contact never changes the other boat. The unit tests run with dynamics noise off; with noise on, a head-on meeting is glancing and the boats slide past each other, which is accepted.
6. **Grounding (c).** `clearance(x, y, heading) = min over 5 hull points (bow, stern, port, starboard, centre) of (water_depth - draft)`, where land (negative or zero water), nodata and off-grid count as a fixed large negative water depth (-10 m), so they are walls. After the step, if clearance at the new position is below 0 **and** below the clearance at the previous position (a boat that starts aground may move anywhere not shallower, so it can always get out), the shallower-going part of the displacement is removed: normal `n` = gradient of clearance (central differences, one grid cell), displacement `d` becomes `d - (d.n) n` if `d.n < 0`; if the slid position is still grounded, or the gradient is zero, the boat stays at the previous position. Hull points and `n` are mapped to metres with a local east/north frame taken from `getXY` of the position and points 1 m east and 1 m north (exact grid rotation, 1.2 degrees at Portsmouth, no UTM-convergence shortcut); the corrected position goes back through `geodesic.direct` so no inverse projection is needed. Cost: about 5 grid lookups per boat per sub-step, plus the gradient only in contact.
7. **Velocity.** After either correction, with unit hull-forward `f` and contact normal `n` (pointing away from the obstacle), if `speed * (f.n) < 0` (moving into it) the new speed is `speed * (1 - (f.n)^2)`: the normal component of the velocity is dropped and only the part along the hull axis survives, so a head-on boat stops and a glancing one keeps sliding; reversing (`f.n` flips sign) is free. The current is not state; its inward part is removed by the position correction. No yaw, rpm or heading change; a turn that sweeps the hull into an obstacle is fixed by position only. `a` is recomputed from the corrected speed.
8. **Event (d).** New message `asv_sim_msgs/msg/Collision.msg` (`std_msgs/Header header`, `string platform`, `uint8 kind` with `KIND_BOAT=0`, `KIND_TERRAIN=1`, `string other` (boat name, `''` for terrain), `float64 latitude`, `float64 longitude`, `float32 closing_speed` m/s (relative to the other boat for boat contacts), `float32 water_depth` m (grid depth plus tide at the place the boat tried to go; NaN on nodata/off-grid, and for boat contacts)), published on `~/collisions` (node-relative, reliable, depth 10). `marine_interfaces/Contact` is a perception contact (classification, shape, curation); it does not fit and would add a core-layer dependency to this package. A message is published once per contact **onset** per (platform, other); the contact is considered ended after 1 s of ROS time (node clock, so it follows `use_sim_time`) without overlap, and the same moment logs one INFO line. Events never feed back into dynamics.
9. **Parameters (e).** Node: `collision.boats` (bool, true for every launch; false skips boat-to-boat), `collision.grid_file` (above). Demo: `demo.yaml` gets `models.demo.length: 4.0`, `beam: 1.7`, `draft: 0.4`; `demo_boats_launch.asv_sim_parameters` adds `collision.grid_file` = the resolved truth grid when there is one (so the demo has terrain collision on; `sim_robot_launch.py` is untouched, terrain stays off there, boat-to-boat is on). `test_demo_config_keys_are_declared_model_parameters` already guards the new keys. Boats are indestructible: no state besides speed/position is touched.
10. **Tests (f).** `asv_sim/test/test_collision.py` (pure, plus synthetic GDAL GeoTIFF in a tmp UTM 19N grid with a land strip, a nodata block and a slope): capsule distance cases (parallel, end to end, crossing, nested); projection and slide; clearance minimum over hull points; speed projection head-on, glancing, reversing; grid depth plus tide (tide raises clearance); land and nodata are walls; started aground may leave but not go shallower; zero gradient stops. In-process node tests (extend the `Rig` pattern of `test_multi_platform.py`): two boats driven at each other never closer than the footprint sum and then back out; a boat driven at a straight shore stops, one at 45 degrees keeps sliding along it, then reverses off; a five-second stalled gap does not tunnel (boat and shore, boat and boat); one event per contact onset, none per step; a second contact after separating gives a second event; no `grid_file` means no terrain effect; an unreadable grid refuses to start; a non-finite pose does not crash; tide drained below the draft grounds a boat that floats at high water. Existing `test_dynamics_stability.py` and `test_multi_platform.py` must pass unchanged. `marine_simulation/test/test_demo_boats_launch.py`: `asv_sim_parameters` carries the grid. flake8/pep257/copyright as for the package.
11. **Docs.** `.agents/README.md` (inventory/layout line for `collision.py`, the parameter table rows, a pitfall: contact is resolved per sub-step inside `Dynamics`, never from the node loop; a new `Collision` topic), `asv_sim/README.md` (collision section, datum caveat), `marine_simulation/README.md` (demo: boats block each other and the shallows, how to turn it off, tide exaggeration makes low water a hazard), cw4/demo yaml comments.
```

## Output Format

Write your findings to this exact format so they can be parsed:

### Findings

| # | Severity | File | Line | Finding |
|---|----------|------|------|---------|
| 1 | must-fix / suggestion | `path/to/file` | line number | Description of the issue |

If you find no issues, write:

### Findings

No issues found.

### Summary

Write a 1-3 sentence overall assessment after the findings table.
