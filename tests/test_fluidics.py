"""Fluidics task (qudi.tasks.fluidics) with dummy hardware.

Usage: QT_QPA_PLATFORM=offscreen python tests/test_fluidics.py [<repo_root>] [quick]
Real DummyValve, DummyMultiAxisStage + PipettingRobot, FluidicsValveLogic, FluidicsFlowLogic,
FluidicsRobotLogic and FluidicsGUI; pump / flow sensor: test modules (~200 ul/min). The task runs in its
own thread, the logic modules in the main thread (event loop), as in qudi.
Sections:
  - task runner options and dummy_config entry, sequence (modes 'next' / 'same'), interrupt, validation
    errors, valve / timeout errors, needle position missing (warning box);
  - probe valve read from the injections file (files written by the injections configurator logic).
Short settings and test data: tests/_short.py, tests/data/fluidics_injections.yml (docs/TESTING.md).
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


# --- fluidics task: options, sequence, interrupt, validation, needle position ---
# ------------------------------------------------------------------ options accepted by the task runner
allowed = TaskRunnerLogic._option_attributes(fluidics.FluidicsDummyTask)
check('task runner accepts option user_config_path (and the obsolete probe_valve_number, ignored)',
      {'user_config_path', 'probe_valve_number'} <= set(allowed), allowed)
check('dummy_config.cfg entry: FluidicsDummyTask, connectors, options',
      lg['task_runner']['options']['module_tasks']['fluidics_dummy'] == {
          'module.Class': 'qudi.tasks.fluidics.FluidicsDummyTask',
          'connect': {'valve_logic': 'fluidics_valve_logic', 'flow_logic': 'fluidics_flow_logic',
                      'robot_logic': 'pipetting_robot_logic'},
          'options': {'user_config_path': '/home/jb/qudi/qudi_task_config_files/fluidics_task.yaml'}})
check('subclass valve layouts', fluidics.FluidicsRAMMTask.cleanup_valve_positions == {'c': 1, 'b': 1, 'a': 1}
      and list(fluidics.FluidicsRAMMTask.cleanup_valve_positions) == ['c', 'b', 'a']
      and fluidics.FluidicsSDTask.start_valve_positions == {'b': 1}
      and list(fluidics.FluidicsSDTask.cleanup_valve_positions) == ['b', 'a']
      and issubclass(fluidics.FluidicsDummyTask, fluidics.FluidicsRAMMTask))


# ------------------------------------------------------------------ (1) full run, mode next and same
def full_run(mode):
    inj = copy.deepcopy(example)
    inj['probe_needle_mode'] = mode
    task = make_task(user_config_path=files(inj, mode))
    t0 = monotonic()
    CALLS.clear()
    result, err, _, t_end, samples = run(task)
    return task, result, err, t0, t_end, samples


arrivals = []
robot.sigStageMovedToTarget.connect(lambda pos, target: arrivals.append((monotonic(), target)))

for mode, tubes in (('next', [1, 2]), ('same', [1])):
    arrivals.clear()
    task, result, err, t0, t_end, samples = full_run(mode)
    logs = task_logs(t0)
    check(f'({mode}) full run succeeds', err is None and task.success, err)
    check(f'({mode}) result: 5/5 steps, needle mode, tubes used {tubes}',
          result == {'steps_done': 5, 'steps_total': 5, 'probe_needle_mode': mode, 'tubes_used': tubes}, result)
    moves = [c[2][0] for c in CALLS if c[1].endswith('start_move_to_target')]
    expected_moves = [1, 2] if mode == 'next' else [1]
    check(f'({mode}) needle moves {expected_moves}', moves == expected_moves, moves)
    check(f'({mode}) robot arrived at {expected_moves}', [t for _, t in arrivals] == expected_moves, arrivals)
    check(f'({mode}) plan logged: one line per step + needle mode',
          any(f"needle mode '{mode}'" in m for m in logs)
          and sum(1 for m in logs if m.startswith(tuple(f'  step {i}/5: ' for i in range(1, 6)))) == 5, logs[:8])
    check(f'({mode}) "Step i/5" logged for each step',
          all(any(m.startswith(f'Step {i}/5') for m in logs) for i in range(1, 6)))
    vols = [m for m in logs if 'µl injected' in m]
    check(f'({mode}) 4 injections, injected volume logged (>= {_short.INJECTION_UL} µl each)',
          len(vols) == 4 and all(float(m.split(': ')[1].split(' ')[0]) >= _short.INJECTION_UL for m in vols), vols)
    sv = [(c[2][0], c[2][1]) for c in CALLS if c[1].endswith('set_valve_position')]
    # expected valve sequence (RAMM layout)
    exp = [('c', 1), ('c', 2)]                     # 7. needle to tube 1 (needle_move / needle_moved)
    exp += [('b', 2), ('c', 2)]                    # 8. start positions
    exp += [('a', 1)]                              # step 1 SSC
    exp += [('a', 7)]                              # step 2 Probe (first probe injection, no move)
    exp += [('c', 1), ('c', 2)]                    # step 3 incubation
    exp += [('a', 7)]                              # step 4 Probe
    if mode == 'next':
        exp += [('c', 1), ('c', 2)]                # needle to tube 2
    exp += [('a', 2)]                              # step 5 Wash buffer
    exp += [('c', 1), ('b', 1), ('a', 1)]          # cleanup
    check(f'({mode}) valve sequence (RAMM layout, cleanup c, b, a)', sv == exp, sv)
    inj = [n for n in names(task_only=True) if n in ('set_pressure', 'start_pressure_regulation_loop', 'start_volume_measurement',
                                       'stop_pressure_regulation_loop')]
    one = ['set_pressure', 'start_pressure_regulation_loop', 'start_volume_measurement',
           'stop_pressure_regulation_loop', 'set_pressure']
    check(f'({mode}) each injection (task calls): set_pressure(0), start regulation, start volume, stop regulation, '
          f'set_pressure(0); cleanup: stop regulation, set_pressure(0)',
          inj == ['stop_pressure_regulation_loop'] + one * 4 + ['stop_pressure_regulation_loop', 'set_pressure'],
          inj)  # first stop: from disable_flowcontrol_actions() (GUI lock)
    check(f'({mode}) end: pressure 0, regulation and volume count stopped, valves c=1 b=1 a=1',
          pump.output[0] == 0.0 and not flow.regulating and not flow.measuring_volume
          and valve_positions() == {'a': 1, 'b': 1, 'c': 1}, (pump.output, valve_positions()))
    during = [s for t, s in samples if t0 + 0.5 < t < (t_end or t0) - 0.2]
    locked = [s for s in during if not any(s['robot']) and not any(s['flow']) and not any(s['valves'])]
    check(f'({mode}) GUIs locked during the run (valves, flow, robot)', len(locked) >= 0.9 * len(during),
          f'{len(locked)}/{len(during)}')
    # robot buttons after each needle move: re-enabled by the GUI, then disabled again by the task
    after_moves = all(not any(s['robot']) for t, s in samples for ta, _ in arrivals if ta + 0.3 < t < ta + 1.0)
    re_enabled = [t for t, s in samples if any(s['robot']) and t0 + 0.5 < t < (t_end or t0) - 0.2]
    check(f'({mode}) robot buttons disabled again after each needle move (GUI samples every 20 ms: none enabled)',
          after_moves and not re_enabled, f'enabled samples: {len(re_enabled)}')
    final = samples[-1][1] if samples else None
    app.processEvents()
    check(f'({mode}) GUIs unlocked at the end', all(gui_state()['flow']) and all(gui_state()['valves'])
          and all(gui_state()['robot']), gui_state())
    print(f'    ({mode}) run time {t_end - t0:.1f} s', flush=True)

# ------------------------------------------------------------------ (2) interrupts
def started(kind):
    def cond():
        if kind == 'injection':
            return flow.measuring_volume and flow.total_volume > 0
        step3 = [t for t, _, m in LOGS if m.startswith('Step 3/5') and t > T_START[0]]
        # incubation wait running (after the valve move), before its end (INCUBATION_S)
        return bool(step3) and monotonic() - step3[0] > 0.4 * _short.INCUBATION_S
    return cond


T_START = [0.0]
for kind in ('injection', 'incubation'):
    T_START[0] = monotonic()
    inj = copy.deepcopy(example)
    task = make_task(user_config_path=files(inj, 'int_' + kind))
    CALLS.clear()
    t0 = monotonic()
    result, err, t_int, t_end, samples = run(task, interrupt_when=started(kind))
    first_cleanup = next((c[0] for c in CALLS if c[0] >= (t_int or 0) and c[1].endswith('stop_pressure_regulation_loop')), None)
    react = (first_cleanup - t_int) if (first_cleanup and t_int) else None
    check(f'(interrupt {kind}) interrupted, task not successful', t_int is not None and not task.success, err)
    check(f'(interrupt {kind}) stops within ~1 s (cleanup starts {react if react is None else round(react, 2)} s after the interrupt)',
          react is not None and react < 1.0)
    check(f'(interrupt {kind}) cleanup: pressure 0, regulation + volume stopped, valves c=1 b=1 a=1',
          pump.output[0] == 0.0 and not flow.regulating and not flow.measuring_volume
          and valve_positions() == {'a': 1, 'b': 1, 'c': 1}, (pump.output, valve_positions(), flow.regulating))
    check(f'(interrupt {kind}) GUIs unlocked', all(gui_state()['flow']) and all(gui_state()['valves'])
          and all(gui_state()['robot']), gui_state())
    check(f'(interrupt {kind}) no error logged by cleanup', not any('Cleanup:' in m for m in task_logs(t0)),
          [m for m in task_logs(t0) if 'Cleanup' in m])
    if kind == 'incubation':
        check('(interrupt incubation) interrupted while incubating (valve c at 1, 2 injections done)',
              sum(1 for c in CALLS if c[1].endswith('start_volume_measurement') and c[0] < t_int) == 2)


# ------------------------------------------------------------------ (3) validation before any hardware call
def expect_failure(label, injections, options=None, origin=ORIGIN, fragments=()):
    robot.origin = None if origin is None else robot.origin
    if origin is not None:
        robot.set_origin(origin)
    task = make_task(**(options or {'user_config_path': files(injections, label)}))
    CALLS.clear()
    result, err, _, _, _ = run(task)
    msg = str(err)
    check(f'(validation {label}) task stops with one error listing every problem',
          err is not None and all(f in msg for f in fragments), msg)
    hw_calls = [n for n in names() if n not in ('stop_pressure_regulation_loop', 'stop_volume_measurement')]
    check(f'(validation {label}) no hardware call, GUIs not locked', hw_calls == [], hw_calls)
    return msg


bad = copy.deepcopy(example)
bad['hybridization list'][0]['product'] = 'Unknown buffer'
bad['hybridization list'][3]['volume'] = 0
bad['hybridization list'][2]['time'] = -5
msg = expect_failure('unknown product', bad,
                     fragments=("product 'Unknown buffer' is not in the buffer list",
                                'volume must be > 0', 'time must be >= 0', '3 problem(s)'))
print('    message:', msg.replace('\n', ' | '))
robot.set_origin(ORIGIN)
noprobes = copy.deepcopy(example)
noprobes['probes'] = {}
expect_failure('probe valve used without probes', noprobes, fragments=('probe list is empty',))
badmode = copy.deepcopy(example)
badmode['probe_needle_mode'] = 'sideways'
expect_failure('invalid needle mode', badmode, fragments=("probe_needle_mode 'sideways'",))
nomode = copy.deepcopy(example)
nomode.pop('probe_needle_mode')
expect_failure('missing user_config_path', example, options={'user_config_path': None},
               fragments=('user_config_path not set',))
missing_exp = os.path.join(TMP, 'does_not_exist.yaml')
expect_failure('missing experiment file', example, options={'user_config_path': missing_exp},
               fragments=(missing_exp,))
exp_bad_inj = os.path.join(TMP, 'exp_bad_inj.yaml')
yaml.safe_dump({'injections_path': '/nowhere/injections.yml'}, open(exp_bad_inj, 'w'))
expect_failure('missing injections file', example, options={'user_config_path': exp_bad_inj},
               fragments=('/nowhere/injections.yml',))

# missing probe_needle_mode -> next (plan only: stopped right after the plan)
task = make_task(user_config_path=files(nomode, 'nomode'))
CALLS.clear()
t0 = monotonic()
result, err, _, _, _ = run(task, interrupt_when=lambda: any("needle mode" in m for m in task_logs(t0)))
check("(file without probe_needle_mode) plan uses 'next'", any("needle mode 'next'" in m for m in task_logs(t0)))

# ------------------------------------------------------------------ (4) valve failure -> raise naming address and position
orig_set = valve_hw.set_valve_position
task = make_task(user_config_path=files(example, 'valvefail'))
valve_hw.set_valve_position = lambda address, pos: orig_set(address, 1 if (address, pos) == ('a', 2) else pos)
t0 = monotonic()
result, err, _, _, _ = run(task)
valve_hw.set_valve_position = orig_set
check('(valve failure) valve a refuses position 2 -> task raises naming address and position',
      err is not None and 'Valve a did not reach position 2' in str(err), err)
check('(valve failure) cleanup still ran (valves c=1 b=1 a=1, GUIs unlocked)',
      valve_positions() == {'a': 1, 'b': 1, 'c': 1} and all(gui_state()['valves']))

# ------------------------------------------------------------------ (5) injection timeout
task = make_task(user_config_path=files(example, 'timeout'))
task.injection_timeout_factor = 0.0
task.injection_timeout_margin_s = 2.0
sensor.mean_flow = 0
t0 = monotonic()
result, err, _, t_end, _ = run(task)
sensor.mean_flow = 200
check('(timeout) no flow -> "volume not reached - check the line" after the timeout',
      err is not None and 'volume not reached - check the line' in str(err) and 'after 2 s' in str(err), err)
check('(timeout) cleanup: pressure 0, valves c=1 b=1 a=1', pump.output[0] == 0.0
      and valve_positions() == {'a': 1, 'b': 1, 'c': 1})

# ------------------------------------------------------------------ (6) needle position (robot origin) not defined
from qudi.tasks.common import fluidics_steps, popups  # noqa: E402


def message_boxes():
    return [w for w in app.topLevelWidgets() if isinstance(w, QtWidgets.QMessageBox) and w.isVisible()]


EXPECTED = fluidics_steps.FluidicsStepsMixin._NEEDLE_POSITION_MESSAGE
robot.origin = None
task = make_task(user_config_path=files(example, 'noorigin'))
CALLS.clear()
t0 = monotonic()
result, err, _, _, _ = run(task)
logs = [(lvl, m) for t, lvl, m in LOGS if t >= t0]
check('(no needle position) task ends without exception, result marks the abort',
      err is None and task.success and result == {'aborted': 'needle position not initialised', 'steps_done': 0},
      (err, result))
check('(no needle position) message logged as a warning, no error logged',
      (logging.WARNING, EXPECTED) in logs and not any(lvl >= logging.ERROR for lvl, _ in logs), logs)
check('(no needle position) no logic call (no hardware, GUIs not locked)', names(t0) == [], names(t0))
boxes = message_boxes()
check('(no needle position) one non-modal warning box "Needle position not defined" with the message, created in '
      'the GUI thread',
      len(boxes) == 1 and boxes[0].text() == EXPECTED and not boxes[0].isModal()
      and boxes[0].windowTitle() == 'Needle position not defined'
      and boxes[0].icon() == QtWidgets.QMessageBox.Warning and boxes[0].thread() is app.thread(),
      [(b.text(), b.isModal()) for b in boxes])
check('(no needle position) GUIs still enabled', all(gui_state()['robot']) and all(gui_state()['valves']), gui_state())
for b in boxes:
    b.close()
app.processEvents()
check('(no needle position) closing the box releases it', message_boxes() == [] and popups._warning_popup._boxes == [])
check('(no needle position) message names the Fluidics GUI and "Set position 1"',
      'Fluidics GUI' in EXPECTED and '"Set position 1"' in EXPECTED and mw.set_position1_Action.text() == 'Set position 1',
      mw.set_position1_Action.text())

# without probe injection the origin is not needed: normal run
buffers_only = copy.deepcopy(example)
buffers_only['hybridization list'] = [e for e in example['hybridization list'] if e.get('product') != 'Probe']
task = make_task(user_config_path=files(buffers_only, 'buffers_only'))
CALLS.clear()
t0 = monotonic()
result, err, _, _, _ = run(task)
check('(no needle position, buffers only) normal run, no warning, no box',
      err is None and result and result.get('steps_done') == len(buffers_only['hybridization list']) > 0
      and EXPECTED not in task_logs(t0) and message_boxes() == [] and 'start_move_to_target' not in names(t0),
      (err, result, len(buffers_only['hybridization list'])))
robot.set_origin(ORIGIN)
app.processEvents()


# --- probe valve read from the injections file ---

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
check('dummy_config task entries: options of fluidics_dummy = user_config_path only; him_dummy = user_config_path '
      'and metadata_template',
      set(tasks_cfg['fluidics_dummy']['options']) == {'user_config_path'}
      and set(tasks_cfg['him_dummy']['options']) == {'user_config_path', 'metadata_template'})
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

# --- injections configurator: needle rinsing time and time estimates ---
from qudi.logic import injections_configurator_logic as icl  # noqa: E402
from qudi.gui.injections_setup.injections_gui import InjectionsGUI  # noqa: E402

# ------------------------------------------------------------------ estimate functions (no Qt)
check('estimate_sequence_time: 2000 ul at 250 ul/min -> 480 s; incubation 600 s -> 600 s; both -> 1080 s',
      icl.estimate_sequence_time([('Hybridization', 'SSC: 1', 2000, 250, None)]) == 480.0
      and icl.estimate_sequence_time([('Hybridization', None, None, None, 600)]) == 600.0
      and icl.estimate_sequence_time([('Hybridization', 'SSC: 1', 2000, 250, None),
                                      ('Hybridization', None, None, None, 600)]) == 1080.0)
mixed = [('Hybridization', 'SSC: 1', 2000, 250, None), ('Hybridization', 'Wash: 2', 500, None, None),
         ('Hybridization', 'Wash: 2', 0, 200, None), ('Hybridization', None, None, None, 60)]
check('step without flowrate (and step with volume 0) ignored (0 s) and reported: steps 2 and 3; file entries (dicts) '
      'accepted',
      icl.estimate_sequence_time(mixed) == 540.0 and icl.ignored_sequence_steps(mixed) == [2, 3]
      and icl.estimate_sequence_time([{'product': 'SSC', 'volume': 2000, 'flowrate': 250, 'time': None}]) == 480.0
      and icl.ignored_sequence_steps([('Hybridization', 'SSC: 1', 2000, 250, None)]) == [],
      (icl.estimate_sequence_time(mixed), icl.ignored_sequence_steps(mixed)))
check('format_minutes: 480 s -> "8.0 min", 90 s -> "1.5 min", 0 -> "0.0 min"',
      (icl.format_minutes(480), icl.format_minutes(90), icl.format_minutes(0)) == ('8.0 min', '1.5 min', '0.0 min'),
      (icl.format_minutes(480), icl.format_minutes(90), icl.format_minutes(0)))
check('format_hours_minutes: 4320 s -> "1 h 12 min", 600 s -> "10 min", 3510 s -> "59 min" (half a minute rounds up), '
      '7200 s -> "2 h 0 min"',
      (icl.format_hours_minutes(4320), icl.format_hours_minutes(600), icl.format_hours_minutes(3510),
       icl.format_hours_minutes(7200)) == ('1 h 12 min', '10 min', '59 min', '2 h 0 min'),
      (icl.format_hours_minutes(4320), icl.format_hours_minutes(600), icl.format_hours_minutes(3510)))
est3 = icl.experiment_time_estimates([('Hybridization', 'SSC: 1', 2000, 250, None)],
                                     [('Photobleaching', None, None, None, 600)], 30, 3)
check('experiment_time_estimates: hybridization 480 + photobleaching 600 + rinse 30 = 1110 s per cycle; 3 probes -> '
      '3330 s', est3['hybridization_s'] == 480 and est3['photobleaching_s'] == 600 and est3['rinsing_s'] == 30
      and est3['cycle_s'] == 1110 and est3['number_of_probes'] == 3 and est3['experiment_s'] == 3330
      and est3['hybridization_ignored'] == [] and est3['photobleaching_ignored'] == [], est3)

# ------------------------------------------------------------------ logic: rinsing time, save / load
conf_rt = configurator(7)
rt_signals, est_signals = [], []
conf_rt.sigRinsingTimeChanged.connect(rt_signals.append)
conf_rt.sigTimeEstimatesChanged.connect(lambda: est_signals.append(1))
check(f'needle_rinsing_time: default {icl.DEFAULT_NEEDLE_RINSING_TIME_S} s, range 0..600',
      conf_rt.needle_rinsing_time == icl.DEFAULT_NEEDLE_RINSING_TIME_S == 30
      and icl.NEEDLE_RINSING_TIME_RANGE_S == (0, 600), conf_rt.needle_rinsing_time)
n0 = len(LOGS)
refused = [conf_rt.set_needle_rinsing_time(v) for v in (-1, 601, 2.5, True)]
check('set_needle_rinsing_time refuses -1, 601, 2.5 and True (error logged, value and signals unchanged)',
      refused == [False] * 4 and conf_rt.needle_rinsing_time == 30 and rt_signals == []
      and len({m for _, lvl, m in LOGS[n0:] if lvl == logging.ERROR and 'needle rinsing time' in m}) == 4, refused)
ok_rt = conf_rt.set_needle_rinsing_time(45)
same_rt = conf_rt.set_needle_rinsing_time(45)
check('set_needle_rinsing_time(45): accepted, sigRinsingTimeChanged(45) once (not again for the same value), '
      'sigTimeEstimatesChanged emitted',
      ok_rt and same_rt and conf_rt.needle_rinsing_time == 45 and rt_signals == [45] and est_signals,
      (rt_signals, est_signals))
sequence(conf_rt)
inj_rt = save(conf_rt, 'seq_rinse45')
saved_rt = yaml.safe_load(open(inj_rt))
conf_rt2 = configurator(7)
rt2 = []
conf_rt2.sigRinsingTimeChanged.connect(rt2.append)
conf_rt2.load_injections(inj_rt)
check('save writes the top-level key needle_rinsing_time (45); load restores it and emits sigRinsingTimeChanged(45)',
      saved_rt.get('needle_rinsing_time') == 45 and conf_rt2.needle_rinsing_time == 45 and rt2 == [45],
      (saved_rt.get('needle_rinsing_time'), conf_rt2.needle_rinsing_time, rt2))
old_file = dict(saved_rt)
old_file.pop('needle_rinsing_time')
old_path = os.path.join(TMP, 'seq_no_rinse_key.yaml')
yaml.safe_dump(old_file, open(old_path, 'w'))
conf_rt2.set_needle_rinsing_time(5)
n0 = len(LOGS)
conf_rt2.load_injections(old_path)
check('file without needle_rinsing_time loads with 30 s and an info line',
      conf_rt2.needle_rinsing_time == 30
      and any(lvl == logging.INFO and 'no needle_rinsing_time' in m and '30 s' in m for _, lvl, m in LOGS[n0:]),
      (conf_rt2.needle_rinsing_time, [m for _, _, m in LOGS[n0:]]))
est_load = []
conf_rt2.sigTimeEstimatesChanged.connect(lambda: est_load.append(1))
conf_rt2.load_injections(inj_rt)
est = conf_rt2.time_estimates()
v = _short.INJECTION_UL
expected_hyb = 5 * v / 200 * 60 + _short.INCUBATION_S  # sequence(): 5 injections at 200 ul/min + 1 incubation
check(f'time_estimates after load: hybridization {expected_hyb:g} s (5 injections + incubation), photobleaching 0, '
      f'cycle = + rinse 45 s, 2 probes; sigTimeEstimatesChanged emitted by the load',
      abs(est['hybridization_s'] - expected_hyb) < 1e-9 and est['photobleaching_s'] == 0
      and abs(est['cycle_s'] - (expected_hyb + 45)) < 1e-9 and est['number_of_probes'] == 2
      and abs(est['experiment_s'] - 2 * (expected_hyb + 45)) < 1e-9 and est_load, est)

# ------------------------------------------------------------------ GUI: spin box and read-only time estimates
conf_gui = configurator(7)
inj_gui = module(InjectionsGUI, f'injections_gui_{len(KEEP)}', {}, {'injections_logic': conf_gui})
gmw = inj_gui._mw
app.processEvents()
spin = gmw.rinsing_time_spinBox
check('rinsing_time_spinBox: range 0..600, suffix " s", tooltip, value of the logic (30)',
      (spin.minimum(), spin.maximum()) == (0, 600) and spin.suffix() == ' s'
      and spin.toolTip() == 'Needle rinsing after each Hi-M cycle (0 = no rinse)' and spin.value() == 30,
      (spin.minimum(), spin.maximum(), spin.suffix(), spin.value()))
edits = (gmw.hybridization_time_lineEdit, gmw.photobleaching_time_lineEdit, gmw.injection_time_lineEdit)
check('time line edits read-only, in minutes; empty sequence: 0.0, 0.0, 0.5 min (rinse 30 s only)',
      all(e.isReadOnly() for e in edits) and [e.text() for e in edits] == ['0.0 min', '0.0 min', '0.5 min'],
      [e.text() for e in edits])
conf_gui.add_probe('RT1', 1)
conf_gui.add_probe('RT2', 2)
conf_gui.add_probe('RT3', 3)
conf_gui.add_injection_step('Hybridization', 'SSC: 1', 2000, 250)
conf_gui.add_incubation_step('Photobleaching', 600)
app.processEvents()
tip = gmw.injection_time_lineEdit.toolTip()
check('after adding steps: hybridization 8.0 min (480 s), photobleaching 10.0 min (600 s), per cycle 18.5 min '
      '(1110 s); tooltip: per cycle 18.5 min, whole experiment (3 probes) 56 min (3330 s) and the minimum-time note',
      [e.text() for e in edits] == ['8.0 min', '10.0 min', '18.5 min']
      and tip.startswith('Per cycle: hybridization + photobleaching + needle rinse = 18.5 min. Whole experiment '
                         '(3 probes): 56 min. Minimum times: valve switching, needle moves and the flow regulation '
                         'ramp are not included.'), ([e.text() for e in edits], tip))
spin.setValue(90)
app.processEvents()
check('spin box 90 s (still in seconds) -> logic 90, per cycle 19.5 min (1170 s), whole experiment 59 min (3510 s)',
      conf_gui.needle_rinsing_time == 90 and spin.suffix() == ' s' and gmw.injection_time_lineEdit.text() == '19.5 min'
      and 'Whole experiment (3 probes): 59 min.' in gmw.injection_time_lineEdit.toolTip(),
      (conf_gui.needle_rinsing_time, gmw.injection_time_lineEdit.text()))
conf_gui.set_needle_rinsing_time(10)
app.processEvents()
check('logic set_needle_rinsing_time(10) -> spin box 10, per cycle 18.2 min (1090 s)',
      spin.value() == 10 and gmw.injection_time_lineEdit.text() == '18.2 min', (spin.value(), gmw.injection_time_lineEdit.text()))
conf_gui.add_injection_step('Hybridization', 'SSC: 1', 500, 0)
app.processEvents()
check("step without flowrate: '*' after the hybridization and per-cycle values, ignored step named in the tooltips",
      gmw.hybridization_time_lineEdit.text() == '8.0 min*' and gmw.injection_time_lineEdit.text() == '18.2 min*'
      and gmw.photobleaching_time_lineEdit.text() == '10.0 min'
      and 'Ignored step(s)' in gmw.hybridization_time_lineEdit.toolTip() and '2' in gmw.hybridization_time_lineEdit.toolTip()
      and 'hybridization 2' in gmw.injection_time_lineEdit.toolTip(),
      ([e.text() for e in edits], gmw.injection_time_lineEdit.toolTip()))
conf_gui.load_injections(inj_rt)
app.processEvents()
check('load (rinse 45, 2 probes) -> spin box 45 and the estimates of the file',
      spin.value() == 45 and gmw.injection_time_lineEdit.text() == icl.format_minutes(expected_hyb + 45)
      and '(2 probes)' in gmw.injection_time_lineEdit.toolTip(), (spin.value(), gmw.injection_time_lineEdit.text()))
conf_gui.delete_hybr_all()
app.processEvents()
check('delete the hybridization list -> hybridization 0, per cycle = rinse only',
      gmw.hybridization_time_lineEdit.text() == '0.0 min' and gmw.injection_time_lineEdit.text() == '0.8 min',
      [e.text() for e in edits])
check('labels of the .ui: rinsing time (s), hybridization time (min)',
      gmw.rinsing_time_label.text() == 'rinsing time (s)' and gmw.hybridization_time_label.text() == 'hybridization time (min)',
      (gmw.rinsing_time_label.text(), gmw.hybridization_time_label.text()))
inj_gui._mw.hide()

print(f'\n{sum(ok for _, ok in results)}/{len(results)} passed', flush=True)
for m in list(KEEP)[::-1]:
    try:
        m.module_state.deactivate()
    except Exception:
        pass
os._exit(0 if all(ok for _, ok in results) else 1)
