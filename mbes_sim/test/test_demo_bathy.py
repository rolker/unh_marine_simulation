"""
Tests for mbes_sim.demo_bathy.

Everything runs against a fake ArcGIS image service that answers ``?f=json`` and
``exportImage`` from a function, so no network is needed.  The one network test
skips when the CCOM GIS service is not reachable.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from mbes_sim import demo_bathy as db
import numpy as np
from osgeo import gdal
from osgeo import osr
import pytest

gdal.UseExceptions()

BBOX = (-70.705, 43.070, -70.695, 43.078)
STEP4 = 4.0
STEP16 = 16.0
NODATA4 = -99999.0
NODATA16 = 3.3999999521443642e+38
# Deliberately not round, like the real services' extents.
EXTENT = (-7880000.123, 5320000.456, -7860000.123, 5340000.456)


def _srs(epsg):
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def _to_3857(x, y):
    transform = osr.CoordinateTransformation(_srs(32619), _srs(3857))
    px, py, _ = transform.TransformPoint(x, y)
    return px, py


def _elevation_4m(x, y):
    """East of the cut: 10 m deep (elevation -10). West of it: no data."""
    return np.where(x > X_CUT, -10.0, NODATA4)


def _elevation_16m(x, y):
    """20 m deep everywhere except the south, which is nodata."""
    return np.where(y > Y_CUT, -20.0, NODATA16)


class FakeService:
    """An image service whose pixels come from a function of the 3857 position."""

    def __init__(self, directory, url, step, nodata, elevation, tag_nodata, shift=0.0):
        self.directory, self.url, self.step = directory, url, step
        self.nodata, self.elevation, self.tag_nodata = nodata, elevation, tag_nodata
        self.shift = shift
        self.exports = 0
        self.count = 0

    def info(self):
        xmin, ymin, xmax, ymax = EXTENT
        return {'extent': {'xmin': xmin, 'ymin': ymin, 'xmax': xmax, 'ymax': ymax,
                           'spatialReference': {'latestWkid': 3857, 'wkid': 102100}},
                'pixelSizeX': self.step, 'pixelSizeY': self.step, 'noDataValue': self.nodata}

    def export(self, query):
        self.exports += 1
        x0, y0, x1, y1 = (float(v) for v in query['bbox'][0].split(','))
        ncols, nrows = (int(v) for v in query['size'][0].split(','))
        assert (query['format'][0], query['pixelType'][0]) == ('tiff', 'F32')
        assert query['bboxSR'][0] == query['imageSR'][0] == '3857'
        assert ncols <= db.MAX_REQUEST_WIDTH and nrows <= db.MAX_REQUEST_HEIGHT
        xs = x0 + (np.arange(ncols) + 0.5) * self.step
        ys = y1 - (np.arange(nrows) + 0.5) * self.step
        gx, gy = np.meshgrid(xs, ys)
        path = os.path.join(self.directory, 'fake_%d.tif' % self.exports)
        dataset = gdal.GetDriverByName('GTiff').Create(path, ncols, nrows, 1, gdal.GDT_Float32)
        dataset.SetGeoTransform((x0 + self.shift, self.step, 0, y1, 0, -self.step))
        dataset.SetProjection(_srs(3857).ExportToWkt())
        band = dataset.GetRasterBand(1)
        if self.tag_nodata:
            band.SetNoDataValue(self.nodata)
        band.WriteArray(self.elevation(gx, gy).astype(np.float32))
        dataset = None
        with open(path, 'rb') as handle:
            return handle.read()


class FakeNetwork:
    """An ``Opener`` routing by URL prefix; ``failures`` are raised first, in order."""

    def __init__(self, *services, failures=()):
        self.services = services
        self.failures = list(failures)
        self.urls = []

    def __call__(self, url, timeout):
        self.urls.append(url)
        if self.failures:
            failure = self.failures.pop(0)
            if failure is not None:
                raise failure
        for service in self.services:
            if url.startswith(service.url):
                query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                if query.get('f') == ['json']:
                    return json.dumps(service.info()).encode()
                return service.export(query)
        raise AssertionError('unexpected URL ' + url)


@pytest.fixture
def chart(tmp_path):
    """Build a 5 m UTM chart grid: 5 m deep, missing the west strip, land (-3) in the north."""
    xmin, ymin, xmax, ymax = db.output_grid(BBOX, 4.0)['bounds']
    west_edge = xmin + 0.1 * (xmax - xmin)
    ncols, nrows = int((xmax - west_edge) / 5) + 4, int((ymax - ymin) / 5) + 4
    west_edge = np.floor(west_edge / 5) * 5
    top = np.ceil(ymax / 5) * 5 + 10
    data = np.full((nrows, ncols), 5.0, dtype=np.float32)
    data[: int((top - (ymax - 250.0)) / 5), :] = -3.0
    path = str(tmp_path / 'chart.tif')
    dataset = gdal.GetDriverByName('GTiff').Create(path, ncols, nrows, 1, gdal.GDT_Float32)
    dataset.SetGeoTransform((west_edge, 5.0, 0, top, 0, -5.0))
    dataset.SetProjection(_srs(32619).ExportToWkt())
    dataset.GetRasterBand(1).WriteArray(data)
    dataset = None
    return path


@pytest.fixture(autouse=True)
def _cuts():
    """Put the data boundaries inside the box, as 3857 positions."""
    xmin, ymin, xmax, ymax = db.output_grid(BBOX, 4.0)['bounds']
    global X_CUT, Y_CUT
    X_CUT = _to_3857(xmin + 0.4 * (xmax - xmin), ymin)[0]
    Y_CUT = _to_3857(xmin, ymin + 0.3 * (ymax - ymin))[1]


def _network(tmp_path, **kwargs):
    four = FakeService(str(tmp_path), db.SERVICE_4M, STEP4, NODATA4, _elevation_4m, True,
                       shift=kwargs.pop('shift', 0.0))
    sixteen = FakeService(str(tmp_path), db.SERVICE_16M, STEP16, NODATA16, _elevation_16m,
                          False)
    return FakeNetwork(four, sixteen, **kwargs), four, sixteen


def _cell(path_or_array, grid, fx, fy):
    """Output value at fractional position (fx, fy) of the output box (0,0 = SW corner)."""
    xmin, ymin, xmax, ymax = grid['bounds']
    x, y = xmin + fx * (xmax - xmin), ymin + fy * (ymax - ymin)
    col, row = int((x - xmin) // grid['resolution']), int((ymax - y) // grid['resolution'])
    return path_or_array[row, col]


def _read(path):
    dataset = gdal.Open(path)
    return dataset.GetRasterBand(1).ReadAsArray(), dataset


def _build(tmp_path, chart, network, **kwargs):
    out = str(tmp_path / 'out' / 'demo.tif')
    messages = []
    provenance = db.build(bbox=BBOX, out=out, chart_grid=chart, opener=network,
                          log=messages.append, **kwargs)
    return out, provenance, messages


# --- tiling maths -------------------------------------------------------------------------

def test_snap_covers_the_box_in_whole_service_pixels():
    ox, oy, step = EXTENT[0], EXTENT[3], 4.0
    box = (ox + 10.1, oy - 50.9, ox + 33.0, oy - 20.0)
    col0, row0, col1, row1 = db.snap_to_service_grid(box, ox, oy, step)
    assert (col0, col1, row0, row1) == (2, 9, 5, 13)
    x0, y0, x1, y1 = db.tile_box((col0, row0, col1 - col0, row1 - row0), ox, oy, step)
    assert x0 <= box[0] and x1 >= box[2] and y0 <= box[1] and y1 >= box[3]


def test_snap_keeps_a_box_that_is_already_on_the_grid():
    ox, oy = 100.0, 900.0
    assert db.snap_to_service_grid((108.0, 880.0, 124.0, 892.0), ox, oy, 4.0) == (2, 2, 6, 5)


def test_tiles_abut_exactly_and_cover_the_window():
    window = (3, 7, 3 + 10_000, 7 + 9_001)
    tiles = db.plan_tiles(window, 4_000)
    covered = np.zeros((window[3] - window[1], window[2] - window[0]), dtype=np.uint8)
    for col, row, ncols, nrows in tiles:
        assert ncols <= 4_000 and nrows <= 4_000
        covered[row - window[1]:row - window[1] + nrows,
                col - window[0]:col - window[0] + ncols] += 1
    assert covered.min() == covered.max() == 1
    assert len(tiles) == 3 * 3


def test_tile_edge_cases_one_pixel_and_exact_multiple():
    assert db.plan_tiles((0, 0, 1, 1), 2048) == [(0, 0, 1, 1)]
    assert db.plan_tiles((0, 0, 4096, 2048), 2048) == [(0, 0, 2048, 2048), (2048, 0, 2048, 2048)]
    assert db.plan_tiles((5, 5, 8, 7), 2) == [(5, 5, 2, 2), (7, 5, 1, 2)]


@pytest.mark.parametrize('tile_px', [0, -1, db.MAX_REQUEST_HEIGHT + 1, 15000])
def test_tile_size_over_the_server_limit_is_refused(tile_px):
    with pytest.raises(db.DemoBathyError):
        db.plan_tiles((0, 0, 100, 100), tile_px)


def test_an_empty_window_is_refused():
    with pytest.raises(db.DemoBathyError):
        db.plan_tiles((4, 4, 4, 9), 100)


def test_tile_boxes_of_neighbours_share_an_edge_exactly():
    ox, oy, step = EXTENT[0], EXTENT[3], 4.0
    left = db.tile_box((0, 0, 2048, 2048), ox, oy, step)
    right = db.tile_box((2048, 0, 100, 2048), ox, oy, step)
    below = db.tile_box((0, 2048, 2048, 10), ox, oy, step)
    assert left[2] == right[0]
    assert left[1] == below[3]


def test_output_grid_snaps_outward_to_the_resolution():
    grid = db.output_grid(BBOX, 4.0)
    xmin, ymin, xmax, ymax = grid['bounds']
    assert all(v % 4.0 == 0 for v in grid['bounds'])
    assert grid['epsg'] == 32619
    assert grid['width'] == (xmax - xmin) / 4 and grid['height'] == (ymax - ymin) / 4
    corner = osr.CoordinateTransformation(_srs(4326), _srs(32619)).TransformPoint(-70.705, 43.07)
    assert xmin <= corner[0] and ymin <= corner[1]


@pytest.mark.parametrize('bbox', [(1, 2, 1, 3), (5, 2, 1, 3), (1, 5, 2, 3), (-200, 0, 1, 1)])
def test_a_bad_bbox_is_refused(bbox):
    with pytest.raises(db.DemoBathyError):
        db.output_grid(bbox, 4.0)


@pytest.mark.parametrize('resolution', [0, -4, float('nan'), float('inf')])
def test_a_bad_resolution_is_refused(resolution):
    with pytest.raises(db.DemoBathyError):
        db.output_grid(BBOX, resolution)


# --- retry ----------------------------------------------------------------------------------

def _http_error(code):
    return urllib.error.HTTPError('http://x', code, 'err', {}, None)


def _fetch(failures, bodies=(b'II*\x00ok',), attempts=5):
    calls, sleeps = [], []
    queue = list(failures)

    def opener(url, timeout):
        calls.append(url)
        if queue:
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return bodies[0]

    result = db.fetch_with_retry('http://x/a', opener, db.is_tiff, attempts=attempts,
                                 sleep=sleeps.append, jitter=lambda: 0.0)
    return result, calls, sleeps


def test_success_after_a_429_and_a_503_with_doubling_delays():
    body, calls, sleeps = _fetch([_http_error(429), _http_error(503)])
    assert body.startswith(b'II*') and len(calls) == 3
    assert sleeps == [1.0, 2.0]


def test_timeouts_and_connection_errors_are_retried():
    _, calls, _ = _fetch([TimeoutError('slow'), urllib.error.URLError('down'),
                          ConnectionResetError('reset')])
    assert len(calls) == 4


def test_http_200_with_a_json_error_body_is_retried():
    body, calls, _ = _fetch([b'{"error": {"code": 400}}'])
    assert db.is_tiff(body) and len(calls) == 2


def test_exhausted_attempts_fail_naming_the_last_failure():
    with pytest.raises(db.DemoBathyError, match='5 attempts.*HTTP 503'):
        _fetch([_http_error(503)] * 5)


def test_other_http_errors_are_not_retried():
    with pytest.raises(db.DemoBathyError, match='HTTP 404'):
        _fetch([_http_error(404)])


# --- fill, coverage -----------------------------------------------------------------------

def test_fill_precedence_is_first_layer_first_and_uncovered_stays_nan():
    nan = np.nan
    first = np.array([[1, nan, nan, nan]], dtype=np.float32)
    second = np.array([[2, 2, nan, nan]], dtype=np.float32)
    third = np.array([[3, 3, 3, nan]], dtype=np.float32)
    depth, source, names = db.fill_layers([('a', first), ('b', second), ('c', third)])
    assert depth[0, :3].tolist() == [1, 2, 3] and np.isnan(depth[0, 3])
    assert source.tolist() == [[0, 1, 2, -1]]
    assert names == ['a', 'b', 'c']


def test_a_valid_negative_depth_is_not_treated_as_missing():
    first = np.array([[np.nan, -2.0]], dtype=np.float32)
    second = np.array([[-5.0, 9.0]], dtype=np.float32)
    depth, _, _ = db.fill_layers([('a', first), ('b', second)])
    assert depth.tolist() == [[-5.0, -2.0]]


def test_coverage_counts_percentages_range_and_negative_cells():
    depth = np.array([[10, -2, np.nan, 4]], dtype=np.float32)
    source = np.array([[0, 1, -1, 1]], dtype=np.int8)
    summary = db.coverage_summary(depth, source, ['a', 'b'])
    assert summary['cells_by_source'] == {'a': 1, 'b': 2}
    assert summary['cells_nodata'] == 1 and summary['percent_nodata'] == 25.0
    assert (summary['depth_min'], summary['depth_max'], summary['cells_negative']) == (-2, 10, 1)


def test_seam_statistics_use_only_cells_valid_in_both():
    comp = np.array([[10, 11, np.nan, 13]], dtype=np.float32)
    chart = np.array([[9, 9, 9, np.nan]], dtype=np.float32)
    seam = db.seam_statistics(comp, chart)
    assert seam['cells'] == 2 and seam['median'] == 1.5 and seam['mean'] == 1.5
    assert db.seam_statistics(comp, np.full_like(comp, np.nan))['cells'] == 0


# --- warp -----------------------------------------------------------------------------------

def _tile_file(path, elevation, nodata, tag):
    xmin, ymin, xmax, ymax = db.output_grid(BBOX, 4.0)['bounds']
    box = db.transform_bounds((xmin - 100, ymin - 100, xmax + 100, ymax + 100), 32619, 3857)
    ncols, nrows = int((box[2] - box[0]) / 4) + 1, int((box[3] - box[1]) / 4) + 1
    xs = box[0] + (np.arange(ncols) + 0.5) * 4
    ys = box[3] - (np.arange(nrows) + 0.5) * 4
    gx, gy = np.meshgrid(xs, ys)
    dataset = gdal.GetDriverByName('GTiff').Create(str(path), ncols, nrows, 1, gdal.GDT_Float32)
    dataset.SetGeoTransform((box[0], 4.0, 0, box[3], 0, -4.0))
    dataset.SetProjection(_srs(3857).ExportToWkt())
    band = dataset.GetRasterBand(1)
    if tag:
        band.SetNoDataValue(nodata)
    band.WriteArray(elevation(gx, gy).astype(np.float32))
    dataset = None
    return str(path)


def test_warp_negates_elevation_to_depth_and_masks_nodata(tmp_path):
    grid = db.output_grid(BBOX, 4.0)
    tile = _tile_file(tmp_path / 't.tif', _elevation_4m, NODATA4, True)
    depth = db.warp_to_grid([tile], grid, NODATA4, negate=True)
    assert _cell(depth, grid, 0.9, 0.5) == pytest.approx(10.0)
    assert np.isnan(_cell(depth, grid, 0.1, 0.5))


def test_service_nodata_never_bleeds_into_valid_cells(tmp_path):
    grid = db.output_grid(BBOX, 4.0)
    tile = _tile_file(tmp_path / 't.tif', _elevation_4m, NODATA4, True)
    depth = db.warp_to_grid([tile], grid, NODATA4, negate=True)
    valid = depth[~np.isnan(depth)]
    assert valid.size and np.all(np.abs(valid - 10.0) < 1e-4)


def test_an_undeclared_nodata_value_is_masked_by_value(tmp_path):
    grid = db.output_grid(BBOX, 4.0)
    tile = _tile_file(tmp_path / 't.tif', _elevation_16m, NODATA16, False)
    depth = db.warp_to_grid([tile], grid, NODATA16, negate=True)
    assert _cell(depth, grid, 0.5, 0.9) == pytest.approx(20.0)
    assert np.isnan(_cell(depth, grid, 0.5, 0.05))
    assert np.nanmax(np.abs(depth)) < 100


# --- writing ----------------------------------------------------------------------------------

def test_written_grid_is_tiled_lzw_utm_float32_with_nodata(tmp_path):
    grid = db.output_grid(BBOX, 4.0)
    depth = np.full((grid['height'], grid['width']), 12.5, dtype=np.float32)
    depth[0, 0] = np.nan
    path = str(tmp_path / 'g.tif')
    db.write_grid(path, depth, grid)
    db.verify_grid(path, depth, grid)
    dataset = gdal.Open(path)
    band = dataset.GetRasterBand(1)
    assert gdal.GetDataTypeName(band.DataType) == 'Float32'
    assert band.GetNoDataValue() == -9999.0
    assert dataset.GetMetadata('IMAGE_STRUCTURE')['COMPRESSION'] == 'LZW'
    assert band.GetBlockSize() == [256, 256]
    assert dataset.GetGeoTransform() == (grid['bounds'][0], 4.0, 0.0, grid['bounds'][3], 0.0, -4.0)
    assert osr.SpatialReference(wkt=dataset.GetProjection()).GetAuthorityCode(None) == '32619'
    assert band.ReadAsArray()[0, 0] == -9999.0


# --- end to end against the fake service -------------------------------------------------

def test_build_fills_in_precedence_order_and_keeps_land(tmp_path, chart):
    network, four, sixteen = _network(tmp_path)
    out, provenance, messages = _build(tmp_path, chart, network)
    array, dataset = _read(out)
    grid = db.output_grid(BBOX, 4.0)
    assert dataset.RasterXSize == grid['width'] and dataset.RasterYSize == grid['height']
    assert osr.SpatialReference(wkt=dataset.GetProjection()).GetAuthorityCode(None) == '32619'
    # East: the compilation (elevation -10 becomes depth 10), whatever else says.
    assert _cell(array, grid, 0.85, 0.5) == pytest.approx(10.0, abs=1e-3)
    # West, south of the land strip: the chart (regional is off).
    assert _cell(array, grid, 0.25, 0.3) == pytest.approx(5.0, abs=1e-3)
    # West, north: the chart's land stays a negative depth, not nodata.
    assert _cell(array, grid, 0.25, 0.97) == pytest.approx(-3.0, abs=1e-3)
    # West of the chart's edge and without compilation: nodata.
    assert _cell(array, grid, 0.02, 0.5) == -9999.0
    assert sixteen.exports == 0
    assert '16m_regional' not in provenance['coverage']['cells_by_source']
    assert provenance['coverage']['cells_nodata'] == np.count_nonzero(array == -9999.0)
    assert any('coverage' in m for m in messages)


def test_regional_fills_between_the_compilation_and_the_chart(tmp_path, chart):
    network, _, sixteen = _network(tmp_path)
    out, provenance, _ = _build(tmp_path, chart, network, regional=True)
    array, _ = _read(out)
    grid = db.output_grid(BBOX, 4.0)
    assert sixteen.exports >= 1
    assert _cell(array, grid, 0.85, 0.5) == pytest.approx(10.0, abs=1e-3)
    # West, north of the 16 m nodata strip: 16 m beats the chart.
    assert _cell(array, grid, 0.25, 0.6) == pytest.approx(20.0, abs=1e-3)
    # West, in the 16 m nodata strip: the chart.
    assert _cell(array, grid, 0.25, 0.1) == pytest.approx(5.0, abs=1e-3)
    assert provenance['coverage']['cells_by_source']['16m_regional'] > 0


def test_provenance_records_requests_services_and_checksums(tmp_path, chart):
    network, _, _ = _network(tmp_path)
    out, provenance, _ = _build(tmp_path, chart, network, tile_px=300)
    on_disk = json.load(open(out + '.provenance.json'))
    assert on_disk == json.loads(json.dumps(provenance))
    assert on_disk['output_sha256'] == db.sha256_of(out)
    assert on_disk['chart_grid']['sha256'] == db.sha256_of(chart)
    assert on_disk['services']['4m_compilation']['url'] == db.SERVICE_4M
    assert on_disk['services']['4m_compilation']['nodata'] == NODATA4
    tiles = on_disk['tiles']['4m_compilation']
    assert len(tiles) > 1 and all(len(t['box_3857']) == 4 for t in tiles)
    assert on_disk['fetched'].endswith('+00:00')
    assert 'not stated' in on_disk['vertical_datum'] and 'WGOM' in on_disk['attribution']
    assert on_disk['compilation_minus_chart']['cells'] > 0
    assert on_disk['output_grid']['nodata'] == -9999.0


def test_every_request_stays_inside_the_server_limits(tmp_path, chart):
    network, _, _ = _network(tmp_path)
    _build(tmp_path, chart, network, tile_px=100)
    exports = [u for u in network.urls if 'exportImage' in u]
    assert len(exports) > 4
    for url in exports:
        ncols, nrows = (int(v) for v in urllib.parse.parse_qs(
            urllib.parse.urlparse(url).query)['size'][0].split(','))
        assert ncols <= 100 and nrows <= 100


def test_a_transient_failure_during_the_build_is_retried(tmp_path, chart, monkeypatch):
    monkeypatch.setattr(db.time, 'sleep', lambda _: None)
    network, _, _ = _network(tmp_path, failures=[None, _http_error(503), TimeoutError('slow')])
    out, _, _ = _build(tmp_path, chart, network)
    assert os.path.isfile(out)


def test_a_tile_whose_geotransform_is_not_what_was_asked_fails_the_run(tmp_path, chart):
    network, _, _ = _network(tmp_path, shift=2.0)
    out = str(tmp_path / 'out' / 'demo.tif')
    with pytest.raises(db.DemoBathyError, match='does not match its request'):
        db.build(bbox=BBOX, out=out, chart_grid=chart, opener=network, log=lambda m: None)
    assert not os.path.exists(out) and not os.path.exists(out + '.provenance.json')


def test_a_failed_run_leaves_no_partial_output(tmp_path, chart, monkeypatch):
    monkeypatch.setattr(db.time, 'sleep', lambda _: None)
    network, _, _ = _network(tmp_path, failures=[None] + [_http_error(503)] * 5)
    out = str(tmp_path / 'out' / 'demo.tif')
    with pytest.raises(db.DemoBathyError, match='giving up'):
        db.build(bbox=BBOX, out=out, chart_grid=chart, opener=network, log=lambda m: None)
    assert not os.path.exists(out) and not os.path.exists(out + '.partial')


def test_a_grid_that_does_not_read_back_leaves_nothing_behind(tmp_path, chart, monkeypatch):
    def broken(path, depth, grid):
        raise db.DemoBathyError('does not read back as written')

    monkeypatch.setattr(db, 'verify_grid', broken)
    network, _, _ = _network(tmp_path)
    out = str(tmp_path / 'out' / 'demo.tif')
    with pytest.raises(db.DemoBathyError, match='read back'):
        db.build(bbox=BBOX, out=out, chart_grid=chart, opener=network, log=lambda m: None)
    assert os.listdir(tmp_path / 'out') == []


def test_an_existing_output_needs_force(tmp_path, chart):
    network, _, _ = _network(tmp_path)
    out, _, _ = _build(tmp_path, chart, network)
    before = db.sha256_of(out)
    with pytest.raises(db.DemoBathyError, match='--force'):
        _build(tmp_path, chart, network)
    assert db.sha256_of(out) == before
    _build(tmp_path, chart, network, force=True)
    assert db.sha256_of(out) == before


def test_a_rerun_with_a_work_dir_reuses_cached_tiles(tmp_path, chart):
    network, four, _ = _network(tmp_path)
    work = str(tmp_path / 'work')
    _build(tmp_path, chart, network, work_dir=work)
    first = four.exports
    _build(tmp_path, chart, network, work_dir=work, force=True)
    assert first >= 1 and four.exports == first


def test_a_stale_cached_tile_is_fetched_again(tmp_path, chart):
    network, four, _ = _network(tmp_path)
    work = str(tmp_path / 'work')
    _build(tmp_path, chart, network, work_dir=work)
    first = four.exports
    old = db.time.time() - db.CACHE_MAX_AGE_S - 60
    for name in os.listdir(work):
        os.utime(os.path.join(work, name), (old, old))
    _build(tmp_path, chart, network, work_dir=work, force=True)
    assert four.exports == 2 * first


def test_a_box_outside_the_service_extent_is_refused(tmp_path, chart):
    network, _, _ = _network(tmp_path)
    with pytest.raises(db.DemoBathyError, match='not inside the extent'):
        db.build(bbox=(-60.0, 43.0, -59.99, 43.01), out=str(tmp_path / 'o.tif'),
                 chart_grid=chart, opener=network, log=lambda m: None)


def test_a_missing_chart_grid_is_named(tmp_path):
    network, _, _ = _network(tmp_path)
    with pytest.raises(db.DemoBathyError, match='chart grid'):
        db.build(bbox=BBOX, out=str(tmp_path / 'o.tif'), chart_grid=str(tmp_path / 'none.tif'),
                 opener=network, log=lambda m: None)


def test_main_reports_a_failure_as_one_line_and_exit_one(tmp_path, capsys):
    existing = tmp_path / 'there.tif'
    existing.write_bytes(b'x')
    code = db.main(['--bbox'] + [str(v) for v in BBOX] + ['--out', str(existing)])
    assert code == 1
    assert 'already exists' in capsys.readouterr().err


def test_the_packaged_chart_grid_path_exists():
    assert os.path.isfile(db.default_chart_grid())


# --- network ------------------------------------------------------------------------------------

def _service_reachable():
    try:
        urllib.request.urlopen(db.SERVICE_4M + '?f=json', timeout=5).read(10)
        return True
    except Exception:  # noqa: BLE001 - any failure means "skip"
        return False


@pytest.mark.skipif(not _service_reachable(), reason='CCOM GIS service not reachable')
def test_one_real_tile_matches_its_request_and_warps(tmp_path):
    info = db.service_info(db.SERVICE_4M, db.urllib_opener)
    assert info['step'] == 4.0 and info['nodata'] == NODATA4
    # A 200 x 200 pixel window in the Portsmouth demo area.
    x, y = _to_3857_from_lonlat(-70.705, 43.0737)
    pixels = db.snap_to_service_grid((x, y - 800, x + 800, y), info['xmin'], info['ymax'], 4.0)
    records = db.fetch_tiles(db.SERVICE_4M, info, pixels, 200, str(tmp_path), db.urllib_opener)
    dataset = gdal.Open(records[0]['file'])
    values = dataset.GetRasterBand(1).ReadAsArray()
    assert np.count_nonzero(values != NODATA4) > 0
    grid = db.output_grid((-70.7045, 43.0735, -70.7035, 43.0745), 4.0)
    depth = db.warp_to_grid([r['file'] for r in records], grid, NODATA4, negate=True)
    assert np.isfinite(depth).any() and np.nanmax(depth) < 100


def _to_3857_from_lonlat(lon, lat):
    transform = osr.CoordinateTransformation(_srs(4326), _srs(3857))
    x, y, _ = transform.TransformPoint(lon, lat)
    return x, y
