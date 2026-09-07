# core/mapdraw.py
#
# Shared equirectangular map drawing helpers for pygame modes.
# Projection matches the one used by mission control and the satellite
# tracker: lon -180..180 -> rect width, lat 90..-90 -> rect height.

import pygame


def latlon_to_xy(rect: pygame.Rect, lat: float, lon: float):
    x = rect.left + int(((lon + 180.0) / 360.0) * rect.width)
    y = rect.top + int(((90.0 - lat) / 180.0) * rect.height)
    return x, y


def draw_latlon_polyline(screen, rect: pygame.Rect, latlons, color, width: int = 1):
    """
    Draw a polyline through [(lat, lon), ...], splitting segments at the
    antimeridian so lines crossing lon +/-180 don't smear horizontally
    across the whole map.
    """
    seg = []
    prev_lon = None
    for lat, lon in latlons:
        if prev_lon is not None and abs(lon - prev_lon) > 180.0:
            if len(seg) >= 2:
                pygame.draw.lines(screen, color, False, seg, width)
            seg = []
        seg.append(latlon_to_xy(rect, lat, lon))
        prev_lon = lon
    if len(seg) >= 2:
        pygame.draw.lines(screen, color, False, seg, width)
