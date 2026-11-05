# Testing rules

These rules apply by default to every task in this repository, unless a prompt says otherwise.

1. **Reference version: qudi-core 1.8** (the version installed on the microscopes). Run all tests on
   1.8 only. Do not test on 1.7 any more unless a prompt asks for it.
2. **Short dummy settings for every task test:**
   - injections of 5 µl, incubations of 1 s, needle rinse 1 s, dummy imaging 0.2 s;
   - 2 ROIs and 2 probes;
   - dedicated test injections / experiment / ROI list files, kept in one test-data folder in the
     repo (`tests/data/`) and reused across tests;
   - shorten durations by overriding the class attributes in the test (e.g.
     `needle_rinsing_duration_s`, `dummy_imaging_time_s`, progress / poll intervals), never by
     changing the real defaults or the configs used on the microscopes.
3. Run only the tests needed for the change described in the prompt. Do not run the full regression
   suites unless the prompt explicitly asks for them (e.g. 'run full tests').
4. **What is checked** is the order and synchronization of the hardware calls (valves, needle,
   pressure regulation start/stop, ZEN triggers, stage moves, GUI locks, cleanup after interrupt or
   error), not durations.
5. **Pure logic with no hardware timing** (e.g. parsing an injections file, choosing the probe
   valve, path optimization) is tested by calling the functions directly with stand-in objects,
   without running a task.

## Where things are

- `tests/run_suites.py` - runs the regression suites one after the other (offscreen Qt) and prints
  pass / fail and the run time of each: `python tests/run_suites.py` (all) or
  `python tests/run_suites.py him roi_path` (suites whose file name contains one of the words).
- `tests/_short.py` - the short settings (volumes, times, number of ROIs / probes), `shorten(task)`
  to set them on a task instance, and helpers to load the shared test data.
- `tests/data/` - shared test files: injections files (fluidics, Hi-M), experiment templates
  (fluidics, Hi-M, ROI scan, photobleaching) and a 2-ROI list.
- Also in `tests/_short.py`, applied by every suite to the modules it builds, never to the classes
  or `dummy_config.cfg`:
  - `module_options()`: short poll / sampling intervals (flow logic, robot logic, dummy stage);
  - `speed_up()`: no 1 s wait of the dummy valve at each move;
  - Hi-M test injections at 1000 µl/min, which shortens the dummy regulation ramp.
- Exceptions, where a check needs more:
  - a 3 s incubation for the runs that check the live countdown (`COUNTDOWN_INCUBATION_S`);
  - 5 ROIs in the start ROI section of `test_roi_scan.py`, whose checks start at the 3rd ROI and
    interrupt during the 4th.
- Each suite runs on its own: `python tests/test_<name>.py` (repository root by default). A few
  suites also compare with a former version of a module (a copy of that file given after the
  repository root); without it those comparisons are reported as `[SKIP]`.

## Organisation

One suite per component in `tests/`, one section per feature inside a suite (a
`# --- <feature> ---` header, also printed when the suite runs):

- `test_roi_path.py` - ROI path optimization: open path and closed tour (`qudi.util.roi_path`),
  the "optimize path" action of the ROI logic / GUI.
- `test_logic_helpers.py` - data folders defined in the logic modules (ROI lists, injections
  files), the random ROI list command-line helper and the local / server folder buttons of the
  experiment configurator.
- `test_task_runner.py` - Task Runner logic / GUI / task widget: progress display, parameter
  hints (placeholder, tooltip), start / end warning dialogs.
- `test_photobleaching.py` - photobleaching task: hardware calls, progress display, dialogs.
- `test_roi_scan.py` - ROI scan task: progress display, start ROI, ZEN settings pop-up of the
  spinning disk, run folder on the server or local folder and run files (experiment copy,
  metadata.yml) - ROI scan and Hi-M.
- `test_fluidics.py` - fluidics task: options, sequence, interrupt, validation and hardware
  errors, needle position, probe valve read from the injections file.
- `test_him.py` - Hi-M task: run files (experiment copy, metadata.yml), number of z planes (not
  used on the SD, still required by the dummy; also the configurator field), SD folder named after
  the ZEN data folder and HiM_task.log, autofocus check of the SD (score, abort rule, wait loop), online
  data transfer (DataTransfer; Hi-M SD transfer cases in the `sd_zen_folder` block) - the words
  `metadata` / `sd_z_planes` / `sd_zen_folder` / `autofocus` / `transfer` run only these blocks -, cycles, progress, interrupt, errors, needle modes, SD (fake ZEN),
  RAMM placeholder, probe valve read from the injections file.

Rule: a change adds or adapts cases in the existing suite of the component it touches; a new file
only for a new component; quick checks made during development are not committed unless they
guard against a bug that could come back.

The checks done on the microscopes with the real hardware are listed in `docs/test_plan.md`
(hardware checklist).
