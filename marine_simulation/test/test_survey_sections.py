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

"""Tests of marine_simulation.survey_sections on the shipped target polygon and small shapes."""

import json
import math
import pathlib

from marine_simulation import survey_sections as ss
import pytest

PACKAGE = pathlib.Path(__file__).resolve().parents[1]
POLYGON = PACKAGE / 'config' / 'demo_target_polygon_camp.json'


def shipped_area():
    data = json.loads(POLYGON.read_text())

    def walk(node):
        if node.get('type') == 'SurveyArea':
            yield [(c['latitude'], c['longitude']) for c in node['children']
                   if c.get('type') == 'Waypoint']
        for child in node.get('children', []):
            yield from walk(child)

    return next(walk(data))


def square(lat=43.0, lon=-70.7, side=500.0):
    """Return a square of ``side`` metres as (lat, lon) vertices."""
    plane = ss.LocalPlane(lat, lon)
    h = side / 2.0
    return [plane.to_latlon(x, y) for x, y in ((-h, -h), (h, -h), (h, h), (-h, h))]


def inside(ring, point, plane):
    """Ray-casting point-in-polygon on the local plane."""
    xy = [plane.to_xy(*p) for p in ring]
    x, y = plane.to_xy(*point)
    hit = False
    for i, (x1, y1) in enumerate(xy):
        x2, y2 = xy[(i + 1) % len(xy)]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def length_m(plane, a, b):
    (x1, y1), (x2, y2) = plane.to_xy(*a), plane.to_xy(*b)
    return math.hypot(x2 - x1, y2 - y1)


@pytest.mark.parametrize('count', [1, 2, 3, 4])
def test_every_section_of_the_shipped_area_has_lines_inside_it(count):
    area = shipped_area()
    plane = ss.LocalPlane(sum(p[0] for p in area) / len(area), sum(p[1] for p in area) / len(area))
    for index in range(count):
        section = ss.plan_section(area, index, count, 80.0)
        assert section.lines
        for start, end in section.segments():
            for point in (start, end):
                assert inside(area, point, plane), (index, point)
            assert length_m(plane, start, end) >= 30.0 - 1e-6


@pytest.mark.parametrize('count', [2, 3, 4])
def test_the_sections_have_equal_areas(count):
    area = shipped_area()
    areas = [ss.plan_section(area, i, count, 80.0).area_m2 for i in range(count)]
    assert max(areas) - min(areas) < 0.03 * (sum(areas) / count)
    assert sum(areas) == pytest.approx(
        ss.plan_section(area, 0, 1, 80.0).area_m2, rel=0.03)


@pytest.mark.parametrize('count', [2, 3, 4])
def test_the_bands_are_disjoint_and_ordered(count):
    area = shipped_area()
    bands = [ss.plan_section(area, i, count, 80.0).band for i in range(count)]
    for (low1, high1), (low2, high2) in zip(bands, bands[1:]):
        assert high1 == pytest.approx(low2) and low1 < high1


def test_lines_of_neighbouring_boats_are_at_least_a_spacing_apart():
    area = shipped_area()
    plane = ss.LocalPlane(sum(p[0] for p in area) / len(area), sum(p[1] for p in area) / len(area))
    a, b = (ss.plan_section(area, i, 2, 80.0) for i in (0, 1))
    angle = math.radians(a.angle_deg)

    def across(section):
        return sorted(ss.rotate(plane.to_xy(*line[0][0]), -angle)[1] for line in section.lines)

    gap = across(b)[0] - across(a)[-1]
    assert gap >= 80.0 * 0.5          # half a spacing from each side of the shared edge, at least


def test_the_plan_is_deterministic():
    area = shipped_area()
    one = ss.mission_plan(ss.plan_section(area, 1, 3, 80.0), 'x_s1', 4.0)
    two = ss.mission_plan(ss.plan_section(area, 1, 3, 80.0), 'x_s1', 4.0)
    assert one == two


def test_lines_alternate_direction():
    section = ss.plan_section(square(), 0, 1, 100.0)
    plane = ss.LocalPlane(43.0, -70.7)
    ends = [(plane.to_xy(*s), plane.to_xy(*e)) for s, e in section.segments()]
    headings = [math.atan2(e[1] - s[1], e[0] - s[0]) for s, e in ends]
    for a, b in zip(headings, headings[1:]):
        assert abs(abs(a - b) - math.pi) < 0.01


def test_a_concave_outline_gives_several_segments_on_one_line():
    # a U: the line through both arms has two segments
    plane = ss.LocalPlane(43.0, -70.7)
    ring = [plane.to_latlon(*p) for p in
            ((0, 0), (600, 0), (600, 600), (400, 600), (400, 200), (200, 200), (200, 600),
             (0, 600))]
    section = ss.plan_section(ring, 0, 1, 100.0, heading_deg=90.0)
    assert any(len(line) == 2 for line in section.lines)
    for start, end in section.segments():
        assert inside(ring, start, plane) and inside(ring, end, plane)
    # no segment crosses the gap of the U
    for start, end in section.segments():
        mid = ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)
        assert inside(ring, mid, plane)


def test_the_heading_argument_sets_the_direction_of_the_lines():
    plane = ss.LocalPlane(43.0, -70.7)
    for heading in (0.0, 90.0, 45.0):
        section = ss.plan_section(square(), 0, 1, 100.0, heading_deg=heading)
        (x1, y1), (x2, y2) = (plane.to_xy(*p) for p in section.segments()[0])
        compass = math.degrees(math.atan2(x2 - x1, y2 - y1)) % 180.0
        assert compass == pytest.approx(heading % 180.0, abs=0.5)


@pytest.mark.parametrize('area, message', [
    ([(43.0, -70.7), (43.1, -70.7)], 'at least three'),
    ([(43.0, -70.7), (43.0, -70.7), (43.0, -70.7)], 'at least three'),
    ([(43.0, -70.7), (43.001, -70.7), (43.002, -70.7)], 'smaller than'),
    ([(43.0, -70.7), (43.1, -70.7), (float('nan'), -70.6)], 'not a latitude'),
    ([(43.0, -70.7), (43.1, -70.7), (95.0, -70.6)], 'not a latitude'),
])
def test_unusable_areas_are_refused_with_a_reason(area, message):
    with pytest.raises(ss.SectionError, match=message):
        ss.plan_section(area, 0, 1, 80.0)


@pytest.mark.parametrize('index, count', [(2, 2), (-1, 2), (0, 0)])
def test_a_section_that_does_not_exist_is_refused(index, count):
    with pytest.raises(ss.SectionError, match='does not exist'):
        ss.plan_section(square(), index, count, 80.0)


def test_an_area_too_small_for_the_spacing_and_line_length_is_refused():
    with pytest.raises(ss.SectionError, match='no line'):
        ss.plan_section(square(side=40.0), 0, 1, 80.0, edge_margin=15.0, min_length=30.0)


def test_a_bad_spacing_is_refused():
    for spacing in (0.0, -5.0, float('nan')):
        with pytest.raises(ss.SectionError):
            ss.plan_section(square(), 0, 1, spacing)


def test_the_mission_has_the_shape_camp_sends_and_mission_manager_reads():
    section = ss.plan_section(shipped_area(), 0, 2, 80.0)
    (pattern,) = ss.mission_plan(section, 'bluefin_s1', 4.0)
    assert pattern['type'] == 'SurveyPattern' and pattern['label'] == 'bluefin_s1'
    lines = pattern['children']
    assert len(lines) == len(section.segments())
    for number, line in enumerate(lines):
        assert line['type'] == 'TrackLine' and line['label'] == 'bluefin_s1_l%03d' % number
        assert line['speed'] == 4.0
        assert [w['type'] for w in line['children']] == ['Waypoint', 'Waypoint']
    command = ss.mission_command([pattern])
    verb, kind, payload = command.split(None, 2)
    assert (verb, kind) == ('replace_task', 'mission_plan')
    assert json.loads(payload) == [pattern]


def test_task_ids_are_what_mission_manager_derives():
    section = ss.plan_section(shipped_area(), 0, 2, 80.0)
    plan = ss.mission_plan(section, 'a_s2', 4.0)
    set_id, line_ids = ss.task_ids('a_s2', len(plan[0]['children']))
    assert set_id == 'a_s2'
    assert line_ids[0] == 'a_s2/a_s2_l000' and len(line_ids) == len(plan[0]['children'])


def test_generations_give_distinct_task_ids():
    assert ss.task_ids('a_s1', 2)[1] != ss.task_ids('a_s2', 2)[1]


def test_the_mission_message_is_small_enough_for_a_string_topic():
    section = ss.plan_section(shipped_area(), 0, 1, 40.0)       # the largest case: one boat
    assert len(ss.mission_command(ss.mission_plan(section, 'x_s1', 4.0))) < 64 * 1024


def test_a_request_that_would_make_thousands_of_lines_is_refused():
    with pytest.raises(ss.SectionError, match='lines; the limit'):
        ss.plan_section(square(side=50000.0), 0, 1, 80.0)


def test_a_request_that_would_need_millions_of_samples_is_refused():
    with pytest.raises(ss.SectionError, match='samples'):
        ss.plan_section(square(side=50000.0), 0, 1, 1.0)


def test_an_absurd_number_of_boats_is_refused():
    with pytest.raises(ss.SectionError, match='sections'):
        ss.plan_section(square(), 0, ss.MAX_BOATS + 1, 80.0)


def test_the_section_carries_the_maths_angle_not_a_heading():
    section = ss.plan_section(square(), 0, 1, 100.0, heading_deg=90.0)     # due east
    assert section.angle_deg % 180.0 == pytest.approx(0.0, abs=0.5)
    assert not hasattr(section, 'heading')


def test_the_area_book_ignores_an_older_stamp_and_takes_a_newer_one():
    book = ss.AreaBook()
    ring = [(43.0, -70.7), (43.0, -70.6), (43.1, -70.6)]
    other = [(44.0, -70.7), (44.0, -70.6), (44.1, -70.6)]
    assert book.update('a', ring, (100, 0)) is True
    assert book.update('a', other, (99, 5)) is False         # stale copy: ignored
    assert book.first() == ('a', ring)
    assert book.update('a', ring, (100, 0)) is False         # the same again: no change
    assert book.update('a', other, (100, 1)) is True         # newer: replaces
    assert book.first() == ('a', other)


def test_the_area_book_hands_out_the_smallest_id_and_is_falsy_when_empty():
    book = ss.AreaBook()
    assert not book and book.first() is None
    ring = [(43.0, -70.7), (43.0, -70.6), (43.1, -70.6)]
    book.update('b', ring, (1, 0))
    book.update('a', ring[::-1], (1, 0))
    assert book and book.first()[0] == 'a'
