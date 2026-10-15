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
Tests for the demo's launch manager configuration and its starter script.

The configuration is written with ``${placeholders}`` filled in from the roster, so these
tests load it the way the script does and check what comes out: the groups and their
dependencies, the lifecycle regular expression, and that every launch file it names exists.
"""

import importlib.util
import pathlib
import re

from ament_index_python.packages import get_package_share_directory, PackageNotFoundError
from launch_manager_proto import config
import pytest
import yaml

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = PACKAGE / 'scripts' / 'demo_manager.py'
CONFIG = PACKAGE / 'config' / 'demo_manager.yaml'
ROSTER = PACKAGE / 'config' / 'demo_roster.yaml'
_spec = importlib.util.spec_from_file_location('demo_manager', SCRIPT)
demo_manager = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo_manager)


def roster_names():
    return [b['name'] for b in yaml.safe_load(ROSTER.read_text())['boats']]


@pytest.fixture
def spec():
    names = roster_names()
    return config.load_config(
        str(CONFIG),
        demo_manager.substitutions(names, '', True, '/tmp/scorer_params.yaml', str(ROSTER)))


def test_the_shipped_configuration_loads_with_the_roster(spec):
    assert spec.name == 'demo_manager' and spec.default_profile == 'demo'
    assert spec.exit_when_all_stopped
    assert set(spec.groups) == {'boats', 'camp', 'scorer'}
    assert spec.profiles['demo'] == ['boats', 'camp', 'scorer']
    assert spec.profiles['headless'] == ['boats', 'scorer']
    assert spec.profiles['boats'] == ['boats']


def test_closing_camp_stops_the_demo_is_expressed_as_follows(spec):
    assert spec.groups['camp'].restart == 'never'
    assert spec.groups['camp'].requires == ['boats']
    assert spec.groups['boats'].follows == ['camp']
    assert spec.groups['scorer'].follows == ['camp']
    assert spec.groups['camp'].follows == []


def test_the_manager_is_the_only_lifecycle_writer(spec):
    # demo_boats_launch.py's own guard must be off when the manager runs it
    assert spec.groups['boats'].arguments['lifecycle_guard'].default is False


def test_boat_lifecycle_regex_matches_exactly_the_roster_boats(spec):
    life = spec.groups['boats'].lifecycle
    names = roster_names()
    regex = re.compile(life.match)
    for name in names:
        assert regex.search('/%s/mbes_sim' % name)
    assert not regex.search('/not_a_boat/mbes_sim')
    assert not regex.search('/%sx/mbes_sim' % names[0])
    assert not regex.search('/coverage_assessment')
    assert life.expect == demo_manager.MIN_LIFECYCLE_NODES_PER_BOAT * len(names)


def test_a_boat_subset_narrows_regex_and_expectation():
    names = roster_names()[:2]
    spec = config.load_config(
        str(CONFIG),
        demo_manager.substitutions(names, ','.join(names), False, '/x.yaml', '/r.yaml'))
    life = spec.groups['boats'].lifecycle
    assert life.expect == demo_manager.MIN_LIFECYCLE_NODES_PER_BOAT * 2
    assert not re.search(life.match, '/%s/mbes_sim' % roster_names()[2])
    boats = spec.groups['boats'].arguments
    assert boats['boats'].default == ','.join(names)
    assert boats['enable_joysticks'].default == 'false'


def test_scorer_is_one_lifecycle_node_at_a_fixed_name(spec):
    scorer = spec.groups['scorer']
    assert scorer.lifecycle.nodes == ['/coverage_assessment']
    params = _scorer_params()
    assert params['ros__parameters']['source_names'] == roster_names()
    assert params['ros__parameters']['grid_topics'] == [
        '/%s/sensors/mbes/grid' % n for n in roster_names()]


def _scorer_params(names=None):
    launch = importlib.util.module_from_spec(importlib.util.spec_from_file_location(
        'boats_for_test', str(PACKAGE / 'launch' / 'demo_boats_launch.py')))
    launch.__spec__.loader.exec_module(launch)
    boats = launch.select_boats(launch.load_roster(str(ROSTER)), ','.join(names or []))
    return demo_manager.scorer_parameters(boats, str(PACKAGE))['/**/coverage_assessment']


def test_scorer_map_frame_is_the_first_boats_map_frame():
    """Boats publish earth -> <boat>/map; a plain 'map' left the scorer never assessing."""
    p = _scorer_params()['ros__parameters']
    first = roster_names()[0]
    assert p['map_frame'] == first + '/map'
    assert p['water_surface_frame'] == first + '/map_tide'
    assert p['water_surface_boat_frame'] == first + '/base_link'


def test_scorer_map_frame_follows_the_selected_boats():
    second = roster_names()[1]
    p = _scorer_params([second])['ros__parameters']
    assert p['map_frame'] == second + '/map'
    assert p['source_names'] == [second]


def test_every_placeholder_in_the_file_is_provided():
    names = demo_manager.substitutions(roster_names(), '', True, '/x', '/r.yaml')
    used = set(re.findall(r'\$\{(\w+)\}', CONFIG.read_text()))
    assert used == set(names), 'placeholders and substitutions disagree'


def test_without_substitutions_the_file_is_refused():
    with pytest.raises(config.ConfigError, match='unknown placeholder'):
        config.load_config(str(CONFIG))


def test_every_launch_file_the_configuration_names_exists(spec):
    missing_packages = []
    for group in spec.groups.values():
        try:
            share = get_package_share_directory(group.package)
        except PackageNotFoundError:
            missing_packages.append(group.package)
            continue
        assert (pathlib.Path(share) / 'launch' / group.file).is_file(), group.name
    if missing_packages:
        pytest.skip('not installed in this environment, so not checked: %s'
                    % ', '.join(missing_packages))


def test_main_refuses_an_unknown_profile_and_an_unknown_boat(capsys):
    assert demo_manager.main(['--profile', 'nope']) == 2
    assert 'unknown profile' in capsys.readouterr().err
    assert demo_manager.main(['--boats', 'ghost']) == 2
    assert 'roster problem' in capsys.readouterr().err


def test_the_per_boat_node_count_agrees_with_the_launch_file():
    launch = demo_manager._load_boats_launch(str(PACKAGE))
    assert demo_manager.MIN_LIFECYCLE_NODES_PER_BOAT == launch.LIFECYCLE_NODES_PER_BOAT


def test_the_chosen_roster_reaches_the_boats_launch(spec):
    assert spec.groups['boats'].arguments['roster_file'].default == str(ROSTER)
    custom = config.load_config(
        str(CONFIG), demo_manager.substitutions(roster_names(), '', True, '/s', '/my/roster.yaml'))
    assert custom.groups['boats'].arguments['roster_file'].default == '/my/roster.yaml'


def test_a_refused_run_leaves_no_temporary_directory_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(demo_manager.tempfile, 'tempdir', str(tmp_path))
    assert demo_manager.main(['--profile', 'nope']) == 2
    assert list(tmp_path.iterdir()) == []


def test_boats_regex_escapes():
    assert demo_manager.boats_regex(['a', 'b.c']) == r'a|b\.c'


def test_script_is_executable_and_installed():
    assert SCRIPT.stat().st_mode & 0o111
    assert 'scripts/demo_manager.py' in (PACKAGE / 'CMakeLists.txt').read_text()
