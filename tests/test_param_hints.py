"""Task parameter hints (Task Runner) and start_roi of the ROI scan task (ROI names only).

Usage: QT_QPA_PLATFORM=offscreen python tests/test_param_hints.py [<repo_root> [<roi_scan_with_resume.py> <taskwidget_before.py>]]
(1) RoiScanDummyTask as configured in dummy_config.cfg (roi_multicolour_scan_dummy), with the real
    roi_logic / laser_control_logic modules of dummy_config.cfg and a 5-ROI list saved by roi_logic;
    the dummy stage's move_abs is recorded.
(2) RoiScanSDTask with recording roi / laser stand-ins and a fake TriggerLogic (ZEN ready / done
    answered at once).
(3) Same calls as before the change for a run from the first ROI and for an interrupt (stand-ins);
    only when <roi_scan_with_resume.py> (the module before the start_roi change) is given.
(4) Task Runner widget hints; the comparisons with the widget before the change only when
    <taskwidget_before.py> is given.
Short settings: tests/_short.py (docs/TESTING.md). The 5-ROI list is kept (start at the 3rd ROI,
interrupt during the 4th).
"""
import sys, os, re, weakref, logging, importlib, importlib.util, tempfile, threading, copy, glob
from time import monotonic, sleep
from importlib.metadata import version

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _short  # noqa: E402  (short settings and shared test data, docs/TESTING.md)
repo = _short.repo_root(sys.argv)
before_path, tw_before_path = _short.reference_files(sys.argv, 2)
sys.path.insert(0, os.path.join(repo, 'src'))
from qtpy import QtCore, QtGui, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
import yaml  # noqa: E402
import qudi.core  # noqa: E402
from qudi.core.connector import Connector  # noqa: E402
from qudi.tasks import roi_multicolour_scan as rs  # noqa: E402

results = []


def check(label, cond, detail=''):
    results.append((label, bool(cond)))
    print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)


print('qudi-core', version('qudi-core'))
TMP = tempfile.mkdtemp()


# ------------------------------------------------------------------ real dummy modules
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
laser = build('laser_control_logic')
stage = MODULES['dummy_translation_stage']
roi.delete_all_roi()
for k in range(6):
    roi.add_roi(position=(100.0 * k, -50.0 * k, 0.0))
roi.save_roi_list(TMP, 'rois_test')
roi_list_path = next(iter(glob.glob(os.path.join(TMP, 'rois_test*'))))
roi.load_roi_list(roi_list_path)
NAMES = list(roi.roi_names)
print('    ROI list:', NAMES, roi_list_path)

STAGE_MOVES = []
_orig_move = stage.move_abs
stage.move_abs = lambda d: (STAGE_MOVES.append(dict(d)), _orig_move(d))[1]

entry = CFG['logic']['task_runner']['options']['module_tasks']['roi_multicolour_scan_dummy']
check('dummy_config: roi_multicolour_scan_dummy is RoiScanDummyTask',
      entry['module.Class'] == 'qudi.tasks.roi_multicolour_scan.RoiScanDummyTask')
user_cfg = os.path.join(TMP, 'roi_scan.yaml')
yaml.safe_dump({'sample_name': 'Mysample', 'save_path': os.path.join(TMP, 'data'), 'roi_list_path': roi_list_path,
                'imaging_sequence': [[488, 50.0], [561, 80.0]]}, open(user_cfg, 'w'))

LOGS = []


class H(logging.Handler):
    def emit(self, r):
        LOGS.append((r.levelno, r.getMessage()))


def run_threaded(task, kwargs, interrupt_when=None, timeout=120):
    out = {}

    def target():
        try:
            out['result'] = task(**kwargs)
        except Exception as err:
            out['error'] = err
    th = threading.Thread(target=target, daemon=True, name='task')
    th.start()
    t0 = monotonic()
    done = False
    while th.is_alive() and monotonic() - t0 < timeout:
        app.processEvents()
        if interrupt_when is not None and not done and interrupt_when():
            done = True
            task.interrupt()
        sleep(0.02)
    for _ in range(20):
        app.processEvents()
        sleep(0.01)
    return out


def dummy_task(**opts):
    cls = getattr(importlib.import_module(entry['module.Class'].rsplit('.', 1)[0]), entry['module.Class'].rsplit('.', 1)[1])
    task = cls()
    for k, v in entry['options'].items():
        setattr(task, k, v)
    task.user_config_path = user_cfg
    task.dummy_imaging_time_s = _short.IMAGING_S
    for k, v in opts.items():
        setattr(task, k, v)
    task.connect_modules({'roi_logic': roi, 'laser_logic': laser})
    if not any(isinstance(h, H) for h in task.log.handlers):
        task.log.addHandler(H())
    return task


def last_folder():
    folders = sorted(glob.glob(os.path.join(TMP, 'data', '*', '*_Scan_*')))
    return folders[-1] if folders else None


def run_dummy(start_roi, **kw):
    LOGS.clear()
    STAGE_MOVES.clear()
    n_folders = len(glob.glob(os.path.join(TMP, 'data', '*', '*_Scan_*')))
    task = dummy_task()
    out = run_threaded(task, {'start_roi': start_roi}, **kw)
    new_folder = len(glob.glob(os.path.join(TMP, 'data', '*', '*_Scan_*'))) == n_folders + 1
    return task, out, new_folder


# (1a) '' -> all ROIs
task, out, new_folder = run_dummy('')
res = out.get('result') or {}
folder = last_folder()
movies = open(os.path.join(folder, 'movie_name.txt')).read().split() if folder else []
meta = yaml.safe_load(open(os.path.join(folder, 'parameters.yml'))) if folder else {}
msgs = [m for _, m in LOGS]
check("(dummy '') all 6 ROIs in list order, new data folder, summary",
      res.get('imaged_rois') == NAMES and new_folder and res.get('directory') == folder
      and [m.split('_')[-2] for m in movies] == [n.split('_')[1] for n in NAMES], (out, movies))
check(f"(dummy '') log 'Scanning ROIs {NAMES[0]} to {NAMES[-1]} (6 of 6)'",
      f'Scanning ROIs {NAMES[0]} to {NAMES[-1]} (6 of 6)' in msgs, msgs[:6])
check("(dummy '') metadata: all 6 ROIs with positions, start_roi ''",
      meta.get('start_roi') == '' and [k for k in meta if k.startswith('ROI')] == NAMES
      and meta[NAMES[1]].startswith('X = 100.0'), meta)
check("(dummy '') no checkpoint file, no resume message",
      not glob.glob(os.path.join(TMP, 'data', '*checkpoint*')) and not any('esum' in m or 'heckpoint' in m for m in msgs))

# (1b) 'ROI_005' (last ROI) and ' ROI_002 ' -> from that ROI to the end
for start, first in (('ROI_005', 5), (' ROI_002 ', 2)):
    task, out, new_folder = run_dummy(start)
    res = out.get('result') or {}
    meta = yaml.safe_load(open(os.path.join(last_folder(), 'parameters.yml')))
    msgs = [m for _, m in LOGS]
    moved = [m for m in msgs if m.startswith('Moving to ')]
    n = 6 - first
    check(f'(dummy {start!r}) ROIs {NAMES[first]}..{NAMES[-1]} only, new folder, log "Scanning ROIs '
          f'{NAMES[first]} to {NAMES[-1]} ({n} of 6)"',
          res.get('imaged_rois') == NAMES[first:] and new_folder and moved == [f'Moving to {x}' for x in NAMES[first:]]
          and f'Scanning ROIs {NAMES[first]} to {NAMES[-1]} ({n} of 6)' in msgs, (out, moved))
    check(f'(dummy {start!r}) metadata: ROIs of the run with positions, start_roi {start.strip()!r}',
          meta.get('start_roi') == start.strip() and [k for k in meta if k.startswith('ROI')] == NAMES[first:], meta)
    check(f'(dummy {start!r}) cleanup moves the stage back to the first ROI of the list ({NAMES[0]})',
          STAGE_MOVES and abs(STAGE_MOVES[-1].get('x', 1) - 0.0) < 1e-6, STAGE_MOVES[-2:])

# (1c) invalid start ROIs -> error before any hardware call, no folder
for start in ('5', '1', '0', '99', 'ROI_999', 'roi_005'):
    vel_calls = []
    task, out, new_folder = run_dummy(start)
    err = str(out.get('error'))
    check(f'(dummy {start!r}) error with the valid range and first/last names; no stage move, no folder, '
          f'no hardware touched',
          out.get('error') is not None and f'from {NAMES[0]} to {NAMES[-1]}' in err and 'position' not in err
          and repr(start) in err and STAGE_MOVES == [] and not new_folder and task._hardware_touched is False,
          (err, STAGE_MOVES))
print('    error message:', err)

# (1d) interrupt mid-scan (during ROI_003, start at ROI_001) -> cleanup as before
task, out, new_folder = run_dummy('ROI_001', interrupt_when=lambda: any(m == f'Moving to {NAMES[3]}' for _, m in LOGS))
msgs = [m for _, m in LOGS]
check('(dummy interrupt) task stopped during ROI 4; ROIs 2 and 3 imaged; cleanup ran and moved the stage '
      'back to ROI 1; ROI GUI unlocked; scan velocity restored',
      task.success is False and task._scanned_rois == NAMES[1:3] and 'cleanup finished' in msgs
      and abs(STAGE_MOVES[-1].get('x', 1)) < 1e-6 and task._prev_stage_velocity
      and roi.get_stage_velocity(list(task._prev_stage_velocity)) == task._prev_stage_velocity,
      (task._scanned_rois, msgs[-4:], STAGE_MOVES[-1:]))


# ------------------------------------------------------------------ (2) SD task with stand-ins + fake TriggerLogic
class Rec:
    def __init__(self):
        self.calls = []

    def rec(self, name, *args):
        self.calls.append((name, args))


class _Stand:
    def __init__(self, rec):
        self._rec = rec

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return lambda *a, **k: self._rec.rec(name, *a, *k.values()) or True


class RoiLogic(_Stand):
    _meta = {'mro': ('RoiLogic',)}

    def load_roi_list(self, path):
        self._rec.rec('load_roi_list', path)
        self.roi_names = ['ROI_001', 'ROI_002', 'ROI_003']

    def get_stage_velocity(self, axes):
        self._rec.rec('get_stage_velocity', axes)
        return {a: 6000.0 for a in axes}

    def get_roi_position(self, name):
        self._rec.rec('get_roi_position', name)
        return (float(name[-1]) * 10, 0.0, 0.0)

    def stage_wait_for_idle(self):
        self._rec.rec('stage_wait_for_idle')


class LaserControlLogic(_Stand):
    _meta = {'mro': ('LaserControlLogic',)}


class TriggerLogic(_Stand):
    _meta = {'mro': ('TriggerLogic',)}

    def is_triggered(self, name):
        self._rec.rec('is_triggered', name)
        if name == 'trigger_ZEN_ready':
            ZEN.ready()  # ZEN starts the experiment: new data folder
        return True


KEEP = []
ZEN = _short.ZenFolders(os.path.join(TMP, 'zen'))  # zen_saving_path of the SD runs


def sd_task(cls, rec, path):
    stands = {'roi_logic': RoiLogic(rec), 'laser_logic': LaserControlLogic(rec), 'trigger_logic': TriggerLogic(rec)}
    KEEP.append(stands)
    task = type(cls.__name__ + 'UnderTest', (cls,), {'user_config_path': path})()
    task.connect_modules(stands)
    if not any(isinstance(h, H) for h in task.log.handlers):
        task.log.addHandler(H())
    return task


# the ZEN settings box of RoiScanSDTask is answered 'Done - continue' (tests/_short.py AutoAnswer)
ZEN_BOX = _short.AutoAnswer('ZEN settings')
sd_cfg = os.path.join(TMP, 'roi_scan_sd.yaml')
yaml.safe_dump({'sample_name': 'SDsample', 'zen_saving_path': ZEN.root, 'roi_list_path': '/fake/rois.json',
                'imaging_sequence': [[488, 50.0]]}, open(sd_cfg, 'w'))
for start, n in (('', 3), ('ROI_002', 2)):
    LOGS.clear()
    rec = Rec()
    task = sd_task(rs.RoiScanSDTask, rec, sd_cfg)
    res = task(start_roi=start)
    msgs = [m for _, m in LOGS]
    i_loops = next((k for k, m in enumerate(msgs) if m == f'ZEN: set the number of acquisition loops to {n}'), None)
    i_ready = next((k for k, m in enumerate(msgs) if m.startswith('Waiting for ZEN to signal it is ready')), None)
    first_ready_poll = next(k for k, c in enumerate(rec.calls) if c == ('is_triggered', ('trigger_ZEN_ready',)))
    check(f'(SD {start!r}) log "ZEN: set the number of acquisition loops to {n}" before waiting for ZEN ready; '
          f'{n} ROI(s) imaged (2 ZEN blocks each)',
          i_loops is not None and i_ready is not None and i_loops < i_ready and task.success
          and res['imaged_rois'] == ['ROI_001', 'ROI_002', 'ROI_003'][3 - n:]
          and sum(c == ('send_trigger', ('trigger_ZEN_start_block',)) for c in rec.calls) == 2 * n,
          (msgs[:8], res))

# ------------------------------------------------------------------ (3) same calls as before (stand-ins)
if before_path is None:
    _short.skipped("(same as before) start_roi '' makes the same roi / laser calls as resume_from_roi=False")
else:
    spec = importlib.util.spec_from_file_location('rs_before', before_path)
    rs_before = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs_before)


    def calls_of(module, kwargs, interrupt_at=None):
        rec = Rec()
        cls = module.RoiScanDummyTask
        task = sd_task(cls, rec, user_cfg_stand)
        task.dummy_imaging_time_s = 0.3  # timing of the interrupt below (0.45 s)
        if interrupt_at:
            threading.Timer(interrupt_at, task.interrupt).start()
        try:
            task(**kwargs)
        except Exception:
            pass
        return [c for c in rec.calls], task.success


    user_cfg_stand = os.path.join(TMP, 'roi_scan_stand.yaml')
    yaml.safe_dump({'sample_name': 'Stand', 'save_path': os.path.join(TMP, 'stand_data'), 'roi_list_path': '/fake/rois.json',
                    'imaging_sequence': [[488, 50.0]]}, open(user_cfg_stand, 'w'))
    for label, interrupt_at in (('full run', None), ('interrupt during ROI 2', 0.45)):
        old_calls, old_ok = calls_of(rs_before, {'resume_from_roi': False}, interrupt_at)
        new_calls, new_ok = calls_of(rs, {'start_roi': ''}, interrupt_at)
        check(f"(same as before, {label}) start_roi '' makes the same roi / laser calls, same order, as "
              f"resume_from_roi=False before ({len(new_calls)} calls), same outcome",
              old_calls == new_calls and old_ok == new_ok, (old_calls, new_calls))

src = open(os.path.join(repo, 'src/qudi/tasks/roi_multicolour_scan.py'), encoding='utf-8').read()
check('no resume / checkpoint left in roi_multicolour_scan.py; call parameter start_roi (str, default "")',
      not re.search(r'resume|checkpoint|_imaged_rois', src, re.I)
      and list(rs.RoiScanDummyTask.call_parameters()) == ['start_roi'])

# ------------------------------------------------------------------ (4) Task Runner widget: hints
from qudi.gui.task_runner.taskwidget import TaskWidget  # noqa: E402
from qudi.core.scripting.moduletask import ModuleTask  # noqa: E402
tw_before = None
if tw_before_path is not None:
    spec = importlib.util.spec_from_file_location('tw_before', tw_before_path)
    tw_before = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tw_before)
HINT = 'ROI name, e.g. ROI_005 (empty = first ROI)'
check('RoiScanTaskBase.parameter_hints', rs.RoiScanTaskBase.parameter_hints == {'start_roi': HINT}
      and rs.RoiScanSDTask.parameter_hints == {'start_roi': HINT})

w = TaskWidget(task_type=rs.RoiScanDummyTask, task_name='roi_multicolour_scan_dummy')
label, editor = w.parameter_widgets['start_roi']
w.resize(700, w.sizeHint().height())
w.show()
app.processEvents()
check('(GUI) start_roi editor is a QLineEdit: grey placeholder = hint, tooltip on editor and label, field empty',
      isinstance(editor, QtWidgets.QLineEdit) and editor.placeholderText() == HINT and editor.toolTip() == HINT
      and label.toolTip() == HINT and editor.text() == '', (type(editor), editor.placeholderText()))
img = w.grab()
img.save(os.path.join(TMP, 'hint_empty.png'))
# hover: a tooltip event on the field shows the hint
pos = editor.rect().center()
QtWidgets.QApplication.sendEvent(editor, QtGui.QHelpEvent(QtCore.QEvent.ToolTip, pos, editor.mapToGlobal(pos)))
app.processEvents()
check('(GUI) hovering the field shows the tooltip with the hint', QtWidgets.QToolTip.isVisible()
      and QtWidgets.QToolTip.text() == HINT, QtWidgets.QToolTip.text())
QtWidgets.QToolTip.hideText()
editor.setText('ROI_005')
app.processEvents()
w.grab().save(os.path.join(TMP, 'hint_filled.png'))
check('(GUI) typed value replaces the grey hint; get_parameters returns it',
      w.get_parameters() == {'start_roi': 'ROI_005'})
if tw_before is None:
    _short.skipped('(GUI) no layout change: same size hint as before the change')
else:
    old = tw_before.TaskWidget(task_type=rs.RoiScanDummyTask, task_name='roi_multicolour_scan_dummy')
    check('(GUI) no layout change: same size hint as before the change',
          w.sizeHint() == old.sizeHint(), (w.sizeHint(), old.sizeHint()))


class NoHintTask(ModuleTask):
    """Task without parameter_hints, with a text and a number parameter."""
    def _run(self, name: str = '', count: int = 3) -> None:
        pass


for cls in (NoHintTask,) if tw_before is not None else ():
    new_w = TaskWidget(task_type=cls, task_name='x')
    old_w = tw_before.TaskWidget(task_type=cls, task_name='x')
    same = all(
        type(n_e) is type(o_e) and n_l.text() == o_l.text() and n_l.toolTip() == o_l.toolTip() == ''
        and n_e.toolTip() == o_e.toolTip() == ''
        and (not isinstance(n_e, QtWidgets.QLineEdit) or n_e.placeholderText() == o_e.placeholderText() == '')
        for (n_l, n_e), (o_l, o_e) in zip(new_w.parameter_widgets.values(), old_w.parameter_widgets.values()))
    check(f'(GUI) task without parameter_hints ({cls.__name__}: name, count): same editors, no tooltip, '
          f'no placeholder, same size hint as before', same and new_w.sizeHint() == old_w.sizeHint()
          and len(new_w.parameter_widgets) == 2)

if tw_before is None:
    _short.skipped('(GUI) task without parameter_hints: same editors, no tooltip, no placeholder, same size hint as before')
print(f'\n{sum(ok for _, ok in results)}/{len(results)} passed', flush=True)
os._exit(0 if all(ok for _, ok in results) else 1)
