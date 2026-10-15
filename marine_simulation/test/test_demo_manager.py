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
from marine_simulation import demo_support
from marine_simulation import roster
import pytest
import yaml

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = PACKAGE / 'scripts' / 'demo_manager.py'
CONFIG = PACKAGE / 'config' / 'demo_manager.yaml'
ROSTER = PACKAGE / 'config' / 'demo_roster.yaml'
_spec = importlib.util.spec_from_file_location('demo_manager', SCRIPT)
demo_manager = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo_manager)


def _substitutions(names, boats_argument, joysticks, scorer, roster_file,
                   joystick_config='/j.yaml', layout='/l.yaml', target='/t.json'):
    return demo_manager.substitutions(names, boats_argument, joysticks, scorer, roster_file,
                                      joystick_config, layout, target)


def roster_names():
    return [b['name'] for b in yaml.safe_load(ROSTER.read_text())['boats']]


@pytest.fixture
def spec():
    names = roster_names()
    return config.load_config(
        str(CONFIG),
        _substitutions(names, '', True, '/tmp/scorer_params.yaml', str(ROSTER)))


def test_the_shipped_configuration_loads_with_the_roster(spec):
    assert spec.name == 'demo_manager' and spec.default_profile == 'demo'
    assert spec.exit_when_all_stopped
    assert set(spec.groups) == {'boats', 'camp', 'scorer', 'target_area', 'layout'}
    assert spec.profiles['demo'] == ['boats', 'camp', 'scorer', 'target_area', 'layout']
    assert spec.profiles['headless'] == ['boats', 'scorer', 'target_area']
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
        _substitutions(names, ','.join(names), False, '/x.yaml', '/r.yaml'))
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
    boats = roster.select_boats(roster.load_roster(str(ROSTER)), ','.join(names or []))
    return demo_manager.scorer_parameters(boats)['/**/coverage_assessment']


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
    names = _substitutions(roster_names(), '', True, '/x', '/r.yaml')
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
    spec = importlib.util.spec_from_file_location(
        'boats_for_test', str(PACKAGE / 'launch' / 'demo_boats_launch.py'))
    launch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launch)
    assert demo_manager.MIN_LIFECYCLE_NODES_PER_BOAT == launch.LIFECYCLE_NODES_PER_BOAT


def test_the_chosen_roster_reaches_the_boats_launch(spec):
    assert spec.groups['boats'].arguments['roster_file'].default == str(ROSTER)
    custom = config.load_config(
        str(CONFIG), _substitutions(roster_names(), '', True, '/s', '/my/roster.yaml'))
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


# -- the manager's CAMP starts on the demo's own settings and tile cache ----------------------

def _camp_launch_module():
    path = PACKAGE / 'launch' / 'demo_camp_launch.py'
    spec = importlib.util.spec_from_file_location('demo_camp_launch', str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _camp_start(monkeypatch, tmp_path, **arguments):
    from launch import LaunchContext
    module = _camp_launch_module()
    demo = demo_support
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setattr(demo, 'running_camp_pids', lambda *a, **k: [])
    started = []
    monkeypatch.setattr(demo, 'camp_node',
                        lambda settings_home, project_file='': started.append(
                            (settings_home, project_file)) or 'camp-node')
    demo.release_demo_locks()
    context = LaunchContext()
    values = {'boats': '', 'roster_file': str(ROSTER),
              'camp_profile': str(PACKAGE / 'config' / 'demo_camp_profile.conf'),
              'camp_view_config': str(PACKAGE / 'config' / 'demo_camp_view.yaml'),
              'target_area_file': ''}
    values.update(arguments)
    context.launch_configurations.update(values)
    try:
        actions = module.launch_setup(context)
    finally:
        demo.release_demo_locks()
    return demo, actions, started


def test_the_camp_group_runs_the_demo_camp_launch(spec):
    camp = spec.groups['camp']
    assert (camp.package, camp.file) == ('marine_simulation', 'demo_camp_launch.py')
    assert camp.arguments['roster_file'].default == str(ROSTER)


def test_manager_camp_gets_the_private_settings_directory(monkeypatch, tmp_path):
    demo, actions, started = _camp_start(monkeypatch, tmp_path)
    assert started == [(demo.settings_root(str(tmp_path)), '')]
    assert actions[-1] == 'camp-node'
    conf = pathlib.Path(demo.settings_root(str(tmp_path)), 'UNH-CCOMJHC',
                        'CCOMAutonomousMissionPlanner.conf')
    text = conf.read_text()
    assert 'cache_dir=' in text and demo.cache_dir(str(tmp_path)) in text
    for name in roster_names():
        assert demo.live_layer_key(name) + '\\live_enabled=true' in text


def test_manager_camp_start_empties_the_tile_cache(monkeypatch, tmp_path):
    demo = demo_support
    cache = pathlib.Path(demo.cache_dir(str(tmp_path)))
    cache.mkdir(parents=True)
    (cache / demo.ROOT_MARKER).write_text('x')
    stale = cache / '_boat_sensors_mbes_cube_bathymetry'
    stale.mkdir()
    (stale / 'tile').write_text('old session')
    _camp_start(monkeypatch, tmp_path)
    assert not stale.exists()
    assert (cache / demo.ROOT_MARKER).is_file()


@pytest.fixture
def held_locks():
    """Release the demo locks the manager code took in this process."""
    yield
    demo_support.release_demo_locks()


def _lock_path(tmp_path):
    return pathlib.Path(tmp_path, '.local', 'state', 'marine_simulation_demo', 'lock')


def _other_process_holding(path):
    """Start a process that holds the flock on ``path`` until its stdin closes."""
    import subprocess
    import sys
    code = ('import fcntl, os, sys\n'
            'os.makedirs(os.path.dirname(sys.argv[1]), exist_ok=True)\n'
            'h = open(sys.argv[1], "w"); fcntl.flock(h, fcntl.LOCK_EX | fcntl.LOCK_NB)\n'
            'print("held", flush=True); sys.stdin.read()\n')
    proc = subprocess.Popen([sys.executable, '-c', code, str(path)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == 'held'
    return proc


def _release(proc):
    proc.stdin.close()
    proc.wait(timeout=10)


def test_manager_camp_restarts_keep_the_manager_lock(monkeypatch, tmp_path, held_locks):
    """The manager holds the lock; each group start runs the camp launch file afresh."""
    import fcntl
    from launch import LaunchContext
    monkeypatch.setenv('HOME', str(tmp_path))
    demo_support.acquire_demo_lock(demo_support.state_dir())
    first = _camp_launch_module()
    second = _camp_launch_module()    # exactly what AnyLaunchDescriptionSource does per start
    assert first is not second
    for module in (first, second):
        monkeypatch.setattr(demo_support, 'running_camp_pids', lambda *a, **k: [])
        monkeypatch.setattr(demo_support, 'camp_node', lambda *a, **k: 'camp-node')
        context = LaunchContext()
        context.launch_configurations.update({
            'boats': '', 'roster_file': str(ROSTER),
            'camp_profile': str(PACKAGE / 'config' / 'demo_camp_profile.conf'),
            'camp_view_config': str(PACKAGE / 'config' / 'demo_camp_view.yaml'),
            'target_area_file': ''})
        assert module.launch_setup(context)[-1] == 'camp-node'
    del first, second
    import gc
    gc.collect()
    with open(_lock_path(tmp_path), 'w') as other:    # still held: a third party is refused
        with pytest.raises(BlockingIOError):
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_the_camp_launch_does_not_take_the_lock():
    module = _camp_launch_module()
    assert 'acquire_demo_lock(' not in pathlib.Path(module.__file__).read_text()


def test_a_lock_held_by_another_process_refuses_the_manager(monkeypatch, tmp_path, held_locks):
    monkeypatch.setenv('HOME', str(tmp_path))
    proc = _other_process_holding(_lock_path(tmp_path))
    try:
        with pytest.raises(ValueError, match='already running'):
            demo_support.acquire_demo_lock(demo_support.state_dir())
    finally:
        _release(proc)


def test_main_refuses_at_startup_with_a_plain_message(monkeypatch, tmp_path, held_locks, capsys):
    monkeypatch.setenv('HOME', str(tmp_path))
    proc = _other_process_holding(_lock_path(tmp_path))
    try:
        assert demo_manager.main(['--no-joysticks']) == 2
    finally:
        _release(proc)
    err = capsys.readouterr().err
    assert err.startswith('THE DEMO DID NOT START:') and 'Traceback' not in err


@pytest.mark.parametrize('error', [
    ValueError('bad'), OSError('disk'), yaml.YAMLError('yaml'),
    PackageNotFoundError('coverage_assessment'), ImportError('demo_support')])
def test_main_reports_scorer_parameter_failures_without_a_traceback(
        monkeypatch, tmp_path, held_locks, capsys, error):
    monkeypatch.setenv('HOME', str(tmp_path))

    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(demo_manager, 'scorer_parameters', fail)
    assert demo_manager.main(['--no-joysticks']) == 2
    err = capsys.readouterr().err
    assert 'THE DEMO DID NOT START' in err and 'scorer parameters' in err


# -- one start command: the target-area publisher and the window placement are groups -----------

def test_the_scorer_waits_for_the_target_area_and_the_boats(spec):
    scorer = spec.groups['scorer']
    assert sorted(scorer.requires) == ['boats', 'target_area']
    assert scorer.follows == ['camp']


def test_the_target_area_publisher_is_a_group_that_stops_with_camp(spec):
    group = spec.groups['target_area']
    assert (group.package, group.file) == ('marine_simulation', 'demo_target_area_launch.py')
    assert group.requires == [] and group.follows == ['camp']
    assert group.restart == 'on-failure'
    assert group.ready_nodes == ['/survey_area_publisher']
    assert group.arguments['target_area_file'].default == '/t.json'


def test_the_window_placement_is_a_run_once_group_after_camp(spec):
    group = spec.groups['layout']
    assert (group.package, group.file) == ('marine_simulation', 'demo_layout_launch.py')
    assert group.requires == ['camp'] and group.follows == ['camp']
    assert group.restart == 'never'     # a clean exit ends the group; nothing follows it
    assert group.arguments['layout_config'].default == '/l.yaml'
    assert not any('layout' in other.follows or 'layout' in other.requires
                   for other in spec.groups.values())


def test_camp_opens_the_target_file_and_the_boats_get_the_joystick_file(spec):
    assert spec.groups['camp'].arguments['target_area_file'].default == '/t.json'
    assert spec.groups['boats'].arguments['joystick_config'].default == '/j.yaml'


def test_the_boats_alone_and_the_headless_profile_need_no_display(spec):
    for name in ('boats', 'headless'):
        assert 'camp' not in spec.profiles[name] and 'layout' not in spec.profiles[name]
    assert 'target_area' in spec.profiles['headless']      # the scorer requires it


def _launch_module(name):
    path = PACKAGE / 'launch' / name
    module_spec = importlib.util.spec_from_file_location(name[:-3], str(path))
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _perform_launch_setup(module, **arguments):
    from launch import LaunchContext
    context = LaunchContext()
    context.launch_configurations.update(arguments)
    return module.launch_setup(context)


def _node_parameters(node):
    """Return the text parameters a ``Node`` was given, as a plain dict."""
    return {key[0].text: yaml.safe_load(value[0].text)
            for group in node._Node__parameters for key, value in group.items()}


def test_the_target_area_launch_runs_the_publisher_on_the_given_file(tmp_path):
    target = tmp_path / 'target.json'
    target.write_text('{}')
    (node,) = _perform_launch_setup(_launch_module('demo_target_area_launch.py'),
                                    target_area_file=str(target))
    assert node.node_package == 'marine_simulation'
    assert node.node_executable == 'publish_survey_area.py'
    assert _node_parameters(node) == {'file': str(target)}


def test_the_target_area_launch_without_a_file_leaves_the_publishers_default():
    (node,) = _perform_launch_setup(_launch_module('demo_target_area_launch.py'),
                                    target_area_file='')
    assert _node_parameters(node) == {}


def test_the_target_area_launch_refuses_a_file_that_is_not_there(tmp_path):
    with pytest.raises(ValueError, match='target_area_file'):
        _perform_launch_setup(_launch_module('demo_target_area_launch.py'),
                              target_area_file=str(tmp_path / 'nope.json'))


def test_the_layout_launch_runs_place_windows_once_and_announces_a_failure(tmp_path):
    from launch.actions import ExecuteProcess, RegisterEventHandler
    layout = tmp_path / 'layout.yaml'
    layout.write_text('x: 1\n')
    actions = _perform_launch_setup(_launch_module('demo_layout_launch.py'),
                                    layout_config=str(layout))
    process = [a for a in actions if isinstance(a, ExecuteProcess)]
    assert len(process) == 1 and len(actions) == 2
    assert isinstance(actions[1], RegisterEventHandler)
    cmd = [part[0].text if hasattr(part[0], 'text') else str(part[0])
           for part in process[0].cmd]
    assert cmd[0].endswith('place_windows.py') and cmd[1:] == ['--layout', str(layout)]


def test_the_layout_launch_refuses_a_layout_file_that_is_not_there(tmp_path):
    with pytest.raises(ValueError, match='layout_config'):
        _perform_launch_setup(_launch_module('demo_layout_launch.py'),
                              layout_config=str(tmp_path / 'nope.yaml'))


# -- the manager's own refusals, before anything starts ----------------------------------------

def _files(tmp_path, *names):
    paths = []
    for name in names:
        path = tmp_path / name
        path.write_text('x: 1\n')
        paths.append(str(path))
    return paths


def _preflight(members, tmp_path, **override):
    joysticks, layout, target = _files(tmp_path, 'j.yaml', 'l.yaml', 't.json')
    arguments = {'enable_joysticks': True, 'joystick_config': joysticks, 'layout_config': layout,
                 'target_file': target, 'check_layout': lambda layout: None,
                 'camp_pids': lambda: []}
    arguments.update(override)
    demo_manager.preflight(members, **arguments)


def test_a_complete_demo_passes_the_preflight(tmp_path):
    _preflight(['boats', 'camp', 'scorer', 'target_area', 'layout'], tmp_path)


@pytest.mark.parametrize('override, message', [
    ({'joystick_config': '/nope/j.yaml'}, 'joystick file'),
    ({'layout_config': '/nope/l.yaml'}, 'layout file'),
    ({'target_file': '/nope/t.json'}, 'target area file'),
    ({'camp_pids': lambda: [4242]}, 'CAMP is already running.*4242'),
])
def test_the_preflight_refuses_a_missing_file_or_a_running_camp(tmp_path, override, message):
    with pytest.raises(ValueError, match=message):
        _preflight(['boats', 'camp', 'target_area', 'layout'], tmp_path, **override)


def test_the_preflight_asks_the_placement_tool_and_passes_its_refusal_on(tmp_path):
    def refuse(layout):
        raise ValueError('the windows cannot be laid out: window placement needs X11')
    with pytest.raises(ValueError, match='needs X11'):
        _preflight(['camp', 'layout'], tmp_path, check_layout=refuse)


def test_the_preflight_only_checks_what_the_chosen_groups_use(tmp_path):
    nothing = {'joystick_config': '/nope', 'layout_config': '/nope', 'target_file': '/nope',
               'camp_pids': lambda: [1], 'check_layout': lambda layout: 1 / 0}
    _preflight(['boats', 'scorer'], tmp_path, enable_joysticks=False, **nothing)
    _preflight(['boats'], tmp_path, enable_joysticks=False, **nothing)
    with pytest.raises(ValueError, match='joystick file'):
        _preflight(['boats'], tmp_path, **nothing)


def _tool(tmp_path, script):
    tool = tmp_path / 'place_windows.py'
    tool.write_text('#!/bin/sh\n' + script)
    tool.chmod(0o755)
    return str(tool)


def test_the_layout_check_runs_the_tool_with_check_and_the_layout(tmp_path):
    record = tmp_path / 'args'
    tool = _tool(tmp_path, 'printf "%%s\\n" "$@" > %s\n' % record)
    demo_manager.check_layout_tool('/my/layout.yaml', tool)
    assert record.read_text().split() == ['--check', '--layout', '/my/layout.yaml']


def test_the_layout_check_reports_the_tools_reason_without_its_prefix(tmp_path):
    tool = _tool(tmp_path, 'echo "place_windows: window placement needs an X11 session" >&2\n'
                           'exit 2\n')
    with pytest.raises(ValueError) as error:
        demo_manager.check_layout_tool('/l.yaml', tool)
    assert str(error.value) == ('the windows cannot be laid out: '
                                'window placement needs an X11 session')


def test_the_layout_check_reports_a_tool_that_cannot_run(tmp_path):
    with pytest.raises(ValueError, match='cannot run the window placement check'):
        demo_manager.check_layout_tool('/l.yaml', str(tmp_path / 'missing'))


@pytest.fixture
def run_manager_spy(monkeypatch, tmp_path, held_locks):
    """Run ``main`` on a private HOME with the manager itself replaced by a recorder."""
    from launch_manager_proto import manager
    seen = []
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setattr(manager, 'run_manager', lambda spec: seen.append(spec) or 0)
    monkeypatch.setattr(demo_manager, 'check_layout_tool', lambda layout: None)
    monkeypatch.setattr(demo_support, 'running_camp_pids', lambda *a, **k: [])
    return seen


def test_the_default_demo_starts_every_part_with_the_installed_files(run_manager_spy):
    assert demo_manager.main(['--no-joysticks']) == 0
    (spec,) = run_manager_spy
    assert spec.default_profile == 'demo'
    assert spec.profiles['demo'] == ['boats', 'camp', 'scorer', 'target_area', 'layout']
    share = pathlib.Path(get_package_share_directory('marine_simulation'), 'config')
    polygon = str(share / 'demo_target_polygon_camp.json')
    assert spec.groups['camp'].arguments['target_area_file'].default == polygon
    assert spec.groups['target_area'].arguments['target_area_file'].default == polygon
    assert spec.groups['layout'].arguments['layout_config'].default == str(
        share / 'demo_layout.yaml')


def test_the_files_given_on_the_command_line_reach_their_groups(run_manager_spy, tmp_path):
    joysticks, layout, target = _files(tmp_path, 'my_j.yaml', 'my_l.yaml', 'my_t.json')
    assert demo_manager.main(['--joysticks', joysticks, '--layout', layout,
                              '--target', target]) == 0
    (spec,) = run_manager_spy
    assert spec.groups['boats'].arguments['joystick_config'].default == joysticks
    assert spec.groups['layout'].arguments['layout_config'].default == layout
    assert spec.groups['camp'].arguments['target_area_file'].default == target
    assert spec.groups['target_area'].arguments['target_area_file'].default == target


def test_no_layout_takes_the_placement_out_of_every_profile(run_manager_spy):
    assert demo_manager.main(['--no-joysticks', '--no-layout']) == 0
    (spec,) = run_manager_spy
    assert all('layout' not in members for members in spec.profiles.values())
    assert spec.profiles['demo'] == ['boats', 'camp', 'scorer', 'target_area']


def test_the_layout_and_no_layout_switches_exclude_each_other(run_manager_spy, capsys):
    with pytest.raises(SystemExit):
        demo_manager.main(['--layout', '/x.yaml', '--no-layout'])


@pytest.mark.parametrize('arguments, message', [
    (['--no-joysticks', '--layout', '/nope/l.yaml'], 'layout file'),
    (['--no-joysticks', '--target', '/nope/t.json'], 'target area file'),
    (['--joysticks', '/nope/j.yaml'], 'joystick file'),
])
def test_main_refuses_a_missing_file_before_anything_starts(run_manager_spy, capsys, arguments,
                                                            message):
    assert demo_manager.main(arguments) == 2
    err = capsys.readouterr().err
    assert err.startswith('THE DEMO DID NOT START:') and message in err
    assert 'Traceback' not in err and run_manager_spy == []


def test_main_refuses_a_camp_that_is_already_open(run_manager_spy, monkeypatch, capsys):
    monkeypatch.setattr(demo_support, 'running_camp_pids', lambda *a, **k: [777])
    assert demo_manager.main(['--no-joysticks']) == 2
    assert 'CAMP is already running' in capsys.readouterr().err and run_manager_spy == []


def test_the_headless_profile_needs_no_display_checks(run_manager_spy, monkeypatch):
    monkeypatch.setattr(demo_manager, 'check_layout_tool', lambda layout: 1 / 0)
    monkeypatch.setattr(demo_support, 'running_camp_pids', lambda *a, **k: [777])
    assert demo_manager.main(['--no-joysticks', '--profile', 'headless',
                              '--layout', '/nope/l.yaml']) == 0


# -- there is one way to start the demo, and nothing is loaded by file path ---------------------

def _shipped_files(*directories):
    for directory in directories:
        for path in sorted((PACKAGE / directory).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                yield path


def test_demo_launch_is_gone_as_a_start_path():
    assert not (PACKAGE / 'launch' / 'demo_launch.py').exists()
    assert not (PACKAGE / 'test' / 'test_demo_launch.py').exists()
    stale = [str(p.relative_to(PACKAGE)) for p in _shipped_files(
        'launch', 'scripts', 'config', 'marine_simulation')
        if 'demo_launch.py' in p.read_text(errors='replace')]
    assert stale == []
    cmake = (PACKAGE / 'CMakeLists.txt').read_text()
    assert 'demo_launch' not in cmake and 'demo_manager.py' in cmake


def test_nothing_that_ships_loads_a_module_by_file_path():
    offenders = [str(p.relative_to(PACKAGE)) for p in _shipped_files(
        'launch', 'scripts', 'marine_simulation')
        if p.suffix in ('.py', '') and 'spec_from_file_location' in p.read_text(
            errors='replace')]
    assert offenders == []


def test_the_helpers_the_manager_and_the_launch_files_share_are_importable_modules():
    from marine_simulation import demo_support, roster as roster_module
    for module in (demo_support, roster_module):
        assert pathlib.Path(module.__file__).is_file()
    # the boats launch re-exports the roster's functions rather than keeping copies
    boats = _launch_module('demo_boats_launch.py')
    for name in ('Boat', 'load_roster', 'select_boats', 'parse_bool'):
        assert getattr(boats, name) is getattr(roster_module, name), name


def test_option_abbreviations_are_rejected(run_manager_spy):
    for abbreviation in ('--prof', '--no-lay', '--lay'):
        with pytest.raises(SystemExit):
            demo_manager.main([abbreviation, 'x'])


def test_a_missing_roster_file_is_a_plain_refusal(capsys):
    assert demo_manager.main(['--roster', '/nope/roster.yaml']) == 2
    err = capsys.readouterr().err
    assert 'roster problem' in err and 'Traceback' not in err


def test_an_unwritable_state_directory_is_a_plain_refusal(monkeypatch, capsys):
    def fail(directory):
        raise PermissionError('read-only file system')
    monkeypatch.setattr(demo_support, 'acquire_demo_lock', fail)
    assert demo_manager.main(['--no-joysticks']) == 2
    err = capsys.readouterr().err
    assert err.startswith('THE DEMO DID NOT START:') and 'read-only' in err


def test_the_layout_check_honours_the_same_tool_override_as_run_demo_sh(tmp_path, monkeypatch):
    record = tmp_path / 'args'
    tool = _tool(tmp_path, 'printf "%%s\\n" "$@" > %s\n' % record)
    monkeypatch.setenv('DEMO_PLACE_WINDOWS', tool)
    demo_manager.check_layout_tool('/my/layout.yaml')
    assert record.read_text().split() == ['--check', '--layout', '/my/layout.yaml']
