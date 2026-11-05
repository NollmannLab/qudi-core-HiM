"""Logic helpers: data folders defined in the logic modules (ROI lists, injections files), the random
ROI list command-line helper (qudi.util.make_random_roi_list) and the local / server folder buttons of the
experiment configurator, its sample tag and ZEN folder dialogs, the sample file (helper, configurator, dialog), and the autofocus report of Hi-M runs (qudi.util.autofocus_report).

Usage: QT_QPA_PLATFORM=offscreen python tests/test_logic_helpers.py [<repo_root>]
Short settings: tests/_short.py (docs/TESTING.md).
"""
import sys, os
from importlib.metadata import version

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _short  # noqa: E402  (short settings and shared test data, docs/TESTING.md)
repo = _short.repo_root(sys.argv)
sys.path.insert(0, os.path.join(repo, 'src'))
from qtpy import QtCore, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
print('qudi-core', version('qudi-core'))
KEEP_ALIVE = []  # objects of each section (Qt threads must not be destroyed while running)


# --- data folders in the logic ---
def _section_data_folders():
    """Data folders defined in the logic: ROI lists (roi_logic roi_list_directory), injections files
    (injections logic injections_directory); the ROI GUI, the injections GUI and the experiment configurator
    GUI start their file dialogs there.
    
    Real modules of dummy_config.cfg (GUIs offscreen), built several times with test option sets (the
    folder options point to temporary folders). The file dialogs are replaced by recorders of their start
    folder. Short settings: tests/_short.py (docs/TESTING.md)."""
    import sys, os, weakref, logging, importlib, tempfile, copy

    from qtpy import QtCore, QtWidgets  # noqa: E402

    import yaml  # noqa: E402
    from importlib.metadata import version  # noqa: E402
    import qudi.core  # noqa: E402
    from qudi.core.connector import Connector  # noqa: E402

    results = []


    def check(label, cond, detail=''):
        results.append((label, bool(cond)))
        print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)


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
    KEEP_ALIVE.append(locals())  # modules, threads and widgets of the section live until the end
    return results

# --- random ROI list helper ---
def _section_random_roi_list():
    """make_random_roi_list CLI + loading in the ROI GUI + path optimization end to end.
    
    Real roi_logic (dummy stage of dummy_config.cfg) and RoiGUI, in a temporary folder."""
    import sys, os, json, weakref, logging, importlib, tempfile, copy, glob, datetime as dt
    from time import sleep
    from importlib.metadata import version

    from qtpy import QtCore, QtWidgets  # noqa: E402

    import numpy as np  # noqa: E402
    import yaml  # noqa: E402
    import qudi.core  # noqa: E402
    from qudi.core.connector import Connector  # noqa: E402
    from qudi.util.roi_path import path_cost  # noqa: E402
    import qudi.logic.roi_logic as roi_module  # noqa: E402

    results = []


    def check(label, cond, detail=''):
        results.append((label, bool(cond)))
        print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)


    LOGS = []


    class H(logging.Handler):
        def emit(self, r):
            LOGS.append((r.levelno, r.getMessage()))


    logging.getLogger().addHandler(H())


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



    import subprocess, filecmp
    TMP = tempfile.mkdtemp()
    PY = sys.executable
    ENV = dict(os.environ, PYTHONPATH=os.path.join(repo, 'src'))


    def cli(*a):
        p = subprocess.run([PY, '-m', 'qudi.util.make_random_roi_list', *a], capture_output=True, text=True, env=ENV, cwd=TMP)
        return p.returncode, p.stdout.strip(), p.stderr.strip()


    # ------------------------------------------------------------------ CLI
    rc, out, err = cli('--n', '25')
    f25 = os.path.join(TMP, 'random_25_rois.json')
    print('    stdout:', out)
    d = json.load(open(f25))
    check('default call: ./random_25_rois.json, prints path and count, exit 0',
          rc == 0 and out == f'{f25}: 25 ROI(s)' and d['name'] == 'random_25_rois', (rc, out, err))
    xy = np.array([r['position'] for r in d['rois']])
    check('names ROI_001..ROI_025, x / y in [0, 10000], z = 0, ROI-logic dict keys',
          [r['name'] for r in d['rois']] == [f'ROI_{k:03d}' for k in range(1, 26)]
          and xy[:, :2].min() >= 0 and xy[:, :2].max() <= 10000 and np.all(xy[:, 2] == 0)
          and set(d) == {'name', 'creation_time', 'cam_image', 'cam_image_extent', 'rois'})
    mtime = os.path.getmtime(f25); content = open(f25).read()
    rc, out, err = cli('--n', '25')
    check('existing file -> exit 1, error message, file not modified',
          rc == 1 and 'already exists' in err and open(f25).read() == content and os.path.getmtime(f25) == mtime, (rc, err))
    ct = ['--creation-time', '2026-10-23 16:00:00.000000']
    cli('--n', '25', '--name', 'a', *ct); cli('--n', '25', '--name', 'b', *ct)
    fa, fb = (json.load(open(os.path.join(TMP, x + '.json'))) for x in 'ab')
    fa.pop('name'); fb.pop('name')
    check('same seed -> same ROIs (fixed creation time: same content apart from the name)', fa == fb)
    cli('--n', '25', '--name', 'same', '--folder', os.path.join(TMP, 'f1'), *ct)
    cli('--n', '25', '--name', 'same', '--folder', os.path.join(TMP, 'f2'), *ct)
    check('same arguments and seed -> byte-identical file',
          filecmp.cmp(os.path.join(TMP, 'f1/same.json'), os.path.join(TMP, 'f2/same.json'), shallow=False))
    cli('--n', '25', '--name', 'seed1', '--seed', '1')
    check('different seed -> different positions',
          json.load(open(os.path.join(TMP, 'seed1.json')))['rois'] != json.load(open(f25))['rois'])
    rc, out, _ = cli('--n', '40', '--z-range', '0', '50', '--seed', '3', '--name', 'test_40', '--folder', os.path.join(TMP, 'sub'),
                     '--x-range', '-5000', '5000', '--y-range', '100', '200', '--first-number', '7')
    d40 = json.load(open(os.path.join(TMP, 'sub/test_40.json')))
    p40 = np.array([r['position'] for r in d40['rois']])
    check('40 ROIs, random z in [0, 50], ranges (negative x), ROI_007..ROI_046, folder created',
          rc == 0 and len(p40) == 40 and p40[:, 2].min() >= 0 and p40[:, 2].max() <= 50 and np.ptp(p40[:, 2]) > 0
          and p40[:, 0].min() >= -5000 and p40[:, 0].max() <= 5000 and p40[:, 1].min() >= 100 and p40[:, 1].max() <= 200
          and [r['name'] for r in d40['rois']] == [f'ROI_{k:03d}' for k in range(7, 47)], out)
    rc, out, _ = cli('--n', '5', '--z', '12.5', '--name', 'z12')
    check('--z fixed value', rc == 0 and all(r['position'][2] == 12.5 for r in json.load(open(os.path.join(TMP, 'z12.json')))['rois']))
    rc, out, err = cli('--n', '5', '--z', '1', '--z-range', '0', '2')
    check('--z with --z-range -> refused by argparse', rc == 2 and 'not allowed' in err, err[-80:])
    for bad in (('--n', '-1'), ('--x-range', '10', '0'), ('--creation-time', 'yesterday')):
        rc, _, err = cli(*bad, '--name', 'bad')
        ok_bad = rc == 1 and 'Error' in err and not os.path.exists(os.path.join(TMP, 'bad.json'))
        check(f'invalid {" ".join(bad)} -> exit 1, no file', ok_bad, (rc, err))
    rc, out, _ = cli('--n', '0')
    d0 = json.load(open(os.path.join(TMP, 'random_0_rois.json')))
    check('--n 0 -> empty list file', rc == 0 and d0['rois'] == [] and out.endswith(': 0 ROI(s)'))
    rc, out, _ = cli('--help')
    check('--help', rc == 0 and '--first-number' in out)

    # ------------------------------------------------------------------ GUI load
    roi = build('roi_logic')
    gui = build('roi_gui')
    mw = gui._mw
    mw.save_path_LineEdit.setText(TMP)


    def pump(k=30):
        for _ in range(k):
            app.processEvents()
            sleep(0.01)


    def gui_load(path):
        orig = QtWidgets.QFileDialog.getOpenFileName
        QtWidgets.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (path, 'json files (*.json)'))
        try:
            mw.load_list_Action.trigger()
            pump()
        finally:
            QtWidgets.QFileDialog.getOpenFileName = orig


    def combo():
        return [mw.active_roi_ComboBox.itemText(i) for i in range(mw.active_roi_ComboBox.count())]


    gui_load(f25)
    check('GUI "Load list": 25 markers, combo ROI_001..ROI_025, list name, positions as in the file',
          len(gui._markers) == 25 and combo() == [f'ROI_{k:03d}' for k in range(1, 26)]
          and mw.roi_list_name_LineEdit.text() == 'random_25_rois'
          and np.allclose([roi.get_roi_position(r['name']) for r in d['rois']], xy), (len(gui._markers), combo()[:2]))
    gui_load(os.path.join(TMP, 'sub/test_40.json'))
    check('GUI load of the 40-ROI list (random z): 40 markers, z kept',
          len(gui._markers) == 40 and np.allclose(roi.get_roi_position('ROI_046'), d40['rois'][-1]['position']))
    gui_load(os.path.join(TMP, 'random_0_rois.json'))
    check('GUI load of the empty list: 0 markers, empty combo, list name shown',
          len(gui._markers) == 0 and combo() == [] and mw.roi_list_name_LineEdit.text() == 'random_0_rois')

    # ------------------------------------------------------------------ end to end with the path optimization
    rc, out, _ = cli('--n', '30', '--name', 'e2e')
    fe = os.path.join(TMP, 'e2e.json')
    de = json.load(open(fe))
    gui_load(fe)
    before_markers = {k: tuple(v.position) if hasattr(v, 'position') else None for k, v in gui._markers.items()}
    n_files = set(os.listdir(TMP))
    mw.optimize_path_Action.trigger()
    pump(80)
    new = sorted(set(os.listdir(TMP)) - n_files)
    print('    new files:', new)
    bk = [f for f in new if f.startswith('e2e_before_optimization_')]
    op = [f for f in new if f.startswith('e2e_optimized_')]
    check('optimize path after loading: backup file and optimized file written', len(bk) == 1 and len(op) == 1, new)
    dbk = json.load(open(os.path.join(TMP, bk[0])))
    dop = json.load(open(os.path.join(TMP, op[0])))
    check('backup = the generated list (same ROIs, positions, creation time)',
          dbk['rois'] == de['rois'] and dbk['creation_time'] == de['creation_time'])
    names = [r['name'] for r in dop['rois']]
    check('optimized names ROI_031..ROI_060, first ROI kept first, same set of positions',
          names == [f'ROI_{k:03d}' for k in range(31, 61)] and dop['rois'][0]['position'] == de['rois'][0]['position']
          and sorted(map(tuple, (r['position'] for r in dop['rois']))) == sorted(map(tuple, (r['position'] for r in de['rois'])))
          and [r['position'] for r in dop['rois']] != [r['position'] for r in de['rois']])
    gui_xy = [tuple(np.round(roi.get_roi_position(nm), 6)) for nm in combo()]
    check('GUI after the click: combo / markers ROI_031..ROI_060 in the new order, list name updated, ROI_031 active',
          combo() == names and set(gui._markers) == set(names)
          and gui_xy == [tuple(np.round(r['position'], 6)) for r in dop['rois']]
          and mw.roi_list_name_LineEdit.text() == dop['name'] and mw.active_roi_ComboBox.currentText() == 'ROI_031')
    msg = [m for lvl, m in LOGS if m.startswith('ROI path optimized')]
    print('    log:', msg[-1] if msg else None)
    KEEP_ALIVE.append(locals())  # modules, threads and widgets of the section live until the end
    return results

# --- configurator: local / server folder buttons ---
def _section_folder_buttons():
    """Experiment configurator GUI: buttons choosing the local folder (save_path) and the server folder
    (save_network_path). The folder dialog is replaced by a recorder returning a chosen folder (or '' for
    Cancel); the SD ROI scan, Hi-M epi and photobleaching definitions of the repository are used."""
    import os, weakref, importlib, tempfile
    from qtpy import QtCore, QtWidgets
    import yaml
    from qudi.core.connector import Connector

    results = []
    def check(label, cond, detail=''):
        results.append((label, bool(cond))); print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)
    class FakeMain(QtCore.QObject): pass
    MAIN = FakeMain()
    CFG = yaml.safe_load(open(os.path.join(repo, 'custom_config/dummy_config.cfg')))
    TMP = tempfile.mkdtemp()
    LOCAL, SERVER, DEF_LOCAL, DEF_SERVER = (os.path.join(TMP, n) for n in ('local', 'server', 'def_local', 'def_server'))
    for d in (LOCAL, SERVER, DEF_LOCAL, DEF_SERVER): os.makedirs(d)
    DIALOGS = []; ANSWER = ['']
    def fake(parent, caption='', directory='', *a, **k):
        DIALOGS.append((caption, directory)); return ANSWER[0]
    ORIGINAL_DIALOG = QtWidgets.QFileDialog.getExistingDirectory
    QtWidgets.QFileDialog.getExistingDirectory = staticmethod(fake)
    MODS = {}
    def build(name):
        if name in MODS: return MODS[name]
        base = next(b for b in ('hardware', 'logic', 'gui') if name in (CFG.get(b) or {}))
        entry = CFG[base][name]; mod, cls = entry['module.Class'].rsplit('.', 1)
        klass = getattr(importlib.import_module(f'qudi.{base}.{mod}'), cls)
        opts = _short.module_options(name, entry.get('options'))
        if name == 'experiments_configurator_logic':
            opts['experiment_definitions_directory'] = os.path.join(repo, 'custom_config/custom_experiments_config/spinning_disk') + '/'
            opts['experiments'] = ['roi_multicolour_scan.yaml', 'him_epi.yaml', 'photobleaching.yaml']
            opts['default path imagedata'] = DEF_LOCAL; opts['default network path'] = DEF_SERVER
        m = klass(qudi_main_weakref=weakref.ref(MAIN), name=name, config=opts)
        by_name = {c.name: c for k in dir(klass) if isinstance(c := getattr(klass, k, None), Connector)}
        for key, target in (entry.get('connect') or {}).items():
            m._meta['connectors'][next(k for k in m._meta['connectors'] if by_name[key] is getattr(klass, k))].connect(build(target))
        m.module_state.activate(); MODS[name] = m; return m
    gui = build('experiments_configurator_gui'); gui.show(); app.processEvents()
    mw, logic = gui._mw, gui._exp_logic
    lb, nb = mw.local_path_pushButton, mw.network_pushButton
    check('tooltips', lb.toolTip() == 'Choose the local folder' and nb.toolTip() == 'Choose the server folder')

    def shown(w): return w.isVisibleTo(mw)
    for exp in ('roi_multicolor_scan', 'him_epi_sd'):
        gui.start_new_experiment_config(exp); app.processEvents()
        check(f'({exp}) both buttons shown and enabled, like their fields',
              shown(lb) and shown(nb) and shown(mw.save_path_LineEdit) and shown(mw.save_network_path_LineEdit)
              and lb.isEnabled() and nb.isEnabled())
        for button, edit, key, chosen, title, default in (
                (lb, mw.save_path_LineEdit, 'save_path', LOCAL, 'Select the local folder for the data', DEF_LOCAL),
                (nb, mw.save_network_path_LineEdit, 'save_network_path', SERVER, 'Select the server folder for the data', DEF_SERVER)):
            # start folder: field value (the default) exists -> field; then a missing field value -> logic default; then home
            edit.setText(os.path.join(TMP, 'missing')); DIALOGS.clear(); ANSWER[0] = ''
            button.click(); app.processEvents()
            start_default = DIALOGS[-1][1] if DIALOGS else None
            check(f'({exp}, {key}) cancel: field unchanged, config unchanged; start = logic default when the field folder '
                  f'does not exist; title {title!r}',
                  edit.text() == os.path.join(TMP, 'missing') and logic.config_dict.get(key) == os.path.join(TMP, 'missing')
                  and start_default == default and DIALOGS[-1][0] == title, (DIALOGS, edit.text()))
            ANSWER[0] = chosen; button.click(); app.processEvents()
            check(f'({exp}, {key}) chosen folder fills the field and reaches the logic config',
                  edit.text() == chosen and logic.config_dict.get(key) == chosen, (edit.text(), logic.config_dict.get(key)))
            ANSWER[0] = ''; DIALOGS.clear(); button.click(); app.processEvents()
            check(f'({exp}, {key}) next dialog starts in the folder of the field', DIALOGS and DIALOGS[-1][1] == chosen, DIALOGS)
    gui.start_new_experiment_config('photobleaching'); app.processEvents()
    check('(photobleaching, no save fields) both buttons hidden with their fields',
          not shown(lb) and not shown(nb) and not shown(mw.save_path_LineEdit) and not shown(mw.save_network_path_LineEdit))
    # home folder fallback: field and logic default missing
    logic.default_path_imagedata = os.path.join(TMP, 'nowhere'); mw.save_path_LineEdit.setText('')
    DIALOGS.clear(); ANSWER[0] = ''; gui.load_local_path_clicked()
    check('start folder = home folder when neither the field nor the logic default exists',
          DIALOGS and DIALOGS[-1][1] == os.path.expanduser('~'), DIALOGS)
    QtWidgets.QFileDialog.getExistingDirectory = ORIGINAL_DIALOG
    KEEP_ALIVE.append(locals())  # modules, threads and widgets of the section live until the end
    return results

# --- configurator: sample tag and ZEN folder dialogs ---
def _section_sample_tag():
    """Experiment configurator: sample tag of the ROI scan (combo box DAPI / RNA / IF / Free, free tag in the line
    edit with a validator, save / load, former dapi / rna keys) and start folder of the two ZEN folder dialogs
    (option 'default zen path'). Folder dialog replaced by a recorder; SD definitions of the repository."""
    import os, weakref, importlib, tempfile, logging
    from qtpy import QtCore, QtGui, QtWidgets
    import yaml
    from qudi.core.connector import Connector

    results = []
    def check(label, cond, detail=''):
        results.append((label, bool(cond))); print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)
    LOGS = []
    class H(logging.Handler):
        def emit(self, r): LOGS.append((r.levelno, r.getMessage()))
    handler = H(); logging.getLogger().addHandler(handler)
    class FakeMain(QtCore.QObject): pass
    MAIN = FakeMain()
    CFG = yaml.safe_load(open(os.path.join(repo, 'custom_config/dummy_config.cfg')))
    TMP = tempfile.mkdtemp()
    ZEN_DEF, REF, ZEN = (os.path.join(TMP, n) for n in ('zen_default', 'references', 'zen_saving'))
    for d in (ZEN_DEF, REF, ZEN): os.makedirs(d)
    DIALOGS = []
    def fake(parent, caption='', directory='', *a, **k):
        DIALOGS.append((caption, directory)); return ''
    ORIGINAL_DIALOG = QtWidgets.QFileDialog.getExistingDirectory
    QtWidgets.QFileDialog.getExistingDirectory = staticmethod(fake)
    MODS = {}
    def build(name):
        if name in MODS: return MODS[name]
        base = next(b for b in ('hardware', 'logic', 'gui') if name in (CFG.get(b) or {}))
        entry = CFG[base][name]; mod, cls = entry['module.Class'].rsplit('.', 1)
        klass = getattr(importlib.import_module(f'qudi.{base}.{mod}'), cls)
        opts = _short.module_options(name, entry.get('options'))
        if name == 'experiments_configurator_logic':
            opts['experiment_definitions_directory'] = os.path.join(repo, 'custom_config/custom_experiments_config/spinning_disk') + '/'
            opts['experiments'] = ['roi_multicolour_scan.yaml', 'him_epi.yaml']
            opts['default zen path'] = ZEN_DEF
        m = klass(qudi_main_weakref=weakref.ref(MAIN), name=name, config=opts)
        by_name = {c.name: c for k in dir(klass) if isinstance(c := getattr(klass, k, None), Connector)}
        for key, target in (entry.get('connect') or {}).items():
            m._meta['connectors'][next(k for k in m._meta['connectors'] if by_name[key] is getattr(klass, k))].connect(build(target))
        m.module_state.activate(); MODS[name] = m; return m
    gui = build('experiments_configurator_gui'); app.processEvents()
    mw, logic = gui._mw, gui._exp_logic
    combo, edit = mw.sample_tag_comboBox, mw.sample_tag_lineEdit
    def shown(w): return not w.isHidden()

    # ------------------------------------------------------------------ ZEN folder dialogs
    sd_cfg = yaml.safe_load(open(os.path.join(repo, 'custom_config/Spinning_disk_config.cfg')))
    check("option 'default zen path' read by the logic; SD configuration sets /mnt/Experiments",
          logic.default_zen_path == ZEN_DEF
          and sd_cfg['logic']['experiments_configurator_logic']['options'].get('default zen path') == '/mnt/Experiments',
          logic.default_zen_path)
    home = os.path.expanduser('~')
    check('_dialog_start_folder: existing field folder, else existing default, else home',
          gui._dialog_start_folder(REF, ZEN_DEF) == REF
          and gui._dialog_start_folder(os.path.join(TMP, 'missing'), ZEN_DEF) == ZEN_DEF
          and gui._dialog_start_folder('', ZEN_DEF) == ZEN_DEF
          and gui._dialog_start_folder('', os.path.join(TMP, 'none')) == home
          and gui._dialog_start_folder('', '') == home)
    for click, field, folder in ((gui.load_ref_images_path_clicked, mw.reference_images_lineEdit, REF),
                                 (gui.load_zen_saving_path_clicked, mw.Zen_saving_folder_lineEdit, ZEN)):
        starts = []
        for text in (folder, os.path.join(TMP, 'missing'), ''):
            field.setText(text); DIALOGS.clear(); click(); starts.append(DIALOGS[-1][1] if DIALOGS else None)
        logic.default_zen_path = os.path.join(TMP, 'none'); field.setText(''); DIALOGS.clear(); click()
        starts.append(DIALOGS[-1][1] if DIALOGS else None); logic.default_zen_path = ZEN_DEF
        check(f'({click.__name__}) start folder: field folder, default zen path (missing / empty field), home',
              starts == [folder, ZEN_DEF, ZEN_DEF, home], starts)
    QtWidgets.QFileDialog.getExistingDirectory = ORIGINAL_DIALOG

    # ------------------------------------------------------------------ sample tag in the GUI
    gui.start_new_experiment_config('roi_multicolor_scan'); app.processEvents()
    check('(roi_multicolor_scan) items DAPI, RNA, IF, Free; default DAPI in the combo and the configuration; label and '
          'combo shown, line edit hidden and disabled',
          [combo.itemText(k) for k in range(combo.count())] == ['DAPI', 'RNA', 'IF', 'Free']
          and combo.currentText() == 'DAPI' and logic.config_dict.get('sample_tag') == 'DAPI'
          and shown(mw.sample_tag_label) and shown(combo) and not shown(edit) and not edit.isEnabled(),
          (combo.currentText(), logic.config_dict.get('sample_tag'), shown(edit), edit.isEnabled()))
    combo.setCurrentText('Free'); app.processEvents()
    free_on = shown(edit) and edit.isEnabled()
    edit.setText('RT1'); app.processEvents()
    check('Free: line edit shown and enabled; typed tag stored in the configuration',
          free_on and logic.config_dict.get('sample_tag') == 'RT1' and combo.currentText() == 'Free',
          logic.config_dict.get('sample_tag'))
    edit.setText('DAPI-2'); app.processEvents()
    check("free tag 'DAPI-2' typed letter by letter keeps 'Free' selected",
          combo.currentText() == 'Free' and edit.text() == 'DAPI-2' and logic.config_dict.get('sample_tag') == 'DAPI-2')
    combo.setCurrentText('IF'); app.processEvents()
    check('IF: stored, line edit hidden and disabled',
          logic.config_dict.get('sample_tag') == 'IF' and not shown(edit) and not edit.isEnabled())
    validator = edit.validator()
    accept = QtGui.QValidator.State.Acceptable
    states = {t: validator.validate(t, 0)[0] for t in ('RT 1', 'RT_1', 'RT1', 'IF-2')}
    check("validator: rejects 'RT 1' and 'RT_1', accepts 'RT1' and 'IF-2'",
          states['RT 1'] != accept and states['RT_1'] != accept and states['RT1'] == accept and states['IF-2'] == accept,
          states)
    logic.update_sample_tag('RNA')
    check('logic update_sample_tag stores the tag; GUI follows', logic.config_dict.get('sample_tag') == 'RNA'
          and combo.currentText() == 'RNA')

    # ------------------------------------------------------------------ save
    out = os.path.join(TMP, 'out')
    # other required fields filled: only the sample tag decides
    for required in ('sample_name', 'roi_list_path', 'zen_saving_path', 'save_path'):
        logic.config_dict[required] = logic.config_dict.get(required) or TMP
    logic.config_dict['imaging_sequence'] = logic.config_dict.get('imaging_sequence') or [['488 nm', 10.0]]
    for bad in ('', 'RT_1', 'RT 1'):
        LOGS.clear(); logic.update_sample_tag(bad)
        logic.save_to_exp_config_file(out, 'roi_multicolor_scan', filename='bad.yml')
        errors = [m for lvl, m in LOGS if lvl >= logging.ERROR and 'not saved' in m]
        check(f'save refused with sample_tag {bad!r} (log error, no file)',
              errors and 'sample_tag' in errors[-1] and not os.path.exists(os.path.join(out, 'bad.yml')), errors)
    logic.update_sample_tag('RT1'); LOGS.clear()
    logic.save_to_exp_config_file(out, 'roi_multicolor_scan', filename='good.yml')
    saved = yaml.safe_load(open(os.path.join(out, 'good.yml'))) if os.path.exists(os.path.join(out, 'good.yml')) else {}
    check('save with a valid free tag writes sample_tag, no dapi / rna key',
          saved.get('sample_tag') == 'RT1' and 'dapi' not in saved and 'rna' not in saved,
          (saved, [m for _, m in LOGS]))

    # ------------------------------------------------------------------ load
    def load(name, **values):
        data = dict(saved); data.pop('sample_tag', None); data.update(values)
        path = os.path.join(TMP, name); yaml.safe_dump(data, open(path, 'w')); LOGS.clear()
        logic.load_config_file(path); app.processEvents()
    load('free.yml', sample_tag='RT1')
    check("load sample_tag 'RT1': Free selected, line edit 'RT1' shown and enabled",
          combo.currentText() == 'Free' and edit.text() == 'RT1' and shown(edit) and edit.isEnabled()
          and logic.config_dict.get('sample_tag') == 'RT1')
    load('rna.yml', sample_tag='RNA')
    check("load sample_tag 'RNA': item RNA, line edit hidden", combo.currentText() == 'RNA' and not shown(edit))
    for fname_old, values, expected in (('old_dapi.yml', {'dapi': True, 'rna': False}, 'DAPI'),
                                         ('old_rna.yml', {'dapi': False, 'rna': True}, 'RNA'),
                                         ('old_none.yml', {'dapi': False, 'rna': False}, 'DAPI')):
        if expected == 'DAPI' and fname_old == 'old_none.yml':
            combo.setCurrentText('IF'); app.processEvents()
        load(fname_old, **values)
        warned = [m for lvl, m in LOGS if lvl == logging.WARNING and 'dapi / rna' in m]
        check(f'load former file {values}: {expected}, warning in the log, dapi / rna dropped',
              combo.currentText() == expected and logic.config_dict.get('sample_tag') == expected and warned
              and 'dapi' not in logic.config_dict and 'rna' not in logic.config_dict,
              (combo.currentText(), logic.config_dict.get('sample_tag'), warned))

    gui.start_new_experiment_config('him_epi_sd'); app.processEvents()
    check('(him_epi_sd, no sample_tag) sample tag widgets hidden',
          not shown(mw.sample_tag_label) and not shown(combo) and not shown(edit))
    logging.getLogger().removeHandler(handler)
    KEEP_ALIVE.append(locals())  # modules, threads and widgets of the section live until the end
    return results

# --- sample file: helper, configurator, sample dialog ---
def _section_sample_file():
    """Sample file (qudi.tasks.common.sample_info): repository template, template validation, required fields,
    save / load; configurator options 'default sample path' / 'sample template', field sample_file and its
    widgets; sample dialog (qudi.gui.experiments_setup.sample_dialog). File / message dialogs replaced by
    recorders."""
    import os, weakref, importlib, tempfile, logging
    from qtpy import QtCore, QtWidgets
    import yaml
    from qudi.core.connector import Connector
    from qudi.tasks.common import sample_info as si
    from qudi.gui.experiments_setup import sample_dialog as sd

    results = []
    def check(label, cond, detail=''):
        results.append((label, bool(cond))); print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)
    TMP = tempfile.mkdtemp()
    TEMPLATE = os.path.join(repo, 'custom_config', 'custom_metadata_templates', 'sample_template.yml')

    # ------------------------------------------------------------------ helper
    template = si.load_sample_template(TEMPLATE)
    names = [f['name'] for f in template]
    check('repository template: 20 fields in file order; types / choices / min-max / required as written',
          len(template) == 20 and names[:3] == ['experiment_type', 'organism', 'sample_type'] and names[-1] == 'project'
          and template[8] == {'name': 'formamide_percent', 'type': 'number', 'choices': [], 'min': 0, 'max': 100,
                              'required': False}
          and [f['name'] for f in template if f['required']] == ['experiment_type', 'organism', 'sample_type',
                                                                  'experimenter']
          and template[7]['choices'] == ['4% PFA'], names)
    bad_cases = {'unknown type': 'a: {type: date}\n', 'min > max': 'a: {type: number, min: 5, max: 1}\n',
                 'choices not a list': 'a: {type: choice, choices: DAPI}\n', 'unknown key': 'a: {type: text, size: 3}\n',
                 'not a mapping': '- a\n- b\n'}
    errors = {}
    for label, text in bad_cases.items():
        path = os.path.join(TMP, f'bad_{len(errors)}.yml'); open(path, 'w').write(text)
        try:
            si.load_sample_template(path); errors[label] = None
        except ValueError as err:
            errors[label] = str(err)
    check('invalid templates -> ValueError with a clear message (unknown type, min > max, choices, key, layout)',
          all(errors.values()) and 'date' in errors['unknown type'] and 'min (5)' in errors['min > max'], errors)
    values = {'experiment_type': 'DNA-FISH', 'organism': '', 'sample_type': None, 'experimenter': 'X'}
    check('missing_required: empty / absent required fields, in template order',
          si.missing_required(template, values) == ['organism', 'sample_type'], si.missing_required(template, values))
    path = os.path.join(TMP, 'sample.yml')
    saved = {'organism': 'Mus musculus', 'experiment_type': 'RNA-FISH', 'formamide_percent': 50,
             'old_field': 'kept', 'genotype': 'yw; +/+ é'}
    si.save_sample_file(path, saved)
    loaded = si.load_sample_file(path)
    check('save then load: same values, same order, field not in the template kept, unicode kept',
          loaded == saved and list(loaded) == list(saved) and 'é' in open(path, encoding='utf-8').read(), loaded)
    errs = []
    for p, text in ((os.path.join(TMP, 'none.yml'), None), (os.path.join(TMP, 'list.yml'), '- a\n')):
        if text is not None:
            open(p, 'w').write(text)
        try:
            si.load_sample_file(p); errs.append(None)
        except RuntimeError as err:
            errs.append(str(err))
    check('load_sample_file: missing file / not a mapping -> RuntimeError', all(errs) and 'does not exist' in errs[0], errs)

    # ------------------------------------------------------------------ configurator
    LOGS = []
    class H(logging.Handler):
        def emit(self, r): LOGS.append((r.levelno, r.getMessage()))
    handler = H(); logging.getLogger().addHandler(handler)
    class FakeMain(QtCore.QObject): pass
    MAIN = FakeMain()
    CFG = yaml.safe_load(open(os.path.join(repo, 'custom_config/dummy_config.cfg')))
    DEF_SAMPLE = os.path.join(TMP, 'samples'); os.makedirs(DEF_SAMPLE)
    MODS = {}
    def build(name):
        if name in MODS: return MODS[name]
        base = next(b for b in ('hardware', 'logic', 'gui') if name in (CFG.get(b) or {}))
        entry = CFG[base][name]; mod, cls = entry['module.Class'].rsplit('.', 1)
        klass = getattr(importlib.import_module(f'qudi.{base}.{mod}'), cls)
        opts = _short.module_options(name, entry.get('options'))
        if name == 'experiments_configurator_logic':
            opts['experiment_definitions_directory'] = os.path.join(repo, 'custom_config/custom_experiments_config/spinning_disk') + '/'
            opts['experiments'] = ['roi_multicolour_scan.yaml', 'him_epi.yaml', 'photobleaching.yaml']
            opts['default sample path'] = DEF_SAMPLE; opts['sample template'] = TEMPLATE
        m = klass(qudi_main_weakref=weakref.ref(MAIN), name=name, config=opts)
        by_name = {c.name: c for k in dir(klass) if isinstance(c := getattr(klass, k, None), Connector)}
        for key, target in (entry.get('connect') or {}).items():
            m._meta['connectors'][next(k for k in m._meta['connectors'] if by_name[key] is getattr(klass, k))].connect(build(target))
        m.module_state.activate(); MODS[name] = m; return m
    gui = build('experiments_configurator_gui'); app.processEvents()
    mw, logic = gui._mw, gui._exp_logic
    sd_cfg = yaml.safe_load(open(os.path.join(repo, 'custom_config/Spinning_disk_config.cfg')))
    sd_opts = sd_cfg['logic']['experiments_configurator_logic']['options']
    check("options 'default sample path' / 'sample template' read; SD configuration sets both",
          logic.default_sample_path == DEF_SAMPLE and logic.sample_template_path == TEMPLATE
          and sd_opts.get('default sample path') == '/home/him_spinning/qudi/qudi_sample_preparation/'
          and sd_opts.get('sample template', '').endswith('custom_config/custom_metadata_templates/sample_template.yml'))
    widgets = (mw.sample_prep_label, mw.sample_prep_lineEdit, mw.sample_prep_load_pushButton, mw.sample_prep_edit_pushButton)
    def shown(w): return not w.isHidden()
    for exp, visible in (('roi_multicolor_scan', True), ('him_epi_sd', True), ('photobleaching', False)):
        gui.start_new_experiment_config(exp); app.processEvents()
        check(f'({exp}) sample file widgets {"shown" if visible else "hidden"}', all(shown(w) == visible for w in widgets))
    gui.start_new_experiment_config('roi_multicolor_scan'); app.processEvents()
    logic.update_sample_file(path)
    check('update_sample_file stores the path; the line edit follows', logic.config_dict.get('sample_file') == path
          and mw.sample_prep_lineEdit.text() == path)
    mw.sample_prep_lineEdit.setText('')
    check('line edit -> logic (empty)', logic.config_dict.get('sample_file') == '')

    OPENS, SAVES, BOXES = [], [], []
    answers = {'open': '', 'save': ''}
    originals = (QtWidgets.QFileDialog.getOpenFileName, QtWidgets.QFileDialog.getSaveFileName, QtWidgets.QMessageBox.warning)
    QtWidgets.QFileDialog.getOpenFileName = staticmethod(lambda parent, caption='', directory='', *a, **k: (OPENS.append(directory), (answers['open'], ''))[1])
    QtWidgets.QFileDialog.getSaveFileName = staticmethod(lambda parent, caption='', directory='', *a, **k: (SAVES.append(directory), (answers['save'], ''))[1])
    QtWidgets.QMessageBox.warning = staticmethod(lambda parent, title, text, *a, **k: BOXES.append((title, text)))
    try:
        gui.load_sample_file_clicked()
        answers['open'] = path; gui.load_sample_file_clicked()
        first, second = OPENS[0], OPENS[1]
        mw.sample_prep_lineEdit.setText(os.path.join(TMP, 'gone', 'x.yml')); answers['open'] = ''; gui.load_sample_file_clicked()
        check('Load: start in default sample path (empty field), then the folder of the field; *.yml chosen fills the '
              'field; missing folder -> default sample path',
              first == DEF_SAMPLE and second == DEF_SAMPLE and OPENS[2] == DEF_SAMPLE and logic.config_dict['sample_file'] != path, OPENS)
        mw.sample_prep_lineEdit.setText(path); OPENS.clear(); gui.load_sample_file_clicked()
        check('Load: start in the folder of the file of the field', OPENS == [TMP], OPENS)

        # dialog opened by "Edit": exec replaced by a callback acting on the dialog
        ACTION = [None]; DIALOGS = []
        def fake_exec(dialog):
            DIALOGS.append(dialog)
            return ACTION[0](dialog) if ACTION[0] else 0
        orig_exec = sd.SampleDialog.exec
        sd.SampleDialog.exec = fake_exec
        # no / invalid template: warning box, no dialog; Load still works
        for label, value in (('not set', ''), ('invalid', os.path.join(TMP, 'bad_0.yml'))):
            logic.sample_template_path = value; BOXES.clear(); DIALOGS.clear(); gui.edit_sample_file_clicked()
            check(f'(Edit, template {label}) warning box, no dialog', BOXES and BOXES[0][0] == 'Sample template' and not DIALOGS, BOXES)
        logic.sample_template_path = TEMPLATE
        # existing file: form filled, value not in the choices shown as typed text, extra field kept on Save
        si.save_sample_file(path, {'experiment_type': 'DNA-FISH', 'organism': 'Danio rerio', 'sample_type': 'embryo',
                                   'experimenter': 'X', 'old_field': 'kept'})
        mw.sample_prep_lineEdit.setText(path)
        def inspect(d):
            w = d.widgets
            ACTION.append({'organism': w['organism'].currentText(), 'formamide': w['formamide_percent'].text(),
                           'save_enabled': d.save_button.isEnabled(), 'label': d.findChildren(QtWidgets.QLabel)[0].text()})
            return 0
        ACTION[0] = inspect; gui.edit_sample_file_clicked(); info = ACTION.pop()
        check('(Edit, existing file) form filled; value not in the choices shown as typed text; empty number field '
              f'shown as {sd.EMPTY_NUMBER_TEXT!r}; Save enabled; required field labelled with "*"',
              info['organism'] == 'Danio rerio' and info['formamide'] == sd.EMPTY_NUMBER_TEXT and info['save_enabled']
              and info['label'] == 'experiment type *', info)
        def save_with_number(d):
            d.widgets['formamide_percent'].setValue(40); return 1 if d.save() else 0
        ACTION[0] = save_with_number; gui.edit_sample_file_clicked()
        again = si.load_sample_file(path)
        check('(Edit, Save) file overwritten: number 40, field not in the template kept, empty optional fields None',
              again.get('formamide_percent') == 40 and again.get('old_field') == 'kept' and again.get('genotype') is None
              and again.get('organism') == 'Danio rerio', again)
        def clear_number_and_save(d):
            d.widgets['formamide_percent'].setValue(d.widgets['formamide_percent'].minimum()); return 1 if d.save() else 0
        ACTION[0] = clear_number_and_save; gui.edit_sample_file_clicked()
        check('(Edit, Save) a number field can be emptied again (None in the file)',
              si.load_sample_file(path).get('formamide_percent') is None)
        # new sample: Save disabled, Save refused while a required field is empty, Save as writes (.yml added)
        mw.sample_prep_lineEdit.setText('')
        def new_sample(d):
            ACTION.append(d.save_button.isEnabled())
            BOXES.clear(); answers['save'] = os.path.join(TMP, 'new_sample')
            refused = not d.save_as() and BOXES and 'experiment type' in BOXES[-1][1] and 'experimenter' in BOXES[-1][1]
            ACTION.append(bool(refused) and not os.path.exists(os.path.join(TMP, 'new_sample.yml')))
            d.widgets['experiment_type'].setCurrentText('IF'); d.widgets['organism'].setCurrentText('Homo sapiens')
            d.widgets['sample_type'].setCurrentText('cells'); d.widgets['experimenter'].setText('X')
            return 1 if d.save_as() else 0
        ACTION[0] = new_sample; SAVES.clear(); gui.edit_sample_file_clicked()
        refused, save_enabled = ACTION.pop(), ACTION.pop()
        new_path = os.path.join(TMP, 'new_sample.yml')
        new_values = si.load_sample_file(new_path) if os.path.exists(new_path) else {}
        check('(Edit, new sample) Save disabled; Save as refused while required fields are empty (box lists them); '
              'Save as writes <name>.yml in template order, starting in default sample path; the line edit shows it',
              not save_enabled and refused and list(new_values) == names and new_values['experiment_type'] == 'IF'
              and SAVES and SAVES[0] == DEF_SAMPLE and mw.sample_prep_lineEdit.text() == new_path
              and logic.config_dict.get('sample_file') == new_path, (save_enabled, refused, SAVES, new_values))
        sd.SampleDialog.exec = orig_exec
    finally:
        (QtWidgets.QFileDialog.getOpenFileName, QtWidgets.QFileDialog.getSaveFileName,
         QtWidgets.QMessageBox.warning) = (staticmethod(originals[0]), staticmethod(originals[1]), staticmethod(originals[2]))
    logging.getLogger().removeHandler(handler)
    KEEP_ALIVE.append(locals())  # modules, threads and widgets of the section live until the end
    return results

# --- autofocus report (qudi.util.autofocus_report) ---
def _section_autofocus_report():
    """Autofocus report of Hi-M runs (qudi.util.autofocus_report): synthetic metadata folders (4 ROIs x 3 cycles) of
    the qudi-core task (correlation.npy cycles x ROIs + autofocus_scores.csv) and of the legacy software (probes x
    ROIs, no CSV), one run (report_run) and several runs (summarize_folder)."""
    import csv, logging, os, tempfile
    import numpy as np
    import yaml
    from qudi.util import autofocus_report as ar

    results = []

    def check(label, cond, detail=''):
        results.append((label, bool(cond)))
        print(f'[{"PASS" if cond else "FAIL"}] {label} {detail if not cond else ""}', flush=True)

    TMP = tempfile.mkdtemp()
    LOGS = []

    class H(logging.Handler):
        def emit(self, r):
            LOGS.append((r.levelno, r.getMessage()))

    log = logging.getLogger('qudi.tests.autofocus_report')
    log.setLevel(logging.INFO)
    log.addHandler(H())
    ROIS = ['ROI_000', 'ROI_001', 'ROI_002', 'ROI_003']

    def run_folder(name, probes, corr, threshold=None, scores=None, rois=ROIS):
        """<TMP>/<name>/metadata with HiM_parameters.yml, correlation.npy and (scores: list of rows)
        autofocus_scores.csv."""
        folder = os.path.join(TMP, name, 'metadata')
        os.makedirs(folder)
        params = {'1- global parameters': {'sample_name': 'S'}, '2- fluidic parameters': {'probes': probes},
                  '4- ROIs': {roi: f'X={k} - Y=0 - Z=None' for k, roi in enumerate(rois)}}
        if threshold is not None:
            params['1- global parameters']['correlation_threshold'] = threshold
        yaml.safe_dump(params, open(os.path.join(folder, 'HiM_parameters.yml'), 'w'), sort_keys=False)
        np.save(os.path.join(folder, 'correlation.npy'), np.asarray(corr, dtype=float))
        if scores is not None:
            with open(os.path.join(folder, 'autofocus_scores.csv'), 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['cycle', 'RT', 'roi', 'score', 'shift_y_px', 'shift_x_px', 'passed'])
                writer.writerows(scores)
        return folder

    def summary_rows(path):
        return list(csv.DictReader(open(path, newline='')))

    rng = np.random.default_rng(1)
    corr_new = rng.uniform(0.6, 1.0, (3, 4))          # cycles x ROIs
    cycle_rt = {1: 'RT3', 2: 'RT1', 3: 'RT2'}          # order of the run (RT column)
    scores = [(c, cycle_rt[c], roi, f'{corr_new[c - 1, k]:.6f}', c * k, -c, True)
              for c in (1, 2, 3) for k, roi in enumerate(ROIS)]
    new = run_folder('new_run', {1: 'RT1', 2: 'RT2', 3: 'RT3'}, corr_new, threshold=0.8, scores=scores)

    seen = {}
    original_heatmap = ar._heatmap

    def spy_heatmap(corr, rois, labels, path, vmin, vmax, threshold, title):
        seen.update(threshold=threshold, labels=list(labels), shape=corr.shape)
        return original_heatmap(corr, rois, labels, path, vmin, vmax, threshold, title)

    ar._heatmap = spy_heatmap
    try:
        written = ar.report_run(new, log=log)
    finally:
        ar._heatmap = original_heatmap
    names = sorted(os.path.basename(p) for p in written)
    rows = summary_rows(os.path.join(new, ar.SUMMARY_NAME))
    check('(report_run, qudi-core run) writes the heatmap, the CSV and the drift figure in the metadata folder',
          names == sorted([ar.HEATMAP_NAME, ar.SUMMARY_NAME, ar.DRIFT_NAME])
          and all(os.path.getsize(p) > 0 for p in written), names)
    check('(report_run) probe labels from the RT column of autofocus_scores.csv (RT3, RT1, RT2), not the probes dict '
          'order; the threshold is read from the parameters (0.8); heatmap ROIs x probes',
          seen.get('labels') == ['RT3', 'RT1', 'RT2'] and seen.get('threshold') == 0.8 and seen.get('shape') == (4, 3),
          seen)
    check('(report_run) CSV: one row per ROI / probe (experiment_folder, roi_name, probe_name, correlation), the '
          'scores of correlation.npy',
          len(rows) == 12 and list(rows[0]) == ['experiment_folder', 'roi_name', 'probe_name', 'correlation']
          and rows[0]['roi_name'] == 'ROI_000' and rows[0]['probe_name'] == 'RT3'
          and abs(float(rows[0]['correlation']) - corr_new[0, 0]) < 1e-12
          and rows[0]['experiment_folder'] == os.path.join(TMP, 'new_run'), rows[:2])

    # legacy run: probes x ROIs, no autofocus_scores.csv
    LOGS.clear()
    legacy = run_folder('legacy_run', {'2': 'RT2', '1': 'RT1', '3': 'RT3'}, rng.uniform(0.6, 1.0, (3, 4)))
    written = ar.report_run(legacy, log=log)
    rows = summary_rows(os.path.join(legacy, ar.SUMMARY_NAME))
    check('(report_run, legacy run) heatmap and CSV, no drift figure; probes in key order (RT1, RT2, RT3) with a note '
          'that the order is assumed; threshold 0.7 by default',
          sorted(os.path.basename(p) for p in written) == sorted([ar.HEATMAP_NAME, ar.SUMMARY_NAME])
          and not os.path.exists(os.path.join(legacy, ar.DRIFT_NAME))
          and [r['probe_name'] for r in rows[:3]] == ['RT1', 'RT2', 'RT3']
          and any('order assumed' in m for _, m in LOGS) and ar.load_run(legacy, log)['threshold'] is None,
          (written, LOGS))

    # aborted run: NaN for the checks not done
    corr_abort = corr_new.copy()
    corr_abort[1, 2:] = np.nan
    corr_abort[2, :] = np.nan
    aborted = run_folder('aborted_run', {1: 'RT1', 2: 'RT2', 3: 'RT3'}, corr_abort, threshold=0.6,
                         scores=[row for row in scores if row[0] == 1 or (row[0] == 2 and row[2] in ROIS[:2])])
    try:
        written = ar.report_run(aborted, log=log)
        abort_err = None
    except Exception as err:
        written, abort_err = [], err
    check('(report_run, aborted run with NaN) no error, heatmap / CSV / drift written (labels of the cycles without '
          'any check from the probes)', abort_err is None and len(written) == 3
          and all(os.path.isfile(p) for p in written), abort_err)

    # label count mismatch
    mismatch = run_folder('mismatch_run', {1: 'RT1', 2: 'RT2'}, rng.uniform(0.6, 1.0, (3, 4)))
    try:
        ar.report_run(mismatch, log=log)
        mismatch_err = None
    except ValueError as err:
        mismatch_err = err
    check('(report_run) 2 probe labels for 3 cycles -> clear ValueError', mismatch_err is not None
          and '2 probe label(s) for the 3 cycle(s)' in str(mismatch_err), mismatch_err)

    # several runs
    root = os.path.join(TMP, 'experiment')
    for k in (1, 2):
        os.makedirs(os.path.join(root, f'run_{k}'))
    run_a = run_folder(os.path.join('experiment', 'run_1'), {1: 'RT1', 2: 'RT2', 3: 'RT3'}, corr_new, 0.8, scores)
    run_b = run_folder(os.path.join('experiment', 'run_2'), {1: 'RT4', 2: 'RT5'}, rng.uniform(0.6, 1.0, (2, 4)), 0.8,
                       [(c, f'RT{c + 3}', roi, '0.9', 0, 0, True) for c in (1, 2) for roi in ROIS])
    LOGS.clear()
    written = ar.summarize_folder(root, log=log)
    rows = summary_rows(os.path.join(root, ar.SUMMARY_NAME))
    check('(summarize_folder) two runs, same ROIs: one global heatmap and CSV in the root folder; 5 probes "<probe> | '
          '<experiment folder>"; no warning',
          sorted(written) == sorted([os.path.join(root, ar.HEATMAP_NAME), os.path.join(root, ar.SUMMARY_NAME)])
          and all(os.path.isfile(p) for p in written) and len(rows) == 4 * 5
          and not any(lvl >= logging.WARNING for lvl, _ in LOGS), (written, len(rows), LOGS))
    run_folder(os.path.join('experiment', 'run_3'), {1: 'RT6'}, rng.uniform(0.6, 1.0, (1, 4)))  # legacy score
    LOGS.clear()
    ar.summarize_folder(root, log=log)
    check('(summarize_folder) runs with and without autofocus_scores.csv -> warning: the scores are not on the same scale',
          any(lvl == logging.WARNING and 'not on the same scale' in m for lvl, m in LOGS), LOGS)
    other = os.path.join(TMP, 'other_experiment')
    run_folder(os.path.join('other_experiment', 'a'), {1: 'RT1'}, rng.uniform(0.6, 1.0, (1, 4)))
    run_folder(os.path.join('other_experiment', 'b'), {1: 'RT1'}, rng.uniform(0.6, 1.0, (1, 3)), rois=ROIS[:3])
    try:
        ar.summarize_folder(other, log=log)
        roi_err = None
    except ValueError as err:
        roi_err = err
    check('(summarize_folder) runs with different ROIs -> ValueError (ROI mismatch)',
          roi_err is not None and 'ROI mismatch' in str(roi_err), roi_err)
    KEEP_ALIVE.append(locals())
    return results


SECTIONS = [
    ('data folders in the logic', _section_data_folders),
    ('random ROI list helper', _section_random_roi_list),
    ('configurator: local / server folder buttons', _section_folder_buttons),
    ('configurator: sample tag and ZEN folder dialogs', _section_sample_tag),
    ('sample file: helper, configurator, sample dialog', _section_sample_file),
    ('autofocus report', _section_autofocus_report),
]

if __name__ == '__main__':
    all_results = []
    for title, run_section in SECTIONS:
        print(f'\n# --- {title} ---', flush=True)
        all_results += run_section()
    print(f'\n{sum(ok for _, ok in all_results)}/{len(all_results)} passed', flush=True)
    os._exit(0 if all(ok for _, ok in all_results) else 1)
