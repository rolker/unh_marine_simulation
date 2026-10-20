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
here; another one (charted objects, issue #113, is the third) is added by appending an
object with the same method to ``Collisions.sources``, nothing in
:meth:`Collisions.resolve` changes.

All distances are metres in a local east/north frame; headings are compass
radians (clockwise from north), as in ``Dynamics``.
"""

from collections import namedtuple
import math

from . import geodesic

# Clearance of a hull point on a nodata cell or off the grid: the void. It
# is far below any real clearance (land is graded by its height, never
# clamped), so "no data" is told apart from "high ground".
VOID_CLEARANCE = -1.0e6

# Another boat further away than this many hull lengths plus beams cannot be
# touching; checking first keeps the (iterative) geodesic away from far pairs.
REACH_FACTOR = 2.0

# The longest hop between two obstacle checks, as a fraction of the beam: a
# bigger step (a long max_step, a fast current) is checked in pieces so a
# thin hull or shore cannot be jumped.
MAX_HOP_BEAMS = 0.5
MAX_HOPS = 500

# Passes of "boats, then terrain" until neither moves the boat any more.
MAX_PASSES = 3

# A contact that has not been seen for this long (node clock) is over; the
# next one is a new event.
CONTACT_RELEASE_NS = 1000000000

# Contact kinds (the values of asv_sim_msgs/msg/Collision).
KIND_BOAT = 0
KIND_TERRAIN = 1
KIND_OBJECT = 2

# Edge of the squares of the spatial hash over the charted objects, metres.
BUCKET = 100.0

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
        return _crossing_penetration(a, b)
    return depth, (dx / distance, dy / distance)


def _crossing_penetration(a, b):
    """Return the exact way out for capsules whose axes cross.

    The offset ``c`` of a's centre from b's centre separates the hulls when
    it leaves the rounded parallelogram ``{x*da + y*db}`` (``|x| <= half_a``,
    ``|y| <= half_b``) grown by the radii. From inside, the shortest way out
    is through the nearest edge.
    """
    ra, rb = a[2], b[2]
    da, half_a = _axis(a)
    db, half_b = _axis(b)
    centre_a = ((a[0][0] + a[1][0]) / 2.0, (a[0][1] + a[1][1]) / 2.0)
    centre_b = ((b[0][0] + b[1][0]) / 2.0, (b[0][1] + b[1][1]) / 2.0)
    c = (centre_a[0] - centre_b[0], centre_a[1] - centre_b[1])
    sin = da[0] * db[1] - da[1] * db[0]
    if abs(sin) < 1e-9:
        # Parallel axes that overlap: leave sideways.
        side = (-da[1], da[0])
        offset = c[0] * side[0] + c[1] * side[1]
        sign = -1.0 if offset < 0.0 else 1.0
        return (ra + rb + abs(offset), (side[0] * sign, side[1] * sign))
    # c = x*da + y*db
    x = (c[0] * db[1] - c[1] * db[0]) / sin
    y = (da[0] * c[1] - da[1] * c[0]) / sin
    # Edge x = +-half_a runs along db; its outward normal is db's
    # perpendicular on the side of +-da. Likewise for y.
    perp_b = (-db[1], db[0])
    if perp_b[0] * da[0] + perp_b[1] * da[1] < 0.0:
        perp_b = (-perp_b[0], -perp_b[1])
    perp_a = (-da[1], da[0])
    if perp_a[0] * db[0] + perp_a[1] * db[1] < 0.0:
        perp_a = (-perp_a[0], -perp_a[1])
    dist_x = (half_a - abs(x)) * abs(sin)
    dist_y = (half_b - abs(y)) * abs(sin)
    if dist_x <= dist_y:
        sign = -1.0 if x < 0.0 else 1.0
        normal = (perp_b[0] * sign, perp_b[1] * sign)
        return ra + rb + max(0.0, dist_x), normal
    sign = -1.0 if y < 0.0 else 1.0
    normal = (perp_a[0] * sign, perp_a[1] * sign)
    return ra + rb + max(0.0, dist_y), normal


def _axis(capsule):
    """Return the unit direction and half length of a capsule's axis."""
    dx = capsule[1][0] - capsule[0][0]
    dy = capsule[1][1] - capsule[0][1]
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return (0.0, 1.0), 0.0
    return (dx / length, dy / length), length / 2.0


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
    """One hop of the boat being stepped: where it was, what it turns to."""

    def __init__(self, dyn, prev, prev_heading, heading, tide):
        self.dyn = dyn
        self.prev = prev                  # (lat, lon) radians before the hop
        self.prev_heading = prev_heading
        self.heading = heading            # a source may put it back
        self.tide = tide
        self.in_void = False              # set by TerrainSource
        model = dyn.model
        self.length = model.length
        self.beam = model.beam
        self.draft = model.draft


def _finite(*values):
    return all(math.isfinite(v) for v in values)


def _contact_key(contact):
    """Key that keeps every physically different contact of one object.

    Two walls of one class meet the boat at different normals; each must
    reach the speed rule. Only the *report* is deduplicated, by onset.
    """
    return (contact.kind, contact.other,
            round(contact.normal[0], 3), round(contact.normal[1], 3))


class BoatSource:
    """Other boats: no interpenetration, tangential motion is kept."""

    def __init__(self, collisions):
        self.collisions = collisions

    def correct(self, step, lat, lon):
        contacts = {}
        others = [d for d in self.collisions.dynamics.values()
                  if d is not step.dyn
                  and _finite(d.latitude, d.longitude, d.heading, d.speed)]
        # A push away from one boat can push into another: a few passes.
        for _ in range(3):
            moved = False
            for other in others:
                reach = REACH_FACTOR * (
                    step.length + step.beam
                    + other.model.length + other.model.beam)
                if self._far(lat, lon, other, reach):
                    continue
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

    @staticmethod
    def _far(lat, lon, other, reach):
        """Cheap flat-earth test that keeps far boats out of the geodesic.

        ``geodesic.inverse`` iterates without a bound and does not converge
        for nearly antipodal points, so it must only see boats that are
        close (a ``set_pose`` can put one anywhere).
        """
        dlat = other.latitude - lat
        dlon = (other.longitude - lon + math.pi) % (2.0 * math.pi) - math.pi
        north = dlat * 6371000.0
        east = dlon * math.cos(lat) * 6371000.0
        return math.hypot(east, north) > reach


class TerrainSource:
    """The sea floor: a boat cannot get shallower than its draft allows.

    Clearance is the least, over five hull points (centre, bow, stern, port,
    starboard), of grid depth plus tide minus draft. Land is graded by its
    height. A nodata cell or a position off the grid is the void
    (:data:`VOID_CLEARANCE`), a wall: a boat in the water cannot enter it
    and a boat in the void can only move through the void or into water,
    never onto land or a shoal.
    """

    uses_tide = True

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

    def clearance(self, frame, east, north, step, heading):
        """Return the hull clearance with the boat centred at an offset."""
        direction = (math.sin(heading), math.cos(heading))
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
            value = (VOID_CLEARANCE if depth is None
                     else depth - step.draft)
            least = min(least, value)
        return max(least, VOID_CLEARANCE)

    def correct(self, step, lat, lon):
        frame = self._frame(*step.prev)
        east, north = offset_en(step.prev[0], step.prev[1], lat, lon)
        before = self.clearance(frame, 0.0, 0.0, step, step.prev_heading)
        step.in_void = before <= VOID_CLEARANCE

        def acceptable(clearance):
            if clearance >= 0.0:
                return True
            if before <= VOID_CLEARANCE:
                return clearance <= VOID_CLEARANCE
            # Aground already is not a reason to stay: a boat may go
            # anywhere that is not shallower than where it is.
            return clearance >= before

        after = self.clearance(frame, east, north, step, step.heading)
        if acceptable(after):
            return lat, lon, []

        h = self.cell
        ge = (self.clearance(frame, east + h, north, step, step.heading)
              - self.clearance(frame, east - h, north, step, step.heading))
        gn = (self.clearance(frame, east, north + h, step, step.heading)
              - self.clearance(frame, east, north - h, step, step.heading))
        norm = math.hypot(ge, gn)
        distance = math.hypot(east, north)
        if norm > 0.0:
            normal = (ge / norm, gn / norm)
        elif distance > 0.0:
            normal = (-east / distance, -north / distance)
        else:
            normal = (-math.sin(step.heading), -math.cos(step.heading))

        depth = self._depth(frame, east, north, step.tide)
        contact = Contact(KIND_TERRAIN, '', normal, (0.0, 0.0),
                          math.nan if depth is None else depth)

        # The way to be as far along as allowed, best first: the shallower
        # going part of the motion removed; no motion; then the same with the
        # heading put back (a turn that swings the hull onto land is a
        # motion into it too).
        candidates = []
        along = east * normal[0] + north * normal[1]
        slid = None
        if norm > 0.0 and along < 0.0:
            slid = (east - along * normal[0], north - along * normal[1])
            candidates.append((slid, step.heading))
        candidates.append(((0.0, 0.0), step.heading))
        if step.heading != step.prev_heading:
            if slid is not None:
                candidates.append((slid, step.prev_heading))
        candidates.append(((0.0, 0.0), step.prev_heading))
        for (e, n), heading in candidates:
            # The last candidate (stay, old heading) is where the boat was:
            # always acceptable, so the loop always returns.
            stay = heading == step.prev_heading and (e, n) == (0.0, 0.0)
            if stay or acceptable(
                    self.clearance(frame, e, n, step, heading)):
                step.heading = heading
                new_lat, new_lon = move_en(
                    step.prev[0], step.prev[1], e, n)
                return new_lat, new_lon, [contact]


class ChartedObjectSource:
    """Charted objects (piers, pontoons, piles, buoys, rocks, wrecks).

    Obstacles are :class:`asv_sim.charts.Primitive` tuples in a local metric
    frame: a circle (a segment of no length) or a segment with a half-width.
    The hull capsule is tested against each primitive near it; a primitive
    with a charted ``depth`` only blocks a boat while that depth plus the
    tide is less than the boat's draft, the rest block at every tide. The
    contact is named by the object class (``other`` of the event).

    :param primitives: Iterable of ``Primitive``.
    :param project: ``project(lat, lon) -> (x, y)`` in the primitives' frame
        (radians in, metres out).
    """

    uses_tide = True

    def __init__(self, primitives, project):
        self.project = project
        self.primitives = list(primitives)
        self.buckets = {}
        for index, p in enumerate(self.primitives):
            x0, x1 = sorted((p.x0, p.x1))
            y0, y1 = sorted((p.y0, p.y1))
            for ix in range(math.floor((x0 - p.radius) / BUCKET),
                            math.floor((x1 + p.radius) / BUCKET) + 1):
                for iy in range(math.floor((y0 - p.radius) / BUCKET),
                                math.floor((y1 + p.radius) / BUCKET) + 1):
                    self.buckets.setdefault((ix, iy), []).append(index)

    def _near(self, x, y, reach):
        found = set()
        for ix in range(math.floor((x - reach) / BUCKET),
                        math.floor((x + reach) / BUCKET) + 1):
            for iy in range(math.floor((y - reach) / BUCKET),
                            math.floor((y + reach) / BUCKET) + 1):
                found.update(self.buckets.get((ix, iy), ()))
        return found

    def correct(self, step, lat, lon):
        contacts = {}
        reach = step.length + step.beam
        for _ in range(3):
            x, y = self.project(lat, lon)
            if not _finite(x, y):
                break
            moved = False
            for index in sorted(self._near(x, y, reach)):
                p = self.primitives[index]
                if p.depth is not None \
                        and p.depth + step.tide - step.draft >= 0.0:
                    continue
                mine = capsule_axis((x, y), step.heading, step.length,
                                    step.beam)
                hit = capsule_penetration(
                    mine, ((p.x0, p.y0), (p.x1, p.y1), p.radius))
                if hit is None:
                    continue
                depth, normal = hit
                lat, lon = move_en(
                    lat, lon, normal[0] * depth, normal[1] * depth)
                x += normal[0] * depth
                y += normal[1] * depth
                contact = Contact(
                    KIND_OBJECT, p.klass, normal, (0.0, 0.0), math.nan)
                contacts[_contact_key(contact)] = contact
                moved = True
            if not moved:
                break
        return lat, lon, list(contacts.values())


class Collisions:
    """Resolve contacts for every registered boat.

    :param grid: A ``mbes_sim.bathy_grid.BathyGrid`` (or anything with
        ``getXY``, ``getDepth`` and ``geoTransform``), or ``None`` for no
        terrain.
    :param boats: ``False`` lets boats pass through each other.
    :param objects: A :class:`ChartedObjectSource`, or ``None``.
    :param emit: Called with one dict per contact onset.
    :param logger: Object with ``info`` and ``warning``.
    """

    def __init__(self, grid=None, boats=True, emit=None, logger=None,
                 objects=None):
        self.dynamics = {}
        self.emit = emit
        self.logger = logger
        self.sources = []
        if boats:
            self.sources.append(BoatSource(self))
        # Boats, charted objects, then terrain: where they disagree (a boat
        # between a pier and the shore) the bottom has the last word.
        if objects is not None:
            self.sources.append(objects)
        if grid is not None:
            self.sources.append(TerrainSource(grid))
        self._last_seen = {}
        self._warned = set()

    def register(self, dyn):
        """Add a boat; its ``name`` must be unique."""
        self.dynamics[dyn.name] = dyn

    def resolve(self, dyn, last_lat, last_lon, timestamp, delta_t,
                last_heading=None):
        """Correct ``dyn`` after a sub-step that took it from ``last``.

        Position, heading (only to put a turn into land back), speed and
        acceleration of ``dyn`` are changed in place; nothing else is. A
        long hop is checked in pieces no longer than a fraction of the beam.
        """
        if not self.sources or not delta_t:
            return
        if last_heading is None:
            last_heading = dyn.heading
        if not _finite(dyn.latitude, dyn.longitude, dyn.heading, dyn.speed,
                       last_lat, last_lon, last_heading):
            return
        tide = 0.0
        if dyn.environment is not None and any(
                getattr(s, 'uses_tide', False) for s in self.sources):
            tide = dyn.environment.getTide(timestamp)

        east, north = offset_en(last_lat, last_lon,
                                dyn.latitude, dyn.longitude)
        turn = (dyn.heading - last_heading + math.pi) % (2.0 * math.pi) \
            - math.pi
        hops = max(1, min(MAX_HOPS, math.ceil(
            math.hypot(east, north) / (MAX_HOP_BEAMS * dyn.model.beam))))

        if hops == MAX_HOPS and math.hypot(east, north) > (
                MAX_HOPS * MAX_HOP_BEAMS * dyn.model.beam):
            self._warn_once(
                ('hops', dyn.name),
                'asv_sim platform {!r}: one step moved {:.0f} m, more than '
                'contact can check in {} hops; thin obstacles may be '
                'jumped'.format(dyn.name, math.hypot(east, north), MAX_HOPS))
        position = (last_lat, last_lon)
        heading = last_heading
        reverted = False
        contacts = {}
        in_void = False
        for k in range(1, hops + 1):
            target = move_en(position[0], position[1],
                             east / hops, north / hops)
            wanted = last_heading + turn * k / hops
            position, heading, found, void = self._hop(
                dyn, position, heading, target, wanted, tide)
            if heading != wanted:
                reverted = True
            in_void = in_void or void
            for contact in found:
                contacts[_contact_key(contact)] = contact
        lat, lon = position
        # Only a heading a source put back replaces the dynamics' own.
        heading = heading % (2.0 * math.pi) if reverted else dyn.heading
        if not _finite(lat, lon, heading):
            raise ArithmeticError('contact moved the boat to a non-finite '
                                  'pose')

        if in_void:
            self._warn_void(dyn)
        if not contacts:
            return

        attempted = (east / delta_t, north / delta_t)
        forward = (math.sin(heading), math.cos(heading))
        speed0 = dyn.speed
        closings = []
        keep = 1.0
        for contact in contacts.values():
            normal = contact.normal
            relative = (attempted[0] - contact.other_velocity[0],
                        attempted[1] - contact.other_velocity[1])
            closings.append(max(0.0, -(relative[0] * normal[0]
                                       + relative[1] * normal[1])))
            along = forward[0] * normal[0] + forward[1] * normal[1]
            if speed0 * along < 0.0:
                # The most restrictive contact decides: a corner stops the
                # boat as the wall it faces does, and the many hops and
                # passes of one grind along a buoy do not compound.
                keep = min(keep, 1.0 - along * along)
        dyn.speed = speed0 * keep
        if reverted:
            dyn.yaw_rate = 0.0
        dyn.latitude, dyn.longitude, dyn.heading = lat, lon, heading
        dyn.a += (dyn.speed - speed0) / delta_t
        for contact, closing in zip(contacts.values(), closings):
            try:
                self._report(dyn, contact, closing, lat, lon, timestamp)
            except Exception as e:  # noqa: B902 - the boat is already fixed
                self._warn_once(
                    ('report', dyn.name),
                    'asv_sim platform {!r}: reporting a contact failed '
                    '({}: {})'.format(dyn.name, type(e).__name__, e))

    def _hop(self, dyn, prev, prev_heading, target, heading, tide):
        """Run the sources over one hop; return pose, contacts, void flag."""
        step = _Step(dyn, prev, prev_heading, heading, tide)
        lat, lon = target
        contacts = {}
        void = False
        for _ in range(MAX_PASSES):
            moved = False
            for source in self.sources:
                new_lat, new_lon, found = source.correct(step, lat, lon)
                if (new_lat, new_lon) != (lat, lon):
                    moved = True
                lat, lon = new_lat, new_lon
                for contact in found:
                    contacts[_contact_key(contact)] = contact
            void = void or step.in_void
            # Only boats and terrain together can undo each other's push.
            if not moved or len(self.sources) < 2:
                break
        return (lat, lon), step.heading, list(contacts.values()), void

    def _warn_void(self, dyn):
        self._warn_once(
            ('void', dyn.name),
            'asv_sim platform {!r} is on a no-data cell or off the bathymetry '
            'grid: terrain collision cannot stop it there, and keeps it off '
            'land and shoals until it is in charted water'.format(dyn.name))

    def _warn_once(self, key, message):
        if key in self._warned:
            return
        self._warned.add(key)
        if self.logger is not None:
            self.logger.warning(message)

    def _report(self, dyn, contact, closing, lat, lon, timestamp):
        key = (dyn.name, contact.kind, contact.other)
        now = timestamp.nanoseconds
        last = self._last_seen.get(key)
        onset = last is None or now - last > CONTACT_RELEASE_NS
        if onset:
            if self.logger is not None:
                if contact.kind == KIND_BOAT:
                    what = 'boat ' + contact.other
                elif contact.kind == KIND_OBJECT:
                    what = 'charted object ' + contact.other
                else:
                    what = 'the bottom or shore'
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
        self._last_seen[key] = now
