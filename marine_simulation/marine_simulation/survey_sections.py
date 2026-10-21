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
Split a target area into one section per boat and turn a section into a survey mission.

The area is the polygon of a latched ``marine_interfaces/SurveyArea`` (latitude and longitude).
It is cut across the survey lines into as many bands of equal area as there are boats; the
i-th selected boat, in roster order, gets the i-th band. Inside its band a boat runs parallel
lines, alternating direction, as a CAMP ``SurveyPattern`` whose ``TrackLine`` children each have
two ``Waypoint`` children: the plan ``mission_manager`` reads from
``marine/mission_manager/command`` (``replace_task mission_plan <json>``), so a real boat would
run the same thing.

Everything is plain Python on a local tangent plane at the polygon's centre (the area is a few
kilometres across, so the error is well under a metre); nothing here needs ROS.
"""

import json
import math
from typing import List, Optional, Sequence, Tuple

EARTH_RADIUS_M = 6371008.8
KNOTS_TO_MS = 0.514444

# limits that keep a bad request (a huge area, a tiny spacing) from running for minutes or
# producing a plan mission_manager cannot take
MAX_BAND_STEPS = 200000
MAX_LINES = 500
MAX_BOATS = 64

# an extra sample of the area per spacing/this many metres when integrating band areas
_SAMPLES_PER_SPACING = 20.0


class SectionError(ValueError):
    """The area cannot be split or surveyed as asked."""


Point = Tuple[float, float]


class LocalPlane:
    """An equirectangular tangent plane at ``(lat0, lon0)``, in metres east and north."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0 = lat0
        self.lon0 = lon0
        self._k = math.radians(1.0) * EARTH_RADIUS_M
        self._cos = math.cos(math.radians(lat0))

    def to_xy(self, lat: float, lon: float) -> Point:
        return ((lon - self.lon0) * self._k * self._cos, (lat - self.lat0) * self._k)

    def to_latlon(self, x: float, y: float) -> Point:
        return (self.lat0 + y / self._k, self.lon0 + x / (self._k * self._cos))


def polygon_area(points: Sequence[Point]) -> float:
    """Return the absolute area of a simple polygon (shoelace)."""
    total = 0.0
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def rotate(point: Point, angle: float) -> Point:
    """Rotate ``point`` by ``angle`` radians counter-clockwise about the origin."""
    c, s = math.cos(angle), math.sin(angle)
    return (point[0] * c - point[1] * s, point[0] * s + point[1] * c)


def line_heading(points: Sequence[Point]) -> float:
    """
    Return the direction, in radians, of the long side of the polygon's smallest bounding box.

    The box is tried along every edge direction; ties go to the first edge, so the answer is
    deterministic. Survey lines run along the long side: fewer, longer lines.
    """
    best = None
    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        if x1 == x2 and y1 == y2:
            continue
        angle = math.atan2(y2 - y1, x2 - x1)
        turned = [rotate(p, -angle) for p in points]
        width = max(p[0] for p in turned) - min(p[0] for p in turned)
        height = max(p[1] for p in turned) - min(p[1] for p in turned)
        if best is None or width * height < best[0] - 1e-9:
            best = (width * height, angle if width >= height else angle + math.pi / 2.0)
    if best is None:
        raise SectionError('the area has no edge')
    return best[1] % math.pi


def crossings(points: Sequence[Point], v: float) -> List[float]:
    """
    Return the sorted ``u`` where the horizontal line at ``v`` crosses the polygon's boundary.

    An edge counts when ``v`` is in ``[low, high)`` of its ends, so a line through a vertex is
    counted once or not at all, and the answer always has an even length.
    """
    found = []
    for i, (u1, v1) in enumerate(points):
        u2, v2 = points[(i + 1) % len(points)]
        if v1 == v2:
            continue
        low, high = (v1, v2) if v1 < v2 else (v2, v1)
        if low <= v < high:
            found.append(u1 + (v - v1) * (u2 - u1) / (v2 - v1))
    return sorted(found)


def covered_length(points: Sequence[Point], v: float) -> float:
    """Return the length of the line at ``v`` that is inside the polygon."""
    xs = crossings(points, v)
    return sum(xs[i + 1] - xs[i] for i in range(0, len(xs) - 1, 2))


def band_edges(points: Sequence[Point], count: int, step: float) -> List[float]:
    """
    Return the ``count + 1`` values of ``v`` that cut the polygon into bands of equal area.

    The covered length is integrated across ``v`` in steps of ``step`` metres and the cuts are
    interpolated where the running area reaches each equal share.
    """
    low = min(p[1] for p in points)
    high = max(p[1] for p in points)
    steps = max(1, int(math.ceil((high - low) / step)))
    if steps > MAX_BAND_STEPS:
        raise SectionError('the area is %.0f spacings across; the limit is %d samples'
                           % ((high - low) / (step * _SAMPLES_PER_SPACING), MAX_BAND_STEPS))
    h = (high - low) / steps
    cumulative = [0.0]
    for k in range(steps):
        cumulative.append(cumulative[-1] + covered_length(points, low + (k + 0.5) * h) * h)
    total = cumulative[-1]
    if total <= 0.0:
        raise SectionError('the area has no extent')
    edges = [low]
    k = 0
    for b in range(1, count):
        target = total * b / count
        while k < steps - 1 and cumulative[k + 1] < target:
            k += 1
        span = cumulative[k + 1] - cumulative[k]
        fraction = (target - cumulative[k]) / span if span > 0.0 else 0.0
        edges.append(low + (k + fraction) * h)
    edges.append(high)
    return edges


def band_lines(points: Sequence[Point], v_low: float, v_high: float, spacing: float,
               edge_margin: float, min_length: float) -> List[List[Tuple[float, float, float]]]:
    """
    Return the survey lines of one band as ``[[(v, u_start, u_end), ...], ...]``.

    One entry per line position, in increasing ``v``; the inner list holds the segments of that
    line inside the polygon (more than one where the outline is concave). The first line is half
    a spacing from the band's lower edge, so the lines of two neighbouring bands are a full
    spacing apart. Segments are shortened by ``edge_margin`` at both ends and dropped when
    shorter than ``min_length``. Direction alternates from line to line (boustrophedon).
    """
    width = v_high - v_low
    count = max(1, int(round(width / spacing)))
    if count > MAX_LINES:
        raise SectionError('a band of %.0f m at a spacing of %g m is %d lines; the limit is %d'
                           % (width, spacing, count, MAX_LINES))
    positions = [v_low + width * (k + 0.5) / count for k in range(count)]
    lines = []
    for index, v in enumerate(positions):
        xs = crossings(points, v)
        segments = []
        for i in range(0, len(xs) - 1, 2):
            u0, u1 = xs[i] + edge_margin, xs[i + 1] - edge_margin
            if u1 - u0 >= min_length:
                segments.append((v, u0, u1))
        if index % 2:
            segments = [(v_, u1, u0) for v_, u0, u1 in reversed(segments)]
        if segments:
            lines.append(segments)
    return lines


class Section:
    """One boat's part of the area: its lines in order, as latitude/longitude end points."""

    def __init__(self, index: int, count: int, lines: List[List[Tuple[Point, Point]]],
                 band: Tuple[float, float], angle_deg: float, area_m2: float):
        self.index = index
        self.count = count
        self.lines = lines          # [[(start, end), ...] per line position]
        self.band = band
        self.angle_deg = angle_deg      # the lines' direction as a maths angle (east = 0, ccw)
        self.area_m2 = area_m2

    def segments(self) -> List[Tuple[Point, Point]]:
        """Return every segment in the order the boat runs them."""
        return [s for line in self.lines for s in line]


def plan_section(area: Sequence[Point], index: int, count: int, spacing: float,
                 edge_margin: float = 15.0, min_length: float = 30.0,
                 heading_deg: Optional[float] = None) -> Section:
    """
    Return section ``index`` (0-based) of ``count`` of the ``area`` (a ring of (lat, lon)).

    ``heading_deg`` is the compass heading of the survey lines; ``None`` picks the long side of
    the area's smallest bounding box. Raises ``SectionError`` for a bad request or an area that
    leaves this section no line.
    """
    if count > MAX_BOATS:
        raise SectionError('%d sections; the limit is %d' % (count, MAX_BOATS))
    if count < 1 or not 0 <= index < count:
        raise SectionError('section %d of %d does not exist' % (index, count))
    if not spacing > 0.0 or edge_margin < 0.0 or min_length < 0.0:
        raise SectionError('spacing must be positive, the margin and the minimum length not '
                           'negative')
    ring = list(dict.fromkeys(tuple(p) for p in area))
    if len(ring) < 3:
        raise SectionError('an area needs at least three distinct vertices, got %d' % len(ring))
    for lat, lon in ring:
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90
                and -180 <= lon <= 180):
            raise SectionError('vertex (%r, %r) is not a latitude and longitude' % (lat, lon))
    plane = LocalPlane(sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring))
    xy = [plane.to_xy(lat, lon) for lat, lon in ring]
    if polygon_area(xy) < 1.0:
        raise SectionError('the area is smaller than one square metre')
    if heading_deg is None:
        angle = line_heading(xy)
    else:
        # compass heading (clockwise from north) to the mathematical angle of the east axis
        angle = (math.pi / 2.0 - math.radians(heading_deg)) % math.pi
    rotated = [rotate(p, -angle) for p in xy]
    edges = band_edges(rotated, count, spacing / _SAMPLES_PER_SPACING)
    v_low, v_high = edges[index], edges[index + 1]
    raw = band_lines(rotated, v_low, v_high, spacing, edge_margin, min_length)
    if not raw:
        raise SectionError('section %d of %d has no line: the area is too small for a spacing '
                           'of %g m and a minimum line length of %g m'
                           % (index + 1, count, spacing, min_length))
    lines = []
    for line in raw:
        out = []
        for v, u0, u1 in line:
            a = plane.to_latlon(*rotate((u0, v), angle))
            b = plane.to_latlon(*rotate((u1, v), angle))
            out.append((a, b))
        lines.append(out)
    band_area = sum(covered_length(rotated, v_low + (k + 0.5) * (v_high - v_low) / 50.0)
                    for k in range(50)) * (v_high - v_low) / 50.0
    return Section(index, count, lines, (v_low, v_high), math.degrees(angle), band_area)


class AreaBook:
    """
    The target areas heard so far, by id, each with the stamp of the message that carried it.

    A message older than the one held for its id is ignored, as the scorer does: the same area
    arrives again (a publisher restart, a second path) and a stale copy must never replace a
    newer one. ``first()`` is the area a boat surveys: the one with the smallest id.
    """

    def __init__(self):
        self.points: dict = {}
        self.stamps: dict = {}

    def update(self, area_id: str, points: Sequence[Point], stamp: Tuple[int, int]) -> bool:
        """Take an area; return whether the book changed (the ring or a first sight of the id)."""
        points = [tuple(p) for p in points]
        known = self.stamps.get(area_id)
        if known is not None and tuple(stamp) < known:
            return False
        changed = self.points.get(area_id) != points
        self.points[area_id] = points
        self.stamps[area_id] = tuple(stamp)
        return changed

    def first(self) -> Optional[Tuple[str, List[Point]]]:
        """Return ``(id, ring)`` of the area with the smallest id, or ``None`` when empty."""
        if not self.points:
            return None
        area_id = min(self.points)
        return area_id, self.points[area_id]

    def __bool__(self) -> bool:
        return bool(self.points)


def line_label(prefix: str, number: int) -> str:
    """Return the label of line ``number`` of the mission whose label is ``prefix``."""
    return '%s_l%03d' % (prefix, number)


def mission_plan(section: Section, prefix: str, speed_knots: float) -> list:
    """
    Return the CAMP mission plan for ``section``.

    A single ``SurveyPattern`` labelled ``prefix`` whose ``TrackLine`` children are labelled
    ``<prefix>_l000``, ``<prefix>_l001``, ... in running order. ``mission_manager`` makes the
    tasks ``<prefix>`` and ``<prefix>/<prefix>_l000`` and so on; ``prefix`` must therefore be
    unique per send, so that feedback of an earlier send is never taken for this one.
    """
    if not speed_knots > 0.0:
        raise SectionError('speed must be positive')

    def waypoint(name, point):
        return {'type': 'Waypoint', 'label': name, 'latitude': point[0], 'longitude': point[1]}

    children = []
    for number, (start, end) in enumerate(section.segments()):
        label = line_label(prefix, number)
        children.append({
            'type': 'TrackLine', 'label': label, 'speed': speed_knots, 'priority': 0,
            'children': [waypoint('start', start), waypoint('end', end)],
        })
    return [{'type': 'SurveyPattern', 'label': prefix, 'speed': speed_knots, 'priority': 0,
             'children': children}]


def mission_command(plan: list) -> str:
    """Return the String ``mission_manager`` receives for ``plan``."""
    return 'replace_task mission_plan ' + json.dumps(plan)


def task_ids(prefix: str, lines: int) -> Tuple[str, List[str]]:
    """Return ``(set task id, [line task ids])`` mission_manager derives from a plan."""
    return prefix, ['%s/%s' % (prefix, line_label(prefix, n)) for n in range(lines)]
