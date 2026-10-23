# -*- coding: utf-8 -*-
"""
Shortest stage path through a set of ROI positions (open path, fixed first point).

The cost of a move between two points is the stage move time when the x and y axes move
simultaneously: max(|dx| / vx, |dy| / vy). The path starts at a given point, visits every point
once and does not return.

  - n <= EXACT_MAX_POINTS: exact optimum (Held-Karp dynamic programming over subsets).
  - larger n: nearest-neighbour path from the start point, then 2-opt (reverse any segment after the
    start point that lowers the total cost, until no reversal improves it), repeated from n_restarts
    random initial orders (fixed seed, so the result is deterministic); the best path is kept.

Pure numpy, no qudi import.

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

__all__ = ['optimize_open_path', 'path_cost', 'move_time_matrix', 'EXACT_MAX_POINTS']

import numpy as np

EXACT_MAX_POINTS = 12  # up to this number of points the exact optimum is computed


def move_time_matrix(xy, speeds=(1.0, 1.0)) -> np.ndarray:
    """Matrix of move times between all points: max(|dx| / vx, |dy| / vy).

    @param xy: (n, 2) array-like of x, y positions
    @param speeds: (vx, vy), both > 0
    @return: (n, n) array, symmetric, zero diagonal
    """
    xy = np.asarray(xy, dtype=float).reshape(-1, 2)
    vx, vy = (float(s) for s in speeds)
    if not (vx > 0 and vy > 0):
        raise ValueError(f'speeds must be > 0, got {speeds!r}')
    dx = np.abs(xy[:, None, 0] - xy[None, :, 0]) / vx
    dy = np.abs(xy[:, None, 1] - xy[None, :, 1]) / vy
    return np.maximum(dx, dy)


def path_cost(xy, order, speeds=(1.0, 1.0)) -> float:
    """Total move time of the open path visiting the points of xy in the given order."""
    order = list(order)
    if len(order) < 2:
        return 0.0
    cost = move_time_matrix(xy, speeds)
    return float(sum(cost[a, b] for a, b in zip(order[:-1], order[1:])))


def optimize_open_path(xy, speeds=(1.0, 1.0), start=0, n_restarts=20, seed=0) -> list:
    """Order of the points of xy (indices) that minimizes the total move time of an open path
    starting at index start. Exact for n <= EXACT_MAX_POINTS, nearest neighbour + 2-opt with
    n_restarts random restarts otherwise (deterministic for a given seed).

    @param xy: (n, 2) array-like of x, y positions
    @param speeds: (vx, vy) used for the move time, both > 0
    @param int start: index of the first point of the path
    @param int n_restarts: number of random initial orders (in addition to the nearest neighbour)
    @param int seed: seed of the random initial orders
    @return: list of the n indices, first one == start
    """
    cost = move_time_matrix(xy, speeds)
    n = cost.shape[0]
    if n == 0:
        return []
    start = int(start)
    if not 0 <= start < n:
        raise ValueError(f'start {start} outside 0..{n - 1}')
    if n <= 2:
        return [start] + [i for i in range(n) if i != start]
    if n <= EXACT_MAX_POINTS:
        return _held_karp(cost, start)

    best = _two_opt(cost, _nearest_neighbour(cost, start))
    best_cost = _order_cost(cost, best)
    rng = np.random.default_rng(seed)
    others = np.array([i for i in range(n) if i != start])
    for _ in range(int(n_restarts)):
        order = _two_opt(cost, [start] + list(rng.permutation(others)))
        order_cost = _order_cost(cost, order)
        if order_cost < best_cost - 1e-12:
            best, best_cost = order, order_cost
    return [int(i) for i in best]


# ======================================================================================================================
# Helpers
# ======================================================================================================================

def _order_cost(cost, order) -> float:
    order = np.asarray(order)
    return float(cost[order[:-1], order[1:]].sum())


def _held_karp(cost, start) -> list:
    """Exact open path from start (dynamic programming over the subsets of visited points)."""
    n = cost.shape[0]
    full = (1 << n) - 1
    dp = np.full((1 << n, n), np.inf)
    parent = np.full((1 << n, n), -1, dtype=int)
    dp[1 << start, start] = 0.0
    bits = 1 << np.arange(n)
    for mask in range(1 << n):
        if not mask & (1 << start):
            continue
        row = dp[mask]
        if not np.isfinite(row).any():
            continue
        # cand[j, k]: path ending in j (within mask) extended to k
        cand = row[:, None] + cost
        best_prev = np.argmin(cand, axis=0)
        best_val = cand[best_prev, np.arange(n)]
        for k in range(n):
            if mask & bits[k]:
                continue
            new_mask = mask | int(bits[k])
            if best_val[k] < dp[new_mask, k]:
                dp[new_mask, k] = best_val[k]
                parent[new_mask, k] = best_prev[k]
    last = int(np.argmin(dp[full]))
    order = []
    mask = full
    while last != -1:
        order.append(last)
        prev = int(parent[mask, last])
        mask &= ~(1 << last)
        last = prev
    return order[::-1]


def _nearest_neighbour(cost, start) -> list:
    n = cost.shape[0]
    visited = np.zeros(n, dtype=bool)
    order = [start]
    visited[start] = True
    for _ in range(n - 1):
        row = np.where(visited, np.inf, cost[order[-1]])
        nxt = int(np.argmin(row))
        order.append(nxt)
        visited[nxt] = True
    return order


def _two_opt(cost, order) -> list:
    """2-opt for an open path with a fixed first point: reverse order[i..k] (1 <= i < k) while a
    reversal lowers the total cost (best reversal of each i applied at once)."""
    order = np.array(order, dtype=int)
    n = len(order)
    improved = True
    while improved:
        improved = False
        for i in range(1, n - 1):
            a = order[i - 1]
            b = order[i]
            ks = np.arange(i + 1, n)
            c = order[ks]
            # edge after the segment (none when the segment ends the path)
            d = np.where(ks + 1 < n, order[np.minimum(ks + 1, n - 1)], -1)
            has_next = d >= 0
            before = cost[a, b] + np.where(has_next, cost[c, np.maximum(d, 0)], 0.0)
            after = cost[a, c] + np.where(has_next, cost[b, np.maximum(d, 0)], 0.0)
            delta = after - before
            j = int(np.argmin(delta))
            if delta[j] < -1e-12:
                k = int(ks[j])
                order[i:k + 1] = order[i:k + 1][::-1]
                improved = True
    return [int(i) for i in order]
