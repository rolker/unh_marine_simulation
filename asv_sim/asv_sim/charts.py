"""Charted objects from S-57 ENC cells as obstacle primitives (issue #113).

Reads the cells with GDAL's OGR S-57 driver (the ``python3-gdal`` that
``mbes_sim`` already needs; the C++ ``s57_grids`` stack is not used, to keep
``asv_sim``'s dependencies small). Every feature of a solid class becomes
circles (points) or segments with a half-width (lines, and the rings of
areas, which are hollow: a boat cannot cross the ring, the inside is never
entered).

The classes follow the classification of ``marine_charts``'s
``S57Dataset::getGrid`` (the real boats' costmap): the ones it rasterises as
lethal (``PILPNT``, ``PYLONS``, ``SLCONS``, ``PONTON``, ``CAUSWY``,
``DAMCON``, ``DYKCON``, ``GATCON``, ``FSHFAC``, ``HULKES``, ``OBSTRN``) and
the discrete hazards (``UWTROC``, ``WRECKS``), plus ``FLODOC`` (a depth area
there, a floating dock here) and buoys and beacons, which the costmap
ignores but a boat can hit. Land (``LNDARE``, ``COALNE``) is left to the
bathymetry grid.
"""

from collections import namedtuple
import glob
import math
import os

# A solid thing in a local metric frame: a circle is a segment of no length.
# ``depth`` is the charted depth over it in metres (positive down, chart
# datum); ``None`` means solid at every tide.
Primitive = namedtuple(
    'Primitive', ['klass', 'x0', 'y0', 'x1', 'y1', 'radius', 'depth'])

# A feature read from a cell: ``parts`` are lists of (lon, lat) degrees;
# ``kind`` is 'point', 'line' or 'area' (its rings are the parts).
Feature = namedtuple(
    'Feature', ['klass', 'kind', 'parts', 'depth', 'cell'], defaults=[''])

# Radius (point) or half-width (line, ring of an area) in metres; 0 leaves a
# class out. Overridable with ``collision.enc_footprints``.
DEFAULT_FOOTPRINTS = {
    'SLCONS': 1.0,   # shoreline construction: piers, quays, walls
    'PONTON': 0.5,   # pontoons, floating docks of marinas
    'FLODOC': 0.5,   # floating dock
    'PILPNT': 0.5,   # pile
    'PYLONS': 1.5,   # bridge supports and pylons
    'CAUSWY': 1.0,
    'DAMCON': 1.0,
    'DYKCON': 1.0,
    'GATCON': 1.0,
    'FSHFAC': 1.0,   # fishing facility
    'HULKES': 1.0,   # hulk
    'OBSTRN': 1.0,   # obstruction
    'WRECKS': 1.5,
    'UWTROC': 1.0,   # underwater or awash rock
    'BCNCAR': 0.75, 'BCNISD': 0.75, 'BCNLAT': 0.75, 'BCNSAW': 0.75,
    'BCNSPP': 0.75,  # beacons
    'BOYCAR': 1.0, 'BOYINB': 1.0, 'BOYISD': 1.0, 'BOYLAT': 1.0,
    'BOYSAW': 1.0, 'BOYSPP': 1.0,  # buoys
}

# Classes whose charted VALSOU (value of sounding) decides whether a boat of
# a given draft can pass over them at the current tide; without one they are
# solid at every tide.
SOUNDED_CLASSES = ('UWTROC', 'WRECKS', 'OBSTRN')

# Data this many degrees apart no longer fit one local frame to a metre.
MAX_SPAN_DEGREES = 0.5


def parse_footprints(overrides, base=None):
    """Return the footprint table with ``["CLASS=metres", ...]`` applied.

    :raises ValueError: for an entry that is not ``CLASS=number``, a class
        that is not a known one, or a negative or non-finite size.
    """
    table = dict(DEFAULT_FOOTPRINTS if base is None else base)
    for entry in overrides:
        name, sep, value = str(entry).partition('=')
        name = name.strip().upper()
        try:
            metres = float(value)
        except ValueError:
            metres = math.nan
        if not sep or not math.isfinite(metres) or metres < 0.0:
            raise ValueError(
                'collision.enc_footprints entry {!r} is not CLASS=metres '
                '(0 or more)'.format(entry))
        if name not in DEFAULT_FOOTPRINTS:
            raise ValueError(
                'collision.enc_footprints: {!r} is not a charted class '
                'asv_sim knows ({})'.format(
                    name, ', '.join(sorted(DEFAULT_FOOTPRINTS))))
        table[name] = metres
    return table


def find_cells(path):
    """Return the ``.000`` cell files at a path (a file or a directory).

    A directory may hold the cells directly or, as an ``ENC_ROOT`` does, one
    directory per cell.
    """
    path = os.path.expanduser(path)
    if os.path.isfile(path):
        return [path]
    if not os.path.isdir(path):
        raise FileNotFoundError(
            'collision.enc_dir {!r} is not a file or directory'.format(path))
    cells = sorted(set(glob.glob(os.path.join(path, '*.000'))
                       + glob.glob(os.path.join(path, '*', '*.000'))))
    if not cells:
        raise FileNotFoundError(
            'collision.enc_dir {!r} holds no .000 cell'.format(path))
    return cells


def read_features(cells, classes):
    """Read the features of the given classes from S-57 cells with OGR."""
    from osgeo import gdal
    from osgeo import ogr
    gdal.UseExceptions()
    wanted = set(classes)
    features = []
    for cell in cells:
        dataset = ogr.Open(cell)
        if dataset is None:
            raise OSError('cannot open the S-57 cell {!r}: {}'.format(
                cell, gdal.GetLastErrorMsg() or 'not an S-57 file'))
        for index in range(dataset.GetLayerCount()):
            layer = dataset.GetLayerByIndex(index)
            klass = layer.GetName()
            if klass not in wanted:
                continue
            fields = [layer.GetLayerDefn().GetFieldDefn(i).GetName()
                      for i in range(layer.GetLayerDefn().GetFieldCount())]
            for feature in layer:
                geometry = feature.GetGeometryRef()
                if geometry is None:
                    continue
                depth = None
                if klass in SOUNDED_CLASSES and 'VALSOU' in fields:
                    i = fields.index('VALSOU')
                    if feature.IsFieldSetAndNotNull(i):
                        depth = feature.GetFieldAsDouble(i)
                for kind, parts in _parts(geometry):
                    features.append(Feature(
                        klass, kind, parts, depth, os.path.basename(cell)))
        dataset = None
    return features


def _parts(geometry):
    """Yield ``(kind, parts)`` for an OGR geometry (collections recursed)."""
    from osgeo import ogr
    kind = ogr.GT_Flatten(geometry.GetGeometryType())
    if kind == ogr.wkbPoint:
        yield 'point', [[(geometry.GetX(), geometry.GetY())]]
    elif kind == ogr.wkbLineString:
        yield 'line', [[(p[0], p[1]) for p in geometry.GetPoints()]]
    elif kind == ogr.wkbPolygon:
        yield 'area', [[(p[0], p[1]) for p in ring.GetPoints()]
                       for ring in (geometry.GetGeometryRef(i)
                                    for i in range(geometry.GetGeometryCount()))]
    elif kind in (ogr.wkbMultiPoint, ogr.wkbMultiLineString,
                  ogr.wkbMultiPolygon, ogr.wkbGeometryCollection):
        for i in range(geometry.GetGeometryCount()):
            yield from _parts(geometry.GetGeometryRef(i))


def make_projection(lon0, lat0):
    """Return ``project(lat, lon) -> (x, y)``: azimuthal equidistant metres.

    Centred on ``(lon0, lat0)`` degrees, x east and y north; within the
    :data:`MAX_SPAN_DEGREES` the distortion is below a centimetre per
    kilometre, and the rotation from true north below a degree.
    """
    from osgeo import osr
    source = osr.SpatialReference()
    source.SetWellKnownGeogCS('WGS84')
    # Latitude first, as ``project`` passes it; explicit, not GDAL's default.
    source.SetAxisMappingStrategy(osr.OAMS_AUTHORITY_COMPLIANT)
    target = osr.SpatialReference()
    target.ImportFromProj4(
        '+proj=aeqd +lat_0={:.9f} +lon_0={:.9f} +x_0=0 +y_0=0 '
        '+datum=WGS84 +units=m +no_defs'.format(lat0, lon0))
    transform = osr.CoordinateTransformation(source, target)

    def project(lat, lon):
        # GDAL 3 takes WGS84 in authority order: latitude first.
        x, y = transform.TransformPoint(math.degrees(lat), math.degrees(lon))[:2]
        return x, y

    def project_degrees(lon, lat):
        x, y = transform.TransformPoint(lat, lon)[:2]
        return x, y

    project.degrees = project_degrees
    return project


def build_primitives(features, footprints, project_degrees):
    """Turn features into primitives; return ``(primitives, counts)``.

    :param project_degrees: ``(lon, lat) -> (x, y)`` in metres.
    :param footprints: class -> radius or half-width in metres.
    :return: A list of :class:`Primitive` and a ``{class: count}`` of the
        primitives made (a line of three segments counts three).
    """
    primitives = []
    counts = {}
    for feature in features:
        size = footprints.get(feature.klass, 0.0)
        if size <= 0.0:
            continue
        made = 0
        for ring in feature.parts:
            points = [project_degrees(lon, lat) for lon, lat in ring]
            if feature.kind == 'point' or len(points) == 1:
                x, y = points[0]
                primitives.append(Primitive(
                    feature.klass, x, y, x, y, size, feature.depth))
                made += 1
                continue
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                primitives.append(Primitive(
                    feature.klass, x0, y0, x1, y1, size, feature.depth))
                made += 1
        if made:
            counts[feature.klass] = counts.get(feature.klass, 0) + made
    return primitives, counts


def load(path, footprint_overrides=()):
    """Read the cells at ``path``; return ``(primitives, project, counts)``.

    :raises ValueError: when the features span more than
        :data:`MAX_SPAN_DEGREES` (point ``path`` at the cells of the area).
    """
    footprints = parse_footprints(footprint_overrides)
    cells = find_cells(path)
    features = read_features(
        cells, [k for k, v in footprints.items() if v > 0.0])
    lons = [lon for f in features for ring in f.parts for lon, _ in ring]
    lats = [lat for f in features for ring in f.parts for _, lat in ring]
    if not lons:
        return [], make_projection(0.0, 0.0), {}
    if max(lons) - min(lons) > MAX_SPAN_DEGREES \
            or max(lats) - min(lats) > MAX_SPAN_DEGREES:
        far = sorted({f.cell for f in features for ring in f.parts
                      for lon, lat in ring
                      if lon in (min(lons), max(lons))
                      or lat in (min(lats), max(lats))})
        raise ValueError(
            'the charted objects in {!r} span {:.2f} x {:.2f} degrees, more '
            'than the {} a local frame holds (outermost features come from '
            '{}); point collision.enc_dir at the cells of the area'.format(
                path, max(lons) - min(lons), max(lats) - min(lats),
                MAX_SPAN_DEGREES, ', '.join(far)))
    project = make_projection((max(lons) + min(lons)) / 2.0,
                              (max(lats) + min(lats)) / 2.0)
    primitives, counts = build_primitives(
        features, footprints, project.degrees)
    return primitives, project, counts
