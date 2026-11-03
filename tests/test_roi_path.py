"""ROI path optimization: open path and closed tour (qudi.util.roi_path, called directly), and the
"optimize path" action of the ROI logic / GUI (roi_logic.optimize_roi_order, save_roi_list).

Usage: QT_QPA_PLATFORM=offscreen python tests/test_roi_path.py [<repo_root>]
Short settings: tests/_short.py (docs/TESTING.md).
"""
import sys, os
from importlib.metadata import version

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _short  # noqa: E402  (short settings and shared test data, docs/TESTING.md)
repo = _short.repo_root(sys.argv)
sys.path.insert(0, os.path.join(repo, 'src'))
from qtpy import QtCore, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
print('qudi-core', version('qudi-core'))
KEEP_ALIVE = []  # objects of each section (Qt threads must not be destroyed while running)


# --- open path ---
def _section_open_path():
    """qudi.util.roi_path on its own (no qudi import needed)."""
    import sys, os, itertools, importlib.util
    from time import perf_counter
    import numpy as np

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
    KEEP_ALIVE.append(locals())  # modules, threads and widgets of the section live until the end
    return results

# --- closed tour ---
def _section_closed_tour():
    """qudi.util.roi_path closed tour (optimize_closed_tour, tour_cost, longest_move), no qudi import."""
    import sys, os, itertools, importlib.util
    from time import perf_counter
    import numpy as np

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
    KEEP_ALIVE.append(locals())  # modules, threads and widgets of the section live until the end
    return results

# --- ROI logic and GUI: optimize path ---
def _section_optimize():
    """ROI path optimization: roi_logic.optimize_roi_order / save_roi_list and the ROI GUI action.
    
    Real roi_logic (dummy stage of dummy_config.cfg) and RoiGUI, in a temporary folder."""
    import sys, os, json, weakref, logging, importlib, tempfile, copy, glob, datetime as dt
    from time import sleep
    from importlib.metadata import version

    from qtpy import QtCore, QtWidgets  # noqa: E402

    import numpy as np  # noqa: E402
    import yaml  # noqa: E402
    import qudi.core  # noqa: E402
    from qudi.core.connector import Connector  # noqa: E402
    from qudi.util.roi_path import tour_cost, longest_move  # noqa: E402
    import qudi.logic.roi_logic as roi_module  # noqa: E402

    results = []


    def check(label, cond, detail=''):
        results.append((label, bool(cond)))
        print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)


    LOGS = []


    class H(logging.Handler):
        def emit(self, r):
            LOGS.append((r.levelno, r.getMessage()))


    logging.getLogger().addHandler(H())


    class FakeMain(QtCore.QObject):
        pass


    MAIN = FakeMain()
    CFG = yaml.safe_load(open(os.path.join(repo, 'custom_config/dummy_config.cfg'), encoding='utf-8'))
    MODULES = {}


    def build(name):
        if name in MODULES:
            return MODULES[name]
        base = next(b for b in ('hardware', 'logic', 'gui') if name in (CFG.get(b) or {}))
        entry = CFG[base][name]
        mod, cls = entry['module.Class'].rsplit('.', 1)
        klass = getattr(importlib.import_module(f'qudi.{base}.{mod}'), cls)
        m = klass(qudi_main_weakref=weakref.ref(MAIN), name=name, config=_short.module_options(name, entry.get('options')))
        by_name = {c.name: c for k in dir(klass) if isinstance(c := getattr(klass, k, None), Connector)}
        for key, target in (entry.get('connect') or {}).items():
            m._meta['connectors'][next(k for k in m._meta['connectors'] if by_name[key] is getattr(klass, k))].connect(build(target))
        m.module_state.activate()
        _short.speed_up(m)
        MODULES[name] = m
        return m


    roi = build('roi_logic')
    stage = MODULES['dummy_translation_stage']
    TMP = tempfile.mkdtemp()
    rng = np.random.default_rng(7)


    def make_list(n, name='mylist'):
        roi.reset_roi_list()
        roi.set_roi_first_digit(1)
        for _ in range(n):
            roi.add_roi(position=np.array([rng.uniform(-5000, 5000), rng.uniform(-5000, 5000), rng.uniform(0, 50)]))
        roi.rename_roi_list(name)
        return roi.roi_list_to_dict(roi._roi_list)


    def as_json(d):
        return json.loads(json.dumps(d))


    def files():
        return sorted(os.path.basename(f) for f in glob.glob(os.path.join(TMP, '*.json')))


    class FixedNow(dt.datetime):
        fixed = None

        @classmethod
        def now(cls, tz=None):
            return cls.fixed or dt.datetime.now(tz)


    REAL_DT = roi_module.datetime


    def optimize(path):
        # the time stamp of the file names is chosen by the test (FixedNow.fixed) during the call only
        roi_module.datetime = FixedNow if FixedNow.fixed else REAL_DT
        try:
            return roi.optimize_roi_order(path)
        finally:
            roi_module.datetime = REAL_DT


    # ------------------------------------------------------------------ 25 random ROIs
    vel = roi.get_stage_velocity(['x', 'y'])
    print('    dummy stage velocity:', vel)
    before = make_list(25)
    names_before = roi.roi_names
    pos_before = {n: np.array(roi.get_roi_position(n)) for n in names_before}
    xy = np.array([pos_before[n][:2] for n in names_before])
    speeds = (float(vel['x']), float(vel['y']))
    FixedNow.fixed = dt.datetime(2026, 10, 23, 15, 30, 0)
    LOGS.clear()
    ok = optimize(TMP)
    app.processEvents()
    stamp = '20261023_153000'
    backup = os.path.join(TMP, f'mylist_before_optimization_{stamp}.json')
    optimized = os.path.join(TMP, f'mylist_optimized_{stamp}.json')
    check('optimize_roi_order -> True; backup and optimized list written', ok and files() == sorted(
        [os.path.basename(backup), os.path.basename(optimized)]), files())
    check('backup file identical in content to the list before', as_json(json.load(open(backup))) == as_json(before))
    opt = json.load(open(optimized))
    new_names = [r['name'] for r in opt['rois']]
    check('optimized file: ROI_026..ROI_050 in the new order, list name mylist_optimized_<stamp>',
          new_names == [f'ROI_{k:03d}' for k in range(26, 51)] and opt['name'] == f'mylist_optimized_{stamp}'
          and roi.roi_list_name == opt['name'] and roi.roi_names == new_names, (new_names[:3], opt['name']))
    new_pos = [np.array(r['position']) for r in opt['rois']]
    check('first ROI unchanged in position (ROI_001 -> ROI_026)', np.allclose(new_pos[0], pos_before['ROI_001']))
    matched = all(any(np.allclose(p, q) for q in pos_before.values()) for p in new_pos)
    same_set = sorted(map(tuple, np.round(new_pos, 9))) == sorted(map(tuple, np.round(list(pos_before.values()), 9)))
    check('every position (x, y, z) kept, z included; same set of positions', matched and same_set)
    xy_new = np.array([p[:2] for p in new_pos])
    old_t = tour_cost(xy, range(25), speeds)
    new_t = tour_cost(xy_new, range(25), speeds)
    old_l = longest_move(xy, range(25), speeds)
    new_l = longest_move(xy_new, range(25), speeds)
    msg = [m for lvl, m in LOGS if m.startswith('ROI path optimized')]
    print('    log:', msg[0] if msg else None)
    check(f'closed total reduced ({old_t:.1f} s -> {new_t:.1f} s), longest move {old_l:.1f} s -> {new_l:.1f} s; '
          f'log line with totals, longest moves, names, backup and saved file',
          new_t < old_t and msg and f'total {old_t:.1f} s -> {new_t:.1f} s, longest move {old_l:.1f} s -> {new_l:.1f} s '
          f'(incl. return to first ROI)' in msg[0] and 'renamed ROI_026..ROI_050' in msg[0]
          and backup in msg[0] and optimized in msg[0] and '(25 ROIs)' in msg[0])
    check('first ROI active, list metadata kept (creation time)', roi.active_roi == 'ROI_026'
          and opt['creation_time'] == before['creation_time'])
    roi.add_roi(position=np.array([0.0, 0.0, 0.0]))
    check('add_roi after the optimization -> ROI_051', roi.roi_names[-1] == 'ROI_051', roi.roi_names[-3:])
    roi.load_roi_list(backup)
    check('reloading the backup gives the original list', as_json(roi.roi_list_to_dict(roi._roi_list)) == as_json(before)
          and roi.roi_names == names_before)

    # ------------------------------------------------------------------ failures
    blocked = os.path.join(TMP, 'not_a_folder')
    open(blocked, 'w').close()
    before = make_list(10, 'blocked')
    LOGS.clear()
    ok = optimize(blocked)
    check('backup save failing (folder path is a file) -> False, error logged, list unchanged in memory',
          ok is False and as_json(roi.roi_list_to_dict(roi._roi_list)) == as_json(before)
          and any(lvl >= logging.ERROR and 'backup' in m for lvl, m in LOGS), LOGS[-3:])

    FixedNow.fixed = dt.datetime(2026, 10, 23, 16, 0, 0)
    before = make_list(10, 'exists')
    existing = os.path.join(TMP, 'exists_before_optimization_20261023_160000.json')
    open(existing, 'w').write('sentinel')
    LOGS.clear()
    ok = optimize(TMP)
    check('backup file already exists -> not overwritten, False, list unchanged',
          ok is False and open(existing).read() == 'sentinel' and as_json(roi.roi_list_to_dict(roi._roi_list)) == as_json(before)
          and any('already exists' in m for lvl, m in LOGS))
    FixedNow.fixed = dt.datetime(2026, 10, 23, 16, 5, 0)
    before = make_list(10, 'exists2')
    existing2 = os.path.join(TMP, 'exists2_optimized_20261023_160500.json')
    open(existing2, 'w').write('sentinel')
    LOGS.clear()
    ok = optimize(TMP)
    check('optimized file already exists -> not overwritten, False; backup on disk; optimized list in memory',
          ok is False and open(existing2).read() == 'sentinel'
          and os.path.exists(os.path.join(TMP, 'exists2_before_optimization_20261023_160500.json'))
          and roi.roi_names[0] == 'ROI_011' and roi.roi_list_name == 'exists2_optimized_20261023_160500'
          and any(lvl >= logging.ERROR and 'only in memory' in m for lvl, m in LOGS))
    FixedNow.fixed = None

    for n in (0, 1, 2):
        before = make_list(n, f'small{n}')
        n_files = len(files())
        LOGS.clear()
        ok = optimize(TMP)
        check(f'{n} ROI(s) -> True, "nothing to optimize", no file, no change',
              ok is True and len(files()) == n_files and as_json(roi.roi_list_to_dict(roi._roi_list)) == as_json(before)
              and any('nothing to optimize' in m for lvl, m in LOGS))

    # ------------------------------------------------------------------ normal save: unchanged behaviour (overwrites)
    make_list(4, 'plain')
    target = os.path.join(TMP, 'plain.json')
    open(target, 'w').write('old')
    r = roi.save_roi_list(TMP, 'plain')
    check('save_roi_list default (Save button): overwrites an existing file, returns True',
          r is True and json.load(open(target))['name'] == 'plain')

    # ------------------------------------------------------------------ GUI
    gui = build('roi_gui')
    mw = gui._mw
    mw.save_path_LineEdit.setText(TMP)
    make_list(12, 'guilist')
    for _ in range(20):
        app.processEvents()
        sleep(0.01)
    check('GUI: tooltip of the optimize action', mw.optimize_path_Action.toolTip() ==
          'Save a backup, reorder the ROIs along the shortest stage path (first ROI kept first), renumber them and '
          'save the result as a new list')
    old_markers = set(gui._markers)
    mw.optimize_path_Action.trigger()
    for _ in range(50):
        app.processEvents()
        sleep(0.01)
    combo = [mw.active_roi_ComboBox.itemText(i) for i in range(mw.active_roi_ComboBox.count())]
    check('GUI click: ROI list (combo box), markers and list name refresh; first ROI active',
          combo == [f'ROI_{k:03d}' for k in range(13, 25)] and set(gui._markers) == set(combo)
          and set(gui._markers) != old_markers and mw.roi_list_name_LineEdit.text().startswith('guilist_optimized_')
          and mw.active_roi_ComboBox.currentText() == 'ROI_013' and roi.roi_list_name == mw.roi_list_name_LineEdit.text(),
          (combo[:3], mw.roi_list_name_LineEdit.text()))
    roi.disable_roi_actions()
    for _ in range(20):
        app.processEvents()
        sleep(0.01)
    disabled = not mw.optimize_path_Action.isEnabled()
    roi.enable_roi_actions()
    for _ in range(20):
        app.processEvents()
        sleep(0.01)
    check('GUI: action disabled while a task holds the ROI lock, enabled again after', disabled and mw.optimize_path_Action.isEnabled())
    mw.roi_list_name_LineEdit.setText('saved_by_button')
    mw.save_list_Action.trigger()
    app.processEvents()
    check('GUI: Save button still saves under the name of the field', os.path.exists(os.path.join(TMP, 'saved_by_button.json')))
    KEEP_ALIVE.append(locals())  # modules, threads and widgets of the section live until the end
    return results

SECTIONS = [
    ('open path', _section_open_path),
    ('closed tour', _section_closed_tour),
    ('ROI logic and GUI: optimize path', _section_optimize),
]

if __name__ == '__main__':
    all_results = []
    for title, run_section in SECTIONS:
        print(f'\n# --- {title} ---', flush=True)
        all_results += run_section()
    print(f'\n{sum(ok for _, ok in all_results)}/{len(all_results)} passed', flush=True)
    os._exit(0 if all(ok for _, ok in all_results) else 1)
