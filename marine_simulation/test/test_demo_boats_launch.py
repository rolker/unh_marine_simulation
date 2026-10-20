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

from launch import LaunchContext, LaunchDescription, LaunchService
from launch.actions import ExecuteProcess, GroupAction, OpaqueFunction
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
PLUG_ORDER_JOYSTICKS = PACKAGE / 'config' / 'demo_joysticks_plug_order.yaml'
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


def _assign(roster, boats, config, exists=lambda p: True, resolve=_js, warn=None):
    return demo.assign_joysticks(roster, boats, config, exists=exists, resolve=resolve,
                                 warn=warn or (lambda message: None))


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


# --- plug-order mode: when_missing: wait ------------------------------------------

def _wait(roster, devices=None):
    config = _config(roster, devices)
    config['when_missing'] = 'wait'
    return config


def test_a_missing_pad_is_kept_and_announced_when_the_file_says_wait(roster):
    config = _wait(roster)
    missing = config['devices'][1]
    notes = []
    assignment = _assign(roster, roster, config, exists=lambda p: p != missing, warn=notes.append)
    assert [assignment[b.name] for b in roster] == config['devices']
    assert len(notes) == 1
    assert roster[1].name in notes[0] and missing in notes[0] and 'not plugged in' in notes[0]
    assert roster[0].name not in notes[0]


def test_no_pad_at_all_still_starts_every_boat_in_wait_mode(roster):
    notes = []
    assignment = _assign(roster, roster, _wait(roster), exists=lambda p: False, warn=notes.append)
    assert set(assignment) == {b.name for b in roster}
    assert len(notes) == len(roster)


def test_wait_mode_says_nothing_when_every_pad_is_there(roster):
    notes = []
    _assign(roster, roster, _wait(roster), warn=notes.append)
    assert notes == []


def test_refuse_is_the_default_and_wait_must_be_spelled_out(roster):
    config = _config(roster)
    missing = config['devices'][1]
    with pytest.raises(ValueError, match='not found'):
        _assign(roster, roster, config, exists=lambda p: p != missing)
    config['when_missing'] = 'refuse'
    with pytest.raises(ValueError, match='not found'):
        _assign(roster, roster, config, exists=lambda p: p != missing)


@pytest.mark.parametrize('policy', ['Wait', 'skip', True, None, 1])
def test_an_unknown_when_missing_value_is_refused_by_name(roster, policy):
    config = _config(roster)
    config['when_missing'] = policy
    with pytest.raises(ValueError, match='when_missing'):
        _assign(roster, roster, config)


def test_wait_mode_still_checks_the_pads_that_are_there(roster):
    config = _wait(roster)
    missing = config['devices'][0]

    def resolve(path):
        return '/dev/input/event5' if path == config['devices'][1] else _js(path)

    with pytest.raises(ValueError, match='-event-joystick') as error:
        _assign(roster, roster, config, exists=lambda p: p != missing, resolve=resolve)
    assert roster[1].name in str(error.value) and roster[0].name not in str(error.value)

    with pytest.raises(ValueError, match='same device'):
        _assign(roster, roster, config, exists=lambda p: p != missing,
                resolve=lambda p: '/dev/input/js0')


def test_wait_mode_refuses_a_missing_event_link_by_its_name(roster):
    config = _wait(roster)
    config['devices'][2] = '/dev/input/by-path/pci-usb-0:3:1.0-event-joystick'
    with pytest.raises(ValueError, match='not plugged in') as error:
        _assign(roster, roster, config, exists=lambda p: False)
    assert roster[2].name in str(error.value)


def test_wait_mode_keeps_the_shape_checks(roster):
    with pytest.raises(ValueError, match='pair by position'):
        _assign(roster, roster, _wait(roster, _config(roster)['devices'][:-1]),
                exists=lambda p: False)
    devices = _config(roster)['devices']
    devices[-1] = devices[0]
    with pytest.raises(ValueError, match='more than once'):
        _assign(roster, roster, _wait(roster, devices), exists=lambda p: False)


def test_the_default_warning_goes_to_stderr_with_the_launch_prefix(roster, capsys):
    config = _wait(roster)
    demo.assign_joysticks(roster, roster[:1], config, exists=lambda p: False, resolve=_js)
    err = capsys.readouterr().err
    assert err.startswith('[demo_boats_launch] ') and roster[0].name in err


def test_the_shipped_plug_order_file_waits_on_js_numbers_in_roster_order(roster):
    config = demo.load_joystick_config(str(PLUG_ORDER_JOYSTICKS))
    assert config['when_missing'] == 'wait'
    assert config['devices'] == ['/dev/input/js%d' % b.index for b in roster]
    # The kernel nodes are their own real path, so the js<N> check passes on them as is.
    notes = []
    assignment = demo.assign_joysticks(roster, roster, config, exists=lambda p: p.endswith('0'),
                                       resolve=lambda p: p, warn=notes.append)
    assert assignment[roster[0].name] == '/dev/input/js0'
    assert len(notes) == len(roster) - 1
    demo.check_joystick_settings(config['deadzone'], config['autorepeat_rate'])
    assert config['deadzone'] == demo.load_joystick_config(str(JOYSTICKS))['deadzone']


# --- nav stack ---------------------------------------------------------------------

def test_enable_nav_is_no_longer_refused_and_defaults_to_off():
    description = demo.generate_launch_description()
    declared = {e.name: e for e in description.entities if hasattr(e, 'default_value')}
    assert 'enable_nav' in declared
    assert not hasattr(demo, 'refuse_enable_nav')
    assert ''.join(t.text for t in declared['enable_nav'].default_value) == 'false'


@pytest.mark.parametrize('value', ['ture', '', 'maybe', '2'])
def test_enable_nav_garbage_is_an_error_not_off(tmp_path, no_host_checks, value):
    with pytest.raises(ValueError, match='enable_nav'):
        demo.launch_setup(_setup_context(tmp_path, enable_nav=value))


@pytest.fixture
def nav_state(tmp_path, monkeypatch):
    """Keep the generated nav2 parameter file out of the real state directory."""
    monkeypatch.setattr(demo.demo_support, 'state_dir', lambda home=None: str(tmp_path / 'state'))
    return tmp_path / 'state' / 'nav'


@pytest.fixture
def included(monkeypatch):
    """Record every ``_include`` of the launch: (package, file, launch arguments)."""
    calls = []

    def record(package, *path, launch_arguments=None):
        calls.append((package, path[-1], dict(launch_arguments or {})))
        return OpaqueFunction(function=lambda context: None)

    monkeypatch.setattr(demo, '_include', record)
    return calls


def test_without_nav_no_boat_gets_mission_manager_or_nav2(tmp_path, no_host_checks, included):
    demo.launch_setup(_setup_context(tmp_path))
    files = [f for _, f, _ in included]
    assert 'mission_manager_launch.py' not in files
    assert 'nav2_bringup_launch.py' not in files


def test_with_nav_every_boat_gets_mission_manager_and_nav2_in_its_own_namespace(
        tmp_path, no_host_checks, nav_state, roster, included):
    actions = demo.launch_setup(_setup_context(tmp_path, enable_nav='true'))
    managers = [(p, a) for p, f, a in included if f == 'mission_manager_launch.py']
    navs = [(p, a) for p, f, a in included if f == 'nav2_bringup_launch.py']
    assert [a['map_frame'] for _, a in managers] == ['%s/map' % b.name for b in roster]
    assert {p for p, _ in managers} == {'mission_manager'}
    assert {p for p, _ in navs} == {'ben_project11'}
    assert [a['namespace'] for _, a in navs] == [b.name for b in roster]
    for _, arguments in navs:
        assert arguments['use_namespace'] == 'true'
        assert arguments['use_composition'] == 'False'
        assert arguments['use_respawn'] == 'False'
        assert arguments['params_file'].startswith(str(nav_state))
    # one top-level group per boat for nav2, after the boats' own groups
    assert sum(isinstance(a, GroupAction) for a in actions) == 2 * len(roster)


def test_nav2_sits_outside_the_boats_namespace_with_a_longer_bond_timeout(included):
    from launch_ros.actions import PushROSNamespace
    group = demo.nav_actions(demo.Boat('a', '', (0, 0, 0), 43.0, -70.0, 0.0, 0), '/p.yaml')
    entities = group.get_sub_entities()
    assert not any(isinstance(e, PushROSNamespace) for e in entities)
    (setting,) = [e for e in entities if isinstance(e, demo.ScopedSetParameter)]
    context = LaunchContext()
    setting.execute(context)
    assert dict(context.launch_configurations['global_params']) == {
        'bond_timeout': demo.demo_nav.BOND_TIMEOUT_S}
    (package, name, arguments), = included
    assert (package, name) == ('ben_project11', 'nav2_bringup_launch.py')
    assert arguments['namespace'] == 'a' and arguments['params_file'] == '/p.yaml'


def test_the_nav2_parameter_file_is_written_with_the_demo_delta(
        tmp_path, no_host_checks, nav_state, included):
    demo.launch_setup(_setup_context(tmp_path, enable_nav='true'))
    written = sorted(nav_state.glob('nav2_params-*.yaml'))
    assert len(written) == 1
    params = yaml.safe_load(written[0].read_text())
    for costmap in ('local_costmap', 'global_costmap'):
        node = params[costmap][costmap]['ros__parameters']
        assert 'chart_layer' not in node['plugins'] and 'chart_layer' not in node
    # the placeholders stay: nav2_bringup_launch.py fills them in per boat
    assert params['bt_task_navigator']['ros__parameters']['global_frame'] == '<tf_prefix>/map'


def test_a_missing_nav_package_is_a_plain_message(
        tmp_path, no_host_checks, nav_state, included, monkeypatch):
    import ament_index_python.packages as packages
    real = packages.get_package_prefix

    def find(package):
        if package == 'mission_manager':
            raise packages.PackageNotFoundError(package)
        return real(package)

    monkeypatch.setattr(packages, 'get_package_prefix', find)
    with pytest.raises(RuntimeError, match='mission_manager package is not installed'):
        demo.launch_setup(_setup_context(tmp_path, enable_nav='true'))


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


# -- the lifecycle guard (issue 96) ----------------------------------------------------------


def _setup_context(tmp_path, **overrides):
    grid = tmp_path / 'grid.tiff'
    grid.write_bytes(b'x')
    values = {
        'boats': '', 'roster_file': str(ROSTER), 'joystick_config': str(JOYSTICKS),
        'enable_joysticks': 'false', 'enable_nav': 'false', 'tide_speed_factor': '10',
        'current_speed': '0.0', 'mbes_grid_file': str(grid), 'cell_size': '1.0',
        'ping_interval': '0.2', 'beam_count': '120', 'lifecycle_guard': 'true',
        'enable_watchdog': 'true', 'idle_timeout': '', 'missing_pad_grace': '',
        'line_spacing': '',
    }
    values.update(overrides)
    context = LaunchContext()
    context.launch_configurations.update(values)
    return context


def _processes(actions):
    return [a for a in actions if type(a) is ExecuteProcess]    # not the Node subclass


@pytest.fixture
def no_host_checks(monkeypatch):
    monkeypatch.setattr(demo, 'check_datum_grids', lambda *a, **k: None)
    monkeypatch.setattr(demo, 'check_mbes_grid', lambda *a, **k: [])    # the grid is a stub
    monkeypatch.setattr(demo, 'get_package_prefix', lambda package: '/opt/' + package)


def test_the_guard_runs_by_default_after_the_boats(tmp_path, no_host_checks):
    actions = demo.launch_setup(_setup_context(tmp_path))
    guards = _processes(actions)
    assert len(guards) == 1 and actions[-1] is guards[0]


def test_the_guard_can_be_turned_off_for_the_launch_manager(tmp_path, no_host_checks):
    actions = demo.launch_setup(_setup_context(tmp_path, lifecycle_guard='false'))
    assert _processes(actions) == []


def test_a_bad_guard_value_is_refused(tmp_path, no_host_checks):
    with pytest.raises(ValueError, match='lifecycle_guard'):
        demo.launch_setup(_setup_context(tmp_path, lifecycle_guard='ture'))


def test_the_guard_waits_for_exactly_the_selected_boats(roster):
    names = [b.name for b in roster][:2]
    command = demo.lifecycle_guard_command(demo.select_boats(roster, ','.join(names)), '/x/guard')
    assert command[:2] == ['/x/guard', 'converge']
    match = command[command.index('--match') + 1]
    assert match == '^/(%s)/' % '|'.join(names)
    assert command[command.index('--expect') + 1] == str(demo.LIFECYCLE_NODES_PER_BOAT * 2)
    assert float(command[command.index('--settle') + 1]) == demo.GUARD_SETTLE_SECONDS
    assert float(command[command.index('--quiet-period') + 1]) == demo.GUARD_QUIET_SECONDS


def test_the_guard_with_nav_expects_mission_manager_and_leaves_nav2_to_nav2(roster):
    boats = demo.select_boats(roster, ','.join(b.name for b in roster[:2]))
    command = demo.lifecycle_guard_command(boats, '/x/guard', True)
    assert command[command.index('--expect') + 1] == str(
        (demo.LIFECYCLE_NODES_PER_BOAT + 1) * 2)
    exclude = command[command.index('--exclude') + 1]
    assert exclude == demo.demo_nav.nav_exclude_regex([b.name for b in boats])
    assert '--exclude' not in demo.lifecycle_guard_command(boats, '/x/guard')


# -- the joystick watchdog --------------------------------------------------------------------

@pytest.fixture
def watchdogs(monkeypatch):
    """Record the watchdog parameters the launch asks for: (boat, index, count, overrides)."""
    calls = []
    real = demo.watchdog_parameters

    def record(boat, index, count, overrides):
        calls.append((boat.name, index, count, dict(overrides)))
        return real(boat, index, count, overrides)

    monkeypatch.setattr(demo, 'watchdog_parameters', record)
    return calls


def test_with_nav_each_boat_gets_a_watchdog_that_knows_its_section(
        tmp_path, no_host_checks, nav_state, included, watchdogs, roster):
    names = [b.name for b in roster][:3]
    demo.launch_setup(_setup_context(tmp_path, enable_nav='true', boats=','.join(names)))
    assert [(n, i, c) for n, i, c, _ in watchdogs] == [(n, i, 3) for i, n in enumerate(names)]


def test_a_subset_of_boats_is_split_among_the_boats_that_run(
        tmp_path, no_host_checks, nav_state, included, watchdogs, roster):
    # the second and fourth boats: sections 0 and 1 of 2, not their roster positions
    names = [roster[1].name, roster[3].name]
    demo.launch_setup(_setup_context(tmp_path, enable_nav='true', boats=','.join(names)))
    assert [(n, i, c) for n, i, c, _ in watchdogs] == [(names[0], 0, 2), (names[1], 1, 2)]


def test_no_watchdog_without_nav_or_when_turned_off(
        tmp_path, no_host_checks, nav_state, included, watchdogs):
    demo.launch_setup(_setup_context(tmp_path))
    demo.launch_setup(_setup_context(tmp_path, enable_nav='true', enable_watchdog='false'))
    assert watchdogs == []


def test_the_timing_arguments_reach_the_watchdog_only_when_given(
        tmp_path, no_host_checks, nav_state, included, watchdogs):
    demo.launch_setup(_setup_context(tmp_path, enable_nav='true'))
    assert set(watchdogs[0][3].values()) == {None}
    watchdogs.clear()
    demo.launch_setup(_setup_context(tmp_path, enable_nav='true', idle_timeout='5',
                                     missing_pad_grace='8', line_spacing='60'))
    assert watchdogs[0][3] == {'idle_timeout': 5.0, 'missing_pad_grace': 8.0,
                               'line_spacing': 60.0}


@pytest.mark.parametrize('name, value', [('idle_timeout', '0'), ('missing_pad_grace', '-1'),
                                         ('line_spacing', 'abc'), ('enable_watchdog', 'ture')])
def test_bad_watchdog_arguments_are_refused(tmp_path, no_host_checks, name, value):
    with pytest.raises(ValueError, match=name):
        demo.launch_setup(_setup_context(tmp_path, **{name: value}))


def test_the_watchdog_parameters_name_the_boat_its_frame_and_its_place(roster):
    boat = roster[2]
    params = demo.watchdog_parameters(boat, 1, 3, {'idle_timeout': 5.0, 'line_spacing': None})
    assert params == {'boat': boat.name, 'map_frame': boat.name + '/map', 'section_index': 1,
                      'section_count': 3, 'idle_timeout': 5.0}


def test_the_demo_values_of_the_watchdog_are_in_the_params_file():
    from marine_simulation import watchdog_core
    params = yaml.safe_load(PARAMS.read_text())['/**/demo_watchdog']['ros__parameters']
    assert params['idle_timeout'] == 30.0 and params['missing_pad_grace'] == 10.0
    known = set(watchdog_core.Params.__dataclass_fields__) | {
        'line_spacing', 'edge_margin', 'min_line_length', 'survey_speed_knots',
        'line_heading_deg'}
    assert set(params) <= known, set(params) - known
    watchdog_core.Params(**{k: v for k, v in params.items()
                            if k in watchdog_core.Params.__dataclass_fields__}).validate()


def test_the_guard_declares_its_launch_argument():
    description = demo.generate_launch_description()
    declared = {e.name: e for e in description.entities if hasattr(e, 'default_value')}
    assert 'lifecycle_guard' in declared


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


# -- launch_setup really runs the grid check -----------------------------------------------------

def test_in_wait_mode_every_boat_gets_a_joy_driver_whether_its_pad_is_there_or_not(
        tmp_path, no_host_checks, monkeypatch, capsys):
    monkeypatch.setattr(demo, 'require_package', lambda *a, **k: None)
    started = []
    real_node = demo.Node

    def recording_node(**kwargs):
        started.append(kwargs)
        return real_node(**kwargs)

    monkeypatch.setattr(demo, 'Node', recording_node)
    devices = [str(tmp_path / ('js%d' % i)) for i in range(4)]
    for device in devices[:2]:                       # two pads plugged in, two not
        pathlib.Path(device).write_bytes(b'')
    config = tmp_path / 'joysticks.yaml'
    config.write_text(yaml.safe_dump({'when_missing': 'wait', 'devices': devices,
                                      'deadzone': 0.1, 'autorepeat_rate': 10.0}))
    demo.launch_setup(_setup_context(tmp_path, enable_joysticks='true',
                                     joystick_config=str(config)))
    joy = [n for n in started if n.get('name') == 'joy_node']
    assert [n['parameters'][0]['dev'] for n in joy] == devices
    err = capsys.readouterr().err
    assert err.count('not plugged in') == 2 and devices[2] in err and devices[3] in err


def test_launch_setup_propagates_a_refused_grid(tmp_path, no_host_checks, monkeypatch):
    def refuse(path, boats):
        raise ValueError('mbes grid is in degrees')
    monkeypatch.setattr(demo, 'check_mbes_grid', refuse)
    with pytest.raises(ValueError, match='in degrees'):
        demo.launch_setup(_setup_context(tmp_path))


def test_launch_setup_prints_the_grid_warnings_to_stderr(tmp_path, no_host_checks,
                                                         monkeypatch, capsys):
    monkeypatch.setattr(demo, 'check_mbes_grid',
                        lambda path, boats: ['WARNING boat dry starts on land'])
    demo.launch_setup(_setup_context(tmp_path))
    assert 'WARNING boat dry starts on land' in capsys.readouterr().err
