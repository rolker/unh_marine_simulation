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
import pathlib

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


# --- roster ------------------------------------------------------------------------

def test_shipped_roster_loads_with_valid_unique_names(roster):
    names = [b.name for b in roster]
    assert len(names) == len(set(names)) >= 1
    assert [b.index for b in roster] == list(range(len(roster)))


def test_roster_boats_start_in_water_at_distinct_places(roster):
    assert len({(b.lat, b.lon) for b in roster}) == len(roster)


@pytest.mark.parametrize('bad', [
    _boat(name='Bad-Name'),
    _boat(name='asv_sim'),
    _boat(name='1alpha'),
    _boat(color={'red': 1.5, 'green': 0.0, 'blue': 0.0}),
    _boat(color={'red': 1.0, 'green': 0.0}),
    _boat(start={'lat': 95.0, 'lon': -70.7, 'heading': 60.0}),
    _boat(start={'lat': 43.0, 'lon': -70.7}),
])
def test_roster_rejects_a_malformed_boat(tmp_path, bad):
    with pytest.raises(ValueError):
        demo.load_roster(_write_roster(tmp_path, bad))


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
    assignment = demo.assign_joysticks(roster, roster, config, exists=lambda p: True)
    assert [assignment[b.name] for b in roster] == config['devices']


def test_a_subset_keeps_its_boats_own_pad(roster):
    config = _config(roster)
    last = roster[-1]
    assignment = demo.assign_joysticks(roster, [last], config, exists=lambda p: True)
    assert assignment == {last.name: config['devices'][-1]}


def test_wrong_number_of_devices_is_refused(roster):
    devices = _config(roster)['devices'][:-1]
    with pytest.raises(ValueError, match='pair by position'):
        demo.assign_joysticks(roster, roster, {'devices': devices}, exists=lambda p: True)


def test_the_same_device_twice_is_refused(roster):
    devices = _config(roster)['devices']
    devices[-1] = devices[0]
    with pytest.raises(ValueError, match='more than once'):
        demo.assign_joysticks(roster, roster, {'devices': devices}, exists=lambda p: True)


def test_missing_device_names_the_boat_pad_and_path(roster):
    config = _config(roster)
    missing = config['devices'][1]
    with pytest.raises(ValueError) as error:
        demo.assign_joysticks(roster, roster, config, exists=lambda p: p != missing)
    message = str(error.value)
    assert roster[1].name in message and missing in message
    assert roster[0].name not in message


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
