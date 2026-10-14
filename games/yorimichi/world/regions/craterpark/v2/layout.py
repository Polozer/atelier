"""Crater Park v2: the whole park as data (plan/layout.md; owner: the layout agent).

Three lines fall from one tower on the block's high east rim, each with one huge air, into one bowl complex on the low
west side: L1 Crater Line (the Canyon Transfer, ramp to ramp), L2 Serpent Line (snake run, the Rim Gap, a carving berm)
and L3 Valley Line (an inclined half-pipe, the Crater Berm, the Crater Gap). The bowl complex is the Crater Bowl, the
Blue Pool (r4's pool, copied) and the Peanut, linked by spines and a channel into one loop. Respawn returns the rider
to each line's roll-in crest; no pushing path back up.

Frame: native metres, y up; a plan point is (x, z) (dsl.py). Island height = y + 680 (placement.LIFT). Native +x is
roughly island west and native +z island north (placement.HEADING 185 degrees).

Plan paths are turtles: a start (x, z), a heading in degrees (atan2(dz, dx) in the native plan) and segments
('straight', L) or ('turn', R, degrees), a positive turn counter-clockwise in (x, z). A line's distance s runs along
its plan path, and its longitudinal profile is a function of that same s.

Longitudinal profiles use additions.profile semantics: ('line', L) runs L metres of PLAN distance at the current angle,
and ('arc', R, to_degrees) turns on a circle to the absolute angle. ('gap', dx, dy, name) is an open gap of dx plan
metres to a surface dy lower, with no collision. along_parts() converts a piece to dsl.Profile semantics, where a
line's length runs along its slope.

Every jump was ridden on the offline gameplay Session (see MEASURED). Keep the numbers marked "ridden" unless a new
ride proves the change.
"""
import math
from dataclasses import dataclass, field

import numpy as np

LIFT = 680.0            # island z = native y + LIFT


# ---------------------------------------------------------------- data types
@dataclass(frozen=True)
class Turtle:
    """A plan path: start (x, z), heading degrees (atan2(dz, dx)), segments ('straight', L) | ('turn', R, degrees)."""
    start: tuple
    heading: float
    segs: tuple

    @property
    def length(self):
        return sum(s[1] if s[0] == 'straight' else s[1] * math.radians(abs(s[2])) for s in self.segs)

    def pieces(self):
        """[(kind, s0, s1, start (x, z), heading0 degrees, radius, turn degrees)], one per segment."""
        x, z = map(float, self.start); a = math.radians(self.heading); s = 0.; out = []
        for seg in self.segs:
            if seg[0] == 'straight':
                L = float(seg[1]); out.append(('straight', s, s + L, (x, z), math.degrees(a), 0., 0.))
                x += L * math.cos(a); z += L * math.sin(a); s += L
            else:
                R, d = float(seg[1]), math.radians(seg[2]); sg = 1. if d > 0 else -1.
                out.append(('turn', s, s + R * abs(d), (x, z), math.degrees(a), R, seg[2]))
                cx, cz = x - sg * R * math.sin(a), z + sg * R * math.cos(a)
                a += d; x, z = cx + sg * R * math.sin(a), cz - sg * R * math.cos(a); s += R * abs(d)
        return out

    def at(self, s):
        """(point (x, z), unit tangent) at plan distance s (clamped to the path)."""
        ps = self.pieces()
        kind, s0, s1, (x, z), h, R, d = next((p for p in ps if s <= p[2] + 1e-9), ps[-1])
        t = min(max(s - s0, 0.), s1 - s0); a = math.radians(h)
        if kind == 'straight':
            return np.array([x + t * math.cos(a), z + t * math.sin(a)]), np.array([math.cos(a), math.sin(a)])
        sg = 1. if d > 0 else -1.; cx, cz = x - sg * R * math.sin(a), z + sg * R * math.cos(a); b = a + sg * t / R
        return np.array([cx + sg * R * math.sin(b), cz - sg * R * math.cos(b)]), np.array([math.cos(b), math.sin(b)])

    def until(self, s_end):
        """The same path cut at plan distance s_end."""
        segs, s = [], 0.
        for seg in self.segs:
            L = seg[1] if seg[0] == 'straight' else seg[1] * math.radians(abs(seg[2]))
            if s + L >= s_end - 1e-9:
                rest = s_end - s
                if rest > 1e-9:
                    segs.append(('straight', rest) if seg[0] == 'straight' else ('turn', seg[1], math.copysign(math.degrees(rest / seg[1]), seg[2])))
                break
            segs.append(seg); s += L
        return Turtle(self.start, self.heading, tuple(segs))

    def points(self, step=.5):
        s = np.arange(0., self.length + 1e-9, step)
        return np.array([self.at(v)[0] for v in s]), s

    def curves(self):
        """The path as dsl curves (curves.Line and curves.Arc), in order."""
        from .curves import Arc, Line
        out = []
        for kind, s0, s1, (x, z), h, R, d in self.pieces():
            a = math.radians(h)
            if kind == 'straight':
                out.append(Line((x, z), (x + (s1 - s0) * math.cos(a), z + (s1 - s0) * math.sin(a))))
            else:
                sg = 1. if d > 0 else -1.; cx, cz = x - sg * R * math.sin(a), z + sg * R * math.cos(a)
                out.append(Arc((cx, cz), R, math.degrees(math.atan2(z - cz, x - cx)), d))
        return out


@dataclass(frozen=True)
class Feature:
    """A feature on a line, from s0 to s1 (plan metres along the line). `kind` names the primitive (pipeline.md section 4);
    `tag` is the ride tag of its riding faces ('takeoff' on a lip, 'landing' on a landing); `params` its sizes."""
    id: str
    kind: str
    s0: float
    s1: float
    width: float
    tag: str = ''
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LineSpec:
    id: str
    name: str
    path: Turtle
    y0: float                   # profile start height (the tower deck)
    profile: tuple              # additions.profile parts plus ('gap', dx, dy, name); no kinks, no ('angle', ...)
    features: tuple
    entry: str                  # where the rider starts: the roll-in crest (respawn point)
    exit: str                   # where it leads: no dead ends
    airs: tuple = ()            # (takeoff feature id, landing feature id)
    rollin: int = 3             # the first `rollin` profile parts are the tower's roll-in (built by the tower, not here)


@dataclass(frozen=True)
class Bowl:
    """A bowl or pool: plan `centre` (x, z), long `axis` degrees, `size` (length, width) of its coping outline (an
    ellipse unless `copy_from` names a source outline), `rim_y` and `floor_y`, a wall profile (transition radius `r`
    then `vert` metres of vertical), `deck` width behind the coping, `coping` steel, material, and the measured
    straight-on entry speed limit."""
    id: str
    centre: tuple
    axis: float
    size: tuple
    rim_y: float
    floor_y: float
    r: float
    vert: float
    deck: float
    material: str
    coping: bool = True
    max_entry: float = 0.
    copy_from: dict = None
    openings: tuple = ()        # (name, plan point on the rim, kind): where a line or link enters through the rim
    notes: str = ''


@dataclass(frozen=True)
class Link:
    """Bowl-complex connection: a spine (two transitions back to back on a cap), a hip or a channel."""
    id: str
    kind: str
    a: str
    b: str
    path: tuple                 # plan points (x, z) along its crest or centreline
    params: dict = field(default_factory=dict)


# ---------------------------------------------------------------- palette (owner, note 26: dark concrete is out)
PALETTE = {
    'concrete': 'material_010',     # pale concrete: every run, ramp and bowl
    'deck': 'material_000',         # decks and the tower
    'pool': 'material_019',         # blue: the Blue Pool only
    'coping': 'coping_steel',       # bowl lips, the pool and the tower lip
    'wood': 'material_016',
}
FORBIDDEN_MATERIALS = ('material_004',)   # dark concrete

# ---------------------------------------------------------------- the tower
TOWER = {
    'centre': (1146.5, 1136.7),    # island (992, 2541); the world-map travel point moves here
    'size': (26.0, 18.0),          # along native x (island east-west), along native z
    'y': 40.0,                     # island 720
    'cap': 1.5,                    # flat caps on every wall, metres
    'sides': 'earth-banked at 30 degrees to the ground fill; no free-standing walls',
    'roll_ins': {'T1': 'L1', 'T2': 'L2', 'T3': 'L3'},
    'material': 'material_000',    # PALETTE['deck']
}

# The Crater Gap receiver, validated by park-assist (#13450): knuckle R15 to 24 degrees, 16 m, R30 to 34 degrees, 8 m,
# R45 out; 6/6 passes (baseline and ollie, spawns 1/4/8 m/s) at lip 18.25-19.35 m/s. It drops 23.9 m over 55.9 m of plan.
# The shorter receiver (no 34-degree part) failed at a 17.2 m/s lip: keep the lip at 18.25 m/s or more.
CRATER_LANDING = (('arc', 15, -24), ('line', 16), ('arc', 30, -34), ('line', 8), ('arc', 45, -5))

# ---------------------------------------------------------------- L1, the Crater Line (the hero)
L1 = LineSpec(
    id='L1', name='Crater Line',
    path=Turtle(start=(1159.388, 1126.798), heading=322.3, segs=(('straight', 262.),)),
    y0=40.0,
    profile=(('arc', 14, -35), ('line', 31.5), ('arc', 30, 0),       # T1 roll-in: 40 -> 10 (720 -> 690)
             ('line', 14),                                                           # flat run-in (no spawn hop)
             ('arc', 16, 30), ('line', 6.5),                                         # A ramp: lip 30 deg at y 15.88
             ('gap', 22., -1.5, 'J2 Canyon Transfer'),                               # open canyon
             ('arc', 25, -32), ('line', 12), ('arc', 40, -5),                         # B ramp: knuckle y 14.38 -> foot -2.84
             ('line', 100.)),                                                        # run at -5 deg to the Crater Bowl rim
    features=(
        Feature('L1_rollin', 'roll_in', 0., 56.7, 16., '', {'crest_r': 14, 'face_deg': 35, 'runout_r': 30, 'walls': 'channel walls 1.2 m, flat cap 1.0 m, steel coping'}),
        Feature('L1_runin', 'run', 56.7, 70.7, 16., '', {'grade_deg': 0}),
        Feature('L1_A', 'transfer_takeoff', 70.7, 85.2, 16., 'takeoff', {'r': 16, 'lip_deg': 30, 'lip_y': 15.88, 'height': 5.88, 'flanks_deg': 30}),
        Feature('L1_canyon', 'gap', 85.2, 107.2, 22., '', {'open': True, 'ground_max_y': 6.0, 'note': 'canyon floor at least 8 m under the lip; nothing in it'}),
        Feature('L1_B', 'transfer_landing', 107.2, 150.2, 20., 'landing', {'knuckle_y': 14.38, 'knuckle_r': 25, 'slope_deg': 32, 'slope_len': 12, 'runout_r': 40}),
        Feature('L1_run', 'run', 150.2, 250.2, 16., '', {'grade_deg': -5, 'to_y': -11.59}),
        Feature('L1_bowl_entry', 'bowl_entry', 250.2, 262.0, 16., '', {'bowl': 'crater_bowl', 'kind': 'roll-in bank cut in the rim: R12 to 28 deg, R12 out onto the floor'}),
    ),
    entry='T1 crest (1159.39, 40.0, 1126.80)', exit='crater_bowl',
    airs=(('L1_A', 'L1_B'),),
)

# ---------------------------------------------------------------- L3, the Valley Line
L3 = LineSpec(
    id='L3', name='Valley Line',
    path=Turtle(start=(1147.608, 1123.76), heading=275.0, segs=(('straight', 176.), ('turn', 35., 90.), ('straight', 111.))),
    y0=40.0,
    # A slow Valley, then a late drop: at -2 degrees the rider settles at about 12.3 m/s, where rolling drag is near zero,
    # so standing, 4 and 8 m/s starts all reach the K1 lip at the same speed (ridden: 18.6-18.7 m/s, plan/l3v3).
    profile=(('arc', 14, -30), ('line', 2), ('arc', 30, -2),                          # T3 roll-in: 40 -> 33.0
             ('line', 102.624),                                                      # the Valley at -2 deg (slow)
             ('arc', 40, -30), ('line', 16), ('arc', 40, -6),                         # Valley drop: 29.4 -> 9.7
             ('line', 55),                                                           # the Crater Berm (plan turn R35, 90 deg)
             ('arc', 40, -5), ('line', 20),                                          # 20 m straight run-in
             ('arc', 22, 24), ('line', 3),                                           # K1: lip 24 deg at y 5.23
             ('gap', 20., -1.5, 'J1 Crater Gap'),
             *CRATER_LANDING,                                                        # knuckle y 3.73 -> foot -20.14
             ('line', 0.5)),                                                         # onto the Crater Bowl's east floor
    features=(
        Feature('L3_rollin', 'roll_in', 0., 22.95, 22., '', {'crest_r': 14, 'face_deg': 30, 'runout_r': 30}),
        Feature('L3_valley', 'valley', 22.95, 125.58, 22., '', {
            'grade_deg': -2, 'floor': 22., 'wall_r': 25., 'wall_top_deg': 50., 'wall_height': 10., 'cap': 1.5, 'coping': True,
            'speed': 'settles at 12.3 m/s (ridden): carve wall to wall up to about 8 m',
            'source': 'r4 12 m half-pipe (native 1320, 960): 22 m floor, R25-30 walls, about 45 deg at the top'}),
        Feature('L3_drop', 'valley', 125.58, 176., 22., '', {
            'grade_deg': -30, 'floor': 22., 'wall_r': 25., 'wall_height': 6., 'cap': 1.5, 'note': 'the Valley walls run on, lower'}),
        Feature('L3_berm', 'berm', 176., 231., 22., '', {'turn_r': 35., 'turn_deg': 90., 'outer_bank_height': 8., 'outer_wall_r': 20., 'bank_deg': 55.,
                                                          'speed': 'about 21 m/s: bank for v^2/(gR) = 1.3'}),
        Feature('L3_runin', 'run', 231., 251.69, 16., '', {'grade_deg': -5}),
        Feature('L3_K1', 'kicker', 251.69, 265.56, 14., 'takeoff', {'r': 22, 'lip_deg': 24, 'lip_y': 5.23, 'height': 3.15, 'flanks': 'kicker flanks at 30 degrees'}),
        Feature('L3_gap', 'gap', 265.56, 285.56, 20., '', {'open': True, 'ground_max_y': 0.0}),
        Feature('L3_landing', 'landing', 285.56, 341.48, 18., 'landing', {'knuckle_y': 3.73, 'knuckle_r': 15, 'slope_deg': 24, 'slope_len': 16,
                                                                          'steep_deg': 34, 'steep_len': 8, 'runout_r': 45}),
        Feature('L3_bowl_entry', 'bowl_entry', 341.48, 342.0, 18., '', {'bowl': 'crater_bowl', 'kind': 'floor level, along the bowl axis (no rim)'}),
    ),
    entry='T3 crest (1147.61, 40.0, 1123.76)', exit='crater_bowl',
    airs=(('L3_K1', 'L3_landing'),),
)

# ---------------------------------------------------------------- L2, the Serpent Line
L2 = LineSpec(
    id='L2', name='Serpent Line',
    path=Turtle(start=(1159.376, 1149.885), heading=5.0, segs=(
        ('straight', 30.), ('turn', 40., -25.), ('straight', 20.), ('turn', 40., 25.),      # Serpent: berms B1, B2
        ('straight', 20.), ('turn', 40., -45.),                                            # B3 onto the jump heading
        ('straight', 201.5),                                                               # straight from s 136.3 to 337.8
        ('turn', 35., -135.), ('straight', 12.))),                                         # carving berm into the bowl
    y0=40.0,
    profile=(('arc', 14, -33), ('line', 20), ('arc', 30, -7),         # T2 roll-in: 40 -> 20.1
             ('line', 97),                                                           # Serpent at -7 deg
             ('arc', 40, -13), ('line', 10), ('arc', 40, -5),                         # chute
             ('arc', 22, 24), ('line', 3),                                           # K3: lip 24 deg at y 8.09
             ('gap', 25., -1.5, 'J3 Rim Gap'),
             *CRATER_LANDING,                                                        # knuckle y 6.59 -> foot about -5.5
             ('arc', 120, 0), ('line', 170.11)),                                    # level run-out and carving berm
    features=(
        Feature('L2_rollin', 'roll_in', 0., 40.3, 14., '', {'crest_r': 14, 'face_deg': 33, 'runout_r': 30}),
        Feature('L2_serpent', 'snake', 40.3, 137.3, 14., '', {
            'grade_deg': -7, 'floor': 14., 'wall': 3.5, 'wall_r': 5., 'outer_wall_in_berms': 5., 'coping': 'one clean coping (owner pick a)',
            'berms': ((30., 47.5), (67.5, 85.), (105., 136.3))}),
        Feature('L2_chute', 'run', 137.3, 156.9, 14., '', {'to_deg': -13}),
        Feature('L2_K3', 'kicker', 156.9, 170.8, 14., 'takeoff', {'r': 22, 'lip_deg': 24, 'lip_y': 7.5, 'height': 3.15}),
        Feature('L2_gap', 'gap', 170.8, 195.8, 25., '', {'open': True, 'ground_max_y': 2.5}),
        Feature('L2_landing', 'landing', 195.8, 251.73, 18., 'landing', {'knuckle_r': 15, 'slope_deg': 24, 'slope_len': 16, 'steep_deg': 34, 'steep_len': 8, 'runout_r': 45}),
        Feature('L2_runout', 'run', 251.73, 337.8, 14., '', {'grade_deg': 0, 'note': 'level: bleeds the landing speed before the berm'}),
        Feature('L2_berm', 'berm', 337.8, 420.3, 16., '', {'turn_r': 35., 'turn_deg': -135., 'outer_bank_height': 6., 'outer_wall_r': 15., 'bank_deg': 40.}),
        Feature('L2_bowl_entry', 'bowl_entry', 420.3, 432.3, 16., '', {'bowl': 'crater_bowl', 'kind': 'roll-in bank at the west end, along the bowl axis'}),
    ),
    entry='T2 crest (1159.38, 40.0, 1149.88)', exit='crater_bowl',
    airs=(('L2_K3', 'L2_landing'),),
)

LINES = (L1, L3, L2)

# ---------------------------------------------------------------- the bowl complex
BOWLS = (
    Bowl('crater_bowl', centre=(1367.1, 932.2), axis=5.0, size=(120., 55.), rim_y=-10.0, floor_y=-20.2,
         r=9.0, vert=1.0, deck=3.0, material=PALETTE['concrete'], max_entry=25.0,
         openings=(('L1', (1357.4, 973.8), 'roll-in bank, NE rim'), ('L3', (1311.5, 926.3), 'east end at floor level'),
                   ('L2', (1429.8, 936.8), 'roll-in bank, west end')),
         notes='Ridden straight-on (simout/bowlwalls.txt): R8 + 1 m vert returns clean to 25 m/s; 26-28 m/s lands on the '
               'deck behind the coping (no bail). The east end is a mellow R25 bank to 30 degrees, where L3 rolls in along '
               'the axis with about 115 m of floor to bleed. r4 SW mega bowl reference: 73 m wide, R10-19, 25 m floor.'),
    Bowl('blue_pool', centre=(1387.6, 870.7), axis=5.0, size=(47., 25.), rim_y=-10.0, floor_y=-12.9,
         r=2.5, vert=0.4, deck=2.0, material=PALETTE['pool'], max_entry=10.0,
         copy_from={'meshes': ('geometry/mesh-0098-000.npz', 'geometry/mesh-0064-000.npz'), 'r4_centre': (1296.3, 910.7),
                        'r4_floor_y': -24.9, 'r4_coping_y': -22.0, 'note': 'translate by (centre - r4_centre), keep orientation; '
                        'r4 pool: about 47 x 25 m, 17 m across at x 1300, 2.9 m deep (4.1 m deep end), R2-3, vertical top'},
         notes='Reached only from inside the complex. Ridden (simout/bowlwalls2.txt): R2.5 + 0.4 m vert returns clean at '
               '8-10 m/s; at 12 m/s the rider lands on the deck. Pool entry 10 m/s or less.'),
    Bowl('peanut', centre=(1312.7, 866.2), axis=5.0, size=(40., 18.), rim_y=-10.0, floor_y=-13.3,
         r=3.0, vert=0.3, deck=2.0, material=PALETTE['concrete'], max_entry=10.0,
         notes='Two lobes 18 m across with a 12 m waist hip. R3 + 0.3 m vert returns clean at 8-10 m/s (ridden).'),
)

LINKS = (
    Link('spine_bowl_pool', 'spine', 'crater_bowl', 'blue_pool', ((1395.5, 895.5), (1375.5, 893.7)),
         {'cap': 0.35, 'crest_y': -10.0, 'note': 'crest R10 or more: above about 10 m/s it is a spine transfer air'}),
    Link('channel_pool_peanut', 'channel', 'blue_pool', 'peanut', ((1364.6, 869.7), (1332.6, 867.9)),
         {'floor': 6., 'wall': 2.0, 'wall_r': 3.0, 'grade_deg': 0., 'note': 'level pump channel at rim height'}),
    Link('spine_peanut_bowl', 'spine', 'peanut', 'crater_bowl', ((1318.6, 890.8), (1298.6, 889.0)),
         {'cap': 0.35, 'crest_y': -10.0}),
)

# ---------------------------------------------------------------- the ground between the lines
GROUND = {
    'site': 'M1: keep the old block hillside as the base; every feature builds up from it (pipeline.md section 6)',
    'fill': 'a smooth membrane (additions.relax) over the block inside its footprint, meeting every feature outline flush '
         '(within 0.3 m)',
    'flanks': 'where a feature stands above the membrane, its flanks fall at 30 degrees or less into it: no thin walls, '
           'no knife edges. Where a wall is needed it is at least 1.2 m thick with a flat cap',
    'gaps': {'L1_canyon': 6.0, 'L3_gap': -9.0, 'L2_gap': 3.0},      # the membrane stays at or under these native y in gaps
    'clearance': 'no membrane above a line\'s riding surface within its width + 2 m',
    'dressing': 'granite domes and autumn bushes on the membrane only, at least 4 m clear of every feature and line',
    'respawn': 'the game resets to each line\'s roll-in crest (decision 1); no pushing path back up',
}

# What the offline Session measured (plan/layout.md; plan/line1/validation*/report.json; plan/simout/).
# Rolling drag on the offline Session, m/s^2 against speed m/s (plan/model.py, calibrated by straight-lane rides): about
# zero below 11 m/s, then 0.8-1.2 m/s^2 (a 5-6 degree slope's worth) from 14 to 30 m/s.
MEASURED_DRAG = ((0, 8, 11, 12, 12.6, 13.4, 16, 18, 20, 22, 25, 28, 30, 40),
                 (0, 0, .06, .15, .4, .75, .82, .95, 1.0, 1.08, 1.1, 1.2, 1.25, 1.4))

MEASURED = {
    'roll_in_30m': 'from the tower deck at 3-5 m/s: 22.1-22.4 m/s on the flat run-in (plan/rollin_speed.py)',
    'L1_canyon_transfer': 'validator PASS at entry 21-24.5 m/s: airs 27-45 m, 1.8-2.8 s, mismatch 5-16 deg, normal 2-6 m/s '
                       '(short B, plan/line1/validation6); park-assist, steered, full route: 37/38/51 m airs, no bail',
    'crater_gap': 'lip 17.6-20.5 m/s: 26-43 m, ollie up to 44 m, no bail (simout/j1_shortest.txt)',
    'crater_bowl_wall': 'R8 + 1 m vert: clean to 25 m/s straight-on',
    'pool_wall': 'R2.5 + 0.4 m vert: clean to 10 m/s; 12 m/s lands on the deck',
    'peanut_wall': 'R3 + 0.3 m vert: clean to 10 m/s',
}


# ---------------------------------------------------------------- helpers
def pieces(line, start=None):
    """The line's continuous surfaces between gaps: [(s0, y0, degrees0, parts)] in additions.profile semantics. A piece
    boundary happens only at a gap, so a landing and its run-out are one surface. `start='exit'` begins at the tower
    roll-in's exit section (exit_station) and leaves the roll-in out."""
    from craterpark.additions import profile
    parts = list(line.profile)
    s0, y0, a0 = 0., line.y0, 0.
    if start == 'exit':
        s0, y0, a0 = exit_station(line)[:3]; parts = parts[line.rollin:]
    out, cur, here = [], [], (s0, y0, a0)
    for part in parts:
        if part[0] == 'angle':
            raise ValueError(f'{line.id}: an angle part is a kink; use an arc')
        if part[0] == 'gap':
            if cur:
                k = profile(here[1], here[2], cur); out.append((*here, tuple(cur)))
                here = (here[0] + k[-1][0], k[-1][1], k[-1][2])
            here, cur = (here[0] + part[1], here[1] + part[2], 0.), []
        else:
            cur.append(part)
    if cur:
        out.append((*here, tuple(cur)))
    return out


def exit_station(line):
    """(s, y, degrees, (x, z), heading degrees): where the tower's roll-in hands over to the line (B's tower builds the
    roll-in up to this section; build_line starts here, so the two never overlap in plan)."""
    from craterpark.additions import profile
    k = profile(line.y0, 0., list(line.profile[:line.rollin]))
    s, y, a = (float(v) for v in k[-1])
    p, d = line.path.at(s)
    return s, y, a, (float(p[0]), float(p[1])), math.degrees(math.atan2(d[1], d[0]))


def cut(s0, y0, a0, parts, stop):
    """A piece's parts cut at plan distance `stop` (None when the piece starts at or past it)."""
    from craterpark.additions import profile
    if s0 >= stop - 1e-6:
        return None
    keep = list(parts)
    while keep and s0 + profile(y0, a0, keep)[-1][0] > stop + 1e-6:
        last = keep[-1]; over = s0 + profile(y0, a0, keep)[-1][0] - stop
        if last[0] == 'line' and last[1] > over:
            keep[-1] = ('line', last[1] - over); break
        keep.pop()
    return tuple(keep) or None


def knots(line, step=1.):
    """[(s, y, degrees)] along the whole line, gaps left out (each piece's knots offset by its start)."""
    from craterpark.additions import profile
    out = []
    for s0, y0, a0, parts in pieces(line):
        out += [(s0 + s, y, a) for s, y, a in profile(y0, a0, list(parts), step)]
    return out


def along_parts(parts, degrees=0.):
    """additions.profile parts (line = plan metres) as dsl.Profile parts (line = metres along the slope)."""
    out, a = [], math.radians(degrees)
    for p in parts:
        if p[0] == 'line':
            out.append(('line', p[1] / max(math.cos(a), 1e-9)))
        else:
            out.append(p); a = math.radians(p[2])
    return out


def feature(fid):
    for line in LINES:
        for f in line.features:
            if f.id == fid:
                return line, f
    raise KeyError(fid)


def corners(path):
    """A turtle as corner points and fillet radii (primitives.Rounded): each turn becomes the intersection of its two
    tangent legs, with its radius."""
    ps = path.pieces(); pts = [np.array(path.start, 'f8')]; radii = [0.]
    for kind, s0, s1, (x, z), h, R, d in ps:
        if kind != 'turn':
            continue
        a = math.radians(h)
        half = R * math.tan(abs(math.radians(d)) / 2)
        pts.append(np.array([x, z]) + half * np.array([math.cos(a), math.sin(a)])); radii.append(R)
    end, _ = path.at(path.length); pts.append(end); radii.append(0.)
    return np.array(pts), np.array(radii)


def curve(path):
    """The turtle as one dsl curve: a curves.Line when straight, else a primitives.Rounded with exact fillets."""
    from .curves import Line
    if len(path.segs) == 1:
        return Line(path.start, path.at(path.length)[0])
    from .primitives import Rounded
    p, r = corners(path)
    return Rounded(p, r)


def slab_ground(lines=None, depth=2.0, step=1.0):
    """An interim ground until A's landform (v2/ground.py) lands: a plan height function (x, z) -> y that sits `depth`
    under the nearest riding station of any line, and at each open gap's `ground_max_y` (or 6 m under its lip) across
    the gap, so the flanks of every line bank down only a short way and never run into each other."""
    pts = []
    for line in lines or LINES:
        for s, y, _ in knots(line, step):
            p, _ = line.path.at(s); pts.append((p[0], p[1], y - depth))
        for f in line.features:
            if f.kind == 'gap':
                floor = f.params.get('ground_max_y')
                if floor is None:
                    floor = min(y for s, y, _ in knots(line, step) if abs(s - f.s0) < step) - 6.
                for s in np.arange(f.s0, f.s1 + 1e-9, step):
                    p, _ = line.path.at(s); pts.append((p[0], p[1], floor))
    P = np.asarray(pts, 'f8')

    def ground(x, z):
        x, z = np.asarray(x, 'f8'), np.asarray(z, 'f8'); shape = np.shape(x)
        q = np.c_[x.ravel(), z.ravel()]; out = np.empty(len(q))
        for a in range(0, len(q), 2048):
            d = ((q[a:a + 2048, None, :] - P[None, :, :2]) ** 2).sum(-1)
            out[a:a + 2048] = P[np.argmin(d, axis=1), 2]
        return out.reshape(shape)
    return ground


def build_stop(line):
    """Where build_line stops: before the first berm turning more than 100 degrees (a bank primitive, not a ramp)."""
    return min([f.s0 for f in line.features if f.kind == 'berm' and abs(f.params.get('turn_deg', 0)) > 100]
               + [line.path.length])


def build_line(line, ground=None, side='bank', on_ground=False):
    """Compile a line with B's primitives, from the tower roll-in's exit section (exit_station) to build_stop: each
    jump (the surface up to its lip, the gap, the surface after it, to the next gap or the end) is one
    primitives.jump_line, and a surface after the last jump is a primitives.ramp. Widths are each piece's widest
    feature. Returns a primitives.Built."""
    from craterpark.additions import profile

    from . import primitives as P
    stop = build_stop(line)
    path = curve(line.path.until(stop))
    ps = []
    for s0, y0, a0, parts in pieces(line, start='exit'):
        kept = cut(s0, y0, a0, parts, stop)
        if kept:
            ps.append((s0, y0, a0, kept))
    gaps = [p for p in line.profile if p[0] == 'gap']

    def width(s0, y0, a0, parts):
        s1 = s0 + profile(y0, a0, list(parts))[-1][0]
        return max([f.width for f in line.features if f.s0 < s1 - 1e-6 and f.s1 > s0 + 1e-6] or [16.])

    built, i = [], 0
    while i < len(ps):
        s0, y0, a0, parts = ps[i]
        if i + 1 < len(ps) and i < len(gaps):
            _, ny, na, nparts = ps[i + 1]
            launch = P.from_additions(y0, a0, list(parts)); landing = P.from_additions(ny, na, list(nparts))
            built.append(P.jump_line(path, launch, landing, gaps[i][1], width(*ps[i]), start=s0, left=side, right=side,
                                     ground=ground, feature=f'{line.id}.{i}', land_width=width(*ps[i + 1]),
                                     on_ground=on_ground))
            i += 2
        else:
            built.append(P.ramp(path, P.from_additions(y0, a0, list(parts)), width(*ps[i]), start=s0, left=side,
                                right=side, ground=ground, feature=f'{line.id}.{i}', on_ground=on_ground))
            i += 1
    return P.Built.concat(built)
