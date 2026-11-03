"""ROI scan on the spinning disk: ZEN settings box before the scan (tasks/common/popups.py ask_confirmation,
gui/task_runner/dialogs.py build_confirmation_box), and the other users of the shared dialogs.

Usage: QT_QPA_PLATFORM=offscreen python tests/test_roi_scan_zen_checklist.py [<repo_root>]
(1)-(4) RoiScanSDTask with recording roi / laser stand-ins and a fake TriggerLogic (ZEN ready / done
answered at once); the task runs in its own thread, the GUI thread answers the box (or not).
(5) fluidics dummy task (stand-ins) without needle position: warning box (show_warning_popup).
(6) photobleaching start warning in the Task Runner widget (build_confirmation_box).
Short settings and test data: tests/_short.py (docs/TESTING.md).
"""
import sys, os, logging, tempfile, threading
from time import monotonic, sleep
from importlib.metadata import version

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _short  # noqa: E402  (short settings and shared test data, docs/TESTING.md)
repo = _short.repo_root(sys.argv)
sys.path.insert(0, os.path.join(repo, 'src'))
from qtpy import QtCore, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
import yaml  # noqa: E402
from qudi.tasks import roi_multicolour_scan as rs  # noqa: E402
from qudi.tasks.common import popups  # noqa: E402

results = []


def check(label, cond, detail=''):
    results.append((label, bool(cond)))
    print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)


print('qudi-core', version('qudi-core'))
TMP = tempfile.mkdtemp()
LOGS = []


class H(logging.Handler):
    def emit(self, r):
        LOGS.append((r.levelno, r.getMessage()))


# ------------------------------------------------------------------ stand-ins
class Rec:
    def __init__(self):
        self.calls = []

    def rec(self, name, *args):
        self.calls.append((name, args))


class _Stand:
    def __init__(self, rec, roi_names):
        self._rec = rec
        self._names = roi_names

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return lambda *a, **k: self._rec.rec(name, *a, *k.values()) or True


class RoiLogic(_Stand):
    _meta = {'mro': ('RoiLogic',)}

    def load_roi_list(self, path):
        self._rec.rec('load_roi_list', path)
        self.roi_names = list(self._names)

    def get_stage_velocity(self, axes):
        self._rec.rec('get_stage_velocity', axes)
        return {a: 6000.0 for a in axes}

    def get_roi_position(self, name):
        self._rec.rec('get_roi_position', name)
        return (float(name[-3:]) * 10, 0.0, 0.0)


class LaserControlLogic(_Stand):
    _meta = {'mro': ('LaserControlLogic',)}


class TriggerLogic(_Stand):
    _meta = {'mro': ('TriggerLogic',)}

    def is_triggered(self, name):
        self._rec.rec('is_triggered', name)
        return True


KEEP = []
ROIS_2 = _short.roi_names()                          # shared 2-ROI list names
ROIS_20 = [f'ROI_{k:03d}' for k in range(1, 21)]     # 20 ROIs for the start_roi case


def sd_yaml(name, sequence):
    path = os.path.join(TMP, f'{name}.yaml')
    yaml.safe_dump({'sample_name': 'SDsample', 'save_path': os.path.join(TMP, f'data_{name}'),
                    'roi_list_path': '/fake/rois.json', 'imaging_sequence': sequence}, open(path, 'w'))
    return path


SEQ = [[488, 50.0], [561, 80.0]]


def sd_task(module, rec, path, roi_names):
    stands = {'roi_logic': RoiLogic(rec, roi_names), 'laser_logic': LaserControlLogic(rec, roi_names),
              'trigger_logic': TriggerLogic(rec, roi_names)}
    KEEP.append(stands)
    task = type('RoiScanSDTaskUnderTest', (module.RoiScanSDTask,), {'user_config_path': path})()
    task.connect_modules(stands)
    if not any(isinstance(h, H) for h in task.log.handlers):
        task.log.addHandler(H())
    return task


def boxes():
    return [w for w in app.topLevelWidgets() if isinstance(w, QtWidgets.QMessageBox) and w.isVisible()
            and w.windowTitle() == 'ZEN settings']


def run(task, kwargs, answer=None, interrupt_when_box=False, timeout=60):
    """Run the task in its own thread; the GUI thread answers the box with the button `answer`
    (None: no answer) or interrupts the task while the box is open. Returns (result, error, box info)."""
    out = {}

    def target():
        try:
            out['result'] = task(**kwargs)
        except Exception as err:
            out['error'] = err
    LOGS.clear()
    seen = {'texts': [], 'buttons': None, 'icon': None, 'modal': None}
    th = threading.Thread(target=target, daemon=True, name='task')
    th.start()
    t0 = monotonic()
    interrupted = False
    while th.is_alive() and monotonic() - t0 < timeout:
        app.processEvents()
        for box in boxes():
            if box.text() not in seen['texts']:
                seen['texts'].append(box.text())
                seen['buttons'] = [b.text() for b in box.buttons()]
                seen['icon'] = box.icon()
                seen['modal'] = box.windowModality()
            if interrupt_when_box and not interrupted:
                interrupted = True
                task.interrupt()
            elif answer is not None:
                [b for b in box.buttons() if b.text() == answer][0].click()
        sleep(0.02)
    th.join(1)
    for _ in range(20):
        app.processEvents()
        sleep(0.01)
    return out.get('result'), out.get('error'), seen


HARDWARE = ('send_trigger', 'is_triggered', 'set_laser_disabled', 'set_laser_enabled', 'set_external_trigger',
            'set_laser_line_intensity', 'disable_tracking_mode', 'disable_roi_actions', 'set_stage_velocity',
            'set_active_roi', 'go_to_roi_xy', 'stage_wait_for_idle', 'enable_tracking_mode', 'enable_roi_actions')
EXPECTED_TEXT = ('In block 7, check the following info:\n'
                 '1- the following channels should be selected: 488 nm, 561 nm\n'
                 '2- the number of loops for blocks 4>9 should be 2')

# ------------------------------------------------------------------ (1) Done - continue
rec = Rec()
task = sd_task(rs, rec, sd_yaml('done', SEQ), ROIS_2)
result, err, seen = run(task, {'start_roi': ''}, answer='Done - continue')
names = [n for n, _ in rec.calls]
msgs = [m for _, m in LOGS]
print('    box text:', repr(seen['texts'][:1]))
check('(1 Done) one modal box "ZEN settings" (warning icon, as the start warning), buttons "Done - continue" and '
      '"Cancel", text as specified',
      seen['texts'] == [EXPECTED_TEXT] and seen['buttons'] == ['Done - continue', 'Cancel']
      and seen['icon'] == QtWidgets.QMessageBox.Warning and seen['modal'] == QtCore.Qt.ApplicationModal, seen)
check('(1 Done) scan runs: both ROIs imaged (2 ZEN blocks each), task successful, box closed',
      err is None and task.success and result.get('imaged_rois') == ROIS_2
      and names.count('send_trigger') == 2 * len(ROIS_2) and not boxes(), (err, result))
i_box_chan = msgs.index('ZEN: select the channels 488 nm, 561 nm') if 'ZEN: select the channels 488 nm, 561 nm' in msgs else -1
i_loops = msgs.index('ZEN: set the number of acquisition loops to 2') if 'ZEN: set the number of acquisition loops to 2' in msgs else -1
i_wait = next((k for k, m in enumerate(msgs) if m.startswith('Waiting for ZEN to signal it is ready')), -1)
check('(1 Done) log: channels and acquisition loops (each once), before the wait for ZEN "ready"',
      0 <= i_box_chan < i_wait and 0 <= i_loops < i_wait
      and sum(m.startswith('ZEN: set the number of acquisition loops') for m in msgs) == 1, msgs[:10])
first_hw = next((k for k, (n, _) in enumerate(rec.calls) if n in HARDWARE), None)
check('(1 Done) no hardware call before the box was answered: first call after load_roi_list is a hardware call '
      'made after the answer (set_laser_disabled)', rec.calls[0][0] == 'load_roi_list'
      and rec.calls[first_hw][0] == 'set_laser_disabled', rec.calls[:4])


# ------------------------------------------------------------------ (2) Cancel
rec = Rec()
task = sd_task(rs, rec, sd_yaml('cancel', SEQ), ROIS_2)
result, err, seen = run(task, {'start_roi': ''}, answer='Cancel')
msgs = [m for _, m in LOGS]
check("(2 Cancel) task ends as finished: result {'cancelled': True, 'imaged_rois': []}, success, "
      "'ROI scan cancelled by the user' logged",
      err is None and task.success and result == {'cancelled': True, 'imaged_rois': []}
      and 'ROI scan cancelled by the user' in msgs, (err, result))
check('(2 Cancel) no trigger / stage / laser call, ROI GUI not locked (only load_roi_list); cleanup restores nothing; '
      'no data folder', [n for n, _ in rec.calls] == ['load_roi_list']
      and 'cleanup: no hardware was touched, nothing to restore' in msgs and not os.path.exists(os.path.join(TMP, 'data_cancel'))
      and not boxes(), (rec.calls, msgs[-3:]))

# ------------------------------------------------------------------ (3) interrupt while the box is open
rec = Rec()
task = sd_task(rs, rec, sd_yaml('interrupt', SEQ), ROIS_2)
t0 = monotonic()
result, err, seen = run(task, {'start_roi': ''}, interrupt_when_box=True)
elapsed = monotonic() - t0
check('(3 interrupt) task stops (not successful), box closed, no hardware call, cleanup restores nothing',
      not task.success and seen['texts'] and not boxes() and [n for n, _ in rec.calls] == ['load_roi_list']
      and any('nothing to restore' in m for _, m in LOGS), (task.success, err, rec.calls, boxes()))

# ------------------------------------------------------------------ (4) start_roi ROI_005 on a 20-ROI list; sequence order
rec = Rec()
task = sd_task(rs, rec, sd_yaml('start5', [[640, 30.0], [488, 50.0], [561, 80.0]]), ROIS_20)
answer = _short.AutoAnswer('ZEN settings', 'Cancel')
result, err, seen = run(task, {'start_roi': 'ROI_005'})
answer.stop()
text = answer.texts[0] if answer.texts else ''
print('    box text:', repr(text))
check("(4 start_roi 'ROI_005', 20 ROIs) text says 16 loops", text.endswith('the number of loops for blocks 4>9 should be 16'),
      text)
check('(4 imaging sequence 640, 488, 561) channels listed in the imaging-sequence order',
      '1- the following channels should be selected: 640 nm, 488 nm, 561 nm\n' in text, text)

# ------------------------------------------------------------------ (5) fluidics: needle position missing -> warning box
from qudi.tasks import fluidics  # noqa: E402
from qudi.tasks.common.fluidics_steps import FluidicsStepsMixin  # noqa: E402


class FluidicsValveLogic(_Stand):
    _meta = {'mro': ('FluidicsValveLogic',)}


class FluidicsFlowLogic(_Stand):
    _meta = {'mro': ('FluidicsFlowLogic',)}


class FluidicsRobotLogic(_Stand):
    _meta = {'mro': ('FluidicsRobotLogic',)}
    origin = None  # needle position 1 not defined
    max_num_probes = 100


rec = Rec()
fl_stands = {'valve_logic': FluidicsValveLogic(rec, []), 'flow_logic': FluidicsFlowLogic(rec, []),
             'robot_logic': FluidicsRobotLogic(rec, [])}
KEEP.append(fl_stands)
fl_task = _short.shorten(fluidics.FluidicsDummyTask())
fl_task.user_config_path = _short.experiment(TMP, 'fluidics_experiment.yaml', 'needle')
fl_task.connect_modules(fl_stands)
fl_task.log.addHandler(H())
warn_boxes = []
fl_result, fl_err, _ = run(fl_task, {})
for _ in range(20):
    app.processEvents()
    sleep(0.01)
warn_boxes = [w for w in app.topLevelWidgets() if isinstance(w, QtWidgets.QMessageBox) and w.isVisible()
              and w.windowTitle() == 'Needle position not defined']
check('(5 fluidics, needle position missing) the non-modal warning box still appears with the message; task '
      'aborted before any hardware call',
      fl_err is None and fl_result == {'aborted': 'needle position not initialised', 'steps_done': 0}
      and len(warn_boxes) == 1 and warn_boxes[0].text() == FluidicsStepsMixin._NEEDLE_POSITION_MESSAGE
      and not warn_boxes[0].isModal() and warn_boxes[0].icon() == QtWidgets.QMessageBox.Warning and rec.calls == [],
      (fl_err, fl_result, [b.text() for b in warn_boxes], rec.calls))
for box in warn_boxes:
    box.close()

# ------------------------------------------------------------------ (6) photobleaching start warning, Task Runner widget
from qudi.tasks import photobleaching  # noqa: E402
from qudi.gui.task_runner.taskwidget import TaskWidget  # noqa: E402

shown = []


def answer_with(button_text):
    def fake_exec(box):
        shown.append({'title': box.windowTitle(), 'text': box.text(), 'icon': box.icon(),
                      'buttons': [b.text() for b in box.buttons()], 'default': box.defaultButton().text(),
                      'escape': box.escapeButton().text(), 'modality': box.windowModality()})
        [b for b in box.buttons() if b.text() == button_text][0].click()
        return 0
    return fake_exec


orig_exec = QtWidgets.QMessageBox.exec
widget = TaskWidget(task_type=photobleaching.PhotoBleachingSDTask, task_name='photobleaching_sd')
starts = []
widget.sigStartTask.connect(lambda params: starts.append(params))
try:
    QtWidgets.QMessageBox.exec = answer_with('Cancel')
    widget.run_interrupt_button.click()
    app.processEvents()
    cancelled_starts = list(starts)
    QtWidgets.QMessageBox.exec = answer_with('Done — start task')
    widget.run_interrupt_button.click()
    app.processEvents()
finally:
    QtWidgets.QMessageBox.exec = orig_exec
expected = {'title': 'Before starting: photobleaching_sd', 'text': photobleaching.PhotoBleachingSDTask.start_warning,
            'icon': QtWidgets.QMessageBox.Warning, 'buttons': ['Done — start task', 'Cancel'], 'default': 'Cancel',
            'escape': 'Cancel', 'modality': QtCore.Qt.ApplicationModal}
check('(6 photobleaching) start warning as before: title "Before starting: <task>", start_warning text, warning '
      'icon, buttons "Done — start task" / Cancel, Cancel default and Escape button, application modal',
      len(shown) == 2 and shown[0] == expected and shown[1] == expected, shown[:1])
check('(6 photobleaching) Cancel prevents the start; "Done — start task" starts the task',
      cancelled_starts == [] and len(starts) == 1, (cancelled_starts, starts))

print(f'\n{sum(ok for _, ok in results)}/{len(results)} passed', flush=True)
os._exit(0 if all(ok for _, ok in results) else 1)
