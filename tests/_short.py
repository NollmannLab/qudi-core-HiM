"""Short test settings and shared test data for the test suites of tests/ (see docs/TESTING.md).

The durations are shortened by overriding class attributes on the task instance created by a test
(shorten), never by changing the class defaults or the microscope configs. The test data (injections
files, ROI list, experiment templates) live in tests/data/ and are reused by every suite.

Modified with Claude code (Anthropic)
"""
import copy
from time import sleep
import json
import os

import yaml

TESTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TESTS)
DATA = os.path.join(TESTS, 'data')

INJECTION_UL = 5        # volume of every injection of the test injections files
INCUBATION_S = 1        # incubation time of the test injections files
RINSE_S = 1.0           # needle rinse
IMAGING_S = 0.2         # dummy imaging time per ROI
N_ROIS = 2              # ROIs of tests/data/rois_2.json
N_PROBES = 2            # probes of the test injections files
VALVE_MOVE_S = 0.01     # wait of the dummy valve at each move (speed_up)
HIM_FLOWRATE = 1000      # µl/min of the Hi-M test injections (dummy flow chain: shorter ramp than 200)
COUNTDOWN_INCUBATION_S = 3  # incubation of the runs that check the live countdown (two updates; 1 s gives one)

# task class attributes overridden on the task instance by shorten() (only those the task has)
TASK_ATTRIBUTES = {'needle_rinsing_duration_s': RINSE_S,
                   'dummy_imaging_time_s': IMAGING_S,
                   'volume_poll_interval_s': 0.1}

# module options overridden in the module configs built by the tests (poll / sampling intervals of the dummy
# setup; dummy_config.cfg itself is not changed)
MODULE_OPTIONS = {'fluidics_flow_logic': {'sampling_interval': 0.1},
                  'pipetting_robot_logic': {'movement_poll_interval': 0.05},
                  'dummy_translation_stage': {'delay_after_move': 0.02}}

FLUIDICS_INJECTIONS = os.path.join(DATA, 'fluidics_injections.yml')
HIM_INJECTIONS = os.path.join(DATA, 'him_injections.yml')
ROI_LIST = os.path.join(DATA, 'rois_2.json')


def repo_root(argv):
    """Repository root: first command-line argument if given, else the parent of tests/."""
    return os.path.abspath(argv[1]) if len(argv) > 1 and not argv[1].startswith('-') else REPO


def reference_files(argv, count):
    """Optional reference files given after the repository root (python tests/<suite>.py <repo_root>
    <file> ...): `count` absolute paths, None for each one not given. Suites that compare the behaviour
    with a former version of a module (a copy of that file) run those comparisons only when it is given."""
    files = [os.path.abspath(a) for a in argv[2:] if a != 'quick' and not a.startswith('-')]
    return (files + [None] * count)[:count]


def skipped(label, reason='reference file not given'):
    """Print the line of a comparison that is not run (does not count as a check)."""
    print(f'[SKIP] {label} ({reason})', flush=True)


def module_options(name, options):
    """Copy of the config options of module `name` with the short intervals of MODULE_OPTIONS."""
    return {**copy.deepcopy(dict(options or {})), **MODULE_OPTIONS.get(name, {})}


def speed_up(module):
    """Short waits on a dummy hardware instance built by a test (the class is not changed): DummyValve
    waits a fixed 1 s in wait_for_idle (called by the valve and by the valve logic at each move).
    Returns the module."""
    if type(module).__name__ == 'DummyValve':
        def wait_for_idle(poll_interval=0.2):
            sleep(VALVE_MOVE_S)
            return True
        module.wait_for_idle = wait_for_idle
    return module


def local_options(repo, options):
    """Copy of the options of a task entry of dummy_config.cfg for the tests: metadata_template (an absolute path
    on the dummy machine) points to the template of the same name in <repo>/custom_config/custom_metadata_templates."""
    options = dict(options or {})
    if options.get('metadata_template'):
        name = os.path.basename(str(options['metadata_template']).replace('\\', '/'))
        options['metadata_template'] = os.path.join(repo, 'custom_config', 'custom_metadata_templates', name)
    return options


def shorten(task, **extra):
    """Set the short durations of TASK_ATTRIBUTES (and extra attributes) on the task instance.
    Only attributes the task class defines are set. Returns the task."""
    for key, value in {**TASK_ATTRIBUTES, **extra}.items():
        if hasattr(type(task), key):
            setattr(task, key, value)
    return task


def with_incubation(injections, seconds):
    """Copy of an injections dict with every incubation step set to `seconds`."""
    content = copy.deepcopy(injections)
    for key in ('hybridization list', 'photobleaching list'):
        for step in content.get(key) or []:
            if step.get('product') is None:
                step['time'] = seconds
    return content


class AutoAnswer:
    """Answers the modal boxes of tasks/common/popups.py ask_confirmation from the GUI thread: every 20 ms,
    a visible QMessageBox whose window title is `title` gets its button `button_text` clicked. The texts
    of the answered boxes are kept in `texts`. Needs a QApplication; keep a reference while it is used."""

    def __init__(self, title, button_text='Done - continue'):
        from qtpy import QtCore, QtWidgets
        self.title, self.button_text, self.texts = title, button_text, []
        self._widgets = QtWidgets
        self._timer = QtCore.QTimer()
        self._timer.timeout.connect(self._poll)
        self._timer.start(20)

    def boxes(self):
        return [w for w in self._widgets.QApplication.topLevelWidgets()
                if isinstance(w, self._widgets.QMessageBox) and w.isVisible() and w.windowTitle() == self.title]

    def _poll(self):
        if self.button_text is None:
            return
        for box in self.boxes():
            for button in box.buttons():
                if button.text() == self.button_text:
                    self.texts.append(box.text())
                    button.click()
                    return

    def stop(self):
        self._timer.stop()


class ZenFolders:
    """Fake ZEN data folders for the spinning-disk tasks: `root` is the zen_saving_path of the test; each
    call of ready() (from a fake TriggerLogic when "trigger_ZEN_ready" is polled, i.e. when ZEN starts the
    experiment) creates a new folder there."""

    def __init__(self, root):
        self.root = root
        self.created = []
        os.makedirs(root, exist_ok=True)

    def ready(self):
        path = os.path.join(self.root, f'zen_experiment_{len(self.created) + 1:03d}')
        os.makedirs(path)
        self.created.append(path)
        return path


def load(path):
    """Fresh copy of a YAML / JSON test file (tests/data/<name> or a full path)."""
    path = path if os.path.isabs(path) else os.path.join(DATA, path)
    with open(path, encoding='utf-8') as stream:
        content = json.load(stream) if path.endswith('.json') else yaml.safe_load(stream)
    return copy.deepcopy(content)


def roi_names():
    """Names of the ROIs of the shared ROI list."""
    return [roi['name'] for roi in load(ROI_LIST)['rois']]


def experiment(folder, template, name, **updates):
    """Write <folder>/<name>_experiment.yaml from a template of tests/data/ and return its path.
    Values of keys ending in '_path' that name a file of tests/data/ become absolute paths;
    save_path (if the template has it) defaults to <folder>/data_<name>; updates override any key."""
    content = load(template)
    for key, value in list(content.items()):
        if key.endswith('_path') and isinstance(value, str) and os.path.exists(os.path.join(DATA, value)):
            content[key] = os.path.join(DATA, value)
    if 'save_path' in content and content['save_path'] in (None, ''):
        content['save_path'] = os.path.join(folder, f'data_{name}')
    content.update(updates)
    path = os.path.join(folder, f'{name}_experiment.yaml')
    with open(path, 'w', encoding='utf-8') as stream:
        yaml.safe_dump(content, stream)
    return path


# ---------------------------------------------------------------------------- autofocus check (Hi-M SD)
AUTOFOCUS_SIZE = (64, 64)   # size of the synthetic autofocus images of the task runs
AUTOFOCUS_MIN_FRACTION = 0.5  # autofocus_min_fraction of the SD experiment files of the tests


def autofocus_image(seed=0, shape=AUTOFOCUS_SIZE):
    """Synthetic brightfield-like image (smoothed noise), float."""
    import numpy as np
    from scipy.ndimage import gaussian_filter
    return gaussian_filter(np.random.default_rng(seed).random(shape), 2) * 1000.0


def write_autofocus_references(folder, n_rois, image=None):
    """<folder>/autofocus_reference.npy with n_rois copies of image (default autofocus_image())."""
    import numpy as np
    os.makedirs(folder, exist_ok=True)
    image = autofocus_image() if image is None else image
    np.save(os.path.join(folder, 'autofocus_reference.npy'), np.stack([image] * n_rois))
    return folder


def write_autofocus_image(zen_folder, number, image=None):
    """What ZEN saves at the end of its autofocus block: <zen_folder>/autofocus/x_AcquisitionBlock1_pt<number>.czi
    (here the image as .npy content, read by read_npy_image)."""
    import numpy as np
    folder = os.path.join(zen_folder, 'autofocus')
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f'experiment_AcquisitionBlock1_pt{number}.czi')
    with open(path, 'wb') as f:
        np.save(f, autofocus_image() if image is None else image)
    return path


def read_npy_image(path):
    """Stand-in of autofocus_check.read_autofocus_image for the test images (no czifile)."""
    import numpy as np
    with open(path, 'rb') as f:
        return np.load(f)


real_read_autofocus_image = None  # autofocus_check.read_autofocus_image before use_npy_autofocus_images


def use_npy_autofocus_images():
    """The task reads the test autofocus images with read_npy_image: installed in the shared module (reads done in
    the test process) and, as HiMSDTask._af_worker, read_and_score_npy (reads done in its helper process)."""
    global real_read_autofocus_image
    from qudi.tasks.common import autofocus_check
    from qudi.tasks import him
    if real_read_autofocus_image is None:
        real_read_autofocus_image = autofocus_check.read_autofocus_image
    autofocus_check.read_autofocus_image = read_npy_image
    him.HiMSDTask._af_worker = staticmethod(read_and_score_npy)


# --- jobs of the helper process of HiMSDTask (module-level: pickled by name, run in a fresh process) ---
def read_and_score_npy(path, ref):
    """Stand-in of autofocus_check.read_and_score for the test images (.npy content)."""
    from qudi.tasks.common.autofocus_check import autofocus_score
    image = read_npy_image(path)
    score, shift_y, shift_x = autofocus_score(ref, image)
    return score, shift_y, shift_x, image


def read_and_score_failing(path, ref):
    """Raises OSError while <path>.failures holds a number > 0 (decremented at each call), then read_and_score_npy."""
    counter = path + '.failures'
    left = int(open(counter).read()) if os.path.exists(counter) else 0
    if left > 0:
        with open(counter, 'w') as f:
            f.write(str(left - 1))
        raise OSError('file still being written (test)')
    return read_and_score_npy(path, ref)


def helper_exit(path, ref):
    """The helper process dies (as after a native crash of the reader)."""
    os._exit(1)


def helper_exit_once(path, ref):
    """The helper process dies the first time (marker <path>.crashed), then read_and_score_npy."""
    marker = path + '.crashed'
    if not os.path.exists(marker):
        open(marker, 'w').close()
        os._exit(1)
    return read_and_score_npy(path, ref)


def helper_sleep(path, ref):
    """A job that never ends in time (stuck read)."""
    sleep(60)

