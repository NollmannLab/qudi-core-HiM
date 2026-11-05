"""ROI scan task (qudi.tasks.roi_multicolour_scan): progress display, start ROI, ZEN settings pop-up of the
spinning disk, run folder on the server folder or in the local folder (also the Hi-M task).

Usage: QT_QPA_PLATFORM=offscreen python tests/test_roi_scan.py [<repo_root> [<roi_scan_with_resume.py>]]
<roi_scan_with_resume.py>: the ROI scan module before the start_roi change; the comparison "same calls as
before" of the start ROI section runs only when it is given.
Short settings and test data: tests/_short.py, tests/data/ (docs/TESTING.md).
"""
import sys, os
from importlib.metadata import version

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _short  # noqa: E402  (short settings and shared test data, docs/TESTING.md)
repo = _short.repo_root(sys.argv)
REF_ROI_SCAN_BEFORE, = _short.reference_files(sys.argv, 1)
sys.path.insert(0, os.path.join(repo, 'src'))
from qtpy import QtCore, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
print('qudi-core', version('qudi-core'))
KEEP_ALIVE = []  # objects of each section (Qt threads must not be destroyed while running)


# --- progress display ---
def _section_progress():
    """ROI scan progress in the Task Runner window.
    
    Real TaskRunnerLogic (own thread, as a threaded qudi logic module) and TaskRunnerGui, started with the
    Run button. roi_logic and laser_control_logic are the real modules of dummy_config.cfg (dummy stage);
    RoiScanDummyTask from its dummy_config entry, RoiScanSDTask with a fake TriggerLogic (ZEN answers at
    once). Short settings and test data: tests/_short.py, tests/data/ (rois_2.json, roi_scan_experiment.yaml)."""
    import sys, os, re, weakref, logging, importlib, tempfile, copy
    from time import monotonic, sleep
    from importlib.metadata import version

    from qtpy import QtCore, QtWidgets  # noqa: E402

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
            if name == 'trigger_ZEN_ready':
                ZEN.ready()  # ZEN starts the experiment: new data folder
            return True


    ZEN = _short.ZenFolders(os.path.join(TMP, 'zen'))  # zen_saving_path of the SD run


    TRIGGER = TriggerLogic()
    MAIN.module_manager.update({'roi_logic': Managed(roi), 'laser_control_logic': Managed(laser),
                                'trigger_logic': Managed(TRIGGER)})

    user_cfg = _short.experiment(TMP, 'roi_scan_experiment.yaml', 'roi_scan', save_path=os.path.join(TMP, 'data'))
    entry = copy.deepcopy(CFG['logic']['task_runner']['options']['module_tasks']['roi_multicolour_scan_dummy'])
    check('dummy_config: roi_multicolour_scan_dummy is RoiScanDummyTask',
          entry['module.Class'] == 'qudi.tasks.roi_multicolour_scan.RoiScanDummyTask')
    entry['options'] = _short.local_options(repo, entry['options'])  # metadata_template of the repository
    entry['options'].update({'user_config_path': user_cfg, 'dummy_imaging_time_s': _short.IMAGING_S})
    tasks_cfg = {'roi_multicolour_scan_dummy': entry,
                 'roi_scan_sd': {'module.Class': 'qudi.tasks.roi_multicolour_scan.RoiScanSDTask',
                                 'connect': {'roi_logic': 'roi_logic', 'laser_logic': 'laser_control_logic',
                                             'trigger_logic': 'trigger_logic'},
                                 'options': {'user_config_path': _short.experiment(
                                     TMP, 'roi_scan_experiment.yaml', 'roi_scan_sd', zen_saving_path=ZEN.root)}}}
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
    exp = [f'0/{N} - Preparing imaging'] + [f'{j}/{N} - {n}' for j, n in enumerate(NAMES, 1)] + [f'{N}/{N} - Done']
    print('    emitted:', emits)
    check(f"(dummy, start_roi '') progress: 'Preparing imaging', 'j/{N} - <name>' for each ROI, 'Done'", emits == exp, emits)
    check(f"(dummy, start_roi '') the window label showed 'j/{N} - ROI_xxx' for every ROI",
          all(f'{j}/{N} - {n}' in shown for j, n in enumerate(NAMES, 1)), shown)
    check("(dummy, start_roi '') label cleared and hidden at the end; task succeeded",
          seen[-1][1:] == ('', False) and FINISHED[-1] == (DUMMY, True), (seen[-2:], FINISHED[-1:]))
    logs = [m for t, lvl, m in LOGS if t >= t0]
    check(f'(dummy) log: "Moving to <roi>" once per ROI, no duplicate ROI / Done line; "0/{N} - Preparing imaging" '
          'logged; "All ROIs done." kept',
          [m for m in logs if m.startswith('Moving to')] == [f'Moving to {n}' for n in NAMES]
          and not any(re.fullmatch(r'\d+/\d+ - .+', m) and not m.endswith('Preparing imaging') for m in logs)
          and f'0/{N} - Preparing imaging' in logs and 'All ROIs done.' in logs, logs)

    # (2) dummy, start_roi = second ROI
    t0, seen, emits = run(DUMMY, start_roi=NAMES[1])
    M = N - 1
    exp = [f'0/{M} - Preparing imaging'] + [f'{j}/{M} - {n}' for j, n in enumerate(NAMES[1:], 1)] + [f'{M}/{M} - Done']
    check(f"(dummy, start_roi {NAMES[1]!r}) progress counts the ROIs of this run: "
          + ', '.join(f"'{j}/{M} - {n}'" for j, n in enumerate(NAMES[1:], 1)), emits == exp and seen[-1][1:] == ('', False), emits)

    # (3) interrupt during the 2nd ROI
    t0, seen, emits = run(DUMMY, interrupt_when=lambda: any(e[2] == f'2/{N} - {NAMES[1]}' for e in EMITS))
    check(f'(dummy, interrupt during ROI 2/{N}) label showed 2/{N}, cleared and hidden after the interrupt; task not successful',
          any(x == f'2/{N} - {NAMES[1]}' for _, x, v in seen if v) and seen[-1][1:] == ('', False)
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
    check(f'(dummy, error at the move to ROI 2/{N}) label showed 2/{N}, cleared and hidden after the error; task failed',
          any(x == f'2/{N} - {NAMES[1]}' for _, x, v in seen if v) and seen[-1][1:] == ('', False)
          and FINISHED[-1] == (DUMMY, False)
          and any('stage move refused (test)' in m or 'Exception during main run method' in m
                  for t, lvl, m in LOGS if t >= t0), (seen[-3:], FINISHED[-1:]))

    # (5) SD with the fake TriggerLogic
    ZEN_BOX = _short.AutoAnswer('ZEN settings')  # answers the ZEN settings box 'Done - continue'
    TRIGGER.sent.clear()
    t0, seen, emits = run('roi_scan_sd')
    exp = [f'0/{N} - Preparing imaging', f'0/{N} - Waiting for ZEN "ready"'] + \
          [f'{j}/{N} - {n}' for j, n in enumerate(NAMES, 1)] + [f'{N}/{N} - Done']
    print('    SD emitted:', emits)
    check(f'(SD) progress: Preparing imaging, Waiting for ZEN "ready", j/{N} - <name>, Done; label cleared at the end',
          emits == exp and seen[-1][1:] == ('', False) and FINISHED[-1] == ('roi_scan_sd', True)
          and TRIGGER.sent.count('trigger_ZEN_start_block') == 2 * N, (emits, seen[-2:]))
    logs = [m for t, lvl, m in LOGS if t >= t0]
    zen_line = f'ZEN: set the number of acquisition loops to {N}'
    i_zen = logs.index(zen_line) if zen_line in logs else -1
    i_wait = next((k for k, m in enumerate(logs) if m.startswith('Waiting for ZEN to signal it is ready')), -1)
    check('(SD) logs: ZEN loop count, then the mixin\'s "Waiting for ZEN..." line once (no duplicate progress line)',
          0 <= i_zen < i_wait and sum(1 for m in logs if 'Waiting for ZEN' in m) == 1, logs[:8])


    ZEN_BOX.stop()
    KEEP_ALIVE.append(locals())  # modules, threads and widgets of the section live until the end
    return results

# --- start ROI ---
def _section_start_roi():
    """start_roi of the ROI scan task (ROI names only).
    (1) RoiScanDummyTask as configured in dummy_config.cfg (roi_multicolour_scan_dummy), with the real
        roi_logic / laser_control_logic modules of dummy_config.cfg and a 5-ROI list saved by roi_logic;
        the dummy stage's move_abs is recorded.
    (2) RoiScanSDTask with recording roi / laser stand-ins and a fake TriggerLogic (ZEN ready / done
        answered at once).
    (3) Same calls as before the change for a run from the first ROI and for an interrupt (stand-ins);
        only when <roi_scan_with_resume.py> is given.
    The 5-ROI list is kept (start at the 3rd ROI, interrupt during the 4th)."""
    import sys, os, re, weakref, logging, importlib, importlib.util, tempfile, threading, copy, glob
    from time import monotonic, sleep
    from importlib.metadata import version

    before_path = REF_ROI_SCAN_BEFORE
    from qtpy import QtCore, QtGui, QtWidgets  # noqa: E402

    import yaml  # noqa: E402
    import qudi.core  # noqa: E402
    from qudi.core.connector import Connector  # noqa: E402
    from qudi.tasks import roi_multicolour_scan as rs  # noqa: E402

    results = []


    def check(label, cond, detail=''):
        results.append((label, bool(cond)))
        print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)


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
    # dummy_config entry of roi_multicolour_scan_dummy: checked once, in the progress display section
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
    yaml.safe_dump({'sample_name': 'SDsample', 'save_path': os.path.join(TMP, 'sd_data'), 'roi_list_path': '/fake/rois.json',
                    'zen_saving_path': ZEN.root, 'imaging_sequence': [[488, 50.0]]}, open(sd_cfg, 'w'))
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

    ZEN_BOX.stop()
    KEEP_ALIVE.append(locals())  # modules, threads and widgets of the section live until the end
    return results

# --- ZEN settings pop-up ---
def _section_zen_popup():
    """ROI scan on the spinning disk: ZEN settings box before the scan (tasks/common/popups.py
    ask_confirmation, gui/task_runner/dialogs.py build_confirmation_box). RoiScanSDTask with recording roi /
    laser stand-ins and a fake TriggerLogic (ZEN ready / done answered at once); the task runs in its own
    thread, the GUI thread answers the box (or not)."""
    import sys, os, logging, tempfile, threading
    from time import monotonic, sleep
    from importlib.metadata import version

    from qtpy import QtCore, QtWidgets  # noqa: E402

    import yaml  # noqa: E402
    from qudi.tasks import roi_multicolour_scan as rs  # noqa: E402
    from qudi.tasks.common import popups  # noqa: E402

    results = []


    def check(label, cond, detail=''):
        results.append((label, bool(cond)))
        print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)


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
            if name == 'trigger_ZEN_ready':
                ZEN.ready()  # ZEN starts the experiment: new data folder
            return True


    KEEP = []
    ZEN = _short.ZenFolders(os.path.join(TMP, 'zen'))  # zen_saving_path of the SD runs
    ROIS_2 = _short.roi_names()                          # shared 2-ROI list names
    ROIS_20 = [f'ROI_{k:03d}' for k in range(1, 21)]     # 20 ROIs for the start_roi case


    def sd_yaml(name, sequence):
        path = os.path.join(TMP, f'{name}.yaml')
        yaml.safe_dump({'sample_name': 'SDsample', 'save_path': os.path.join(TMP, f'data_{name}'),
                        'roi_list_path': '/fake/rois.json', 'imaging_sequence': sequence,
                        'zen_saving_path': ZEN.root}, open(path, 'w'))
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
    KEEP_ALIVE.append(locals())  # modules, threads and widgets of the section live until the end
    return results

# --- run folder and run files ---
def _section_data_folder():
    """Run folder created by qudi (tasks/common/data_folders.py) for the ROI scan and the Hi-M task: on the
    server folder (save_network_path) when it is writable, otherwise in the local folder (save_path); files
    written there besides the data (tasks/common/run_metadata.py): experiment_config.yaml and metadata.yml
    (option metadata_template; the repository's Spinning_Disk_setup.cfg unless a case changes it).

    Temporary "server" and "local" folders; unreachable folders are paths under a regular file or under
    /proc (cannot be created, also when the tests run as root). ROI scan SD: roi / laser stand-ins and a
    fake TriggerLogic (ZEN ready / done answered at once), the ZEN settings box answered 'Done - continue'.
    Hi-M: the real dummy fluidics, roi and laser modules of dummy_config.cfg. Short settings and test data:
    tests/_short.py (docs/TESTING.md)."""
    import os, re, logging, tempfile, threading, weakref, importlib, glob
    from datetime import datetime
    from time import monotonic, sleep

    from qtpy import QtCore, QtWidgets

    import yaml
    from qudi.core.connector import Connector
    from qudi.tasks import roi_multicolour_scan as rs
    from qudi.tasks import him
    from qudi.tasks.common import data_folders, run_metadata

    results = []

    def check(label, cond, detail=''):
        results.append((label, bool(cond)))
        print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)

    TMP = tempfile.mkdtemp()
    DAY = datetime.today().strftime('%Y_%m_%d')
    LOGS = []
    QtCore.qInstallMessageHandler(lambda *a: None)

    class H(logging.Handler):
        def emit(self, r):
            LOGS.append((r.levelno, r.getMessage()))

    ROIS = _short.roi_names()   # ROI_000, ROI_001
    ZEN_BOX = _short.AutoAnswer('ZEN settings')  # answers the ZEN settings box of the ROI scan
    A_FILE = os.path.join(TMP, 'a_file.txt')
    open(A_FILE, 'w').close()
    MISSING = os.path.join(A_FILE, 'server')        # parent is a file: cannot be created
    READ_ONLY = '/proc/qudi_test_server'             # under /proc: cannot be created
    TEMPLATE = os.path.join(repo, 'custom_config', 'custom_metadata_templates', 'Spinning_Disk_setup.cfg')

    def folder(name):
        path = os.path.join(TMP, name)
        os.makedirs(path, exist_ok=True)
        return path

    # ------------------------------------------------------------------ stand-ins
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
            self.roi_names = list(ROIS)

        def get_stage_velocity(self, axes):
            self._rec.rec('get_stage_velocity', axes)
            return {a: 6000.0 for a in axes}

        def get_roi_position(self, name):
            self._rec.rec('get_roi_position', name)
            return (float(name[-3:]) * 10, 0.0, 0.0)

    class LaserControlLogic(_Stand):
        _meta = {'mro': ('LaserControlLogic',)}

    class ZenSim:
        """Fake ZEN saving folder: when "ready" is raised (the user starts the ZEN experiment), ZEN creates its
        data folder there - one new folder ('one'), none ('none') or two ('two')."""
        def __init__(self, root):
            self.root, self.mode, self.created = root, 'one', []
            for old in ('2026-11-01_old_experiment', '2026-11-02_old_experiment'):
                os.makedirs(os.path.join(root, old), exist_ok=True)
            open(os.path.join(root, 'notes.txt'), 'w').close()  # a file: not counted as a folder

        def ready(self):
            for _ in range({'one': 1, 'none': 0, 'two': 2}[self.mode]):
                path = os.path.join(self.root, f'{DAY.replace("_", "-")}_Scan_test_{len(self.created) + 1:02d}')
                os.makedirs(path)
                self.created.append(path)

        def tree(self):
            """Every file and folder under the ZEN saving folder (relative paths)."""
            return sorted(os.path.relpath(os.path.join(d, n), self.root)
                          for d, dirs, files in os.walk(self.root) for n in dirs + files)

    ZEN = ZenSim(folder('zen'))

    class TriggerLogic(_Stand):
        """Fake ZEN triggers: every poll answered at once; "ready" makes ZEN create its data folder; with
        autofocus=True (Hi-M), ZEN saves an autofocus image at each autofocus block (every other start trigger)."""
        _meta = {'mro': ('TriggerLogic',)}

        def __init__(self, rec, zen=None, autofocus=False):
            super().__init__(rec)
            self.zen = zen if zen is not None else ZEN
            self.autofocus, self.starts = autofocus, 0

        def send_trigger(self, name):
            self._rec.rec('send_trigger', name)
            if name == 'trigger_ZEN_start_block':
                self.starts += 1
                if self.autofocus and self.starts % 2 == 1:
                    _short.write_autofocus_image(self.zen.created[-1], self.starts)

        def is_triggered(self, name):
            self._rec.rec('is_triggered', name)
            if name == 'trigger_ZEN_ready':
                self.zen.ready()
            return True

    KEEP = []

    def run(task, kwargs=None, timeout=120):
        out = {}

        def target():
            try:
                out['result'] = task(**(kwargs or {}))
            except Exception as err:
                out['error'] = err
        LOGS.clear()
        th = threading.Thread(target=target, daemon=True, name='task')
        th.start()
        t0 = monotonic()
        while th.is_alive() and monotonic() - t0 < timeout:
            app.processEvents()
            sleep(0.02)
        th.join(1)
        for _ in range(10):
            app.processEvents()
            sleep(0.01)
        return out.get('result'), out.get('error')

    def scan_yaml(name, **values):
        path = os.path.join(TMP, f'{name}.yaml')
        content = {'sample_name': 'SDsample', 'roi_list_path': '/fake/rois.json', 'imaging_sequence': [[488, 50.0]],
                   'zen_saving_path': ZEN.root}
        content.update(values)
        yaml.safe_dump(content, open(path, 'w'))
        return path

    def scan_task(cls, path, template=TEMPLATE):
        rec = Rec()
        stands = {'roi_logic': RoiLogic(rec), 'laser_logic': LaserControlLogic(rec)}
        if cls is rs.RoiScanSDTask:
            stands['trigger_logic'] = TriggerLogic(rec)
        KEEP.append(stands)
        task = _short.shorten(type(cls.__name__ + 'UnderTest', (cls,),
                                   {'user_config_path': path, 'metadata_template': template})())
        task.connect_modules(stands)
        if not any(isinstance(h, H) for h in task.log.handlers):  # tasks of the same class share their logger
            task.log.addHandler(H())
        return task, rec

    def movies(path):
        path = os.path.join(path, 'movie_name.txt')
        return open(path).read().split() if os.path.exists(path) else None

    def server_boxes():
        return [w for w in app.topLevelWidgets() if isinstance(w, QtWidgets.QMessageBox) and w.isVisible()
                and w.windowTitle() == data_folders.SERVER_WARNING_TITLE]

    def close_boxes():
        for box in server_boxes():
            box.close()
        app.processEvents()

    def run_folders(root):
        return sorted(glob.glob(os.path.join(root, DAY, '*')))

    def mirror(root, zen_folder):
        return os.path.join(root, os.path.basename(zen_folder), 'metadata')

    SD_DAY = DAY.replace('_', '-')  # dated folder of the spinning-disk runs: <save_path>/<YYYY-MM-DD>/

    def local_sd(local):
        return os.path.join(local, SD_DAY)

    # ------------------------------------------------------------------ (1) ROI scan SD, server folder writable
    server, local = folder('server_1'), folder('local_1')
    cfg = scan_yaml('sd_server', save_path=local, save_network_path=server)
    for run_number in (1, 2):
        before = len([n for n in os.listdir(ZEN.root) if os.path.isdir(os.path.join(ZEN.root, n))])
        tree_before = ZEN.tree()
        task, rec = scan_task(rs.RoiScanSDTask, cfg)
        result, err = run(task, {'start_roi': ''})
        zen_folder = ZEN.created[-1] if ZEN.created else ''
        run_folder = mirror(local_sd(local), zen_folder)
        prefix = str(before + 1).zfill(3)
        expected = [f'scan_{prefix}_{r[4:]}_ROI' for r in ROIS]
        check(f'(1 ROI scan SD, run {run_number}) files in <save_path>/<YYYY-MM-DD>/<ZEN folder name>/metadata (local '
              f'even with save_network_path set): '
              f'parameters.yml, movie_name.txt, experiment_config.yaml, metadata.yml; prefix {prefix} (folders before '
              f'+ 1); names {expected}; no HiM_task.log',
              err is None and result.get('directory') == run_folder and result.get('imaged_rois') == ROIS
              and task.prefix == prefix and movies(run_folder) == expected
              and sorted(os.listdir(run_folder)) == ['experiment_config.yaml', 'metadata.yml', 'movie_name.txt',
                                                     'parameters.yml'],
              (err, result, task.prefix, os.listdir(run_folder) if os.path.isdir(run_folder) else None))
        check(f'(1 ROI scan SD, run {run_number}) nothing created or modified in the ZEN saving folder (only the folder '
              f'ZEN created, still empty); nothing on the server; no pop-up, no warning',
              ZEN.tree() == sorted(tree_before + [os.path.basename(zen_folder)]) and os.listdir(zen_folder) == []
              and os.listdir(server) == [] and os.listdir(local) == [SD_DAY] and not server_boxes()
              and not any(lvl >= logging.WARNING for lvl, _ in LOGS),
              (ZEN.tree(), os.listdir(server), [m for lvl, m in LOGS if lvl >= logging.WARNING]))
    # metadata folder already holding files -> metadata_<HHMMSS>
    other = data_folders.create_mirror_folder(local_sd(local), zen_folder, task.log)
    check('(1 create_mirror_folder) existing metadata folder with files -> metadata_<HHMMSS> in the same folder, '
          'logged; nothing created in the ZEN folder',
          os.path.dirname(other) == os.path.dirname(run_folder) and re.fullmatch(r'metadata_\d{6}', os.path.basename(other))
          and os.path.isdir(other) and os.listdir(zen_folder) == []
          and any('already holds files' in m for _, m in LOGS), other)

    # ------------------------------------------------------------------ (2) save_network_path missing / not writable
    for label, server in (('missing', MISSING), ('not writable', READ_ONLY), ('empty', '')):
        local = folder(f'local_2_{label.replace(" ", "_")}')
        task, rec = scan_task(rs.RoiScanSDTask, scan_yaml(f'sd_{label[:3]}', save_path=local, save_network_path=server))
        result, err = run(task, {'start_roi': ''})
        run_folder = mirror(local_sd(local), ZEN.created[-1])
        check(f'(2 save_network_path {label}) not used by the SD ROI scan: files under <save_path>/<YYYY-MM-DD>/<ZEN '
              f'folder name>/metadata, scan runs (both ROIs), no pop-up, no warning',
              err is None and result.get('directory') == run_folder and result.get('imaged_rois') == ROIS
              and movies(run_folder) == [f'scan_{task.prefix}_{r[4:]}_ROI' for r in ROIS] and not server_boxes()
              and not any(lvl >= logging.WARNING for lvl, _ in LOGS),
              (err, result, [m for lvl, m in LOGS if lvl >= logging.WARNING]))
        close_boxes()

    # ------------------------------------------------------------------ (3b) zen_saving_path missing / not a folder
    for label, values, fragment in (('missing', {'zen_saving_path': None}, "'zen_saving_path' missing"),
                                    ('not a folder', {'zen_saving_path': A_FILE}, 'is not an existing folder')):
        task, rec = scan_task(rs.RoiScanSDTask, scan_yaml(f'sd_zen_{label[:3]}', save_path=folder('local_3b'), **values))
        result, err = run(task, {'start_roi': ''})
        check(f'(3b zen_saving_path {label}) error "{fragment}" before any hardware call (no roi / laser / trigger call), '
              f'cleanup restores nothing',
              err is not None and fragment in str(err) and rec.calls == []
              and any('nothing to restore' in m for _, m in LOGS), (err, rec.calls))

    # ------------------------------------------------------------------ (3c) no / two new ZEN folders
    for mode, fragment in (('none', 'No new file was created by ZEN'), ('two', 'More than one folder were found')):
        ZEN.mode = mode
        local = folder(f'local_3c_{mode}')
        task, rec = scan_task(rs.RoiScanSDTask, scan_yaml(f'sd_zen_{mode}', save_path=local))
        task._ZEN_FOLDER_ATTEMPTS = 2  # shorter wait for the missing folder (2 attempts, 1 s apart)
        result, err = run(task, {'start_roi': ''})
        names = [n for n, _ in rec.calls]
        check(f'(3c {mode} new ZEN folder) clear error ("{fragment}..."), no ROI imaged, no qudi folder; cleanup as '
              f'usual (stage back to the first ROI, lasers off, velocity restored, ROI GUI unlocked)',
              err is not None and fragment in str(err) and 'send_trigger' not in names
              and os.listdir(local) in ([], [os.path.basename(local_sd(local))])  # at most the empty dated folder
              and 'cleanup finished' in [m for _, m in LOGS] and 'go_to_roi_xy' in names
              and 'enable_roi_actions' in names and names.count('set_stage_velocity') == 2, (err, names[-6:]))
    ZEN.mode = 'one'

    # ------------------------------------------------------------------ (4) local folder not writable, no server
    for k, (label, local) in enumerate((('under a file', os.path.join(A_FILE, 'local')),
                                        ('on /proc', '/proc/qudi_test_local'))):
        task, rec = scan_task(rs.RoiScanSDTask, scan_yaml(f'sd_local_{k}', save_path=local))
        result, err = run(task, {'start_roi': ''})
        names = [n for n, _ in rec.calls]
        check(f'(4 local folder {label}, no server) error before any hardware call (only the ROI list loaded, no '
              f'laser / stage / trigger call), cleanup restores nothing, no pop-up',
              err is not None and f'The local data folder {local} cannot be written' in str(err)
              and names == ['load_roi_list'] and any('nothing to restore' in m for _, m in LOGS)
              and not server_boxes(), (err, names))

    # ------------------------------------------------------------------ Hi-M (real dummy modules)
    class FakeMain(QtCore.QObject):
        pass

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

    flow = build('fluidics_flow_logic')
    mods = {'valve_logic': MODULES['fluidics_valve_logic'], 'flow_logic': flow, 'robot_logic': build('pipetting_robot_logic'),
            'roi_logic': build('roi_logic'), 'laser_logic': build('laser_control_logic')}
    mods['robot_logic'].set_origin((0.0, 0.0, 1000.0))
    app.processEvents()
    injections = _short.load(_short.HIM_INJECTIONS)
    injections['probes'] = {1: 'RT1'}
    injections['hybridization list'] = [{'step_number': 1, 'procedure': 'Hybridization', 'product': 'SSC',
                                         'volume': _short.INJECTION_UL, 'flowrate': _short.HIM_FLOWRATE, 'time': None}]
    injections['photobleaching list'] = []
    inj_path = os.path.join(TMP, 'him_injections_1probe.yml')
    yaml.safe_dump(injections, open(inj_path, 'w'))
    sample = _short.load('him_experiment.yaml')['sample_name']

    def him_task(cls, exp, trigger=None):
        task = _short.shorten(cls(), progress_interval_s=0.2)
        task.user_config_path = exp
        task.metadata_template = TEMPLATE
        task.connect_modules(dict(mods, trigger_logic=trigger) if trigger else dict(mods))
        task.log.addHandler(H())
        return task

    # ------------------------------------------------------------------ (5) Hi-M SD, 1 probe, 2 ROIs, server folder
    server, local = folder('server_5'), folder('local_5')
    _short.use_npy_autofocus_images()  # test autofocus images: .npy content (no czifile)
    ref_images = _short.write_autofocus_references(folder('zen_ref'), len(ROIS))
    exp = _short.experiment(TMP, 'him_experiment.yaml', 'him_sd', injections_path=inj_path, save_path=local,
                            save_network_path=server, zen_ref_images_path=ref_images, correlation_threshold=0.6,
                            zen_saving_path=ZEN.root, autofocus_min_fraction=_short.AUTOFOCUS_MIN_FRACTION)
    trigger = TriggerLogic(Rec(), autofocus=True)
    KEEP.append(trigger)
    result, err = run(him_task(him.HiMSDTask, exp, trigger), timeout=180)
    run_folder = mirror(local_sd(local), ZEN.created[-1])
    names = movies(run_folder)
    prefix = str(len([n for n in os.listdir(ZEN.root) if os.path.isdir(os.path.join(ZEN.root, n))])).zfill(3)
    check(f'(5 Hi-M SD, 1 probe, 2 ROIs) files in <save_path>/<YYYY-MM-DD>/<ZEN folder name>/metadata '
          f'(HiM_parameters.yml, movie_name.txt, injections.yml, HiM_task.log); names scan_{prefix}_RT1_<roi>_ROI; '
          f'nothing on the server (no transfer), nothing written by qudi in the ZEN folder',
          err is None and result and result['cycles_done'] == 1 and result['directory'] == run_folder
          and {'HiM_parameters.yml', 'injections.yml', 'HiM_task.log', 'experiment_config.yaml',
               'metadata.yml'} <= set(os.listdir(run_folder))
          and names == [f'scan_{prefix}_RT1_{r[4:]}_ROI' for r in ROIS] and os.listdir(server) == []
          and os.listdir(ZEN.created[-1]) == ['autofocus'], (err, result, names))  # only the images of the fake ZEN

    # ------------------------------------------------------------------ (6) dummies with save_path only
    save_path = os.path.join(TMP, 'dummy_data')
    task, rec = scan_task(rs.RoiScanDummyTask, scan_yaml('dummy', save_path=save_path))
    result, err = run(task, {'start_roi': ''})
    run_folder = os.path.join(save_path, DAY, '001_Scan_SDsample')
    check('(6 ROI scan dummy, save_path only) save_path/YYYY_MM_DD/001_Scan_<sample> with parameters.yml and '
          'movie_name.txt; names scan_001_<roi number>_ROI; no pop-up, no warning',
          err is None and result.get('directory') == run_folder
          and os.path.exists(os.path.join(run_folder, 'parameters.yml'))
          and movies(run_folder) == [f'scan_001_{r[4:]}_ROI' for r in ROIS]
          and not server_boxes() and not any(lvl >= logging.WARNING for lvl, _ in LOGS), (err, result))
    exp = _short.experiment(TMP, 'him_experiment.yaml', 'him_dummy', injections_path=inj_path)
    result, err = run(him_task(him.HiMDummyTask, exp), timeout=180)
    run_folder = os.path.join(TMP, 'data_him_dummy', DAY, f'001_HiM_{sample}')
    check(f'(6 Hi-M dummy, save_path only) save_path/YYYY_MM_DD/001_HiM_{sample} with HiM_parameters.yml and '
          f'movie_name.txt; names scan_001_RT1_<roi>_ROI; no pop-up',
          err is None and result and result['cycles_done'] == 1 and result['directory'] == run_folder
          and os.path.exists(os.path.join(run_folder, 'HiM_parameters.yml'))
          and movies(run_folder) == [f'scan_001_RT1_{r[4:]}_ROI' for r in ROIS] and not server_boxes(),
          (err, result))

    # ------------------------------------------------------------------ run files: experiment copy and metadata.yml
    def acquisition(metadata):
        """Acquisition section of metadata.yml as one mapping."""
        return {k: v for item in metadata['Acquisition'] for k, v in item.items()}

    template = yaml.safe_load(open(TEMPLATE, encoding='utf-8'))
    save_path = os.path.join(TMP, 'run_files_data')
    exp = scan_yaml('run_files', save_path=save_path, imaging_sequence=[[561, 30.0], [488, 50.0]])
    # (7) ROI scan dummy, 2 ROIs, template set
    task, rec = scan_task(rs.RoiScanDummyTask, exp)
    result, err = run(task, {'start_roi': ''})
    run_folder = os.path.join(save_path, DAY, '001_Scan_SDsample')
    copy_path = os.path.join(run_folder, 'experiment_config.yaml')
    meta_path = os.path.join(run_folder, 'metadata.yml')
    meta = yaml.safe_load(open(meta_path, encoding='utf-8')) if os.path.exists(meta_path) else None
    acq = acquisition(meta) if meta else {}
    check('(7 run files, template set) experiment_config.yaml byte-identical to the experiment file',
          err is None and os.path.exists(copy_path) and open(copy_path, 'rb').read() == open(exp, 'rb').read(), err)
    check('(7 run files, template set) metadata.yml: Time set, sample name, laser lines / powers in sequence order '
          '(561, 488 / 30, 50), the 2 ROIs with their positions',
          meta is not None and meta['Time'] and acq['sample_name'] == 'SDsample'
          and acq['laser_lines'] == [561, 488] and acq['laser_power_(%)'] == [30.0, 50.0]
          and acq['roi_list_(xyz)'] == [{'ROI_000': [0.0, 0.0, 0.0]}, {'ROI_001': [10.0, 0.0, 0.0]}], acq)
    check('(7 run files, template set) metadata.yml: sections in template order, fields the task does not know as in '
          'the template (number_z_planes not in the experiment file)',
          meta is not None and list(meta) == list(template) and meta['Camera'] == template['Camera']
          and meta['Fluidics'] == template['Fluidics']
          and acq['number_z_planes'] == acquisition(template)['number_z_planes']
          and acq['exposure_time_(s)'] == acquisition(template)['exposure_time_(s)'], meta)
    params = yaml.safe_load(open(os.path.join(run_folder, 'parameters.yml'))) if os.path.isdir(run_folder) else {}
    check('(7 run files, template set) parameters.yml and movie_name.txt as before',
          params == {'Sample name': 'SDsample', 'start_roi': '', 'ROI_000': 'X = 0.0 - Y = 0.0',
                     'ROI_001': 'X = 10.0 - Y = 0.0'}
          and movies(run_folder) == [f'scan_001_{r[4:]}_ROI' for r in ROIS], params)

    # (8) template option not set
    task, rec = scan_task(rs.RoiScanDummyTask, exp, template=None)
    result, err = run(task, {'start_roi': ''})
    run_folder = os.path.join(save_path, DAY, '002_Scan_SDsample')
    warnings = [m for lvl, m in LOGS if lvl == logging.WARNING]
    check('(8 run files, no template) one warning "no metadata template set - metadata.yml not written", run '
          'completes, no metadata.yml (experiment_config.yaml still written)',
          err is None and result.get('imaged_rois') == ROIS and warnings == [run_metadata.NO_TEMPLATE_WARNING]
          and not os.path.exists(os.path.join(run_folder, 'metadata.yml'))
          and os.path.exists(os.path.join(run_folder, 'experiment_config.yaml')), (err, warnings))

    # (9) template path wrong / file unreadable
    bad_yaml = os.path.join(TMP, 'bad_template.cfg')
    open(bad_yaml, 'w').write('Acquisition: [unclosed\n')
    for label, path, fragment in (('wrong path', os.path.join(TMP, 'no_template.cfg'), 'is not an existing file'),
                                  ('unreadable', bad_yaml, 'Could not read metadata_template')):
        task, rec = scan_task(rs.RoiScanDummyTask, exp, template=path)
        result, err = run(task, {'start_roi': ''})
        check(f'(9 run files, template {label}) error "{fragment}" before any hardware call (no roi / laser call, '
              f'no run folder), cleanup restores nothing',
              err is not None and fragment in str(err) and rec.calls == []
              and not os.path.exists(os.path.join(save_path, DAY, '003_Scan_SDsample'))
              and any('nothing to restore' in m for _, m in LOGS), (err, rec.calls))

    ZEN_BOX.stop()
    KEEP_ALIVE.append(locals())  # modules, threads and widgets of the section live until the end
    return results


SECTIONS = [
    ('progress display', _section_progress),
    ('start ROI', _section_start_roi),
    ('ZEN settings pop-up', _section_zen_popup),
    ('run folder and run files', _section_data_folder),
]

if __name__ == '__main__':
    all_results = []
    for title, run_section in SECTIONS:
        print(f'\n# --- {title} ---', flush=True)
        all_results += run_section()
    print(f'\n{sum(ok for _, ok in all_results)}/{len(all_results)} passed', flush=True)
    os._exit(0 if all(ok for _, ok in all_results) else 1)
