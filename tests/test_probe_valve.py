"""Probe valve read from the injections file (fluidics task, dummy hardware, injections configurator logic).

Usage: QT_QPA_PLATFORM=offscreen python tests/test_probe_valve.py [<repo_root>]
Real DummyValve, DummyMultiAxisStage + PipettingRobot, FluidicsValveLogic, FluidicsFlowLogic,
FluidicsRobotLogic and FluidicsGUI. Pump / flow sensor: test modules implementing PumpInterface /
FlowSensorInterface with the dummy flowboard behaviour (~200 ul/min). The task runs in its own
thread, the logic modules in the main thread (event loop), as in qudi.
"""
import sys, os, weakref, logging, tempfile, threading, copy
from time import monotonic, sleep
from importlib.metadata import version

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _short  # noqa: E402  (short settings and shared test data, docs/TESTING.md)
repo = _short.repo_root(sys.argv)
QUICK = 'quick' in sys.argv[1:]
sys.path.insert(0, os.path.join(repo, 'src'))
from qtpy import QtCore, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
QtWidgets.QMessageBox.information = staticmethod(lambda *a, **k: QtWidgets.QMessageBox.Ok)
import yaml  # noqa: E402
from numpy.random import normal  # noqa: E402
import qudi.core  # noqa: E402
from qudi.interface.pump_interface import PumpInterface  # noqa: E402
from qudi.interface.flow_sensor_interface import FlowSensorInterface  # noqa: E402
from qudi.hardware.fluidics_valve.dummy_valve import DummyValve  # noqa: E402
from qudi.hardware.multi_axis_translation_stage.dummy_multi_axis_stage import DummyMultiAxisStage  # noqa: E402
from qudi.hardware.interfuse_hardware.pipetting_robot import PipettingRobot  # noqa: E402
from qudi.logic.fluidics_valve_logic import FluidicsValveLogic  # noqa: E402
from qudi.logic.fluidics_flow_logic import FluidicsFlowLogic  # noqa: E402
from qudi.logic.fluidics_robot_logic import FluidicsRobotLogic  # noqa: E402
from qudi.logic.taskrunner_logic import TaskRunnerLogic  # noqa: E402
from qudi.gui.fluidics.fluidics_gui import FluidicsGUI  # noqa: E402
from qudi.tasks import fluidics  # noqa: E402
from qudi.tasks.common import fluidics_steps  # noqa: E402
from qudi.logic.injections_configurator_logic import InjectionsLogic, PROBE_BUFFER_NAME  # noqa: E402

results = []


def check(label, cond, detail=''):
    results.append((label, bool(cond)))
    print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)


print('qudi-core', version('qudi-core'))


class FakeMain(QtCore.QObject):
    pass


MAIN = FakeMain()
KEEP = []
LOGS = []


class H(logging.Handler):
    def emit(self, r):
        LOGS.append((monotonic(), r.levelno, r.getMessage()))


def module(cls, name, config=None, connect=None):
    m = cls(qudi_main_weakref=weakref.ref(MAIN), name=name, config=config or {})
    m.log.addHandler(H())
    for key, target in (connect or {}).items():
        m._meta['connectors'][key].connect(target)
    m.module_state.activate()
    KEEP.append(m)
    return m


class TestPump(PumpInterface):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.output = {0: 0.0}

    def on_activate(self): pass
    def on_deactivate(self): pass
    def set_output(self, param_dict): self.output.update({int(c): float(v) for c, v in param_dict.items()})
    def get_output(self, param_list=None): return dict(self.output)
    def get_constraints(self): return {'kind': 'pressure', 'unit': 'mbar', 'minimum': 0.0, 'maximum': 350.0}
    def stop(self): self.output = {c: 0.0 for c in self.output}


class TestFlowSensor(FlowSensorInterface):
    """Dummy flowboard behaviour: ~200 ul/min whatever the pressure."""
    mean_flow = 200

    def on_activate(self): pass
    def on_deactivate(self): pass
    def get_flowrate(self, param_list=None): return {0: int(self.mean_flow + normal(0, 10))}
    def get_sensor_unit(self, param_list=None): return {0: 'ul/min'}


dcfg = yaml.safe_load(open(os.path.join(repo, 'custom_config/dummy_config.cfg'), encoding='utf-8'))
hw = dcfg['hardware']
valve_hw = _short.speed_up(module(DummyValve, 'dummy_valve', hw['dummy_valve']['options']))
stage_opts = dict(hw['dummy_translation_stage']['options'])
# dummy_config limits x/y to +-1000 um while the grid pitch is 14900 um: widened here so that the
# robot can reach tubes 1..3
stage_opts.update({'x_min': -1000, 'x_max': 200000, 'y_min': -1000, 'y_max': 200000, 'delay_after_move': 0.2})
stage = module(DummyMultiAxisStage, 'dummy_translation_stage', _short.module_options('dummy_translation_stage', stage_opts))
robot_hw = module(PipettingRobot, 'dummy_pipetting_robot', hw['dummy_pipetting_robot']['options'],
                  {'motor': stage})
pump, rinse_pump, sensor = module(TestPump, 'pump'), module(TestPump, 'rinsing_pump'), module(TestFlowSensor, 'sensor')
lg = dcfg['logic']
valve = module(FluidicsValveLogic, 'fluidics_valve_logic', {}, {'valve': valve_hw})
flow_opts = {k: v for k, v in lg['fluidics_flow_logic']['options'].items()}
flow = module(FluidicsFlowLogic, 'fluidics_flow_logic', _short.module_options('fluidics_flow_logic', flow_opts),
              {'flow_sensor': sensor, 'fluidics_pump': pump, 'rinsing_pump': rinse_pump, 'valve_logic': valve})
robot = module(FluidicsRobotLogic, 'pipetting_robot_logic', _short.module_options('pipetting_robot_logic', lg['pipetting_robot_logic']['options']),
               {'robot': robot_hw})
gui = module(FluidicsGUI, 'fluidics_gui', {}, {'valve_logic': valve, 'fluidics_logic': flow,
                                               'positioning_logic': robot})
mw = gui._mw
check('dummy hardware, logic and fluidics GUI activate',
      all(m.module_state() == 'idle' for m in KEEP), [(m.module_name, m.module_state()) for m in KEEP])
ORIGIN = (0.0, 0.0, 1000.0)
robot.set_origin(ORIGIN)
app.processEvents()

# ------------------------------------------------------------------ spies on the logic calls
CALLS = []


def spy(obj, name):
    orig = getattr(obj, name)

    def wrapper(*a, **k):
        CALLS.append((monotonic(), f'{type(obj).__name__}.{name}', a, threading.current_thread().name))
        return orig(*a, **k)
    setattr(obj, name, wrapper)


for name in ('set_valve_position', 'set_valve_positions', 'disable_valve_positioning', 'enable_valve_positioning'):
    spy(valve, name)
for name in ('set_pressure', 'start_pressure_regulation_loop', 'stop_pressure_regulation_loop',
             'start_volume_measurement', 'stop_volume_measurement', 'disable_flowcontrol_actions',
             'enable_flowcontrol_actions'):
    spy(flow, name)
for name in ('start_move_to_target', 'disable_positioning_actions', 'enable_positioning_actions'):
    spy(robot, name)


def names(since=0.0, task_only=False):
    return [c[1].split('.')[1] for c in CALLS if c[0] >= since and (not task_only or c[3] == 'task')]


def gui_state():
    return {'robot': [mw.move_stage_Action.isEnabled(), mw.set_position1_Action.isEnabled(),
                      mw.go_to_position_Action.isEnabled()],
            'flow': [mw.set_pressure_Action.isEnabled(), mw.volume_measurement_Action.isEnabled(),
                     mw.rinsing_Action.isEnabled(), mw.start_flow_measurement_Action.isEnabled()],
            'valves': [cb.isEnabled() for cb in gui.valve_ComboBoxes]}


# ------------------------------------------------------------------ files
TMP = tempfile.mkdtemp()
EXAMPLE = _short.FLUIDICS_INJECTIONS
example = yaml.safe_load(open(EXAMPLE, encoding='utf-8'))


def files(injections, name):
    inj = os.path.join(TMP, name + '_injections.yml')
    yaml.safe_dump(injections, open(inj, 'w'))
    exp = os.path.join(TMP, name + '_experiment.yaml')
    yaml.safe_dump({'injections_path': inj}, open(exp, 'w'))
    return exp


def make_task(cls=fluidics.FluidicsDummyTask, **options):
    task = _short.shorten(cls())
    for k, v in options.items():
        setattr(task, k, v)
    task.connect_modules({'valve_logic': valve, 'flow_logic': flow, 'robot_logic': robot})
    if not any(isinstance(h, H) for h in task.log.handlers):
        task.log.addHandler(H())
    return task


def run(task, interrupt_when=None, timeout=300):
    """Run the task in its own thread while the main thread processes the logic events.
    interrupt_when(): checked every 20 ms; when True the task is interrupted (once).
    Returns (result, exception, interrupt time, end time, GUI samples)."""
    out = {}

    def target():
        try:
            out['result'] = task()
        except Exception as err:
            out['error'] = err
        out['end'] = monotonic()

    samples = []
    th = threading.Thread(target=target, daemon=True, name='task')
    t_int = None
    th.start()
    start = monotonic()
    while th.is_alive() and monotonic() - start < timeout:
        app.processEvents()
        samples.append((monotonic(), gui_state()))
        if interrupt_when is not None and t_int is None and interrupt_when():
            t_int = monotonic()
            task.interrupt()
        sleep(0.02)
    th.join(1)
    for _ in range(20):
        app.processEvents()
        sleep(0.01)
    return out.get('result'), out.get('error'), t_int, out.get('end'), samples


def task_logs(since):
    return [m for t, lvl, m in LOGS if t >= since]


def valve_positions():
    return {a: valve_hw.get_valve_position(a) for a in ('a', 'b', 'c')}



def message_boxes():
    return [w for w in app.topLevelWidgets() if isinstance(w, QtWidgets.QMessageBox) and w.isVisible()]


NEEDLE_MSG = fluidics_steps.FluidicsStepsMixin._NEEDLE_POSITION_MESSAGE


# ------------------------------------------------------------------ configs
def cfg(name):
    return yaml.safe_load(open(os.path.join(repo, 'custom_config', name), encoding='utf-8'))


raw = {n: open(os.path.join(repo, 'custom_config', n), encoding='utf-8').read()
       for n in ('Spinning_disk_config.cfg', 'RAMM_config.cfg', 'dummy_config.cfg')}
check('configs: no probe_valve_number left (commented or not) in Spinning_disk / RAMM / dummy',
      all('probe_valve_number' not in t for t in raw.values()))
check('Spinning_disk_config: injections_configurator_logic probe_valve_outlet 3; dummy: 7',
      cfg('Spinning_disk_config.cfg')['logic']['injections_configurator_logic']['options']['probe_valve_outlet'] == 3
      and lg['injections_configurator_logic']['options']['probe_valve_outlet'] == 7)
tasks_cfg = lg['task_runner']['options']['module_tasks']
check('dummy_config task entries: options of fluidics_dummy / him_dummy = user_config_path only',
      set(tasks_cfg['fluidics_dummy']['options']) == {'user_config_path'}
      and set(tasks_cfg['him_dummy']['options']) == {'user_config_path'})
tr_err = {}
for cls in (fluidics.FluidicsDummyTask, fluidics.FluidicsSDTask, fluidics.FluidicsRAMMTask):
    try:
        TaskRunnerLogic._validate_task_options(TaskRunnerLogic.__new__(TaskRunnerLogic), 'fluidics', cls,
                                               {'user_config_path': 'x', 'probe_valve_number': 3})
    except Exception as err:
        tr_err[cls.__name__] = err
check('a config still setting probe_valve_number is accepted by the task runner (qudi does not fail)', not tr_err, tr_err)


# ------------------------------------------------------------------ injections files written by the configurator logic
def configurator(outlet):
    opts = dict(lg['injections_configurator_logic']['options'], probe_valve_outlet=outlet)
    conf = module(InjectionsLogic, f'injections_configurator_{outlet}_{len(KEEP)}', opts,
                  {'valve': valve, 'robot': robot})
    # fresh lists for each instance (the lists start as class attributes of the logic)
    conf.delete_all_buffer()
    conf.delete_all_probes()
    conf.delete_hybr_all()
    conf.delete_photobl_all()
    return conf


def sequence(conf, with_probe=True, mode='next'):
    conf.add_buffer('SSC', 1)
    conf.add_buffer('Wash', 2)
    conf.add_probe('probe_A', 1)
    conf.add_probe('DAPI', 4)
    conf.set_probe_needle_mode(mode)
    probe = f'{PROBE_BUFFER_NAME}: {conf.probe_valve_number}'
    v = _short.INJECTION_UL
    for item in (('SSC: 1', v), (probe, v), None, (probe, v), (probe, v), ('Wash: 2', v)):
        if item is None:
            conf.add_incubation_step('Hybridization', _short.INCUBATION_S)
        elif with_probe or not item[0].startswith(PROBE_BUFFER_NAME):
            conf.add_injection_step('Hybridization', item[0], item[1], 200)


def experiment(inj_path, name):
    exp = os.path.join(TMP, name + '_experiment.yaml')
    yaml.safe_dump({'injections_path': inj_path}, open(exp, 'w'))
    return exp


def save(conf, name):
    path = os.path.join(TMP, name + '.yaml')
    conf.save_injections(path)
    return path


conf7 = configurator(7)
sequence(conf7)
inj7 = save(conf7, 'seq_probe7')
d7 = yaml.safe_load(open(inj7))
check('configurator (probe_valve_outlet 7) writes buffer Probe -> 7, steps with product "Probe"',
      d7['buffer'] == {1: 'SSC', 2: 'Wash', 7: 'Probe'}
      and [e['product'] for e in d7['hybridization list']] == ['SSC', 'Probe', None, 'Probe', 'Probe', 'Wash'], d7)

# same sequence re-saved on a configurator with probe_valve_outlet 3: load, Probe entry moved to 3, save
conf3 = configurator(3)
conf3.load_injections(inj7)
row7 = [k for k, (name, v) in enumerate(conf3.buffer_list_model.items) if name == PROBE_BUFFER_NAME][0]
conf3.delete_buffer(conf3.buffer_list_model.index(row7))
conf3.add_buffer(PROBE_BUFFER_NAME, 3)
inj3 = save(conf3, 'seq_probe3')
d3 = yaml.safe_load(open(inj3))
check('same sequence re-saved with Probe on 3: buffer Probe -> 3, same steps, same needle mode',
      d3['buffer'] == {1: 'SSC', 2: 'Wash', 3: 'Probe'} and d3['hybridization list'] == d7['hybridization list']
      and d3['probe_needle_mode'] == 'next', d3['buffer'])

conf_same = configurator(3)
sequence(conf_same, mode='same')
inj_same = save(conf_same, 'seq_probe3_same')

conf_np = configurator(7)
sequence(conf_np, with_probe=False)
dnp = yaml.safe_load(open(save(conf_np, 'tmp_np')))
del dnp['buffer'][7]  # the configurator always writes its Probe entry: removed to get a file without it
injnp = os.path.join(TMP, 'seq_no_probe.yaml')
yaml.safe_dump(dnp, open(injnp, 'w'))
check('file without a Probe entry: buffer steps + incubation only',
      dnp['buffer'] == {1: 'SSC', 2: 'Wash'} and [e['product'] for e in dnp['hybridization list']] == ['SSC', None, 'Wash'],
      dnp)


def run_case(inj_path, name, **options):
    task = make_task(user_config_path=experiment(inj_path, name), **options)
    CALLS.clear()
    t0 = monotonic()
    result, err, _, _, _ = run(task)
    logs = [(lvl, m) for t, lvl, m in LOGS if t >= t0]
    a_moves = [c[2][1] for c in CALLS if c[1].endswith('set_valve_position') and c[2][0] == 'a']
    needle = [c[2][0] for c in CALLS if c[1].endswith('start_move_to_target')]
    first_hw = min([c[0] for c in CALLS if c[1].split('.')[1] in ('set_valve_position', 'start_move_to_target',
                                                                  'disable_valve_positioning', 'set_pressure')] or [1e18])
    plan_t = [t for t, lvl, m in LOGS if t >= t0 and (m.startswith('Probe valve:') or m.startswith('No Probe entry'))]
    return task, result, err, logs, a_moves, needle, (plan_t[0] if plan_t else None, first_hw)


def msgs(logs):
    return [m for _, m in logs]


def warnings_of(logs, text):
    return [m for lvl, m in logs if lvl == logging.WARNING and text in m]


def show_plan(logs, label):
    lines = [m for m in msgs(logs) if m.startswith(('Fluidics sequence', 'Probe valve', 'No Probe', '  step'))]
    print(f'    plan ({label}):')
    for m in lines:
        print('      ' + m)
    return lines


# (1) Probe on 7, mode next
task, result, err, logs, a7, needle7, (t_plan, t_hw) = run_case(inj7, 'p7')
plan = show_plan(logs, 'Probe on 7')
check('(Probe on 7) runs; valve a: SSC 1, Probe 7 x3, Wash 2, cleanup 1',
      err is None and task.success and a7 == [1, 7, 7, 7, 2, 1], (err, a7))
check(f"(Probe on 7) plan line 'Probe valve: 7 (from {os.path.basename(inj7)}) - 3 probe injection(s) in the "
      f"hybridization list'", f'Probe valve: 7 (from {inj7}) - 3 probe injection(s) in the hybridization list' in plan)
check("(Probe on 7) one plan line per step, probe steps with valve and tube: 'step 2/6: inject Probe (valve 7, tube 1)', "
      "4/6 tube 2, 5/6 tube 3", len([m for m in plan if m.startswith('  step ')]) == 6
      and any(m.startswith('  step 2/6: inject Probe (valve 7, tube 1)') for m in plan)
      and any(m.startswith('  step 4/6: inject Probe (valve 7, tube 2)') for m in plan)
      and any(m.startswith('  step 5/6: inject Probe (valve 7, tube 3)') for m in plan)
      and any(m.startswith(f'  step 3/6: incubation {_short.INCUBATION_S:g} s') for m in plan))
check('(Probe on 7) plan logged before any hardware call', t_plan is not None and t_plan < t_hw, (t_plan, t_hw))
check("(Probe on 7, 'next') needle to the first tube, then to the next ones: moves 1, 2, 3; tubes used [1, 2, 3]",
      needle7 == [1, 2, 3] and result['tubes_used'] == [1, 2, 3], (needle7, result))
check('(Probe on 7) no probe_valve_number warning (option not set); only the existing "tube not listed" warnings '
      'for tubes 2 and 3', [m for lvl, m in logs if lvl >= logging.WARNING] == [
          'Tube 2 is used but not listed in the probes of the injections file.',
          'Tube 3 is used but not listed in the probes of the injections file.'],
      [m for lvl, m in logs if lvl >= logging.WARNING])

# (2) same sequence, Probe on 3
task, result, err, logs, a3, needle3, (t_plan, t_hw) = run_case(inj3, 'p3')
plan = show_plan(logs, 'Probe on 3')
check('(Probe on 3) runs; valve a: SSC 1, Probe 3 x3, Wash 2, cleanup 1',
      err is None and task.success and a3 == [1, 3, 3, 3, 2, 1], (err, a3))
check('(Probe on 3) plan: probe valve 3, steps with valve 3 and tubes 1, 2, 3',
      f'Probe valve: 3 (from {inj3}) - 3 probe injection(s) in the hybridization list' in plan
      and any(m.startswith('  step 5/6: inject Probe (valve 3, tube 3)') for m in plan) and t_plan < t_hw)
check('(Probe on 3) same needle behaviour as with Probe on 7 (moves 1, 2, 3)',
      needle3 == needle7 == [1, 2, 3] and result['tubes_used'] == [1, 2, 3], (needle3, needle7))

# (3) 'same' mode
task, result, err, logs, a, needle, _ = run_case(inj_same, 'p3_same')
plan = show_plan(logs, "Probe on 3, 'same'")
check("('same' mode) one tube: needle moved once to tube 1, every probe step from tube 1, valve 3",
      err is None and task.success and needle == [1] and result['tubes_used'] == [1] and a == [1, 3, 3, 3, 2, 1]
      and sum(1 for m in plan if 'inject Probe (valve 3, tube 1)' in m) == 3, (err, needle, result))

# (4) the SD situation: config still sets probe_valve_number 3, the file has Probe on 7
task, result, err, logs, a, needle, (t_plan, t_hw) = run_case(inj7, 'legacy_opt', probe_valve_number=3)
w = warnings_of(logs, 'probe_valve_number')
print('    warning:', w)
check('(config still sets probe_valve_number: 3, file Probe on 7) exactly one warning: option ignored, probe valve '
      'read from the injections file, value used 7', len(w) == 1 and 'ignored' in w[0] and 'injections file' in w[0]
      and 'Probe valve used: 7' in w[0] and '(3)' in w[0], w)
check('(same) task runs with valve 7, Probe steps recognised as probe injections (needle 1, 2, 3)',
      err is None and task.success and a == [1, 7, 7, 7, 2, 1] and needle == [1, 2, 3], (err, a, needle))
check('(same) the warning comes first, before the plan', msgs(logs).index(w[0]) < min(
      k for k, m in enumerate(msgs(logs)) if m.startswith('Probe valve:')))

# (5) no Probe entry, buffer steps only, no robot origin
robot.origin = None
task, result, err, logs, a, needle, (t_plan, t_hw) = run_case(injnp, 'noprobe')
plan = show_plan(logs, 'no Probe entry')
check('(no Probe entry, buffers only, no robot origin) runs: 3/3 steps, valve a 1, 2, cleanup 1',
      err is None and task.success and result['steps_done'] == 3 and a == [1, 2, 1], (err, result, a))
check("(same) plan: 'No Probe entry in the injections file - buffer injections only', before any hardware call",
      'No Probe entry in the injections file - buffer injections only' in plan and t_plan < t_hw)
check('(same) no needle move, no needle-position warning / message box, no origin required',
      needle == [] and NEEDLE_MSG not in msgs(logs) and message_boxes() == [], (needle, message_boxes()))
task, result, err, logs, a, needle, _ = run_case(injnp, 'noprobe_opt', probe_valve_number=7)
w = warnings_of(logs, 'probe_valve_number')
check('(no Probe entry + option still set) one warning stating that no probe valve is used, task runs',
      len(w) == 1 and 'Probe valve used: none (no Probe entry - buffer injections only)' in w[0]
      and err is None and task.success, (w, err))
robot.set_origin(ORIGIN)
app.processEvents()

# (6) a Probe entry used and no robot origin: needle-position abort as before
robot.origin = None
task, result, err, logs, a, needle, _ = run_case(inj3, 'p3_noorigin')
check('(Probe on 3 used, no robot origin) needle-position warning, aborted before any hardware call',
      err is None and result == {'aborted': 'needle position not initialised', 'steps_done': 0} and a == [] and needle == []
      and NEEDLE_MSG in msgs(logs), (err, result))
for b in message_boxes():
    b.close()
robot.set_origin(ORIGIN)
app.processEvents()

# (7) option check: user_config_path still required, probe_valve_number not
task = make_task()
try:
    task._check_options()
    msg = ''
except RuntimeError as err:
    msg = str(err)
check('_check_options: user_config_path still required; probe_valve_number not required',
      'user_config_path not set' in msg and make_task(user_config_path='x')._check_options() is None, msg)

print(f'\n{sum(ok for _, ok in results)}/{len(results)} passed', flush=True)
for m in list(KEEP)[::-1]:
    try:
        m.module_state.deactivate()
    except Exception:
        pass
os._exit(0 if all(ok for _, ok in results) else 1)
