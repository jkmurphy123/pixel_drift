from .constants import QueenState


def update_workers(world, dt: float):
    speed = world.config.ant_speed_tiles_per_sec
    active_target = world.get_active_dig_target()
    active_diggers = max(3, min(6, len(world.ants) // 2))

    for index, ant in enumerate(world.ants):
        if active_target is not None and index < active_diggers:
            _update_digger(world, ant, active_target, speed, dt)
        elif world.has_open_tunnel():
            _update_tunnel_wanderer(world, ant, speed, dt)
        else:
            _update_surface_wanderer(world, ant, speed, dt)


def _update_digger(world, ant, target, speed: float, dt: float):
    route = world.get_route_to_active_face()
    support_x, support_y = route[-1]
    if _move_along_route(ant, route, speed, dt):
        ant.state = 1
        return

    target_x = target[0] + 0.5
    target_y = target[1] + 0.45
    dx = target_x - support_x
    dy = target_y - support_y
    dist_sq = (ant.x - support_x) ** 2 + (ant.y - support_y) ** 2

    if dist_sq <= 0.30 * 0.30:
        ant.state = 2
        ant.vx = 0.25 if dx >= 0 else -0.25 if dx < 0 else 0.0
        ant.vy = 0.15 if dy >= 0 else -0.15 if dy < 0 else 0.0
        world.apply_dig_work(dt)
        return

    ant.state = 1
    _move_toward_point(ant, support_x, support_y, speed * 0.6, dt, world)


def _update_surface_wanderer(world, ant, speed: float, dt: float):
    left_bound = 1.0
    right_bound = world.cols - 2.0
    upper_bound = max(0.5, world.surface_row - 2.4)
    lower_bound = max(upper_bound + 0.2, world.surface_row - 0.35)

    ant.wander_timer -= dt
    if ant.wander_timer <= 0.0:
        ant.wander_timer = world.rng.uniform(0.35, 1.2)
        ant.vx += world.rng.uniform(-0.85, 0.85)
        ant.vy += world.rng.uniform(-0.25, 0.25)

    if abs(ant.vx) < 0.15:
        ant.vx = 0.15 if ant.vx >= 0 else -0.15

    ant.vx = max(-1.0, min(1.0, ant.vx))
    ant.vy = max(-0.35, min(0.35, ant.vy))

    ant.x += ant.vx * speed * dt
    ant.y += ant.vy * speed * 0.35 * dt

    if ant.x < left_bound:
        ant.x = left_bound
        ant.vx = abs(ant.vx)
    elif ant.x > right_bound:
        ant.x = right_bound
        ant.vx = -abs(ant.vx)

    if ant.y < upper_bound:
        ant.y = upper_bound
        ant.vy = abs(ant.vy)
    elif ant.y > lower_bound:
        ant.y = lower_bound
        ant.vy = -abs(ant.vy)

    ant.state = 0


def _update_tunnel_wanderer(world, ant, speed: float, dt: float):
    route = world.get_carved_route_points()
    if len(route) < 2:
        _update_surface_wanderer(world, ant, speed, dt)
        return

    if ant.wander_timer <= 0.0 or ant.route_target_index < 0 or ant.route_target_index >= len(route):
        ant.wander_timer = world.rng.uniform(0.6, 1.8)
        nearest_idx = _nearest_route_index(route, ant.x, ant.y)
        offset = world.rng.choice((-1, 1))
        candidate = nearest_idx + offset * world.rng.randint(1, min(4, len(route) - 1))
        ant.route_target_index = max(0, min(len(route) - 1, candidate))
    else:
        ant.wander_timer -= dt

    nearest_idx = _nearest_route_index(route, ant.x, ant.y)
    if ant.route_target_index == nearest_idx and len(route) > 1:
        ant.route_target_index = max(0, min(len(route) - 1, nearest_idx + world.rng.choice((-1, 1))))

    if ant.route_target_index > nearest_idx:
        next_idx = nearest_idx + 1
    elif ant.route_target_index < nearest_idx:
        next_idx = nearest_idx - 1
    else:
        next_idx = ant.route_target_index

    target_x, target_y = route[next_idx]
    _move_toward_point(ant, target_x, target_y, speed * 0.55, dt, world)
    ant.state = 0


def _move_along_route(ant, route, speed: float, dt: float):
    if len(route) <= 1:
        return False

    nearest_idx = _nearest_route_index(route, ant.x, ant.y)
    if nearest_idx < len(route) - 1:
        target_x, target_y = route[nearest_idx + 1]
        dx = target_x - ant.x
        dy = target_y - ant.y
        if dx * dx + dy * dy > 0.18 * 0.18:
            _move_toward_point_raw(ant, target_x, target_y, speed, dt)
            return True

    target_x, target_y = route[-1]
    dx = target_x - ant.x
    dy = target_y - ant.y
    if dx * dx + dy * dy > 0.18 * 0.18:
        _move_toward_point_raw(ant, target_x, target_y, speed, dt)
        return True
    return False


def _nearest_route_index(route, x: float, y: float):
    best_idx = 0
    best_dist = None
    for idx, (px, py) in enumerate(route):
        dist = (px - x) * (px - x) + (py - y) * (py - y)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_idx = idx
    return best_idx


def _move_toward_point(ant, target_x: float, target_y: float, speed: float, dt: float, world):
    _move_toward_point_raw(ant, target_x, target_y, speed, dt)
    ant.x = max(1.0, min(world.cols - 2.0, ant.x))
    ant.y = max(0.5, min(world.rows - 1.5, ant.y))


def _move_toward_point_raw(ant, target_x: float, target_y: float, speed: float, dt: float):
    dx = target_x - ant.x
    dy = target_y - ant.y
    dist = max(0.0001, (dx * dx + dy * dy) ** 0.5)
    ant.vx = dx / dist
    ant.vy = dy / dist
    ant.x += ant.vx * speed * dt
    ant.y += ant.vy * speed * dt


def update_queen(world, dt: float):
    queen = world.queen
    if queen.state == QueenState.SURFACE_WAIT:
        queen.x = world.entrance_col + 0.5
        queen.y = max(0.8, world.surface_row - 1.3)
        return

    if queen.state == QueenState.RELOCATE_TO_CHAMBER:
        route = world.get_queen_route_points()
        if _move_entity_along_route(queen, route, 0.7, dt):
            return
        queen.state = QueenState.SETTLED
        queen.x, queen.y = world.queen_chamber_center
        return

    settle_x, settle_y = world.queen_chamber_center
    queen.x += (settle_x - queen.x) * min(1.0, dt * 0.9)
    queen.y += (settle_y - queen.y) * min(1.0, dt * 0.9)


def _move_entity_along_route(entity, route, speed: float, dt: float):
    if len(route) <= 1:
        return False

    nearest_idx = _nearest_route_index(route, entity.x, entity.y)
    if nearest_idx < len(route) - 1:
        target_x, target_y = route[nearest_idx + 1]
    else:
        target_x, target_y = route[-1]

    dx = target_x - entity.x
    dy = target_y - entity.y
    if dx * dx + dy * dy <= 0.18 * 0.18 and nearest_idx >= len(route) - 2:
        return False

    _move_toward_point_raw(entity, target_x, target_y, speed, dt)
    return True
