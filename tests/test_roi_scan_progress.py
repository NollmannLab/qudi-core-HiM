"""ROI scan progress in the Task Runner window.

Usage: QT_QPA_PLATFORM=offscreen python tests/test_roi_scan_progress.py [<repo_root>]
Real TaskRunnerLogic (own thread, as a threaded qudi logic module) and TaskRunnerGui, started with the
Run button. roi_logic and laser_control_logic are the real modules of dummy_config.cfg (dummy stage);
RoiScanDummyTask from its dummy_config entry, RoiScanSDTask with a fake TriggerLogic (ZEN answers at
once). Short settings and test data: tests/_short.py, tests/data/ (rois_2.json, roi_scan_experiment.yaml).
"""
import sys, os, re, weakref, logging, importlib, tempfile, copy
from time import monotonic, sleep
from importlib.metadata import version

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _short  # noqa: E402  (short settings and shared test data, docs/TESTING.md)
repo = _short.repo_root(sys.argv)
sys.path.insert(0, os.path.join(repo, 'src'))
from qtpy import QtCore, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
import yaml  # noqa: E402
import qudi.core  # noqa: E402
from qudi.core.connector import Connector  # noqa: E402
from qudi.logic.taskrunner_logic import TaskRunnerLogic  # noqa: E402
from qudi.gui.task_runner.task_runner_gui import TaskRunnerGui  # noqa: E402
from qudi.tasks import roi_multicolour_scan as rs  # noqa: E402
from qudi.tasks.common.progress import ProgressModuleTask  # noqa: E402

results = []


def check(label, cond, detail=''):
    results.append((label, bool(cond)))
    print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)


print('qudi-core', version('qudi-core'))
LOGS = []


class H(logging.Handler):
    def emit(self, r):
        LOGS.append((monotonic(), r.levelno, r.getMessage()))


logging.getLogger().addHandler(H())
TMP = tempfile.mkdtemp()


class Managed:
    def __init__(self, instance):
        self.instance = instance

    def activate(self):
        pass


class ModuleManager(dict):
    gui = None

    def deactivate_module(self, name):
        self.gui.module_state.deactivate()


class ThreadManager:
    def __init__(self):
        self.threads = []

    def get_new_thread(self, name):
        t = QtCore.QThread()
        t.setObjectName(name)
        self.threads.append(t)
        return t

    def quit_thread(self, thread):
        thread.quit()

    def join_thread(self, thread):
        thread.wait()


class FakeMain(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.module_manager = ModuleManager()
        self.thread_manager = ThreadManager()


MAIN = FakeMain()
CFG = yaml.safe_load(open(os.path.join(repo, 'custom_config/dummy_config.cfg'), encoding='utf-8'))
MODULES = {}


def build(name):
    if name in MODULES:
        return MODULES[name]
    base = next(b for b in ('hardware', 'logic') if name in (CFG.get(b) or {}))
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
ROIS = _short.ROI_LIST
roi.load_roi_list(ROIS)
NAMES = list(roi.roi_names)
N = len(NAMES)
print('    ROIs:', NAMES)


class TriggerLogic:  # stand-in; qudi-core connectors check _meta['mro']
    _meta = {'mro': ('TriggerLogic',)}

    def __init__(self):
        self.sent = []

    def send_trigger(self, name):
        self.sent.append(name)

    def is_triggered(self, name):
        return True


TRIGGER = TriggerLogic()
MAIN.module_manager.update({'roi_logic': Managed(roi), 'laser_control_logic': Managed(laser),
                            'trigger_logic': Managed(TRIGGER)})

user_cfg = _short.experiment(TMP, 'roi_scan_experiment.yaml', 'roi_scan', save_path=os.path.join(TMP, 'data'))
entry = copy.deepcopy(CFG['logic']['task_runner']['options']['module_tasks']['roi_multicolour_scan_dummy'])
check('dummy_config: roi_multicolour_scan_dummy is RoiScanDummyTask',
      entry['module.Class'] == 'qudi.tasks.roi_multicolour_scan.RoiScanDummyTask')
entry['options'].update({'user_config_path': user_cfg, 'dummy_imaging_time_s': _short.IMAGING_S})
tasks_cfg = {'roi_multicolour_scan_dummy': entry,
             'roi_scan_sd': {'module.Class': 'qudi.tasks.roi_multicolour_scan.RoiScanSDTask',
                             'connect': {'roi_logic': 'roi_logic', 'laser_logic': 'laser_control_logic',
                                         'trigger_logic': 'trigger_logic'},
                             'options': {'user_config_path': user_cfg}}}
check('RoiScanTaskBase derives from ProgressModuleTask; subclasses unchanged',
      rs.RoiScanTaskBase.__bases__ == (ProgressModuleTask,)
      and rs.RoiScanSDTask.__bases__ == (rs.SDImagingMixin, rs.RoiScanTaskBase)
      and rs.RoiScanDummyTask.__bases__ == (rs.DummyImagingMixin, rs.RoiScanTaskBase))

logic = TaskRunnerLogic(qudi_main_weakref=weakref.ref(MAIN), name='task_runner', config={'module_tasks': tasks_cfg})
logic.module_state.activate()
LOGIC_THREAD = QtCore.QThread()
logic.moveToThread(LOGIC_THREAD)
LOGIC_THREAD.start()
gui = TaskRunnerGui(qudi_main_weakref=weakref.ref(MAIN), name='task_runner_gui', config={})
MAIN.module_manager.gui = gui
for conn in gui._meta['connectors'].values():
    conn.connect(logic)
gui.module_state.activate()
gui._mw.resize(900, 400)
EMITS = []
logic.sigTaskProgress.connect(lambda n, s, t: EMITS.append((monotonic(), n, f'{s} - {t}')), QtCore.Qt.DirectConnection)
FINISHED = []
logic.sigTaskFinished.connect(lambda n, r, ok: FINISHED.append((n, ok)), QtCore.Qt.DirectConnection)


def run(name, start_roi='', interrupt_when=None, timeout=120):
    """Type start_roi, click Run; sample the progress line every 20 ms until the task ends."""
    widget = gui._mw.task_widgets[name]
    widget.parameter_widgets['start_roi'][1].setText(start_roi)
    seen = []
    EMITS.clear()
    widget.run_interrupt_button.click()
    t0 = monotonic()
    started = interrupted = False
    while monotonic() - t0 < timeout:
        app.processEvents()
        started = started or name in logic.running_tasks
        state = (widget.progress_label.full_text(), widget.progress_label.isVisible())
        if not seen or seen[-1][1:] != state:
            seen.append((monotonic(), *state))
        if interrupt_when is not None and not interrupted and interrupt_when():
            interrupted = True
            widget.run_interrupt_button.click()
        if started and name not in logic.running_tasks:
            break
        sleep(0.02)
    for _ in range(30):
        app.processEvents()
        sleep(0.01)
    seen.append((monotonic(), widget.progress_label.full_text(), widget.progress_label.isVisible()))
    return t0, seen, [t for _, n, t in EMITS if n == name]


DUMMY = 'roi_multicolour_scan_dummy'

# (1) dummy, start_roi ''
t0, seen, emits = run(DUMMY)
shown = [x for _, x, v in seen if v]
exp = [f'0/{N} - Preparing imaging'] + [f'{j}/{N} - ROI {j}/{N} - {n}' for j, n in enumerate(NAMES, 1)] + [f'{N}/{N} - Done']
print('    emitted:', emits)
check(f"(dummy, start_roi '') progress: 'Preparing imaging', 'ROI j/{N} - <name>' for each ROI, 'Done'", emits == exp, emits)
check(f"(dummy, start_roi '') the window label showed 'ROI j/{N} - ROI_xxx' for every ROI",
      all(f'{j}/{N} - ROI {j}/{N} - {n}' in shown for j, n in enumerate(NAMES, 1)), shown)
check("(dummy, start_roi '') label cleared and hidden at the end; task succeeded",
      seen[-1][1:] == ('', False) and FINISHED[-1] == (DUMMY, True), (seen[-2:], FINISHED[-1:]))
logs = [m for t, lvl, m in LOGS if t >= t0]
check(f'(dummy) log: "Moving to <roi>" once per ROI, no duplicate ROI / Done line; "0/{N} - Preparing imaging" '
      'logged; "All ROIs done." kept',
      [m for m in logs if m.startswith('Moving to')] == [f'Moving to {n}' for n in NAMES]
      and not any(re.match(r'\d/\d - ROI', m) or m.endswith('- Done') for m in logs)
      and f'0/{N} - Preparing imaging' in logs and 'All ROIs done.' in logs, logs)

# (2) dummy, start_roi = second ROI
t0, seen, emits = run(DUMMY, start_roi=NAMES[1])
M = N - 1
exp = [f'0/{M} - Preparing imaging'] + [f'{j}/{M} - ROI {j}/{M} - {n}' for j, n in enumerate(NAMES[1:], 1)] + [f'{M}/{M} - Done']
check(f"(dummy, start_roi {NAMES[1]!r}) progress counts the ROIs of this run: "
      + ', '.join(f"'ROI {j}/{M} - {n}'" for j, n in enumerate(NAMES[1:], 1)), emits == exp and seen[-1][1:] == ('', False), emits)

# (3) interrupt during the 2nd ROI
t0, seen, emits = run(DUMMY, interrupt_when=lambda: any(e[2].startswith(f'2/{N} - ROI') for e in EMITS))
check(f'(dummy, interrupt during ROI 2/{N}) label showed ROI 2/{N}, cleared and hidden after the interrupt; task not successful',
      any(x.startswith(f'2/{N} - ROI 2/{N}') for _, x, v in seen if v) and seen[-1][1:] == ('', False)
      and FINISHED[-1] == (DUMMY, False), (seen[-3:], FINISHED[-1:]))

# (4) error: the stage refuses the move to the 2nd ROI
orig = roi.go_to_roi_xy
moves = []


def failing_move(*a, **k):
    moves.append(roi.active_roi)
    if len(moves) == 2:
        raise RuntimeError('stage move refused (test)')
    return orig(*a, **k)


roi.go_to_roi_xy = failing_move
t0, seen, emits = run(DUMMY)
roi.go_to_roi_xy = orig
check(f'(dummy, error at the move to ROI 2/{N}) label showed ROI 2/{N}, cleared and hidden after the error; task failed',
      any(x.startswith(f'2/{N} - ROI 2/{N}') for _, x, v in seen if v) and seen[-1][1:] == ('', False)
      and FINISHED[-1] == (DUMMY, False)
      and any('stage move refused (test)' in m or 'Exception during main run method' in m
              for t, lvl, m in LOGS if t >= t0), (seen[-3:], FINISHED[-1:]))

# (5) SD with the fake TriggerLogic
TRIGGER.sent.clear()
t0, seen, emits = run('roi_scan_sd')
exp = [f'0/{N} - Preparing imaging', f'0/{N} - Waiting for ZEN "ready"'] + \
      [f'{j}/{N} - ROI {j}/{N} - {n}' for j, n in enumerate(NAMES, 1)] + [f'{N}/{N} - Done']
print('    SD emitted:', emits)
check(f'(SD) progress: Preparing imaging, Waiting for ZEN "ready", ROI j/{N} - <name>, Done; label cleared at the end',
      emits == exp and seen[-1][1:] == ('', False) and FINISHED[-1] == ('roi_scan_sd', True)
      and TRIGGER.sent.count('trigger_ZEN_start_block') == 2 * N, (emits, seen[-2:]))
logs = [m for t, lvl, m in LOGS if t >= t0]
zen_line = f'ZEN: set the number of acquisition loops to {N}'
i_zen = logs.index(zen_line) if zen_line in logs else -1
i_wait = next((k for k, m in enumerate(logs) if m.startswith('Waiting for ZEN to signal it is ready')), -1)
check('(SD) logs: ZEN loop count, then the mixin\'s "Waiting for ZEN..." line once (no duplicate progress line)',
      0 <= i_zen < i_wait and sum(1 for m in logs if 'Waiting for ZEN' in m) == 1, logs[:8])

print(f'\n{sum(ok for _, ok in results)}/{len(results)} passed', flush=True)
os._exit(0 if all(ok for _, ok in results) else 1)
