"""Tests for BathyGrid cell lookup: nodata and the grid edges."""

import math

from mbes_sim.bathy_grid import BathyGrid
import numpy as np
from osgeo import gdal
from osgeo import osr
import pytest

gdal.UseExceptions()

ORIGIN_X, ORIGIN_Y, CELL = 500000.0, 4770000.0, 5.0


def _write(path, data, nodata=None):
    driver = gdal.GetDriverByName('GTiff')
    rows, cols = data.shape
    dataset = driver.Create(str(path), cols, rows, 1, gdal.GDT_Float32)
    dataset.SetGeoTransform((ORIGIN_X, CELL, 0.0, ORIGIN_Y, 0.0, -CELL))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32619)
    dataset.SetProjection(srs.ExportToWkt())
    band = dataset.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(nodata)
    band.WriteArray(data.astype(np.float32))
    dataset = None
    return str(path)


def _centre(col, row):
    return ORIGIN_X + (col + 0.5) * CELL, ORIGIN_Y - (row + 0.5) * CELL


@pytest.fixture
def grid(tmp_path):
    data = np.arange(12, dtype=np.float32).reshape(3, 4) + 1.0
    data[1, 2] = -9999.0
    data[2, 3] = np.nan
    return BathyGrid(_write(tmp_path / 'g.tif', data, nodata=-9999.0))


def test_a_valid_cell_reads_back(grid):
    assert grid.getDepth(*_centre(1, 0)) == 2.0
    assert grid.getDepth(*_centre(0, 2)) == 9.0


def test_a_nodata_cell_is_none_not_a_sounding(grid):
    assert grid.getDepth(*_centre(2, 1)) is None


def test_a_nan_cell_is_none(grid):
    assert grid.getDepth(*_centre(3, 2)) is None


def test_outside_the_grid_is_none_on_every_side(grid):
    for col, row in ((-1, 0), (0, -1), (4, 0), (0, 3), (-1, -1)):
        assert grid.getDepth(*_centre(col, row)) is None


def test_just_outside_the_left_and_top_edge_does_not_wrap(grid):
    # int() truncation put x in (-1, 0) cells on column 0 and anything below -1 on the
    # far edge of the array.
    assert grid.getDepth(ORIGIN_X - 0.5 * CELL, ORIGIN_Y - 0.5 * CELL) is None
    assert grid.getDepth(ORIGIN_X - 1.5 * CELL, ORIGIN_Y - 0.5 * CELL) is None
    assert grid.getDepth(ORIGIN_X + 0.5 * CELL, ORIGIN_Y + 1.5 * CELL) is None


def test_a_grid_without_nodata_returns_every_cell(tmp_path):
    data = np.array([[-10.0, 3.0]], dtype=np.float32)
    plain = BathyGrid(_write(tmp_path / 'plain.tif', data))
    assert plain.getDepth(*_centre(0, 0)) == -10.0
    assert plain.getDepth(*_centre(1, 0)) == 3.0


def test_lat_lon_lookup_goes_through_the_grid_crs(tmp_path):
    transform = osr.CoordinateTransformation(_wgs84(), _utm())
    lon, lat = -70.7, 43.07
    x, y, _ = transform.TransformPoint(lon, lat)
    origin_x = math.floor(x / CELL) * CELL - 2 * CELL
    origin_y = math.ceil(y / CELL) * CELL + 2 * CELL
    data = np.full((4, 4), 7.0, dtype=np.float32)
    path = tmp_path / 'll.tif'
    dataset = gdal.GetDriverByName('GTiff').Create(str(path), 4, 4, 1, gdal.GDT_Float32)
    dataset.SetGeoTransform((origin_x, CELL, 0.0, origin_y, 0.0, -CELL))
    dataset.SetProjection(_utm().ExportToWkt())
    dataset.GetRasterBand(1).WriteArray(data)
    dataset = None
    assert BathyGrid(str(path)).getDepthAtLatLon(lat, lon) == 7.0


def _wgs84():
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def _utm():
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32619)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def test_water_depth_adds_the_tide_and_is_none_when_dry(tmp_path):
    data = np.array([[10.0, 1.0, -2.0]], dtype=np.float32)
    plain = BathyGrid(_write(tmp_path / 'w.tif', data))
    assert plain.getWaterDepth(*_centre(0, 0), tide_level=1.5) == 11.5
    assert plain.getWaterDepth(*_centre(1, 0), tide_level=-1.0) is None
    assert plain.getWaterDepth(*_centre(1, 0), tide_level=-0.5) == 0.5
    assert plain.getWaterDepth(*_centre(2, 0), tide_level=1.0) is None
    assert plain.getWaterDepth(*_centre(2, 0), tide_level=3.0) == 1.0
    assert plain.getWaterDepth(ORIGIN_X - 100.0, ORIGIN_Y) is None


def test_a_nodata_value_that_float32_cannot_hold_exactly_still_matches(tmp_path):
    data = np.array([[-99999.9, 4.0]], dtype=np.float32)
    odd = BathyGrid(_write(tmp_path / 'odd.tif', data, nodata=-99999.9))
    assert odd.getDepth(*_centre(0, 0)) is None
    assert odd.getDepth(*_centre(1, 0)) == 4.0


@pytest.mark.parametrize('x, y', [(float('nan'), 1.0), (1.0, float('inf')),
                                  (float('-inf'), float('nan'))])
def test_a_non_finite_position_is_none_not_an_exception(grid, x, y):
    assert grid.getDepth(x, y) is None
