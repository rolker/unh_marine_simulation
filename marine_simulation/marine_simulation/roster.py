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
The demo's boat roster: who the boats are, and the strict parsing of switches.

``config/demo_roster.yaml`` is the only place boat names live. Everything that needs the
boats (the boats launch, the CAMP settings, the scorer parameters, the launch manager's
starter) reads them through ``load_roster`` / ``select_boats``, so no name is copied into a
second file. Plain functions with no launch context, so they are unit tested directly.
"""

import dataclasses
import math
import re
from typing import List, Sequence, Tuple

import yaml

# Names that are already in use as top-level namespaces or TF frames.
RESERVED_NAMES = frozenset({
    'asv_sim', 'earth', 'marine', 'parameter_events', 'rosout', 'tf', 'tf_static',
})
# Used with fullmatch: `$` would accept a trailing newline.
_NAME_PATTERN = re.compile(r'[a-z][a-z0-9_]*')


@dataclasses.dataclass(frozen=True)
class Boat:
    """One boat of the roster."""

    name: str
    pad: str
    color: Tuple[float, float, float]
    lat: float
    lon: float
    heading: float
    index: int

    def frame(self, suffix: str) -> str:
        """Return the boat's TF frame name for ``suffix``."""
        return '%s/%s' % (self.name, suffix)


def number(value, what: str, low: float = None, high: float = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('%s must be a number, got %r' % (what, value))
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('%s must be a finite number, got %r' % (what, value))
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValueError('%s = %s is outside [%s, %s]' % (what, value, low, high))
    return value


_TRUE_WORDS = ('true', '1', 'yes', 'on')
_FALSE_WORDS = ('false', '0', 'no', 'off')


def parse_bool(value: str, what: str) -> bool:
    """
    Parse a boolean launch argument strictly.

    Anything outside true/1/yes/on and false/0/no/off raises: ``enable_joysticks:=ture``
    must not quietly start four boats with no pads.
    """
    word = value.strip().lower()
    if word in _TRUE_WORDS:
        return True
    if word in _FALSE_WORDS:
        return False
    raise ValueError('%s must be one of %s, got %r'
                     % (what, ', '.join(_TRUE_WORDS + _FALSE_WORDS), value))


def load_roster(path: str) -> List[Boat]:
    """Read and validate the boat roster; return the boats in file order."""
    with open(path) as f:
        data = yaml.safe_load(f)
    entries = data.get('boats') if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError("%s: expected a non-empty 'boats' list" % path)

    boats = []
    seen = set()
    for index, entry in enumerate(entries):
        where = '%s: boats[%d]' % (path, index)
        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str):
            raise ValueError("%s: each boat needs a string 'name'" % where)
        name = entry['name']
        where = '%s: boat %r' % (path, name)
        if not _NAME_PATTERN.fullmatch(name):
            raise ValueError('%s: the name must match %s (it becomes a ROS namespace '
                             'and a TF frame prefix)' % (where, _NAME_PATTERN.pattern))
        if name in RESERVED_NAMES:
            raise ValueError('%s: %r is reserved' % (where, name))
        if name in seen:
            raise ValueError('%s: duplicate boat name' % where)
        seen.add(name)

        color = entry.get('color')
        if not isinstance(color, dict) or set(color) != {'red', 'green', 'blue'}:
            raise ValueError("%s: 'color' needs exactly red, green and blue" % where)
        start = entry.get('start')
        if not isinstance(start, dict) or set(start) != {'lat', 'lon', 'heading'}:
            raise ValueError("%s: 'start' needs exactly lat, lon and heading" % where)
        boats.append(Boat(
            name=name,
            pad=str(entry.get('pad', '')),
            color=tuple(number(color[k], '%s color.%s' % (where, k), 0.0, 1.0)
                        for k in ('red', 'green', 'blue')),
            lat=number(start['lat'], where + ' start.lat', -90.0, 90.0),
            lon=number(start['lon'], where + ' start.lon', -180.0, 180.0),
            heading=number(start['heading'], where + ' start.heading', 0.0, 360.0),
            index=index,
        ))
    return boats


def select_boats(roster: Sequence[Boat], requested: str) -> List[Boat]:
    """
    Return the roster boats named in the comma separated ``requested``.

    An empty string selects every boat. Boats keep their roster position (and
    so their joystick) whatever subset is chosen.
    """
    names = [n.strip() for n in requested.split(',') if n.strip()]
    if not names:
        return list(roster)
    known = {b.name: b for b in roster}
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ValueError('unknown boat(s) %s; the roster has %s'
                         % (', '.join(repr(n) for n in unknown), ', '.join(known)))
    if len(set(names)) != len(names):
        raise ValueError('boat listed more than once in %r' % requested)
    return [known[n] for n in names]
