"""Task Runner (logic, GUI, task widget): progress display, parameter hints, start / end warning dialogs.

Usage: QT_QPA_PLATFORM=offscreen python tests/test_task_runner.py [<repo_root> [<base_taskwidget.py> [<taskwidget_before_hints.py>]]]
<base_taskwidget.py>: taskwidget.py before the progress change (idle layout comparison);
<taskwidget_before_hints.py>: taskwidget.py before the parameter hints change (editor / size comparison).
The comparisons run only when the files are given.
Short settings and test data: tests/_short.py, tests/data/ (docs/TESTING.md).
"""
import sys, os
from importlib.metadata import version

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _short  # noqa: E402  (short settings and shared test data, docs/TESTING.md)
repo = _short.repo_root(sys.argv)
REF_BASE_TASKWIDGET, REF_TASKWIDGET_BEFORE_HINTS = _short.reference_files(sys.argv, 2)
sys.path.insert(0, os.path.join(repo, 'src'))
from qtpy import QtCore, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
print('qudi-core', version('qudi-core'))
KEEP_ALIVE = []  # objects of each section (Qt threads must not be destroyed while running)


# --- progress display ---
def _section_progress():
    """Task progress in the Task Runner window: TaskRunnerLogic + TaskRunnerGui + fluidics dummy task.
    
    Real modules from dummy_config.cfg for the fluidics (valve, flow, robot, fluidics GUI), real
    TaskRunnerLogic and TaskRunnerGui, tasks run in their own QThread (fake thread manager). The
    photobleaching SD dummy task runs with recording roi / laser logic stand-ins.
    <base_taskwidget.py>: taskwidget.py before the change, to compare the idle layout (comparison only when given).
    Short settings and test data: tests/_short.py, tests/data/fluidics_injections.yml (docs/TESTING.md); the
    progress interval of the tasks is set to PROGRESS_S in the task options of this test."""
    import sys, os, re, weakref, logging, importlib, importlib.util, tempfile, copy
    from time import monotonic, sleep
    from importlib.metadata import version

    base_taskwidget = REF_BASE_TASKWIDGET
    PROGRESS_S = 0.2  # progress_interval_s of the tasks (task options of this test)
    from qtpy import QtCore, QtWidgets  # noqa: E402

    QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: QtWidgets.QMessageBox.Ok)
    import yaml  # noqa: E402
    import numpy as np  # noqa: E402
    import qudi.core  # noqa: E402
    from qudi.core.connector import Connector  # noqa: E402
    from qudi.logic.taskrunner_logic import TaskRunnerLogic  # noqa: E402
    from qudi.gui.task_runner.task_runner_gui import TaskRunnerGui  # noqa: E402
    from qudi.gui.task_runner.taskwidget import TaskWidget  # noqa: E402
    from qudi.tasks.common.progress import ProgressModuleTask  # noqa: E402
    from qudi.tasks import fluidics, photobleaching  # noqa: E402

    np.random.seed(0)
    results = []


    def check(label, cond, detail=''):
        results.append((label, bool(cond)))
        print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)


    PROBLEMS = []


    class H(logging.Handler):
        def emit(self, r):
            if r.levelno >= logging.WARNING:
                PROBLEMS.append(f'{r.name} {r.levelname}: {r.getMessage()} {r.exc_info[1] if r.exc_info else ""}')


    logging.getLogger().addHandler(H())
    QT_MESSAGES = []
    # ignored: offscreen-plugin notice, and the task-thread join notice of TaskRunnerLogic (counted
    # separately in WAIT_SELF: it also appears for tasks without progress, see the photobleaching run)
    WAIT_SELF = []
    QtCore.qInstallMessageHandler(lambda mode, ctx, msg: None if 'propagateSizeHints' in msg else
                                  WAIT_SELF.append(msg) if 'wait on itself' in msg else QT_MESSAGES.append(msg))


    # ------------------------------------------------------------------ qudi main stand-in
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


    flow = build('fluidics_flow_logic')
    build('fluidics_gui')
    valve, robot = MODULES['fluidics_valve_logic'], MODULES['pipetting_robot_logic']
    valve_hw = MODULES['dummy_valve']
    robot.set_origin((0.0, 0.0, 1000.0))
    for name in ('fluidics_valve_logic', 'fluidics_flow_logic', 'pipetting_robot_logic'):
        MAIN.module_manager[name] = Managed(MODULES[name])


    class _Stand:
        def __init__(self, calls):
            self._calls = calls

        def __getattr__(self, name):
            if name.startswith('_'):
                raise AttributeError(name)
            return lambda *a, **k: self._calls.append(name)


    class RoiLogic(_Stand):
        _meta = {'mro': ('RoiLogic',)}
        roi_names = ['ROI_001', 'ROI_002']


    class LaserControlLogic(_Stand):
        _meta = {'mro': ('LaserControlLogic',)}


    PB_CALLS = []
    MAIN.module_manager['roi_logic'] = Managed(RoiLogic(PB_CALLS))
    MAIN.module_manager['laser_control_logic'] = Managed(LaserControlLogic(PB_CALLS))

    # ------------------------------------------------------------------ files
    TMP = tempfile.mkdtemp()
    # incubation long enough for the live countdown checked below
    example = _short.with_incubation(_short.load(_short.FLUIDICS_INJECTIONS), _short.COUNTDOWN_INCUBATION_S)
    inj = os.path.join(TMP, 'injections.yml')
    yaml.safe_dump(example, open(inj, 'w'))
    exp = os.path.join(TMP, 'experiment.yaml')
    yaml.safe_dump({'injections_path': inj}, open(exp, 'w'))
    pb_cfg = os.path.join(TMP, 'pb.yaml')
    yaml.safe_dump({'roi_list_path': '/fake/rois.json', 'imaging_sequence': [[561, 50.0]],
                    'illumination_time': 0.3}, open(pb_cfg, 'w'))
    tasks_cfg = copy.deepcopy(CFG['logic']['task_runner']['options']['module_tasks'])
    tasks_cfg['fluidics_dummy']['options']['user_config_path'] = exp
    tasks_cfg['fluidics_dummy']['options']['progress_interval_s'] = PROGRESS_S
    tasks_cfg['fluidics_dummy']['options']['volume_poll_interval_s'] = _short.TASK_ATTRIBUTES['volume_poll_interval_s']
    tasks_cfg['photobleaching_sd_dummy']['options']['user_config_path'] = pb_cfg
    tasks_cfg.pop('photobleaching_ramm_dummy', None)  # entry no longer in dummy_config.cfg

    # ------------------------------------------------------------------ task runner logic + GUI
    logic = TaskRunnerLogic(qudi_main_weakref=weakref.ref(MAIN), name='task_runner',
                            config={'module_tasks': tasks_cfg})
    logic.module_state.activate()
    # as in qudi (threaded logic module): the task runner logic lives in its own thread. With PySide6 the
    # task's run() executes in the thread that connected thread.started (the logic thread), so the main
    # thread (GUI, fluidics logic) keeps processing events while a task runs.
    LOGIC_THREAD = QtCore.QThread()
    LOGIC_THREAD.setObjectName('task_runner')
    logic.moveToThread(LOGIC_THREAD)
    LOGIC_THREAD.start()
    gui = TaskRunnerGui(qudi_main_weakref=weakref.ref(MAIN), name='task_runner_gui', config={})
    MAIN.module_manager.gui = gui
    for conn in gui._meta['connectors'].values():
        conn.connect(logic)
    gui.module_state.activate()

    EMITS = []  # (time, name, step, text) from TaskRunnerLogic.sigTaskProgress
    logic.sigTaskProgress.connect(lambda n, s, t: EMITS.append((monotonic(), n, s, t)), QtCore.Qt.DirectConnection)


    def widget(name):
        return gui._mw.task_widgets[name]


    def label_state(name):
        lbl = widget(name).progress_label
        return lbl.full_text(), lbl.isVisible()


    def run(name, interrupt_when=None, before_poll=None, timeout=240):
        """Start the task through the logic; sample the label of the window every 20 ms."""
        seen = []
        t0 = monotonic()
        logic.run_task(name, {})
        started = False
        interrupted = False
        while monotonic() - t0 < timeout:
            app.processEvents()
            if before_poll is not None:
                before_poll()
            if name in logic.running_tasks:
                started = True
            if gui._mw is not None:
                state = label_state(name)
                if not seen or seen[-1][1:] != state:
                    seen.append((monotonic(), *state))
            if interrupt_when is not None and not interrupted and interrupt_when():
                interrupted = True
                logic.interrupt_task(name)
            if started and name not in logic.running_tasks:
                break
            sleep(0.02)
        for _ in range(30):
            app.processEvents()
            sleep(0.01)
        if gui._mw is not None:
            seen.append((monotonic(), *label_state(name)))
        return t0, seen


    mw = gui._mw
    mw.resize(900, 600)
    mw.show()
    app.processEvents()

    # ------------------------------------------------------------------ (0) idle layout unchanged
    if base_taskwidget is None:
        _short.skipped('(idle) widget size hints identical to before the change')
        for name, cls in (('fluidics_dummy', fluidics.FluidicsDummyTask),
                          ('photobleaching_sd_dummy', photobleaching.PhotoBleachingSDTask)):
            new_w = TaskWidget(task_type=cls, task_name=name)
            check(f'(idle) {name}: progress line hidden', new_w.progress_label.isHidden())
    else:
        spec = importlib.util.spec_from_file_location('base_taskwidget', base_taskwidget)
        base_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(base_mod)
        for name, cls in (('fluidics_dummy', fluidics.FluidicsDummyTask),
                          ('photobleaching_sd_dummy', photobleaching.PhotoBleachingSDTask)):
            new_w = TaskWidget(task_type=cls, task_name=name)
            old_w = base_mod.TaskWidget(task_type=cls, task_name=name)
            check(f'(idle) {name}: widget size hint identical to before the change '
                  f'({new_w.sizeHint().height()} px high), progress line hidden',
                  new_w.sizeHint() == old_w.sizeHint() and new_w.progress_label.isHidden(),
                  (new_w.sizeHint(), old_w.sizeHint()))
    groupbox_h = {n: w.parent().height() for n, w in mw.task_widgets.items()}
    check('(idle) progress lines hidden in the window', all(not label_state(n)[1] for n in mw.task_widgets))
    check('ProgressModuleTask: FluidicsTaskBase bases (FluidicsStepsMixin first); photobleaching also a ProgressModuleTask',
          fluidics.FluidicsTaskBase.__bases__[0].__name__ == 'FluidicsStepsMixin'
          and issubclass(fluidics.FluidicsDummyTask, ProgressModuleTask)
          and issubclass(photobleaching.PhotoBleachingSDTask, ProgressModuleTask))

    # ------------------------------------------------------------------ (1) normal fluidics run
    EMITS.clear()
    PROBLEMS.clear()
    max_h = {'v': 0}


    def track_height():
        if gui._mw is not None:
            max_h['v'] = max(max_h['v'], widget('fluidics_dummy').parent().height())


    t0, seen = run('fluidics_dummy', before_poll=track_height)
    texts = [f'{s} - {t}' for _, n, s, t in EMITS]
    print('    emitted:', texts[:6], '...', texts[-3:])
    shown = [s[1] for s in seen if s[2]]
    check('(run) step lines emitted in order: needle 0/5, steps 1..5, Done 5/5',
          [x for x in texts if not re.search(r'µl$|left$', x)] ==
          ['0/5 - Moving the needle to tube 1', '1/5 - Injecting SSC', '2/5 - Injecting Probe',
           f'3/5 - Incubating {_short.COUNTDOWN_INCUBATION_S} s', '4/5 - Injecting Probe', '4/5 - Moving the needle to tube 2',
           '5/5 - Injecting Wash buffer', '5/5 - Done'], texts)
    live_inj = [x for x in texts if x.endswith('µl')]
    live_inc = [x for x in texts if x.endswith('left')]
    check(f'(run) live injected volume, rounded to 1 µl ("2/5 - Injecting Probe - 3/{_short.INJECTION_UL} µl"), '
          f'at least one per injection',
          len(live_inj) >= 4 and all(re.fullmatch(rf'\d/5 - Injecting .+ - \d+/{_short.INJECTION_UL} µl', x) for x in live_inj)
          and {x.split(' - ')[0] for x in live_inj} == {'1/5', '2/5', '4/5', '5/5'}, live_inj)
    check('(run) live incubation countdown ("3/5 - Incubating - 0:01 left"), decreasing',
          len(live_inc) >= 2 and all(re.fullmatch(r'3/5 - Incubating - 0:\d\d left', x) for x in live_inc)
          and [int(x[-7:-5]) for x in live_inc] == sorted([int(x[-7:-5]) for x in live_inc], reverse=True), live_inc)
    gaps = [EMITS[i][0] - EMITS[i - 1][0] for i in range(1, len(EMITS)) if re.search(r'µl$|left$', EMITS[i][3])]
    check(f'(run) live updates at most one per progress interval ({PROGRESS_S:g} s; min gap {min(gaps):.2f} s)',
          min(gaps) >= PROGRESS_S - 0.02, gaps)
    check('(run) the window label showed the steps and the live values',
          '1/5 - Injecting SSC' in shown and any(x.endswith('µl') for x in shown)
          and any(x.endswith('left') for x in shown) and '0/5 - Moving the needle to tube 1' in shown, shown[:12])
    check('(run) label cleared and hidden at the end', seen[-1][1:] == ('', False), seen[-3:])
    check('(run) no warning / error logged, no Qt warning', not PROBLEMS and not QT_MESSAGES, (PROBLEMS, QT_MESSAGES))
    check('(run) group box grows by one line only while running', max_h['v'] > groupbox_h['fluidics_dummy']
          and widget('fluidics_dummy').parent().height() == groupbox_h['fluidics_dummy'],
          (groupbox_h['fluidics_dummy'], max_h['v'], widget('fluidics_dummy').parent().height()))

    # elision: long text in a narrow window
    w = widget('fluidics_dummy')
    mw.resize(300, 600)
    app.processEvents()
    w.task_progress('2/5', 'Injecting a product with a very long name indeed - 120/200 µl')
    app.processEvents()
    lbl = w.progress_label
    check('(elide) long text elided in a narrow window, full text as tooltip, single line',
          lbl.text() != lbl.full_text() and lbl.text().endswith('…') and lbl.toolTip() == lbl.full_text()
          and lbl.height() <= lbl.fontMetrics().height() + 4, (lbl.text(), lbl.height()))
    w.clear_progress()
    mw.resize(900, 600)
    app.processEvents()

    # ------------------------------------------------------------------ (2) interrupt
    EMITS.clear()
    PROBLEMS.clear()
    t0, seen = run('fluidics_dummy', interrupt_when=lambda: any(e[3].endswith('µl') and e[2] == '2/5' for e in EMITS))
    check('(interrupt) label showed the step before the interrupt, cleared and hidden after',
          any('2/5' in s[1] for s in seen) and seen[-1][1:] == ('', False), seen[-3:])

    # ------------------------------------------------------------------ (3) error (valve a refuses the probe outlet 7)
    orig = valve_hw.set_valve_position
    valve_hw.set_valve_position = lambda a, p: orig(a, 1 if (a, p) == ('a', 7) else p)
    EMITS.clear()
    t0, seen = run('fluidics_dummy')
    valve_hw.set_valve_position = orig
    check('(error) task failed, label cleared and hidden after the error',
          any('Valve a did not reach position 7' in p for p in PROBLEMS) and any('2/5' in s[1] for s in seen)
          and seen[-1][1:] == ('', False), (seen[-3:], PROBLEMS[-2:]))

    # ------------------------------------------------------------------ (4) photobleaching: progress per ROI
    PROBLEMS.clear()
    EMITS.clear()
    PB_CALLS.clear()
    h_before = widget('photobleaching_sd_dummy').parent().height()
    n_wait = len(WAIT_SELF)
    t0, seen = run('photobleaching_sd_dummy')
    pb_texts = [f'{s} - {t}' for _, n, s, t in EMITS if n == 'photobleaching_sd_dummy']
    check('(photobleaching) runs (lasers driven); progress "1/2 - ROI 1/2 - moving to ROI_001" ... "2/2 - Done" '
          'shown in the label during the run; label cleared and hidden, same height at the end',
          'set_laser_enabled' in PB_CALLS and '1/2 - ROI 1/2 - moving to ROI_001' in pb_texts
          and '2/2 - ROI 2/2 - moving to ROI_002' in pb_texts and pb_texts[-1] == '2/2 - Done'
          and any(s[2] for s in seen) and seen[-1][1:] == ('', False)
          and widget('photobleaching_sd_dummy').parent().height() == h_before,
          (PB_CALLS[:5], pb_texts, seen[-3:], PROBLEMS))
    check('(photobleaching) no warning / error', not PROBLEMS, PROBLEMS)
    print(f'    "QThread::wait: Thread tried to wait on itself": {len(WAIT_SELF) - n_wait} for the photobleaching run, '
          f'{n_wait} for the 3 fluidics runs before')

    # ------------------------------------------------------------------ (5) close / reopen the window while running
    PROBLEMS.clear()
    QT_MESSAGES.clear()
    EMITS.clear()
    state = {'closed': False, 'reopened': False, 'after': []}


    def close_reopen():
        if not state['closed'] and any(e[2] == '1/5' and e[3].endswith('µl') for e in EMITS):
            state['closed'] = True
            gui._mw.close()  # like the window close button: sigClosed -> module deactivated
            app.processEvents()
            state['closed_ok'] = gui._mw is None and gui.module_state() == 'deactivated'
            state['t_closed'] = monotonic()
        elif state['closed'] and not state['reopened'] and monotonic() - state['t_closed'] > 1.5:
            state['reopened'] = True
            gui.module_state.activate()
            state['t_reopen'] = monotonic()
        elif state['reopened'] and gui._mw is not None and len(state['after']) < 3:
            txt = label_state('fluidics_dummy')
            if txt[1] and (not state['after'] or state['after'][-1] != txt[0]):
                state['after'].append(txt[0])


    t0, seen = run('fluidics_dummy', before_poll=close_reopen)
    check('(close / reopen) window closed during the run, module deactivated, reopened',
          state.get('closed_ok') and state['reopened'] and gui._mw is not None)
    check('(close / reopen) the next update appears in the reopened window',
          len(state['after']) >= 1 and re.match(r'\d/5 - ', state['after'][0]), state['after'])
    check('(close / reopen) no error / warning, no Qt warning; label cleared at the end',
          not PROBLEMS and not QT_MESSAGES and seen[-1][1:] == ('', False), (PROBLEMS, QT_MESSAGES, seen[-2:]))
    KEEP_ALIVE.append(locals())  # modules, threads and widgets of the section live until the end
    return results

# --- parameter hints ---
def _section_hints():
    """Task Runner widget: parameter hints of a task (placeholder text and tooltip of the editor),
    typed values, tasks without hints; the comparisons with the widget before the change only when
    <taskwidget_before_hints.py> is given."""
    import os, importlib.util, tempfile
    from qtpy import QtCore, QtGui, QtWidgets
    from qudi.tasks import roi_multicolour_scan as rs

    results = []


    def check(label, cond, detail=''):
        results.append((label, bool(cond)))
        print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)

    TMP = tempfile.mkdtemp()
    tw_before_path = REF_TASKWIDGET_BEFORE_HINTS

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
    KEEP_ALIVE.append(locals())  # modules, threads and widgets of the section live until the end
    return results

# --- start / end warning dialogs ---
def _section_warning_dialogs():
    """Start warning of a task in the Task Runner widget (photobleaching), built by
    gui/task_runner/dialogs.py build_confirmation_box: title, text, icon, buttons, default / Escape button,
    modality; Cancel prevents the start."""
    from qtpy import QtCore, QtWidgets

    results = []


    def check(label, cond, detail=''):
        results.append((label, bool(cond)))
        print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)

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
    KEEP_ALIVE.append(locals())  # modules, threads and widgets of the section live until the end
    return results

SECTIONS = [
    ('progress display', _section_progress),
    ('parameter hints', _section_hints),
    ('start / end warning dialogs', _section_warning_dialogs),
]

if __name__ == '__main__':
    all_results = []
    for title, run_section in SECTIONS:
        print(f'\n# --- {title} ---', flush=True)
        all_results += run_section()
    print(f'\n{sum(ok for _, ok in all_results)}/{len(all_results)} passed', flush=True)
    os._exit(0 if all(ok for _, ok in all_results) else 1)
