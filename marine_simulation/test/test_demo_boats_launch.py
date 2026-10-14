# Copyright 2026 Roland Arsenault, UNH CCOM
# All rights reserved.
#
# Software License Agreement (BSD 2-Clause Simplified License)
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""
Unit tests for the fail-fast checks in launch/demo_boats_launch.py.

The launch file is loaded by path (it is not an importable package). The tests
read the boat names from the shipped roster instead of quoting them, so renaming
a boat there does not break anything here.
"""

import importlib.util
import os
import pathlib

from launch import LaunchDescription, LaunchService
from launch.actions import GroupAction, OpaqueFunction
from launch_ros.actions import SetParameter, SetRemap
import numpy as np
from osgeo import gdal
from osgeo import osr
import pytest
import yaml

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
LAUNCH = PACKAGE / 'launch' / 'demo_boats_launch.py'
_spec = importlib.util.spec_from_file_location('demo_boats_launch', LAUNCH)
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)

ROSTER = PACKAGE / 'config' / 'demo_roster.yaml'
JOYSTICKS = PACKAGE / 'config' / 'demo_joysticks.yaml'
PARAMS = PACKAGE / 'config' / 'demo_params.yaml'


def _boat(**overrides):
    entry = {'name': 'alpha', 'pad': 'red', 'color': {'red': 1.0, 'green': 0.0, 'blue': 0.0},
             'start': {'lat': 43.0, 'lon': -70.7, 'heading': 60.0}}
    entry.update(overrides)
    return entry


def _write_roster(tmp_path, *entries):
    path = tmp_path / 'roster.yaml'
    path.write_text(yaml.safe_dump({'boats': list(entries)}))
    return str(path)


@pytest.fixture
def roster():
    return demo.load_roster(str(ROSTER))


def _config(roster, devices=None):
    return {'devices': devices or ['/dev/input/by-path/pad%d-joystick' % b.index
                                   for b in roster]}


def _js(path):
    """Resolve ``padN-joystick`` links to ``/dev/input/jsN`` like udev would."""
    return '/dev/input/js%s' % path.rsplit('/pad', 1)[1].split('-')[0]


def _assign(roster, boats, config, exists=lambda p: True, resolve=_js):
    return demo.assign_joysticks(roster, boats, config, exists=exists, resolve=resolve)


# --- roster ------------------------------------------------------------------------

def test_shipped_roster_loads_with_valid_unique_names(roster):
    names = [b.name for b in roster]
    assert len(names) == len(set(names)) >= 1
    assert [b.index for b in roster] == list(range(len(roster)))


def test_roster_boats_start_at_distinct_places(roster):
    assert len({(b.lat, b.lon) for b in roster}) == len(roster)


@pytest.mark.parametrize('bad', [
    _boat(name='Bad-Name'),
    _boat(name='asv_sim'),
    _boat(name='1alpha'),
    _boat(color={'red': 1.5, 'green': 0.0, 'blue': 0.0}),
    _boat(color={'red': 1.0, 'green': 0.0}),
    _boat(start={'lat': 95.0, 'lon': -70.7, 'heading': 60.0}),
    _boat(start={'lat': 43.0, 'lon': -70.7}),
    _boat(name='alpha\n'),
    _boat(start={'lat': float('nan'), 'lon': -70.7, 'heading': 60.0}),
    _boat(start={'lat': 43.0, 'lon': float('nan'), 'heading': 60.0}),
    _boat(start={'lat': 43.0, 'lon': -70.7, 'heading': float('nan')}),
    _boat(start={'lat': float('inf'), 'lon': -70.7, 'heading': 60.0}),
    _boat(color={'red': float('nan'), 'green': 0.0, 'blue': 0.0}),
], ids=['name-case', 'reserved-name', 'name-digit', 'colour-range', 'colour-missing',
        'lat-range', 'start-missing', 'name-newline', 'lat-nan', 'lon-nan', 'heading-nan',
        'lat-inf', 'colour-nan'])
def test_roster_rejects_a_malformed_boat(tmp_path, bad):
    with pytest.raises(ValueError):
        demo.load_roster(_write_roster(tmp_path, bad))


def test_roster_nan_in_the_yaml_text_is_rejected(tmp_path):
    # The roster file spells it `.nan`; yaml.safe_dump above writes the same.
    path = tmp_path / 'roster.yaml'
    path.write_text(
        'boats:\n  - name: alpha\n    color: {red: 1.0, green: 0.0, blue: 0.0}\n'
        '    start: {lat: .nan, lon: -70.7, heading: 60.0}\n')
    with pytest.raises(ValueError, match='finite'):
        demo.load_roster(str(path))


def test_roster_rejects_duplicate_names(tmp_path):
    with pytest.raises(ValueError, match='duplicate'):
        demo.load_roster(_write_roster(tmp_path, _boat(), _boat()))


# --- selecting boats ---------------------------------------------------------------

def test_empty_selection_is_every_boat_and_a_subset_keeps_roster_positions(roster):
    assert demo.select_boats(roster, '') == roster
    last = roster[-1]
    chosen = demo.select_boats(roster, ' %s ' % last.name)
    assert chosen == [last] and chosen[0].index == len(roster) - 1


def test_unknown_or_repeated_boat_is_refused(roster):
    with pytest.raises(ValueError, match='unknown'):
        demo.select_boats(roster, roster[0].name + ',nosuchboat')
    with pytest.raises(ValueError, match='more than once'):
        demo.select_boats(roster, '%s,%s' % (roster[0].name, roster[0].name))


# --- joysticks ---------------------------------------------------------------------

def test_joysticks_pair_with_the_roster_by_position(roster):
    config = _config(roster)
    assignment = _assign(roster, roster, config)
    assert [assignment[b.name] for b in roster] == config['devices']


def test_a_subset_keeps_its_boats_own_pad(roster):
    config = _config(roster)
    last = roster[-1]
    assignment = _assign(roster, [last], config)
    assert assignment == {last.name: config['devices'][-1]}


def test_wrong_number_of_devices_is_refused(roster):
    devices = _config(roster)['devices'][:-1]
    with pytest.raises(ValueError, match='pair by position'):
        _assign(roster, roster, {'devices': devices})


def test_the_same_device_twice_is_refused(roster):
    devices = _config(roster)['devices']
    devices[-1] = devices[0]
    with pytest.raises(ValueError, match='more than once'):
        _assign(roster, roster, {'devices': devices})


def test_missing_device_names_the_boat_pad_and_path(roster):
    config = _config(roster)
    missing = config['devices'][1]
    with pytest.raises(ValueError) as error:
        _assign(roster, roster, config, exists=lambda p: p != missing)
    message = str(error.value)
    assert roster[1].name in message and missing in message
    assert roster[0].name not in message


def test_an_event_joystick_link_is_refused(roster):
    config = _config(roster)

    def resolve(path):
        return '/dev/input/event5' if path == config['devices'][1] else _js(path)

    with pytest.raises(ValueError, match='-event-joystick') as error:
        _assign(roster, roster, config, resolve=resolve)
    assert roster[1].name in str(error.value) and 'event5' in str(error.value)
    assert roster[0].name not in str(error.value)


def test_two_links_to_one_device_are_refused(roster):
    config = _config(roster)
    with pytest.raises(ValueError, match='same device'):
        _assign(roster, roster, config, resolve=lambda p: '/dev/input/js0')


def test_two_links_to_one_device_only_matter_for_the_boats_launched(roster):
    config = _config(roster)

    def resolve(path):
        return '/dev/input/js9' if path == config['devices'][-1] else _js(path)

    # The last pad shares js9 with nobody; a subset without it is fine either way.
    assert _assign(roster, roster[:1], config, resolve=resolve)


def test_shipped_joystick_config_pairs_with_the_shipped_roster(roster):
    config = demo.load_joystick_config(str(JOYSTICKS))
    assert len(config['devices']) == len(roster)
    assert all(d.endswith('-joystick') and not d.endswith('-event-joystick')
               for d in config['devices'])
    assert 0.0 <= config['deadzone'] < 0.5


# --- nav stack ---------------------------------------------------------------------

@pytest.mark.parametrize('value', ['true', 'True', ' 1 ', 'yes'])
def test_enable_nav_is_refused_with_not_wired_yet(value):
    with pytest.raises(RuntimeError, match='not wired yet'):
        demo.refuse_enable_nav(value)


def test_enable_nav_false_is_accepted():
    demo.refuse_enable_nav('false')


@pytest.mark.parametrize('value', ['ture', '', 'maybe', '2'])
def test_enable_nav_garbage_is_an_error_not_off(value):
    with pytest.raises(ValueError, match='enable_nav'):
        demo.refuse_enable_nav(value)


# --- strict argument parsing -------------------------------------------------------

@pytest.mark.parametrize('text, expected', [
    ('true', True), ('True', True), (' 1 ', True), ('yes', True), ('on', True),
    ('false', False), ('FALSE', False), ('0', False), ('no', False), ('off', False)])
def test_parse_bool_accepts_the_documented_words(text, expected):
    assert demo.parse_bool(text, 'x') is expected


@pytest.mark.parametrize('text', ['ture', '', 'y', 'tru', '2', 'none'])
def test_parse_bool_refuses_anything_else(text):
    with pytest.raises(ValueError, match='enable_joysticks'):
        demo.parse_bool(text, 'enable_joysticks')


@pytest.mark.parametrize('text', ['nan', 'inf', '-inf', 'abc', '', '0', '-1'])
def test_parse_float_positive_refuses_bad_values(text):
    with pytest.raises(ValueError):
        demo.parse_float(text, 'cell_size', positive=True)


def test_parse_float_accepts_a_plain_number_and_checks_the_range():
    assert demo.parse_float('0.2', 'ping_interval', positive=True) == 0.2
    assert demo.parse_float('0', 'current_speed', low=0.0) == 0.0
    with pytest.raises(ValueError):
        demo.parse_float('-0.5', 'current_speed', low=0.0)


def test_tide_speed_factor_zero_is_a_frozen_tide_and_negative_is_refused():
    assert demo.parse_tide_speed_factor('0') == 0.0
    assert demo.parse_tide_speed_factor('10') == 10.0
    for bad in ('-1', 'nan', 'inf', 'fast'):
        with pytest.raises(ValueError, match='tide_speed_factor'):
            demo.parse_tide_speed_factor(bad)


@pytest.mark.parametrize('text', ['0', '-3', '1.5', 'many', ''])
def test_parse_positive_int_refuses_bad_values(text):
    with pytest.raises(ValueError, match='beam_count'):
        demo.parse_positive_int(text, 'beam_count')


def test_parse_positive_int_accepts_a_count():
    assert demo.parse_positive_int('120', 'beam_count') == 120


# --- joystick settings, packages, datum grids ---------------------------------------

@pytest.mark.parametrize('deadzone, rate', [(0.0, 10.0), (0.1, 2.5), (0.99, 50.0)])
def test_joystick_settings_in_range_are_accepted(deadzone, rate):
    demo.check_joystick_settings(deadzone, rate)


@pytest.mark.parametrize('deadzone, rate', [
    (-0.1, 10.0), (1.0, 10.0), (1.5, 10.0), (0.1, 2.0), (0.1, 0.0), (0.1, -5.0)])
def test_joystick_settings_out_of_range_are_refused(deadzone, rate):
    with pytest.raises(ValueError):
        demo.check_joystick_settings(deadzone, rate)


def test_shipped_joystick_settings_pass_the_checks():
    config = demo.load_joystick_config(str(JOYSTICKS))
    demo.check_joystick_settings(config['deadzone'], config['autorepeat_rate'])


def test_a_missing_joy_linux_is_a_plain_message():
    def find(package):
        raise LookupError(package)

    with pytest.raises(RuntimeError, match='joy_linux package is not installed'):
        demo.require_package('joy_linux', 'install it', find=find)
    demo.require_package('joy_linux', 'install it', find=lambda package: '/opt')


def test_datum_grids_present_pass(tmp_path):
    (tmp_path / 'geoid').mkdir()
    (tmp_path / 'geoid' / 'us_noaa_g2018u0.tif').write_text('')
    (tmp_path / 'vdatum').mkdir()
    (tmp_path / 'vdatum' / 'AREA_mllw.gtx').write_text('')
    demo.check_datum_grids(str(tmp_path))


def test_datum_grids_missing_are_named(tmp_path):
    with pytest.raises(RuntimeError) as error:
        demo.check_datum_grids(str(tmp_path))
    assert 'us_noaa_g2018u0.tif' in str(error.value) and '_mllw.gtx' in str(error.value)


def test_datum_grids_with_only_the_geoid_are_refused(tmp_path):
    (tmp_path / 'geoid').mkdir()
    (tmp_path / 'geoid' / 'us_noaa_g2018u0.tif').write_text('')
    (tmp_path / 'vdatum').mkdir()
    (tmp_path / 'vdatum' / 'AREA_mhhw.gtx').write_text('')
    with pytest.raises(RuntimeError, match='_mllw.gtx'):
        demo.check_datum_grids(str(tmp_path))


# --- scoped actions keep group values inside their group ---------------------------

def _probe(seen, key):
    def run(context):
        seen.append((key, list(context.launch_configurations.get('global_params', [])),
                     list(context.launch_configurations.get('ros_remaps', []))))
    return OpaqueFunction(function=run)


def _run(actions):
    service = LaunchService()
    service.include_launch_description(LaunchDescription(actions))
    assert service.run() == 0


def test_scoped_actions_do_not_leak_into_the_next_group():
    seen = []
    # The outer, unscoped actions create the lists the stock classes then extend
    # in place; that is the situation the real launches are in.
    _run([
        SetParameter(name='outer', value=1),
        SetRemap(src='outer_in', dst='outer_out'),
        GroupAction([
            demo.ScopedSetParameter(name='boat', value='first'),
            demo.ScopedSetRemap(src='a', dst='first/a'),
            _probe(seen, 'first'),
        ]),
        GroupAction([_probe(seen, 'second')]),
        _probe(seen, 'outside'),
    ])
    by_key = {key: (params, remaps) for key, params, remaps in seen}
    first_params, first_remaps = by_key['first']
    assert ('boat', 'first') in [(k, v) for k, v in first_params]
    assert ('a', 'first/a') in first_remaps
    for key in ('second', 'outside'):
        params, remaps = by_key[key]
        assert [k for k, _ in params] == ['outer'], key
        assert remaps == [('outer_in', 'outer_out')], key


def test_the_stock_actions_do_leak_which_is_why_the_scoped_ones_exist():
    seen = []
    _run([
        SetParameter(name='outer', value=1),
        SetRemap(src='outer_in', dst='outer_out'),
        GroupAction([
            SetParameter(name='boat', value='first'),
            SetRemap(src='a', dst='first/a'),
        ]),
        _probe(seen, 'after'),
    ])
    _, params, remaps = seen[0]
    # This is a canary, not a regression test. If it fails, launch_ros has started
    # scoping SetParameter / SetRemap inside a GroupAction itself: that is good news.
    # Delete ScopedSetParameter, ScopedSetRemap and test_scoped_actions_do_not_leak_
    # into_the_next_group, use the stock actions in demo_boats_launch.py, and drop the
    # matching pitfall bullet in .agents/README.md.
    fixed = ('launch_ros now scopes SetParameter/SetRemap inside a GroupAction: delete '
             'the Scoped* subclasses and this test (see the comment above)')
    assert 'boat' in [k for k, _ in params], fixed
    assert ('a', 'first/a') in remaps, fixed


# --- names and frames come from the roster -----------------------------------------

def test_asv_sim_parameters_are_derived_from_the_roster(roster):
    params = demo.asv_sim_parameters(roster, 10.0, 0.0)
    assert params['platforms'] == [b.name for b in roster]
    assert params['environment.current.speed'] == 0.0
    for b in roster:
        assert params['platforms.%s.mru_frame' % b.name] == '%s/motion_sensor' % b.name
        assert params['platforms.%s.start_lat' % b.name] == b.lat
        assert params['platforms.%s.model' % b.name] == 'demo'


def test_asv_sim_remappings_are_five_per_boat_and_stay_in_the_boats_namespace(roster):
    remaps = demo.asv_sim_remappings(roster)
    assert len(remaps) == 5 * len(roster)
    for src, dst in remaps:
        assert src.split('/')[0] == dst.split('/')[0]


def test_no_boat_name_is_hard_coded_in_the_launch_or_params(roster):
    text = LAUNCH.read_text() + PARAMS.read_text()
    for b in roster:
        assert b.name not in text


def test_cube_never_reloads_from_disk():
    params = yaml.safe_load(PARAMS.read_text())['/**/cube_bathymetry']['ros__parameters']
    assert params['draft_dir'] == '' and params['prior_store_dir'] == ''
    assert 'bizzyboat' not in LAUNCH.read_text()


# --- mbes grid resolution ---------------------------------------------------------------

def _grids(tmp_path):
    demo_grid, chart, other = (tmp_path / n for n in ('demo.tif', 'chart.tif', 'other.tif'))
    for path in (demo_grid, chart, other):
        path.write_bytes(b'x')
    return str(demo_grid), str(chart), str(other)


def test_an_explicit_grid_argument_wins_over_everything(tmp_path):
    demo_grid, chart, other = _grids(tmp_path)
    path, message = demo.resolve_mbes_grid(other, {'MBES_DEMO_GRID': demo_grid}, demo_grid, chart)
    assert path == other and 'argument' in message


def test_an_explicit_grid_that_is_not_a_file_is_refused(tmp_path):
    demo_grid, chart, _ = _grids(tmp_path)
    with pytest.raises(ValueError, match='is not a file'):
        demo.resolve_mbes_grid(str(tmp_path / 'missing.tif'), {}, demo_grid, chart)


def test_the_environment_grid_is_next_and_must_exist(tmp_path):
    demo_grid, chart, other = _grids(tmp_path)
    path, message = demo.resolve_mbes_grid('', {'MBES_DEMO_GRID': other}, demo_grid, chart)
    assert path == other and 'MBES_DEMO_GRID' in message
    with pytest.raises(ValueError, match='MBES_DEMO_GRID'):
        gone = {'MBES_DEMO_GRID': str(tmp_path / 'gone.tif')}
        demo.resolve_mbes_grid('', gone, demo_grid, chart)


def test_the_demo_grid_is_used_when_it_exists(tmp_path):
    demo_grid, chart, _ = _grids(tmp_path)
    path, message = demo.resolve_mbes_grid('', {}, demo_grid, chart)
    assert path == demo_grid and 'demo truth grid' in message


def test_without_a_demo_grid_the_chart_grid_is_used_and_the_command_is_named(tmp_path):
    _, chart, _ = _grids(tmp_path)
    path, message = demo.resolve_mbes_grid('', {}, str(tmp_path / 'absent.tif'), chart)
    assert path == chart
    assert 'not found' in message and 'falling back' in message
    assert 'build_demo_bathy' in message and str(tmp_path / 'absent.tif') in message


def test_the_shipped_default_is_the_demo_location_and_the_launch_argument_is_empty():
    assert demo.DEMO_GRID == '~/data/sim/mbes_truth/portsmouth_demo_utm19n.tif'
    declared = {a.name: a for a in demo.generate_launch_description().entities
                if hasattr(a, 'name')}
    default = declared['mbes_grid_file'].default_value
    assert default is not None and ''.join(s.text for s in default) == ''


# --- mbes grid sanity ---------------------------------------------------------------------

def _utm_grid(tmp_path, name, epsg=32619, values=None):
    """Write a grid around 43.07 N 70.7 W; the west half is water (5 m), the east half land."""
    gdal.UseExceptions()
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    target = osr.SpatialReference()
    target.ImportFromEPSG(epsg)
    target.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    x, y, _ = osr.CoordinateTransformation(wgs84, target).TransformPoint(-70.7, 43.07)
    if epsg == 4326:
        origin, step = (-70.8, 43.2), 0.001
        ncols, nrows = 200, 260
    else:
        origin, step = (x - 500.0, y + 500.0), 10.0
        ncols, nrows = 100, 100
    data = np.full((nrows, ncols), 5.0, dtype=np.float32)
    data[:, ncols // 2:] = -3.0 if values is None else values
    path = str(tmp_path / name)
    dataset = gdal.GetDriverByName('GTiff').Create(path, ncols, nrows, 1, gdal.GDT_Float32)
    dataset.SetGeoTransform((origin[0], step, 0, origin[1], 0, -step))
    dataset.SetProjection(target.ExportToWkt())
    dataset.GetRasterBand(1).WriteArray(data)
    dataset = None
    return path


def _roster_boat(name, lon):
    return demo.Boat(name=name, pad='red', color=(1.0, 0.0, 0.0), lat=43.07, lon=lon,
                     heading=0.0, index=0)


def test_a_usable_grid_with_boats_on_water_gives_no_warnings(tmp_path):
    path = _utm_grid(tmp_path, 'ok.tif')
    assert demo.check_mbes_grid(path, [_roster_boat('a', -70.7005)]) == []


def test_a_boat_starting_on_land_or_off_the_grid_is_named_in_a_warning(tmp_path):
    path = _utm_grid(tmp_path, 'ok.tif')
    warnings = demo.check_mbes_grid(
        path, [_roster_boat('wet', -70.7005), _roster_boat('dry', -70.6990),
               _roster_boat('lost', -71.5)])
    assert len(warnings) == 2
    assert 'dry' in warnings[0] and 'depth -3.00' in warnings[0]
    assert 'lost' in warnings[1] and 'off the grid' in warnings[1]
    assert all(w.startswith('WARNING') for w in warnings)


def test_a_grid_in_degrees_is_refused(tmp_path):
    path = _utm_grid(tmp_path, 'deg.tif', epsg=4326)
    with pytest.raises(ValueError, match='projected CRS'):
        demo.check_mbes_grid(path, [])


def test_an_unreadable_grid_is_refused_with_its_path(tmp_path):
    bad = tmp_path / 'bad.tif'
    bad.write_bytes(b'not a tiff')
    with pytest.raises(ValueError, match='cannot be read'):
        demo.check_mbes_grid(str(bad), [])


def test_the_shipped_chart_grid_passes_the_check_for_the_roster_boats(roster):
    from ament_index_python.packages import get_package_share_directory
    chart = os.path.join(get_package_share_directory('mbes_sim'), 'data', 'US5NH02M.tiff')
    assert demo.check_mbes_grid(chart, roster) == []
