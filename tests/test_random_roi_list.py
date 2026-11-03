"""make_random_roi_list CLI + loading in the ROI GUI + path optimization end to end.

Usage: QT_QPA_PLATFORM=offscreen python tests/test_random_roi_list.py [<repo_root>]
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
from qudi.util.roi_path import path_cost  # noqa: E402
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



import subprocess, filecmp
TMP = tempfile.mkdtemp()
PY = sys.executable
ENV = dict(os.environ, PYTHONPATH=os.path.join(repo, 'src'))


def cli(*a):
    p = subprocess.run([PY, '-m', 'qudi.util.make_random_roi_list', *a], capture_output=True, text=True, env=ENV, cwd=TMP)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


# ------------------------------------------------------------------ CLI
rc, out, err = cli('--n', '25')
f25 = os.path.join(TMP, 'random_25_rois.json')
print('    stdout:', out)
d = json.load(open(f25))
check('default call: ./random_25_rois.json, prints path and count, exit 0',
      rc == 0 and out == f'{f25}: 25 ROI(s)' and d['name'] == 'random_25_rois', (rc, out, err))
xy = np.array([r['position'] for r in d['rois']])
check('names ROI_001..ROI_025, x / y in [0, 10000], z = 0, ROI-logic dict keys',
      [r['name'] for r in d['rois']] == [f'ROI_{k:03d}' for k in range(1, 26)]
      and xy[:, :2].min() >= 0 and xy[:, :2].max() <= 10000 and np.all(xy[:, 2] == 0)
      and set(d) == {'name', 'creation_time', 'cam_image', 'cam_image_extent', 'rois'})
mtime = os.path.getmtime(f25); content = open(f25).read()
rc, out, err = cli('--n', '25')
check('existing file -> exit 1, error message, file not modified',
      rc == 1 and 'already exists' in err and open(f25).read() == content and os.path.getmtime(f25) == mtime, (rc, err))
ct = ['--creation-time', '2026-10-23 16:00:00.000000']
cli('--n', '25', '--name', 'a', *ct); cli('--n', '25', '--name', 'b', *ct)
fa, fb = (json.load(open(os.path.join(TMP, x + '.json'))) for x in 'ab')
fa.pop('name'); fb.pop('name')
check('same seed -> same ROIs (fixed creation time: same content apart from the name)', fa == fb)
cli('--n', '25', '--name', 'same', '--folder', os.path.join(TMP, 'f1'), *ct)
cli('--n', '25', '--name', 'same', '--folder', os.path.join(TMP, 'f2'), *ct)
check('same arguments and seed -> byte-identical file',
      filecmp.cmp(os.path.join(TMP, 'f1/same.json'), os.path.join(TMP, 'f2/same.json'), shallow=False))
cli('--n', '25', '--name', 'seed1', '--seed', '1')
check('different seed -> different positions',
      json.load(open(os.path.join(TMP, 'seed1.json')))['rois'] != json.load(open(f25))['rois'])
rc, out, _ = cli('--n', '40', '--z-range', '0', '50', '--seed', '3', '--name', 'test_40', '--folder', os.path.join(TMP, 'sub'),
                 '--x-range', '-5000', '5000', '--y-range', '100', '200', '--first-number', '7')
d40 = json.load(open(os.path.join(TMP, 'sub/test_40.json')))
p40 = np.array([r['position'] for r in d40['rois']])
check('40 ROIs, random z in [0, 50], ranges (negative x), ROI_007..ROI_046, folder created',
      rc == 0 and len(p40) == 40 and p40[:, 2].min() >= 0 and p40[:, 2].max() <= 50 and np.ptp(p40[:, 2]) > 0
      and p40[:, 0].min() >= -5000 and p40[:, 0].max() <= 5000 and p40[:, 1].min() >= 100 and p40[:, 1].max() <= 200
      and [r['name'] for r in d40['rois']] == [f'ROI_{k:03d}' for k in range(7, 47)], out)
rc, out, _ = cli('--n', '5', '--z', '12.5', '--name', 'z12')
check('--z fixed value', rc == 0 and all(r['position'][2] == 12.5 for r in json.load(open(os.path.join(TMP, 'z12.json')))['rois']))
rc, out, err = cli('--n', '5', '--z', '1', '--z-range', '0', '2')
check('--z with --z-range -> refused by argparse', rc == 2 and 'not allowed' in err, err[-80:])
for bad in (('--n', '-1'), ('--x-range', '10', '0'), ('--creation-time', 'yesterday')):
    rc, _, err = cli(*bad, '--name', 'bad')
    ok_bad = rc == 1 and 'Error' in err and not os.path.exists(os.path.join(TMP, 'bad.json'))
    check(f'invalid {" ".join(bad)} -> exit 1, no file', ok_bad, (rc, err))
rc, out, _ = cli('--n', '0')
d0 = json.load(open(os.path.join(TMP, 'random_0_rois.json')))
check('--n 0 -> empty list file', rc == 0 and d0['rois'] == [] and out.endswith(': 0 ROI(s)'))
rc, out, _ = cli('--help')
check('--help', rc == 0 and '--first-number' in out)

# ------------------------------------------------------------------ GUI load
roi = build('roi_logic')
gui = build('roi_gui')
mw = gui._mw
mw.save_path_LineEdit.setText(TMP)


def pump(k=30):
    for _ in range(k):
        app.processEvents()
        sleep(0.01)


def gui_load(path):
    orig = QtWidgets.QFileDialog.getOpenFileName
    QtWidgets.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (path, 'json files (*.json)'))
    try:
        mw.load_list_Action.trigger()
        pump()
    finally:
        QtWidgets.QFileDialog.getOpenFileName = orig


def combo():
    return [mw.active_roi_ComboBox.itemText(i) for i in range(mw.active_roi_ComboBox.count())]


gui_load(f25)
check('GUI "Load list": 25 markers, combo ROI_001..ROI_025, list name, positions as in the file',
      len(gui._markers) == 25 and combo() == [f'ROI_{k:03d}' for k in range(1, 26)]
      and mw.roi_list_name_LineEdit.text() == 'random_25_rois'
      and np.allclose([roi.get_roi_position(r['name']) for r in d['rois']], xy), (len(gui._markers), combo()[:2]))
gui_load(os.path.join(TMP, 'sub/test_40.json'))
check('GUI load of the 40-ROI list (random z): 40 markers, z kept',
      len(gui._markers) == 40 and np.allclose(roi.get_roi_position('ROI_046'), d40['rois'][-1]['position']))
gui_load(os.path.join(TMP, 'random_0_rois.json'))
check('GUI load of the empty list: 0 markers, empty combo, list name shown',
      len(gui._markers) == 0 and combo() == [] and mw.roi_list_name_LineEdit.text() == 'random_0_rois')

# ------------------------------------------------------------------ end to end with the path optimization
rc, out, _ = cli('--n', '30', '--name', 'e2e')
fe = os.path.join(TMP, 'e2e.json')
de = json.load(open(fe))
gui_load(fe)
before_markers = {k: tuple(v.position) if hasattr(v, 'position') else None for k, v in gui._markers.items()}
n_files = set(os.listdir(TMP))
mw.optimize_path_Action.trigger()
pump(80)
new = sorted(set(os.listdir(TMP)) - n_files)
print('    new files:', new)
bk = [f for f in new if f.startswith('e2e_before_optimization_')]
op = [f for f in new if f.startswith('e2e_optimized_')]
check('optimize path after loading: backup file and optimized file written', len(bk) == 1 and len(op) == 1, new)
dbk = json.load(open(os.path.join(TMP, bk[0])))
dop = json.load(open(os.path.join(TMP, op[0])))
check('backup = the generated list (same ROIs, positions, creation time)',
      dbk['rois'] == de['rois'] and dbk['creation_time'] == de['creation_time'])
names = [r['name'] for r in dop['rois']]
check('optimized names ROI_031..ROI_060, first ROI kept first, same set of positions',
      names == [f'ROI_{k:03d}' for k in range(31, 61)] and dop['rois'][0]['position'] == de['rois'][0]['position']
      and sorted(map(tuple, (r['position'] for r in dop['rois']))) == sorted(map(tuple, (r['position'] for r in de['rois'])))
      and [r['position'] for r in dop['rois']] != [r['position'] for r in de['rois']])
gui_xy = [tuple(np.round(roi.get_roi_position(nm), 6)) for nm in combo()]
check('GUI after the click: combo / markers ROI_031..ROI_060 in the new order, list name updated, ROI_031 active',
      combo() == names and set(gui._markers) == set(names)
      and gui_xy == [tuple(np.round(r['position'], 6)) for r in dop['rois']]
      and mw.roi_list_name_LineEdit.text() == dop['name'] and mw.active_roi_ComboBox.currentText() == 'ROI_031')
msg = [m for lvl, m in LOGS if m.startswith('ROI path optimized')]
print('    log:', msg[-1] if msg else None)

print(f'\n{sum(ok for _, ok in results)}/{len(results)} passed', flush=True)
os._exit(0 if all(ok for _, ok in results) else 1)
