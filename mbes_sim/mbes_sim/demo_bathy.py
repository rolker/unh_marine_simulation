#!/usr/bin/env python3
"""
Build the demo truth bathymetry grid sampled by ``mbes_sim``.

The CCOM GIS "WGOM, LI, SNE Bathymetry and Backscatter Compilation" is a public
ArcGIS image service (2 m and 4 m versions, elevations, EPSG:3857).  This tool
fetches the part of it that covers a latitude/longitude box, in tiles under the
server limits, and turns it into a grid ``BathyGrid`` can read: positive depth,
UTM zone 19N, one band, with the gaps filled from lower precedence sources.

Fill precedence per cell: the 2 m compilation, then the 4 m compilation, then the
16 m regional service (only with ``--regional``), then the packaged chart grid.  The
chart grid has no nodata value (land and drying cells are negative depths), so the
output carries its nodata value (-9999) only outside the chart extent.

The numeric steps are plain functions (tiling, retry, fill, coverage,
provenance) so they can be tested without a network.  See
``marine_simulation/README.md`` for the command that builds the demo grid.
"""

import argparse
import datetime
import hashlib
import http.client
import json
import math
import os
import pathlib
import random
import shutil
import sys
import tempfile
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple
import urllib.error
import urllib.parse
import urllib.request
import uuid

import numpy as np
from osgeo import gdal
from osgeo import osr

gdal.UseExceptions()

SERVICE_ROOT = 'https://gis.ccom.unh.edu/server/rest/services/WGOM-LI-SNE/'
SERVICE_2M = SERVICE_ROOT + 'WGOM_LI_SNE_Bathymetry_2m_WMAS/ImageServer'
SERVICE_4M = SERVICE_ROOT + 'WGOM_LI_SNE_BTY_4m_20230922_WMAS_IS/ImageServer'
SERVICE_16M = SERVICE_ROOT + 'WGOM_LI_SNE_Regional_Bathymetry_16m_WMAS_IS/ImageServer'

ATTRIBUTION = (
    'Bathymetry: WGOM, LI, SNE Bathymetry and Backscatter Compilation, UNH Center for '
    'Coastal and Ocean Mapping / Joint Hydrographic Center, via the CCOM GIS image services '
    'WGOM_LI_SNE_Bathymetry_2m_WMAS (' + SERVICE_2M + ') and WGOM_LI_SNE_BTY_4m_20230922_WMAS_IS '
    '(' + SERVICE_4M + '). The services and their portal items state no licence or copyright '
    'terms (checked 2026-10-14); contributing surveys are named by the WGOM_LI_SNE_Footprints '
    "map service. The 2 m cell size is the product's, not the source surveys' (0.5 to 2 m).")
DATUM_CAVEAT = (
    'The vertical datum of the CCOM compilation is not stated in the service metadata or its '
    'portal item. It is treated as comparable to the chart grid (MLLW) so the simulated tide '
    'applies the same way; the seam statistics report the measured offset between the two '
    'where they overlap. Suitable for the demo; not survey truth until CCOM GIS confirms the '
    'datum.')

OUTPUT_EPSG = 32619
OUTPUT_NODATA = -9999.0
OUTPUT_TILE = 256
USER_AGENT = 'mbes_sim-build_demo_bathy/1 (UNH CCOM; roland@ccom.unh.edu)'

# ArcGIS image service limits (both services report these).
MAX_REQUEST_WIDTH = 15000
MAX_REQUEST_HEIGHT = 4100
DEFAULT_RESOLUTION_M = 2.0
DEFAULT_TILE_PX = 2048
REQUEST_TIMEOUT_S = 60.0
RETRY_ATTEMPTS = 5
RETRY_BASE_DELAY_S = 1.0
# Values beyond this are service nodata (-99999 and 3.4e38), never a sounding.
PLAUSIBLE_ELEVATION_M = 1.0e4
CACHE_MAX_AGE_S = 24 * 3600
# Service pixels fetched beyond the output box so the warp has data at its edges.
MARGIN_PIXELS = 4
# Sanity bounds on what a server may tell us and send us.
MAX_BODY_BYTES = 128 * 1024 * 1024
MAX_SERVICE_STEP_M = 1000.0
MAX_TILES = 2000
MAX_OUTPUT_CELLS = 50_000_000

SOURCE_2M = '2m_compilation'
SOURCE_4M = '4m_compilation'
SOURCE_16M = '16m_regional'
SOURCE_CHART = 'chart_grid'


class DemoBathyError(Exception):
    """A failure the tool reports as one line and a non-zero exit."""


# ----------------------------------------------------------------------------------------
# Geometry and tiling
# ----------------------------------------------------------------------------------------

def _srs(epsg: int) -> osr.SpatialReference:
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def transform_bounds(box: Tuple[float, float, float, float], src_epsg: int, dst_epsg: int,
                     samples: int = 21) -> Tuple[float, float, float, float]:
    """Bounds, in the destination CRS, of a box given in the source CRS (edges densified)."""
    xmin, ymin, xmax, ymax = box
    transform = osr.CoordinateTransformation(_srs(src_epsg), _srs(dst_epsg))
    xs, ys = [], []
    for i in range(samples):
        f = i / (samples - 1)
        for x, y in ((xmin + f * (xmax - xmin), ymin), (xmin + f * (xmax - xmin), ymax),
                     (xmin, ymin + f * (ymax - ymin)), (xmax, ymin + f * (ymax - ymin))):
            px, py, _ = transform.TransformPoint(x, y)
            xs.append(px)
            ys.append(py)
    return min(xs), min(ys), max(xs), max(ys)


def output_grid(bbox_lonlat: Sequence[float], resolution: float) -> Dict:
    """
    Compute the output grid: UTM 19N, edges snapped outward to multiples of the resolution.

    ``bbox_lonlat`` is (west, south, east, north) in degrees.
    """
    west, south, east, north = bbox_lonlat
    if not (west < east and south < north):
        raise DemoBathyError('bbox must be W S E N with W < E and S < N, got %r'
                             % (tuple(bbox_lonlat),))
    if not (-180.0 <= west and east <= 180.0 and -90.0 <= south and north <= 90.0):
        raise DemoBathyError('bbox is not a longitude/latitude box in degrees: %r'
                             % (tuple(bbox_lonlat),))
    if not (resolution > 0 and math.isfinite(resolution)):
        raise DemoBathyError('resolution must be a positive number, got %r' % (resolution,))
    xmin, ymin, xmax, ymax = transform_bounds((west, south, east, north), 4326, OUTPUT_EPSG)
    xmin = math.floor(xmin / resolution + 1e-9) * resolution
    ymin = math.floor(ymin / resolution + 1e-9) * resolution
    xmax = math.ceil(xmax / resolution - 1e-9) * resolution
    ymax = math.ceil(ymax / resolution - 1e-9) * resolution
    return {'epsg': OUTPUT_EPSG, 'resolution': resolution,
            'bounds': (xmin, ymin, xmax, ymax),
            'width': int(round((xmax - xmin) / resolution)),
            'height': int(round((ymax - ymin) / resolution))}


def snap_to_service_grid(box: Tuple[float, float, float, float], origin_x: float,
                         origin_y: float, step: float) -> Tuple[int, int, int, int]:
    """
    Whole service pixels covering a box, as (col0, row0, col1, row1), end exclusive.

    The service grid starts at (origin_x, origin_y) (upper left) and steps ``step``
    metres; row 0 is the top row.
    """
    xmin, ymin, xmax, ymax = box
    col0 = math.floor((xmin - origin_x) / step + 1e-9)
    col1 = math.ceil((xmax - origin_x) / step - 1e-9)
    row0 = math.floor((origin_y - ymax) / step + 1e-9)
    row1 = math.ceil((origin_y - ymin) / step - 1e-9)
    return col0, row0, col1, row1


def plan_tiles(pixels: Tuple[int, int, int, int], tile_px: int
               ) -> List[Tuple[int, int, int, int]]:
    """
    Cut a pixel window into tiles of at most ``tile_px`` on a side.

    Returns (col, row, ncols, nrows) for each tile.  The tiles abut exactly because
    they are cut in whole pixels of the service grid.
    """
    if not 1 <= tile_px <= MAX_REQUEST_HEIGHT:
        raise DemoBathyError('tile size must be 1..%d pixels (server limit is %d x %d), got %r'
                             % (MAX_REQUEST_HEIGHT, MAX_REQUEST_WIDTH, MAX_REQUEST_HEIGHT,
                                tile_px))
    col0, row0, col1, row1 = pixels
    if col1 <= col0 or row1 <= row0:
        raise DemoBathyError('empty pixel window %r' % (pixels,))
    tiles = []
    for row in range(row0, row1, tile_px):
        for col in range(col0, col1, tile_px):
            tiles.append((col, row, min(tile_px, col1 - col), min(tile_px, row1 - row)))
    return tiles


def tile_box(tile: Tuple[int, int, int, int], origin_x: float, origin_y: float, step: float
             ) -> Tuple[float, float, float, float]:
    """(xmin, ymin, xmax, ymax) of a tile in the service CRS."""
    col, row, ncols, nrows = tile
    return (origin_x + col * step, origin_y - (row + nrows) * step,
            origin_x + (col + ncols) * step, origin_y - row * step)


# ----------------------------------------------------------------------------------------
# HTTP with retry
# ----------------------------------------------------------------------------------------

Opener = Callable[[str, float], bytes]


def urllib_opener(url: str, timeout: float) -> bytes:
    """Fetch a URL with the tool's User-Agent; the default ``Opener``."""
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        body = response.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise DemoBathyError('response from %s is larger than %d bytes' % (url, MAX_BODY_BYTES))
    return body


def is_tiff(body: bytes) -> bool:
    """Return True for classic and BigTIFF headers of either byte order."""
    return body[:4] in (b'II*\x00', b'MM\x00*', b'II+\x00', b'MM\x00+')


def fetch_with_retry(url: str, opener: Opener, validate: Callable[[bytes], bool],
                     attempts: int = RETRY_ATTEMPTS, timeout: float = REQUEST_TIMEOUT_S,
                     sleep: Callable[[float], None] = time.sleep,
                     jitter: Callable[[], float] = random.random) -> bytes:
    """
    Fetch ``url`` and return a body that ``validate`` accepts, retrying transient failures.

    Retried: timeouts, connection errors, HTTP 429 and 5xx, and any body that fails
    ``validate`` (ArcGIS answers some errors with HTTP 200 and a JSON body).  Other
    HTTP errors are not retried.  Delays double from ``RETRY_BASE_DELAY_S`` with
    jitter.  Exhausting the attempts raises ``DemoBathyError``.
    """
    last = 'no attempt made'
    for attempt in range(attempts):
        if attempt:
            sleep(RETRY_BASE_DELAY_S * (2 ** (attempt - 1)) * (1.0 + jitter()))
        try:
            body = opener(url, timeout)
        except urllib.error.HTTPError as error:
            if error.code != 429 and error.code < 500:
                raise DemoBathyError('HTTP %d from %s' % (error.code, url)) from error
            last = 'HTTP %d' % error.code
            continue
        except (http.client.HTTPException, OSError) as error:
            last = '%s: %s' % (type(error).__name__, error)
            continue
        if validate(body):
            return body
        last = 'unexpected response body (%d bytes, starts %r)' % (len(body), body[:60])
    raise DemoBathyError('giving up on %s after %d attempts; last failure: %s'
                         % (url, attempts, last))


def _valid_json(body: bytes) -> bool:
    try:
        return 'error' not in json.loads(body.decode('utf-8'))
    except (ValueError, TypeError):
        return False


def service_info(service: str, opener: Opener) -> Dict:
    """Read the facts the tiling needs from the service JSON."""
    body = fetch_with_retry(service + '?f=json', opener, _valid_json)
    info = json.loads(body.decode('utf-8'))
    try:
        extent = info['extent']
        result = {'xmin': float(extent['xmin']), 'ymax': float(extent['ymax']),
                  'xmax': float(extent['xmax']), 'ymin': float(extent['ymin']),
                  'step': float(info['pixelSizeX']), 'nodata': float(info['noDataValue'])}
        step_y = float(info['pixelSizeY'])
        reference = extent['spatialReference']
        wkid = reference.get('latestWkid') or reference['wkid']
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise DemoBathyError('%s: unexpected service description (%s)' % (service, error))
    if wkid not in (3857, 102100, 102113):
        raise DemoBathyError('%s: service CRS %r is not Web Mercator' % (service, wkid))
    values = list(result.values())
    if not all(math.isfinite(v) for v in values + [step_y]):
        raise DemoBathyError('%s: service description holds a non-finite number' % service)
    if not 0 < result['step'] <= MAX_SERVICE_STEP_M or abs(step_y - result['step']) > 1e-9:
        raise DemoBathyError('%s: service pixel size %r x %r is not a square size in (0, %g] m'
                             % (service, result['step'], step_y, MAX_SERVICE_STEP_M))
    if not (result['xmin'] < result['xmax'] and result['ymin'] < result['ymax']):
        raise DemoBathyError('%s: service extent is empty' % service)
    return result


def export_url(service: str, box: Tuple[float, float, float, float], ncols: int, nrows: int
               ) -> str:
    """Build the ``exportImage`` request for one tile."""
    query = urllib.parse.urlencode([
        ('bbox', ','.join('%.8f' % v for v in box)), ('bboxSR', '3857'), ('imageSR', '3857'),
        ('size', '%d,%d' % (ncols, nrows)), ('format', 'tiff'), ('pixelType', 'F32'),
        ('f', 'image')])
    return '%s/exportImage?%s' % (service, query)


def _cache_name(service: str, box: Tuple[float, float, float, float], ncols: int, nrows: int
                ) -> str:
    key = '|'.join([service, ','.join('%.8f' % v for v in box), '%d,%d' % (ncols, nrows),
                    'F32'])
    return 'tile_' + hashlib.sha256(key.encode()).hexdigest()[:20] + '.tif'


def check_tile(path: str, box: Tuple[float, float, float, float], ncols: int, nrows: int,
               step: float) -> None:
    """Fail unless a tile file is the Float32 raster that was requested, readable end to end."""
    try:
        dataset = gdal.Open(path)
        band = dataset.GetRasterBand(1)
        data_type = band.DataType
        band.ReadAsArray()  # a body cut short opens fine and only fails when read
    except RuntimeError as error:
        raise DemoBathyError('tile %s is not a readable raster: %s'
                             % (os.path.basename(path), error)) from error
    gt = dataset.GetGeoTransform()
    tolerance = 1e-6 * step
    expected = (box[0], step, 0.0, box[3], 0.0, -step)
    problems = []
    if (dataset.RasterXSize, dataset.RasterYSize) != (ncols, nrows):
        problems.append('size %dx%d, requested %dx%d'
                        % (dataset.RasterXSize, dataset.RasterYSize, ncols, nrows))
    if any(abs(a - b) > tolerance for a, b in zip(gt, expected)):
        problems.append('geotransform %r, requested %r' % (gt, expected))
    if dataset.RasterCount != 1:
        problems.append('%d bands' % dataset.RasterCount)
    if data_type != gdal.GDT_Float32:
        problems.append('data type %s, requested Float32' % gdal.GetDataTypeName(data_type))
    dataset = None
    if problems:
        raise DemoBathyError('tile %s does not match its request: %s'
                             % (os.path.basename(path), '; '.join(problems)))


def fetch_tiles(service: str, info: Dict, pixels: Tuple[int, int, int, int], tile_px: int,
                work_dir: str, opener: Opener, now: Callable[[], float] = time.time
                ) -> List[Dict]:
    """
    Fetch every tile of a pixel window into ``work_dir`` and return their records.

    A cached tile is reused only when it is under ``CACHE_MAX_AGE_S`` old and passes
    ``check_tile``, so one product never mixes fetch dates.
    """
    records = []
    tiles = plan_tiles(pixels, tile_px)
    if len(tiles) > MAX_TILES:
        raise DemoBathyError('%d tiles requested from %s; check the bbox and --tile-px'
                             % (len(tiles), service))
    for tile in tiles:
        box = tile_box(tile, info['xmin'], info['ymax'], info['step'])
        ncols, nrows = tile[2], tile[3]
        path = os.path.join(work_dir, _cache_name(service, box, ncols, nrows))
        cached = False
        if os.path.isfile(path) and now() - os.path.getmtime(path) < CACHE_MAX_AGE_S:
            try:
                check_tile(path, box, ncols, nrows, info['step'])
                cached = True
            except DemoBathyError:
                cached = False
        if not cached:
            body = fetch_with_retry(export_url(service, box, ncols, nrows), opener, is_tiff)
            handle, partial = tempfile.mkstemp(dir=work_dir, suffix='.partial')
            try:
                with os.fdopen(handle, 'wb') as stream:
                    stream.write(body)
                os.chmod(partial, 0o644)
                check_tile(partial, box, ncols, nrows, info['step'])
                os.replace(partial, path)
            finally:
                if os.path.exists(partial):
                    os.unlink(partial)
        records.append({'file': path, 'box_3857': list(box), 'size_px': [ncols, nrows],
                        'cached': cached})
    return records


# ----------------------------------------------------------------------------------------
# Mosaic, fill, coverage
# ----------------------------------------------------------------------------------------

def warp_to_grid(sources: Sequence[str], grid: Dict, src_nodata: Optional[float],
                 negate: bool) -> np.ndarray:
    """
    Resample rasters onto the output grid; cells with no valid source are NaN.

    Service nodata is excluded from the interpolation (it never mixes into valid cells)
    and anything outside ``PLAUSIBLE_ELEVATION_M`` is also masked, which catches the
    16 m service's 3.4e38 that its exported GeoTIFF does not declare.  With ``negate``
    the values (elevations) become depths.
    """
    vrt_path = '/vsimem/%s.vrt' % uuid.uuid4().hex
    options = {} if src_nodata is None else {'srcNodata': src_nodata}
    vrt = gdal.BuildVRT(vrt_path, list(sources), **options)
    try:
        warp_options = {'format': 'MEM', 'outputBounds': grid['bounds'],
                        'width': grid['width'], 'height': grid['height'],
                        'dstSRS': 'EPSG:%d' % grid['epsg'], 'resampleAlg': 'bilinear',
                        'dstNodata': float('nan'), 'outputType': gdal.GDT_Float32}
        if src_nodata is not None:
            warp_options['srcNodata'] = src_nodata
        warped = gdal.Warp('', vrt, **warp_options)
        array = warped.GetRasterBand(1).ReadAsArray().astype(np.float32)
    finally:
        vrt = None
        gdal.Unlink(vrt_path)
    array[~np.isfinite(array) | (np.abs(array) > PLAUSIBLE_ELEVATION_M)] = np.nan
    return -array if negate else array


def fill_layers(layers: Sequence[Tuple[str, np.ndarray]]
                ) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """
    Combine depth layers, highest precedence first.

    Returns (depth, source index per cell, source names); cells no layer covers are
    NaN with index -1.
    """
    shape = layers[0][1].shape
    depth = np.full(shape, np.nan, dtype=np.float32)
    source = np.full(shape, -1, dtype=np.int8)
    for index, (_, array) in enumerate(layers):
        take = np.isnan(depth) & ~np.isnan(array)
        depth[take] = array[take]
        source[take] = index
    return depth, source, [name for name, _ in layers]


def coverage_summary(depth: np.ndarray, source: np.ndarray, names: Sequence[str]) -> Dict:
    """Cell counts per source, nodata count, depth range and the count of negative cells."""
    total = int(depth.size)
    cells = {name: int(np.count_nonzero(source == i)) for i, name in enumerate(names)}
    nodata = int(np.count_nonzero(source == -1))
    valid = depth[~np.isnan(depth)]
    return {'cells_total': total, 'cells_by_source': cells, 'cells_nodata': nodata,
            'percent_by_source': {n: 100.0 * c / total for n, c in cells.items()},
            'percent_nodata': 100.0 * nodata / total,
            'depth_min': float(valid.min()) if valid.size else None,
            'depth_max': float(valid.max()) if valid.size else None,
            'cells_negative': int(np.count_nonzero(valid < 0))}


def seam_statistics(compilation: np.ndarray, chart: np.ndarray) -> Dict:
    """Compilation depth minus chart depth where both are valid (a datum and vintage hint)."""
    both = ~np.isnan(compilation) & ~np.isnan(chart)
    count = int(np.count_nonzero(both))
    if not count:
        return {'cells': 0, 'median': None, 'p05': None, 'p95': None, 'mean': None}
    diff = (compilation[both] - chart[both]).astype(np.float64)
    p05, median, p95 = np.percentile(diff, [5, 50, 95])
    return {'cells': count, 'median': float(median), 'p05': float(p05), 'p95': float(p95),
            'mean': float(diff.mean())}


def format_summary(coverage: Dict, seam: Dict) -> str:
    """Format the coverage summary the tool prints."""
    lines = ['coverage (%d cells):' % coverage['cells_total']]
    for name, count in coverage['cells_by_source'].items():
        lines.append('  %-16s %10d  %6.2f %%' % (name, count, coverage['percent_by_source'][name]))
    lines.append('  %-16s %10d  %6.2f %%' % ('nodata', coverage['cells_nodata'],
                                             coverage['percent_nodata']))
    lines.append('depth range: %s .. %s m (positive down)'
                 % (_fmt(coverage['depth_min']), _fmt(coverage['depth_max'])))
    lines.append('negative-depth (land or drying) cells: %d' % coverage['cells_negative'])
    if seam['cells']:
        lines.append('compilation minus chart where both exist (%d cells): median %s m, '
                     '5th %s m, 95th %s m, mean %s m'
                     % (seam['cells'], _fmt(seam['median']), _fmt(seam['p05']),
                        _fmt(seam['p95']), _fmt(seam['mean'])))
    else:
        lines.append('compilation minus chart: no overlapping cells')
    return '\n'.join(lines)


def _fmt(value: Optional[float]) -> str:
    return 'n/a' if value is None else '%.2f' % value


# ----------------------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------------------

def sha256_of(path: str) -> str:
    """SHA-256 of a file, hex."""
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def write_grid(path: str, depth: np.ndarray, grid: Dict) -> None:
    """Write the depth array as a tiled LZW Float32 GeoTIFF with the output nodata value."""
    data = np.where(np.isnan(depth), np.float32(OUTPUT_NODATA), depth).astype(np.float32)
    driver = gdal.GetDriverByName('GTiff')
    dataset = driver.Create(
        path, grid['width'], grid['height'], 1, gdal.GDT_Float32,
        options=['TILED=YES', 'BLOCKXSIZE=%d' % OUTPUT_TILE, 'BLOCKYSIZE=%d' % OUTPUT_TILE,
                 'COMPRESS=LZW', 'PREDICTOR=3', 'BIGTIFF=IF_SAFER'])
    xmin, _, _, ymax = grid['bounds']
    res = grid['resolution']
    dataset.SetGeoTransform((xmin, res, 0.0, ymax, 0.0, -res))
    dataset.SetProjection(_srs(grid['epsg']).ExportToWkt())
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(OUTPUT_NODATA)
    band.WriteArray(data)
    band.FlushCache()
    dataset.FlushCache()
    dataset = None


def verify_grid(path: str, depth: np.ndarray, grid: Dict) -> None:
    """Reopen the written file and fail unless it reads back as what was meant to be written."""
    dataset = gdal.Open(path)
    band = dataset.GetRasterBand(1)
    expected = np.where(np.isnan(depth), np.float32(OUTPUT_NODATA), depth).astype(np.float32)
    srs = osr.SpatialReference(wkt=dataset.GetProjection())
    if (srs.GetAuthorityCode(None) != str(grid['epsg']) or band.GetNoDataValue() != OUTPUT_NODATA
            or not np.array_equal(band.ReadAsArray(), expected)):
        raise DemoBathyError('%s does not read back as written' % path)


def build_provenance(*, args: Dict, grid: Dict, services: Dict, tiles: Dict, chart_path: str,
                     output_sha256: str, coverage: Dict, seam: Dict, fetched: str) -> Dict:
    """Assemble the provenance record written next to the grid."""
    return {
        'tool': 'mbes_sim.demo_bathy', 'format_version': 1, 'fetched': fetched,
        'options': args,
        'output_grid': {'epsg': grid['epsg'], 'resolution_m': grid['resolution'],
                        'bounds': list(grid['bounds']), 'width': grid['width'],
                        'height': grid['height'], 'nodata': OUTPUT_NODATA,
                        'values': 'depth, metres, positive down; negative = land or drying'},
        'services': services,
        'tiles': tiles,
        'chart_grid': {'path': chart_path, 'sha256': sha256_of(chart_path)},
        'output_sha256': output_sha256,
        'coverage': coverage, 'compilation_minus_chart': seam,
        'vertical_datum': DATUM_CAVEAT, 'attribution': ATTRIBUTION,
    }


def default_chart_grid() -> str:
    """Return the path of the chart grid shipped with this package."""
    from ament_index_python import get_package_share_directory
    return str(pathlib.Path(get_package_share_directory('mbes_sim')) / 'data' / 'US5NH02M.tiff')


def build(*, bbox: Sequence[float], out: str, resolution: float = DEFAULT_RESOLUTION_M,
          regional: bool = False,
          chart_grid: Optional[str] = None, tile_px: int = DEFAULT_TILE_PX,
          work_dir: Optional[str] = None, force: bool = False, opener: Opener = urllib_opener,
          service_2m: str = SERVICE_2M, service_4m: str = SERVICE_4M,
          service_16m: str = SERVICE_16M,
          log: Callable[[str], None] = print) -> Dict:
    """Fetch, mosaic, fill and write the grid; returns the provenance record."""
    out = os.path.abspath(out)
    provenance_path = out + '.provenance.json'
    if (os.path.exists(out) or os.path.exists(provenance_path)) and not force:
        raise DemoBathyError('%s already exists; use --force to replace it' % out)
    chart_grid = chart_grid or default_chart_grid()
    if not os.path.isfile(chart_grid):
        raise DemoBathyError('chart grid %s is not a file' % chart_grid)
    grid = output_grid(bbox, resolution)
    cells = grid['width'] * grid['height']
    if cells > MAX_OUTPUT_CELLS:
        raise DemoBathyError('%d cells is far more than a demo box; check the bbox' % cells)

    own_work_dir = work_dir is None
    work_dir = work_dir or tempfile.mkdtemp(prefix='build_demo_bathy_')
    try:
        os.makedirs(work_dir, exist_ok=True)
        fetched = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
        wanted = [(SOURCE_2M, service_2m, True), (SOURCE_4M, service_4m, True)]
        if regional:
            wanted.append((SOURCE_16M, service_16m, True))
        need_3857 = transform_bounds(grid['bounds'], OUTPUT_EPSG, 3857)
        layers, services, tiles = [], {}, {}
        for name, service, negate in wanted:
            info = service_info(service, opener)
            margin = MARGIN_PIXELS * info['step']
            box = (need_3857[0] - margin, need_3857[1] - margin,
                   need_3857[2] + margin, need_3857[3] + margin)
            if not (info['xmin'] <= box[0] and box[2] <= info['xmax']
                    and info['ymin'] <= box[1] and box[3] <= info['ymax']):
                raise DemoBathyError('the bbox is not inside the extent of %s' % service)
            pixels = snap_to_service_grid(box, info['xmin'], info['ymax'], info['step'])
            count = len(plan_tiles(pixels, tile_px))
            log('%s: %d tile(s) of up to %d px' % (name, count, tile_px))
            records = fetch_tiles(service, info, pixels, tile_px, work_dir, opener)
            layers.append((name, warp_to_grid([r['file'] for r in records], grid, info['nodata'],
                                              negate)))
            services[name] = {'url': service, 'pixel_size_m': info['step'],
                              'nodata': info['nodata'], 'extent_3857': [
                                  info['xmin'], info['ymin'], info['xmax'], info['ymax']],
                              'values': 'elevation, metres; negated to depth'}
            tiles[name] = [{k: v for k, v in r.items() if k != 'file'} for r in records]
        chart = warp_to_grid([chart_grid], grid, None, negate=False)
        layers.append((SOURCE_CHART, chart))

        depth, source, names = fill_layers(layers)
        coverage = coverage_summary(depth, source, names)
        compilation, _, _ = fill_layers(layers[:2])
        seam = seam_statistics(compilation, chart)

        out_dir = os.path.dirname(out)
        os.makedirs(out_dir, exist_ok=True)
        # Unique names, so two builds into one directory never share a half-written file.
        partials = []
        try:
            for suffix in ('.partial', '.provenance.partial'):
                handle, name = tempfile.mkstemp(dir=out_dir, prefix='.build_demo_bathy_',
                                                suffix=suffix)
                partials.append(name)
                os.close(handle)
                os.chmod(name, 0o644)  # mkstemp makes it 0600; the product is for everyone
            partial, partial_provenance = partials
            write_grid(partial, depth, grid)
            verify_grid(partial, depth, grid)
            provenance = build_provenance(
                args={'bbox': list(bbox), 'resolution': resolution, 'regional': regional,
                      'tile_px': tile_px, 'out': out}, grid=grid, services=services, tiles=tiles,
                chart_path=os.path.abspath(chart_grid), output_sha256=sha256_of(partial),
                coverage=coverage, seam=seam, fetched=fetched)
            with open(partial_provenance, 'w') as handle:
                json.dump(provenance, handle, indent=1)
                handle.write('\n')
            # The grid goes first: provenance records the grid's SHA-256, so a torn pair
            # (killed between the two renames) is detectable by that checksum.
            os.replace(partial, out)
            os.replace(partial_provenance, provenance_path)
        finally:
            for leftover in partials:
                if os.path.exists(leftover):
                    os.unlink(leftover)
    finally:
        if own_work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)
    log(format_summary(coverage, seam))
    log('wrote %s' % out)
    log('wrote %s' % provenance_path)
    return provenance


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Command line."""
    parser = argparse.ArgumentParser(
        prog='build_demo_bathy',
        description='Build the demo truth bathymetry grid for mbes_sim from the CCOM GIS '
                    '2 m and 4 m compilations (negated to depth, UTM 19N, filled from the '
                    'chart grid).')
    parser.add_argument('--bbox', nargs=4, type=float, required=True,
                        metavar=('WEST', 'SOUTH', 'EAST', 'NORTH'),
                        help='longitude/latitude box in degrees')
    parser.add_argument('--out', required=True, help='output GeoTIFF path')
    parser.add_argument('--resolution', type=float, default=DEFAULT_RESOLUTION_M,
                        help='output cell size in metres (default 2)')
    parser.add_argument('--regional', action='store_true',
                        help='also fill from the 16 m regional service before the chart grid')
    parser.add_argument('--chart-grid', default=None,
                        help='fill grid (default: the packaged US5NH02M.tiff)')
    parser.add_argument('--tile-px', type=int, default=DEFAULT_TILE_PX,
                        help='request tile size in pixels, at most %d' % MAX_REQUEST_HEIGHT)
    parser.add_argument('--work-dir', default=None,
                        help='keep fetched tiles here so a rerun resumes (default: a temp dir)')
    parser.add_argument('--force', action='store_true', help='replace an existing output')
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for ``build_demo_bathy``."""
    args = parse_args(argv)
    try:
        build(bbox=args.bbox, out=args.out, resolution=args.resolution, regional=args.regional,
              chart_grid=args.chart_grid, tile_px=args.tile_px, work_dir=args.work_dir,
              force=args.force)
    except DemoBathyError as error:
        print('build_demo_bathy: %s' % error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
