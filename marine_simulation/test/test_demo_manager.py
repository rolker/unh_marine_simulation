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
import shutil

from ament_index_python.packages import get_package_share_directory, PackageNotFoundError
from launch_manager_proto import config
from marine_simulation import demo_support
from marine_simulation import roster
import pytest
import yaml

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = PACKAGE / 'scripts' / 'demo_manager.py'
CONFIG = PACKAGE / 'config' / 'demo_manager.yaml'
SHIPPED_PERSPECTIVE = PACKAGE / 'config' / 'demo.perspective'
ROSTER = PACKAGE / 'config' / 'demo_roster.yaml'
POLYGON = PACKAGE / 'config' / 'demo_target_polygon_camp.json'
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
    assert set(spec.groups) == {'boats', 'camp', 'scorer', 'target_area', 'layout', 'rqt'}
    assert spec.profiles['demo'] == ['boats', 'camp', 'scorer', 'target_area', 'layout', 'rqt']
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
              'layout_config': str(PACKAGE / 'config' / 'demo_layout.yaml'), 'camp_fresh': 'false',
              'target_area_file': str(POLYGON)}
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
    assert started == [(demo.settings_root(str(tmp_path)), str(POLYGON))]
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
            'layout_config': str(PACKAGE / 'config' / 'demo_layout.yaml'), 'camp_fresh': 'false',
            'target_area_file': str(POLYGON)})
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
                 'camp_pids': lambda: [], 'check_target': lambda target: None}
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
    assert spec.profiles['demo'] == ['boats', 'camp', 'scorer', 'target_area', 'layout', 'rqt']
    share = pathlib.Path(get_package_share_directory('marine_simulation'), 'config')
    polygon = str(share / 'demo_target_polygon_camp.json')
    assert spec.groups['camp'].arguments['target_area_file'].default == polygon
    assert spec.groups['target_area'].arguments['target_area_file'].default == polygon
    assert spec.groups['layout'].arguments['layout_config'].default == str(
        share / 'demo_layout.yaml')


def test_the_files_given_on_the_command_line_reach_their_groups(run_manager_spy, tmp_path):
    joysticks, layout, target = _files(tmp_path, 'my_j.yaml', 'my_l.yaml', 'my_t.json')
    shutil.copy(PACKAGE / 'config' / 'demo_target_polygon_camp.json', target)
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
    assert spec.profiles['demo'] == ['boats', 'camp', 'scorer', 'target_area', 'rqt']


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


# -- extra boats-launch arguments: name:=value ---------------------------------------------------

def _boats_arguments(spec):
    return {name: arg.default for name, arg in spec.groups['boats'].arguments.items()}


def test_a_declared_boats_launch_argument_reaches_the_boats_group(run_manager_spy):
    assert demo_manager.main(['--no-joysticks', 'tide_speed_factor:=0', 'cell_size:=2.5']) == 0
    (spec,) = run_manager_spy
    arguments = _boats_arguments(spec)
    assert arguments['tide_speed_factor'] == '0' and arguments['cell_size'] == '2.5'
    assert arguments['lifecycle_guard'] is False       # the manager's own settings are intact
    from launch_manager_proto.manager import launch_argument_text
    assert launch_argument_text(arguments['tide_speed_factor']) == '0'


def test_the_last_value_of_a_repeated_argument_wins(run_manager_spy):
    assert demo_manager.main(['--no-joysticks', 'tide_speed_factor:=1',
                              'tide_speed_factor:=3']) == 0
    assert _boats_arguments(run_manager_spy[0])['tide_speed_factor'] == '3'


def test_no_extra_arguments_leaves_the_boats_group_as_configured(run_manager_spy):
    assert demo_manager.main(['--no-joysticks']) == 0
    assert 'tide_speed_factor' not in _boats_arguments(run_manager_spy[0])


@pytest.mark.parametrize('argument, message', [
    ('tide_speed_fcator:=1', 'not an argument of the boats launch.*tide_speed_factor'),
    ('boats:=bluefin', r'set by the demo.s own options'),
    ('roster_file:=/x.yaml', r'set by the demo.s own options'),
    ('enable_joysticks:=false', r'set by the demo.s own options'),
    ('joystick_config:=/x.yaml', r'set by the demo.s own options'),
    ('lifecycle_guard:=true', r'set by the demo.s own options'),
    ('tide_speed_factor', 'name:=value'),
    ('=1', 'name:=value'),
])
def test_an_unknown_or_manager_owned_argument_is_refused(run_manager_spy, capsys, argument,
                                                         message):
    assert demo_manager.main(['--no-joysticks', argument]) == 2
    err = capsys.readouterr().err
    assert err.startswith('THE DEMO DID NOT START:') and 'Traceback' not in err
    assert re.search(message, err), err
    assert run_manager_spy == []


def test_the_declared_names_are_read_from_the_launch_file_not_listed_here():
    declared = demo_support.declared_launch_arguments()
    boats = _launch_module('demo_boats_launch.py')
    from launch.actions import DeclareLaunchArgument
    expected = [e.name for e in boats.generate_launch_description().entities
                if isinstance(e, DeclareLaunchArgument)]
    assert declared == expected and 'tide_speed_factor' in declared


def test_the_owned_names_come_from_the_configuration(spec):
    declared = ['boats', 'tide_speed_factor', 'brand_new_argument']
    extra = demo_manager.boats_launch_arguments(spec, ['brand_new_argument:=1'], declared)
    assert extra == {'brand_new_argument': '1'}      # a new launch argument needs no code here
    with pytest.raises(ValueError, match='set by the demo'):
        demo_manager.boats_launch_arguments(spec, ['boats:=x'], declared)


# -- empty option values and the target area's content --------------------------------------

@pytest.mark.parametrize('option', ['--roster', '--joysticks', '--layout', '--target',
                                    '--config', '--profile'])
@pytest.mark.parametrize('form', ['separate', 'equals'])
def test_an_empty_option_value_is_refused_not_replaced_by_a_default(run_manager_spy, capsys,
                                                                    option, form):
    argv = [option, ''] if form == 'separate' else [option + '=']
    with pytest.raises(SystemExit) as stop:
        demo_manager.main(['--no-joysticks'] + argv)
    assert stop.value.code == 2 and 'needs a value' in capsys.readouterr().err
    assert run_manager_spy == []


def test_a_malformed_target_file_is_refused_before_anything_starts(
        run_manager_spy, tmp_path, capsys):
    bad = tmp_path / 'bad.json'
    bad.write_text('{"not": json')
    assert demo_manager.main(['--no-joysticks', '--target', str(bad)]) == 2
    err = capsys.readouterr().err
    assert err.startswith('THE DEMO DID NOT START:') and 'target area file cannot be used' in err
    assert 'not valid JSON' in err and 'Traceback' not in err and run_manager_spy == []


def test_a_target_file_with_no_survey_area_is_refused(run_manager_spy, tmp_path, capsys):
    empty = tmp_path / 'empty.json'
    empty.write_text('{}')
    assert demo_manager.main(['--no-joysticks', '--target', str(empty)]) == 2
    assert 'target area file cannot be used' in capsys.readouterr().err


def test_the_installed_demo_polygon_passes_the_target_check():
    demo_manager.check_target_tool(str(PACKAGE / 'config' / 'demo_target_polygon_camp.json'))


def test_the_headless_profile_skips_nothing_about_the_target(run_manager_spy, tmp_path, capsys):
    bad = tmp_path / 'bad.json'
    bad.write_text('nope')
    # target_area is in the headless profile, so its file is checked there too
    assert demo_manager.main(['--no-joysticks', '--profile', 'headless', '--target',
                              str(bad)]) == 2
    assert 'target area file cannot be used' in capsys.readouterr().err


def test_the_target_check_reports_a_tool_that_cannot_run(tmp_path):
    with pytest.raises(ValueError, match='cannot run the target area check'):
        demo_manager.check_target_tool('/t.json', str(tmp_path / 'missing'))


# --- the camp_fresh option ---------------------------------------------------------------

def test_the_fresh_option_reaches_the_camp_group_and_defaults_off():
    off = demo_manager.substitutions(['a'], '', True, '/s', '/r', '/j', '/l', '/t')
    on = demo_manager.substitutions(['a'], '', True, '/s', '/r', '/j', '/l', '/t', True)
    assert (off['camp_fresh'], on['camp_fresh']) == ('false', 'true')
    loaded = config.load_config(str(CONFIG), on)
    assert loaded.groups['camp'].arguments['camp_fresh'].default == 'true'


def test_the_parser_knows_camp_fresh():
    parser = demo_manager.build_parser()
    assert parser.parse_args([]).camp_fresh is False
    assert parser.parse_args(['--camp-fresh']).camp_fresh is True


def test_manager_camp_start_passes_fresh_to_the_actions(monkeypatch, tmp_path):
    seen = []
    import marine_simulation.demo_support as support
    real = support.camp_actions
    monkeypatch.setattr(support, 'camp_actions', lambda *a, **k: seen.append(k) or real(*a, **k))
    _camp_start(monkeypatch, tmp_path, camp_fresh='true')
    _camp_start(monkeypatch, tmp_path)
    assert [k['fresh'] for k in seen] == [True, False]


# --- rqt on the demo perspective -----------------------------------------------------------

def test_the_rqt_group_needs_nothing_stops_with_camp_and_is_never_restarted(spec):
    group = spec.groups['rqt']
    assert (group.package, group.file) == ('marine_simulation', 'demo_rqt_launch.py')
    assert group.requires == [] and group.follows == ['camp']
    assert group.restart == 'never'
    assert group.arguments['rqt_fresh'].default == 'false'
    assert group.arguments['boats'].default == '' and 'roster_file' in group.arguments
    # nothing waits for rqt or stops with it
    assert not any('rqt' in other.requires or 'rqt' in other.follows
                   for name, other in spec.groups.items() if name != 'rqt')
    # it is part of the demo display only
    assert 'rqt' in spec.profiles['demo']
    assert all('rqt' not in members for name, members in spec.profiles.items()
               if name != 'demo')


def test_the_rqt_fresh_option_reaches_the_rqt_group_and_defaults_off():
    off = demo_manager.substitutions(['a'], '', True, '/s', '/r', '/j', '/l', '/t')
    on = demo_manager.substitutions(['a'], '', True, '/s', '/r', '/j', '/l', '/t', False, True)
    assert (off['rqt_fresh'], on['rqt_fresh']) == ('false', 'true')
    assert on['camp_fresh'] == 'false'          # the two options are independent
    loaded = config.load_config(str(CONFIG), on)
    assert loaded.groups['rqt'].arguments['rqt_fresh'].default == 'true'
    assert loaded.groups['camp'].arguments['camp_fresh'].default == 'false'


def test_the_parser_knows_rqt_fresh():
    parser = demo_manager.build_parser()
    assert parser.parse_args([]).rqt_fresh is False
    assert parser.parse_args(['--rqt-fresh']).rqt_fresh is True


# -- the navigation stack switch ------------------------------------------------------------

def test_nav_is_off_by_default_and_the_option_has_a_no_form():
    parser = demo_manager.build_parser()
    assert parser.parse_args([]).nav is False
    assert parser.parse_args(['--nav']).nav is True
    assert parser.parse_args(['--nav', '--no-nav']).nav is False


def test_nav_raises_the_expected_lifecycle_nodes_by_mission_manager_only():
    names = roster_names()
    off = demo_manager.substitutions(names, '', True, '/s', '/r', '/j', '/l', '/t')
    on = demo_manager.substitutions(names, '', True, '/s', '/r', '/j', '/l', '/t',
                                    enable_nav=True)
    per_boat = demo_manager.MIN_LIFECYCLE_NODES_PER_BOAT
    assert off['boats_expect'] == str(per_boat * len(names))
    assert on['boats_expect'] == str((per_boat + 1) * len(names))
    assert (off['enable_nav'], on['enable_nav']) == ('false', 'true')
    loaded = config.load_config(str(CONFIG), on)
    assert loaded.groups['boats'].lifecycle.expect == (per_boat + 1) * len(names)
    assert loaded.groups['boats'].arguments['enable_nav'].default == 'true'


def test_the_boats_group_leaves_nav2s_own_lifecycle_nodes_to_nav2(spec):
    life = spec.groups['boats'].lifecycle
    name = roster_names()[0]
    found = [n for n in ('/%s/helm_manager' % name, '/%s/mission_manager' % name,
                         '/%s/sensors/mbes/cube_bathymetry' % name,
                         '/%s/controller_server' % name, '/%s/bt_task_navigator' % name,
                         '/%s/global_costmap/global_costmap' % name)
             if re.search(life.match, n) and not re.search(life.exclude, n)]
    assert found == ['/%s/helm_manager' % name, '/%s/mission_manager' % name,
                     '/%s/sensors/mbes/cube_bathymetry' % name]


def test_enable_nav_is_owned_by_the_manager_so_an_extra_one_is_refused(spec):
    with pytest.raises(ValueError, match='set by the demo'):
        demo_manager.boats_launch_arguments(
            spec, ['enable_nav:=true'], ['boats', 'enable_nav'])


def test_main_passes_nav_to_the_boats_group(run_manager_spy):
    assert demo_manager.main(['--no-joysticks', '--nav']) == 0
    (spec,) = run_manager_spy
    assert spec.groups['boats'].arguments['enable_nav'].default == 'true'
    assert spec.groups['boats'].lifecycle.expect % (demo_manager.MIN_LIFECYCLE_NODES_PER_BOAT
                                                    + 1) == 0


def _text(log_info):
    return ''.join(part.text for part in log_info.msg)


def _rqt_launch(monkeypatch, tmp_path, ini_text=None, **arguments):
    """Perform the rqt launch's setup on a private home; return its actions."""
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    if ini_text is not None:
        (tmp_path / 'config' / 'ros.org').mkdir(parents=True, exist_ok=True)
        (tmp_path / 'config' / 'ros.org' / 'rqt_gui.ini').write_text(ini_text)
    monkeypatch.setattr('shutil.which', lambda name: '/opt/ros/jazzy/bin/rqt')
    values = {'boats': '', 'roster_file': str(ROSTER), 'rqt_perspective_file': '',
              'rqt_fresh': 'false'}
    values.update(arguments)
    return _perform_launch_setup(_launch_module('demo_rqt_launch.py'), **values)


def _words(process):
    return [part[0].text for part in process.cmd]


def _generated(tmp_path, names):
    from marine_simulation import demo_perspective
    return demo_perspective.generated_file(
        names, str(tmp_path / 'home' / '.local' / 'state' / 'marine_simulation_demo' / 'rqt'))


def _stored(path):
    """Return the settings text rqt writes after it imported ``path`` (a binary name list)."""
    import os
    name = '%40' + os.path.basename(path)[0:]
    return ('[General]\nperspectives=@Variant(\\0\\0\\0\\t)\n\n[perspective]\n'
            + name + '\\pluginmanager\\running-plugins=x\n')


def test_the_first_start_imports_the_perspective_generated_for_the_roster(
        monkeypatch, tmp_path):
    from launch.actions import ExecuteProcess, LogInfo
    message, process = _rqt_launch(monkeypatch, tmp_path)
    assert isinstance(message, LogInfo) and isinstance(process, ExecuteProcess)
    assert 'importing' in _text(message) and 'first start' in _text(message)
    assert process.cmd[0][0].text == '/opt/ros/jazzy/bin/rqt'
    # rqt runs on the operator's settings: nothing here may point XDG_CONFIG_HOME elsewhere
    assert process.additional_env is None
    words = _words(process)
    names = roster_names()
    assert words[1:3] == ['--force-discover', '--perspective-file']
    assert words[3] == _generated(tmp_path, names)
    # the whole roster gives the file shipped in config/ (same content, so same bytes)
    assert pathlib.Path(words[3]).read_text() == SHIPPED_PERSPECTIVE.read_text()
    assert '--lock-perspective' not in words


def test_a_later_start_uses_the_stored_perspective_by_the_name_rqt_gave_it(
        monkeypatch, tmp_path):
    path = _generated(tmp_path, roster_names())
    message, process = _rqt_launch(monkeypatch, tmp_path, _stored(path))
    assert 'stored perspective' in _text(message)
    assert _words(process)[1:] == ['--force-discover', '--perspective',
                                   '@' + pathlib.Path(path).name]


def test_a_different_set_of_boats_is_its_own_perspective_and_is_imported(monkeypatch, tmp_path):
    names = roster_names()
    stored = _stored(_generated(tmp_path, names))
    message, process = _rqt_launch(monkeypatch, tmp_path, stored, boats=','.join(names[:2]))
    assert 'first start' in _text(message)
    imported = pathlib.Path(_words(process)[3])
    assert imported != pathlib.Path(_generated(tmp_path, names))
    text = imported.read_text()
    assert '/%s/sensors/mbes/detections' % names[0] in text
    assert '/%s/sensors/mbes/detections' % names[-1] not in text


def test_the_fresh_option_imports_again_once_per_process(monkeypatch, tmp_path):
    stored = _stored(_generated(tmp_path, roster_names()))
    first, process = _rqt_launch(monkeypatch, tmp_path, stored, rqt_fresh='true')
    assert 'asked for' in _text(first)
    assert '--perspective-file' in _words(process)
    # a restart of the group in the same manager process keeps what rqt saved since
    second, process = _rqt_launch(monkeypatch, tmp_path, rqt_fresh='true')
    assert 'stored perspective' in _text(second)
    assert '--perspective' in _words(process)


def test_an_explicit_perspective_file_replaces_the_generated_one(monkeypatch, tmp_path):
    message, process = _rqt_launch(monkeypatch, tmp_path,
                                   rqt_perspective_file=str(SHIPPED_PERSPECTIVE))
    assert _words(process)[3] == str(SHIPPED_PERSPECTIVE)


def test_an_unreadable_rqt_settings_file_still_starts_rqt_without_the_perspective(
        monkeypatch, tmp_path):
    from launch.actions import ExecuteProcess
    (tmp_path / 'config' / 'ros.org' / 'rqt_gui.ini').mkdir(parents=True)     # a directory
    message, process = _rqt_launch(monkeypatch, tmp_path)
    assert 'without the demo perspective' in _text(message)
    assert isinstance(process, ExecuteProcess)
    assert _words(process)[1:] == ['--force-discover']


def test_a_missing_rqt_is_a_message_not_a_failed_demo(monkeypatch):
    from launch.actions import LogInfo
    monkeypatch.setattr('shutil.which', lambda name: None)
    (message,) = _perform_launch_setup(_launch_module('demo_rqt_launch.py'),
                                       boats='', roster_file=str(ROSTER),
                                       rqt_perspective_file='', rqt_fresh='false')
    assert isinstance(message, LogInfo)
