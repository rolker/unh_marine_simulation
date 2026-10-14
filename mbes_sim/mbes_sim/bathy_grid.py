import math

from osgeo import gdal


class BathyGrid:
    def __init__(self, fname):
        gdal.UseExceptions()
        self.dataset = gdal.Open(fname, gdal.GA_ReadOnly)
        self.band = self.dataset.GetRasterBand(1)
        self.geoTransform = self.dataset.GetGeoTransform()
        self.inverseGeoTransform = gdal.InvGeoTransform(self.geoTransform)
        self.nodata = self.band.GetNoDataValue()
        self.data = self.band.ReadAsArray()
        
        sourceSR = gdal.osr.SpatialReference()
        sourceSR.SetWellKnownGeogCS("WGS84")
        
        targetSR = gdal.osr.SpatialReference()
        targetSR.ImportFromWkt(self.dataset.GetProjection())
        
        self.coordinateTransformation = gdal.osr.CoordinateTransformation(sourceSR, targetSR)

    def getXY(self,lat,lon):
        return self.coordinateTransformation.TransformPoint(lat,lon)[:2]
        
    def getDepthAtLatLon(self,lat,lon):
        x,y = self.getXY(lat,lon)
        return self.getDepth(x,y)

    def getDepth(self,x,y):
        """Depth at a grid-CRS position, or None outside the grid or on a nodata cell."""
        xi = self.inverseGeoTransform[0]+x*self.inverseGeoTransform[1]+y*self.inverseGeoTransform[2]
        yi = self.inverseGeoTransform[3]+x*self.inverseGeoTransform[4]+y*self.inverseGeoTransform[5]
        col = math.floor(xi)
        row = math.floor(yi)
        # Negative indices must not wrap to the far edge of the array.
        if row < 0 or col < 0 or row >= self.data.shape[0] or col >= self.data.shape[1]:
            return None
        value = self.data[row,col]
        if math.isnan(value) or (self.nodata is not None and value == self.nodata):
            return None
        return value
