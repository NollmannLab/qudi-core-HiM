# -*- coding: utf-8 -*-
"""
Shortest stage tour / path through a set of ROI positions.

The cost of a move between two points is the stage move time when the x and y axes move
simultaneously: max(|dx| / vx, |dy| / vy).

optimize_closed_tour (used by the ROI logic): closed tour - the move from the last point back to
the start point counts, as the stage returns to the first ROI after each scan / cycle.
  - n <= EXACT_MAX_POINTS: exact optimum (Held-Karp dynamic programming over subsets), plus the
    local optima of the heuristic below as further candidates for the tie-break;
  - larger n: nearest-neighbour tour, then local improvement with 2-opt (segment reversal) and
    Or-opt (a block of 1, 2 or 3 consecutive points moved elsewhere in the tour, in either
    orientation) until no move improves the total; repeated from n_restarts random initial tours
    (fixed seed, so the result is deterministic);
  - tie-break: among the tours found whose total is within `tolerance` (fraction) of the best total,
    the one with the smallest longest single move (closing move included) is kept;
  - the order starts at `start`, in the direction whose first move is shorter.

optimize_open_path: open path (no return to the start point).
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

__all__ = ['optimize_closed_tour', 'tour_cost', 'longest_move', 'optimize_open_path', 'path_cost', 'move_time_matrix',
           'EXACT_MAX_POINTS']

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


def tour_cost(xy, order, speeds=(1.0, 1.0)) -> float:
    """Total move time of the CLOSED tour visiting the points of xy in the given order and returning
    from the last point to the first one."""
    order = list(order)
    if len(order) < 2:
        return 0.0
    return _tour_cost(move_time_matrix(xy, speeds), order)


def longest_move(xy, order, speeds=(1.0, 1.0)) -> float:
    """Longest single move of the CLOSED tour in the given order (move back to the first point
    included)."""
    order = list(order)
    if len(order) < 2:
        return 0.0
    return _tour_longest(move_time_matrix(xy, speeds), order)


def optimize_closed_tour(xy, speeds=(1.0, 1.0), start=0, tolerance=0.02, n_restarts=20, seed=0) -> list:
    """Order of the points of xy (indices) for a closed tour of short total move time, starting at
    index start (the move from the last point back to start is part of the total).

    Among the tours found whose total is within `tolerance` (fraction of the best total) of the best
    one, the tour with the smallest longest single move (closing move included) is returned; with
    tolerance 0 the best total found is returned (ties: smallest longest move). The order starts at
    start, in the direction whose first move is shorter.

    @param xy: (n, 2) array-like of x, y positions
    @param speeds: (vx, vy) used for the move time, both > 0
    @param int start: index of the first point
    @param float tolerance: fraction of the best total within which the longest move is minimized (>= 0)
    @param int n_restarts: number of random initial tours (in addition to the nearest neighbour)
    @param int seed: seed of the random initial tours
    @return: list of the n indices, first one == start
    """
    cost = move_time_matrix(xy, speeds)
    n = cost.shape[0]
    if n == 0:
        return []
    start = int(start)
    if not 0 <= start < n:
        raise ValueError(f'start {start} outside 0..{n - 1}')
    if tolerance < 0:
        raise ValueError(f'tolerance must be >= 0, got {tolerance}')
    if n <= 3:
        # every closed tour through <= 3 points has the same moves
        return _orient(cost, [start] + [i for i in range(n) if i != start], start)

    candidates = []
    if n <= EXACT_MAX_POINTS:
        candidates.append(_held_karp_closed(cost, start))
    candidates.append(_local_search_closed(cost, _nearest_neighbour(cost, start)))
    rng = np.random.default_rng(seed)
    others = np.array([i for i in range(n) if i != start])
    for _ in range(int(n_restarts)):
        candidates.append(_local_search_closed(cost, [start] + list(rng.permutation(others))))

    totals = np.array([_tour_cost(cost, t) for t in candidates])
    longest = np.array([_tour_longest(cost, t) for t in candidates])
    best_total = totals.min()
    if tolerance > 0:
        eligible = totals <= best_total * (1.0 + tolerance) + 1e-12
    else:
        eligible = totals <= best_total + 1e-9 * max(1.0, best_total)
    index = min(np.flatnonzero(eligible), key=lambda k: (longest[k], totals[k]))
    return _orient(cost, candidates[index], start)


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


# ======================================================================================================================
# Closed tour helpers
# ======================================================================================================================

def _tour_cost(cost, order) -> float:
    order = np.asarray(order)
    return float(cost[order, np.roll(order, -1)].sum())


def _tour_longest(cost, order) -> float:
    order = np.asarray(order)
    return float(cost[order, np.roll(order, -1)].max())


def _orient(cost, tour, start) -> list:
    """Rotate the closed tour so that it begins at start, in the direction whose first move is shorter
    (same tour, same total)."""
    tour = [int(i) for i in tour]
    k = tour.index(start)
    tour = tour[k:] + tour[:k]
    if len(tour) > 2 and cost[start, tour[-1]] < cost[start, tour[1]]:
        tour = [tour[0]] + tour[:0:-1]
    return tour


def _held_karp_closed(cost, start) -> list:
    """Exact closed tour from start (dynamic programming over the subsets of visited points, the
    move back to start added at the end)."""
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
    last = int(np.argmin(dp[full] + cost[:, start]))
    order = []
    mask = full
    while last != -1:
        order.append(last)
        prev = int(parent[mask, last])
        mask &= ~(1 << last)
        last = prev
    return order[::-1]


def _closed_masks(n):
    """Moves that are not allowed, independent of the tour: 2-opt needs 1 <= i < k <= n-1; an Or-opt
    block of length L at position i cannot go into an edge m = i-1 .. i+L-1 (cyclic) touching it."""
    i = np.arange(n)[:, None]
    m = np.arange(n)[None, :]
    two_opt = ~((i >= 1) & (m > i))
    or_opt = {length: (m - (i - 1)) % n <= length for length in (1, 2, 3)}
    return two_opt, or_opt


def _best_two_opt_closed(perm, perm_next, edge, mask):
    """Best 2-opt move: reversal of tour[i..k]. perm[a, b] = cost[tour[a], tour[b]],
    perm_next[a, b] = perm[a, b + 1] (cyclic), edge[m] = perm[m, m + 1]. Position 0 is never moved,
    which still covers every pair of edges of the closed tour. Returns (delta, i, k)."""
    # delta[i, k] = c(t[i-1], t[k]) + c(t[i], t[k+1]) - c(t[i-1], t[i]) - c(t[k], t[k+1])
    delta = np.roll(perm, 1, axis=0) + perm_next - np.roll(edge, 1)[:, None] - edge[None, :]
    delta[mask] = np.inf
    r, col = divmod(int(np.argmin(delta)), delta.shape[1])
    return float(delta[r, col]), r, col


def _best_or_opt_closed(perm, perm_next, edge, masks):
    """Best Or-opt move: a block of 1, 2 or 3 consecutive points (cyclic positions i .. i+L-1)
    removed and inserted into another edge m = (tour[m], tour[m+1]), in either orientation.
    Returns (delta, i, block length, m, reversed)."""
    n = perm.shape[0]
    idx = np.arange(n)
    perm_t = perm.T                       # perm_t[i, m] = c(t[m], t[i])
    perm_next_t = perm_next               # perm_next[x, m] = c(t[x], t[m+1])
    best = (np.inf, 0, 1, 0, False)
    for length, invalid in masks.items():
        if n - length < 3:
            continue
        last = (idx + length - 1) % n     # position of the last point of the block
        prev = (idx - 1) % n
        after = (idx + length) % n
        gain = perm[prev, idx] + perm[last, after] - perm[prev, after]
        # forward: c(t[m], t[i]) + c(t[last], t[m+1]); reversed: c(t[m], t[last]) + c(t[i], t[m+1])
        forward = perm_t + perm_next_t[last] - edge[None, :] - gain[:, None]
        backward = perm_t[last] + perm_next_t - edge[None, :] - gain[:, None]
        for reverse, delta in ((False, forward), (True, backward)):
            delta[invalid] = np.inf
            r, col = divmod(int(np.argmin(delta)), n)
            if delta[r, col] < best[0]:
                best = (float(delta[r, col]), r, length, col, reverse)
    return best


def _apply_or_opt(tour, i, length, m, reverse):
    """Closed tour with the block tour[i..i+length-1] (cyclic) moved into edge (tour[m], tour[m+1])."""
    n = len(tour)
    rolled = np.roll(tour, -i)  # block first
    block = rolled[:length]
    rest = rolled[length:]
    anchor = tour[m]
    pos = int(np.flatnonzero(rest == anchor)[0])
    seg = block[::-1] if reverse else block
    return np.concatenate((rest[:pos + 1], seg, rest[pos + 1:]))


def _local_search_closed(cost, tour) -> list:
    """2-opt + Or-opt on the closed tour: the best improving move of either kind is applied, until
    no move improves the total."""
    tour = np.array(tour, dtype=int)
    n = len(tour)
    if n < 4:
        return [int(i) for i in tour]
    two_opt_mask, or_opt_masks = _closed_masks(n)
    while True:
        perm = cost[np.ix_(tour, tour)]
        perm_next = np.roll(perm, -1, axis=1)
        edge = np.diagonal(perm_next).copy()
        d2, i, k = _best_two_opt_closed(perm, perm_next, edge, two_opt_mask)
        do, oi, length, om, reverse = _best_or_opt_closed(perm, perm_next, edge, or_opt_masks)
        if min(d2, do) >= -1e-12:
            break
        if d2 <= do:
            tour[i:k + 1] = tour[i:k + 1][::-1].copy()
        else:
            tour = _apply_or_opt(tour, oi, length, om, reverse)
    return [int(i) for i in tour]
