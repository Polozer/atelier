"""Crater Park's drawn and collision meshes made clean, from build.py's pieces (Blender; docs/CRATERPARK.md "Clean geometry").

clean(loaded) takes build.py's pieces (entry, arrays, kept faces), after the tunnel carve and the added pieces, and
returns what build.py exports:
1. the open space reachable from outside (clean.reachable) and, by rays, the faces seen from it (visibility); a
   foundation face on a riding surface (COVER) and a prism wall shared by two prisms are hidden before any ray;
2. faces lying on a higher-ranked face (ROLES order, piece by piece) have its outline cut out of them exactly
   (clean.subtract): no face lies on another, so nothing flickers and nothing is pushed back;
0. an old mesh an added piece was laid through (CUT_UNDER) loses its parts over the piece's top, cut exactly;
3. T-junctions split, within each mesh and against every other mesh's vertices (clean.fix_tjunctions);
4. the grind lines found on that collision (grind.py), each drawn as the steel coping, Douglas-Peucker'd (COPING_TOL);
5. the baked occlusion on the fine faces (build.ambient_occlusion, the coping included as before);
6. every mesh remeshed (remesh.py): the added pieces as height fields over the ground, the rest by planar patches,
   chains shared, within TOL_H of the fine surface and TOL_AO of its occlusion (and TOL_UV of its UVs).
"""
import json
import math
import time

import numpy as np

from craterpark import additions, clean, grind, remesh, visibility
from craterpark import build as B

TOL_H = .003        # metres: a remeshed surface's height off the fine one at every fine vertex, at most
TOL_B = .0015       # metres: a simplified chain (an outline, a crease, a seam) off the fine one
TOL_AO = .02        # the baked occlusion, linear
TOL_UV = .002       # texture tiles, on the textured pieces
COPING_TOL = .0015  # metres: a coping line simplified this close to its lip
WELD = 2e-4         # metres: the library's positions are float32 (0.12 mm apart near x = 1300)
TJ = 5e-4           # metres: a vertex this close to another face's edge splits it
# Old meshes an added piece was laid through, whose parts over its top showed through it (a planter's cap as a
# wedge in the plaza kicker's face): cut away exactly (clean.cut_under). Listed, not inferred: a floor a piece runs
# into (the pool landing's run-out under the pool's floor) is ridden over the piece and must stay.
CUT_UNDER = {'add-run-plaza_gap_kicker': ('mesh-0140-000', 'mesh-0179-000')}
COVER = .05         # metres: a foundation face this close on a riding surface is hidden (build.COVER)


def log(t0, *a):
    print(f'{time.time() - t0:7.1f}s clean:', *a, flush=True)


def mesh_rank(entry):
    if entry['id'] == 'add-coping':
        return len(B.ROLES) + 1.
    return B.ROLES.index('bridge_support') + .5 if entry.get('added') else B.ROLES.index(entry['role'])


def heightfield(entry):
    i = entry['id']
    return bool(entry.get('added')) and not i.endswith('-sides') and not i.startswith(('add-solid', 'add-kicker')) and i != 'add-coping'


def compact(P, F, UV):
    used = np.unique(F); rm = np.full(len(P), -1, 'i8'); rm[used] = np.arange(len(used))
    return P[used], rm[F], UV[used]


def weld(P, F, UV):
    """Corners on one position and UV made one vertex; folded faces dropped."""
    key = np.concatenate([np.round(P / WELD), np.round(UV / 1e-5)], 1).astype('i8')
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    F = inv.ravel()[F]
    F = F[(F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])]
    return P[first], F, UV[first]


def clean(loaded, coping_lines=None):
    """build.py's pieces -> (meshes [(entry, P, F, UV, AO)], collision {role: triangles}, grind lines, stats)."""
    t0 = time.time(); stats = {}
    pieces = []
    for entry, a, keep in loaded:
        F = a['triangles'][keep].astype('i8')
        if not len(F):
            continue
        P, F, UV = compact(a['positions'].astype('f8'), F, a['uvs'].astype('f8'))
        pieces.append({'entry': entry, 'P': P, 'F': F, 'UV': UV})
    stats['fine_faces'] = int(sum(len(p['F']) for p in pieces))
    # 0. old meshes an added piece was laid through (CUT_UNDER): their parts over its top cut away, exactly
    byid = {p['entry']['id']: p for p in pieces}
    for piece, olds in CUT_UNDER.items():
        if piece not in byid:
            continue
        t = byid[piece]['P'][byid[piece]['F']]
        skin = t[remesh.face_normals(t.reshape(-1, 3), np.arange(3 * len(t)).reshape(-1, 3))[0][:, 1] > .05]
        for o in olds:
            if o not in byid:
                continue
            q = byid[o]; T0 = q['P'][q['F']]
            lo, hi = skin.reshape(-1, 3).min(0), skin.reshape(-1, 3).max(0)
            near = np.flatnonzero((T0.max(1) >= lo).all(1) & (T0.min(1) <= hi).all(1))
            keep = np.ones(len(T0), bool); add_P, add_UV = [], []
            for f in near.tolist():
                parts = clean.cut_under(T0[f], skin)
                if len(parts) == 1 and np.allclose(parts[0], T0[f]):
                    continue
                keep[f] = False
                if len(parts):
                    tri = q['F'][f]
                    bc = np.linalg.lstsq(np.stack([T0[f][1] - T0[f][0], T0[f][2] - T0[f][0]], 1),
                                         (parts.reshape(-1, 3) - T0[f][0]).T, rcond=None)[0].T
                    bc = np.stack([1 - bc[:, 0] - bc[:, 1], bc[:, 0], bc[:, 1]], 1)
                    add_P.append(parts.reshape(-1, 3)); add_UV.append(bc @ q['UV'][tri])
            if (~keep).any():
                base = len(q['P'])
                P = np.concatenate([q['P']] + add_P); UV = np.concatenate([q['UV']] + add_UV)
                F = np.concatenate([q['F'][keep], base + np.arange(sum(len(x) for x in add_P)).reshape(-1, 3)])
                q['P'], q['F'], q['UV'] = weld(*compact(P, F, UV))
                stats.setdefault('cut_under', {})[o] = int((~keep).sum())
                log(t0, f'{o}: {int((~keep).sum())} faces cut under {piece}')
    T = np.concatenate([p['P'][p['F']] for p in pieces])
    owner = np.repeat(np.arange(len(pieces)), [len(p['F']) for p in pieces])
    # 1. visibility
    reach = clean.reachable(T, log=lambda m: log(t0, m))
    pre = np.zeros(len(T), bool)
    role = np.array([p['entry']['role'] for p in pieces])[owner]
    found = role == 'foundation'
    ride = (role == 'original')
    two = np.array([bool(p['entry'].get('doubleSided')) for p in pieces])[owner]
    if found.any():
        f = np.flatnonzero(found)
        pre[f[clean.covered(T[f], T[ride], eps=COVER)]] = True
        pre[f[clean.inner_walls(T[f], np.zeros(len(f), 'i8'))]] = True
    log(t0, 'hidden before rays (foundation on riding, shared prism walls):', int(pre.sum()))
    tree = visibility.bvh(T)
    seen = visibility.seen_faces(tree, T, two, reach, test=~pre) & ~pre
    del tree
    stats['hidden'] = int((~seen).sum())
    log(t0, 'faces seen:', int(seen.sum()), 'of', len(T))
    # 2. overlaps clipped by rank (piece by piece within a mesh)
    order = sorted(range(len(pieces)), key=lambda k: (mesh_rank(pieces[k]['entry']), pieces[k]['entry']['id']))
    mrank = np.empty(len(pieces), 'i8'); mrank[order] = np.arange(len(pieces))
    rank = np.concatenate([mrank[k] * (1 << 24) + B.pieces(p['F']) for k, p in enumerate(pieces)])
    vis = np.flatnonzero(seen)
    pairs = clean.overlap_pairs(T[vis], rank[vis])
    stats['overlap_pairs'] = int(len(pairs))
    removed = np.zeros(len(T), bool); parts = {}
    if len(pairs):
        pairs = vis[pairs]
        srt = pairs[np.argsort(pairs[:, 0], kind='stable')]
        starts = np.flatnonzero(np.r_[True, srt[1:, 0] != srt[:-1, 0]]); ends = np.r_[starts[1:], len(srt)]
        for s, e in zip(starts, ends):
            f = srt[s, 0]
            removed[f] = True
            kept = clean.subtract(T[f], T[srt[s:e, 1]])
            if len(kept):
                parts[f] = kept
    stats['clipped'] = int(removed.sum())
    log(t0, 'overlapping faces clipped:', int(removed.sum()), 'parts kept:', sum(len(v) for v in parts.values()))
    start = np.r_[0, np.cumsum([len(p['F']) for p in pieces])]
    for k, p in enumerate(pieces):
        g = np.arange(start[k], start[k + 1])
        F = p['F'][(seen & ~removed)[g]]
        P, UV = p['P'], p['UV']
        nP, nUV, nF = [P], [UV], [F]; base = len(P)
        for gi in g[removed[g]]:
            if gi not in parts:
                continue
            q = parts[gi]; tri = p['F'][gi - start[k]]; T3 = P[tri]
            sol = np.linalg.lstsq(np.stack([T3[1] - T3[0], T3[2] - T3[0]], 1), (q.reshape(-1, 3) - T3[0]).T, rcond=None)[0].T
            bc = np.stack([1 - sol[:, 0] - sol[:, 1], sol[:, 0], sol[:, 1]], 1)
            nP.append(q.reshape(-1, 3)); nUV.append(bc @ UV[tri]); nF.append(base + np.arange(3 * len(q)).reshape(-1, 3)); base += 3 * len(q)
        P, F, UV = np.concatenate(nP), np.concatenate(nF), np.concatenate(nUV)
        p['P'], p['F'], p['UV'] = weld(*compact(P, F, UV)) if len(F) else (P[:0], F, UV[:0])
    pieces = [p for p in pieces if len(p['F'])]
    # 3. T-junctions
    for k, p in enumerate(pieces):
        lo, hi = p['P'].min(0) - 1, p['P'].max(0) + 1
        others = np.concatenate([x['P'] for j, x in enumerate(pieces) if j != k])
        others = others[((others >= lo) & (others <= hi)).all(1)]
        P, F, added, p['UV'] = clean.fix_tjunctions(p['P'], p['F'], others, tol=TJ, attrs=p['UV'])   # UVs along the split edge
        p['P'], p['F'] = P, F
    log(t0, 'T-junctions split')
    # 4. grind lines on the fine collision, and the coping along them
    above, final = collision(pieces)
    lines = grind.grind_lines(final['original'], np.concatenate([x for r, x in final.items() if r != 'original']))
    log(t0, 'grind lines:', len(lines))
    # the rails keep every point (park.json); the tube needs only the points off a straight run
    tube = additions.coping([l[remesh.dp_chain(np.arange(len(l)), l, None, COPING_TOL, None)] for l in lines])
    if tube is not None:
        v, f, uv = tube
        cop = v.astype('f8')[f]
        tree = visibility.bvh(np.concatenate([np.concatenate([p['P'][p['F']] for p in pieces]), cop]))
        keep = visibility.seen_faces(tree, cop, False, reach)
        del tree
        P, F, UV = compact(v.astype('f8'), f[keep].astype('i8'), uv.astype('f8'))
        pieces.append({'entry': {'id': 'add-coping', 'role': 'coping', 'material': additions.COPING_MATERIAL,
                                 'doubleSided': False, 'added': True}, 'P': P, 'F': F, 'UV': UV})
        stats['coping'] = {'faces': int(len(f)), 'seen': int(keep.sum())}
    # 5. occlusion on the fine faces
    for p, ao in zip(pieces, B.ambient_occlusion([(p['P'], p['F']) for p in pieces])):
        p['AO'] = ao
    log(t0, 'occlusion baked')
    # 6. remesh
    keys = np.concatenate([np.round(p['P'] / WELD).astype('i8') for p in pieces])
    who = np.repeat(np.arange(len(pieces)), [len(p['P']) for p in pieces])
    u, inv = np.unique(keys, axis=0, return_inverse=True); inv = inv.ravel()
    # a position used by more than one piece is a seam between meshes: it stays
    pairs_ = np.unique(np.stack([inv, who], 1), axis=0)
    shared = np.bincount(pairs_[:, 0], minlength=len(u)) > 1
    off = np.r_[0, np.cumsum([len(p['P']) for p in pieces])]
    for k, p in enumerate(pieces):
        e = p['entry']; P, F, UV, AO = p['P'], p['F'], p['UV'], p['AO']
        mine = inv[off[k]:off[k + 1]]
        cnt = np.bincount(mine, minlength=len(u))
        fixed_v = shared[mine] | (cnt[mine] > 1)                       # seams with other meshes, UV seams within
        textured = e['role'] not in B.PLAIN and e['id'] != 'add-coping'
        A = np.stack([AO] + ([UV[:, 0], UV[:, 1]] if textured else []), 1)
        tolA = np.array([TOL_AO] + ([TOL_UV, TOL_UV] if textured else []))
        if e['id'] == 'add-coping':
            Tn = F
        elif heightfield(e) and (remesh.face_normals(P, F)[0][:, 1] > .05).any():
            up = remesh.face_normals(P, F)[0][:, 1] > .05
            lab = np.unique(np.where(up, 0, 1 + np.arange(len(F))), return_inverse=True)[1].ravel()
            Tn = remesh.remesh_mesh(P, F, A, TOL_H, tolA, lab, normal_of=lambda l: np.array([0., 1., 0.]), tol_b=TOL_B,
                                    fixed=set(range(1, int(lab.max()) + 1)), fixed_vertex=fixed_v)
        else:
            Tn = remesh.remesh_mesh(P, F, A, TOL_H, tolA, remesh.planar_patches(P, F), tol_b=TOL_B, fixed_vertex=fixed_v)
        used = np.unique(Tn); rm = np.full(len(P), -1, 'i8'); rm[used] = np.arange(len(used))
        p['out'] = (P[used], rm[Tn], UV[used], AO[used])
        p['fine_faces'] = int(len(F))
    log(t0, 'remeshed')
    return pieces, lines, stats


def collision(pieces):
    """Per role, the faces the board rides, as build.py: riding faces as they are, the others with every corner
    inside the solid sunk; faces whose top edge is inside the solid left out. Returns (riding_above, {role: (n,3,3)})."""
    parts = {}
    for p in pieces:
        r = p['entry']['role']
        if r == 'coping':
            continue
        parts.setdefault(r, []).append(p['P'][p['F']])
    ride = np.concatenate(parts['original']).astype('f8')
    above = B.riding_above(ride[B.unit_normals(ride)[:, 1] > .2])
    final = {}
    for r, x in parts.items():
        t = np.concatenate(x).astype('f8')
        t = t[~B.hidden_walls(t, above)]
        if r != 'original':
            t, _ = B.sink_inside(t, above)
        final[r] = t
    return above, final
