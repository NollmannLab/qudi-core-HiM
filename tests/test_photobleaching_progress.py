"""Photobleaching task progress in the Task Runner window.

Usage: QT_QPA_PLATFORM=offscreen python tests/test_photobleaching_progress.py [<repo_root> [<photobleaching_before.py>]]
(A) hardware calls: the task before and after the change, run directly with recording roi / laser
    logic stand-ins: same calls with the same arguments, same order, same illumination times.
(B) Task Runner: real TaskRunnerLogic (own thread, as a threaded qudi logic module) and
    TaskRunnerGui, the photobleaching_sd_dummy entry of dummy_config.cfg (PhotoBleachingSDTask),
    started with the Run button of its task widget: start dialog, progress line, end reminder.
The comparisons with the task before the change (A) run only when <photobleaching_before.py> is given.
Short settings: tests/_short.py (docs/TESTING.md) - 2 ROIs; illumination 1.5 s in (A), PB_S in (B).
"""
import sys, os, re, weakref, logging, importlib.util, tempfile, copy, math
from time import monotonic, sleep
from importlib.metadata import version

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _short  # noqa: E402  (short settings and shared test data, docs/TESTING.md)
repo = _short.repo_root(sys.argv)
before_path, = _short.reference_files(sys.argv, 1)
ROIS = ['ROI_001', 'ROI_002'][:_short.N_ROIS]  # ROI names of the roi_logic stand-in
N = len(ROIS)
PB_S = 3.0  # illumination time per ROI in (B): seconds-left countdown 2, 1
sys.path.insert(0, os.path.join(repo, 'src'))
from qtpy import QtCore, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
import yaml  # noqa: E402
import qudi.core  # noqa: E402
from qudi.logic.taskrunner_logic import TaskRunnerLogic  # noqa: E402
from qudi.gui.task_runner.task_runner_gui import TaskRunnerGui  # noqa: E402
from qudi.tasks.common.progress import ProgressModuleTask  # noqa: E402
from qudi.tasks import photobleaching as pb  # noqa: E402

results = []


def check(label, cond, detail=''):
    results.append((label, bool(cond)))
    print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)


print('qudi-core', version('qudi-core'))
PROBLEMS = []


class H(logging.Handler):
    def emit(self, r):
        # ignored: offscreen-plugin notice; task-thread join notice of TaskRunnerLogic (also without
        # progress, see the task-progress test)
        if r.levelno >= logging.WARNING and not any(m in r.getMessage() for m in
                                                    ('propagateSizeHints', 'wait on itself')):
            PROBLEMS.append(f'{r.name} {r.levelname}: {r.getMessage()} {r.exc_info[1] if r.exc_info else ""}')


logging.getLogger().addHandler(H())


# ------------------------------------------------------------------ roi / laser stand-ins
class Recorder:
    def __init__(self):
        self.calls = []
        self.t0 = monotonic()
        self.fail_on = None  # (method name, call number) -> raise

    def rec(self, name, *args):
        self.calls.append((monotonic() - self.t0, name, args))
        if self.fail_on and self.fail_on[0] == name and sum(c[1] == name for c in self.calls) == self.fail_on[1]:
            raise RuntimeError(f'{name} failed (test)')


class _Stand:
    def __init__(self, rec):
        self._rec = rec

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return lambda *a, **k: self._rec.rec(name, *a, *k.values())


class RoiLogic(_Stand):
    _meta = {'mro': ('RoiLogic',)}

    def stage_wait_for_idle(self):  # a stage move takes 0.3 s
        self._rec.rec('stage_wait_for_idle')
        sleep(0.3)

    def load_roi_list(self, path):
        self._rec.rec('load_roi_list', path)
        self.roi_names = list(ROIS)


class LaserControlLogic(_Stand):
    _meta = {'mro': ('LaserControlLogic',)}


TMP = tempfile.mkdtemp()
KEEP = []  # connectors hold weak references: keep the stand-ins alive


def stand_ins(rec):
    pair = (RoiLogic(rec), LaserControlLogic(rec))
    KEEP.append(pair)
    return {'roi_logic': pair[0], 'laser_logic': pair[1]}


def pb_yaml(illumination_time):
    path = os.path.join(TMP, f'pb_{illumination_time}.yaml')
    yaml.safe_dump({'roi_list_path': '/fake/rois.json', 'imaging_sequence': [[561, 50.0], [640, 80.0]],
                    'illumination_time': illumination_time}, open(path, 'w'))
    return path


# ------------------------------------------------------------------ (A) same hardware calls, order, timing
pb_before = None
if before_path is not None:
    spec = importlib.util.spec_from_file_location('pb_before', before_path)
    pb_before = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pb_before)


def direct_run(cls, path, interrupt_after=None):
    rec = Recorder()
    task_cls = type(cls.__name__ + 'UnderTest', (cls,), {'user_config_path': path})
    task = task_cls()
    task.connect_modules(stand_ins(rec))
    emits = []
    if hasattr(task, 'sigProgress'):
        task.sigProgress.connect(lambda s, t: emits.append((monotonic() - rec.t0, s, t)), QtCore.Qt.DirectConnection)
    if interrupt_after is not None:
        import threading
        threading.Timer(interrupt_after, task.interrupt).start()
    result = task()
    return rec, result, task.success, emits


def widths(rec):
    en = [t for t, n, _ in rec.calls if n == 'set_laser_enabled']
    dis = [t for t, n, _ in rec.calls if n == 'set_laser_disabled'][1:1 + len(en)]
    return [round(d - e, 2) for e, d in zip(en, dis)]


path_a = pb_yaml(1.5)
for label, kwargs in (('normal run', {}), ('interrupt during ROI 2', {'interrupt_after': 2.3})):
    new_rec, new_res, new_ok, emits = direct_run(pb.PhotoBleachingSDTask, path_a, **kwargs)
    if pb_before is None:
        _short.skipped(f'(A {label}) same hardware calls, arguments, order and illumination times as before')
    else:
        old_rec, old_res, old_ok, _ = direct_run(pb_before.PhotoBleachingSDTask, path_a, **kwargs)
        old_calls = [(n, a) for _, n, a in old_rec.calls]
        new_calls = [(n, a) for _, n, a in new_rec.calls]
        check(f'(A {label}) same hardware calls, arguments and order as before ({len(new_calls)} calls), same result',
              old_calls == new_calls and old_res == new_res and old_ok == new_ok, (old_calls, new_calls))
        check(f'(A {label}) same illumination times: before {widths(old_rec)}, after {widths(new_rec)}',
              len(widths(old_rec)) == len(widths(new_rec))
              and all(abs(a - b) < 0.05 for a, b in zip(widths(old_rec), widths(new_rec))))
    if label == 'normal run':
        texts = [f'{s} - {t}' for _, s, t in emits]
        print('    progress:', texts)
        exp = []
        for i, roi_name in enumerate(ROIS, 1):
            exp += [f'{i}/{N} - ROI {i}/{N} - moving to {roi_name}', f'{i}/{N} - ROI {i}/{N} - illuminating 1.5 s']
        check('(A) progress: moving / illuminating per ROI, seconds left, Done',
              [x for x in texts if 'left' not in x] == exp + [f'{N}/{N} - Done']
              and [x for x in texts if 'left' in x] == [f'{i}/{N} - ROI {i}/{N} - 1 s left' for i in range(1, N + 1)],
              texts)

# log lines: the existing ones kept, one line per move
rec = Recorder()
task = type('T', (pb.PhotoBleachingSDTask,), {'user_config_path': path_a})()
task.connect_modules(stand_ins(rec))
lines = []


class L(logging.Handler):
    def emit(self, r):
        lines.append(r.getMessage())


task.log.addHandler(L())
task.log.setLevel(logging.INFO)
task()
check('(A) log: "Moving to ROI_00i" once per ROI (no duplicate), illumination and Done lines added',
      [m for m in lines if 'ROI_00' in m] == [f'Moving to {r}' for r in ROIS]
      and f'1/{N} - ROI 1/{N} - illuminating 1.5 s' in lines and f'{N}/{N} - Done' in lines
      and not any('moving to' in m for m in lines), lines)
check('_interruptible_wait without on_wait still works (0.3 s)',
      (lambda t0: (task._interruptible_wait(0.3), 0.3 <= monotonic() - t0 < 0.45)[1])(monotonic()))
check('PhotoBleachingBase derives from ProgressModuleTask; subclasses unchanged',
      pb.PhotoBleachingBase.__bases__ == (ProgressModuleTask,)
      and pb.PhotoBleachingSDTask.__bases__ == (pb.PhotoBleachingBase,))
if pb_before is None:
    _short.skipped('start / end warnings identical to before')
else:
    check('start / end warnings identical to before',
          pb.PhotoBleachingSDTask.start_warning == pb_before.PhotoBleachingSDTask.start_warning
          and pb.PhotoBleachingSDTask.end_warning == pb_before.PhotoBleachingSDTask.end_warning)

# ------------------------------------------------------------------ (B) Task Runner window
DIALOGS = []


def fake_exec(box):
    DIALOGS.append(('modal', box.windowTitle(), box.text()))
    [b for b in box.buttons() if b.text().startswith('Done')][0].click()
    return 0


_orig_show = QtWidgets.QMessageBox.show


def fake_show(box):
    DIALOGS.append(('nonmodal', box.windowTitle(), box.text()))
    _orig_show(box)


QtWidgets.QMessageBox.exec = fake_exec
QtWidgets.QMessageBox.show = fake_show


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
        self.threads = []  # keep the QThreads alive

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
REC = Recorder()
MAIN.module_manager['roi_logic'] = Managed(RoiLogic(REC))
MAIN.module_manager['laser_control_logic'] = Managed(LaserControlLogic(REC))
CFG = yaml.safe_load(open(os.path.join(repo, 'custom_config/dummy_config.cfg'), encoding='utf-8'))
tasks_cfg = {'photobleaching_sd_dummy': copy.deepcopy(CFG['logic']['task_runner']['options']['module_tasks']
                                                      ['photobleaching_sd_dummy'])}
check('dummy_config entry photobleaching_sd_dummy is PhotoBleachingSDTask',
      tasks_cfg['photobleaching_sd_dummy']['module.Class'] == 'qudi.tasks.photobleaching.PhotoBleachingSDTask')
tasks_cfg['photobleaching_sd_dummy']['options']['user_config_path'] = pb_yaml(PB_S)

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
NAME = 'photobleaching_sd_dummy'
EMITS = []
logic.sigTaskProgress.connect(lambda n, s, t: EMITS.append((monotonic(), s, t)), QtCore.Qt.DirectConnection)
FINISHED = []
logic.sigTaskFinished.connect(lambda n, r, ok: FINISHED.append(ok), QtCore.Qt.DirectConnection)


def label_state():
    lbl = gui._mw.task_widgets[NAME].progress_label
    return lbl.full_text(), lbl.isVisible()


def run(interrupt_when=None, timeout=60):
    """Click Run in the task widget; sample the progress line every 20 ms until the task ends."""
    seen = []
    DIALOGS.clear()
    EMITS.clear()
    PROBLEMS.clear()
    gui._mw.task_widgets[NAME].run_interrupt_button.click()
    t0 = monotonic()
    started = interrupted = False
    while monotonic() - t0 < timeout:
        app.processEvents()
        started = started or NAME in logic.running_tasks
        state = label_state()
        if not seen or seen[-1][1:] != state:
            seen.append((monotonic(), *state))
        if interrupt_when is not None and not interrupted and interrupt_when():
            interrupted = True
            gui._mw.task_widgets[NAME].run_interrupt_button.click()
        if started and NAME not in logic.running_tasks:
            break
        sleep(0.02)
    for _ in range(30):
        app.processEvents()
        sleep(0.01)
    seen.append((monotonic(), *label_state()))
    return seen


START = pb.PhotoBleachingSDTask.start_warning
END = pb.PhotoBleachingSDTask.end_warning

# normal run: N ROIs x PB_S
seen = run()
shown = [s[1] for s in seen if s[2]]
left = [(t, x) for t, x, v in seen if v and x.endswith('s left')]
print('    label:', shown[:8], '...', shown[-3:])
check('(B run) start dialog (modal) before the start, end reminder (non-modal) after - as before',
      [d[0] for d in DIALOGS] == ['modal', 'nonmodal'] and DIALOGS[0][2] == START and DIALOGS[1][2] == END, DIALOGS)
check('(B run) label shows moving / illuminating for each ROI',
      all(f'{i}/{N} - ROI {i}/{N} - moving to {r}' in shown and f'{i}/{N} - ROI {i}/{N} - illuminating {PB_S:g} s' in shown
          for i, r in enumerate(ROIS, 1)), shown)
for i in range(1, N + 1):
    vals = [int(re.search(r'- (\d+) s left', x).group(1)) for _, x in left if x.startswith(f'{i}/{N} ')]
    check(f'(B run) ROI {i}: "ROI {i}/{N} - k s left" counts down by one: {vals}',
          vals == list(range(int(PB_S) - 1, 0, -1)), vals)
gaps = [EMITS[k][0] - EMITS[k - 1][0] for k in range(1, len(EMITS)) if EMITS[k][2].endswith('s left')]
check(f'(B run) seconds-left updates once per second (gaps {min(gaps):.2f}-{max(gaps):.2f} s)',
      min(gaps) >= 0.98 and max(gaps) < 1.2, gaps)
check('(B run) Done emitted; label cleared and hidden at the end', EMITS[-1][1:] == (f'{N}/{N}', 'Done')
      and seen[-1][1:] == ('', False), (EMITS[-1], seen[-2:]))
check('(B run) no warning / error logged', not PROBLEMS, PROBLEMS)

# interrupt with the stop button during ROI 2
seen = run(interrupt_when=lambda: any(e[1] == f'2/{N}' and e[2].endswith('s left') for e in EMITS))
check('(B interrupt) label showed ROI 2, cleared and hidden after the interrupt; dialogs as before',
      any(s[1].startswith(f'2/{N}') for s in seen) and seen[-1][1:] == ('', False)
      and [d[0] for d in DIALOGS] == ['modal', 'nonmodal'], (seen[-3:], DIALOGS))

# error: lasers fail when switched on for ROI 2
REC.fail_on = ('set_laser_enabled', 2)
REC.calls.clear()
seen = run()
REC.fail_on = None
check('(B error) task failed, label showed ROI 2, cleared and hidden after the error; end reminder shown',
      FINISHED[-1] is False and any(s[1].startswith(f'2/{N}') for s in seen)
      and seen[-1][1:] == ('', False) and [d[0] for d in DIALOGS] == ['modal', 'nonmodal'],
      (seen[-3:], PROBLEMS[-1:], DIALOGS))

print(f'\n{sum(ok for _, ok in results)}/{len(results)} passed', flush=True)
os._exit(0 if all(ok for _, ok in results) else 1)
