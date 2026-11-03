"""ROI scan on the spinning disk: files in the folder created by ZEN (shared SDImagingMixin code with the
Hi-M SD task), and the ROI scan dummy unchanged.

Usage: QT_QPA_PLATFORM=offscreen python tests/test_roi_scan_zen_folder.py [<repo_root>]
A temporary zen_saving_path holds 2 existing folders; the fake TriggerLogic creates the "ZEN" folder(s)
when "ready" is polled (one, none or two). ROI scan: roi / laser stand-ins; Hi-M: the real dummy
fluidics, roi and laser modules of dummy_config.cfg. The ZEN settings box of the ROI scan is answered
'Done - continue'. Short settings and test data: tests/_short.py (docs/TESTING.md).
"""
import sys, os, logging, tempfile, threading, weakref, importlib, copy, glob
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
from qudi.tasks import roi_multicolour_scan as rs  # noqa: E402
from qudi.tasks import him  # noqa: E402

results = []


def check(label, cond, detail=''):
    results.append((label, bool(cond)))
    print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)


print('qudi-core', version('qudi-core'))
TMP = tempfile.mkdtemp()
LOGS = []
QtCore.qInstallMessageHandler(lambda *a: None)


class H(logging.Handler):
    def emit(self, r):
        LOGS.append((r.levelno, r.getMessage()))


ROIS = _short.roi_names()   # ROI_000, ROI_001
ZEN_BOX = _short.AutoAnswer('ZEN settings')  # answers the ZEN settings box of the ROI scan


def zen_root(name):
    """Temporary zen_saving_path with 2 existing folders."""
    root = os.path.join(TMP, name)
    for old in ('2026_10_01_old', '2026_10_02_old'):
        os.makedirs(os.path.join(root, old))
    return root


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


class TriggerLogic(_Stand):
    """Fake ZEN: when "ready" is polled the first time, creates `new` folders in `root` (ZEN starting the
    experiment), then answers every poll at once."""
    _meta = {'mro': ('TriggerLogic',)}

    def __init__(self, rec, root=None, new=('2026_11_03_ZEN_experiment',)):
        super().__init__(rec)
        self.root, self.new, self.created = root, new, []

    def is_triggered(self, name):
        self._rec.rec('is_triggered', name)
        if name == 'trigger_ZEN_ready' and self.root and not self.created:
            for folder in self.new:
                path = os.path.join(self.root, folder)
                os.makedirs(path)
                self.created.append(path)
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
    content = {'sample_name': 'SDsample', 'roi_list_path': '/fake/rois.json', 'imaging_sequence': [[488, 50.0]]}
    content.update(values)
    yaml.safe_dump(content, open(path, 'w'))
    return path


def scan_task(cls, path, trigger=None):
    rec = Rec()
    stands = {'roi_logic': RoiLogic(rec), 'laser_logic': LaserControlLogic(rec)}
    if trigger is not None:
        trigger._rec = rec
        stands['trigger_logic'] = trigger
    KEEP.append(stands)
    task = _short.shorten(type(cls.__name__ + 'UnderTest', (cls,), {'user_config_path': path})())
    task.connect_modules(stands)
    task.log.addHandler(H())
    return task, rec


def movies(folder):
    path = os.path.join(folder, 'movie_name.txt')
    return open(path).read().split() if os.path.exists(path) else None


# ------------------------------------------------------------------ (1) ROI scan SD, 2 ROIs
for dapi in (False, True):
    root = zen_root(f'zen_scan_{int(dapi)}')
    trigger = TriggerLogic(None, root)
    task, rec = scan_task(rs.RoiScanSDTask, scan_yaml(f'sd_{int(dapi)}', zen_saving_path=root, dapi=dapi), trigger)
    result, err = run(task, {'start_roi': ''})
    folder = os.path.join(trigger.created[0], 'metadata') if trigger.created else None
    expected = [f'scan_003_{"DAPI_" if dapi else ""}{r[4:]}_ROI' for r in ROIS]
    label = 'with dapi' if dapi else 'no dapi'
    check(f'(1 ROI scan SD, {label}) both ROIs imaged; data folder = <new ZEN folder>/metadata, with '
          f'parameters.yml and movie_name.txt; prefix 003; movie names {expected}',
          err is None and result.get('imaged_rois') == ROIS and result.get('directory') == folder
          and os.path.exists(os.path.join(folder, 'parameters.yml')) and task.prefix == '003'
          and movies(folder) == expected, (err, result, task.prefix, movies(folder) if folder else None))
    check(f'(1 ROI scan SD, {label}) no other folder created (only the ZEN folder in zen_saving_path); '
          f'"ZEN will save the data in the following folder" logged',
          sorted(os.listdir(root)) == sorted(['2026_10_01_old', '2026_10_02_old', os.path.basename(trigger.created[0])])
          and any(m == f'ZEN will save the data in the following folder : {trigger.created[0]}' for _, m in LOGS),
          os.listdir(root))

# ------------------------------------------------------------------ (2) no new folder / two new folders
for label, new, fragment in (('no new folder', (), 'No new file was created by ZEN'),
                             ('two new folders', ('2026_11_03_a', '2026_11_03_b'), 'More than one folder were found')):
    root = zen_root(f'zen_{label.replace(" ", "_")}')
    trigger = TriggerLogic(None, root, new=new)
    task, rec = scan_task(rs.RoiScanSDTask, scan_yaml(label.replace(' ', '_'), zen_saving_path=root), trigger)
    task._ZEN_FOLDER_ATTEMPTS = 2  # shorter wait for the missing folder (2 attempts, 1 s apart)
    result, err = run(task, {'start_roi': ''})
    names = [n for n, _ in rec.calls]
    msgs = [m for _, m in LOGS]
    print(f'    {label}: {err}')
    check(f'(2 {label}) clear error ("{fragment}..."), no ROI imaged, no data file; cleanup as usual (stage back to '
          f'the first ROI, lasers off, velocity restored, ROI GUI unlocked)',
          err is not None and fragment in str(err) and 'send_trigger' not in names
          and not glob.glob(os.path.join(root, '*', 'metadata')) and 'cleanup finished' in msgs
          and 'go_to_roi_xy' in names and 'set_laser_disabled' in names[names.index('is_triggered'):]
          and 'enable_roi_actions' in names and names.count('set_stage_velocity') == 2, (err, names[-8:]))

# ------------------------------------------------------------------ (3) zen_saving_path missing / not a folder
not_a_folder = os.path.join(TMP, 'a_file.txt')
open(not_a_folder, 'w').close()
for label, values, fragment in (('missing', {}, "'zen_saving_path' missing"),
                                ('not a folder', {'zen_saving_path': not_a_folder}, 'is not an existing folder')):
    task, rec = scan_task(rs.RoiScanSDTask, scan_yaml(f'zen_{label.replace(" ", "_")}', **values),
                          TriggerLogic(None))
    ZEN_BOX.texts.clear()
    result, err = run(task, {'start_roi': ''})
    check(f'(3 zen_saving_path {label}) error "{fragment}" before any hardware call (no roi / laser / trigger call, '
          f'no ZEN box), cleanup restores nothing',
          err is not None and fragment in str(err) and rec.calls == [] and not ZEN_BOX.texts
          and any('nothing to restore' in m for _, m in LOGS), (err, rec.calls))

# ------------------------------------------------------------------ (4) Hi-M SD, 1 probe, 2 ROIs (real dummy modules)


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
root = zen_root('zen_him')
ref_images = os.path.join(TMP, 'zen_ref')
os.makedirs(ref_images)
injections = _short.load(_short.HIM_INJECTIONS)
injections['probes'] = {1: 'RT1'}
injections['hybridization list'] = [{'step_number': 1, 'procedure': 'Hybridization', 'product': 'SSC',
                                     'volume': _short.INJECTION_UL, 'flowrate': _short.HIM_FLOWRATE, 'time': None}]
injections['photobleaching list'] = []
inj_path = os.path.join(TMP, 'him_sd_injections.yml')
yaml.safe_dump(injections, open(inj_path, 'w'))
exp = _short.experiment(TMP, 'him_experiment.yaml', 'him_sd', injections_path=inj_path, zen_saving_path=root,
                        zen_ref_images_path=ref_images, correlation_threshold=0.6)
him_rec = Rec()
him_trigger = TriggerLogic(him_rec, root)
KEEP.append(him_trigger)
him_task = _short.shorten(him.HiMSDTask(), progress_interval_s=0.2)
him_task.user_config_path = exp
him_task.connect_modules(dict(mods, trigger_logic=him_trigger))
him_task.log.addHandler(H())
result, err = run(him_task, timeout=180)
folder = os.path.join(him_trigger.created[0], 'metadata') if him_trigger.created else None
names = movies(folder) if folder else None
check("(4 Hi-M SD, 1 probe, 2 ROIs) new ZEN folder found; HiM_parameters.yml and movie_name.txt in <new folder>/metadata; "
      "movie names unchanged ('scan__RT1_<roi number>_ROI')",
      err is None and result and result['cycles_done'] == 1 and result['directory'] == folder
      and os.path.exists(os.path.join(folder, 'HiM_parameters.yml'))
      and names == [f'scan__RT1_{r[4:]}_ROI' for r in ROIS], (err, result, names))

# ------------------------------------------------------------------ (5) ROI scan dummy: own folder under save_path
save_path = os.path.join(TMP, 'dummy_data')
task, rec = scan_task(rs.RoiScanDummyTask, scan_yaml('dummy', save_path=save_path))
result, err = run(task, {'start_roi': ''})
created = glob.glob(os.path.join(save_path, '*', '001_Scan_SDsample'))
check('(5 ROI scan dummy) still creates save_path/YYYY_MM_DD/001_Scan_<sample> with parameters.yml and '
      'movie_name.txt; names scan_001_<roi number>_ROI',
      err is None and len(created) == 1 and result.get('directory') == created[0]
      and os.path.exists(os.path.join(created[0], 'parameters.yml'))
      and movies(created[0]) == [f'scan_001_{r[4:]}_ROI' for r in ROIS], (err, result, created))

print(f'\n{sum(ok for _, ok in results)}/{len(results)} passed', flush=True)
os._exit(0 if all(ok for _, ok in results) else 1)
