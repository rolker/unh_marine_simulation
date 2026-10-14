"""Nearest-cell depth lookup in a GDAL raster (band 1, positive depth)."""

import math

from osgeo import gdal


class BathyGrid:
    """A bathymetry grid read into memory; cells are looked up by position."""

    def __init__(self, fname):
        gdal.UseExceptions()
        self.dataset = gdal.Open(fname, gdal.GA_ReadOnly)
        self.band = self.dataset.GetRasterBand(1)
        self.geoTransform = self.dataset.GetGeoTransform()
        self.inverseGeoTransform = gdal.InvGeoTransform(self.geoTransform)
        self.nodata = self.band.GetNoDataValue()
        self.data = self.band.ReadAsArray()

        sourceSR = gdal.osr.SpatialReference()
        sourceSR.SetWellKnownGeogCS('WGS84')

        targetSR = gdal.osr.SpatialReference()
        targetSR.ImportFromWkt(self.dataset.GetProjection())

        self.coordinateTransformation = gdal.osr.CoordinateTransformation(sourceSR, targetSR)

    def getXY(self, lat, lon):
        return self.coordinateTransformation.TransformPoint(lat, lon)[:2]

    def getDepthAtLatLon(self, lat, lon):
        x, y = self.getXY(lat, lon)
        return self.getDepth(x, y)

    def getDepth(self, x, y):
        """Return the depth at a grid-CRS position, or None off the grid or on a nodata cell."""
        gt = self.inverseGeoTransform
        col = math.floor(gt[0] + x * gt[1] + y * gt[2])
        row = math.floor(gt[3] + x * gt[4] + y * gt[5])
        # A negative index must not wrap to the far edge of the array.
        if row < 0 or col < 0 or row >= self.data.shape[0] or col >= self.data.shape[1]:
            return None
        value = self.data[row, col]
        if math.isnan(value) or (self.nodata is not None and value == self.nodata):
            return None
        return value
