"""ROI path optimization: roi_logic.optimize_roi_order / save_roi_list and the ROI GUI action.

Usage: QT_QPA_PLATFORM=offscreen python tests/test_roi_optimize.py [<repo_root>]
Real roi_logic (dummy stage of dummy_config.cfg) and RoiGUI, in a temporary folder.
"""
import sys, os, json, weakref, logging, importlib, tempfile, copy, glob, datetime as dt
from time import sleep
from importlib.metadata import version

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _short  # noqa: E402  (short settings and shared test data, docs/TESTING.md)
repo = _short.repo_root(sys.argv)
sys.path.insert(0, os.path.join(repo, 'src'))
from qtpy import QtCore, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
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


print('qudi-core', version('qudi-core'))
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

print(f'\n{sum(ok for _, ok in results)}/{len(results)} passed', flush=True)
os._exit(0 if all(ok for _, ok in results) else 1)
