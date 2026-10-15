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
Tests for scripts/publish_survey_area.py.

The script is loaded by path (it is not an importable package). The parser tests need
no ROS; the node tests run the real node on a private ROS_DOMAIN_ID with localhost-only
discovery and a subscriber that starts after the node has published, with the QoS the
scorer (``coverage_assessment``) uses for ``survey_area``.
"""

import copy
import importlib.util
import json
import math
import os
import pathlib
import time

import pytest

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = PACKAGE / 'scripts' / 'publish_survey_area.py'
DEMO_FILE = PACKAGE / 'config' / 'demo_target_polygon_camp.json'
_spec = importlib.util.spec_from_file_location('publish_survey_area', SCRIPT)
psa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(psa)


def _wp(lat, lon, label='w'):
    return {'type': 'Waypoint', 'label': label, 'latitude': lat, 'longitude': lon}


def _area(label='a0', vertices=((43.0, -70.7), (43.0, -70.6), (43.1, -70.6))):
    return {'type': 'SurveyArea', 'label': label,
            'children': [_wp(lat, lon) for lat, lon in vertices]}


def _project(*children):
    return {'type': 'Group', 'label': 'root', 'children': list(children)}


def _write(tmp_path, project, name='p.json'):
    path = tmp_path / name
    path.write_text(json.dumps(project))
    return str(path)


# ---- parser ----

def test_demo_file_parses():
    areas = psa.load_survey_areas(str(DEMO_FILE))
    assert [label for label, _ in areas] == ['area0000']
    vertices = areas[0][1]
    assert len(vertices) == 10
    assert vertices[0] != vertices[-1]  # the ring is closed implicitly, not repeated
    assert all(43.0 < lat < 43.2 and -70.8 < lon < -70.6 for lat, lon in vertices)


def test_nested_groups_and_waypoint_order():
    inner = _area('deep', ((1.0, 2.0), (3.0, 4.0), (5.0, 6.0)))
    project = _project({'type': 'Group', 'children': [{'type': 'Group', 'children': [inner]}]},
                       _area('top'))
    areas = psa.parse_survey_areas(project)
    assert [label for label, _ in areas] == ['deep', 'top']
    assert areas[0][1] == [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]


def test_non_waypoint_children_are_ignored():
    area = _area()
    area['children'].insert(1, {'type': 'Group', 'children': [_wp(0.0, 0.0)]})
    assert len(psa.parse_survey_areas(_project(area))[0][1]) == 3


def test_unlabelled_area_gets_a_generated_id():
    area = _area()
    del area['label']
    assert psa.parse_survey_areas(_project(area))[0][0] == 'area0000'


@pytest.mark.parametrize('project, text', [
    (_project(), 'no SurveyArea'),
    (_project({'type': 'Waypoint', 'latitude': 1.0, 'longitude': 2.0}), 'no SurveyArea'),
    (_project(_area(vertices=((1.0, 2.0), (3.0, 4.0)))), '2 distinct vertices'),
    (_project(_area(vertices=((1.0, 2.0), (3.0, 4.0), (1.0, 2.0)))), '2 distinct vertices'),
    (_project(_area(vertices=((1.0, 2.0),) * 5)), '1 distinct vertices'),
    (_project(_area(vertices=())), '0 distinct vertices'),
    (_project({'type': 'Group', 'children': 5}), 'not a list'),
    (_project(dict(_area(), children='x')), 'not a list'),
    (_project(_area('x'), _area('x')), 'more than once'),
    ([], 'no SurveyArea'),
    ('text', 'no SurveyArea'),
])
def test_parser_refusals(project, text):
    with pytest.raises(psa.SurveyAreaFileError, match=text):
        psa.parse_survey_areas(project)


@pytest.mark.parametrize('key', ['latitude', 'longitude'])
def test_vertex_without_coordinate_is_refused(key):
    area = _area()
    del area['children'][1][key]
    with pytest.raises(psa.SurveyAreaFileError, match='has no ' + key):
        psa.parse_survey_areas(_project(area))


@pytest.mark.parametrize('lat, lon', [
    ('43.0', -70.0), (43.0, None), (True, -70.0), (91.0, 0.0), (-91.0, 0.0),
    (0.0, 181.0), (0.0, -181.0), (math.nan, 0.0), (0.0, math.inf),
])
def test_bad_coordinates_are_refused(lat, lon):
    area = _area()
    area['children'][2] = _wp(lat, lon)
    with pytest.raises(psa.SurveyAreaFileError, match='waypoint 2'):
        psa.parse_survey_areas(_project(area))


def test_file_refusals(tmp_path):
    with pytest.raises(psa.SurveyAreaFileError, match='file not found'):
        psa.load_survey_areas(str(tmp_path / 'missing.json'))
    with pytest.raises(psa.SurveyAreaFileError, match="'file' parameter is empty"):
        psa.load_survey_areas('')
    bad = tmp_path / 'bad.json'
    bad.write_text('{not json')
    with pytest.raises(psa.SurveyAreaFileError, match='not valid JSON'):
        psa.load_survey_areas(str(bad))
    with pytest.raises(psa.SurveyAreaFileError, match='cannot read'):
        psa.load_survey_areas(str(tmp_path))  # a directory
    path = _write(tmp_path, _project())
    with pytest.raises(psa.SurveyAreaFileError, match=pathlib.Path(path).name):
        psa.load_survey_areas(path)


def test_deep_nesting_does_not_overflow_the_stack():
    node = _area('deep')
    for _ in range(5000):
        node = {'type': 'Group', 'children': [node]}
    assert [label for label, _ in psa.parse_survey_areas(node)] == ['deep']


def test_nesting_too_deep_for_json_is_a_refusal(tmp_path):
    path = tmp_path / 'deep.json'
    path.write_text('[' * 200000)
    with pytest.raises(psa.SurveyAreaFileError, match='nested too deeply|not valid JSON'):
        psa.load_survey_areas(str(path))


def test_oversized_file_is_refused(tmp_path, monkeypatch):
    path = _write(tmp_path, _project(_area()))
    monkeypatch.setattr(psa, 'MAX_FILE_BYTES', 10)
    with pytest.raises(psa.SurveyAreaFileError, match='larger than'):
        psa.load_survey_areas(path)


def test_more_areas_than_the_latched_history_is_refused():
    ok = _project(*[_area('a%d' % i) for i in range(psa.MAX_AREAS)])
    assert len(psa.parse_survey_areas(ok)) == psa.MAX_AREAS
    too_many = _project(*[_area('a%d' % i) for i in range(psa.MAX_AREAS + 1)])
    with pytest.raises(psa.SurveyAreaFileError, match='latched history'):
        psa.parse_survey_areas(too_many)


def test_too_many_vertices_is_refused():
    ring = [(43.0 + i * 1e-5, -70.0) for i in range(psa.MAX_VERTICES + 1)]
    with pytest.raises(psa.SurveyAreaFileError, match='at most'):
        psa.parse_survey_areas(_project(_area(vertices=ring)))


def test_huge_integer_coordinate_is_a_refusal():
    area = _area()
    area['children'][0] = _wp(10 ** 400, 0.0)
    with pytest.raises(psa.SurveyAreaFileError, match='too many digits'):
        psa.parse_survey_areas(_project(area))


@pytest.mark.parametrize('label', [[], {}, 5, None])
def test_non_string_labels_do_not_crash(label):
    area = _area()
    area['label'] = label
    assert psa.parse_survey_areas(_project(area))[0][0] == 'area0000'


def test_generated_label_does_not_collide_with_a_user_label():
    unnamed = _area()
    del unnamed['label']
    areas = psa.parse_survey_areas(_project(unnamed, _area('area0000')))
    assert len({label for label, _ in areas}) == 2


def test_home_directory_is_expanded(tmp_path, monkeypatch):
    _write(tmp_path, _project(_area('home')), 'mine.json')
    monkeypatch.setenv('HOME', str(tmp_path))
    assert psa.load_survey_areas('~/mine.json')[0][0] == 'home'


def test_area_ids():
    two = [('a', []), ('b', [])]
    assert psa.area_ids(two) == ['a', 'b']
    assert psa.area_ids(two[:1], 'custom') == ['custom']
    with pytest.raises(psa.SurveyAreaFileError, match='2 areas'):
        psa.area_ids(two, 'custom')


@pytest.mark.parametrize('a, b', [
    (0.0, 0.0), (-0.1, 0.01), (0.5, -0.01), (math.nan, 0.01), (0.5, math.inf),
])
def test_unset_or_invalid_standard_is_refused(a, b):
    with pytest.raises(psa.SurveyAreaFileError):
        psa.validate_standard(a, b)


def test_standard_accepts_a_or_b_alone_and_the_defaults():
    psa.validate_standard(psa.DEFAULT_STANDARD_A, psa.DEFAULT_STANDARD_B)
    psa.validate_standard(0.5, 0.0)
    psa.validate_standard(0.0, 0.013)


def test_defaults_are_s44_order_1a():
    assert (psa.DEFAULT_STANDARD_A, psa.DEFAULT_STANDARD_B) == (0.5, 0.013)
    assert psa.DEFAULT_STANDARD_NAME == 'demo'


def test_script_is_executable():
    # ros2 run refuses a non-executable script.
    assert os.access(SCRIPT, os.X_OK)


# ---- message and node (need ROS) ----

try:
    import rclpy
except ImportError:  # pragma: no cover (no ROS environment sourced)
    rclpy = None

needs_ros = pytest.mark.skipif(rclpy is None, reason='rclpy is not importable')


@needs_ros
def test_build_survey_areas():
    from builtin_interfaces.msg import Time
    areas = psa.load_survey_areas(str(DEMO_FILE))
    stamp = Time(sec=5, nanosec=6)
    (msg,) = psa.build_survey_areas(areas, ['x'], stamp, 'demo', 0.5, 0.013, 3)
    assert msg.id == 'x'
    assert msg.stamp == stamp
    assert msg.priority == 3
    assert (msg.standard.name, msg.standard.a, msg.standard.b) == ('demo', 0.5, 0.013)
    assert [(p.latitude, p.longitude) for p in msg.polygon.points] == areas[0][1]


@pytest.fixture
def ros_domain(monkeypatch):
    # A domain per test process (1..100), so concurrent runs do not hear each other.
    monkeypatch.setenv('ROS_DOMAIN_ID', str(1 + os.getpid() % 100))
    monkeypatch.setenv('ROS_LOCALHOST_ONLY', '1')
    monkeypatch.setenv('ROS_AUTOMATIC_DISCOVERY_RANGE', 'LOCALHOST')
    yield
    if rclpy.ok():
        rclpy.shutdown()


def _receive(node_args, qos, timeout=10.0):
    """Start the publisher node, then a subscriber, spin both; return what arrived."""
    from marine_interfaces.msg import SurveyArea
    publisher = psa.make_node(['--ros-args'] + node_args)
    listener = rclpy.create_node('survey_area_listener')
    got = []
    listener.create_subscription(SurveyArea, '/survey_area', got.append, qos)
    end = time.monotonic() + timeout
    while not got and time.monotonic() < end:
        rclpy.spin_once(publisher, timeout_sec=0.05)
        rclpy.spin_once(listener, timeout_sec=0.05)
    # Give a second sample, if any, a moment to show up.
    for _ in range(10):
        rclpy.spin_once(listener, timeout_sec=0.05)
    publisher.destroy_node()
    listener.destroy_node()
    return got


@needs_ros
def test_late_subscriber_with_the_scorer_qos_receives_the_area(ros_domain):
    got = _receive(['-p', 'file:=%s' % DEMO_FILE], psa.latched_qos())
    assert len(got) == 1
    assert got[0].id == 'area0000'
    assert len(got[0].polygon.points) == 10
    assert (got[0].standard.name, got[0].standard.a, got[0].standard.b) == (
        'demo', 0.5, 0.013)
    assert got[0].stamp.sec > 0 or got[0].stamp.nanosec > 0


@needs_ros
def test_a_volatile_subscriber_gets_nothing(ros_domain):
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    volatile = QoSProfile(depth=100, reliability=ReliabilityPolicy.RELIABLE,
                          durability=DurabilityPolicy.VOLATILE)
    assert _receive(['-p', 'file:=%s' % DEMO_FILE], volatile, timeout=1.5) == []


@needs_ros
def test_parameters_reach_the_message(tmp_path, ros_domain):
    path = _write(tmp_path, _project(_area('only')))
    got = _receive(['-p', 'file:=' + path, '-p', 'area_id:=mine', '-p', 'priority:=4',
                    '-p', 'standard_name:=tight', '-p', 'standard_a:=0.25',
                    '-p', 'standard_b:=0.0'], psa.latched_qos())
    assert [(m.id, m.priority, m.standard.name, m.standard.a, m.standard.b)
            for m in got] == [('mine', 4, 'tight', 0.25, 0.0)]


@needs_ros
def test_node_refuses_bad_inputs(tmp_path, ros_domain):
    two = _write(tmp_path, _project(_area('a'), _area('b')), 'two.json')
    for args, text in [
            (['-p', 'file:=' + str(tmp_path / 'missing.json')], 'file not found'),
            (['-p', 'file:=' + two, '-p', 'area_id:=x'], '2 areas'),
            (['-p', 'file:=%s' % DEMO_FILE, '-p', 'standard_a:=0.0', '-p', 'standard_b:=0.0'],
             'not set'),
            (['-p', 'file:=%s' % DEMO_FILE, '-p', 'priority:=40000'], 'int16'),
    ]:
        with pytest.raises(psa.SurveyAreaFileError, match=text):
            psa.make_node(['--ros-args'] + args).destroy_node()
        rclpy.shutdown()


@needs_ros
def test_main_exits_nonzero_on_a_refusal(tmp_path, ros_domain, capsys):
    status = psa.main(['--ros-args', '-p', 'file:=' + str(tmp_path / 'nope.json')])
    assert status == 1
    assert 'refused' in capsys.readouterr().err


def test_an_unmodified_fixture_is_not_mutated():
    # parse_survey_areas must not consume or edit its input.
    project = _project(_area())
    before = copy.deepcopy(project)
    psa.parse_survey_areas(project)
    assert project == before


@needs_ros
def test_publisher_offers_reliable_transient_local(ros_domain):
    from rclpy.qos import DurabilityPolicy, ReliabilityPolicy
    assert psa.latched_qos().depth == 100
    node = psa.make_node(['--ros-args', '-p', 'file:=%s' % DEMO_FILE])
    try:
        (info,) = node.get_publishers_info_by_topic('/survey_area')
        assert info.qos_profile.durability == DurabilityPolicy.TRANSIENT_LOCAL
        assert info.qos_profile.reliability == ReliabilityPolicy.RELIABLE
    finally:
        node.destroy_node()


@needs_ros
def test_stamp_is_wall_clock_even_under_sim_time(ros_domain):
    # With use_sim_time and no /clock the node clock reads 0; the stamp must not.
    got = _receive(['-p', 'file:=%s' % DEMO_FILE, '-p', 'use_sim_time:=true'],
                   psa.latched_qos())
    assert len(got) == 1
    assert abs(got[0].stamp.sec - time.time()) < 60


@needs_ros
def test_integer_standard_parameters_are_accepted(ros_domain):
    got = _receive(['-p', 'file:=%s' % DEMO_FILE, '-p', 'standard_a:=1', '-p', 'standard_b:=0'],
                   psa.latched_qos())
    assert [(m.standard.a, m.standard.b) for m in got] == [(1.0, 0.0)]


@needs_ros
def test_wrong_type_parameter_is_a_refusal(ros_domain):
    with pytest.raises(psa.SurveyAreaFileError, match='bad parameter|must be a number'):
        psa.make_node(['--ros-args', '-p', 'file:=%s' % DEMO_FILE,
                       '-p', 'standard_a:=text']).destroy_node()
    rclpy.shutdown()
    with pytest.raises(psa.SurveyAreaFileError, match='bad parameter'):
        psa.make_node(['--ros-args', '-p', 'file:=%s' % DEMO_FILE,
                       '-p', 'priority:=1.5']).destroy_node()


# --- --check: the dry run the launch manager makes before it starts the demo ----------

def test_check_accepts_the_shipped_polygon(capsys):
    assert psa.main(['--check', str(psa.default_file())]) == 0
    assert 'holds 1 survey area' in capsys.readouterr().out


def test_check_refuses_a_malformed_file_with_the_reason(tmp_path, capsys):
    bad = tmp_path / 'bad.json'
    bad.write_text('{"x": ')
    assert psa.main(['--check', str(bad)]) == 2
    assert 'not valid JSON' in capsys.readouterr().err


def test_check_refuses_a_missing_file_and_a_file_without_areas(tmp_path, capsys):
    assert psa.main(['--check', str(tmp_path / 'nope.json')]) == 2
    empty = tmp_path / 'empty.json'
    empty.write_text('{}')
    assert psa.main(['--check', str(empty)]) == 2


def test_check_needs_exactly_one_file(capsys):
    assert psa.main(['--check']) == 2 and psa.main(['--check', 'a', 'b']) == 2
    assert 'usage' in capsys.readouterr().err
