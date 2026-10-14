"""Plan curves in (x, z), parameterised by arc length t in metres (Spline: to within 1e-9 relative).

Every curve has: length, closed, point(t) (n, 2), tangent(t) (n, 2) unit, normal(t) = the tangent turned 90 degrees
counter-clockwise in (x, z), i.e. (-tz, tx), curvature(t) signed (positive turning toward the normal), breaks()
(semantic parameters: ends, corners, part joins; kept by every sampling), samples(tess, ...) (adaptive parameters).
"""
import math

import numpy as np

GAUSS_X, GAUSS_W = np.polynomial.legendre.leggauss(6)


def plan3(p, y=0.):
    """Plan points (n, 2) -> 3D (n, 3) at height y (scalar or (n,))."""
    p = np.asarray(p, 'f8')
    return np.stack([p[:, 0], np.broadcast_to(y, (len(p),)), p[:, 1]], 1)


def adaptive(spans, density, dense=64):
    """Parameters over `spans` [(t0, t1)] whose spacing follows `density(t)` (samples per metre): each span gets
    ceil(integral of density) segments, placed at equal steps of the cumulative density. Span ends are always kept."""
    out = []
    for t0, t1 in spans:
        if t1 - t0 <= 1e-12:
            out.append([t0]); continue
        n = max(dense, int((t1 - t0) * 4) + 2)
        t = np.linspace(t0, t1, n)
        # midpoint rule: a density that jumps at a span's end (an arc meeting a line) never leaks into the span
        d = np.maximum(np.asarray(density((t[1:] + t[:-1]) / 2), 'f8'), 1e-9)
        cum = np.concatenate([[0.], np.cumsum(d * np.diff(t))])
        k = max(1, int(math.ceil(cum[-1] - 1e-9)))
        out.append(np.interp(np.linspace(0, cum[-1], k + 1), cum, t))
    t = np.unique(np.concatenate(out)) if out else np.zeros(0)
    return t


def merge_params(t, extra, tol=1e-9, near=.01):
    """The adaptive parameters `t` united with the kept ones `extra` (knots, tags, given stations): every kept one
    survives; an adaptive one within `near` (1 cm) of a kept one, or of the previous adaptive one, is dropped, so no
    sliver row is ever made."""
    keep = np.unique(np.asarray(extra, 'f8').ravel())
    keep = keep[np.r_[True, np.diff(keep) > tol]] if len(keep) else keep
    t = np.unique(np.asarray(t, 'f8'))
    if len(keep) and len(t):
        j = np.clip(np.searchsorted(keep, t), 1, len(keep)) if len(keep) > 1 else np.zeros(len(t), 'i8')
        d = np.minimum(np.abs(t - keep[np.clip(j - 1, 0, len(keep) - 1)]), np.abs(t - keep[np.clip(j, 0, len(keep) - 1)]))
        t = t[d > near]
    if len(t) > 1:
        t = t[np.r_[True, np.diff(t) > near]]
    out = np.unique(np.concatenate([t, keep]))
    return out[np.r_[True, np.diff(out) > tol]] if len(out) else out


class Curve:
    closed = False
    length = 0.

    def point(self, t):
        raise NotImplementedError

    def tangent(self, t):
        raise NotImplementedError

    def curvature(self, t):
        return np.zeros(np.shape(t))

    def normal(self, t):
        T = self.tangent(t)
        return np.stack([-T[:, 1], T[:, 0]], 1)

    def breaks(self):
        return np.asarray([0., self.length])

    def point3(self, t, y=0.):
        return plan3(self.point(np.atleast_1d(t)), y)

    def samples(self, tess, extra=(), offsets=(0.,), height=None):
        """Adaptive parameters: spacing from `tess` for the plan curvature at every lateral offset in `offsets` (the
        outer edge of a sweep is stretched by |1 - k o|), and for the curvature of `height` (a dsl.Height) if given.
        Breaks and `extra` are always included."""
        o = np.asarray(offsets, 'f8')

        def density(t):
            k = self.curvature(t)
            stretch = np.abs(1 - k[:, None] * o[None, :]).max(1)
            # the tightest offset curve's radius |1/k - o| sets the chord rule; the angle rule is offset-free
            inv = 1 / np.where(np.abs(k) > 1e-12, k, 1e-12)
            r = np.abs(inv[:, None] - o[None, :]).min(1)
            d = np.where(np.abs(k) > 1e-12, np.abs(k) / tess.step_angle(np.maximum(r, 1e-6)), 0.)
            d = np.maximum(d, stretch / (tess.max_edge / math.sqrt(2)))
            if height is not None:
                d = np.maximum(d, tess.density(height.curvature(t)))
            return d
        b = np.unique(np.concatenate([self.breaks(), [0., self.length]]))
        return merge_params(adaptive(list(zip(b[:-1], b[1:])), density), [x for x in np.ravel(extra) if 0 <= x <= self.length])


class Line(Curve):
    """A straight segment from a to b (plan points)."""

    def __init__(self, a, b):
        self.a, self.b = np.asarray(a, 'f8'), np.asarray(b, 'f8')
        self.length = float(np.linalg.norm(self.b - self.a))
        self.d = (self.b - self.a) / self.length

    def point(self, t):
        t = np.atleast_1d(np.asarray(t, 'f8'))
        return self.a + t[:, None] * self.d

    def tangent(self, t):
        return np.broadcast_to(self.d, (len(np.atleast_1d(t)), 2)).copy()


class Arc(Curve):
    """A circular arc about `centre` of `radius` from angle `start_deg` (atan2 in (x, z)) turning `sweep_deg` (positive:
    counter-clockwise in (x, z), so curvature +1/R)."""

    def __init__(self, centre, radius, start_deg, sweep_deg):
        self.c = np.asarray(centre, 'f8'); self.r = float(radius)
        self.a0 = math.radians(start_deg); self.sw = math.radians(sweep_deg)
        self.sign = 1. if sweep_deg >= 0 else -1.
        self.length = self.r * abs(self.sw)
        self.closed = abs(abs(sweep_deg) - 360.) < 1e-9

    def _angle(self, t):
        return self.a0 + self.sign * np.atleast_1d(np.asarray(t, 'f8')) / self.r

    def point(self, t):
        a = self._angle(t)
        return self.c + self.r * np.stack([np.cos(a), np.sin(a)], 1)

    def tangent(self, t):
        a = self._angle(t)
        return self.sign * np.stack([-np.sin(a), np.cos(a)], 1)

    def curvature(self, t):
        return np.full(len(np.atleast_1d(t)), self.sign / self.r)


class Polyline(Curve):
    """Straight segments through `points` (k, 2); corners are breaks (a sweep should not turn a corner: use a Spline).
    `closed` joins the last point to the first."""

    def __init__(self, points, closed=False):
        p = np.asarray(points, 'f8')
        self.closed = closed
        self.p = np.concatenate([p, p[:1]]) if closed else p
        seg = np.linalg.norm(np.diff(self.p, axis=0), axis=1)
        self.s = np.concatenate([[0.], np.cumsum(seg)]); self.length = float(self.s[-1])

    def _seg(self, t):
        t = np.atleast_1d(np.asarray(t, 'f8'))
        return np.clip(np.searchsorted(self.s, t, 'right') - 1, 0, len(self.s) - 2), t

    def point(self, t):
        k, t = self._seg(t)
        u = (t - self.s[k]) / np.maximum(self.s[k + 1] - self.s[k], 1e-12)
        return self.p[k] + u[:, None] * (self.p[k + 1] - self.p[k])

    def tangent(self, t):
        k, _ = self._seg(t)
        d = self.p[k + 1] - self.p[k]
        return d / np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-12)

    def breaks(self):
        return self.s.copy()


class Spline(Curve):
    """A C2 cubic spline through `points` (k, 2) (natural ends, or periodic when `closed`), parameterised by arc length.
    Its knots are not breaks (it is smooth through them)."""

    def __init__(self, points, closed=False, sub=32):
        p = np.asarray(points, 'f8')
        if closed and np.linalg.norm(p[0] - p[-1]) < 1e-9:
            p = p[:-1]
        self.closed = closed
        self.p = np.concatenate([p, p[:1]]) if closed else p
        h = np.linalg.norm(np.diff(self.p, axis=0), axis=1)
        self.u = np.concatenate([[0.], np.cumsum(h)])
        self.M = self._second(self.p, h, closed)
        # arc length table: `sub` sub-intervals per knot span, Gauss-Legendre on each
        uu = np.concatenate([np.linspace(self.u[i], self.u[i + 1], sub + 1)[:-1] for i in range(len(h))] + [[self.u[-1]]])
        a, b = uu[:-1], uu[1:]
        x = (a + b)[:, None] / 2 + (b - a)[:, None] / 2 * GAUSS_X[None, :]
        speed = np.linalg.norm(self._d1(x.ravel()), axis=1).reshape(x.shape)
        seg = (speed * GAUSS_W[None, :]).sum(1) * (b - a) / 2
        self.tu = uu; self.ts = np.concatenate([[0.], np.cumsum(seg)])
        self.length = float(self.ts[-1])

    @staticmethod
    def _second(p, h, closed):
        n = len(h)
        if n == 1:
            return np.zeros((2, 2))
        d = np.diff(p, axis=0) / h[:, None]
        if closed:
            A = np.zeros((n, n)); r = np.zeros((n, 2))
            for i in range(n):
                hp, hn = h[i - 1], h[i]
                A[i, (i - 1) % n] = hp; A[i, i] = 2 * (hp + hn); A[i, (i + 1) % n] = hn
                r[i] = 6 * (d[i] - d[i - 1])
            m = np.linalg.solve(A, r)
            return np.concatenate([m, m[:1]])
        A = np.zeros((n + 1, n + 1)); r = np.zeros((n + 1, 2))
        A[0, 0] = A[n, n] = 1.
        for i in range(1, n):
            A[i, i - 1] = h[i - 1]; A[i, i] = 2 * (h[i - 1] + h[i]); A[i, i + 1] = h[i]
            r[i] = 6 * (d[i] - d[i - 1])
        return np.linalg.solve(A, r)

    def _k(self, u):
        return np.clip(np.searchsorted(self.u, u, 'right') - 1, 0, len(self.u) - 2)

    def _eval(self, u, order):
        u = np.atleast_1d(np.asarray(u, 'f8')); k = self._k(u)
        h = (self.u[k + 1] - self.u[k])[:, None]
        a = (self.u[k + 1][:, None] - u[:, None]); b = (u[:, None] - self.u[k][:, None])
        M0, M1, P0, P1 = self.M[k], self.M[k + 1], self.p[k], self.p[k + 1]
        if order == 0:
            return (M0 * a ** 3 + M1 * b ** 3) / (6 * h) + (P0 / h - M0 * h / 6) * a + (P1 / h - M1 * h / 6) * b
        if order == 1:
            return (-M0 * a ** 2 + M1 * b ** 2) / (2 * h) - (P0 / h - M0 * h / 6) + (P1 / h - M1 * h / 6)
        return (M0 * a + M1 * b) / h

    def _d1(self, u):
        return self._eval(u, 1)

    def _u(self, t):
        """Spline parameter u at arc length t: interpolation in the table, then two Newton steps."""
        t = np.clip(np.atleast_1d(np.asarray(t, 'f8')), 0., self.length)
        u = np.interp(t, self.ts, self.tu)
        for _ in range(2):
            j = np.clip(np.searchsorted(self.tu, u, 'right') - 1, 0, len(self.tu) - 2)
            a = self.tu[j]
            x = (a + u)[:, None] / 2 + (u - a)[:, None] / 2 * GAUSS_X[None, :]
            sp = np.linalg.norm(self._d1(x.ravel()), axis=1).reshape(x.shape)
            s = self.ts[j] + (sp * GAUSS_W[None, :]).sum(1) * (u - a) / 2
            u = u - (s - t) / np.maximum(np.linalg.norm(self._d1(u), axis=1), 1e-12)
        return u

    def point(self, t):
        return self._eval(self._u(t), 0)

    def tangent(self, t):
        d = self._d1(self._u(t))
        return d / np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-12)

    def curvature(self, t):
        u = self._u(t); d1 = self._d1(u); d2 = self._eval(u, 2)
        return (d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / np.maximum(np.linalg.norm(d1, axis=1) ** 3, 1e-12)
