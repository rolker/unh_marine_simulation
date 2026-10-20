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

**Title**: Local branch feature/issue-111 at 692ec07
**Branch**: feature/issue-111
**Base**: 236b952
**HEAD**: 692ec07

## Diff

````diff
diff --git a/.agents/README.md b/.agents/README.md
index 0f579bf..c5be651 100644
--- a/.agents/README.md
+++ b/.agents/README.md
@@ -21,8 +21,9 @@
 ```
 unh_marine_simulation/
 ├── asv_sim/                           # ASV dynamics simulator
-│   ├── asv_sim/                       #   Python module (dynamics, environment, model, platform, collision)
+│   ├── asv_sim/                       #   Python module (dynamics, environment, model, platform, collision, charts)
 │   ├── config/                        #   Platform configs (ben.yaml, cw4.yaml, drix.yaml, demo.yaml, ...)
+│   ├── enc/                           #   NOAA S-57 cells US5PSMCC/US5PSMCD (+ update, README, user agreement) for charted-object collision
 │   └── test/                          #   Linting, tide tests, test_multi_platform.py (in-process)
 ├── asv_sim_msgs/                      # Service and message definitions
 │   ├── msg/Collision.msg
@@ -176,9 +177,13 @@ Known build issues:
 | Parameter | Type | Default | Range | Effect |
 |-----------|------|---------|-------|--------|
 | `collision.boats` | bool | `true` | | Boats block each other; `false` lets them pass through |
+| `collision.enc_dir` | string | `''` | | One S-57 `.000` or a directory of cells, read once with OGR (`asv_sim/charts.py`); empty means no charted objects; unreadable path, unknown class override or cells over 0.5 degree apart raise at start |
+| `collision.enc_footprints` | string array | `['']` | | `CLASS=metres` overrides (radius or half width; 0 drops the class); the default is the table in `asv_sim/README.md` |
 | `collision.grid_file` | string | `''` | | Bathymetry GeoTIFF read once at start with `mbes_sim.bathy_grid.BathyGrid`; empty means no terrain collision; an unreadable file raises at start |
 | `models.<name>.length` | double, m | `4.0` | 0.01 to 1000, not less than `beam` | Hull length (capsule footprint) |
 | `models.<name>.beam` | double, m | `1.7` | 0.01 to 1000, not more than `length` | Hull width |
 | `models.<name>.draft` | double, m | `0.4` | 0.01 to 1000 | The boat grounds where grid depth + tide is less than this |
 
+- **Charted objects (issue #113) come from OGR on the S-57 cells, not from the C++ `s57_grids` stack (asv_sim keeps its dependency surface small; `python3-gdal` is already `mbes_sim`'s).** The classes follow `marine_charts`'s `S57Dataset::getGrid` lethal list plus the hazards, and add buoys and beacons (the costmap ignores them). Land is left to the bathymetry grid. `UWTROC`/`WRECKS`/`OBSTRN` with a `VALSOU` block only while depth + tide < draft; without one they block at every tide. The cells are installed with the package (`asv_sim/enc`, about 2.3 MB; US5PSMCD ships with its `.001` update, which OGR applies) so the demo needs nothing under `ENC_ROOT`; the demo launch passes `share/asv_sim/enc` (argument `charted_objects`). `collision.enc_dir` must hold the cells of the area only: overlapping cells of different scales are all read. The footprints are choices, not chart data.
+
 Topic: `/asv_sim/collisions` (`asv_sim_msgs/msg/Collision`, reliable, depth 10), one message per contact onset.
diff --git a/asv_sim/README.md b/asv_sim/README.md
index f33d1d7..501a312 100644
--- a/asv_sim/README.md
+++ b/asv_sim/README.md
@@ -73,14 +73,20 @@ step and a boat cannot tunnel through a shore or another hull.
   starts later does not see earlier events. The node also logs one INFO line.
   `closing_speed` is the closing speed of the attempted motion, current
   included.
+- **Charted objects.** With `collision.enc_dir`, the piers, pontoons, piles,
+  buoys, beacons, rocks and wrecks of S-57 ENC cells block boats the same way
+  (see below). A contact is named by the S-57 class in the event's `other`.
 - **More obstacle sources.** `Collisions.sources` is a list of objects with
-  `correct(step, lat, lon)`; boats and terrain are two of them. Another source
-  (for example charted objects, issue #113) is appended to the list.
+  `correct(step, lat, lon)`; boats, charted objects and terrain are three of
+  them, run in that order (the bottom has the last word). Another source is
+  appended to the list.
 
 | Parameter | Default | Meaning |
 |-----------|---------|---------|
 | `collision.boats` | `true` | Boats block each other; `false` lets them pass through |
 | `collision.grid_file` | `''` | Bathymetry GeoTIFF (as `mbes_sim.bathy_grid` reads it); empty: no terrain collision. Read once at start; an unreadable file stops the node |
+| `collision.enc_dir` | `''` | One S-57 `.000` cell or a directory of cells (flat, or one directory per cell as in an ENC_ROOT); empty: no charted objects. Read once at start with GDAL's OGR S-57 driver; an unreadable path, a class override that is not known, or cells more than half a degree apart stop the node. Point it at the cells of the area only (overlapping cells of different scales would all be read) |
+| `collision.enc_footprints` | `[]` | Overrides `CLASS=metres` of the footprints below (radius of a point, half width of a line); `0` leaves the class out, e.g. `BOYLAT=1.5`, `SLCONS=0` |
 | `models.<name>.length` | `4.0` m | Hull length (0.01 to 1000); must not be less than `beam` |
 | `models.<name>.beam` | `1.7` m | Hull width |
 | `models.<name>.draft` | `0.4` m | Keel depth; the boat grounds where the water is shallower |
@@ -91,3 +97,38 @@ compilation.
 
 The defaults are the C-Worker 4 (`cw4.yaml`). `coastal_surveyor`, `drix` and
 `echoboat240` use them without having been checked against those boats.
+
+### Charted objects
+
+`asv_sim/charts.py` reads the S-57 cells and turns the features of the classes
+below into circles (points) and segments with a half-width (lines; the rings of
+areas, which are hollow: a boat cannot cross the ring, the inside is never
+entered). The classes follow the classification of `marine_charts`'s
+`S57Dataset::getGrid`, the one behind the real boats' costmap: what it rasterises
+as lethal, plus the discrete hazards. Buoys and beacons are ignored there but a
+boat can hit them, so they are here. Land (`LNDARE`, `COALNE`) is left to the
+bathymetry grid.
+
+| S-57 class | Footprint (m) | Meaning |
+|---|---|---|
+| `SLCONS` | 1.0 | shoreline construction: piers, quays, walls |
+| `PONTON`, `FLODOC` | 0.5 | pontoons and floating docks |
+| `PILPNT` | 0.5 | pile |
+| `PYLONS` | 1.5 | pylon, bridge support |
+| `CAUSWY`, `DAMCON`, `DYKCON`, `GATCON`, `FSHFAC`, `HULKES`, `OBSTRN` | 1.0 | causeway, dam, dyke, gate, fishing facility, hulk, obstruction |
+| `WRECKS` | 1.5 | wreck |
+| `UWTROC` | 1.0 | underwater or awash rock |
+| `BCNCAR`, `BCNISD`, `BCNLAT`, `BCNSAW`, `BCNSPP` | 0.75 | beacons |
+| `BOYCAR`, `BOYINB`, `BOYISD`, `BOYLAT`, `BOYSAW`, `BOYSPP` | 1.0 | buoys |
+
+`UWTROC`, `WRECKS` and `OBSTRN` with a charted `VALSOU` block only while that depth
+plus the tide is less than the boat's draft; without one (the costmap assumes the
+same) and every other class, at every tide. The footprints are choices made here, not
+chart data; a pontoon or pier outline of the chart is thin, so the half-width is
+what makes it a thing a hull can hit. Frame: an azimuthal equidistant projection
+centred on the loaded data (below a centimetre per kilometre within the half
+degree limit); the per-class counts are logged at start.
+
+`enc/` holds the two harbour-scale NOAA cells that cover the demo area, installed
+with the package (about 2.3 MB), so a machine needs nothing under `ENC_ROOT`; see
+`enc/README.md` for editions and source.
diff --git a/asv_sim/asv_sim/asv_sim_node.py b/asv_sim/asv_sim/asv_sim_node.py
index 88f18cf..29e2102 100755
--- a/asv_sim/asv_sim/asv_sim_node.py
+++ b/asv_sim/asv_sim/asv_sim_node.py
@@ -66,6 +66,35 @@ class AsvSim(rclpy.node.Node):
                 description='Bathymetry GeoTIFF (band 1, positive depth, '
                 'as read by mbes_sim.bathy_grid). Empty: no terrain '
                 'collision. Read once at start.')).value
+        enc_dir = self.declare_parameter(
+            'collision.enc_dir', '',
+            ParameterDescriptor(
+                description='S-57 ENC cell (.000) or a directory of cells; '
+                'charted piers, pontoons, piles, buoys, beacons, rocks and '
+                'wrecks block boats. Empty: no charted objects. Read once '
+                'at start; an unreadable path stops the node. Point it at '
+                'the cells of the area only.')).value
+        enc_footprints = self.declare_parameter(
+            'collision.enc_footprints', [''],
+            ParameterDescriptor(
+                description='Overrides of the footprint of a charted class '
+                'as CLASS=metres (radius of a point, half width of a line); '
+                '0 leaves the class out. Example: BOYLAT=1.5, SLCONS=0.')).value
+        objects = None
+        if enc_dir:
+            from asv_sim import charts
+            primitives, project, counts = charts.load(
+                enc_dir, [e for e in enc_footprints if e])
+            objects = asv_sim.collision.ChartedObjectSource(
+                primitives, project)
+            self.get_logger().info(
+                'charted objects on: {} primitives from {} ({})'.format(
+                    len(primitives), enc_dir, ', '.join(
+                        '{} {}'.format(k, v)
+                        for k, v in sorted(counts.items())) or 'none'))
+        else:
+            self.get_logger().info(
+                'charted objects off: collision.enc_dir is not set')
         grid = None
         if grid_file:
             from mbes_sim.bathy_grid import BathyGrid
@@ -80,7 +109,7 @@ class AsvSim(rclpy.node.Node):
             QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
         return asv_sim.collision.Collisions(
             grid=grid, boats=boats, emit=self._publishCollision,
-            logger=self.get_logger())
+            logger=self.get_logger(), objects=objects)
 
     def _publishCollision(self, event: dict) -> None:
         msg = Collision()
diff --git a/asv_sim/asv_sim/charts.py b/asv_sim/asv_sim/charts.py
new file mode 100644
index 0000000..28755b6
--- /dev/null
+++ b/asv_sim/asv_sim/charts.py
@@ -0,0 +1,249 @@
+"""Charted objects from S-57 ENC cells as obstacle primitives (issue #113).
+
+Reads the cells with GDAL's OGR S-57 driver (the ``python3-gdal`` that
+``mbes_sim`` already needs; the C++ ``s57_grids`` stack is not used, to keep
+``asv_sim``'s dependencies small). Every feature of a solid class becomes
+circles (points) or segments with a half-width (lines, and the rings of
+areas, which are hollow: a boat cannot cross the ring, the inside is never
+entered).
+
+The classes follow the classification of ``marine_charts``'s
+``S57Dataset::getGrid`` (the real boats' costmap): the ones it rasterises as
+lethal (``PILPNT``, ``PYLONS``, ``SLCONS``, ``PONTON``, ``CAUSWY``,
+``DAMCON``, ``DYKCON``, ``GATCON``, ``FSHFAC``, ``HULKES``, ``OBSTRN``) and
+the discrete hazards (``UWTROC``, ``WRECKS``), plus ``FLODOC`` (a depth area
+there, a floating dock here) and buoys and beacons, which the costmap
+ignores but a boat can hit. Land (``LNDARE``, ``COALNE``) is left to the
+bathymetry grid.
+"""
+
+from collections import namedtuple
+import glob
+import math
+import os
+
+# A solid thing in a local metric frame: a circle is a segment of no length.
+# ``depth`` is the charted depth over it in metres (positive down, chart
+# datum); ``None`` means solid at every tide.
+Primitive = namedtuple(
+    'Primitive', ['klass', 'x0', 'y0', 'x1', 'y1', 'radius', 'depth'])
+
+# A feature read from a cell: ``parts`` are lists of (lon, lat) degrees;
+# ``kind`` is 'point', 'line' or 'area' (its rings are the parts).
+Feature = namedtuple('Feature', ['klass', 'kind', 'parts', 'depth'])
+
+# Radius (point) or half-width (line, ring of an area) in metres; 0 leaves a
+# class out. Overridable with ``collision.enc_footprints``.
+DEFAULT_FOOTPRINTS = {
+    'SLCONS': 1.0,   # shoreline construction: piers, quays, walls
+    'PONTON': 0.5,   # pontoons, floating docks of marinas
+    'FLODOC': 0.5,   # floating dock
+    'PILPNT': 0.5,   # pile
+    'PYLONS': 1.5,   # bridge supports and pylons
+    'CAUSWY': 1.0,
+    'DAMCON': 1.0,
+    'DYKCON': 1.0,
+    'GATCON': 1.0,
+    'FSHFAC': 1.0,   # fishing facility
+    'HULKES': 1.0,   # hulk
+    'OBSTRN': 1.0,   # obstruction
+    'WRECKS': 1.5,
+    'UWTROC': 1.0,   # underwater or awash rock
+    'BCNCAR': 0.75, 'BCNISD': 0.75, 'BCNLAT': 0.75, 'BCNSAW': 0.75,
+    'BCNSPP': 0.75,  # beacons
+    'BOYCAR': 1.0, 'BOYINB': 1.0, 'BOYISD': 1.0, 'BOYLAT': 1.0,
+    'BOYSAW': 1.0, 'BOYSPP': 1.0,  # buoys
+}
+
+# Classes whose charted VALSOU (value of sounding) decides whether a boat of
+# a given draft can pass over them at the current tide; without one they are
+# solid at every tide.
+SOUNDED_CLASSES = ('UWTROC', 'WRECKS', 'OBSTRN')
+
+# Data this many degrees apart no longer fit one local frame to a metre.
+MAX_SPAN_DEGREES = 0.5
+
+
+def parse_footprints(overrides, base=None):
+    """Return the footprint table with ``["CLASS=metres", ...]`` applied.
+
+    :raises ValueError: for an entry that is not ``CLASS=number``, a class
+        that is not a known one, or a negative or non-finite size.
+    """
+    table = dict(DEFAULT_FOOTPRINTS if base is None else base)
+    for entry in overrides:
+        name, sep, value = str(entry).partition('=')
+        name = name.strip().upper()
+        try:
+            metres = float(value)
+        except ValueError:
+            metres = math.nan
+        if not sep or not math.isfinite(metres) or metres < 0.0:
+            raise ValueError(
+                'collision.enc_footprints entry {!r} is not CLASS=metres '
+                '(0 or more)'.format(entry))
+        if name not in DEFAULT_FOOTPRINTS:
+            raise ValueError(
+                'collision.enc_footprints: {!r} is not a charted class '
+                'asv_sim knows ({})'.format(
+                    name, ', '.join(sorted(DEFAULT_FOOTPRINTS))))
+        table[name] = metres
+    return table
+
+
+def find_cells(path):
+    """Return the ``.000`` cell files at a path (a file or a directory).
+
+    A directory may hold the cells directly or, as an ``ENC_ROOT`` does, one
+    directory per cell.
+    """
+    path = os.path.expanduser(path)
+    if os.path.isfile(path):
+        return [path]
+    if not os.path.isdir(path):
+        raise FileNotFoundError(
+            'collision.enc_dir {!r} is not a file or directory'.format(path))
+    cells = sorted(set(glob.glob(os.path.join(path, '*.000'))
+                       + glob.glob(os.path.join(path, '*', '*.000'))))
+    if not cells:
+        raise FileNotFoundError(
+            'collision.enc_dir {!r} holds no .000 cell'.format(path))
+    return cells
+
+
+def read_features(cells, classes):
+    """Read the features of the given classes from S-57 cells with OGR."""
+    from osgeo import gdal
+    from osgeo import ogr
+    gdal.UseExceptions()
+    wanted = set(classes)
+    features = []
+    for cell in cells:
+        dataset = ogr.Open(cell)
+        for index in range(dataset.GetLayerCount()):
+            layer = dataset.GetLayerByIndex(index)
+            klass = layer.GetName()
+            if klass not in wanted:
+                continue
+            fields = [layer.GetLayerDefn().GetFieldDefn(i).GetName()
+                      for i in range(layer.GetLayerDefn().GetFieldCount())]
+            for feature in layer:
+                geometry = feature.GetGeometryRef()
+                if geometry is None:
+                    continue
+                depth = None
+                if klass in SOUNDED_CLASSES and 'VALSOU' in fields:
+                    i = fields.index('VALSOU')
+                    if feature.IsFieldSetAndNotNull(i):
+                        depth = feature.GetFieldAsDouble(i)
+                for kind, parts in _parts(geometry):
+                    features.append(Feature(klass, kind, parts, depth))
+    return features
+
+
+def _parts(geometry):
+    """Yield ``(kind, parts)`` for an OGR geometry (collections recursed)."""
+    from osgeo import ogr
+    kind = ogr.GT_Flatten(geometry.GetGeometryType())
+    if kind == ogr.wkbPoint:
+        yield 'point', [[(geometry.GetX(), geometry.GetY())]]
+    elif kind == ogr.wkbLineString:
+        yield 'line', [[(p[0], p[1]) for p in geometry.GetPoints()]]
+    elif kind == ogr.wkbPolygon:
+        yield 'area', [[(p[0], p[1]) for p in ring.GetPoints()]
+                       for ring in (geometry.GetGeometryRef(i)
+                                    for i in range(geometry.GetGeometryCount()))]
+    elif kind in (ogr.wkbMultiPoint, ogr.wkbMultiLineString,
+                  ogr.wkbMultiPolygon, ogr.wkbGeometryCollection):
+        for i in range(geometry.GetGeometryCount()):
+            yield from _parts(geometry.GetGeometryRef(i))
+
+
+def make_projection(lon0, lat0):
+    """Return ``project(lat, lon) -> (x, y)``: azimuthal equidistant metres.
+
+    Centred on ``(lon0, lat0)`` degrees, x east and y north; within the
+    :data:`MAX_SPAN_DEGREES` the distortion is below a centimetre per
+    kilometre, and the rotation from true north below a degree.
+    """
+    from osgeo import osr
+    source = osr.SpatialReference()
+    source.SetWellKnownGeogCS('WGS84')
+    target = osr.SpatialReference()
+    target.ImportFromProj4(
+        '+proj=aeqd +lat_0={:.9f} +lon_0={:.9f} +x_0=0 +y_0=0 '
+        '+datum=WGS84 +units=m +no_defs'.format(lat0, lon0))
+    transform = osr.CoordinateTransformation(source, target)
+
+    def project(lat, lon):
+        # GDAL 3 takes WGS84 in authority order: latitude first.
+        x, y = transform.TransformPoint(math.degrees(lat), math.degrees(lon))[:2]
+        return x, y
+
+    def project_degrees(lon, lat):
+        x, y = transform.TransformPoint(lat, lon)[:2]
+        return x, y
+
+    project.degrees = project_degrees
+    return project
+
+
+def build_primitives(features, footprints, project_degrees):
+    """Turn features into primitives; return ``(primitives, counts)``.
+
+    :param project_degrees: ``(lon, lat) -> (x, y)`` in metres.
+    :param footprints: class -> radius or half-width in metres.
+    :return: A list of :class:`Primitive` and a ``{class: count}`` of the
+        primitives made (a line of three segments counts three).
+    """
+    primitives = []
+    counts = {}
+    for feature in features:
+        size = footprints.get(feature.klass, 0.0)
+        if size <= 0.0:
+            continue
+        made = 0
+        for ring in feature.parts:
+            points = [project_degrees(lon, lat) for lon, lat in ring]
+            if feature.kind == 'point' or len(points) == 1:
+                x, y = points[0]
+                primitives.append(Primitive(
+                    feature.klass, x, y, x, y, size, feature.depth))
+                made += 1
+                continue
+            for (x0, y0), (x1, y1) in zip(points, points[1:]):
+                primitives.append(Primitive(
+                    feature.klass, x0, y0, x1, y1, size, feature.depth))
+                made += 1
+        if made:
+            counts[feature.klass] = counts.get(feature.klass, 0) + made
+    return primitives, counts
+
+
+def load(path, footprint_overrides=()):
+    """Read the cells at ``path``; return ``(primitives, project, counts)``.
+
+    :raises ValueError: when the features span more than
+        :data:`MAX_SPAN_DEGREES` (point ``path`` at the cells of the area).
+    """
+    footprints = parse_footprints(footprint_overrides)
+    cells = find_cells(path)
+    features = read_features(
+        cells, [k for k, v in footprints.items() if v > 0.0])
+    lons = [lon for f in features for ring in f.parts for lon, _ in ring]
+    lats = [lat for f in features for ring in f.parts for _, lat in ring]
+    if not lons:
+        return [], make_projection(0.0, 0.0), {}
+    if max(lons) - min(lons) > MAX_SPAN_DEGREES \
+            or max(lats) - min(lats) > MAX_SPAN_DEGREES:
+        raise ValueError(
+            'the charted objects in {!r} span {:.2f} x {:.2f} degrees, more '
+            'than the {} a local frame holds; point collision.enc_dir at '
+            'the cells of the area'.format(
+                path, max(lons) - min(lons), max(lats) - min(lats),
+                MAX_SPAN_DEGREES))
+    project = make_projection((max(lons) + min(lons)) / 2.0,
+                              (max(lats) + min(lats)) / 2.0)
+    primitives, counts = build_primitives(
+        features, footprints, project.degrees)
+    return primitives, project, counts
diff --git a/asv_sim/asv_sim/collision.py b/asv_sim/asv_sim/collision.py
index 25a0dce..32d9df3 100644
--- a/asv_sim/asv_sim/collision.py
+++ b/asv_sim/asv_sim/collision.py
@@ -11,7 +11,7 @@ step and a boat cannot tunnel through a shore or a hull.
 What a boat can touch is a list of *obstacle sources*. Each source has
 ``correct(step, lat, lon)``, returning the (possibly corrected) position and
 the list of :class:`Contact` it made. Boats and terrain are the two sources
-here; another one (charted objects, issue #113) is added by appending an
+here; another one (charted objects, issue #113, is the third) is added by appending an
 object with the same method to ``Collisions.sources``, nothing in
 :meth:`Collisions.resolve` changes.
 
@@ -49,6 +49,10 @@ CONTACT_RELEASE_NS = 1000000000
 # Contact kinds (the values of asv_sim_msgs/msg/Collision).
 KIND_BOAT = 0
 KIND_TERRAIN = 1
+KIND_OBJECT = 2
+
+# Edge of the squares of the spatial hash over the charted objects, metres.
+BUCKET = 100.0
 
 # A contact: kind, name of the other boat ('' for terrain), unit normal
 # (east, north) pointing away from the obstacle, velocity (east, north) of
@@ -386,6 +390,77 @@ class TerrainSource:
                 return new_lat, new_lon, [contact]
 
 
+class ChartedObjectSource:
+    """Charted objects (piers, pontoons, piles, buoys, rocks, wrecks).
+
+    Obstacles are :class:`asv_sim.charts.Primitive` tuples in a local metric
+    frame: a circle (a segment of no length) or a segment with a half-width.
+    The hull capsule is tested against each primitive near it; a primitive
+    with a charted ``depth`` only blocks a boat while that depth plus the
+    tide is less than the boat's draft, the rest block at every tide. The
+    contact is named by the object class (``other`` of the event).
+
+    :param primitives: Iterable of ``Primitive``.
+    :param project: ``project(lat, lon) -> (x, y)`` in the primitives' frame
+        (radians in, metres out).
+    """
+
+    uses_tide = True
+
+    def __init__(self, primitives, project):
+        self.project = project
+        self.primitives = list(primitives)
+        self.buckets = {}
+        for index, p in enumerate(self.primitives):
+            x0, x1 = sorted((p.x0, p.x1))
+            y0, y1 = sorted((p.y0, p.y1))
+            for ix in range(math.floor((x0 - p.radius) / BUCKET),
+                            math.floor((x1 + p.radius) / BUCKET) + 1):
+                for iy in range(math.floor((y0 - p.radius) / BUCKET),
+                                math.floor((y1 + p.radius) / BUCKET) + 1):
+                    self.buckets.setdefault((ix, iy), []).append(index)
+
+    def _near(self, x, y, reach):
+        found = set()
+        for ix in range(math.floor((x - reach) / BUCKET),
+                        math.floor((x + reach) / BUCKET) + 1):
+            for iy in range(math.floor((y - reach) / BUCKET),
+                            math.floor((y + reach) / BUCKET) + 1):
+                found.update(self.buckets.get((ix, iy), ()))
+        return found
+
+    def correct(self, step, lat, lon):
+        contacts = {}
+        reach = step.length + step.beam
+        for _ in range(3):
+            x, y = self.project(lat, lon)
+            if not _finite(x, y):
+                break
+            moved = False
+            for index in sorted(self._near(x, y, reach)):
+                p = self.primitives[index]
+                if p.depth is not None \
+                        and p.depth + step.tide - step.draft >= 0.0:
+                    continue
+                mine = capsule_axis((x, y), step.heading, step.length,
+                                    step.beam)
+                hit = capsule_penetration(
+                    mine, ((p.x0, p.y0), (p.x1, p.y1), p.radius))
+                if hit is None:
+                    continue
+                depth, normal = hit
+                lat, lon = move_en(
+                    lat, lon, normal[0] * depth, normal[1] * depth)
+                x += normal[0] * depth
+                y += normal[1] * depth
+                contacts[p.klass] = Contact(
+                    KIND_OBJECT, p.klass, normal, (0.0, 0.0), math.nan)
+                moved = True
+            if not moved:
+                break
+        return lat, lon, list(contacts.values())
+
+
 class Collisions:
     """Resolve contacts for every registered boat.
 
@@ -393,17 +468,23 @@ class Collisions:
         ``getXY``, ``getDepth`` and ``geoTransform``), or ``None`` for no
         terrain.
     :param boats: ``False`` lets boats pass through each other.
+    :param objects: A :class:`ChartedObjectSource`, or ``None``.
     :param emit: Called with one dict per contact onset.
     :param logger: Object with ``info`` and ``warning``.
     """
 
-    def __init__(self, grid=None, boats=True, emit=None, logger=None):
+    def __init__(self, grid=None, boats=True, emit=None, logger=None,
+                 objects=None):
         self.dynamics = {}
         self.emit = emit
         self.logger = logger
         self.sources = []
         if boats:
             self.sources.append(BoatSource(self))
+        # Boats, charted objects, then terrain: where they disagree (a boat
+        # between a pier and the shore) the bottom has the last word.
+        if objects is not None:
+            self.sources.append(objects)
         if grid is not None:
             self.sources.append(TerrainSource(grid))
         self._last_seen = {}
@@ -543,8 +624,12 @@ class Collisions:
         onset = last is None or now - last > CONTACT_RELEASE_NS
         if onset:
             if self.logger is not None:
-                what = ('boat ' + contact.other if contact.kind == KIND_BOAT
-                        else 'the bottom or shore')
+                if contact.kind == KIND_BOAT:
+                    what = 'boat ' + contact.other
+                elif contact.kind == KIND_OBJECT:
+                    what = 'charted object ' + contact.other
+                else:
+                    what = 'the bottom or shore'
                 self.logger.info(
                     'asv_sim platform {!r} touched {} at {:.1f} m/s'.format(
                         dyn.name, what, closing))
diff --git a/asv_sim/enc/NOAA_USERAGREEMENT.TXT b/asv_sim/enc/NOAA_USERAGREEMENT.TXT
new file mode 100644
index 0000000..09ee781
--- /dev/null
+++ b/asv_sim/enc/NOAA_USERAGREEMENT.TXT
@@ -0,0 +1,43 @@
+USER AGREEMENT 
+  
+By using the website and the NOAA Electronic Navigational Charts (NOAA ENCs®) distributed there, you acknowledge that you have read, understood, and accepted the terms and conditions stated in this User Agreement.  NOAA reserves the right to change this Agreement at any time and without notice.  Your use of the website and/or the Electronic Navigational Charts available there shall constitute your agreement to be bound by any this Agreement and any changes.  
+  
+1. Description of NOAA Electronic Navigational Charts (NOAA ENCs®)  
+  
+The NOAA ENCs distributed here are a geo-referenced database(s) of NOAA nautical chart features and their attributes, published by NOAA in the format of the International Hydrographic Organization S-57 Standard, "IHO Transfer Standard for Digital Hydrographic Data." NOAA updates the ENCs for Notice to Mariners on a weekly basis (timing of their availability is not guaranteed). NOAA ENCs are an official product of NOAA.  
+  
+2. Permitted Use 
+  
+The NOAA ENCs are intended for navigational use. They are intended to be used in their electronic form only. You may download, use, and redistribute them without restriction, and without payment to NOAA, except as noted herein.  
+  
+They may be used to meet federal chart carriage regulations published in the Code of Federal Regulations. On November 15, 2005, the regulations were as stated below. These regulations may change, and mariners are advised to check the Code of Federal Regulations for their current status.  
+  
+1) On May 2, 2001, the United States Coast Guard amended the United States chart carriage regulations to permit government vessels to use electronic charting and navigation systems in lieu of paper charts.  
+  
+2) On July 1, 2002, the International Maritime Organization's (IMO) amendments to chapter V of the International Convention for the Safety of Life at Sea (SOLAS) became effective after being accepted by the Contracting Governments to SOLAS (Jan 2002) and the IMOs Maritime Safety Committee (Dec 2000). These amendments, in part, allowed an electronic chart display system (ECDIS) using ENCs to be accepted as meeting chart carriage requirements of SOLAS chapter V.  
+  
+3) On August 15, 2002, the United States Coast Guard issued a statement of policy to bring its regulations into agreement with SOLAS Chapter V (as amended by the changes taking effect July 1, 2002). The policy statement said that, if a ship has an approved ECDIS installed according to SOLAS, Chapter V, the ECDIS will be considered as meeting the ship's nautical chart carriage regulations. The ships that are affected are:  
+a. U.S.-flagged ships of 150 or more gross tons that engage on international voyages.  
+b. U.S.-flagged ships certificated solely for service on the Great Lakes and the St. Lawrence River.  
+c. Foreign-flag ships to which SOLAS, Chapter V, applies that are operating on the navigable waters of the United States.  
+This policy is not applicable to U.S.-flag ships engaged only on domestic voyages. These ships must continue to comply with existing navigation equipment requirements until the chart carriage regulations are formally amended.  
+  
+3. Limitations on Use  
+  
+NOAA ENCs® may be redistributed, but redistributed NOAA ENCs are NOT considered official NOAA ENCs, and do not meet federal chart carriage regulations for regulated vessels unless redistributed by a "Certified NOAA ENC Distributor" or by a "Certified NOAA ENC Value Added Distributor". Click http://chartmaker.ncd.noaa.gov/mcd/enc/fedreg_encrule.htm for further information on ENC Distributorships.  
+  
+Copying of the NOAA ENCs to any other server or location for further distribution is discouraged unless the following guidelines are followed: 1) this User Agreement is displayed and accepted by anyone accessing the NOAA ENCs, and 2) a reference to this Web site is included so that anyone accessing the NOAA ENCs is advised of their origin.  
+  
+If these NOAA ENC's are incorporated into any other product in a form other than as provided by NOAA, the producer of that product assumes full liability and must adhere to conditions described in the paragraph above concerning copying.  
+  
+4. Warnings  
+  
+Weekly updates to the ENCs are done on a "best efforts" basis. The timing of their availability is not guaranteed. You are responsible for ensuring that your ENCs are the most current edition and that the most recent updates have been applied.  
+  
+While NOAA has accuracy standards for each step in the data collection and chart production process, much of the depth information found on NOAA charts is based on surveys conducted before 1940, the shoreline is more than 20 years old, and paper charts used to be compiled manually. For more information regarding the accuracy of electronic charts, click http://chartmaker.ncd.noaa.gov/mcd/enc/encartcl.htm.  
+  
+5. Trademarks and Copyright  
+  
+"NOAA®" and the NOAA® emblem are registered trademarks of the National Oceanic and Atmospheric Administration.  
+  
+NOAA ENC® is a registered trademark of the National Oceanic and Atmospheric Administration.
diff --git a/asv_sim/enc/README.md b/asv_sim/enc/README.md
new file mode 100644
index 0000000..bae42db
--- /dev/null
+++ b/asv_sim/enc/README.md
@@ -0,0 +1,22 @@
+# ENC cells for the charted-object collision (issue #113)
+
+NOAA Electronic Navigational Charts, S-57, the two harbour-scale (usage band 5,
+1:12000) cells that cover the Ocean Discovery Day demo area (Portsmouth Harbor,
+lat 43.0537 to 43.0937, lon -70.7405 to -70.6695, the demo truth grid):
+
+| Cell | Edition | Update | Issued | Covers |
+|------|---------|--------|--------|--------|
+| `US5PSMCC.000` | 4 | 0 | 2025-02-18 | lon -70.800 to -70.725, lat 43.05 to 43.125 |
+| `US5PSMCD.000` + `US5PSMCD.001` | 5 | 1 | 2026-02-12 | lon -70.725 to -70.650, lat 43.05 to 43.125 |
+
+Source: NOAA Office of Coast Survey, https://charts.noaa.gov/ENCs/ENCs.shtml
+(copied from an ENC_ROOT downloaded in July 2026). The NOAA user agreement
+(`NOAA_USERAGREEMENT.TXT`) permits redistribution without restriction. These
+copies are a simulation fixture, not updated and not for navigation.
+
+`asv_sim` reads them with GDAL's OGR S-57 driver (`asv_sim/charts.py`) when
+`collision.enc_dir` points at this directory; the demo launch does. Point it at
+another cell file or a directory of cells (flat, or one directory per cell as in
+an ENC_ROOT) for another area; a directory holding cells more than half a degree
+apart is refused. Cells of different scales that overlap would both be read:
+give it the cells you want and no others.
diff --git a/asv_sim/enc/US5PSMCC.000 b/asv_sim/enc/US5PSMCC.000
new file mode 100644
index 0000000..eb6006e
Binary files /dev/null and b/asv_sim/enc/US5PSMCC.000 differ
diff --git a/asv_sim/enc/US5PSMCD.000 b/asv_sim/enc/US5PSMCD.000
new file mode 100644
index 0000000..ead38cc
Binary files /dev/null and b/asv_sim/enc/US5PSMCD.000 differ
diff --git a/asv_sim/enc/US5PSMCD.001 b/asv_sim/enc/US5PSMCD.001
new file mode 100644
index 0000000..5077ed8
Binary files /dev/null and b/asv_sim/enc/US5PSMCD.001 differ
diff --git a/asv_sim/package.xml b/asv_sim/package.xml
index bc5c7be..653726a 100644
--- a/asv_sim/package.xml
+++ b/asv_sim/package.xml
@@ -15,12 +15,13 @@
   <depend>python3-transforms3d</depend>
   <!-- Only needed when collision.grid_file is set (BathyGrid reader). -->
   <exec_depend>mbes_sim</exec_depend>
+  <!-- Only needed when collision.enc_dir is set (OGR reads the S-57 cells). -->
+  <exec_depend>python3-gdal</exec_depend>
 
   <test_depend>ament_copyright</test_depend>
   <test_depend>ament_flake8</test_depend>
   <test_depend>ament_pep257</test_depend>
   <test_depend>python3-pytest</test_depend>
-  <test_depend>python3-gdal</test_depend>
   <test_depend>python3-numpy</test_depend>
   <test_depend>launch_testing</test_depend>
   <test_depend>launch_testing_ros</test_depend>
diff --git a/asv_sim/setup.py b/asv_sim/setup.py
index 82c081c..054d847 100644
--- a/asv_sim/setup.py
+++ b/asv_sim/setup.py
@@ -16,7 +16,9 @@ setup(
         (os.path.join('share', package_name, 'launch'),
             glob(os.path.join('launch', '*launch.[pxy][yma]*'))),
         (os.path.join('share', package_name, 'config'),
-            glob(os.path.join('config', '*.yaml')))
+            glob(os.path.join('config', '*.yaml'))),
+        (os.path.join('share', package_name, 'enc'),
+            glob(os.path.join('enc', '*')))
 
     ],
     install_requires=['setuptools'],
diff --git a/asv_sim/test/conftest.py b/asv_sim/test/conftest.py
index be17f8b..c36deb8 100644
--- a/asv_sim/test/conftest.py
+++ b/asv_sim/test/conftest.py
@@ -1,3 +1,34 @@
+from asv_sim import model
+import pytest
+import rclpy
+import rclpy.node
+import synthetic_grid
+
 # Skip launch_testing files when run via plain pytest (colcon test).
 # These require the launch_test runner instead.
 collect_ignore = ['test_tide_integration.py']
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
diff --git a/asv_sim/test/test_charts.py b/asv_sim/test/test_charts.py
new file mode 100644
index 0000000..62d4418
--- /dev/null
+++ b/asv_sim/test/test_charts.py
@@ -0,0 +1,290 @@
+"""Charted objects as obstacles (issue #113).
+
+The primitive builder is tested on a hand-made feature list, the obstacle
+source on primitives in metres around the synthetic test origin, and the
+reader on the two real NOAA cells installed with the package.
+
+Runs under plain pytest (``colcon test``); no launch_test runner needed.
+"""
+
+import math
+import os
+import pathlib
+
+from asv_sim import charts
+from asv_sim import collision
+import pytest
+from test_collision import ns
+from test_collision import Rig
+
+ENC_DIR = pathlib.Path(__file__).resolve().parents[1] / 'enc'
+
+
+def linear(lon, lat):
+    """Project flatly for the builder tests: 1 degree is 1000 m."""
+    return lon * 1000.0, lat * 1000.0
+
+
+def source_for(rig, primitives):
+    """Return an obstacle source whose frame is centred on the rig origin."""
+    project = charts.make_projection(rig.lon0, rig.lat0)
+    return collision.ChartedObjectSource(primitives, project)
+
+
+def solid(klass, x0, y0, x1, y1, radius, depth=None):
+    return charts.Primitive(klass, x0, y0, x1, y1, radius, depth)
+
+
+# the builder ---------------------------------------------------------------
+
+def test_a_line_becomes_one_segment_per_leg_with_the_class_half_width():
+    features = [charts.Feature(
+        'SLCONS', 'line', [[(0.0, 0.0), (0.01, 0.0), (0.01, 0.01)]], None)]
+    prims, counts = charts.build_primitives(
+        features, charts.DEFAULT_FOOTPRINTS, linear)
+    assert counts == {'SLCONS': 2}
+    assert [(p.x0, p.y0, p.x1, p.y1) for p in prims] == [
+        (0.0, 0.0, 10.0, 0.0), (10.0, 0.0, 10.0, 10.0)]
+    assert all(p.radius == charts.DEFAULT_FOOTPRINTS['SLCONS'] for p in prims)
+
+
+def test_a_point_becomes_a_circle_with_the_class_radius():
+    features = [charts.Feature('BOYLAT', 'point', [[(0.002, 0.003)]], None)]
+    prims, counts = charts.build_primitives(
+        features, charts.DEFAULT_FOOTPRINTS, linear)
+    assert counts == {'BOYLAT': 1}
+    p = prims[0]
+    assert (p.x0, p.y0, p.x1, p.y1) == (2.0, 3.0, 2.0, 3.0)
+    assert p.radius == charts.DEFAULT_FOOTPRINTS['BOYLAT']
+
+
+def test_an_area_contributes_all_its_rings_as_segments():
+    outer = [(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01), (0, 0)]
+    hole = [(0.002, 0.002), (0.004, 0.002), (0.004, 0.004), (0.002, 0.002)]
+    features = [charts.Feature('PONTON', 'area', [outer, hole], None)]
+    prims, counts = charts.build_primitives(
+        features, charts.DEFAULT_FOOTPRINTS, linear)
+    assert counts == {'PONTON': 4 + 3}
+
+
+def test_the_charted_depth_is_carried_and_a_class_of_size_zero_is_left_out():
+    features = [
+        charts.Feature('UWTROC', 'point', [[(0.0, 0.0)]], 0.3),
+        charts.Feature('BOYLAT', 'point', [[(0.0, 0.0)]], None)]
+    table = charts.parse_footprints(['BOYLAT=0'])
+    prims, counts = charts.build_primitives(features, table, linear)
+    assert counts == {'UWTROC': 1}
+    assert prims[0].depth == 0.3
+
+
+def test_footprint_overrides_replace_the_defaults():
+    table = charts.parse_footprints(['boylat=2.5', 'SLCONS = 0.1'])
+    assert table['BOYLAT'] == 2.5 and table['SLCONS'] == 0.1
+    assert table['PILPNT'] == charts.DEFAULT_FOOTPRINTS['PILPNT']
+
+
+@pytest.mark.parametrize('entry', ['BOYLAT', 'BOYLAT=big', 'BOYLAT=-1',
+                                   'BOYLAT=nan', 'LNDARE=1', '=2'])
+def test_a_bad_footprint_override_is_refused(entry):
+    with pytest.raises(ValueError, match='collision.enc_footprints'):
+        charts.parse_footprints([entry])
+
+
+def test_a_path_that_is_not_there_or_holds_no_cell_is_refused(tmp_path):
+    with pytest.raises(FileNotFoundError):
+        charts.find_cells(str(tmp_path / 'absent'))
+    with pytest.raises(FileNotFoundError, match='no .000'):
+        charts.find_cells(str(tmp_path))
+
+
+# the obstacle source -------------------------------------------------------
+
+def bow_east(rig, d):
+    return rig.en(d)[0] + d.model.length / 2.0
+
+
+def test_a_boat_driven_at_a_pier_stops_at_it_and_backs_off(mdl, world):
+    rig = Rig(mdl, world, terrain=False)
+    # a north-south pier 2 m wide, 30 m east of the origin
+    rig.collisions.sources.append(source_for(rig, [
+        solid('SLCONS', 30.0, -60.0, 30.0, 60.0, 1.0)]))
+    a = rig.add('a', 0.0, 0.0, 90.0)
+    rig.run(25.0, {'a': 1.0})
+    assert bow_east(rig, a) == pytest.approx(29.0, abs=0.1)
+    assert abs(a.speed) < 0.2
+    assert [(e['kind'], e['other']) for e in rig.events] == [
+        (collision.KIND_OBJECT, 'SLCONS')]
+    rig.run(8.0, {'a': -1.0})
+    assert bow_east(rig, a) < 25.0
+
+
+def test_a_buoy_blocks_head_on_and_lets_a_boat_slide_past(mdl, world):
+    rig = Rig(mdl, world, terrain=False)
+    rig.collisions.sources.append(source_for(rig, [
+        solid('BOYLAT', 30.0, 0.0, 30.0, 0.0, 1.0),
+        solid('BOYLAT', 30.0, 40.0, 30.0, 40.0, 1.0)]))
+    head_on = rig.add('head_on', 0.0, 0.0, 90.0)
+    glancing = rig.add('glancing', 0.0, 38.4, 90.0)
+    rig.run(25.0, {'head_on': 1.0, 'glancing': 1.0})
+    assert bow_east(rig, head_on) < 30.0
+    assert abs(head_on.speed) < 0.3
+    assert rig.en(glancing)[0] > 33.0, 'it slid around the buoy'
+    objects = {(e['platform'], e['other']) for e in rig.events}
+    assert ('head_on', 'BOYLAT') in objects
+
+
+def test_a_charted_depth_blocks_only_while_the_water_over_it_is_too_shallow(
+        mdl, world):
+    # a rock with 0.2 m over it and a boat that draws 0.4 m
+    for tide, blocked in ((0.0, True), (0.1, True), (1.0, False)):
+        rig = Rig(mdl, world, terrain=False, tide=tide)
+        rig.collisions.sources.append(source_for(rig, [
+            solid('UWTROC', 20.0, 0.0, 20.0, 0.0, 1.0, depth=0.2)]))
+        a = rig.add('a', 0.0, 0.0, 90.0)
+        rig.run(20.0, {'a': 1.0})
+        assert (rig.en(a)[0] < 20.0) == blocked, tide
+
+
+def test_an_object_without_a_charted_depth_blocks_at_every_tide(mdl, world):
+    rig = Rig(mdl, world, terrain=False, tide=5.0)
+    rig.collisions.sources.append(source_for(rig, [
+        solid('WRECKS', 20.0, 0.0, 20.0, 0.0, 1.5)]))
+    a = rig.add('a', 0.0, 0.0, 90.0)
+    rig.run(20.0, {'a': 1.0})
+    assert bow_east(rig, a) < 20.0
+
+
+def test_objects_far_from_the_boat_do_not_matter(mdl, world):
+    rig = Rig(mdl, world, terrain=False)
+    rig.collisions.sources.append(source_for(rig, [
+        solid('SLCONS', 5000.0, -60.0, 5000.0, 60.0, 1.0),
+        solid('BOYLAT', 0.0, -500.0, 0.0, -500.0, 1.0)]))
+    a = rig.add('a', 0.0, 0.0, 90.0)
+    rig.run(20.0, {'a': 1.0})
+    assert rig.en(a)[0] > 30.0
+    assert not rig.events
+
+
+def test_a_long_step_is_checked_in_pieces_against_a_pier(mdl, world):
+    mdl.max_step = 10.0
+    rig = Rig(mdl, world, terrain=False)
+    rig.collisions.sources.append(source_for(rig, [
+        solid('SLCONS', 30.0, -60.0, 30.0, 60.0, 1.0)]))
+    a = rig.add('a', 5.0, 0.0, 90.0)
+    a.speed = 2.75
+    a.update(1.0, 0.0, ns(0.0), apply_noise=False)
+    a.update(1.0, 0.0, ns(10.0), apply_noise=False)
+    assert bow_east(rig, a) < 30.0
+
+
+def test_a_boat_lying_across_a_pier_is_pushed_clear(mdl, world):
+    rig = Rig(mdl, world, terrain=False)
+    rig.collisions.sources.append(source_for(rig, [
+        solid('SLCONS', 0.0, -60.0, 0.0, 60.0, 1.0)]))
+    a = rig.add('a', 0.0, 0.0, 90.0)   # its hull runs across the pier
+    rig.run(1.0, {})
+    east, _ = rig.en(a)
+    assert abs(east) > 2.0 + 1.0 - 0.1, 'bow to stern clear of the pier'
+
+
+# the real cells ------------------------------------------------------------
+
+def test_the_installed_cells_give_every_expected_class():
+    primitives, project, counts = charts.load(str(ENC_DIR))
+    for klass in ('SLCONS', 'PONTON', 'PILPNT', 'BOYLAT', 'BOYSPP', 'BCNLAT',
+                  'UWTROC', 'WRECKS', 'OBSTRN'):
+        assert counts.get(klass, 0) > 0, klass
+    assert len(primitives) == sum(counts.values()) > 5000
+    # Cod Rock Lighted Buoy 5, 28 m north of the demo's first start
+    x, y = project(math.radians(43.074547), math.radians(-70.711249))
+    near = [p for p in primitives
+            if p.klass == 'BOYLAT' and math.hypot(p.x0 - x, p.y0 - y) < 1.0]
+    assert near, 'the buoy is in the primitives'
+
+
+def test_the_cells_cover_the_demo_area_and_nothing_is_far_away():
+    primitives, project, counts = charts.load(str(ENC_DIR))
+    x0, y0 = project(math.radians(43.0537), math.radians(-70.7405))
+    x1, y1 = project(math.radians(43.0937), math.radians(-70.6695))
+    inside = [p for p in primitives
+              if min(x0, x1) <= p.x0 <= max(x0, x1)
+              and min(y0, y1) <= p.y0 <= max(y0, y1)]
+    assert len(inside) > 0.5 * len(primitives)
+
+
+def _clear_approach(primitives):
+    """Return ``(pier, sign)``: a long charted pier and the side to come from.
+
+    The corridor from 25 m out to the pier's middle must hold no other
+    primitive within 4 m, so the only thing the boat can meet is the pier.
+    """
+    piers = sorted(
+        (p for p in primitives if p.klass == 'SLCONS'
+         and math.hypot(p.x1 - p.x0, p.y1 - p.y0) > 15.0),
+        key=lambda p: -math.hypot(p.x1 - p.x0, p.y1 - p.y0))
+    for pier in piers:
+        length = math.hypot(pier.x1 - pier.x0, pier.y1 - pier.y0)
+        mx, my = (pier.x0 + pier.x1) / 2.0, (pier.y0 + pier.y1) / 2.0
+        nx, ny = -(pier.y1 - pier.y0) / length, (pier.x1 - pier.x0) / length
+        for sign in (1.0, -1.0):
+            start = (mx + sign * nx * 28.0, my + sign * ny * 28.0)
+            end = (mx + sign * nx * (pier.radius + 0.5),
+                   my + sign * ny * (pier.radius + 0.5))
+            if all(p is pier or _distance_to_segment(p, start, end) > 4.0
+                   for p in primitives):
+                return pier, sign
+    raise AssertionError('no charted pier with a clear approach')
+
+
+def _distance_to_segment(p, a, b):
+    """Distance in metres from a primitive's nearest point to segment a-b."""
+    near, far = collision.segment_closest(
+        (p.x0, p.y0), (p.x1, p.y1), a, b)
+    return math.hypot(near[0] - far[0], near[1] - far[1]) - p.radius
+
+
+def test_a_boat_driven_at_a_charted_pier_of_the_real_cells_stops(mdl, world):
+    primitives, project, _ = charts.load(str(ENC_DIR))
+    pier, sign = _clear_approach(primitives)
+    length = math.hypot(pier.x1 - pier.x0, pier.y1 - pier.y0)
+    mx, my = (pier.x0 + pier.x1) / 2.0, (pier.y0 + pier.y1) / 2.0
+    nx, ny = -(pier.y1 - pier.y0) / length, (pier.x1 - pier.x0) / length
+    start_x, start_y = mx + sign * nx * 25.0, my + sign * ny * 25.0
+    heading = math.degrees(math.atan2(-sign * nx, -sign * ny)) % 360.0
+
+    rig = Rig(mdl, world, terrain=False)
+    rig.collisions.sources.append(
+        collision.ChartedObjectSource(primitives, project))
+    d = rig.add('a', 0.0, 0.0, heading)
+    # the cells use their own frame: put the boat at its projected start
+    lat, lon = _unproject(project, start_x, start_y)
+    d.set(math.degrees(lat), math.degrees(lon), heading)
+    d.last_update = None
+
+    rig.run(30.0, {'a': 1.0})
+    x, y = project(d.latitude, d.longitude)
+    gap = abs((x - mx) * nx + (y - my) * ny)
+    # bow to centre: half the hull axis (1.15) plus its radius (0.85) plus
+    # the pier's half width
+    assert gap == pytest.approx(2.0 + pier.radius, abs=0.6)
+    assert [e['other'] for e in rig.events][:1] == ['SLCONS']
+    rig.run(8.0, {'a': -1.0})
+    x2, y2 = project(d.latitude, d.longitude)
+    assert abs((x2 - mx) * nx + (y2 - my) * ny) > gap + 3.0
+
+
+def _unproject(project, x, y):
+    """Find the (lat, lon) radians that project to (x, y) by iteration."""
+    lat, lon = math.radians(43.07), math.radians(-70.71)
+    for _ in range(20):
+        px, py = project(lat, lon)
+        east, north = x - px, y - py
+        lat, lon = collision.move_en(lat, lon, east, north)
+    return lat, lon
+
+
+def test_the_package_ships_the_cells_it_documents():
+    names = sorted(os.listdir(ENC_DIR))
+    for needed in ('US5PSMCC.000', 'US5PSMCD.000', 'US5PSMCD.001',
+                   'README.md', 'NOAA_USERAGREEMENT.TXT'):
+        assert needed in names
diff --git a/asv_sim/test/test_collision.py b/asv_sim/test/test_collision.py
index 2fbde59..ce0e686 100644
--- a/asv_sim/test/test_collision.py
+++ b/asv_sim/test/test_collision.py
@@ -76,42 +76,18 @@ def ns(seconds):
     return Time(nanoseconds=int(round(seconds * 1e9)))
 
 
-@pytest.fixture
-def mdl():
-    rclpy.init()
-    node = rclpy.node.Node('collision_test')
-    try:
-        yield model.Model('demo', node)
-    finally:
-        node.destroy_node()
-        rclpy.shutdown()
-
-
-@pytest.fixture(scope='module')
-def origin_and_grid(tmp_path_factory):
-    path = str(tmp_path_factory.mktemp('grid') / 'truth.tif')
-    lat, lon = synthetic_grid.write_grid(path)
-    return lat, lon, path
-
-
-@pytest.fixture
-def world(origin_and_grid):
-    from mbes_sim.bathy_grid import BathyGrid
-    lat, lon, path = origin_and_grid
-    return lat, lon, BathyGrid(path)
-
-
 class Rig:
     """Boats on the synthetic grid, stepped by hand."""
 
-    def __init__(self, mdl, world, boats=True, terrain=True, tide=0.0):
+    def __init__(self, mdl, world, boats=True, terrain=True, tide=0.0,
+                 objects=None):
         self.lat0, self.lon0, grid = world
         self.mdl = mdl
         self.log = Recorder()
         self.events = []
         self.collisions = collision.Collisions(
             grid=grid if terrain else None, boats=boats,
-            emit=self.events.append, logger=self.log)
+            emit=self.events.append, logger=self.log, objects=objects)
         self.env = Tide(tide)
         self.boats = {}
         self.frozen = {}
diff --git a/asv_sim/test/test_multi_platform.py b/asv_sim/test/test_multi_platform.py
index 35cb6f7..25d3209 100644
--- a/asv_sim/test/test_multi_platform.py
+++ b/asv_sim/test/test_multi_platform.py
@@ -452,3 +452,34 @@ def test_the_grid_stops_a_boat_at_the_shore_through_the_node(tmp_path):
         assert kinds == {Collision.KIND_TERRAIN}
     finally:
         r.close()
+
+
+ENC_DIR = pathlib.Path(__file__).resolve().parents[1] / 'enc'
+
+
+def test_the_node_reads_charted_objects_from_a_cell_directory(tmp_path):
+    r = Rig(tmp_path, {'collision.enc_dir': str(ENC_DIR),
+                       'collision.enc_footprints': ['BOYLAT=2.0', 'UWTROC=0']})
+    try:
+        r.wait_for_fixes()
+        sources = r.sim.collisions.sources
+        objects = [s for s in sources
+                   if type(s).__name__ == 'ChartedObjectSource']
+        assert len(objects) == 1
+        klasses = {p.klass for p in objects[0].primitives}
+        assert 'SLCONS' in klasses and 'UWTROC' not in klasses
+        assert {p.radius for p in objects[0].primitives
+                if p.klass == 'BOYLAT'} == {2.0}
+    finally:
+        r.close()
+
+
+@pytest.mark.parametrize('extra', [
+    {'collision.enc_dir': '/no/such/enc'},
+    {'collision.enc_dir': str(ENC_DIR),
+     'collision.enc_footprints': ['LNDARE=1']},
+])
+def test_unusable_charted_object_settings_refuse_to_start(tmp_path, extra):
+    with pytest.raises((FileNotFoundError, ValueError)):
+        Rig(tmp_path, extra)
+    assert not rclpy.ok()
diff --git a/asv_sim_msgs/msg/Collision.msg b/asv_sim_msgs/msg/Collision.msg
index 51e585f..022b17d 100644
--- a/asv_sim_msgs/msg/Collision.msg
+++ b/asv_sim_msgs/msg/Collision.msg
@@ -11,9 +11,12 @@ string platform
 
 uint8 KIND_BOAT = 0
 uint8 KIND_TERRAIN = 1
+uint8 KIND_OBJECT = 2
 uint8 kind
 
-# Name of the other boat for KIND_BOAT; empty for KIND_TERRAIN.
+# Name of the other boat for KIND_BOAT; the S-57 class of the charted
+# object (SLCONS, PONTON, PILPNT, BOYLAT, UWTROC, WRECKS, ...) for
+# KIND_OBJECT; empty for KIND_TERRAIN.
 string other
 
 # Where the blocked boat is, degrees.
@@ -26,5 +29,5 @@ float32 closing_speed
 
 # KIND_TERRAIN: water depth (grid depth plus tide) in metres under the
 # hull centre at the place the boat tried to go; NaN where there is no
-# water or no data. KIND_BOAT: NaN.
+# water or no data. KIND_BOAT and KIND_OBJECT: NaN.
 float32 water_depth
diff --git a/marine_simulation/README.md b/marine_simulation/README.md
index 6c8ee31..417db60 100644
--- a/marine_simulation/README.md
+++ b/marine_simulation/README.md
@@ -493,6 +493,7 @@ The venue is Portsmouth Harbour. The simulated multibeams sample the demo truth
 | `joystick_config` | `config/demo_joysticks.yaml` | Joystick device links; copy and edit per host. |
 | `enable_joysticks` | `true` | Start a `joy_linux` driver per boat. `joy_to_helm` runs either way, so `sensor_msgs/Joy` on `<boat>/joy` drives the boat. |
 | `enable_nav` | `false` | Reserved. `true` is refused ("not wired yet"). |
+| `charted_objects` | `true` | The piers, pontoons, piles, buoys, beacons, rocks and wrecks of the ENC cells installed with `asv_sim` (`share/asv_sim/enc`) block the boats; `false` leaves them out. |
 | `tide_speed_factor` | `10` | Tide speed multiplier (10 = about a 75 minute cycle, 0 = a frozen tide). |
 | `current_speed` | `0.0` | Water current in m/s. `asv_sim` itself defaults to 1.0 m/s toward 090, which drifts an undriven boat east at about 2 knots. |
 | `mbes_grid_file` | empty | Ground-truth bathymetry the simulated multibeams sample. Empty means `$MBES_DEMO_GRID`, else `~/data/sim/mbes_truth/portsmouth_demo_utm19n.tif` when it exists, else `mbes_sim/data/US5NH02M.tiff` (the launch prints which and why, on stderr). An explicit path must be a file. |
@@ -764,8 +765,9 @@ so the shallows move in and out within a round; at low water a boat can be
 aground and must back out. Contacts are announced on `/asv_sim/collisions`
 (`asv_sim_msgs/msg/Collision`). To let boats pass through each other, start
 `asv_sim` with `collision.boats:=false` (not a launch argument yet; set it in a
-copy of `demo.yaml`). Charted objects (piers, buoys, rocks) are not obstacles
-yet (issue #113). Details: `asv_sim/README.md`.
+copy of `demo.yaml`). Charted objects (piers, pontoons, piles,
+buoys, beacons, rocks, wrecks of the S-57 cells in `asv_sim/enc`) block the boats too
+(`charted_objects:=false` turns them off); a contact names the S-57 class in the event. Details: `asv_sim/README.md`.
 
 ### Known limits
 
diff --git a/marine_simulation/launch/demo_boats_launch.py b/marine_simulation/launch/demo_boats_launch.py
index e08cacc..3b02f65 100644
--- a/marine_simulation/launch/demo_boats_launch.py
+++ b/marine_simulation/launch/demo_boats_launch.py
@@ -317,12 +317,14 @@ def refuse_enable_nav(enable_nav: str) -> None:
 
 def asv_sim_parameters(
         boats: Sequence[Boat], tide_speed_factor: float, current_speed: float,
-        grid_file: str = '') -> dict:
+        grid_file: str = '', enc_dir: str = '') -> dict:
     """
     Return the ``asv_sim`` parameters for the selected boats.
 
     ``grid_file`` is the bathymetry the sonars sample; ``asv_sim`` grounds the boats on it
     (empty: boats still block each other but the sea floor and shore do not stop them).
+    ``enc_dir`` holds the S-57 cells whose piers, pontoons, piles, buoys, rocks and wrecks
+    block the boats (empty: charted objects do not).
     """
     params = {
         'platforms': [b.name for b in boats],
@@ -331,6 +333,8 @@ def asv_sim_parameters(
     }
     if grid_file:
         params['collision.grid_file'] = grid_file
+    if enc_dir:
+        params['collision.enc_dir'] = enc_dir
     for b in boats:
         prefix = 'platforms.%s.' % b.name
         params[prefix + 'model'] = 'demo'
@@ -600,6 +604,13 @@ def launch_setup(context, *args, **kwargs):
         'autorepeat_rate': 10.0,
     }
     tide_speed_factor = parse_tide_speed_factor(arg('tide_speed_factor'))
+    enc_dir = ''
+    if parse_bool(arg('charted_objects'), 'charted_objects'):
+        enc_dir = os.path.join(get_package_share_directory('asv_sim'), 'enc')
+        if not os.path.isdir(enc_dir):
+            raise RuntimeError(
+                'charted_objects is on but %s is not installed; rebuild asv_sim or launch '
+                'with charted_objects:=false' % enc_dir)
     current_speed = parse_float(arg('current_speed'), 'current_speed', low=0.0)
     check_datum_grids()
 
@@ -623,7 +634,8 @@ def launch_setup(context, *args, **kwargs):
             package='asv_sim', executable='asv_sim', name='asv_sim', emulate_tty=True,
             parameters=[
                 PathJoinSubstitution([FindPackageShare('asv_sim'), 'config', 'demo.yaml']),
-                asv_sim_parameters(boats, tide_speed_factor, current_speed, mbes_grid_file),
+                asv_sim_parameters(
+                    boats, tide_speed_factor, current_speed, mbes_grid_file, enc_dir),
             ],
             remappings=asv_sim_remappings(boats)),
     ]
@@ -661,6 +673,9 @@ def generate_launch_description():
         declare('tide_speed_factor', TextSubstitution(text='10'),
                 'Tide speed multiplier (10 = ~75 min cycle, 3600 = ~12 sec cycle, '
                 '1 = real-time, 0 = a frozen tide).'),
+        declare('charted_objects', TextSubstitution(text='true'),
+                'true: piers, pontoons, piles, buoys, beacons, rocks and wrecks of the ENC cells '
+                'installed with asv_sim block the boats; false: they do not.'),
         declare('current_speed', TextSubstitution(text='0.0'),
                 'Water current in m/s. asv_sim itself defaults to 1.0 m/s toward 090, '
                 'which drifts every boat; the demo defaults to none.'),
diff --git a/marine_simulation/test/test_demo_boats_launch.py b/marine_simulation/test/test_demo_boats_launch.py
index f569479..fbdfd66 100644
--- a/marine_simulation/test/test_demo_boats_launch.py
+++ b/marine_simulation/test/test_demo_boats_launch.py
@@ -534,6 +534,12 @@ def test_asv_sim_grounds_the_boats_on_the_sonar_grid_when_there_is_one(roster):
     assert 'collision.grid_file' not in demo.asv_sim_parameters(roster, 10.0, 0.0)
 
 
+def test_asv_sim_gets_the_charted_objects_when_a_cell_directory_is_given(roster):
+    params = demo.asv_sim_parameters(roster, 10.0, 0.0, '', '/share/asv_sim/enc')
+    assert params['collision.enc_dir'] == '/share/asv_sim/enc'
+    assert 'collision.enc_dir' not in demo.asv_sim_parameters(roster, 10.0, 0.0)
+
+
 def test_the_launch_hands_asv_sim_the_grid_the_sonars_use():
     text = LAUNCH.read_text()
     assert 'asv_sim_parameters(boats, tide_speed_factor, current_speed, mbes_grid_file)' in text
````

## Plan Context

Below is the `## Approach` section of the plan this change is meant
to implement. It is context, not the subject of the review: flag
divergences between the diff and this plan, but do not review the
plan itself.

```markdown

Approved by Roland 2026-10-20 with all ten recommendations, boat-to-boat collision ON by default for every asv_sim launch (terrain stays grid-gated). Charted objects (piers, buoys, rocks awash, wrecks) were a follow-up (#113); Roland moved them into this PR on 2026-10-20 (steps 12 to 16 below).

1. **New `asv_sim/asv_sim/collision.py`** holds all contact logic so `dynamics.py` only gains one hook. Pure functions (no ROS): capsule distance, offset helpers; `BoatSource` and `TerrainSource` classes; a `Collisions` object (owned by the node, created before the platforms) registers each platform's `Dynamics` and resolves contacts; it is the only thing that touches the grid and the event callback (the node turns events into `Collision` messages).

   **Obstacle sources.** `Collisions.resolve` does not know what a boat can hit: it runs the list `Collisions.sources`, each an object with `correct(step, lat, lon)` that takes the position the previous source left and returns the corrected position plus a list of `Contact` tuples (kind, name of what was hit, unit normal pointing away from it, velocity of the obstacle, water depth). `resolve` applies the same speed rule and one-event-per-onset bookkeeping to every contact. Boats, charted objects (#113, steps 12 to 16) and terrain are the three, in that order, so the bottom has the last word.
2. **Where it sits in the integration.** `Dynamics.__init__` takes an optional `contact` object. `_step` calls `contact.resolve(self, last_lat, last_long, timestamp)` once per **sub-step**, right after the position (own motion plus current) is applied and before `cog/sog` are computed, so `sog`/`cog` report the motion actually achieved and a long stalled gap (up to `max_step * max_substeps` = 10 s, 27 m at top speed) is resolved step by step instead of tunnelling through a shore or a hull. Not called when `delta_t is None` (first update, after `set`). `Dynamics.update` wraps the sub-steps in `except (ArithmeticError, ValueError)` that resets the boat to rest, so the hook is called inside its own try/except: a failure in contact code is logged (throttled, `_log`) and the step keeps the uncorrected position; contact code must never reset a boat or end the node. No contact object (the default in `Dynamics` tests) keeps today's behaviour exactly. `set_pose`/`sim_reset` are never blocked; they can place a boat anywhere (including aground) and the next step only stops it getting shallower.
3. **Grid (a).** New node parameter `collision.grid_file` (string, default `''` = terrain collision off, logged once at INFO). Read once at start with `mbes_sim.bathy_grid.BathyGrid` (lazy import so `asv_sim` still runs without `mbes_sim` when no grid is set; `exec_depend mbes_sim`, no cycle: `mbes_sim` does not depend on `asv_sim`). An unreadable file raises at start (a sim silently without terrain is the failure to avoid); live change is not supported. The demo launch passes the same resolved `mbes_grid_file` it gives the sonars, so one truth file drives sonar and grounding. One more copy of the array in the `asv_sim` process (27 MB demo, 69 MB chart). Tide: `Environment.getTide(timestamp)` per update; water depth = grid depth (MLLW, positive down) + tide, the same sum `mbes_sim` uses. The #98 datum caveat (CCOM compilation datum unstated, treated as MLLW) applies and goes in the README.
4. **Footprint and draft (b).** Model parameters `models.<m>.length` (4.0 m), `.beam` (1.7 m), `.draft` (0.4 m), validated: a `floating_point_range` descriptor for > 0 and an `add_on_set_parameters_callback` that rejects a later set with `length < beam` (refused with a reason, not clamped); the pair is checked once at the end of `Model.__init__` (a pair declared one after another must not be judged against the other's default), where a bad declared pair raises. The hull is a capsule: axis segment of half-length `(length - beam)/2` along `heading` through the reference position, radius `beam/2` (the position is the model's reference point; no offset parameter, the 0.5 m reference offset on Ben is below the other errors here). `cw4.yaml` and `demo.yaml` carry the values; other model files keep the defaults and get a comment saying the size is unverified.
5. **Hops, passes and order.** `resolve` splits a sub-step longer than half a beam into hops of at most that length (a long `max_step` or a fast current cannot jump a hull or shore), runs boats then terrain per hop for up to three passes, and terrain wins in a wedge between a boat and the shore (the boat may overlap the other boat for that step). Boats farther than a few hull lengths are skipped with a flat-earth test before the geodesic, which does not terminate for near-antipodal points.
6a. **Boat to boat (c).** A boat resolves only itself, against the *current* positions of the others (they are treated as fixed for that sub-step; each boat gets its own turn in its own update, at most one tick stale). For each other boat: capsule-to-capsule closest points (segments in a local metric frame at the pair, from `geodesic.inverse`); if `distance < r_a + r_b` the stepping boat is moved along the contact normal (other to self) by the penetration, which removes interpenetration and keeps the tangential displacement, so boats touch and slide but cannot pass, and reverse is always free because a move away produces no penetration. Contact that begins overlapped (placed on top of each other by `set_pose`/roster) pushes the stepping boat out by the full penetration on its next step. Contact never changes the other boat. The unit tests run with dynamics noise off; with noise on, a head-on meeting is glancing and the boats slide past each other, which is accepted.
6. **Grounding (c).** `clearance(x, y, heading) = min over 5 hull points (bow, stern, port, starboard, centre) of (water_depth - draft)`. Land is graded by its height (never clamped); nodata and off-grid are the void (-1e6), a wall. A boat in the void may move through the void or into water, never onto land or a shoal, and a warning names it once. After the step, if clearance at the new position and new heading is below 0 **and** below the clearance at the previous position and previous heading (so a turn that swings the hull onto land counts) (a boat that starts aground may move anywhere not shallower, so it can always get out), the shallower-going part of the displacement is removed: normal `n` = gradient of clearance (central differences, one grid cell), displacement `d` becomes `d - (d.n) n` if `d.n < 0`; if the slid position is still grounded, or the gradient is zero, the boat stays at the previous position; if that is not enough the heading is put back too and the yaw rate zeroed. Hull points and `n` are mapped to metres with a local east/north frame taken from `getXY` of the position and points 1 m east and 1 m north (exact grid rotation, 1.2 degrees at Portsmouth, no UTM-convergence shortcut); the corrected position goes back through `geodesic.direct` so no inverse projection is needed. Cost: about 5 grid lookups per boat per sub-step, plus the gradient only in contact.
7. **Velocity.** After either correction, with unit hull-forward `f` and contact normal `n` (pointing away from the obstacle), if `speed * (f.n) < 0` (moving into it) the new speed is `speed * (1 - (f.n)^2)`: the normal component of the velocity is dropped and only the part along the hull axis survives, so a head-on boat stops and a glancing one keeps sliding; reversing (`f.n` flips sign) is free. The current is not state; its inward part is removed by the position correction. No yaw, rpm or heading change; a turn that sweeps the hull into an obstacle is fixed by position only. `a` is recomputed from the corrected speed.
8. **Event (d).** (Round 1 review: apply the correction before reporting, so a failing publisher cannot leave a boat inside; `~/collisions` is not latched.) New message `asv_sim_msgs/msg/Collision.msg` (`std_msgs/Header header`, `string platform`, `uint8 kind` with `KIND_BOAT=0`, `KIND_TERRAIN=1`, `string other` (boat name, `''` for terrain), `float64 latitude`, `float64 longitude`, `float32 closing_speed` m/s (relative to the other boat for boat contacts), `float32 water_depth` m (grid depth plus tide at the place the boat tried to go; NaN on nodata/off-grid, and for boat contacts)), published on `~/collisions` (node-relative, reliable, depth 10). `marine_interfaces/Contact` is a perception contact (classification, shape, curation); it does not fit and would add a core-layer dependency to this package. A message is published once per contact **onset** per (platform, other); the contact is considered ended after 1 s of ROS time (node clock, so it follows `use_sim_time`) without overlap, and the same moment logs one INFO line. Events never feed back into dynamics.
9. **Parameters (e).** Node: `collision.boats` (bool, true for every launch; false skips boat-to-boat), `collision.grid_file` (above). Demo: `demo.yaml` gets `models.demo.length: 4.0`, `beam: 1.7`, `draft: 0.4`; `demo_boats_launch.asv_sim_parameters` adds `collision.grid_file` = the resolved truth grid when there is one (so the demo has terrain collision on; `sim_robot_launch.py` is untouched, terrain stays off there, boat-to-boat is on). `test_demo_config_keys_are_declared_model_parameters` already guards the new keys. Boats are indestructible: no state besides speed/position is touched.
10. **Tests (f).** `asv_sim/test/test_collision.py` (pure, plus synthetic GDAL GeoTIFF in a tmp UTM 19N grid with a land strip, a nodata block and a slope): capsule distance cases (parallel, end to end, crossing, nested); projection and slide; clearance minimum over hull points; speed projection head-on, glancing, reversing; grid depth plus tide (tide raises clearance); land and nodata are walls; started aground may leave but not go shallower; zero gradient stops. In-process node tests (extend the `Rig` pattern of `test_multi_platform.py`): two boats driven at each other never closer than the footprint sum and then back out; a boat driven at a straight shore stops, one at 45 degrees keeps sliding along it, then reverses off; a five-second stalled gap does not tunnel (boat and shore, boat and boat); one event per contact onset, none per step; a second contact after separating gives a second event; no `grid_file` means no terrain effect; an unreadable grid refuses to start; a non-finite pose does not crash; tide drained below the draft grounds a boat that floats at high water. Existing `test_dynamics_stability.py` and `test_multi_platform.py` must pass unchanged. `marine_simulation/test/test_demo_boats_launch.py`: `asv_sim_parameters` carries the grid. flake8/pep257/copyright as for the package.
11. **Docs.** `.agents/README.md` (inventory/layout line for `collision.py`, the parameter table rows, a pitfall: contact is resolved per sub-step inside `Dynamics`, never from the node loop; a new `Collision` topic), `asv_sim/README.md` (collision section, datum caveat), `marine_simulation/README.md` (demo: boats block each other and the shallows, how to turn it off, tide exaggeration makes low water a hazard), cw4/demo yaml comments.

12. **Charted objects (#113): reader.** New `asv_sim/charts.py` reads S-57 ENC cells with GDAL's OGR S-57 driver (`python3-gdal`, already `mbes_sim`'s dependency) instead of the C++ `s57_grids`/`marine_charts` stack, so asv_sim's dependency surface stays small. Classes follow `marine_charts/S57Dataset::getGrid` (read in `core_ws/src/s57_tools/marine_charts/src/s57_dataset.cpp`): what the costmap rasterises as lethal (`PILPNT`, `PYLONS`, `SLCONS`, `PONTON`, `CAUSWY`, `DAMCON`, `DYKCON`, `GATCON`, `FSHFAC`, `HULKES`, `OBSTRN`), the discrete hazards (`UWTROC`, `WRECKS`), `FLODOC`, and buoys and beacons (`BOY*`, `BCN*`), which the costmap ignores but a boat can hit; land (`LNDARE`, `COALNE`) stays with the bathymetry grid. Points become circles, lines segments with a half-width, areas their hollow rings; `UWTROC`/`WRECKS`/`OBSTRN` with a `VALSOU` carry it as a depth.
13. **Primitives and projection.** Precomputed at start in a local azimuthal-equidistant frame centred on the loaded data (data over half a degree wide are refused), with a 100 m spatial hash; the per-class counts are logged at start. The footprint table (radius or half-width per class) is `DEFAULT_FOOTPRINTS`, overridable with `collision.enc_footprints` (`CLASS=metres`, 0 drops a class).
14. **Source.** `ChartedObjectSource.correct`: hull capsule against the primitives in the buckets around the boat, through the same `capsule_penetration` as boat to boat (a circle is a capsule of no length, so crossing hulls and thin piers use the exact push); a primitive with a charted depth blocks only while depth + tide < draft; contact named by the S-57 class (`other` of the event, new `KIND_OBJECT = 2`). Order: boats, objects, terrain.
15. **Cells.** The two harbour-scale cells that cover the demo truth grid extent (lat 43.0537 to 43.0937, lon -70.7405 to -70.6695) are `US5PSMCC` (edition 4) and `US5PSMCD` (edition 5, update 1), found by scanning every cell under `~/data/ENC_ROOT` for `M_COVR` coverage; the coarser `US4NH1BD` also covers it and is left out (overlapping scales would duplicate objects). They are installed with the package (`asv_sim/enc`, about 2.3 MB, NOAA user agreement allows redistribution) so a fresh event machine needs nothing under `ENC_ROOT`. Parameters `collision.enc_dir` (default empty = off) and `collision.enc_footprints`; the demo launch passes `share/asv_sim/enc` unless `charted_objects:=false`.
16. **Charted-object tests.** `test_charts.py`: builder on a hand-made feature list (line, point, area with a hole, depth carried, class off, overrides and bad overrides, bad paths); the source on primitives around the synthetic origin (pier stop and back-off, buoy head-on and glancing, charted depth against tide, unknown depth at any tide, far objects, long step, boat across a pier); the installed cells (counts for every expected class, buoy Cod Rock Lighted Buoy 5 present, coverage of the demo area, a boat driven at the longest clear charted pier stops and backs off); node tests for the parameters. Fixtures `mdl`/`world` moved to `conftest.py`.
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
