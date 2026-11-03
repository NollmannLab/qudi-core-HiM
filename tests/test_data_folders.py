"""Data folders defined in the logic: ROI lists (roi_logic roi_list_directory), injections files
(injections logic injections_directory); the ROI GUI, the injections GUI and the experiment configurator
GUI start their file dialogs there.

Usage: QT_QPA_PLATFORM=offscreen python tests/test_data_folders.py [<repo_root>]
Real modules of dummy_config.cfg (GUIs offscreen), built several times with test option sets (the
folder options point to temporary folders). The file dialogs are replaced by recorders of their start
folder. Short settings: tests/_short.py (docs/TESTING.md).
"""
import sys, os, weakref, logging, importlib, tempfile, copy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _short  # noqa: E402  (short settings and shared test data, docs/TESTING.md)
repo = _short.repo_root(sys.argv)
sys.path.insert(0, os.path.join(repo, 'src'))
from qtpy import QtCore, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
import yaml  # noqa: E402
from importlib.metadata import version  # noqa: E402
import qudi.core  # noqa: E402
from qudi.core.connector import Connector  # noqa: E402

results = []


def check(label, cond, detail=''):
    results.append((label, bool(cond)))
    print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)


print('qudi-core', version('qudi-core'))
LOGS = []


class H(logging.Handler):
    def emit(self, r):
        LOGS.append((r.levelno, r.name, r.getMessage()))


logging.getLogger().addHandler(H())
QtCore.qInstallMessageHandler(lambda *a: None)


class FakeMain(QtCore.QObject):
    pass


MAIN = FakeMain()
CFG = yaml.safe_load(open(os.path.join(repo, 'custom_config/dummy_config.cfg'), encoding='utf-8'))
TMP = tempfile.mkdtemp()
ROI_DIR = os.path.join(TMP, 'roi_lists_logic')
INJ_DIR = os.path.join(TMP, 'injections_logic')
OLD_ROI = os.path.join(TMP, 'roi_lists_gui_option')
OLD_INJ = os.path.join(TMP, 'injections_gui_option')
QUDI_DIR = os.path.join(TMP, 'qudi')
for d in (ROI_DIR, INJ_DIR, OLD_ROI, OLD_INJ, QUDI_DIR):
    os.makedirs(d)

# ------------------------------------------------------------------ dialogs recorded
DIALOGS = []


def fake_dialog(kind):
    def dialog(parent, caption='', directory='', *a, **k):
        DIALOGS.append((kind, caption, directory))
        return '', ''
    return staticmethod(dialog)


QtWidgets.QFileDialog.getOpenFileName = fake_dialog('open')
QtWidgets.QFileDialog.getSaveFileName = fake_dialog('save')


# ------------------------------------------------------------------ module builder (one set of modules per scenario)
def builder(options=None, connect=None):
    """Return build(name): modules of dummy_config.cfg with options updated by options[name] (None removes
    a key) and connections replaced by connect[name]."""
    modules = {}
    options = options or {}
    connect = connect or {}

    def build(name):
        if name in modules:
            return modules[name]
        base = next(b for b in ('hardware', 'logic', 'gui') if name in (CFG.get(b) or {}))
        entry = CFG[base][name]
        mod, cls = entry['module.Class'].rsplit('.', 1)
        klass = getattr(importlib.import_module(f'qudi.{base}.{mod}'), cls)
        opts = _short.module_options(name, entry.get('options'))
        for key, value in (options.get(name) or {}).items():
            if value is None:
                opts.pop(key, None)
            else:
                opts[key] = value
        m = klass(qudi_main_weakref=weakref.ref(MAIN), name=name, config=opts)
        by_name = {c.name: c for k in dir(klass) if isinstance(c := getattr(klass, k, None), Connector)}
        for key, target in (connect.get(name, entry.get('connect')) or {}).items():
            m._meta['connectors'][next(k for k in m._meta['connectors'] if by_name[key] is getattr(klass, k))].connect(build(target))
        m.module_state.activate()
        _short.speed_up(m)
        modules[name] = m
        return m
    return build


def folders(build):
    """Start folders of: ROI GUI save path field and load dialog, injections GUI load / save dialogs,
    configurator ROI list / injections dialogs."""
    DIALOGS.clear()
    roi_gui = build('roi_gui')
    field = roi_gui._mw.save_path_LineEdit.text()
    roi_gui.load_roi_list()
    inj_gui = build('injection_configurator_gui')
    inj_gui.load_injections_clicked()
    inj_gui.save_injections_clicked()
    exp_gui = build('experiments_configurator_gui')
    exp_gui.load_roi_list_clicked()
    exp_gui.load_injections_clicked()
    starts = [d for _, _, d in DIALOGS]
    return {'roi_field': field, 'roi_load': starts[0], 'inj_load': starts[1], 'inj_save': starts[2],
            'exp_roi': starts[3], 'exp_inj': starts[4]}


def warnings_since(n):
    return [m for lvl, _, m in LOGS[n:] if lvl == logging.WARNING and 'obsolete' in m]


EXPECTED = {'roi_field': ROI_DIR, 'roi_load': ROI_DIR, 'inj_load': INJ_DIR, 'inj_save': INJ_DIR,
            'exp_roi': ROI_DIR, 'exp_inj': INJ_DIR}
LOGIC_OPTS = {'roi_logic': {'roi_list_directory': ROI_DIR},
              'injections_configurator_logic': {'injections_directory': INJ_DIR},
              'experiments_configurator_gui': {'default_path': QUDI_DIR},
              # the definition files of the repository (the config points to the folder of the dummy machine)
              'experiments_configurator_logic': {
                  'experiment_definitions_directory': os.path.join(repo, 'custom_config/custom_experiments_config/dummy/')}}

# ------------------------------------------------------------------ (1) dummy config (folders in the logic)
dummy_gui = {n: (CFG['gui'][n].get('options') or {}) for n in ('roi_gui', 'injection_configurator_gui',
                                                                 'experiments_configurator_gui')}
check('dummy_config.cfg: folders in roi_logic / injections logic, configurator logic connected to both, '
      'no folder option left in the three GUIs (configurator keeps default_path)',
      CFG['logic']['roi_logic']['options']['roi_list_directory'] == '/home/jb/qudi/roi_lists/'
      and CFG['logic']['injections_configurator_logic']['options']['injections_directory']
      == '/home/jb/qudi/injections_configurations/'
      and CFG['logic']['experiments_configurator_logic']['connect']['roi_logic'] == 'roi_logic'
      and CFG['logic']['experiments_configurator_logic']['connect']['injections_logic'] == 'injections_configurator_logic'
      and 'default_path' not in dummy_gui['roi_gui'] and 'default_path' not in dummy_gui['injection_configurator_gui']
      and set(dummy_gui['experiments_configurator_gui']) == {'default_path'}, dummy_gui)
n0 = len(LOGS)
got = folders(builder(LOGIC_OPTS))
check('(dummy config) ROI GUI save path + load, injections GUI load / save, configurator ROI list / injections '
      'dialogs all start in the folders of the logic; no obsolete-option warning',
      got == EXPECTED and warnings_since(n0) == [], (got, warnings_since(n0)))

# ------------------------------------------------------------------ (2) old config: GUI options still set
old = copy.deepcopy(LOGIC_OPTS)
old.update({'roi_gui': {'default_path': OLD_ROI}, 'injection_configurator_gui': {'default_path': OLD_INJ},
            'experiments_configurator_gui': {'default_path': QUDI_DIR, 'default_roi_path': OLD_ROI,
                                             'default_injections_path': OLD_INJ}})
n0 = len(LOGS)
got = folders(builder(old))
w = warnings_since(n0)
print('    warnings:', *w, sep='\n      ')
check('(old config, logic folders set) logic values used everywhere', got == EXPECTED, got)
check('(old config) one warning per obsolete option (4), each naming the option, where the value goes, and the '
      'folder used', len(w) == 4
      and sum('default_path of this ROI GUI' in m and 'roi_logic: options: roi_list_directory' in m and ROI_DIR in m for m in w) == 1
      and sum('default_path of this injections GUI' in m and 'injections_directory' in m and INJ_DIR in m for m in w) == 1
      and sum('default_roi_path' in m and ROI_DIR in m for m in w) == 1
      and sum('default_injections_path' in m and INJ_DIR in m for m in w) == 1, w)

# old config without the logic options: the GUI values are used (with the warnings)
old_only = copy.deepcopy(old)
old_only['roi_logic'] = {'roi_list_directory': None}
old_only['injections_configurator_logic'] = {'injections_directory': None}
n0 = len(LOGS)
got = folders(builder(old_only))
w = warnings_since(n0)
check('(old config, logic folders not set) the GUI option values are used, one warning per option',
      got == {'roi_field': OLD_ROI, 'roi_load': OLD_ROI, 'inj_load': OLD_INJ, 'inj_save': OLD_INJ,
              'exp_roi': OLD_ROI, 'exp_inj': OLD_INJ} and len(w) == 4, (got, w))
missing = [m for lvl, n, m in LOGS[n0:] if lvl == logging.WARNING and ('roi_list_directory' in m or 'injections_directory' in m)
           and 'obsolete' not in m]
check('(logic folder options not set) qudi warns about the missing logic options (missing="warn")', len(missing) >= 2,
      missing)

# ------------------------------------------------------------------ (3) configurator without roi_logic / injections logic
exp_connect = {k: v for k, v in CFG['logic']['experiments_configurator_logic']['connect'].items()
               if k not in ('roi_logic', 'injections_logic')}
build = builder(LOGIC_OPTS, connect={'experiments_configurator_logic': exp_connect})
n0 = len(LOGS)
DIALOGS.clear()
exp_logic = build('experiments_configurator_logic')
exp_gui = build('experiments_configurator_gui')
exp_gui.load_roi_list_clicked()
exp_gui.load_injections_clicked()
starts = [d for _, _, d in DIALOGS]
check('(configurator without roi_logic / injections logic) activates; properties return ""; both dialogs fall back '
      'to default_path; no warning', exp_logic.module_state() == 'idle' and exp_gui.module_state() == 'idle'
      and exp_logic.roi_list_directory == '' and exp_logic.injections_directory == ''
      and starts == [QUDI_DIR, QUDI_DIR] and warnings_since(n0) == [], (starts, warnings_since(n0)))

print(f'\n{sum(ok for _, ok in results)}/{len(results)} passed', flush=True)
os._exit(0 if all(ok for _, ok in results) else 1)
