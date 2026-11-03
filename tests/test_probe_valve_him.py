"""Hi-M task: probe valve read from the injections file (dummy setup).

Usage: QT_QPA_PLATFORM=offscreen python tests/test_probe_valve_him.py [<repo_root>]
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
check('dummy_config: him_dummy is HiMDummyTask, options user_config_path only, the 5 connectors',
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



from qudi.tasks.common import fluidics_steps  # noqa: E402
from qudi.logic.taskrunner_logic import TaskRunnerLogic  # noqa: E402
NEEDLE_MSG = fluidics_steps.FluidicsStepsMixin._NEEDLE_POSITION_MESSAGE


def step(product, volume=_short.INJECTION_UL):
    return {'step_number': 0, 'procedure': 'Hybridization', 'product': product, 'volume': volume, 'flowrate': _short.HIM_FLOWRATE,
            'time': None}


def injections(probe_outlet, mode='next', with_probe=True):
    buffer = {1: 'SSC', 2: 'Wash'}
    if probe_outlet is not None:
        buffer[probe_outlet] = 'Probe'
    hyb = [step('SSC'), step('Probe'), {'step_number': 0, 'procedure': 'Hybridization', 'product': None,
                                         'volume': None, 'flowrate': None, 'time': _short.INCUBATION_S}, step('Probe'),
           step('Wash')]
    if not with_probe:
        hyb = [s for s in hyb if s['product'] != 'Probe']
    pb = [dict(step('Wash'), procedure='Photobleaching'), dict(step('SSC'), procedure='Photobleaching')]
    for lst in (hyb, pb):
        for k, s in enumerate(lst, 1):
            s['step_number'] = k
    return {'buffer': buffer, 'probes': {1: 'RT1', 4: 'RT2'}, 'hybridization list': hyb,
            'photobleaching list': pb, 'probe_needle_mode': mode}


def run_case(inj, name, **attrs):
    task = make_task(user_config_path=files(inj, name), **attrs)
    CALLS.clear()
    t0 = monotonic()
    result, err, _, _ = run(task)
    logs = [(t, lvl, m) for t, lvl, m in LOGS if t >= t0]
    a_moves = [a[1] for n, a in calls(t0, 'valve.set_valve_position') if a[0] == 'a']
    needle = [a[0] for n, a in calls(t0, 'robot.start_move_to_target')]
    hw = [c[0] for c in CALLS if c[0] >= t0 and c[1] in HARDWARE]
    plan_t = [t for t, lvl, m in logs if m.startswith(('Probe valve:', 'No Probe entry'))]
    return task, result, err, [(lvl, m) for _, lvl, m in logs], a_moves, needle, (plan_t[0] if plan_t else None,
                                                                                  hw[0] if hw else 1e18), t0


def plan_of(logs, label):
    first = [k for k, (_, m) in enumerate(logs) if m.startswith('Hi-M experiment')]
    last = [k for k, (_, m) in enumerate(logs) if m.startswith('    step') or m.startswith('  photobleaching')]
    lines = [m for _, m in logs[first[0]:last[-1] + 1]] if first and last else []
    print(f'    plan ({label}):')
    for m in lines:
        print('      ' + m)
    return lines


def warnings_of(logs, text):
    return [m for lvl, m in logs if lvl == logging.WARNING and text in m]


accepted = True
try:
    TaskRunnerLogic._validate_task_options(TaskRunnerLogic.__new__(TaskRunnerLogic), 'him', him.HiMDummyTask,
                                           {'user_config_path': 'x', 'probe_valve_number': 3})
except Exception:
    accepted = False
check('a config still setting probe_valve_number is accepted by the task runner (HiMDummyTask)', accepted)

# per cycle, valve a during the hybridization (1 SSC, P, P, 2 Wash), cleanup a=1, photobleaching (2 Wash, 1 SSC),
# cleanup a=1, needle rinse (rinsing_valve_positions of the flow logic: a=3, restored to 1); end cleanup a=1


def expected_a(p, with_probe=True):
    hyb = [1, p, p, 2] if with_probe else [1, 2]
    return (hyb + [1] + [2, 1] + [1] + [3, 1]) * 2 + [1]


# (1) Probe on 7, 'next'
task, result, err, logs, a7, needle7, (t_plan, t_hw), t0 = run_case(injections(7), 'p7')
plan = plan_of(logs, 'Probe on 7')
inj7 = os.path.join(TMP, 'p7_injections.yml')
check('(Probe on 7) 2 cycles done; valve a: per cycle SSC 1, Probe 7, Probe 7, Wash 2 | PB Wash 2, SSC 1',
      err is None and result and result['cycles_done'] == 2 and a7 == expected_a(7), (err, result, a7))
check(f"(Probe on 7) plan line 'Probe valve: 7 (from {os.path.basename(inj7)}) - 2 probe injection(s) in the "
      "hybridization list'", f'Probe valve: 7 (from {inj7}) - 2 probe injection(s) in the hybridization list' in plan)
check("(Probe on 7) plan: first cycle in full ('step 2/5: inject Probe (valve 7, tube 1)', 4/5 tube 2), "
      "cycle 2 with its tubes 4, 5; photobleaching 2 steps, buffer valve only",
      any(m.startswith('    step 2/5: inject Probe (valve 7, tube 1)') for m in plan)
      and any(m.startswith('    step 4/5: inject Probe (valve 7, tube 2)') for m in plan)
      and sum(1 for m in plan if m.startswith('    step ')) == 5 + 2
      and '  cycle 2/2 - RT2: same hybridization steps, probe injection(s) from tube(s) 4, 5' in plan
      and '  photobleaching: 2 step(s), buffer valve only' in plan, plan)
check('(Probe on 7) plan logged before any hardware call (moved before the GUI lock / stage velocity)',
      t_plan is not None and t_plan < t_hw, (t_plan, t_hw))
check("(Probe on 7, 'next') needle: cycle 1 tubes 1 then 2, cycle 2 tubes 4 then 5; tubes used [1, 2, 4, 5]",
      needle7 == [1, 2, 4, 5] and result['tubes_used'] == [1, 2, 4, 5], (needle7, result))
check('(Probe on 7) no probe_valve_number warning', not warnings_of(logs, 'probe_valve_number'))
end_state_ok('Probe on 7', t0)

# (2) same sequence re-saved with Probe on 3
task, result, err, logs, a3, needle3, (t_plan, t_hw), t0 = run_case(injections(3), 'p3')
plan = plan_of(logs, 'Probe on 3')
check('(Probe on 3) 2 cycles; valve 3 for the Probe steps', err is None and result['cycles_done'] == 2
      and a3 == expected_a(3), (err, a3))
check('(Probe on 3) plan: probe valve 3, steps with valve 3', any(m.startswith('Probe valve: 3 (from ') for m in plan)
      and any(m.startswith('    step 4/5: inject Probe (valve 3, tube 2)') for m in plan) and t_plan < t_hw)
check('(Probe on 3) same needle behaviour (1, 2, 4, 5)', needle3 == needle7 == [1, 2, 4, 5], (needle3, needle7))

# (3) 'same' mode
task, result, err, logs, a, needle, _, t0 = run_case(injections(3, mode='same'), 'p3_same')
plan = plan_of(logs, "Probe on 3, 'same'")
check("('same' mode) one tube per cycle: needle 1, 4; plan cycle 2 'tube(s) 4'",
      err is None and result['cycles_done'] == 2 and needle == [1, 4] and result['tubes_used'] == [1, 4]
      and '  cycle 2/2 - RT2: same hybridization steps, probe injection(s) from tube(s) 4' in plan
      and sum(1 for m in plan if 'inject Probe (valve 3, tube 1)' in m) == 2, (err, needle, result))

# (4) config still sets probe_valve_number: 3, file Probe on 7
task, result, err, logs, a, needle, _, t0 = run_case(injections(7), 'legacy', probe_valve_number=3)
w = warnings_of(logs, 'probe_valve_number')
print('    warning:', w)
check('(option probe_valve_number: 3 still set, file Probe on 7) exactly one warning (ignored, value used 7); '
      'runs with valve 7 and the needle moves', len(w) == 1 and 'ignored' in w[0] and 'Probe valve used: 7' in w[0]
      and err is None and result['cycles_done'] == 2 and a == expected_a(7) and needle == [1, 2, 4, 5], (w, err))

# (5) no Probe entry, buffer steps only, no robot origin
robot.origin = None
task, result, err, logs, a, needle, (t_plan, t_hw), t0 = run_case(injections(None, with_probe=False), 'noprobe')
plan = plan_of(logs, 'no Probe entry')
check('(no Probe entry, buffers only, no robot origin) runs: 2 cycles, valve a buffers only',
      err is None and result and result['cycles_done'] == 2 and a == expected_a(None, with_probe=False), (err, result, a))
check("(same) plan 'No Probe entry in the injections file - buffer injections only', cycle 2 buffer injections "
      "only, before any hardware call", 'No Probe entry in the injections file - buffer injections only' in plan
      and '  cycle 2/2 - RT2: same hybridization steps (buffer injections only)' in plan and t_plan < t_hw, plan)
check('(same) no needle move, no needle-position warning, no origin required',
      needle == [] and NEEDLE_MSG not in [m for _, m in logs] and result['tubes_used'] == [], (needle, result))
end_state_ok('no Probe entry', t0)

# (6) Probe used and no origin: needle-position abort as before
task, result, err, logs, a, needle, _, t0 = run_case(injections(3), 'p3_noorigin')
check('(Probe on 3 used, no robot origin) needle-position warning, aborted before any hardware call',
      err is None and result == {'aborted': 'needle position not initialised', 'cycles_done': 0}
      and not [n for n, _ in calls(t0) if n in HARDWARE] and NEEDLE_MSG in [m for _, m in logs], (err, result))
for w_ in [w_ for w_ in app.topLevelWidgets() if isinstance(w_, QtWidgets.QMessageBox)]:
    w_.close()
robot.set_origin(ORIGIN)
app.processEvents()

check('no Qt warning (timers started from another thread, ...)', not QT_MESSAGES, QT_MESSAGES)
print(f'\n{sum(ok for _, ok in results)}/{len(results)} passed', flush=True)
os._exit(0 if all(ok for _, ok in results) else 1)
