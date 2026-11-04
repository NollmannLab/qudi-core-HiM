"""Hi-M task (qudi.tasks.him) on the dummy setup, the SD task with a fake ZEN, the RAMM placeholder.

Usage: QT_QPA_PLATFORM=offscreen python tests/test_him.py [<repo_root>] [quick | metadata | sd_z_planes ...]
(quick: without the interrupt / error / SD / RAMM cases; metadata, sd_z_planes: only these blocks.)
Real modules of dummy_config.cfg: fluidics (dummy valve, DaqPumpController pumps, DummyFlowSensor,
FluidicsFlowLogic, pipetting robot on the dummy stage), roi_logic and laser_control_logic. The task
runs in its own thread, the modules in the main thread (event loop). Logic calls are recorded.
Sections:
  - run files: experiment_config.yaml and metadata.yml in the run folder;
  - number of z planes: not used by the SD task, still required by the dummy;
  - Hi-M cycles: full run, progress, interrupt, errors, needle position, needle modes, SD (fake ZEN),
    RAMM placeholder;
  - probe valve read from the injections file (plan, needle, valve, obsolete option).
Short settings and test data: tests/_short.py, tests/data/ (him_injections.yml, rois_2.json), docs/TESTING.md.
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
check('dummy_config: him_dummy is HiMDummyTask, options user_config_path and metadata_template (a template of the '
      'repository), and the 5 connectors',
      ENTRY['module.Class'] == 'qudi.tasks.him.HiMDummyTask'
      and set(ENTRY['options']) == {'user_config_path', 'metadata_template'}
      and os.path.isfile(_short.local_options(repo, ENTRY['options'])['metadata_template'])
      and set(ENTRY['connect']) == {'valve_logic', 'flow_logic', 'robot_logic', 'roi_logic', 'laser_logic'})
MODS = {'valve_logic': valve, 'flow_logic': flow, 'robot_logic': robot, 'roi_logic': roi, 'laser_logic': laser}


def make_task(cls=him.HiMDummyTask, user_config_path=None, **attrs):
    task = cls()
    for k, v in _short.local_options(repo, ENTRY['options']).items():
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
ONLY = set(sys.argv[1:]) & {'metadata', 'sd_z_planes'}  # run only these blocks, then stop


def selected(block):
    return not ONLY or block in ONLY


# --- run files: experiment copy and metadata.yml ---
if selected('metadata'):
    # Hi-M dummy, 1 probe, 2 ROIs, metadata_template of dummy_config.cfg (template of the repository)
    meta_inj = copy.deepcopy(EXAMPLE)
    meta_inj['probes'] = {1: 'RT1'}
    meta_exp = files(meta_inj, 'metadata')
    task = make_task(user_config_path=meta_exp)
    t0 = monotonic()
    result, err, _, _ = run(task)
    run_folder = result['directory'] if result else ''
    meta_path = os.path.join(run_folder, 'metadata.yml')
    meta = yaml.safe_load(open(meta_path, encoding='utf-8')) if os.path.exists(meta_path) else None
    template = yaml.safe_load(open(task.metadata_template, encoding='utf-8'))
    section = lambda m, name: {k: v for item in m[name] for k, v in item.items()}  # noqa: E731
    acq = section(meta, 'Acquisition') if meta else {}
    fluidics_meta = section(meta, 'Fluidics') if meta else {}
    check('(run files) 1 cycle done; experiment_config.yaml byte-identical to the experiment file',
          err is None and result and result['cycles_done'] == 1
          and open(os.path.join(run_folder, 'experiment_config.yaml'), 'rb').read() == open(meta_exp, 'rb').read(),
          (err, result))
    check('(run files) metadata.yml: Fluidics hybridization / photobleaching = the lists of the injections file',
          fluidics_meta.get('hybridization') == meta_inj['hybridization list']
          and fluidics_meta.get('photobleaching') == meta_inj['photobleaching list'], fluidics_meta)
    check(f'(run files) metadata.yml: Time, sample name, laser lines / powers, 5 z planes, the {N} ROIs with their '
          f'positions; other sections as in the template',
          meta is not None and meta['Time'] and acq['sample_name'] == 'Mysample' and acq['laser_lines'] == [488, 561]
          and acq['laser_power_(%)'] == [50.0, 80.0] and acq['number_z_planes'] == 5
          and acq['roi_list_(xyz)'] == [{n: [float(v) for v in roi.get_roi_position(n)]} for n in NAMES]
          and list(meta) == list(template) and meta['Camera'] == template['Camera'], acq)
    him_params = yaml.safe_load(open(os.path.join(run_folder, 'HiM_parameters.yml'))) if run_folder else {}
    check('(run files) HiM_parameters.yml as before (global, fluidic, imaging parameters, ROIs) and movie_name.txt',
          list(him_params) == ['1- global parameters', '2- fluidic parameters', '3- imaging parameters', '4- ROIs']
          and him_params['2- fluidic parameters']['probes'] == {1: 'RT1'} and list(him_params['4- ROIs']) == NAMES
          and open(os.path.join(run_folder, 'movie_name.txt')).read().split()
          == [f'scan_001_RT1_{n[4:]}_ROI' for n in NAMES], him_params)
    end_state_ok('run files', t0)

# --- number of z planes: not used by the SD task, still required by the dummy ---
if selected('sd_z_planes'):
    class ZenTrigger:  # fake TriggerLogic: ZEN ready / done answered at once
        _meta = {'mro': ('TriggerLogic',)}

        def __init__(self):
            self.sent = []

        def send_trigger(self, name):
            self.sent.append(name)

        def is_triggered(self, name):
            return True

    z_trigger = ZenTrigger()
    z_box = _short.AutoAnswer('ZEN settings')  # answers the ZEN settings box ('Done - continue')
    z_ref = os.path.join(TMP, 'zen_ref_z')
    os.makedirs(z_ref, exist_ok=True)
    z_inj = copy.deepcopy(EXAMPLE)
    z_inj['probes'] = {1: 'RT1'}
    template = yaml.safe_load(open(_short.local_options(repo, ENTRY['options'])['metadata_template'], encoding='utf-8'))
    template_z = {k: v for item in template['Acquisition'] for k, v in item.items()}['number_z_planes']

    def z_run(cls, name, drop_z_planes, **extra):
        exp = files(z_inj, name, extra=extra)
        if drop_z_planes:
            content = yaml.safe_load(open(exp))
            content.pop('num_z_planes')
            yaml.safe_dump(content, open(exp, 'w'))
        task = make_task(cls=cls, user_config_path=exp) if cls is him.HiMDummyTask else None
        if task is None:
            task = cls()
            for k, v in _short.local_options(repo, ENTRY['options']).items():
                setattr(task, k, v)
            task.user_config_path = exp
            _short.shorten(task, progress_interval_s=0.2)
            task.connect_modules(dict(MODS, trigger_logic=z_trigger))
            if not any(isinstance(h, H) for h in task.log.handlers):
                task.log.addHandler(H())
        t0 = monotonic()
        result, err, _, _ = run(task)
        folder = result.get('directory') if result else None
        params = yaml.safe_load(open(os.path.join(folder, 'HiM_parameters.yml'))) if folder else {}
        meta = yaml.safe_load(open(os.path.join(folder, 'metadata.yml'), encoding='utf-8')) if folder else {}
        acq = {k: v for item in meta['Acquisition'] for k, v in item.items()} if meta else {}
        logs = [(lvl, m) for t, lvl, m in LOGS if t >= t0]
        return task, result, err, params, acq, logs, t0

    sd_extra = {'zen_ref_images_path': z_ref, 'correlation_threshold': 0.6}
    # (1) SD experiment file without num_z_planes
    task, result, err, params, acq, logs, t0 = z_run(him.HiMSDTask, 'sd_no_z', True, **sd_extra)
    check(f'(SD, no num_z_planes in the file) 1 cycle x {N} ROIs done; HiM_parameters.yml without "number of z planes"; '
          f'metadata.yml number_z_planes as in the template ({template_z!r})',
          err is None and result and result['cycles_done'] == 1
          and 'number of z planes' not in params['3- imaging parameters']
          and 'num_z_planes' not in params['1- global parameters'] and acq.get('number_z_planes') == template_z
          and task.num_z_planes is None, (err, result, params.get('3- imaging parameters'), acq.get('number_z_planes')))
    end_state_ok('SD, no num_z_planes', t0)
    # (2) old SD experiment file still with num_z_planes (5)
    task, result, err, params, acq, logs, t0 = z_run(him.HiMSDTask, 'sd_old_z', False, **sd_extra)
    check('(SD, old file with num_z_planes: 5) runs; value ignored (not read, no "number of z planes" entry, metadata '
          'field as in the template), no warning about it',
          err is None and result and result['cycles_done'] == 1 and task.num_z_planes is None
          and 'number of z planes' not in params['3- imaging parameters'] and acq.get('number_z_planes') == template_z
          and not any(lvl >= logging.WARNING and 'z_planes' in m for lvl, m in logs), (err, result, acq))
    # (4) Hi-M dummy: num_z_planes still required and used
    task, result, err, params, acq, logs, t0 = z_run(him.HiMDummyTask, 'dummy_no_z', True)
    check("(dummy, no num_z_planes in the file) still an error before any hardware call: 'num_z_planes' missing",
          err is not None and "'num_z_planes' missing" in str(err) and not [n for n, _ in calls(t0) if n in HARDWARE], err)
    task, result, err, params, acq, logs, t0 = z_run(him.HiMDummyTask, 'dummy_z', False)
    check('(dummy, num_z_planes: 5) unchanged: HiM_parameters.yml "number of z planes" 5, metadata.yml number_z_planes 5',
          err is None and result and params['3- imaging parameters'].get('number of z planes') == 5
          and acq.get('number_z_planes') == 5 and task.num_z_planes == 5, (err, params.get('3- imaging parameters')))
    z_box.stop()

    # (3) experiment configurator: the SD Hi-M definition has no number-of-planes field (dummy Hi-M still has it)
    def configurator(definitions, experiments):
        """Experiment configurator logic + GUI of dummy_config.cfg on the definitions of the repository."""
        modules = {}

        def build_cfg(name):
            if name in modules:
                return modules[name]
            if name in MODULES:
                return MODULES[name]
            base = next(b for b in ('hardware', 'logic', 'gui') if name in (CFG.get(b) or {}))
            entry = CFG[base][name]
            mod, cls = entry['module.Class'].rsplit('.', 1)
            klass = getattr(importlib.import_module(f'qudi.{base}.{mod}'), cls)
            opts = _short.module_options(name, entry.get('options'))
            if name == 'experiments_configurator_logic':
                opts['experiment_definitions_directory'] = os.path.join(
                    repo, 'custom_config', 'custom_experiments_config', definitions) + os.sep
                opts['experiments'] = experiments
            m = klass(qudi_main_weakref=weakref.ref(MAIN), name=name, config=opts)
            by_name = {c.name: c for k in dir(klass) if isinstance(c := getattr(klass, k, None), Connector)}
            for key, target in (entry.get('connect') or {}).items():
                m._meta['connectors'][next(k for k in m._meta['connectors']
                                           if by_name[key] is getattr(klass, k))].connect(build_cfg(target))
            m.module_state.activate()
            modules[name] = m
            return m
        gui = build_cfg('experiments_configurator_gui')
        KEEP_CFG.append(modules)
        return gui

    KEEP_CFG = []
    shown = {}
    for definitions, experiments, name in (('spinning_disk', ['him_epi.yaml'], 'him_epi_sd'),
                                           ('dummy', ['him.yaml'], 'Hi-M Dummy')):
        gui = configurator(definitions, experiments)
        gui.show()
        gui.start_new_experiment_config(name)
        app.processEvents()
        mw = gui._mw
        shown[name] = (mw.num_z_planes_SpinBox.isVisibleTo(mw), mw.num_z_planes_Label.isVisibleTo(mw),
                       mw.imaging_sequence_ListView.isVisibleTo(mw) if hasattr(mw, 'imaging_sequence_ListView') else None)
        mw.close()
    check('(configurator) SD Hi-M experiment: number-of-planes field and label hidden; Hi-M dummy: still shown',
          shown['him_epi_sd'][:2] == (False, False) and shown['Hi-M Dummy'][:2] == (True, True), shown)

if ONLY:
    print(f'\n{sum(ok for _, ok in results)}/{len(results)} passed', flush=True)
    os._exit(0 if all(ok for _, ok in results) else 1)

# --- Hi-M cycles: run, progress, interrupt, errors, needle, SD, RAMM ---

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

    ZEN_BOX = _short.AutoAnswer('ZEN settings')  # answers the ZEN settings box of the SD task ('Done - continue')
    task = sd_task()
    t0 = monotonic()
    result, err, _, _ = run(task)
    logs = [(lvl, m) for t, lvl, m in LOGS if t >= t0]
    msgs = [m for _, m in logs]
    zen = trigger.created[0] if trigger.created else ''
    print('    SD result:', result, err)
    check(f'(SD) ZEN settings box answered once, loops 1 cycle x {N} ROIs = {N}; channels and loops logged before the '
          f'wait for ready; no warning line with the loops any more',
          len(ZEN_BOX.texts) == 1 and ZEN_BOX.texts[0].endswith(f'2- the number of loops for blocks 4>9 should be {N}')
          and 'ZEN: select the channels 488 nm, 561 nm' in msgs
          and f'ZEN: set the number of acquisition loops to {N}' in msgs
          and not any(m.startswith('ZEN: number of acquisition loops =') for m in msgs),
          (ZEN_BOX.texts, [m for m in msgs if 'ZEN' in m][:4]))
    run_folder = result['directory'] if result else ''
    check('(SD) run folder created by qudi in save_path (no server folder): YYYY_MM_DD/001_HiM_<sample>; the folder '
          'created by ZEN is not used',
          err is None and os.path.isdir(run_folder) and os.path.basename(run_folder).startswith('001_HiM_')
          and os.path.dirname(os.path.dirname(run_folder)) == os.path.join(TMP, 'data_sd')
          and not os.path.exists(os.path.join(zen, 'metadata')), (result, err))
    movies = open(os.path.join(run_folder, 'movie_name.txt')).read().split() if run_folder else []
    check(f'(SD) HiM_parameters.yml and movie_name.txt in the run folder; names scan_001_RT1_<roi>_ROI ({movies[:1]})',
          os.path.exists(os.path.join(run_folder, 'HiM_parameters.yml'))
          and movies == [f'scan_001_RT1_{n[4:]}_ROI' for n in NAMES], movies)
    ph = [m for lvl, m in logs if 'Autofocus check not implemented yet' in m]
    check(f'(SD) autofocus placeholder logged once per run ({N} ROIs)', ph == [
          'Autofocus check not implemented yet (zen_ref_images_path, correlation_threshold)'], ph)
    i_af = [k for k, m in enumerate(msgs) if 'autofocus confirmed done by ZEN' in m]
    i_ph = [k for k, m in enumerate(msgs) if 'Autofocus check not implemented' in m]
    i_acq = [k for k, m in enumerate(msgs) if 'Triggering ZEN acquisition' in m]
    check('(SD) order: autofocus done -> autofocus check -> acquisition block; 2 ZEN blocks per ROI',
          i_af and i_ph and i_acq and i_af[0] < i_ph[0] < i_acq[0] and trigger.sent.count('trigger_ZEN_start_block') == 2 * N)
    SD_MISSING = files(sd_inj, 'sd_missing', extra={'zen_ref_images_path': os.path.join(TMP, 'nowhere'),
                                                     'correlation_threshold': 0.6})
    task = sd_task()
    task.user_config_path = SD_MISSING
    t0 = monotonic()
    result, err, _, _ = run(task)
    check('(SD) zen_ref_images_path not an existing folder -> error before any hardware call',
          err is not None and 'zen_ref_images_path' in str(err) and 'is not an existing folder' in str(err)
          and not [n for n, _ in calls(t0) if n in HARDWARE], err)
    ZEN_BOX.stop()

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


# --- probe valve read from the injections file ---
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
