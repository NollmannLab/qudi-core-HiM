"""Hi-M task (qudi.tasks.him) on the dummy setup, the SD task with a fake ZEN, the RAMM placeholder.

Usage: QT_QPA_PLATFORM=offscreen python tests/test_him.py [<repo_root>] [quick]
Short settings and test data: tests/_short.py, tests/data/ (him_injections.yml, rois_2.json), docs/TESTING.md.
Real modules of dummy_config.cfg: fluidics (dummy valve, DaqPumpController pumps, DummyFlowSensor,
FluidicsFlowLogic, pipetting robot on the dummy stage), roi_logic and laser_control_logic. The task
runs in its own thread, the modules in the main thread (event loop). Logic calls are recorded.
"""
import sys, os, re, weakref, logging, importlib, tempfile, threading, copy, glob, shutil
from time import monotonic, sleep
from importlib.metadata import version

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _short  # noqa: E402  (short settings and shared test data, docs/TESTING.md)
repo = _short.repo_root(sys.argv)
sys.path.insert(0, os.path.join(repo, 'src'))
from qtpy import QtCore, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: QtWidgets.QMessageBox.Ok)
import yaml  # noqa: E402
import numpy as np  # noqa: E402
import qudi.core  # noqa: E402
from qudi.core.connector import Connector  # noqa: E402
from qudi.tasks import him  # noqa: E402

np.random.seed(0)
results = []


def check(label, cond, detail=''):
    results.append((label, bool(cond)))
    print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)


print('qudi-core', version('qudi-core'))
TMP = tempfile.mkdtemp()
QT_MESSAGES = []
QtCore.qInstallMessageHandler(lambda mode, ctx, msg: None if 'propagateSizeHints' in msg else QT_MESSAGES.append(msg))


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
valve, robot = MODULES['fluidics_valve_logic'], build('pipetting_robot_logic')
roi = build('roi_logic')
laser = build('laser_control_logic')
valve_hw = MODULES['dummy_valve']
ORIGIN = (0.0, 0.0, 1000.0)
robot.set_origin(ORIGIN)
INITIAL_VELOCITY = {'x': 6000.0, 'y': 6000.0}  # differs from scan_stage_velocity, so that the restore is visible
roi.set_stage_velocity(INITIAL_VELOCITY)
app.processEvents()

# ROI lists: the shared test list (tests/data/rois_2.json), and an empty list
ROI3 = _short.ROI_LIST
roi.load_roi_list(ROI3)
NAMES = list(roi.roi_names)
N = len(NAMES)
roi.delete_all_roi()
roi.save_roi_list(TMP, 'rois0')
ROI0 = os.path.join(TMP, 'rois0.json')
roi.load_roi_list(ROI3)
print('    ROIs:', NAMES)

# ------------------------------------------------------------------ call recording
CALLS = []  # (time, 'object.method', args, thread)


def spy(obj, tag, names):
    for name in names:
        orig = getattr(obj, name)

        def wrapper(*a, _orig=orig, _name=name, **k):
            CALLS.append((monotonic(), f'{tag}.{_name}', a + tuple(k.values()), threading.current_thread().name))
            return _orig(*a, **k)
        setattr(obj, name, wrapper)


spy(valve, 'valve', ('set_valve_position', 'disable_valve_positioning', 'enable_valve_positioning'))
spy(flow, 'flow', ('set_pressure', 'start_pressure_regulation_loop', 'stop_pressure_regulation_loop',
                   'start_volume_measurement', 'stop_volume_measurement', 'start_rinsing', 'stop_rinsing',
                   'disable_flowcontrol_actions', 'enable_flowcontrol_actions'))
spy(robot, 'robot', ('start_move_to_target', 'disable_positioning_actions', 'enable_positioning_actions'))
spy(roi, 'roi', ('load_roi_list', 'set_active_roi', 'go_to_roi_xy', 'stage_wait_for_idle', 'get_stage_velocity',
                 'set_stage_velocity', 'disable_tracking_mode', 'enable_tracking_mode', 'disable_roi_actions',
                 'enable_roi_actions'))
spy(laser, 'laser', ('stop_laser_output', 'disable_laser_actions', 'enable_laser_actions', 'set_laser_disabled'))
HARDWARE = ('valve.set_valve_position', 'robot.start_move_to_target', 'flow.set_pressure',  # set_active_roi left out: also called by load_roi_list (no move)
            'flow.start_pressure_regulation_loop', 'flow.start_rinsing', 'roi.go_to_roi_xy',
            'roi.set_stage_velocity', 'valve.disable_valve_positioning', 'laser.stop_laser_output')

LOGS = []


class H(logging.Handler):
    def emit(self, r):
        LOGS.append((monotonic(), r.levelno, r.getMessage()))


# ------------------------------------------------------------------ files
EXAMPLE = _short.load(_short.HIM_INJECTIONS)


def files(injections, name, roi_list=ROI3, save_path=None, extra=None):
    inj = os.path.join(TMP, f'{name}_injections.yml')
    yaml.safe_dump(injections, open(inj, 'w'))
    exp = {'sample_name': 'Mysample', 'roi_list_path': roi_list, 'injections_path': inj,
           'imaging_sequence': [[488, 50.0], [561, 80.0]], 'num_z_planes': 5,
           'save_path': save_path or os.path.join(TMP, f'data_{name}')}
    exp.update(extra or {})
    path = os.path.join(TMP, f'{name}_experiment.yaml')
    yaml.safe_dump(exp, open(path, 'w'))
    return path


ENTRY = CFG['logic']['task_runner']['options']['module_tasks']['him_dummy']
check('dummy_config: him_dummy is HiMDummyTask, options user_config_path only, and the 5 connectors',
      ENTRY['module.Class'] == 'qudi.tasks.him.HiMDummyTask' and set(ENTRY['options']) == {'user_config_path'}
      and set(ENTRY['connect']) == {'valve_logic', 'flow_logic', 'robot_logic', 'roi_logic', 'laser_logic'})
MODS = {'valve_logic': valve, 'flow_logic': flow, 'robot_logic': robot, 'roi_logic': roi, 'laser_logic': laser}


def make_task(cls=him.HiMDummyTask, user_config_path=None, **attrs):
    task = cls()
    for k, v in ENTRY['options'].items():
        setattr(task, k, v)
    task.user_config_path = user_config_path
    # short settings; live progress every 0.2 s so that the short waits still show their live text
    _short.shorten(task, progress_interval_s=0.2)
    for k, v in attrs.items():
        setattr(task, k, v)
    task.connect_modules(dict(MODS))
    if not any(isinstance(h, H) for h in task.log.handlers):
        task.log.addHandler(H())
    return task


PROGRESS = []


def run(task, interrupt_when=None, timeout=600):
    out = {}
    PROGRESS.clear()
    task.sigProgress.connect(lambda s, t: PROGRESS.append((monotonic(), s, t)), QtCore.Qt.DirectConnection)

    def target():
        try:
            out['result'] = task()
        except Exception as err:
            out['error'] = err
    th = threading.Thread(target=target, daemon=True, name='task')
    t0 = monotonic()
    th.start()
    t_int = None
    while th.is_alive() and monotonic() - t0 < timeout:
        app.processEvents()
        if interrupt_when is not None and t_int is None and interrupt_when():
            t_int = monotonic()
            task.interrupt()
        sleep(0.02)
    th.join(2)
    for _ in range(40):
        app.processEvents()
        sleep(0.01)
    return out.get('result'), out.get('error'), t0, t_int


def calls(since, prefix=''):
    return [(c[1], c[2]) for c in CALLS if c[0] >= since and c[1].startswith(prefix)]


def valve_positions():
    return {a: valve_hw.get_valve_position(a) for a in 'abc'}


def end_state_ok(label, t0):
    names = [n for n, _ in calls(t0)]
    vel = dict(roi.get_stage_velocity(['x', 'y']))
    state = {'pressure': flow.get_pressure()[0], 'regulating': flow.regulating,
             'measuring': flow.measuring_volume, 'rinsing': flow.rinsing_enabled, 'valves': valve_positions()}
    ok = (state['pressure'] == 0.0 and not state['regulating'] and not state['measuring'] and not state['rinsing']
          and state['valves'] == {'a': 1, 'b': 1, 'c': 1})
    unlocked = all(n in names for n in ('valve.enable_valve_positioning', 'flow.enable_flowcontrol_actions',
                                        'robot.enable_positioning_actions', 'roi.enable_tracking_mode',
                                        'roi.enable_roi_actions', 'laser.enable_laser_actions'))
    last_roi = [a for n, a in calls(t0, 'roi.set_active_roi')][-1:]
    check(f'({label}) cleanup: pressure 0, regulation / volume / rinsing stopped, valves c=1 b=1 a=1, stage '
          f'back to {NAMES[0]} at the previous velocity {vel}, every GUI unlocked, no cleanup error',
          ok and unlocked and last_roi == [(NAMES[0],)] and 'roi.go_to_roi_xy' in names[-12:]
          and vel == INITIAL_VELOCITY and [a for n, a in calls(t0, 'roi.set_stage_velocity')][-1] == (INITIAL_VELOCITY,)
          and not any('Cleanup' in m for t, lvl, m in LOGS if t >= t0),
          (state, unlocked, last_roi, [m for t, lvl, m in LOGS if t >= t0 and 'Cleanup' in m]))


QUICK = 'quick' in sys.argv[1:]

# ------------------------------------------------------------------ (1) full 2-probe run (example injections file)
# incubation long enough for the live countdown checked below
task = make_task(user_config_path=files(_short.with_incubation(EXAMPLE, _short.COUNTDOWN_INCUBATION_S), 'full'))
CALLS.clear()
t0 = monotonic()
result, err, _, _ = run(task)
print('    result:', result, err)
check('(full run) 2 cycles done, no error', err is None and result and result['cycles_done'] == 2
      and result['probes'] == ['RT1', 'RT2'] and result['rois'] == N, (result, err))
seq = []
for n, a in calls(t0):
    if n == 'robot.start_move_to_target':
        seq.append(f'needle {a[0]}')
    elif n == 'valve.set_valve_position':
        seq.append(f'{a[0]}={a[1]}')
    elif n == 'flow.start_volume_measurement':
        seq.append('inject')
    elif n == 'roi.set_active_roi':
        seq.append(a[0])
    elif n == 'flow.start_rinsing':
        seq.append('rinse')
cyc = ['c=1', 'needle {t}', 'c=2',          # needle move (syringe valve closed during the move)
       'b=2', 'c=2',                          # start positions
       'a=1', 'inject', 'a=7', 'inject',      # SSC, probe
       'c=1', 'c=2',                          # incubation
       'a=2', 'inject',                       # wash buffer
       'c=1', 'b=1', 'a=1',                   # cleanup positions
       *NAMES, NAMES[0],                      # imaging, back to the first ROI
       'b=2', 'c=2', 'a=2', 'inject', 'a=3', 'inject', 'c=1', 'b=1', 'a=1',  # photobleaching
       'rinse', 'a=3', 'b=2', 'b=1', 'a=1']   # rinse: flow-logic rinse valve positions, restored after
expected = [x.format(t=1) for x in cyc] + [x.format(t=2) for x in cyc] + ['c=1', 'b=1', 'a=1', NAMES[0]]  # cleanup
body = seq[seq.index('c=1'):]  # the first set_active_roi comes from load_roi_list
check(f'(full run) order per cycle: needle -> hybridization (SSC, probe, incubation, wash) -> imaging of the '
      f'{N} ROIs -> back to first ROI -> photobleaching (valve a only) -> rinse; needle tubes 1 then 2',
      body == expected, '\n      got ' + str(seq) + '\n      exp ' + str(expected))
check('(full run) tubes used [1, 2], one needle move per cycle', result and result['tubes_used'] == [1, 2]
      and [x for x in seq if x.startswith('needle')] == ['needle 1', 'needle 2'], result)
folder = result['directory'] if result else ''
movies = open(os.path.join(folder, 'movie_name.txt')).read().split() if folder else []
exp_movies = [f'scan_001_{rt}_{n[4:]}_ROI' for rt in ('RT1', 'RT2') for n in NAMES]
check(f'(full run) data folder {os.path.relpath(folder, TMP) if folder else None} = data/<day>/001_HiM_Mysample; '
      f'movie_name.txt = {movies[:2]}...', folder.endswith('001_HiM_Mysample') and movies == exp_movies, movies)
params = yaml.safe_load(open(os.path.join(folder, 'HiM_parameters.yml'))) if folder else {}
check('(full run) HiM_parameters.yml: global parameters, probes, both lists, imaging parameters, ROI positions',
      list(params) == ['1- global parameters', '2- fluidic parameters', '3- imaging parameters', '4- ROIs']
      and params['2- fluidic parameters']['probes'] == {1: 'RT1', 2: 'RT2'}
      and len(params['2- fluidic parameters']['photobleaching list']) == 2
      and params['3- imaging parameters']['number of laser lines'] == 2
      and list(params['4- ROIs']) == NAMES and params['4- ROIs'][NAMES[1]].startswith('X=100.0'), params)
labels = [f'{s} - {t}' for _, s, t in PROGRESS]
print('    progress (first / last):', labels[:3], labels[-3:])
check('(full run) progress: cycle, hybridization steps with live volume, ROI j/M, photobleaching, rinse countdown, Done',
      'Cycle 1/2 - RT1' in labels and 'Cycle 2/2 - RT2' in labels
      and 'Cycle 1/2 - RT1 - Hybridization 2/4 - Injecting Probe' in labels
      and any(re.fullmatch(rf'Cycle 1/2 - RT1 - Injecting SSC - \d+/{_short.INJECTION_UL} µl', x) for x in labels)
      and f'Cycle 1/2 - RT1 - Hybridization 3/4 - Incubating {_short.COUNTDOWN_INCUBATION_S} s' in labels
      and any(re.fullmatch(r'Cycle 1/2 - RT1 - Incubating - 0:0\d left', x) for x in labels)
      and [x for x in labels if x.startswith('Cycle 2/2 - RT2 - ROI')] == [f'Cycle 2/2 - RT2 - ROI {j}/{N}' for j in range(1, N + 1)]
      and 'Cycle 1/2 - RT1 - Photobleaching 1/2 - Injecting Wash buffer' in labels
      and any(re.fullmatch(rf'Cycle 1/2 - RT1 - Rinsing needle - [0-{int(_short.RINSE_S)}] s left', x) for x in labels)
      and labels[-1] == '2/2 - Done', labels)
rinse = [c for c in CALLS if c[0] >= t0 and c[1] == 'flow.start_rinsing']
check(f'(full run) rinse: start_rinsing({_short.RINSE_S:g}) runs in the flow logic thread, the task waits for its end',
      len(rinse) == 2 and rinse[0][2] == (float(_short.RINSE_S),) and rinse[0][3] == 'MainThread'
      and not [m for m in QT_MESSAGES if 'Timer' in m], (rinse, QT_MESSAGES))
end_state_ok('full run', t0)

if not QUICK:
    # ------------------------------------------------------------------ (2) interrupts
    short = copy.deepcopy(EXAMPLE)
    for lst in ('hybridization list', 'photobleaching list'):
        for e in short[lst]:
            if e['volume']:
                e['volume'] = 5
    for label, cond in (('hybridization', lambda: any(t.startswith('Hybridization 2/4') for _, s, t in PROGRESS)
                         and any('Injecting Probe -' in t for _, s, t in PROGRESS)),
                        ('imaging', lambda: any(t == f'ROI 2/{N}' for _, s, t in PROGRESS)),
                        ('rinse', lambda: any(t.startswith('Rinsing needle - ') for _, s, t in PROGRESS))):
        task = make_task(user_config_path=files(short, f'int_{label}'))
        t0 = monotonic()
        result, err, _, t_int = run(task, interrupt_when=cond)
        check(f'(interrupt during {label}) task stopped (no result), interrupted in that phase',
              t_int is not None and result is None and not task.success, (result, err))
        end_state_ok(f'interrupt during {label}', t0)

    # ------------------------------------------------------------------ (3) errors before any hardware call
    def expect_error(label, injections, fragments, roi_list=ROI3, origin=True, n=None):
        if not origin:
            robot.origin = None
        task = make_task(user_config_path=files(injections, f'err_{label}', roi_list=roi_list))
        t0 = monotonic()
        result, err, _, _ = run(task)
        if not origin:
            robot.set_origin(ORIGIN)
        msg = str(err)
        hw = [n_ for n_, _ in calls(t0) if n_ in HARDWARE]
        check(f'(error: {label}) one error naming the problem(s); no hardware call, no GUI lock',
              err is not None and all(f in msg for f in fragments) and (n is None or f'{n} problem(s)' in msg)
              and hw == [] and not task._hardware_touched, (msg, hw))
        return msg

    bad = copy.deepcopy(EXAMPLE)
    bad['hybridization list'][0]['product'] = 'Unknown buffer'
    expect_error('unknown product', bad, ("hybridization list: step 1: product 'Unknown buffer' is not in the buffer list",))
    bad_pb = copy.deepcopy(EXAMPLE)
    bad_pb['photobleaching list'][1]['product'] = 'Unknown'
    expect_error('unknown product in the photobleaching list', bad_pb,
                 ("photobleaching list: step 2: product 'Unknown' is not in the buffer list",))
    # needle position (robot origin) not defined: warning + message box, task ends as finished
    from qudi.tasks.common import fluidics_steps

    def boxes():
        return [w for w in app.topLevelWidgets() if isinstance(w, QtWidgets.QMessageBox) and w.isVisible()]

    for label, injections in (('missing origin', EXAMPLE), ('missing origin + unknown product', bad)):
        robot.origin = None
        task = make_task(user_config_path=files(injections, f'noorigin_{len(LOGS)}'))
        t0 = monotonic()
        n0 = len(LOGS)
        result, err, _, _ = run(task)
        robot.set_origin(ORIGIN)
        logs = [(lvl, m) for t, lvl, m in LOGS[n0:]]
        names = [n for n, _ in calls(t0)]
        shown = boxes()
        check(f'({label}) task ends as finished (no exception, success), result '
              f"{{'aborted': 'needle position not initialised', 'cycles_done': 0}}",
              err is None and task.success and result == {'aborted': 'needle position not initialised', 'cycles_done': 0},
              (err, result))
        check(f'({label}) warning logged, no error logged; pop-up shown (non-modal, GUI thread) with the message',
              (logging.WARNING, fluidics_steps.FluidicsStepsMixin._NEEDLE_POSITION_MESSAGE) in logs
              and not any(lvl >= logging.ERROR for lvl, _ in logs)
              and len(shown) == 1 and shown[0].text() == fluidics_steps.FluidicsStepsMixin._NEEDLE_POSITION_MESSAGE
              and not shown[0].isModal() and shown[0].thread() is app.thread(), (logs, [b.text() for b in shown]))
        check(f'({label}) no logic call at all: no valve / robot / stage / pressure call, no GUI lock, ROI list not '
              f'loaded; cleanup restored nothing', names == [] and not task._hardware_touched and not task._gui_locked
              and any('Hi-M task ended after 0/0' in m for _, m in logs)
              and not any('cleanup' in m.lower() and 'ended' not in m for _, m in logs), (names, logs[-3:]))
        for b in shown:
            b.close()
        app.processEvents()
    collide = copy.deepcopy(EXAMPLE)
    collide['hybridization list'].insert(2, {'product': 'Probe', 'volume': _short.INJECTION_UL, 'flowrate': _short.HIM_FLOWRATE,
                                             'time': None})
    expect_error("'next' tube colliding with a probe", collide,
                 ("probe RT1 (tube 1): with probe_needle_mode 'next' its 2 probe injections use tubes 1-2, "
                  "but tube 2 is probe RT2",), n=1)
    same = copy.deepcopy(collide)
    same['probe_needle_mode'] = 'same'
    task = make_task(user_config_path=files(same, 'same_mode'))
    task.dummy_imaging_time_s = 0.0
    t0 = monotonic()
    result, err, _, t_int = run(task, interrupt_when=lambda: any(t == f'ROI 1/{N}' for _, s, t in PROGRESS))
    check("('same' mode, 2 probe injections per cycle) no tube problem: the run starts (interrupted at the first ROI)",
          t_int is not None and 'Hi-M task not started' not in str(err), err)
    expect_error('empty ROI list', EXAMPLE, (f'the ROI list {ROI0} is empty',), roi_list=ROI0, n=1)
    all_bad = copy.deepcopy(collide)
    all_bad['hybridization list'][0]['product'] = 'Unknown buffer'
    msg = expect_error('everything at once', all_bad, ('Unknown buffer', 'tube 2 is probe RT2', 'is empty'),
                       roi_list=ROI0, n=3)
    check('(errors) the needle position is no longer a problem of the error list',
          'robot origin' not in msg and 'needle position' not in msg)
    print('    message:', msg.replace('\n', ' | '))
    roi.load_roi_list(ROI3)

    # ------------------------------------------------------------------ (4) HiMSDTask with a fake ZEN
    class TriggerLogic:  # stand-in; qudi-core 1.8 connectors check _meta['mro']
        _meta = {'mro': ('TriggerLogic',)}

        def __init__(self):
            self.mode = 'one'
            self.sent = []
            self.created = []

        def send_trigger(self, name):
            self.sent.append(name)

        def is_triggered(self, name):
            if name == 'trigger_ZEN_ready':
                if not self.created and self.mode in ('one', 'two'):
                    for k in range(1 if self.mode == 'one' else 2):
                        path = os.path.join(ZEN_SAVE, f'2026-10-19_HiM_{len(os.listdir(ZEN_SAVE))}')
                        os.makedirs(path)
                        self.created.append(path)
                return True
            return True

    ZEN_SAVE = os.path.join(TMP, 'zen_saving')
    ZEN_REF = os.path.join(TMP, 'zen_ref')
    os.makedirs(os.path.join(ZEN_SAVE, 'old_experiment'))
    os.makedirs(ZEN_REF)
    open(os.path.join(ZEN_SAVE, 'a_file.txt'), 'w').close()
    sd_inj = copy.deepcopy(EXAMPLE)
    sd_inj['probes'] = {1: 'RT1'}
    sd_inj['hybridization list'] = [{'product': 'SSC', 'volume': _short.INJECTION_UL, 'flowrate': _short.HIM_FLOWRATE, 'time': None}]
    sd_inj['photobleaching list'] = []
    sd_exp = files(sd_inj, 'sd', extra={'zen_saving_path': ZEN_SAVE, 'zen_ref_images_path': ZEN_REF,
                                        'correlation_threshold': 0.6, 'transfer_data': False, 'email': ''})
    trigger = TriggerLogic()
    KEEP = [trigger]

    def sd_task():
        task = him.HiMSDTask()
        task.user_config_path = sd_exp
        _short.shorten(task)
        task.connect_modules(dict(MODS, trigger_logic=trigger))
        if not any(isinstance(h, H) for h in task.log.handlers):
            task.log.addHandler(H())
        return task

    task = sd_task()
    t0 = monotonic()
    result, err, _, _ = run(task)
    logs = [(lvl, m) for t, lvl, m in LOGS if t >= t0]
    msgs = [m for _, m in logs]
    zen = trigger.created[0] if trigger.created else ''
    print('    SD result:', result, err)
    check(f'(SD) ZEN settings logged before the wait for ready: loops 1 x {N} = {N}, C = 2, Z = 5',
          f'ZEN: number of acquisition loops = 1 x {N} = {N}, C = 2, Z = 5' in msgs, [m for m in msgs if 'ZEN' in m][:4])
    check('(SD) new ZEN folder found (the old folder and the file ignored); metadata subfolder is the data folder',
          err is None and result['directory'] == os.path.join(zen, 'metadata') and os.path.isdir(result['directory'])
          and f'ZEN will save the data in the following folder : {zen}' in msgs, (result, err))
    movies = open(os.path.join(zen, 'metadata', 'movie_name.txt')).read().split() if zen else []
    check('(SD) HiM_parameters.yml and movie_name.txt in metadata/; legacy SD names with an empty prefix '
          f'({movies[:1]})', os.path.exists(os.path.join(zen, 'metadata', 'HiM_parameters.yml'))
          and movies == [f'scan__RT1_{n[4:]}_ROI' for n in NAMES], movies)
    ph = [m for lvl, m in logs if 'Autofocus check not implemented yet' in m]
    check(f'(SD) autofocus placeholder logged once per run ({N} ROIs)', ph == [
          'Autofocus check not implemented yet (zen_ref_images_path, correlation_threshold)'], ph)
    i_af = [k for k, m in enumerate(msgs) if 'autofocus confirmed done by ZEN' in m]
    i_ph = [k for k, m in enumerate(msgs) if 'Autofocus check not implemented' in m]
    i_acq = [k for k, m in enumerate(msgs) if 'Triggering ZEN acquisition' in m]
    check('(SD) order: autofocus done -> autofocus check -> acquisition block; 2 ZEN blocks per ROI',
          i_af and i_ph and i_acq and i_af[0] < i_ph[0] < i_acq[0] and trigger.sent.count('trigger_ZEN_start_block') == 2 * N)
    for mode, fragment in (('none', 'No new file was created by ZEN'), ('two', 'More than one folder were found')):
        trigger.mode = mode
        trigger.created = []
        task = sd_task()
        t0 = monotonic()
        result, err, _, _ = run(task)
        imaged = [m for t, lvl, m in LOGS if t >= t0 and 'Triggering ZEN' in m]
        check(f'(SD, {mode} new ZEN folder) clear error "{fragment}...", no ROI imaged, cleanup ran',
              err is not None and fragment in str(err) and not imaged
              and any('Hi-M task ended after 0/1' in m for t, lvl, m in LOGS if t >= t0), err)
        print('    message:', err)
        end_state_ok(f'SD, {mode} new ZEN folder', t0)
    SD_MISSING = files(sd_inj, 'sd_missing', extra={'zen_saving_path': os.path.join(TMP, 'nowhere'),
                                                     'zen_ref_images_path': ZEN_REF, 'correlation_threshold': 0.6})
    task = sd_task()
    task.user_config_path = SD_MISSING
    t0 = monotonic()
    result, err, _, _ = run(task)
    check('(SD) zen_saving_path not an existing folder -> error before any hardware call',
          err is not None and 'zen_saving_path' in str(err) and 'is not an existing folder' in str(err)
          and not [n for n, _ in calls(t0) if n in HARDWARE], err)

    # ------------------------------------------------------------------ (5) RAMM placeholder
    task = him.HiMRAMMTask()
    task.user_config_path = files(EXAMPLE, 'ramm')
    task.connect_modules(dict(MODS))
    t0 = monotonic()
    pos0 = robot.get_position() if hasattr(robot, 'get_position') else None
    result, err, _, _ = run(task)
    check('(RAMM) stops at once with the placeholder message; nothing moved, no GUI locked',
          err is not None and 'Hi-M imaging on the RAMM is not migrated yet (focus logic, FPGA) - see '
          'legacy/HiM_imaging_RAMM.py' in str(err) and '1 problem(s)' in str(err)
          and not [n for n, _ in calls(t0) if n in HARDWARE], err)

check('no Qt warning (timers started from another thread, ...)', not QT_MESSAGES, QT_MESSAGES)
print(f'\n{sum(ok for _, ok in results)}/{len(results)} passed', flush=True)
os._exit(0 if all(ok for _, ok in results) else 1)
