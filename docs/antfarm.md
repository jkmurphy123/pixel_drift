AGENTS.md
Project description

This repository contains a plugin mode for a kiosk slideshow system that simulates a 2D ant farm colony.
The simulation renders a side-view cross section of soil where ants dig tunnels and chambers over time.

The system must run autonomously with no user input and operate efficiently on Raspberry Pi–class hardware.

The goal is visual plausibility, not biological accuracy.

Agent role

You are a simulation systems engineer responsible for implementing a tile-based colony simulator.

Priorities:

coherent nest growth

stable performance

visually readable simulation

deterministic behavior

modular architecture

Avoid over-engineering biological realism.

Technology assumptions

Language: Python

Graphics assumptions:

The simulation will run inside an existing slideshow/plugin system that likely uses one of:

pygame

pygame-ce

SDL wrapper

simple frame buffer rendering

Rendering must use geometric primitives only:

rectangles

circles

ellipses

lines

No bitmap sprites.

Core architecture

The ant farm mode must be implemented as a self-contained simulation module.

Recommended modules:

antfarm/
    __init__.py
    antfarm_mode.py
    world.py
    entities.py
    behavior.py
    planner.py
    render.py
    config.py
    constants.py

Responsibilities:

antfarm_mode.py

Plugin entrypoint.

Responsible for:

initialization

config loading

simulation loop

rendering calls

Main methods:

initialize(config)
update(dt)
render(surface)
reset()
world.py

Contains world state.

Responsibilities:

tile grid

pheromone fields

colony jobs

terrain mutation

Core class:

World

Attributes:

width
height
tiles
pheromone_fields
ants
queen
entrance_position
colony_phase
active_jobs
rng
entities.py

Defines ant entities.

Classes:

WorkerAnt
QueenAnt

Worker fields:

id
x
y
state
heading
carrying_soil
dig_progress
target_job

Queen fields:

x
y
state
target_chamber
behavior.py

Worker state machine logic.

States:

WANDER
SEEK_DIG_SITE
DIG
CARRY_SOIL
DROP_SOIL
IDLE

Behavior rules should use local information only whenever possible.

planner.py

Colony-level planning system.

This module produces digging jobs that shape the nest.

Job types:

DIG_MAIN_SHAFT
CREATE_QUEEN_CHAMBER
DIG_BRANCH_TUNNEL
EXPAND_CHAMBER
MAINTAIN_AREA

The planner should update infrequently (every few seconds).

Workers simply react to nearby job signals.

render.py

Responsible for all drawing.

Rendering rules:

Soil

brown rectangles

Tunnels

dark voids

Chambers

slightly lighter floors

Ants

Workers:

small circles or ellipses

Queen:

larger oval

Rendering must avoid expensive operations.

config.py

Handles configuration parameters.

Required parameters:

worker_count
orientation

Optional parameters:

seed
dig_speed
branchiness
chamber_frequency
sim_ticks_per_second
surface_height_ratio
constants.py

Contains enums and default values.

Examples:

TileType
AntState
ColonyPhase
JobType
World design

The simulation is a tilemap grid.

Suggested default sizes:

Portrait:

48 x 80

Landscape:

80 x 48

Top rows represent surface air.

Below is soil.

Tile types
AIR
SURFACE
SOIL
TUNNEL
CHAMBER
LOOSE_SOIL
SPOIL_PILE

Optional tile attributes:

hardness
support
chamber_id
Pheromone fields

Maintain scalar fields per tile.

Fields:

dig_pheromone
traffic_pheromone
queen_pheromone

Behavior:

diffuse slightly

decay slowly

influence worker decisions

Keep implementation lightweight.

Colony phases

The colony progresses through stages.

Phase 1 — Founding

Workers begin digging downward.

Goal:

create entrance shaft
Phase 2 — Queen chamber

Once depth threshold reached:

Workers create a larger chamber.

After chamber completion:

Queen relocates into chamber.

Phase 3 — Expansion

Workers begin branching tunnels.

New chambers appear.

Traffic concentrates along established routes.

Phase 4 — Maintenance

Workers expand tunnels and smooth chambers.

Simulation continues indefinitely.

Digging rules

Workers may dig only soil adjacent to tunnel or air.

Excavation process:

target tile
dig for N ticks
convert tile to tunnel
optionally create loose soil
carry soil upward
deposit near entrance
Structural constraints

To avoid chaotic nests enforce:

tunnel continuity preference

branch probability limit

chamber spacing

avoid surface breaches

avoid massive open cavities

These rules are critical.

Queen behavior

States:

SURFACE_WAIT
RELOCATE_TO_CHAMBER
SETTLED

Behavior:

waits near entrance

moves once chamber ready

emits strong queen pheromone after settling

Movement model

Avoid expensive pathfinding.

Preferred system:

local tile scanning

pheromone gradient following

heading bias

occasional random deviation

A simple pathfinder may be used only for queen relocation.

Simulation loop

Recommended structure:

update_pheromones()
planner_update_if_needed()
update_ants()
apply_digging()
update_colony_phase()
render()

Simulation tick rate may be lower than render rate.

Example:

render: 30 FPS
simulation: 8 ticks/sec
Determinism

Support deterministic runs using:

random_seed

This helps debugging and reproducibility.

Performance requirements

The simulation must:

run continuously

avoid heavy pathfinding

use tile updates only where necessary

minimize per-frame allocations

Target hardware:

Raspberry Pi Zero / Pi 4 class devices
Development milestones
Milestone 1

Basic rendering.

soil grid

moving ants

surface strip

Milestone 2

Excavation.

entrance tunnel

connected digging

tile updates

Milestone 3

Queen chamber event.

chamber carving

queen relocation

Milestone 4

Colony expansion.

side tunnels

additional chambers

job planner

Milestone 5

Visual polish.

spoil pile

smoother chambers

pheromone tuning

orientation tuning

Debug tools

Include optional debug overlays:

tile types
pheromone heatmap
colony phase
job locations
ant states

These should be toggleable.

Acceptance criteria

The plugin is considered complete when:

ants autonomously dig tunnels

a queen chamber forms

queen relocates underground

tunnels expand over time

simulation runs indefinitely

portrait and landscape both work

performance remains stable

Implementation guidelines

Favor:

modular architecture

deterministic simulation

simple math

clarity over complexity

Avoid:

expensive pathfinding

high-resolution physics

excessive biological realism

The simulation should create the illusion of a living ant colony rather than simulate exact insect behavior.

When uncertain

If any design decision is unclear:

propose a short plan

prefer simpler implementation

ensure tunnels/chambers remain visually coherent
