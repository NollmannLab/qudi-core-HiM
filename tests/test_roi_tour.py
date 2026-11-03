"""qudi.util.roi_path closed tour (optimize_closed_tour, tour_cost, longest_move), no qudi import.

Usage: python tests/test_roi_tour.py [<repo_root>]
"""
import sys, os, itertools, importlib.util
from time import perf_counter
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _short  # noqa: E402  (short settings and shared test data, docs/TESTING.md)
spec = importlib.util.spec_from_file_location('roi_path', os.path.join(_short.repo_root(sys.argv), 'src/qudi/util/roi_path.py'))
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)
results = []


def check(label, cond, detail=''):
    results.append((label, bool(cond)))
    print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)


def brute_closed(xy, speeds, start):
    n = len(xy)
    others = [i for i in range(n) if i != start]
    return min(rp.tour_cost(xy, [start, *p], speeds) for p in itertools.permutations(others))


rng = np.random.default_rng(11)

# definitions
sq = [[0, 0], [10, 0], [10, 30], [0, 30]]
check('tour_cost / longest_move include the closing move (x 1/s, y 3/s: 10+10+10+10, longest 10; 0 -> 50 -> 5 -> 0: longest 50)',
      rp.tour_cost(sq, [0, 1, 2, 3], (1, 3)) == 40 and rp.longest_move(sq, [0, 1, 2, 3], (1, 3)) == 10
      and rp.tour_cost(sq, [0, 2, 1, 3], (1, 3)) == 40 and rp.longest_move([[0, 0], [50, 0], [5, 0]], [0, 1, 2]) == 50)
check('path_cost (open) unchanged: no closing move', rp.path_cost(sq, [0, 1, 2, 3], (1, 3)) == 30)

# exact vs brute force, 5-9 points
ok, diffs = True, []
for _ in range(25):
    n = int(rng.integers(5, 10))
    xy = rng.uniform(0, 1000, (n, 2))
    speeds = tuple(rng.uniform(0.5, 2.0, 2))
    start = int(rng.integers(0, n))
    order = rp.optimize_closed_tour(xy, speeds, start=start, tolerance=0)
    c, b = rp.tour_cost(xy, order, speeds), brute_closed(xy, speeds, start)
    diffs.append(c - b)
    ok &= abs(c - b) < 1e-9 and order[0] == start and sorted(order) == list(range(n))
check(f'exact closed tour (Held-Karp, tolerance 0) = brute force on 25 random sets of 5-9 points '
      f'(max difference {max(diffs):.1e})', ok)

# heuristic (exact disabled) within 2 % of exact, 10-12 points
ratios = []
for _ in range(20):
    n = int(rng.integers(10, 13))
    xy = rng.uniform(0, 1000, (n, 2))
    speeds = (1.0, float(rng.uniform(0.5, 2.0)))
    exact = rp.tour_cost(xy, rp.optimize_closed_tour(xy, speeds, tolerance=0), speeds)
    saved, rp.EXACT_MAX_POINTS = rp.EXACT_MAX_POINTS, 0
    try:
        heur = rp.tour_cost(xy, rp.optimize_closed_tour(xy, speeds, tolerance=0), speeds)
    finally:
        rp.EXACT_MAX_POINTS = saved
    ratios.append(heur / exact)
check(f'2-opt + Or-opt within 2 % of the exact closed tour on 20 random sets of 10-12 points '
      f'(worst {100 * (max(ratios) - 1):.2f} %, mean {100 * (np.mean(ratios) - 1):.2f} %)', max(ratios) <= 1.02, ratios)

# closed tour vs the previous open-path result (both evaluated as closed tours)
print('    n  seed | open path as closed: total  longest | closed tour (tol 0.02): total  longest | time')
not_worse = True
for n in (30, 50):
    for seed in range(5):
        xy = np.random.default_rng(100 + seed).uniform(0, 10000, (n, 2))
        speeds = (1000.0, 1000.0) if seed % 2 == 0 else (1000.0, 500.0)
        old = rp.optimize_open_path(xy, speeds)
        t0 = perf_counter()
        new = rp.optimize_closed_tour(xy, speeds)
        dt = perf_counter() - t0
        ot, ol = rp.tour_cost(xy, old, speeds), rp.longest_move(xy, old, speeds)
        nt, nl = rp.tour_cost(xy, new, speeds), rp.longest_move(xy, new, speeds)
        not_worse &= nt <= ot + 1e-9
        print(f'   {n:3d} {seed:4d} | {ot:26.1f} {ol:8.1f} | {nt:29.1f} {nl:8.1f} | {dt:.2f} s')
check('30 and 50 random points (5 sets each, equal and unequal speeds): closed total not worse than the '
      'open-path result evaluated as a closed tour', not_worse)


# tolerance: 0 -> best total found; 0.02 -> longest move <= longest move at 0
def candidates_of(xy, speeds, tolerance):
    found = []
    orig = rp._local_search_closed

    def rec(cost, tour):
        t = orig(cost, tour)
        found.append(t)
        return t
    rp._local_search_closed = rec
    try:
        order = rp.optimize_closed_tour(xy, speeds, tolerance=tolerance)
    finally:
        rp._local_search_closed = orig
    return order, found


ok0, ok2, gains = True, True, []
for n in (20, 30, 50):
    for seed in range(4):
        xy = np.random.default_rng(200 + seed).uniform(0, 10000, (n, 2))
        o0, found = candidates_of(xy, (1.0, 1.0), 0.0)
        best = min(rp.tour_cost(xy, t) for t in found)
        o2 = rp.optimize_closed_tour(xy, (1.0, 1.0), tolerance=0.02)
        ok0 &= abs(rp.tour_cost(xy, o0) - best) < 1e-9
        ok2 &= (rp.longest_move(xy, o2) <= rp.longest_move(xy, o0) + 1e-9
                and rp.tour_cost(xy, o2) <= 1.02 * best + 1e-9)
        gains.append((rp.longest_move(xy, o0) - rp.longest_move(xy, o2), rp.tour_cost(xy, o2) / best - 1))
check('tolerance 0: total = best total among all tours found (12 sets of 20-50 points)', ok0)
reduced = [g for g in gains if g[0] > 1e-9]
check(f'tolerance 0.02: longest move <= longest move at tolerance 0, total within 2 % of the best '
      f'(longest move shorter in {len(reduced)}/12 sets, by up to {max([g[0] for g in gains]):.0f} s for '
      f'+{100 * max([g[1] for g in gains]):.2f} % total)', ok2)

# start and direction
ok = True
for n in (1, 2, 3, 4, 8, 13, 30):
    xy = rng.uniform(0, 1000, (n, 2))
    c = rp.move_time_matrix(xy)
    for start in {0, n - 1, n // 2}:
        o = rp.optimize_closed_tour(xy, start=start)
        ok &= o[0] == start and sorted(o) == list(range(n))
        if n > 2:
            ok &= c[start, o[1]] <= c[start, o[-1]]
check('first index always start, permutation, direction with the shorter first move (n = 1, 2, 3, 4, 8, 13, 30)', ok)
xy = rng.uniform(0, 1000, (30, 2))
check('deterministic for a given seed', rp.optimize_closed_tour(xy, seed=4) == rp.optimize_closed_tour(xy, seed=4))

# grid: optimal closed tour on a 6 x 5 grid is 30 one-step moves
grid = [(x * 100.0, y * 100.0) for y in range(5) for x in range(6)]
idx = list(range(1, 30))
rng.shuffle(idx)
shuffled = [grid[0]] + [grid[i] for i in idx]
o = rp.optimize_closed_tour(shuffled)
check(f'shuffled 6 x 5 grid: closed tour of 30 one-step moves (total {rp.tour_cost(shuffled, o):g}, longest '
      f'{rp.longest_move(shuffled, o):g})', abs(rp.tour_cost(shuffled, o) - 3000) < 1e-9 and rp.longest_move(shuffled, o) == 100)

# timing
xy50 = rng.uniform(0, 10000, (50, 2))
t0 = perf_counter()
rp.optimize_closed_tour(xy50, speeds=(1000.0, 1000.0))
dt = perf_counter() - t0
check(f'50 points: {dt:.2f} s (< 1 s)', dt < 1.0)
xy12 = rng.uniform(0, 10000, (12, 2))
t0 = perf_counter()
rp.optimize_closed_tour(xy12)
check(f'12 points (exact + heuristic candidates): {perf_counter() - t0:.2f} s', True)
print(f'\n{sum(ok for _, ok in results)}/{len(results)} passed')
sys.exit(0 if all(ok for _, ok in results) else 1)
