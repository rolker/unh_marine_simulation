"""A synthetic bathymetry GeoTIFF for the collision tests (issue #111).

UTM 19N, 2 m cells, 600 m square, built around an origin near Portsmouth
Harbour:

- water 10 m deep west of a straight shore at ``SHORE_EAST`` m east of the
  origin (grid east, a degree or so off true east: UTM grid convergence);
- land (depth -2 m) east of it, with a 1 m deep shelf from ``SHELF_EAST``;
- nodata (-9999) north of ``NODATA_NORTH`` m.
"""

import math

import numpy as np
from osgeo import gdal
from osgeo import osr

# Portsmouth Harbour (the demo's start area).
LAT0 = 43.0743
LON0 = -70.7108
CELL = 2.0
SHORE_EAST = 50.0
SHELF_EAST = 30.0
NODATA_NORTH = 120.0
HALF = 300.0


def write_grid(path):
    """Write the grid to ``path``; return the (lat, lon) of its origin."""
    gdal.UseExceptions()
    geographic = osr.SpatialReference()
    geographic.SetWellKnownGeogCS('WGS84')
    utm = osr.SpatialReference()
    utm.ImportFromEPSG(32619)
    forward = osr.CoordinateTransformation(geographic, utm)
    inverse = osr.CoordinateTransformation(utm, geographic)
    x0, y0 = forward.TransformPoint(LAT0, LON0)[:2]
    x0 = math.floor(x0 / CELL) * CELL
    y0 = math.floor(y0 / CELL) * CELL
    lat, lon = inverse.TransformPoint(x0, y0)[:2]

    count = int(2 * HALF / CELL)
    east = CELL * (np.arange(count) + 0.5) - HALF
    north = HALF - CELL * (np.arange(count) + 0.5)
    e, n = np.meshgrid(east, north)
    data = np.full(e.shape, 10.0, dtype=np.float32)
    data[(e >= SHELF_EAST) & (e < SHORE_EAST)] = 1.0
    data[e >= SHORE_EAST] = -2.0
    data[n >= NODATA_NORTH] = -9999.0

    dataset = gdal.GetDriverByName('GTiff').Create(
        path, count, count, 1, gdal.GDT_Float32)
    dataset.SetGeoTransform((x0 - HALF, CELL, 0.0, y0 + HALF, 0.0, -CELL))
    dataset.SetProjection(utm.ExportToWkt())
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(-9999.0)
    band.WriteArray(data)
    dataset.FlushCache()
    return lat, lon
