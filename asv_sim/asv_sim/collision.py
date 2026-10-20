"""Contact resolution for ``asv_sim`` (issue #111): blocking only.

Boats are indestructible. A contact only keeps a boat from getting any
further into whatever it touches: no damage, no penalty, no reset.

The resolver is called by :class:`asv_sim.dynamics.Dynamics` once per
integration sub-step, right after the boat's position (its own motion plus
the current) has been advanced, so a long stalled gap is resolved step by
step and a boat cannot tunnel through a shore or a hull.

What a boat can touch is a list of *obstacle sources*. Each source has
``correct(step, lat, lon)``, returning the (possibly corrected) position and
the list of :class:`Contact` it made. Boats and terrain are the two sources
here; another one (charted objects, issue #113) is added by appending an
object with the same method to ``Collisions.sources``, nothing in
:meth:`Collisions.resolve` changes.

All distances are metres in a local east/north frame; headings are compass
radians (clockwise from north), as in ``Dynamics``.
"""

from collections import namedtuple
import math

from . import geodesic

# What a boat that is on land, on a nodata cell or off the grid is treated
# as drawing against: a fixed depth of water far below any draft.
WALL_CLEARANCE = -10.0

# A contact that has not been seen for this long (node clock) is over; the
# next one is a new event.
CONTACT_RELEASE_NS = 1000000000

# Contact kinds (the values of asv_sim_msgs/msg/Collision).
KIND_BOAT = 0
KIND_TERRAIN = 1

# A contact: kind, name of the other boat ('' for terrain), unit normal
# (east, north) pointing away from the obstacle, velocity (east, north) of
# the obstacle, and the water depth under the hull centre (NaN: none).
Contact = namedtuple(
    'Contact', ['kind', 'other', 'normal', 'other_velocity', 'water_depth'])


def segment_closest(p0, p1, q0, q1):
    """Return the closest points of segments p0-p1 and q0-q1 (2-D tuples)."""
    d1 = (p1[0] - p0[0], p1[1] - p0[1])
    d2 = (q1[0] - q0[0], q1[1] - q0[1])
    r = (p0[0] - q0[0], p0[1] - q0[1])
    a = d1[0] * d1[0] + d1[1] * d1[1]
    e = d2[0] * d2[0] + d2[1] * d2[1]
    f = d2[0] * r[0] + d2[1] * r[1]
    eps = 1e-12
    if a <= eps and e <= eps:
        return p0, q0
    if a <= eps:
        s = 0.0
        t = min(1.0, max(0.0, f / e))
    else:
        c = d1[0] * r[0] + d1[1] * r[1]
        if e <= eps:
            t = 0.0
            s = min(1.0, max(0.0, -c / a))
        else:
            b = d1[0] * d2[0] + d1[1] * d2[1]
            denom = a * e - b * b
            s = min(1.0, max(0.0, (b * f - c * e) / denom)) \
                if denom > eps else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t = 0.0
                s = min(1.0, max(0.0, -c / a))
            elif t > 1.0:
                t = 1.0
                s = min(1.0, max(0.0, (b - c) / a))
    return ((p0[0] + d1[0] * s, p0[1] + d1[1] * s),
            (q0[0] + d2[0] * t, q0[1] + d2[1] * t))


def capsule_axis(centre, heading, length, beam):
    """Return the end points of a hull capsule's axis and its radius."""
    half = max(0.0, (length - beam) / 2.0)
    direction = (math.sin(heading), math.cos(heading))
    return ((centre[0] - direction[0] * half, centre[1] - direction[1] * half),
            (centre[0] + direction[0] * half, centre[1] + direction[1] * half),
            beam / 2.0)


def capsule_penetration(a, b):
    """Return ``(depth, normal)`` of two overlapping capsules, else ``None``.

    :param a: ``(axis_start, axis_end, radius)`` of the first capsule.
    :param b: the same for the second.
    :return: Overlap depth in metres and the unit vector pointing from ``b``
        to ``a`` (the direction to move ``a`` to separate them).
    """
    pa, pb = segment_closest(a[0], a[1], b[0], b[1])
    dx = pa[0] - pb[0]
    dy = pa[1] - pb[1]
    distance = math.hypot(dx, dy)
    depth = a[2] + b[2] - distance
    if depth <= 0.0:
        return None
    if distance < 1e-9:
        # Axes cross: any direction separates them; take the one from b's
        # centre to a's, else east.
        cx = (a[0][0] + a[1][0] - b[0][0] - b[1][0]) / 2.0
        cy = (a[0][1] + a[1][1] - b[0][1] - b[1][1]) / 2.0
        norm = math.hypot(cx, cy)
        return (depth, (cx / norm, cy / norm) if norm > 1e-9 else (1.0, 0.0))
    return depth, (dx / distance, dy / distance)


def offset_en(lat0, lon0, lat1, lon1):
    """Return the (east, north) metres from point 0 to point 1 (radians)."""
    azimuth, distance = geodesic.inverse(lon0, lat0, lon1, lat1)
    return distance * math.sin(azimuth), distance * math.cos(azimuth)


def move_en(lat, lon, east, north):
    """Return ``(lat, lon)`` in radians after moving by (east, north) m."""
    distance = math.hypot(east, north)
    if distance == 0.0:
        return lat, lon
    lon2, lat2 = geodesic.direct(
        lon, lat, math.atan2(east, north), distance)
    return lat2, lon2


class _Step:
    """The boat being stepped and where it was and is."""

    def __init__(self, dyn, prev, tide):
        self.dyn = dyn
        self.prev = prev        # (lat, lon) radians before the sub-step
        self.heading = dyn.heading
        self.tide = tide
        model = dyn.model
        self.length = model.length
        self.beam = model.beam
        self.draft = model.draft


class BoatSource:
    """Other boats: no interpenetration, tangential motion is kept."""

    def __init__(self, collisions):
        self.collisions = collisions

    def correct(self, step, lat, lon):
        contacts = {}
        others = [d for d in self.collisions.dynamics.values()
                  if d is not step.dyn]
        # A push away from one boat can push into another: a few passes.
        for _ in range(3):
            moved = False
            for other in others:
                east, north = offset_en(lat, lon, other.latitude,
                                        other.longitude)
                mine = capsule_axis(
                    (0.0, 0.0), step.heading, step.length, step.beam)
                theirs = capsule_axis(
                    (east, north), other.heading, other.model.length,
                    other.model.beam)
                hit = capsule_penetration(mine, theirs)
                if hit is None:
                    continue
                depth, normal = hit
                lat, lon = move_en(
                    lat, lon, normal[0] * depth, normal[1] * depth)
                velocity = (other.speed * math.sin(other.heading),
                            other.speed * math.cos(other.heading))
                contacts[other.name] = Contact(
                    KIND_BOAT, other.name, normal, velocity, math.nan)
                moved = True
            if not moved:
                break
        return lat, lon, list(contacts.values())


class TerrainSource:
    """The sea floor: a boat cannot get shallower than its draft allows.

    Clearance is the least, over five hull points (centre, bow, stern, port,
    starboard), of grid depth plus tide minus draft. Land, nodata cells and
    positions off the grid count as :data:`WALL_CLEARANCE`.
    """

    def __init__(self, grid):
        self.grid = grid
        self.cell = max(1.0, abs(grid.geoTransform[1]))

    def _frame(self, lat, lon):
        """Return the grid position and the grid vectors of 1 m east/north."""
        x0, y0 = self.grid.getXY(math.degrees(lat), math.degrees(lon))
        lat_e, lon_e = move_en(lat, lon, 1.0, 0.0)
        lat_n, lon_n = move_en(lat, lon, 0.0, 1.0)
        xe, ye = self.grid.getXY(math.degrees(lat_e), math.degrees(lon_e))
        xn, yn = self.grid.getXY(math.degrees(lat_n), math.degrees(lon_n))
        return (x0, y0, xe - x0, ye - y0, xn - x0, yn - y0)

    def _depth(self, frame, east, north, tide):
        """Return water depth above the sea floor at an offset, or None."""
        x = frame[0] + east * frame[2] + north * frame[4]
        y = frame[1] + east * frame[3] + north * frame[5]
        depth = self.grid.getDepth(x, y)
        if depth is None:
            return None
        return float(depth) + tide

    def clearance(self, frame, east, north, step):
        """Return the hull clearance with the boat centred at an offset."""
        direction = (math.sin(step.heading), math.cos(step.heading))
        right = (direction[1], -direction[0])
        half_length = step.length / 2.0
        half_beam = step.beam / 2.0
        points = (
            (0.0, 0.0),
            (direction[0] * half_length, direction[1] * half_length),
            (-direction[0] * half_length, -direction[1] * half_length),
            (right[0] * half_beam, right[1] * half_beam),
            (-right[0] * half_beam, -right[1] * half_beam))
        least = math.inf
        for de, dn in points:
            depth = self._depth(frame, east + de, north + dn, step.tide)
            value = (WALL_CLEARANCE if depth is None
                     else max(WALL_CLEARANCE, depth - step.draft))
            least = min(least, value)
        return least

    def correct(self, step, lat, lon):
        frame = self._frame(*step.prev)
        east, north = offset_en(step.prev[0], step.prev[1], lat, lon)
        before = self.clearance(frame, 0.0, 0.0, step)
        after = self.clearance(frame, east, north, step)
        # Aground already is not a reason to stay: a boat may go anywhere
        # that is not shallower than where it is.
        if after >= 0.0 or after >= before:
            return lat, lon, []

        h = self.cell
        ge = (self.clearance(frame, east + h, north, step)
              - self.clearance(frame, east - h, north, step))
        gn = (self.clearance(frame, east, north + h, step)
              - self.clearance(frame, east, north - h, step))
        norm = math.hypot(ge, gn)
        speed = math.hypot(east, north)
        if norm > 0.0:
            normal = (ge / norm, gn / norm)
        elif speed > 0.0:
            normal = (-east / speed, -north / speed)
        else:
            normal = (-math.sin(step.heading), -math.cos(step.heading))

        depth = self._depth(frame, east, north, step.tide)
        contact = Contact(KIND_TERRAIN, '', normal, (0.0, 0.0),
                          math.nan if depth is None else depth)
        along = east * normal[0] + north * normal[1]
        if norm > 0.0 and along < 0.0:
            slid = (east - along * normal[0], north - along * normal[1])
            clearance = self.clearance(frame, slid[0], slid[1], step)
            if clearance >= 0.0 or clearance >= before:
                new_lat, new_lon = move_en(
                    step.prev[0], step.prev[1], slid[0], slid[1])
                return new_lat, new_lon, [contact]
        return step.prev[0], step.prev[1], [contact]


class Collisions:
    """Resolve contacts for every registered boat.

    :param grid: A ``mbes_sim.bathy_grid.BathyGrid`` (or anything with
        ``getXY``, ``getDepth`` and ``geoTransform``), or ``None`` for no
        terrain.
    :param boats: ``False`` lets boats pass through each other.
    :param emit: Called with one dict per contact onset.
    :param logger: Object with ``info`` and ``warning``.
    """

    def __init__(self, grid=None, boats=True, emit=None, logger=None):
        self.dynamics = {}
        self.emit = emit
        self.logger = logger
        self.sources = []
        if boats:
            self.sources.append(BoatSource(self))
        if grid is not None:
            self.sources.append(TerrainSource(grid))
        self._last_seen = {}

    def register(self, dyn):
        """Add a boat; its ``name`` must be unique."""
        self.dynamics[dyn.name] = dyn

    def resolve(self, dyn, last_lat, last_lon, timestamp, delta_t):
        """Correct ``dyn`` after a sub-step that took it from ``last``.

        Position, speed and acceleration of ``dyn`` are changed in place;
        nothing else is.
        """
        if not self.sources or not delta_t:
            return
        if not all(math.isfinite(v) for v in (
                dyn.latitude, dyn.longitude, dyn.heading, dyn.speed,
                last_lat, last_lon)):
            return
        tide = 0.0
        if dyn.environment is not None:
            tide = dyn.environment.getTide(timestamp)
        step = _Step(dyn, (last_lat, last_lon), tide)

        lat, lon = dyn.latitude, dyn.longitude
        contacts = []
        for source in self.sources:
            lat, lon, found = source.correct(step, lat, lon)
            contacts.extend(found)
        if not contacts:
            return
        if not all(math.isfinite(v) for v in (lat, lon)):
            raise ArithmeticError('contact moved the boat to a non-finite '
                                  'position')

        forward = (math.sin(dyn.heading), math.cos(dyn.heading))
        velocity = (dyn.speed * forward[0], dyn.speed * forward[1])
        speed0 = dyn.speed
        for contact in contacts:
            normal = contact.normal
            relative = (velocity[0] - contact.other_velocity[0],
                        velocity[1] - contact.other_velocity[1])
            closing = max(0.0, -(relative[0] * normal[0]
                                 + relative[1] * normal[1]))
            along = forward[0] * normal[0] + forward[1] * normal[1]
            if dyn.speed * along < 0.0:
                dyn.speed *= 1.0 - along * along
            self._report(dyn, contact, closing, lat, lon, timestamp)
        dyn.latitude, dyn.longitude = lat, lon
        dyn.a += (dyn.speed - speed0) / delta_t

    def _report(self, dyn, contact, closing, lat, lon, timestamp):
        key = (dyn.name, contact.kind, contact.other)
        now = timestamp.nanoseconds
        last = self._last_seen.get(key)
        self._last_seen[key] = now
        if last is not None and now - last <= CONTACT_RELEASE_NS:
            return
        if self.logger is not None:
            what = ('boat ' + contact.other if contact.kind == KIND_BOAT
                    else 'the bottom or shore')
            self.logger.info(
                'asv_sim platform {!r} touched {} at {:.1f} m/s'.format(
                    dyn.name, what, closing))
        if self.emit is not None:
            self.emit({
                'stamp': timestamp, 'platform': dyn.name,
                'kind': contact.kind, 'other': contact.other,
                'latitude': math.degrees(lat),
                'longitude': math.degrees(lon),
                'closing_speed': closing,
                'water_depth': contact.water_depth})
