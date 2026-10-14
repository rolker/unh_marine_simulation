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
Unit tests for launch/demo_launch.py.

The launch file is loaded by path. The tests build the launch description by calling
``launch_setup`` with a hand-made context instead of running it, because running it
would start CAMP and the boats. Boat names come from the shipped roster (or are
synthetic), never quoted.
"""

import importlib.util
import os
import pathlib
import random
import time

from ament_index_python.packages import get_package_share_directory, PackageNotFoundError
from launch import LaunchContext, LaunchDescription, LaunchService
from launch.actions import EmitEvent, ExecuteProcess, IncludeLaunchDescription
from launch.actions import RegisterEventHandler
from launch.events import Shutdown
from launch.events.process import ProcessExited
import pytest
import yaml

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
LAUNCH = PACKAGE / 'launch' / 'demo_launch.py'
_spec = importlib.util.spec_from_file_location('demo_launch', LAUNCH)
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)

CONFIG = PACKAGE / 'config'


def _installed(package):
    try:
        get_package_share_directory(package)
        return True
    except PackageNotFoundError:
        return False


needs_camp = pytest.mark.skipif(not _installed('camp'), reason='camp is not installed')
needs_scorer = pytest.mark.skipif(not _installed('coverage_assessment'),
                                  reason='coverage_assessment is not installed')


def _boat(name, index=0, lat=43.0, lon=-70.7):
    return demo.boats_launch.Boat(name=name, pad='x', color=(1.0, 1.0, 1.0), lat=lat, lon=lon,
                                  heading=0.0, index=index)


@pytest.fixture
def roster():
    return demo.boats_launch.load_roster(str(CONFIG / 'demo_roster.yaml'))


# --- the Qt value encoder -----------------------------------------------------------

# Samples written by Qt 5.15's own QSettings (QPointF in an INI file).
QT_SAMPLES = [
    ((-7871456.853737771, 5323287.301604602),
     r'@Variant(\0\0\0\x1a\xc1^\x6\xf8\x36\xa3\xa3\xbf\x41TN\x85\xd3M}c)'),
    ((-7871000.5, 5300000.25), r'@Variant(\0\0\0\x1a\xc1^\x6\x86 \0\0\0\x41T7\xc8\x10\0\0\0)'),
    ((0.0, 0.0), r'@Variant(\0\0\0\x1a\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0)'),
    ((44.0, 44.0), r'@Variant(\0\0\0\x1a@F\0\0\0\0\0\0@F\0\0\0\0\0\0)'),
    # Contains a comma, so Qt quotes the whole value.
    ((-6771564.69930638, -4981698.6370737385),
     r'"@Variant(\0\0\0\x1a\xc1Y\xd4\xdb,\xc1o\x8c\xc1S\0\xf0\xa8\xc5\xd0\xee)"'),
]


@pytest.mark.parametrize('point, text', QT_SAMPLES)
def test_point_variant_matches_what_qt_writes(point, text):
    assert demo.qt_point_variant(*point) == text


def test_point_variant_matches_qt_for_random_points(tmp_path):
    qtcore = pytest.importorskip('PyQt5.QtCore')
    rng = random.Random(3)
    for number in range(300):
        x, y = rng.uniform(-2e7, 2e7), rng.uniform(-2e7, 2e7)
        path = str(tmp_path / ('s%d.conf' % number))
        settings = qtcore.QSettings(path, qtcore.QSettings.IniFormat)
        settings.setValue('MainWindow/mapCenter', qtcore.QPointF(x, y))
        settings.sync()
        line = [row for row in open(path).read().splitlines()
                if row.startswith('mapCenter=')][0]
        assert line == 'mapCenter=' + demo.qt_point_variant(x, y)


def test_web_mercator_matches_camps_formula():
    assert demo.web_mercator(0.0, 0.0) == (0.0, 0.0)
    x, y = demo.web_mercator(0.0, 180.0)
    assert x == pytest.approx(20037508.342789244)
    assert y == 0.0
    x, y = demo.web_mercator(43.074296, -70.7105)
    assert (x, y) == pytest.approx((-7871456.853737771, 5323287.301604602))


# --- the profile --------------------------------------------------------------------

def test_live_layer_key_matches_what_camp_writes():
    # Copied from a real CAMP settings file.
    assert demo.live_layer_key('bluefin') == \
        'live%3A%252Fbluefin%252Fsensors%252Fmbes%252Fcube_bathymetry'


def test_the_shipped_template_parses_and_has_no_generated_section():
    sections = demo.parse_profile((CONFIG / 'demo_camp_profile.conf').read_text())
    assert 'MainWindow' not in sections and 'MapView' not in sections
    assert sections['BackgroundTileLayers'][0] == 'ids=openstreetmap'
    assert 'seeded=true' in sections['BackgroundTileLayers']


def test_profile_has_the_view_and_a_live_layer_per_boat():
    template = (CONFIG / 'demo_camp_profile.conf').read_text()
    boats = [_boat('one'), _boat('two')]
    text = demo.build_profile(template, boats, 43.0743, -70.7105, 1.25)
    sections = demo.parse_profile(text)
    assert 'mapScale=1.25' in sections['MainWindow']
    assert sections['MainWindow'][0].startswith('mapCenter=')
    assert sections['MapView'][1] == r'mapView\scale=1.25'
    assert sections['MapView'][0].replace(r'mapView\center', 'mapCenter') == \
        sections['MainWindow'][0]
    for name in ('one', 'two'):
        key = demo.live_layer_key(name)
        assert '%s\\live_enabled=true' % key in sections['MapItem']
        assert '%s\\visible=true' % key in sections['MapItem']
    # The fixed part is still there.
    assert 'openstreetmap\\visible=true' in sections['MapItem']
    assert len(sections['MapItem']) == 4 + 2 * 2


def test_profile_reads_back_the_same_view_in_qt(tmp_path):
    qtcore = pytest.importorskip('PyQt5.QtCore')
    template = (CONFIG / 'demo_camp_profile.conf').read_text()
    path = tmp_path / 'p.conf'
    path.write_text(demo.build_profile(template, [_boat('one')], 43.074296, -70.7105, 0.9))
    settings = qtcore.QSettings(str(path), qtcore.QSettings.IniFormat)
    point = settings.value('MainWindow/mapCenter')
    assert (point.x(), point.y()) == pytest.approx(demo.web_mercator(43.074296, -70.7105))
    assert float(settings.value('MainWindow/mapScale')) == 0.9
    assert settings.value('MapView/mapView/center') == point
    key = demo.live_layer_key('one')
    settings.beginGroup('MapItem')
    settings.beginGroup(key.replace('%3A', ':').replace('%25', '%'))
    # QSettings decodes the percent escapes of group names itself.
    assert settings.value('visible') == 'true' or settings.value('visible') is True
    assert settings.value('live_enabled') in ('true', True)


@pytest.mark.parametrize('section', ['MainWindow', 'MapView'])
def test_profile_template_may_not_set_the_generated_sections(section):
    with pytest.raises(ValueError, match=section):
        demo.build_profile('[%s]\nx=1\n' % section, [_boat('one')], 43.0, -70.0, 1.0)


@pytest.mark.parametrize('scale', [0.0, -1.0, float('nan'), float('inf')])
def test_profile_rejects_a_bad_scale(scale):
    with pytest.raises(ValueError, match='view_scale'):
        demo.build_profile('', [_boat('one')], 43.0, -70.0, scale)


@pytest.mark.parametrize('text', ['key=1\n', '[open\nk=v\n', '[s]\nno equals sign\n'])
def test_profile_parser_rejects_malformed_text(text):
    with pytest.raises(ValueError):
        demo.parse_profile(text)


def test_view_centre_is_the_mean_of_the_boat_starts():
    boats = [_boat('a', lat=43.0, lon=-70.0), _boat('b', lat=45.0, lon=-72.0)]
    assert demo.view_center(boats) == (44.0, -71.0)


def test_shipped_view_config_loads():
    view = demo.load_view(str(CONFIG / 'demo_camp_view.yaml'))
    assert view['scale'] > 0 and 'lat' not in view


@pytest.mark.parametrize('body', [
    'camp_view: {}\n', 'camp_view: {scale: 1, lat: 43.0}\n', 'camp_view: {scale: 1, zoom: 2}\n',
    'nothing: 1\n', '- a\n'])
def test_view_config_rejects_a_malformed_file(tmp_path, body):
    path = tmp_path / 'view.yaml'
    path.write_text(body)
    with pytest.raises(ValueError):
        demo.load_view(str(path))


# --- the settings directory ---------------------------------------------------------

def test_seeding_writes_the_profile_where_camp_reads_it(tmp_path):
    root = demo.settings_root(str(tmp_path))
    path = demo.seed_camp_settings(root, '[A]\nk=v\n', str(tmp_path))
    assert path == os.path.join(root, 'UNH-CCOMJHC', 'CCOMAutonomousMissionPlanner.conf')
    assert open(path).read() == '[A]\nk=v\n'


def test_seeding_again_throws_away_what_a_session_left_behind(tmp_path):
    root = demo.settings_root(str(tmp_path))
    path = demo.seed_camp_settings(root, 'first\n', str(tmp_path))
    with open(os.path.join(root, 'QtProject.conf'), 'w') as f:  # Qt writes such files
        f.write('leftover')
    with open(path, 'a') as f:
        f.write('drift')
    demo.seed_camp_settings(root, 'second\n', str(tmp_path))
    assert open(path).read() == 'second\n'
    assert not os.path.exists(os.path.join(root, 'QtProject.conf'))


def test_seeding_never_touches_the_operators_own_camp_settings(tmp_path):
    own = tmp_path / '.config' / 'UNH-CCOMJHC'
    own.mkdir(parents=True)
    (own / 'CCOMAutonomousMissionPlanner.conf').write_text('mine')
    demo.seed_camp_settings(demo.settings_root(str(tmp_path)), 'demo\n', str(tmp_path))
    assert (own / 'CCOMAutonomousMissionPlanner.conf').read_text() == 'mine'


def test_reset_refuses_a_path_that_is_not_the_demo_directory(tmp_path):
    victim = tmp_path / 'precious'
    victim.mkdir()
    (victim / 'file').write_text('x')
    with pytest.raises(ValueError, match='refusing'):
        demo.reset_settings_root(str(victim), str(tmp_path))
    with pytest.raises(ValueError, match='refusing'):
        demo.reset_settings_root(str(tmp_path), str(tmp_path))
    assert (victim / 'file').read_text() == 'x'


def test_reset_refuses_a_symlink_and_leaves_its_target_alone(tmp_path):
    target = tmp_path / 'elsewhere'
    target.mkdir()
    (target / 'keep').write_text('x')
    root = pathlib.Path(demo.settings_root(str(tmp_path)))
    root.parent.mkdir(parents=True)
    root.symlink_to(target)
    with pytest.raises(ValueError, match='symlink'):
        demo.reset_settings_root(str(root), str(tmp_path))
    assert (target / 'keep').read_text() == 'x'


def test_reset_refuses_a_directory_it_did_not_create(tmp_path):
    root = pathlib.Path(demo.settings_root(str(tmp_path)))
    root.mkdir(parents=True)
    (root / 'stranger.txt').write_text('x')
    with pytest.raises(ValueError, match='did not create'):
        demo.reset_settings_root(str(root), str(tmp_path))
    assert (root / 'stranger.txt').read_text() == 'x'


def test_reset_accepts_an_empty_existing_directory(tmp_path):
    root = pathlib.Path(demo.settings_root(str(tmp_path)))
    root.mkdir(parents=True)
    assert demo.reset_settings_root(str(root), str(tmp_path)) == str(root)
    assert (root / demo.ROOT_MARKER).is_file()


def test_reset_refuses_a_plain_file(tmp_path):
    root = pathlib.Path(demo.settings_root(str(tmp_path)))
    root.parent.mkdir(parents=True)
    root.write_text('x')
    with pytest.raises(ValueError, match='not a directory'):
        demo.reset_settings_root(str(root), str(tmp_path))


# --- scorer parameters --------------------------------------------------------------

TEMPLATE = {'/**/coverage_assessment': {'ros__parameters': {
    'grid_topics': ['/zzz/grid'], 'source_names': ['zzz'], 'survey_area_topic': '/survey_area',
    'cell_size': 1.0, 'map_frame': 'zzz/map', 'water_surface_frame': 'zzz/map_tide',
    'water_surface_boat_frame': 'zzz/base_link', 'max_areas': 20}}}


def test_scorer_parameters_follow_the_boats_not_the_template():
    out = demo.scorer_parameters(TEMPLATE, [_boat('one'), _boat('two', 1)])
    p = out['/**/coverage_assessment']['ros__parameters']
    assert p['grid_topics'] == ['/one/sensors/mbes/grid', '/two/sensors/mbes/grid']
    assert p['source_names'] == ['one', 'two']
    assert (p['map_frame'], p['water_surface_frame'], p['water_surface_boat_frame']) == \
        ('one/map', 'one/map_tide', 'one/base_link')
    assert p['survey_area_topic'] == '/survey_area' and p['max_areas'] == 20
    assert 'zzz' not in yaml.safe_dump(out)


def test_scorer_parameters_do_not_modify_the_template():
    before = yaml.safe_dump(TEMPLATE)
    demo.scorer_parameters(TEMPLATE, [_boat('one')])
    assert yaml.safe_dump(TEMPLATE) == before


def test_scorer_needs_a_boat_and_a_usable_template():
    with pytest.raises(ValueError, match='at least one boat'):
        demo.scorer_parameters(TEMPLATE, [])
    with pytest.raises(ValueError, match='no'):
        demo.scorer_parameters({'x': 1}, [_boat('one')])


@needs_scorer
def test_the_installed_scorer_example_is_a_usable_template(tmp_path, roster):
    template = os.path.join(get_package_share_directory('coverage_assessment'),
                            'config', 'coverage_assessment.yaml')
    path = demo.write_scorer_parameters(template, roster, str(tmp_path))
    p = yaml.safe_load(open(path))['/**/coverage_assessment']['ros__parameters']
    assert p['source_names'] == [b.name for b in roster]
    assert 'grid_topics' in p


# --- target area (issue #93) --------------------------------------------------------

def test_target_area_is_off_by_default_and_adds_nothing():
    assert demo.target_area_actions(False, '', lambda: False) == []


def test_target_area_needs_a_file(tmp_path):
    with pytest.raises(ValueError, match='target_area_file'):
        demo.target_area_actions(True, '', lambda: True)
    with pytest.raises(ValueError, match='not a file'):
        demo.target_area_actions(True, str(tmp_path / 'missing.json'), lambda: True)


def test_target_area_is_refused_until_issue_93_is_installed(tmp_path):
    target = tmp_path / 'target.json'
    target.write_text('{}')
    with pytest.raises(ValueError, match='#93'):
        demo.target_area_actions(True, str(target), lambda: False)


def test_target_area_becomes_one_node_with_the_file_parameter(tmp_path):
    target = tmp_path / 'target.json'
    target.write_text('{}')
    actions = demo.target_area_actions(True, str(target), lambda: True)
    assert len(actions) == 1
    node = actions[0]
    assert node.node_package == 'marine_simulation'
    assert node.node_executable == 'publish_survey_area.py'
    assert _perform(node._Node__node_name) == 'survey_area_publisher'
    assert node._Node__parameters is not None


# --- window placement preflight -----------------------------------------------------

class FakeWindows:
    """Stand-in for place_windows whose check_layout uses a fake wmctrl and xrandr."""

    def __init__(self, real, xrandr, wmctrl_ok=True):
        self._real = real
        self._xrandr = xrandr
        self._wmctrl_ok = wmctrl_ok

    def __getattr__(self, name):
        return getattr(self._real, name)

    def check_layout(self, path, environ):
        def runner(command):
            if command[0] == 'wmctrl':
                if not self._wmctrl_ok:
                    raise self._real.LayoutError(
                        'wmctrl is not installed (sudo apt install wmctrl)')
                return ''
            return self._xrandr
        return self._real.check_layout(path, environ, runner)


XRANDR = ' 0: +*HDMI-0 3840/800x2160/450+0+240  HDMI-0\n'
X11 = {'XDG_SESSION_TYPE': 'x11', 'DISPLAY': ':0'}


def _fake(xrandr=XRANDR, wmctrl_ok=True):
    return FakeWindows(demo.load_place_windows(), xrandr, wmctrl_ok)


def test_placement_preflight_passes_for_the_shipped_layout():
    demo.check_placement_prerequisites(str(CONFIG / 'demo_layout.yaml'), _fake(), X11)


def test_placement_preflight_refuses_wayland():
    with pytest.raises(ValueError, match='X11'):
        demo.check_placement_prerequisites(
            str(CONFIG / 'demo_layout.yaml'), _fake(),
            {'XDG_SESSION_TYPE': 'wayland', 'DISPLAY': ':0'})


def test_placement_preflight_names_the_package_when_wmctrl_is_missing():
    with pytest.raises(ValueError, match='apt install wmctrl'):
        demo.check_placement_prerequisites(str(CONFIG / 'demo_layout.yaml'),
                                           _fake(wmctrl_ok=False), X11)


def test_placement_preflight_refuses_a_monitor_that_is_not_connected():
    with pytest.raises(ValueError, match='HDMI-0'):
        demo.check_placement_prerequisites(
            str(CONFIG / 'demo_layout.yaml'),
            _fake(' 0: +*DP-2 1920/1x1080/1+0+0  DP-2\n'), X11)


def test_placement_preflight_refuses_a_malformed_layout(tmp_path):
    path = tmp_path / 'layout.yaml'
    path.write_text('windows: []\n')
    with pytest.raises(ValueError, match='layout_config'):
        demo.check_placement_prerequisites(str(path), _fake(), X11)


# --- the launch description ---------------------------------------------------------

DEFAULTS = {
    'boats': '', 'roster_file': str(CONFIG / 'demo_roster.yaml'),
    'joystick_config': str(CONFIG / 'demo_joysticks.yaml'), 'enable_joysticks': 'false',
    'layout_config': str(CONFIG / 'demo_layout.yaml'),
    'camp_profile': str(CONFIG / 'demo_camp_profile.conf'),
    'camp_view_config': str(CONFIG / 'demo_camp_view.yaml'), 'target_area_file': '',
    'enable_boats': 'true', 'enable_camp': 'true', 'enable_scorer': 'true',
    'enable_target_area': 'false', 'enable_window_layout': 'false',
}


@pytest.fixture(autouse=True)
def _release_locks():
    demo.release_demo_locks()
    yield
    demo.release_demo_locks()


def _setup(monkeypatch, tmp_path, **overrides):
    monkeypatch.setenv('HOME', str(tmp_path))
    # The machine running the tests may have its own CAMP open.
    monkeypatch.setattr(demo, 'running_camp_pids', lambda *a, **k: [])
    demo.release_demo_locks()
    context = LaunchContext()
    for name, value in {**DEFAULTS, **overrides}.items():
        context.launch_configurations[name] = value
    return demo.launch_setup(context)


def _kinds(actions):
    return sorted(type(a).__name__ for a in actions)


def _includes(actions):
    return [a for a in actions if isinstance(a, IncludeLaunchDescription)]


def test_every_launch_argument_the_setup_reads_is_declared():
    declared = {a.name for a in demo.generate_launch_description().entities
                if hasattr(a, 'default_value')}
    assert declared == set(DEFAULTS)


def test_the_display_is_on_by_default_except_the_unfinished_target_area():
    defaults = {a.name: ''.join(s.perform(LaunchContext()) for s in a.default_value)
                for a in demo.generate_launch_description().entities
                if hasattr(a, 'default_value') and a.name.startswith('enable_')}
    assert defaults == {'enable_boats': 'true', 'enable_camp': 'true', 'enable_scorer': 'true',
                        'enable_joysticks': 'true', 'enable_target_area': 'false',
                        'enable_window_layout': 'true'}


def _perform(substitutions):
    if isinstance(substitutions, str):
        return substitutions
    return ''.join(s.perform(LaunchContext()) if hasattr(s, 'perform') else str(s)
                   for s in substitutions)


def _camp(actions):
    return [a for a in actions if getattr(a, 'node_package', '') == 'camp']


def _arguments(node):
    # launch_ros keeps the arguments private until the action runs.
    return [_perform(a) for a in node._Node__arguments or []]


@needs_camp
@needs_scorer
def test_everything_enabled_gives_boats_scorer_and_camp(monkeypatch, tmp_path):
    actions = _setup(monkeypatch, tmp_path)
    assert len(_includes(actions)) == 2
    assert len(_camp(actions)) == 1
    conf = pathlib.Path(demo.settings_root(str(tmp_path)), 'UNH-CCOMJHC',
                        'CCOMAutonomousMissionPlanner.conf')
    assert conf.is_file()


@needs_camp
@needs_scorer
def test_camp_gets_the_demo_settings_directory(monkeypatch, tmp_path):
    camp = _camp(_setup(monkeypatch, tmp_path))[0]
    env = {_perform(k): _perform(v) for k, v in camp.additional_env}
    assert env == {'XDG_CONFIG_HOME': demo.settings_root(str(tmp_path))}


@needs_camp
def test_camp_opens_the_target_file_when_one_is_given(monkeypatch, tmp_path):
    target = tmp_path / 'target.json'
    target.write_text('{}')
    target_off = {'enable_boats': 'false', 'enable_scorer': 'false'}
    camp = _camp(_setup(monkeypatch, tmp_path, target_area_file=str(target), **target_off))[0]
    assert str(target) in _arguments(camp)
    plain = _camp(_setup(monkeypatch, tmp_path, **target_off))[0]
    assert str(target) not in _arguments(plain)


@needs_camp
@needs_scorer
@pytest.mark.parametrize('switch, expect_includes, expect_camp', [
    ('enable_boats', 1, True), ('enable_scorer', 1, True), ('enable_camp', 2, False)])
def test_each_switch_removes_only_its_part(monkeypatch, tmp_path, switch, expect_includes,
                                           expect_camp):
    actions = _setup(monkeypatch, tmp_path, **{switch: 'false'})
    assert len(_includes(actions)) == expect_includes
    assert bool([a for a in actions if getattr(a, 'node_package', '') == 'camp']) == expect_camp


def test_everything_off_is_empty(monkeypatch, tmp_path):
    assert _setup(monkeypatch, tmp_path, enable_boats='false', enable_camp='false',
                  enable_scorer='false') == []


@needs_camp
def test_a_boat_subset_reaches_the_profile_and_the_scorer(monkeypatch, tmp_path, roster):
    first = roster[0].name
    _setup(monkeypatch, tmp_path, boats=first, enable_boats='false',
           enable_scorer='true' if _installed('coverage_assessment') else 'false')
    conf = pathlib.Path(demo.settings_root(str(tmp_path)), 'UNH-CCOMJHC',
                        'CCOMAutonomousMissionPlanner.conf').read_text()
    assert demo.live_layer_key(first) in conf
    for other in roster[1:]:
        assert demo.live_layer_key(other.name) not in conf


def test_a_bad_switch_value_is_refused(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match='enable_camp'):
        _setup(monkeypatch, tmp_path, enable_camp='ture')


def test_an_unknown_boat_is_refused(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match='unknown boat'):
        _setup(monkeypatch, tmp_path, boats='nosuchboat')


def test_target_area_is_refused_until_it_is_installed(monkeypatch, tmp_path):
    target = tmp_path / 'target.json'
    target.write_text('{}')
    monkeypatch.setattr(demo, 'target_script_installed', lambda: False)
    with pytest.raises(ValueError, match='#93'):
        _setup(monkeypatch, tmp_path, enable_target_area='true', target_area_file=str(target),
               enable_boats='false', enable_camp='false', enable_scorer='false')


def test_window_layout_on_wayland_is_refused_before_anything_starts(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    with pytest.raises(ValueError, match='X11'):
        _setup(monkeypatch, tmp_path, enable_window_layout='true')


# --- review round 1: target file, running CAMP, lock, cache, shutdown ---------------

def test_a_target_file_that_does_not_exist_is_refused_even_with_the_publisher_off(
        monkeypatch, tmp_path):
    with pytest.raises(ValueError, match='target_area_file'):
        _setup(monkeypatch, tmp_path, target_area_file=str(tmp_path / 'typo.json'),
               enable_boats='false', enable_camp='false', enable_scorer='false')


@needs_camp
def test_the_target_file_reaches_camp_as_an_absolute_path(monkeypatch, tmp_path):
    (tmp_path / 'target.json').write_text('{}')
    monkeypatch.chdir(tmp_path)
    camp = _camp(_setup(monkeypatch, tmp_path, target_area_file='target.json',
                        enable_boats='false', enable_scorer='false'))[0]
    assert str(tmp_path / 'target.json') in _arguments(camp)


def _fake_proc(tmp_path, commands):
    root = tmp_path / 'proc'
    root.mkdir()
    for pid, argv in commands.items():
        (root / str(pid)).mkdir()
        (root / str(pid) / 'cmdline').write_bytes(b'\0'.join(a.encode() for a in argv) + b'\0')
    (root / 'self').mkdir()  # not a process id
    return str(root)


def test_a_running_camp_is_found_by_its_executable_name(tmp_path):
    proc = _fake_proc(tmp_path, {
        10: ['/opt/ros/lib/camp/CCOMAutonomousMissionPlanner', '/ws/'],
        11: ['/usr/bin/python3', 'CCOMAutonomousMissionPlanner.py'],
        12: ['bash', '-c', 'echo CCOMAutonomousMissionPlanner']})
    assert demo.running_camp_pids(proc) == [10]
    with pytest.raises(ValueError, match='already running.*10'):
        demo.refuse_running_camp(proc)


def test_no_camp_running_is_fine(tmp_path):
    proc = _fake_proc(tmp_path, {5: ['bash']})
    assert demo.running_camp_pids(proc) == []
    demo.refuse_running_camp(proc)


@needs_camp
def test_the_launch_refuses_to_start_next_to_a_running_camp(monkeypatch, tmp_path):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setattr(demo, 'running_camp_pids', lambda *a, **k: [4242])
    context = LaunchContext()
    for name, value in {**DEFAULTS, 'enable_boats': 'false', 'enable_scorer': 'false'}.items():
        context.launch_configurations[name] = value
    with pytest.raises(ValueError, match='4242'):
        demo.launch_setup(context)


def test_a_second_demo_is_refused_while_the_first_holds_the_lock(tmp_path):
    demo.acquire_demo_lock(str(tmp_path))
    with pytest.raises(ValueError, match='already running'):
        demo.acquire_demo_lock(str(tmp_path))
    demo.release_demo_locks()
    demo.acquire_demo_lock(str(tmp_path))  # free again


@needs_scorer
def test_launch_setup_takes_the_lock_before_touching_the_state(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, enable_boats='false', enable_camp='false')
    state = pathlib.Path(demo.state_dir(str(tmp_path)))
    marker = state / 'run' / 'coverage_assessment.yaml'
    assert marker.is_file()
    with pytest.raises(ValueError, match='already running'):
        demo.acquire_demo_lock(str(state))  # the launch holds it
    assert marker.is_file()  # and the failed second launch deleted nothing


def test_qt_strings_match_what_qt_writes(tmp_path):
    qtcore = pytest.importorskip('PyQt5.QtCore')
    for number, text in enumerate([
            '/home/roland/.local/state/x', '/with space/and,comma', '/semi;colon', 'a=b',
            ' lead', 'trail ', 'say "hi"', 'back\\slash', 'plain']):
        path = str(tmp_path / ('q%d.conf' % number))
        settings = qtcore.QSettings(path, qtcore.QSettings.IniFormat)
        settings.setValue('LiveTileCache/cache_dir', text)
        settings.sync()
        line = [row for row in open(path).read().splitlines()
                if row.startswith('cache_dir=')][0]
        assert line == 'cache_dir=' + demo.qt_ini_string(text), text
        reread = qtcore.QSettings(path, qtcore.QSettings.IniFormat)
        assert reread.value('LiveTileCache/cache_dir') == text


def test_the_profile_points_camps_tile_cache_at_the_demo_directory(tmp_path):
    template = (CONFIG / 'demo_camp_profile.conf').read_text()
    text = demo.build_profile(template, [_boat('one')], 43.0, -70.0, 1.0,
                              str(tmp_path / 'cache dir'))
    cache = str(tmp_path / 'cache dir')
    assert demo.parse_profile(text)['LiveTileCache'] == ['cache_dir=' + cache]
    with pytest.raises(ValueError, match='LiveTileCache'):
        demo.build_profile('[LiveTileCache]\nx=1\n', [_boat('one')], 43.0, -70.0, 1.0)


@needs_camp
def test_the_tile_cache_is_emptied_on_every_start(monkeypatch, tmp_path):
    kwargs = {'enable_boats': 'false', 'enable_scorer': 'false'}
    _setup(monkeypatch, tmp_path, **kwargs)
    cache = pathlib.Path(demo.cache_dir(str(tmp_path)))
    (cache / 'old_tile.bin').write_text('x')
    _setup(monkeypatch, tmp_path, **kwargs)
    assert not (cache / 'old_tile.bin').exists() and (cache / demo.ROOT_MARKER).is_file()


def test_state_directories_other_than_the_demos_are_never_reset(tmp_path):
    other = tmp_path / 'elsewhere'
    other.mkdir()
    with pytest.raises(ValueError, match='refusing'):
        demo.reset_state_dir(str(other), demo.CACHE_DIR_NAME, str(tmp_path))
    with pytest.raises(ValueError, match='refusing'):  # the cache path is not the config one
        demo.reset_state_dir(demo.cache_dir(str(tmp_path)), demo.SETTINGS_ROOT_NAME,
                             str(tmp_path))


@pytest.mark.parametrize('body, message', [
    ('camp_view: {scale: "1"}\n', 'finite number'),
    ('camp_view: {scale: true}\n', 'finite number'),
    ('camp_view: {scale: 0}\n', 'greater than zero'),
    ('camp_view: {scale: -2}\n', 'outside'),
    ('camp_view: {scale: .nan}\n', 'finite'),
    ('camp_view: {scale: 1, lat: 90, lon: 0}\n', 'outside'),
    ('camp_view: {scale: 1, lat: 43, lon: 181}\n', 'outside'),
    ('camp_view: {scale: 1, lat: "43", lon: 0}\n', 'finite number'),
])
def test_view_config_checks_types_and_ranges(tmp_path, body, message):
    path = tmp_path / 'view.yaml'
    path.write_text(body)
    with pytest.raises(ValueError, match=message):
        demo.load_view(str(path))


def test_view_config_accepts_an_explicit_centre(tmp_path):
    path = tmp_path / 'view.yaml'
    path.write_text('camp_view: {scale: 2, lat: 43.07, lon: -70.71}\n')
    assert demo.load_view(str(path)) == {'scale': 2.0, 'lat': 43.07, 'lon': -70.71}


# --- closing the CAMP window stops the whole demo (owner requirement, 2026-10-14) -----

def _handlers(actions):
    return [a.event_handler for a in actions if isinstance(a, RegisterEventHandler)]


def _exited(action, returncode=0):
    return ProcessExited(action=action, name='x', cmd=[], cwd=None, env=None,
                         returncode=returncode, pid=1)


@needs_camp
def test_closing_camp_shuts_the_whole_launch_down(monkeypatch, tmp_path):
    actions = _setup(monkeypatch, tmp_path, enable_boats='false', enable_scorer='false')
    camp = _camp(actions)[0]
    handlers = [h for h in _handlers(actions) if h.matches(_exited(camp))]
    assert len(handlers) == 1
    entities = handlers[0].handle(_exited(camp), LaunchContext())
    shutdowns = [e for e in entities if isinstance(e, EmitEvent)
                 and isinstance(e.event, Shutdown)]
    assert len(shutdowns) == 1 and 'CAMP' in shutdowns[0].event.reason


@needs_camp
def test_camp_crashing_also_stops_the_demo_and_other_exits_do_not(monkeypatch, tmp_path):
    actions = _setup(monkeypatch, tmp_path, enable_boats='false', enable_scorer='false')
    camp = _camp(actions)[0]
    assert any(h.matches(_exited(camp, returncode=-11)) for h in _handlers(actions))
    other = demo.placement_process('/x.yaml')
    assert not any(h.matches(_exited(other)) for h in _handlers(actions))


def test_without_camp_nothing_shuts_the_demo_down(monkeypatch, tmp_path):
    actions = _setup(monkeypatch, tmp_path, enable_boats='false', enable_camp='false',
                     enable_scorer='false')
    assert _handlers(actions) == []


def test_a_failed_placement_is_announced_and_a_good_one_is_quiet():
    class Event:

        def __init__(self, returncode):
            self.returncode = returncode

    assert demo.placement_exit(Event(0), None) == []
    banner = demo.placement_exit(Event(1), None)
    assert len(banner) == 1 and 'NOT IN PLACE' in _perform(banner[0].msg)


def test_the_handler_really_stops_a_running_launch_when_camp_exits():
    # A real LaunchService run: a short-lived process stands in for the CAMP window
    # being closed, a long one for the boats. The launch must end well before it.
    camp = ExecuteProcess(cmd=['sleep', '1'])
    boats = ExecuteProcess(cmd=['sleep', '60'])
    service = LaunchService()
    service.include_launch_description(
        LaunchDescription([boats, camp, *demo.camp_exit_handlers(camp)]))
    started = time.monotonic()
    assert service.run() == 0
    assert time.monotonic() - started < 30


def test_the_state_directory_is_private_and_an_empty_fleet_is_refused(tmp_path):
    state = tmp_path / 'state'
    demo.acquire_demo_lock(str(state))
    assert (state.stat().st_mode & 0o777) == 0o700
    with pytest.raises(ValueError):
        demo.view_center([])
