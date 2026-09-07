# core/orbit.py
#
# Orbit propagation helpers for the satellite tracker mode, built on the
# `sgp4` package. Everything here is pure math on datetimes — no pygame,
# no network — so it is fully unit-testable headless.
#
# Accuracy notes (fine for a world-map kiosk display):
# - TEME -> "pseudo-ECEF" uses a plain GMST rotation, ignoring polar
#   motion and nutation. Error is tens of meters to ~1 km — invisible on
#   a world map.
# - The subsolar point uses the standard NOAA approximations (~0.1 deg).

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sgp4.api import Satrec, jday

EARTH_RADIUS_KM = 6371.0
WGS84_A_KM = 6378.137          # equatorial radius
WGS84_F = 1.0 / 298.257223563  # flattening


# ---------------------------------------------------------------------------
# Time / frame helpers
# ---------------------------------------------------------------------------

def _jd_fr(when: datetime):
    """UTC datetime -> (julian day, fraction) pair used by sgp4."""
    when = when.astimezone(timezone.utc)
    return jday(when.year, when.month, when.day, when.hour, when.minute,
                when.second + when.microsecond / 1e6)


def gmst_rad(when: datetime) -> float:
    """Greenwich mean sidereal time (IAU 1982 approximation), radians."""
    jd, fr = _jd_fr(when)
    d = (jd + fr) - 2451545.0
    return math.radians((280.46061837 + 360.98564736629 * d) % 360.0)


# ---------------------------------------------------------------------------
# Orbit
# ---------------------------------------------------------------------------

@dataclass
class SubPoint:
    lat: float      # degrees, geocentric (good enough at map scale)
    lon: float      # degrees, -180..180
    alt_km: float
    vel_kmh: float


class Orbit:
    """One satellite's orbit, propagated from a TLE via SGP4."""

    def __init__(self, name: str, norad_id: int, line1: str, line2: str):
        self.name = name
        self.norad_id = int(norad_id)
        self.line1 = line1
        self.line2 = line2
        self._sat = Satrec.twoline2rv(line1, line2)

    # -- orbital element conveniences ------------------------------------

    @property
    def period_minutes(self) -> float:
        # sat.no_kozai is mean motion in radians/minute
        return 2.0 * math.pi / self._sat.no_kozai

    @property
    def inclination_deg(self) -> float:
        return math.degrees(self._sat.inclo)

    @property
    def mean_motion_rev_day(self) -> float:
        return self._sat.no_kozai * 1440.0 / (2.0 * math.pi)

    # -- propagation ------------------------------------------------------

    def ecef(self, when: datetime):
        """
        Pseudo-ECEF position (x, y, z) in km, or None if SGP4 reports an
        error at this time (decayed/invalid element set).
        """
        jd, fr = _jd_fr(when)
        err, r, v = self._sat.sgp4(jd, fr)
        if err != 0:
            return None
        g = gmst_rad(when)
        x = r[0] * math.cos(g) + r[1] * math.sin(g)
        y = -r[0] * math.sin(g) + r[1] * math.cos(g)
        return (x, y, r[2])

    def velocity_kmh(self, when: datetime):
        jd, fr = _jd_fr(when)
        err, r, v = self._sat.sgp4(jd, fr)
        if err != 0:
            return None
        return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) * 3600.0

    def subpoint(self, when: datetime):
        """Sub-satellite point, or None on propagation error."""
        pos = self.ecef(when)
        vel = self.velocity_kmh(when)
        if pos is None or vel is None:
            return None
        x, y, z = pos
        rmag = math.sqrt(x * x + y * y + z * z)
        return SubPoint(
            lat=math.degrees(math.asin(z / rmag)),
            lon=math.degrees(math.atan2(y, x)),
            alt_km=rmag - EARTH_RADIUS_KM,
            vel_kmh=vel,
        )

    def ground_track(self, when: datetime, before_min: float, after_min: float,
                     step_s: float = 30.0):
        """
        Ground track as a list of (lat, lon) spanning
        [when - before_min, when + after_min]. Points that fail to
        propagate are skipped.
        """
        pts = []
        t0 = when - timedelta(minutes=before_min)
        steps = int((before_min + after_min) * 60.0 / step_s) + 1
        for i in range(steps):
            sp = self.subpoint(t0 + timedelta(seconds=step_s * i))
            if sp is not None:
                pts.append((sp.lat, sp.lon))
        return pts

    def footprint_circle(self, lat: float, lon: float, alt_km: float, n: int = 48):
        """
        Visibility footprint: the circle of points on the surface from
        which the satellite is on the horizon, as (lat, lon) pairs.
        """
        rho = footprint_radius_deg(alt_km)  # angular radius of the circle
        lat1 = math.radians(lat)
        lon1 = math.radians(lon)
        d = math.radians(rho)
        pts = []
        for i in range(n):
            bearing = 2.0 * math.pi * i / n
            lat2 = math.asin(
                math.sin(lat1) * math.cos(d)
                + math.cos(lat1) * math.sin(d) * math.cos(bearing)
            )
            lon2 = lon1 + math.atan2(
                math.sin(bearing) * math.sin(d) * math.cos(lat1),
                math.cos(d) - math.sin(lat1) * math.sin(lat2),
            )
            pts.append((math.degrees(lat2), math.degrees(lon2)))
        return pts


def footprint_radius_deg(alt_km: float) -> float:
    """Angular radius (deg) of the horizon circle seen from altitude."""
    alt_km = max(1.0, alt_km)
    return math.degrees(math.acos(EARTH_RADIUS_KM / (EARTH_RADIUS_KM + alt_km)))


# ---------------------------------------------------------------------------
# Day/night
# ---------------------------------------------------------------------------

def subsolar_point(when: datetime):
    """
    (lat, lon) of the point where the sun is directly overhead.
    NOAA solar-position approximations — good to ~0.1 degree.
    """
    when = when.astimezone(timezone.utc)
    n = when.timetuple().tm_yday
    hour = when.hour + when.minute / 60.0 + when.second / 3600.0
    gamma = 2.0 * math.pi / 365.0 * (n - 1 + (hour - 12.0) / 24.0)

    eqtime_min = 229.18 * (
        0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma)
    )
    decl = (
        0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma)
    )
    utc_minutes = when.hour * 60 + when.minute + when.second / 60.0
    lon = -(utc_minutes + eqtime_min - 720.0) / 4.0
    lon = ((lon + 180.0) % 360.0) - 180.0
    return math.degrees(decl), lon


def is_night(lat: float, lon: float, sun_lat: float, sun_lon: float) -> bool:
    """True if the sun is below the horizon at (lat, lon)."""
    phi = math.radians(lat)
    delta = math.radians(sun_lat)
    h = math.radians(lon - sun_lon)
    cos_zenith = math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.cos(h)
    return cos_zenith < -0.05  # small buffer ~ civil twilight


# ---------------------------------------------------------------------------
# Observer look angles & pass prediction
# ---------------------------------------------------------------------------

def geodetic_to_ecef(lat_deg: float, lon_deg: float, h_km: float = 0.0):
    """WGS84 geodetic -> ECEF (km)."""
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    e2 = WGS84_F * (2.0 - WGS84_F)
    n = WGS84_A_KM / math.sqrt(1.0 - e2 * math.sin(lat) ** 2)
    x = (n + h_km) * math.cos(lat) * math.cos(lon)
    y = (n + h_km) * math.cos(lat) * math.sin(lon)
    z = (n * (1.0 - e2) + h_km) * math.sin(lat)
    return (x, y, z)


def look_angles(sat_ecef, obs_lat: float, obs_lon: float):
    """
    (azimuth_deg, elevation_deg, range_km) of a satellite ECEF position
    as seen from an observer at geodetic (obs_lat, obs_lon).
    """
    ox, oy, oz = geodetic_to_ecef(obs_lat, obs_lon)
    dx, dy, dz = sat_ecef[0] - ox, sat_ecef[1] - oy, sat_ecef[2] - oz

    lat = math.radians(obs_lat)
    lon = math.radians(obs_lon)
    # ENU basis vectors at the observer
    east = (-math.sin(lon), math.cos(lon), 0.0)
    north = (-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon), math.cos(lat))
    up = (math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat))

    e = dx * east[0] + dy * east[1] + dz * east[2]
    n_ = dx * north[0] + dy * north[1] + dz * north[2]
    u = dx * up[0] + dy * up[1] + dz * up[2]

    rng = math.sqrt(e * e + n_ * n_ + u * u)
    el = math.degrees(math.asin(u / rng))
    az = math.degrees(math.atan2(e, n_)) % 360.0
    return az, el, rng


@dataclass
class Pass:
    aos: datetime       # acquisition of signal (rises above horizon)
    los: datetime       # loss of signal (sets below horizon)
    max_elev_deg: float

    @property
    def duration_s(self) -> float:
        return (self.los - self.aos).total_seconds()


def _elevation_at(orbit: Orbit, obs_lat, obs_lon, when):
    pos = orbit.ecef(when)
    if pos is None:
        return None
    return look_angles(pos, obs_lat, obs_lon)[1]


def _refine_crossing(orbit: Orbit, obs_lat, obs_lon, t_below, t_above, min_el):
    """Bisect between two sample times to ~1 s crossing accuracy."""
    for _ in range(6):
        mid = t_below + (t_above - t_below) / 2
        el = _elevation_at(orbit, obs_lat, obs_lon, mid)
        if el is not None and el >= min_el:
            t_above = mid
        else:
            t_below = mid
    return t_above


def predict_passes(orbit: Orbit, obs_lat: float, obs_lon: float,
                   start: datetime, hours: float = 24.0,
                   step_s: float = 30.0, min_elev_deg: float = 0.0):
    """
    All passes above `min_elev_deg` in [start, start + hours], computed by
    stepping SGP4 and bisecting horizon crossings. One-time cost per call
    is a few thousand propagations — sub-second on a Pi.
    """
    passes = []
    t = start
    end = start + timedelta(hours=hours)
    step = timedelta(seconds=step_s)

    prev_t = t
    prev_el = _elevation_at(orbit, obs_lat, obs_lon, t)
    in_pass = prev_el is not None and prev_el >= min_elev_deg
    aos = _refine_crossing(orbit, obs_lat, obs_lon, t - step, t, min_elev_deg) if in_pass else None
    max_el = prev_el if in_pass else None

    while t < end:
        t += step
        el = _elevation_at(orbit, obs_lat, obs_lon, t)
        if el is None:
            prev_t, prev_el = t, None
            continue

        if not in_pass and el >= min_elev_deg and prev_el is not None:
            in_pass = True
            aos = _refine_crossing(orbit, obs_lat, obs_lon, prev_t, t, min_elev_deg)
            max_el = el
        elif in_pass and aos is not None and max_el is not None:
            max_el = max(max_el, el)
            if el < min_elev_deg:
                in_pass = False
                los = _refine_crossing(orbit, obs_lat, obs_lon, prev_t, t, min_elev_deg)
                passes.append(Pass(aos=aos, los=los, max_elev_deg=max_el))
                aos, max_el = None, None

        prev_t, prev_el = t, el

    if in_pass and aos is not None and max_el is not None:
        # Pass still in progress at the end of the window.
        passes.append(Pass(aos=aos, los=end, max_elev_deg=max_el))
    return passes


# ---------------------------------------------------------------------------
# Target selection (one satellite per day, no state file needed)
# ---------------------------------------------------------------------------

def target_for_date(targets, when: datetime):
    """
    Deterministic one-target-per-day rotation: index = (day-of-year - 1)
    mod len(targets). Same answer all day, advances at midnight, and
    requires no persisted state.
    """
    if not targets:
        return None, -1
    idx = (when.timetuple().tm_yday - 1) % len(targets)
    return targets[idx], idx
