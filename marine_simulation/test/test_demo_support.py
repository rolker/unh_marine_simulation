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
Unit tests for ``marine_simulation.demo_support``, the helpers the demo manager shares.

CAMP's settings profile and the Qt encodings, the state directory guards, the one-demo lock,
the scorer parameters and the CAMP start actions. Boat names come from the shipped roster (or
are synthetic), never quoted.
"""

import os
import pathlib
import random
import re

from ament_index_python.packages import get_package_share_directory, PackageNotFoundError
from launch import LaunchContext
from launch.actions import LogInfo
from marine_simulation import demo_support as demo
from marine_simulation import roster as roster_module
import pytest
import yaml

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
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


POLYGON = str(CONFIG / 'demo_target_polygon_camp.json')


def _boat(name, index=0, lat=43.0, lon=-70.7):
    return roster_module.Boat(name=name, pad='x', color=(1.0, 1.0, 1.0), lat=lat, lon=lon,
                              heading=0.0, index=index)


@pytest.fixture
def roster():
    return roster_module.load_roster(str(CONFIG / 'demo_roster.yaml'))


@pytest.fixture(autouse=True)
def _release_locks():
    demo.release_demo_locks()
    yield
    demo.release_demo_locks()


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


def test_shipped_view_config_is_an_empty_override_so_the_view_is_fitted():
    assert demo.load_view(str(CONFIG / 'demo_camp_view.yaml')) == {}


@pytest.mark.parametrize('body', [
    'camp_view: {lat: 43.0, lon: -70.0}\n', 'camp_view: {scale: 1, lat: 43.0}\n',
    'camp_view: {scale: 1, zoom: 2}\n',
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


def test_a_second_demo_is_refused_while_the_first_holds_the_lock(tmp_path):
    demo.acquire_demo_lock(str(tmp_path))
    with pytest.raises(ValueError, match='already running'):
        demo.acquire_demo_lock(str(tmp_path))
    demo.release_demo_locks()
    demo.acquire_demo_lock(str(tmp_path))  # free again


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


def _perform(substitutions):
    if isinstance(substitutions, str):
        return substitutions
    return ''.join(s.perform(LaunchContext()) if hasattr(s, 'perform') else str(s)
                   for s in substitutions)


def test_a_failed_placement_is_announced_and_a_good_one_is_quiet():
    class Event:

        def __init__(self, returncode):
            self.returncode = returncode

    assert demo.placement_exit(Event(0), None) == []
    banner = demo.placement_exit(Event(1), None)
    assert len(banner) == 1 and 'NOT IN PLACE' in _perform(banner[0].msg)


def test_the_state_directory_is_private_and_an_empty_fleet_is_refused(tmp_path):
    state = tmp_path / 'state'
    demo.acquire_demo_lock(str(state))
    assert (state.stat().st_mode & 0o777) == 0o700
    with pytest.raises(ValueError):
        demo.view_center([])


def test_camp_actions_seed_the_private_settings_and_empty_the_tile_cache(
        monkeypatch, tmp_path, roster):
    monkeypatch.setenv('HOME', str(tmp_path))
    started = []
    monkeypatch.setattr(demo, 'camp_node', lambda home, project='': started.append(
        (home, project)) or 'camp-node')
    cache = pathlib.Path(demo.cache_dir(str(tmp_path)))
    cache.mkdir(parents=True)
    (cache / demo.ROOT_MARKER).write_text('x')
    (cache / 'old_tile.bin').write_text('old session')

    def start(target=''):
        return demo.camp_actions(roster, str(CONFIG / 'demo_camp_profile.conf'),
                                 str(CONFIG / 'demo_camp_view.yaml'), target,
                                 CAMP_LAYOUT)

    actions = start(POLYGON)
    assert started == [(demo.settings_root(str(tmp_path)), POLYGON)]
    assert actions[-1] == 'camp-node'
    assert any(isinstance(a, LogInfo) and 'CAMP map view' in ''.join(
        getattr(part, 'text', '') for part in a.msg) for a in actions)
    conf = pathlib.Path(demo.settings_root(str(tmp_path)), 'UNH-CCOMJHC',
                        'CCOMAutonomousMissionPlanner.conf').read_text()
    assert 'cache_dir=' in conf and demo.cache_dir(str(tmp_path)) in conf
    for boat in roster:
        assert demo.live_layer_key(boat.name) + '\\live_enabled=true' in conf
    assert not (cache / 'old_tile.bin').exists() and (cache / demo.ROOT_MARKER).is_file()


def test_camp_actions_refuse_a_missing_profile(tmp_path, roster):
    with pytest.raises(ValueError, match='camp_profile'):
        demo.camp_actions(roster, str(tmp_path / 'nope.conf'),
                          str(CONFIG / 'demo_camp_view.yaml'))


def test_the_target_area_node_is_the_publisher_script():
    node = demo.target_area_node('/some/target.json')
    assert node.node_package == 'marine_simulation'
    assert node.node_executable == demo.TARGET_AREA_EXECUTABLE == 'publish_survey_area.py'
    assert _perform(node._Node__node_name) == demo.TARGET_AREA_NODE_NAME
    assert not demo.target_area_node('')._Node__parameters


def test_the_target_area_script_is_installed_with_the_package():
    from ament_index_python.packages import get_package_prefix
    assert os.path.isfile(os.path.join(get_package_prefix('marine_simulation'), 'lib',
                                       'marine_simulation', demo.TARGET_AREA_EXECUTABLE))


def test_placement_actions_run_the_process_and_watch_its_exit():
    from launch.actions import ExecuteProcess, RegisterEventHandler
    process, handler = demo.placement_actions('/my/layout.yaml')
    assert isinstance(process, ExecuteProcess) and isinstance(handler, RegisterEventHandler)


DECLARED = ['boats', 'roster_file', 'tide_speed_factor', 'cell_size']
OWNED = ['boats', 'roster_file']


def test_launch_arguments_are_parsed_to_a_dict():
    assert demo.parse_launch_arguments(['tide_speed_factor:=1', 'cell_size:=a=b'],
                                       DECLARED, OWNED) == {
        'tide_speed_factor': '1', 'cell_size': 'a=b'}
    assert demo.parse_launch_arguments([], DECLARED, OWNED) == {}
    assert demo.parse_launch_arguments(['cell_size:='], DECLARED, OWNED) == {'cell_size': ''}


@pytest.mark.parametrize('item, message', [
    ('tide_speed:=1', 'not an argument of the boats launch.*cell_size, tide_speed_factor'),
    ('boats:=a', 'set by the demo'),
    ('cell_size', 'name:=value'),
    (':=1', 'name:=value'),
    ('1x:=1', 'name:=value'),
])
def test_bad_launch_arguments_are_refused_with_the_reason(item, message):
    with pytest.raises(ValueError, match=message):
        demo.parse_launch_arguments([item], DECLARED, OWNED)


def test_the_demo_scores_on_a_two_metre_lattice_whatever_the_example_says():
    assert demo.DEMO_SCORER_CELL_SIZE == 2.0
    out = demo.scorer_parameters(TEMPLATE, [_boat('one')])        # the template says 1.0
    assert out['/**/coverage_assessment']['ros__parameters']['cell_size'] == 2.0
    assert TEMPLATE['/**/coverage_assessment']['ros__parameters']['cell_size'] == 1.0


def _lattice_cells(points, cell_size):
    """Return the scorer's bounding-box lattice cell count for (lat, lon) ``points``."""
    import math
    lats = [lat for lat, _ in points]
    lons = [lon for _, lon in points]
    north = (max(lats) - min(lats)) * 111320.0
    east = (max(lons) - min(lons)) * 111320.0 * math.cos(math.radians(sum(lats) / len(lats)))
    return (north / cell_size) * (east / cell_size)


def _shipped_polygon():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'publish_survey_area_for_test', str(PACKAGE / 'scripts' / 'publish_survey_area.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_survey_areas(str(CONFIG / 'demo_target_polygon_camp.json'))


@needs_scorer
def test_the_shipped_target_polygon_fits_the_scorers_raster_limit(tmp_path, roster):
    """The scorer rejects an area over max_raster_cells: found at the first real CAMP run."""
    template = os.path.join(get_package_share_directory('coverage_assessment'),
                            'config', 'coverage_assessment.yaml')
    params = yaml.safe_load(open(demo.write_scorer_parameters(
        template, roster, str(tmp_path))))['/**/coverage_assessment']['ros__parameters']
    areas = _shipped_polygon()
    assert areas, 'the shipped target has no survey area'
    for label, points in areas:
        cells = _lattice_cells(points, params['cell_size'])
        assert cells < params['max_raster_cells'], (
            '%s spans about %.0f lattice cells at %s m; the scorer refuses over %s'
            % (label, cells, params['cell_size'], params['max_raster_cells']))


def test_the_limit_check_would_have_caught_the_one_metre_failure():
    (label, points), = _shipped_polygon()
    # what the scorer logged at 1 m: 2.49846e+06 cells (the estimate is within 0.1 %)
    assert abs(_lattice_cells(points, 1.0) - 2.49846e6) < 2.5e3
    assert _lattice_cells(points, 1.0) > 1000000 > _lattice_cells(points, 2.0)


# --- the starting view is fitted to the target polygon -----------------------------------

BIG_SCREEN = (3840, 2160)          # HDMI-0 of the demo computer


def _polygon_points():
    (label, points), = _shipped_polygon()
    return points


def _bounds(points):
    lats = [lat for lat, _ in points]
    lons = [lon for _, lon in points]
    return min(lats), min(lons), max(lats), max(lons)


def test_the_fitted_view_contains_every_vertex_with_a_margin_on_the_big_screen():
    points = _polygon_points()
    lat, lon, scale = demo.fit_view(_bounds(points), BIG_SCREEN)
    cx, cy = demo.web_mercator(lat, lon)
    view_width = BIG_SCREEN[0] * (1 - demo.PANEL_WIDTH_FRACTION)
    view_height = BIG_SCREEN[1] - demo.CHROME_HEIGHT_PIXELS
    for vertex in points:
        x, y = demo.web_mercator(*vertex)
        assert abs(x - cx) * scale <= 0.45 * view_width, vertex
        assert abs(y - cy) * scale <= 0.45 * view_height, vertex
    assert demo.MIN_CAMP_SCALE < scale <= demo.MAX_CAMP_SCALE


def test_the_fit_is_centred_on_the_polygon_and_tight_in_the_limiting_direction():
    points = _polygon_points()
    lat, lon, scale = demo.fit_view(_bounds(points), BIG_SCREEN)
    xs, ys = zip(*(demo.web_mercator(*p) for p in points))
    cx, cy = demo.web_mercator(lat, lon)
    assert cx == pytest.approx((min(xs) + max(xs)) / 2, abs=0.01)
    assert cy == pytest.approx((min(ys) + max(ys)) / 2, abs=0.01)
    view_width = BIG_SCREEN[0] * (1 - demo.PANEL_WIDTH_FRACTION)
    extent_px = max((max(xs) - min(xs)) * scale / view_width,
                    (max(ys) - min(ys)) * scale / (BIG_SCREEN[1] - demo.CHROME_HEIGHT_PIXELS))
    assert extent_px == pytest.approx(1 / (1 + 2 * demo.FIT_MARGIN))     # margin each side


def test_a_smaller_window_zooms_out_so_the_polygon_still_fits():
    bounds = _bounds(_polygon_points())
    assert demo.fit_view(bounds, (1600, 900))[2] < demo.fit_view(bounds, BIG_SCREEN)[2]


def test_the_inverse_projection_round_trips():
    for lat, lon in [(43.07, -70.71), (-33.0, 151.2), (0.0, 0.0)]:
        back = demo.inverse_web_mercator(*demo.web_mercator(lat, lon))
        assert back == pytest.approx((lat, lon), abs=1e-9)


@pytest.mark.parametrize('bounds', [(43.0, -70.0, 43.0, -70.0),            # one vertex
                                    (43.0, -70.0, 43.0, -69.99),           # a line, east-west
                                    (43.0, -70.0, 43.01, -70.0)])          # a line, north-south
def test_a_target_without_extent_is_refused_plainly(bounds):
    with pytest.raises(ValueError, match='no extent to fit the map view to'):
        demo.fit_view(bounds, BIG_SCREEN)


def test_a_window_too_small_for_the_panel_and_bars_is_refused():
    with pytest.raises(ValueError, match='too small'):
        demo.fit_view(_bounds(_polygon_points()), (1000, 150))


def test_the_shipped_polygons_bounds_come_from_the_publisher(tmp_path):
    lat0, lon0, lat1, lon1 = demo.target_bounds(POLYGON, str(PACKAGE / 'scripts' /
                                                             'publish_survey_area.py'))
    assert (lat0, lon0, lat1, lon1) == pytest.approx(_bounds(_polygon_points()), abs=1e-8)


def test_target_bounds_report_a_bad_file_plainly(tmp_path):
    bad = tmp_path / 'bad.json'
    bad.write_text('{ nope')
    with pytest.raises(ValueError, match='target area file cannot be used.*not valid JSON'):
        demo.target_bounds(str(bad), str(PACKAGE / 'scripts' / 'publish_survey_area.py'))
    with pytest.raises(ValueError, match='cannot run'):
        demo.target_bounds(str(bad), str(tmp_path / 'missing'))


CAMP_LAYOUT = str(pathlib.Path(__file__).resolve().parent / 'camp_maximized_layout.yaml')
XRANDR_BIG = (' 0: +*HDMI-0 3840/800x2160/450+0+240  HDMI-0\n'
              ' 1: +DP-2 1920/519x1200/320+4966+0  DP-2\n')


def test_the_window_size_is_the_monitor_of_the_layouts_camp_entry():
    size, note = demo.camp_window_size(CAMP_LAYOUT, lambda c: XRANDR_BIG)
    assert size == BIG_SCREEN and 'HDMI-0' in note


def test_a_rect_entry_gives_the_rect_size(tmp_path):
    layout = tmp_path / 'layout.yaml'
    layout.write_text(
        'windows:\n  - name: camp\n    match: {wm_class: CCOMAutonomousMissionPlanner}\n'
        '    monitor: HDMI-0\n    rect: {x: 0, y: 0, width: 1600, height: 900}\n')
    assert demo.camp_window_size(str(layout), lambda c: 1 / 0)[0] == (1600, 900)


@pytest.mark.parametrize('xrandr, layout_text', [
    (' 1: +DP-2 1920/519x1200/320+4966+0  DP-2\n', None),        # monitor not connected
    ('', None),
    (XRANDR_BIG, 'windows: []\n'),                                # no CAMP entry
    (XRANDR_BIG, 'nonsense'),
])
def test_an_unreadable_window_size_is_none_with_a_reason(tmp_path, xrandr, layout_text):
    layout = pathlib.Path(CAMP_LAYOUT)
    if layout_text is not None:
        layout = tmp_path / 'layout.yaml'
        layout.write_text(layout_text)
    size, note = demo.camp_window_size(str(layout), lambda c: xrandr)
    assert size is None and note


def test_a_missing_layout_file_or_xrandr_is_none_with_a_reason(tmp_path):
    assert demo.camp_window_size(str(tmp_path / 'nope.yaml'))[0] is None

    def boom(command):
        raise OSError('xrandr: not found')
    size, note = demo.camp_window_size(CAMP_LAYOUT, boom)
    assert size is None and 'xrandr' in note


def _start_view(view, target=POLYGON, layout=None, runner=lambda c: XRANDR_BIG, boats=None):
    return demo.camp_start_view(boats or [_boat('one', lat=43.0, lon=-70.0)], view, target,
                                layout or CAMP_LAYOUT,
                                str(PACKAGE / 'scripts' / 'publish_survey_area.py'), runner)


def test_without_an_override_the_view_is_fitted_to_the_polygon_on_the_big_screen():
    lat, lon, scale, how = _start_view({})
    assert (lat, lon, scale) == pytest.approx(demo.fit_view(_bounds(_polygon_points()),
                                                            BIG_SCREEN))
    assert 'fitted' in how and '3840x2160' in how and 'HDMI-0' in how


def test_an_explicit_view_is_used_verbatim_and_the_polygon_is_not_even_read():
    assert _start_view({'scale': 0.7, 'lat': 43.5, 'lon': -70.5}, target='/nope.json')[:3] == (
        43.5, -70.5, 0.7)
    lat, lon, scale, how = _start_view({'scale': 0.7}, target='')      # boats' centre
    assert (lat, lon, scale) == (43.0, -70.0, 0.7) and 'explicit' in how


def test_an_unreadable_window_falls_back_to_a_named_size():
    lat, lon, scale, how = _start_view({}, runner=lambda c: '')
    assert scale == pytest.approx(demo.fit_view(_bounds(_polygon_points()),
                                                demo.FALLBACK_WINDOW)[2])
    assert 'assuming a 1920x1080 window' in how


def test_without_a_target_the_view_is_the_boats_at_a_fixed_scale():
    lat, lon, scale, how = _start_view({}, target='')
    assert (lat, lon, scale) == (43.0, -70.0, demo.UNFITTED_SCALE) and 'no target' in how


@pytest.mark.parametrize('wm_class', ['CCOMAutonomousMissionPlanner', 'CCOM', 'Planner'])
def test_the_camp_entry_is_found_the_way_place_windows_matches(wm_class):
    entries = [{'match': {'wm_class': 'other'}}, {'match': {'wm_class': wm_class}, 'n': 1}]
    assert demo._camp_layout_entry(entries)['n'] == 1


def test_a_lone_title_only_entry_is_taken_for_camps_and_two_are_ambiguous():
    assert demo._camp_layout_entry([{'match': {'title': 'Mission'}}]) is not None
    assert demo._camp_layout_entry([{'match': {'title': 'a'}}, {'match': {'title': 'b'}}]) is None


def test_layout_file_problems_are_named(tmp_path):
    assert 'cannot read' in demo.camp_window_size(str(tmp_path))[1]
    bad = tmp_path / 'l.yaml'
    bad.write_text('windows: 3\n')
    assert 'no list of windows' in demo.camp_window_size(str(bad))[1]


def test_the_scale_is_clamped_to_camps_limits():
    tiny = (43.0, -70.0, 43.00001, -69.99999)
    assert demo.fit_view(tiny, BIG_SCREEN)[2] == demo.MAX_CAMP_SCALE


def test_camp_actions_fit_the_view_to_the_polygon_in_the_settings_it_writes(
        monkeypatch, tmp_path, roster):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setattr(demo, 'camp_node', lambda home, project='': 'camp-node')
    monkeypatch.setattr(demo, 'camp_window_size', lambda layout, runner=None: (BIG_SCREEN, 'x'))
    demo.camp_actions(roster, str(CONFIG / 'demo_camp_profile.conf'),
                      str(CONFIG / 'demo_camp_view.yaml'), POLYGON,
                      CAMP_LAYOUT)
    conf = pathlib.Path(demo.settings_root(str(tmp_path)), 'UNH-CCOMJHC',
                        'CCOMAutonomousMissionPlanner.conf').read_text()
    # the publisher prints the bounds to nine decimals, so fit what it prints
    bounds = tuple(round(v, 9) for v in _bounds(_polygon_points()))
    lat, lon, scale = demo.fit_view(bounds, BIG_SCREEN)
    written = float(re.search(r'^mapScale=(\S+)$', conf, re.M).group(1))
    assert written == pytest.approx(scale, rel=1e-6)
    assert demo.qt_point_variant(*demo.web_mercator(lat, lon)) in conf


# --- CAMP remembers its own window and view between starts ------------------------------

# What CAMP's QSettings wrote when it closed maximised: a Qt-escaped byte array (backslashes,
# a doubled quote, parentheses, commas) that must come back byte for byte.
SAVED_GEOMETRY = (r'geometry="@ByteArray(\x1\xd9\xd0\xcb\0\x3\0\0\0\0\0\x42\0\0\xf\xff'
                  r'\0\0\b\x97,\"q\";\0\0\0\0\0\0\0\x18\0\0\xf\xff\0\0\b\x97)"')
SAVED_STATE = r'state="@ByteArray(\0\0\0\xff\0\0\0\0\xfd\0\0\0\x2\0\0\0\0\0\0\x1\x5c)"'
SAVED_CENTER = r'mapCenter="@Variant(\0\0\0\x1a\x41\x8b\xc9\x80\0\0\0\0\xc1\x54\x34\x1\0\0\0\0)"'
SAVED_SCALE = 'mapScale=0.40625'
SAVED_FILE = """[General]
recentProjects=a.json, b.json

[MainWindow]
%s
%s
%s
%s
sidePanelWidth=300

[MapView]
mapView\\center="@Variant(\\0\\0\\0\\x1a\\x41\\x8b)"
mapView\\scale=0.40625

[MapItem]
openstreetmap\\visible=false
somechart\\visible=true
""" % (SAVED_GEOMETRY, SAVED_STATE, SAVED_CENTER, SAVED_SCALE)
PROFILE_TEMPLATE = str(CONFIG / 'demo_camp_profile.conf')


def _write_saved(home, text=SAVED_FILE):
    path = pathlib.Path(demo.camp_settings_path(demo.settings_root(str(home))))
    path.parent.mkdir(parents=True)
    (path.parent.parent / demo.ROOT_MARKER).write_text('x')
    path.write_text(text)
    return path


def test_carry_over_keeps_only_the_window_and_view_lines_exactly_as_written():
    saved = demo.carry_over(SAVED_FILE)
    assert saved['MainWindow'] == [SAVED_GEOMETRY, SAVED_STATE, SAVED_CENTER, SAVED_SCALE]
    assert saved['MapView'] == [
        'mapView\\center="@Variant(\\0\\0\\0\\x1a\\x41\\x8b)"', 'mapView\\scale=0.40625']
    assert set(saved) == {'MainWindow', 'MapView'}          # layers and the rest are not kept


def test_a_half_a_view_is_not_kept_and_a_window_alone_is():
    only_center = '[MainWindow]\n%s\n%s\n[MapView]\nmapView\\scale=1\n' % (
        SAVED_GEOMETRY, SAVED_CENTER)
    saved = demo.carry_over(only_center)
    assert saved == {'MainWindow': [SAVED_GEOMETRY]} and not demo.has_saved_view(saved)
    assert demo.carry_over('[MainWindow]\nsidePanelWidth=3\n') == {}


def test_a_saved_window_and_view_round_trip_through_the_profile_byte_for_byte(roster):
    with open(PROFILE_TEMPLATE) as f:
        template = f.read()
    saved = demo.carry_over(SAVED_FILE)
    profile = demo.build_profile(template, roster, None, None, None, '/cache', saved)
    sections = demo.parse_profile(profile)
    assert sections['MainWindow'] == saved['MainWindow']
    assert sections['MapView'] == saved['MapView']
    assert SAVED_GEOMETRY in profile.splitlines()
    # and what the next start reads back is the same again
    assert demo.carry_over(profile) == saved
    # the layers still come from the template and the boats, not from what CAMP saved
    assert 'somechart' not in profile and 'openstreetmap\\visible=false' not in profile
    assert 'openstreetmap\\visible=true' in profile
    assert 'cache_dir=/cache' in profile


def test_without_a_saved_view_the_view_is_generated_and_a_saved_window_still_kept(roster):
    with open(PROFILE_TEMPLATE) as f:
        template = f.read()
    saved = demo.carry_over('[MainWindow]\n%s\n%s\n' % (SAVED_GEOMETRY, SAVED_STATE))
    profile = demo.build_profile(template, roster, 43.0, -70.0, 0.8, None, saved)
    window = demo.parse_profile(profile)['MainWindow']
    assert window[:2] == [SAVED_GEOMETRY, SAVED_STATE]
    assert any(line.startswith('mapScale=0.8') for line in window)
    assert 'mapView\\scale=0.8' in profile
    with pytest.raises(ValueError, match='view_scale'):
        demo.build_profile(template, roster, 43.0, -70.0, None, None, saved)


def _start_camp(monkeypatch, tmp_path, roster, fresh=False):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setattr(demo, 'camp_node', lambda home, project='': 'camp-node')
    actions = demo.camp_actions(roster, PROFILE_TEMPLATE,
                                str(CONFIG / 'demo_camp_view.yaml'), POLYGON, CAMP_LAYOUT,
                                fresh=fresh)
    conf = pathlib.Path(demo.camp_settings_path(demo.settings_root(str(tmp_path)))).read_text()
    text = [''.join(getattr(part, 'text', '') for part in a.msg)
            for a in actions if isinstance(a, LogInfo)]
    return conf, text


def test_a_start_carries_over_what_camp_saved(monkeypatch, tmp_path, roster):
    _write_saved(tmp_path)
    cache = pathlib.Path(demo.cache_dir(str(tmp_path)))
    cache.mkdir(parents=True)
    (cache / demo.ROOT_MARKER).write_text('x')
    (cache / 'old_tile.bin').write_text('stale coverage')
    conf, text = _start_camp(monkeypatch, tmp_path, roster)
    lines = conf.splitlines()
    assert SAVED_GEOMETRY in lines and SAVED_STATE in lines and SAVED_SCALE in lines
    assert 'mapView\\scale=0.40625' in lines and SAVED_CENTER in lines
    assert any('saved: window, view' in t for t in text)
    assert any('the view CAMP saved' in t for t in text)
    assert 'somechart' not in conf and 'openstreetmap\\visible=false' not in conf   # layers reset
    assert not (cache / 'old_tile.bin').exists()                  # the tile cache is emptied


def test_a_first_start_has_no_geometry_and_the_fitted_view(monkeypatch, tmp_path, roster):
    conf, text = _start_camp(monkeypatch, tmp_path, roster)
    assert 'geometry=' not in conf and 'state=' not in conf
    assert any('nothing saved yet' in t for t in text)
    assert any('fitted' in t for t in text)


def test_fresh_discards_the_saved_window_and_view(monkeypatch, tmp_path, roster):
    _write_saved(tmp_path)
    conf, text = _start_camp(monkeypatch, tmp_path, roster, fresh=True)
    assert 'geometry=' not in conf and 'mapScale=0.40625' not in conf
    assert any('--camp-fresh' in t for t in text) and any('fitted' in t for t in text)


def test_an_unusable_saved_file_makes_it_a_first_start(monkeypatch, tmp_path, roster):
    _write_saved(tmp_path, 'this is not a settings file\n')
    conf, text = _start_camp(monkeypatch, tmp_path, roster)
    assert 'geometry=' not in conf and any('not using' in t for t in text)


def test_a_second_start_restores_what_the_first_one_wrote(monkeypatch, tmp_path, roster):
    first, _ = _start_camp(monkeypatch, tmp_path, roster)
    # CAMP closes maximised, rewriting the file (no comments) with its window and its own view
    path = pathlib.Path(demo.camp_settings_path(demo.settings_root(str(tmp_path))))
    closed = '[MainWindow]\n%s\n%s\n%s\n%s\n' % (
        SAVED_GEOMETRY, SAVED_STATE, SAVED_CENTER, SAVED_SCALE)
    path.write_text(closed)
    second, text = _start_camp(monkeypatch, tmp_path, roster)
    assert demo.parse_profile(second)['MainWindow'] == demo.parse_profile(closed)['MainWindow']
    assert demo.GENERATED_VIEW_MARKER not in second.splitlines()
    assert any('saved: window, view' in t for t in text)


def test_a_view_the_demo_generated_is_not_read_back_after_an_unclean_exit(
        monkeypatch, tmp_path, roster):
    first, _ = _start_camp(monkeypatch, tmp_path, roster)
    assert demo.GENERATED_VIEW_MARKER in first.splitlines()
    # CAMP was killed: the file is still the one the demo wrote, plus whatever it carried
    second, text = _start_camp(monkeypatch, tmp_path, roster)
    assert any('fitted' in t for t in text) and not any('view CAMP saved' in t for t in text)
    assert demo.GENERATED_VIEW_MARKER in second.splitlines()


@pytest.mark.parametrize('scale', ['0', '-1', '', 'nan', 'inf', 'abc'])
def test_a_saved_scale_that_is_not_positive_and_finite_is_not_a_saved_view(scale):
    text = '[MainWindow]\n%s\n%s\nmapScale=%s\n' % (SAVED_GEOMETRY, SAVED_CENTER, scale)
    saved = demo.carry_over(text)
    assert not demo.has_saved_view(saved) and saved == {'MainWindow': [SAVED_GEOMETRY]}
