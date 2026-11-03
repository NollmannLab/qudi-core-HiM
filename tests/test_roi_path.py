"""qudi.util.roi_path on its own (no qudi import needed).

Usage: python tests/test_roi_path.py [<repo_root>]
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


def brute(xy, speeds, start):
    n = len(xy)
    best = None
    for perm in itertools.permutations([i for i in range(n) if i != start]):
        order = [start, *perm]
        c = rp.path_cost(xy, order, speeds)
        if best is None or c < best[0] - 1e-12:
            best = (c, order)
    return best


rng = np.random.default_rng(1)
# cost definition
check('cost = max(|dx|/vx, |dy|/vy)', abs(rp.path_cost([[0, 0], [30, 10]], [0, 1], (10, 1)) - 10.0) < 1e-12
      and abs(rp.path_cost([[0, 0], [30, 10]], [0, 1], (1, 10)) - 30.0) < 1e-12)

# exact vs brute force, 5-9 points, random speeds and start
ok, worst = True, []
for trial in range(25):
    n = int(rng.integers(5, 10))
    xy = rng.uniform(0, 1000, (n, 2))
    speeds = tuple(rng.uniform(0.5, 2.0, 2))
    start = int(rng.integers(0, n))
    order = rp.optimize_open_path(xy, speeds, start=start)
    c = rp.path_cost(xy, order, speeds)
    b = brute(xy, speeds, start)[0]
    ok &= abs(c - b) < 1e-9 and order[0] == start and sorted(order) == list(range(n))
    worst.append(c - b)
check(f'exact (Held-Karp) = brute force on 25 random sets of 5-9 points (max difference {max(worst):.1e})', ok)

# 2-opt (exact disabled) within 2 % of the exact optimum on 10-12 points
ratios = []
for trial in range(15):
    n = int(rng.integers(10, 13))
    xy = rng.uniform(0, 1000, (n, 2))
    speeds = (1.0, float(rng.uniform(0.5, 2.0)))
    exact = rp.path_cost(xy, rp.optimize_open_path(xy, speeds, start=0), speeds)
    saved = rp.EXACT_MAX_POINTS
    rp.EXACT_MAX_POINTS = 0
    try:
        heur_order = rp.optimize_open_path(xy, speeds, start=0)
    finally:
        rp.EXACT_MAX_POINTS = saved
    ratios.append(rp.path_cost(xy, heur_order, speeds) / exact)
check(f'2-opt + restarts within 2 % of the exact optimum on 15 random sets of 10-12 points '
      f'(worst {100 * (max(ratios) - 1):.2f} %, mean {100 * (np.mean(ratios) - 1):.2f} %)', max(ratios) <= 1.02, ratios)

# first index always start, permutation, deterministic
firsts = True
for n in (1, 2, 3, 8, 13, 30):
    xy = rng.uniform(0, 1000, (n, 2))
    for start in {0, n - 1, n // 2}:
        order = rp.optimize_open_path(xy, start=start)
        firsts &= order[0] == start and sorted(order) == list(range(n))
check('first index is always start; result is a permutation (n = 1, 2, 3, 8, 13, 30)', firsts)
xy = rng.uniform(0, 1000, (25, 2))
check('deterministic: same input and seed -> same order', rp.optimize_open_path(xy, seed=3) == rp.optimize_open_path(xy, seed=3))

# serpentine grid stays serpentine-like (6 x 5 grid, pitch 100, start at a corner, list in shuffled order)
grid = [(x * 100.0, y * 100.0) for y in range(5) for x in range(6)]
idx = list(range(1, len(grid)))
rng.shuffle(idx)
shuffled = [grid[0]] + [grid[i] for i in idx]
order = rp.optimize_open_path(shuffled, start=0)
path = np.array([shuffled[i] for i in order])
steps = np.abs(np.diff(path, axis=0)).max(axis=1)
opt = rp.path_cost(shuffled, order)
check(f'serpentine 6 x 5 grid (shuffled list): every move is one grid step (cost {opt:g} = 29 x 100), '
      f'start kept', np.allclose(steps, 100.0) and abs(opt - 2900) < 1e-9 and tuple(path[0]) == grid[0], steps)
# with x 3x faster than y, a path of long x rows is preferred: the y steps are the minimum (4)
order_fx = rp.optimize_open_path(shuffled, speeds=(3.0, 1.0), start=0)
p = np.array([shuffled[i] for i in order_fx])
check('serpentine grid, x 3x faster: 4 row changes (y moves), the rest along x', int(np.sum(np.abs(np.diff(p[:, 1])) > 0)) == 4,
      int(np.sum(np.abs(np.diff(p[:, 1])) > 0)))

# timing
xy40 = rng.uniform(0, 10000, (40, 2))
t0 = perf_counter()
rp.optimize_open_path(xy40, speeds=(1.0, 1.0), start=0)
dt40 = perf_counter() - t0
check(f'40 points: {dt40:.2f} s (< 1 s)', dt40 < 1.0)
xy12 = rng.uniform(0, 10000, (12, 2))
t0 = perf_counter()
rp.optimize_open_path(xy12, start=0)
dt12 = perf_counter() - t0
check(f'12 points (exact): {dt12:.2f} s', dt12 < 2.0)
print(f'\n{sum(ok for _, ok in results)}/{len(results)} passed')
sys.exit(0 if all(ok for _, ok in results) else 1)
