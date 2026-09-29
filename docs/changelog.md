# Changelog

This file records the main changes made to the project.

## [Unreleased]

Last updated: 2026-09-29

### Cameras

#### Added

- Completed the Hamamatsu ORCA-Flash4.0 hardware module (`HCam`) on top of the
  official DCAM-API v4 bindings (`dcam.py`, `dcamapi4.py`), following the
  structure and conventions of the Kinetix module:
  - live acquisition in a DCAM ring buffer, single-image acquisition, and
    fixed-length movie acquisition (buffer allocated at each start);
  - `get_most_recent_image` returns `(frame, number of acquired frames)` and
    `get_acquired_data` returns a `[n_frames, height, width]` stack;
  - ROI selection (1-based, inclusive limits) automatically enlarged to the
    steps accepted by the camera;
  - external-trigger acquisition for the synchronized Hi-M imaging (external
    edge trigger, "trigger ready" and exposure output triggers);
  - new config options: `live_buffer_frames`, `trigger_ready_channel`,
    `exposure_out_channel`, `output_trigger_polarity`.
- Added `abort_movie_acquisition` (default: stop the acquisition) to
  `CameraInterface`.
- Multi-camera support (2026-09-21), to select one camera among up to three on
  microscopes that have several cameras:
  - new interfuse `hardware/interfuse_hardware/camera_interfuse.py`
    (`CameraInterfuse`): three connectors (`camera_1` mandatory, `camera_2` and
    `camera_3` optional) and one active camera to which every call of
    `CameraInterface` is forwarded; a camera that fails to activate is removed
    from the list; duplicated camera names are made unique; the selected camera
    is reset to its default state (exposure and gain measured at activation,
    full sensor); other attributes (e.g. Andor-specific methods) are forwarded
    to the active camera;
  - `CameraInterface`: optional `get_available_cameras`, `get_active_camera`,
    `set_active_camera` and `get_camera_type` (defaults for a single camera);
  - `camera_logic`: `get_available_cameras`, `get_active_camera`,
    `select_camera(name)` and the signal `sigCameraChanged(str)`; the switch is
    refused while the camera is busy (live, saving, synchronized acquisition);
    the initialization from the hardware was moved to `_init_from_hardware()`
    so that the capabilities are read again after each switch;
  - `basic_imaging_gui`: the `camera_comboBox` is filled from the logic
    (hidden if only one camera is available) and emits `sigSwitchCamera`; it is
    disabled unless the camera is idle and the lasers and the brightfield are
    off; after a switch the indicators, the settings dialogs, the ROI selection,
    the image rotation, the contrast, the displayed image and the save settings
    are reset (`_refresh_camera_ui`);
  - `custom_config/dummy_config.cfg` now uses three dummy cameras of different
    sizes behind the interfuse to test the selection in the GUI.
- Camera activation failures (2026-09-22): a camera module that cannot be
  initialized now logs the error instead of raising it (Kinetix as before,
  ORCA changed) and reports it with the new optional
  `CameraInterface.is_available()` (default `True`). The camera interfuse
  leaves such a camera out of the list (so it is not in the combo box) while the
  interfuse, the logic and the GUI are still activated with the other cameras;
  the interfuse (or the logic, for a single camera) only raises a clear error if
  no camera is available. The Kinetix `on_deactivate` no longer fails when the
  camera was not initialized.
- Dummy camera: new option `simulate_activation_failure` (default `False`) to
  simulate a camera that cannot be initialized (error logged, `is_available()`
  returns `False`), so that this behavior of the interfuse, the logic and the
  GUI can be tested with the dummy config (`dummy_config.cfg`).
- `basic_imaging_gui`: the display is fully reset when the camera is changed
  (image, rubberband, contrast controls, and the view is fitted to the size of
  the first image of the new camera).
- Generalized the two remaining Andor-specific special cases that were
  detected by matching the camera name (`get_name() ==
  'iXon Ultra 897'/'iXon Ultra 888'`) in `basic_imaging_gui` and `camera_logic`
  (2026-09-22), following JB's review of these special cases:
  - `CameraInterface.get_cycle_time()` (optional, default:
    `get_exposure()`): the real time elapsed between two consecutive frames,
    for cameras whose acquisition cycle adds overhead beyond the requested
    exposure (Andor's kinetic time). Overridden by the Andor iXon Ultra
    (`get_cycle_time` delegates to the existing `get_kinetic_time`).
  - `camera_logic.can_spool`: a capability flag (same pattern as `has_gain` /
    `has_temp`), `True` only if the active camera exposes `set_spool`
    (currently only the Andor iXon Ultra); refreshed in `_init_from_hardware`
    so it stays correct across a camera switch. Spooling itself was
    deliberately left out of `CameraInterface`: it is a hardware-specific,
    tif/fits-only acquisition mode, not a capability every camera is expected
    to have.
- Added a TODO at the top of `ixon_ultra_888.py` (2026-09-22) as a reminder to:
  test spooling thoroughly and make sure it is only used when the user
  explicitly asks for it; check that live acquisition and movie acquisition
  both work properly full-frame without crashing the camera; and test both of
  these together with a ROI set, not only full frame.

#### Changed

- `CameraInterface.get_gain_limits` is no longer abstract (default `(0, 0)`),
  so that cameras without gain control (Kinetix, ORCA) can be instantiated.
- `CameraInterface.get_most_recent_image` now has the `copy` argument used by
  `camera_logic`; the return conventions of the acquisition methods are
  documented in the interface.
- `CameraInterface` now documents one contract shared by all cameras (Kinetix,
  ORCA, dummy): `True` = success for every bool-returning method, 2D images
  `[h, w]` / stacks `[n, h, w]`, `get_size` = full sensor `(width, height)`,
  `start_single_acquisition` returns the frame (or `None`),
  `get_most_recent_image` returns `(image | None, frame_count)`.
- `camera_logic` no longer depends on the camera type: the `cam_type` /
  `POLLING_CAMERAS` branching was removed (only the Andor-specific temperature
  setpoint test remains). It uses the public hardware calls only, ignores
  frames that are `None`/empty (`_is_valid_image`) and remembers the frame
  count given to `prepare_camera_for_multichannel_imaging` (`_n_frames_prepared`)
  so that `start_acquisition` needs no camera-specific argument. Its public API
  is unchanged (`basic_imaging_gui` untouched).
- Kinetix and ORCA: `set_image` and `start_movie_acquisition` now return
  `True` on success; `get_most_recent_image` returns `(None, 0)` when no frame
  is available; Kinetix `start_single_acquisition` returns `None` on failure.
- `camera_logic`: `get_kinetic_time()` (Andor-only) replaced by
  `get_cycle_time()`, which now relies on the new optional
  `CameraInterface.get_cycle_time` (defaults to `get_exposure()` for every
  other camera); `_kinetic_time` attribute renamed to `_cycle_time`
  accordingly; `start_spooling` now checks `can_spool` itself and
  logs-and-returns instead of letting an unsupported camera raise
  `AttributeError` on `set_spool`.
- `basic_imaging_gui`: the exposure/kinetic-time display (previously
  duplicated in `_update_camera_setting_widgets` and `update_exposure`) was
  factored into one helper, `_update_exposure_display`, driven by
  `camera_logic.get_cycle_time()` (shown as "Cycle time" whenever it differs
  from the exposure) instead of a name check on the camera. The three spots
  that decided whether to use spooling (`save_video_accepted`,
  `save_video_clicked`, `video_quickstart_clicked`) now use
  `camera_logic.can_spool` instead of the camera name; while at it, every
  branch now explicitly sets both `_video`/`_spooling` (previously only one of
  the two flags was set in some branches, which could leave a stale flag after
  a camera switch).
- The dummy camera was rewritten as a time-based simulation (frames produced at
  the exposure rate, synthetic scene with orientation marker, ROI, live, movie,
  abort, no-live mode) following the same contract, so it can be used to test
  the GUI and the tasks without hardware. Andor-specific simulation helpers
  were kept.
- The ORCA module now raises an error when the camera cannot be initialized
  (instead of logging it and staying active in an unusable state), and uses
  `camera_id` to select the camera when several are connected.

#### Removed

- Removed the ORCA code inherited from the legacy `hamamatsu_camera` wrapper
  (`setPropertyValue`, `getFrames`, ...), which is not available with DCAM-API v4.
- Removed the ORCA acquisition-mode methods (no equivalent property on the
  ORCA-Flash4.0).
- Removed `custom_config/dummy_multicamera_config.cfg`: this was a standalone
  three-dummy-camera + interfuse config created while developing the
  multi-camera selection feature, made redundant once `dummy_config.cfg`
  itself was updated to the same three-camera + interfuse setup (see
  "Multi-camera support" above).

#### Fixed

- Fixed the undefined variable `exc` in the exception handler of the live loop
  of `camera_logic`.
- Fixed the ORCA imports and the duplicated `get_size` definition.
- Removed the duplicated call of `init_save_settings_ui()` in `basic_imaging_gui.on_activate`, which created the save dialog twice.
- Kinetix `set_image` now clears the previous ROI (`reset_rois()`) before setting the new one: pyvcam appends ROIs on sensors supporting several regions, which made the reset to full sensor fail with "New ROI overlaps existing ROI".
- Andor iXon Ultra (`ixon_ultra_888.py`) : the module did not yet satisfy
  `CameraInterface`:
  - `get_image_size` was missing, so the class could not be instantiated, and
    `get_size` returned the current, possibly ROI-reduced size instead of the
    full sensor (fixed first, 2026-09-22).
  - Return-value convention (2026-09-22): `set_exposure`, `set_gain`,
    `set_image`, `start_live_acquisition`, `start_movie_acquisition` and
    `abort_movie_acquisition` now return `True` on success (some used to
    return `True` on error, `set_image` returned an error code);
    `start_single_acquisition` now blocks and returns the acquired frame (or
    `None`) instead of an error flag; `get_most_recent_image` now takes the
    `copy` argument used by `camera_logic` and returns `(image, frame_count)`,
    `None` if no frame is available; `get_acquired_data` now returns `None`
    (instead of a zero-filled array) when the data could not be retrieved.
  - Added `is_available()` / `self._available`, set only once `on_activate`
    has fully succeeded, and guarded `on_deactivate` so that it does not fail
    if activation did not complete - same pattern as Kinetix, ORCA and the
    dummy camera, so that this camera failing to activate no longer brings
    down the interfuse, the logic and the GUI.
  - While doing this, found and fixed a pre-existing bug in `on_activate`:
    the camera-initialization check compared `Error_Codes.DRV_SUCCESS` (an
    enum member) directly to `ret` (the plain integer the SDK returns), which
    could never be `True`; replaced with the same `check_error`/
    `get_key_from_value` pattern used by every other SDK call in this module.
  - Fixed the `ConfigOption(..., 'False')` string/boolean issue for
    `_has_temp` / `_has_shutter` / `_has_gain` / `_support_live_acquisition`
    (2026-09-22): the default was the string `'False'`, which is truthy in
    Python, so `has_temp()` / `has_shutter()` / `has_gain()` /
    `support_live_acquisition()` would all report `True` whenever a config
    file left these keys unset - the opposite of the intended default.
    Changed the defaults to the boolean `False`; no config file in the repo
    references this camera yet, so nothing depended on the old behaviour.
    This closes the review shared with JB on 2026-09-22 - the module now
    fully satisfies the common camera contract (`camera_interface.py`).
- `camera_logic.save_to_ome_tif`: fixed a crash (`TypeError`, `None * i`) that
  occurred for every non-Andor camera, because the OME-TIFF metadata key it
  read (`'kinetic_time_(s)'`) was only ever populated for the Andor camera.
  `basic_imaging_gui._create_metadata_dict` now always records a generic
  `'cycle_time_(s)'` key (from the new `camera_logic.get_cycle_time()`), and
  `save_to_ome_tif` falls back to the exposure time if that key is still
  missing from older saved metadata.
- Two bugs found by JB while running the multi-camera checklist on real
  ORCA + Kinetix hardware (`docs/test_plan.md`, 2026-09-28 - everything else
  in that round passed):
  - **Kinetix `set_image()` cropped every ROI, including a "reset to full
    sensor", by 1 pixel in both directions** (3199x3199 instead of
    3200x3200). `hstart`/`vstart` are 1-based (first pixel = 1, the same
    convention `camera_logic.py` uses for every camera - see ORCA's
    `set_image` docstring), but were passed straight through to pyvcam's
    0-based `set_roi()` (missing `- 1`), and the ROI size was computed as
    `end - start` instead of `end - start + 1`. Fixed in `kinetix.py`;
    `set_image` also assigned `self._width`/`self._height` from the wrong
    (swapped) axis, which `get_acquired_data()`'s movie-buffer shape was
    unwittingly relying on to come out in the right (height, width) order -
    that buffer allocation was updated to match now that the swap is gone.
    Not present on the ORCA, which already did the `- 1`/`+ 1` conversion
    correctly.
  - **The multi-camera selector showed a cryptic hardware-queried name**
    (pyvcam's own model string for the Kinetix, the DCAM model/serial string
    for the ORCA) instead of the `camera_name` given in the config file.
    `CameraInterfuse._register_camera` builds the selector's display name
    from `get_name()` (see `camera_interfuse.py`'s own docstring), and both
    `kinetix.py` and `orca_flash4.py`'s `get_name()` queried the hardware
    for an identifier instead of returning the already-existing
    `camera_name` `ConfigOption` - the pattern `dummy_camera.py` and
    `ixon_ultra_888.py` already used. Both now return `camera_name`
    directly; the hardware-queried model/serial string is still logged once
    at activation, for provenance.
  - Verified with a new mock test (`t14_kinetix_roi_fix.py`, loading the real
    `kinetix.py` against a faked pyvcam): the full-sensor reset now measures
    exactly 3200x3200, a non-square ROI lands on the correct (non-swapped)
    axis and reaches pyvcam's `set_roi()` with the correctly 0-based
    coordinates, `get_name()` returns the configured name, and
    `get_acquired_data()`'s buffer shape matches a non-square frame.

### Pipetting robot

#### Added

- Added a generic pipetting-robot interfuse based on
  `MultiAxisStageInterface`.
- Added support for Cartesian and polar robot geometries.
- Added configurable robot axis roles.
- Added validation of the robot axes and their movement limits.
- Added configurable tube-grid geometry and tube-position mapping.
- Added a configurable safe Z position.
- Added safe robot parking, with Z moved to the safety position before
  horizontal movements.
- Added optional automatic parking when the module is deactivated.
- Added safe axis calibration, with the Z axis calibrated before the
  horizontal axes.
- Added support for different stage backends, including PI, ASI MS2000,
  and dummy stages.

#### Changed

- Separated generic multi-axis stage operations from robot-specific
  operations.
- Moved tube-grid geometry, parking, and robot safety behavior into the
  pipetting-robot interfuse.
- Updated positioning logic and GUI connections to use the new pipetting
  robot interface.

### DAQ

#### Added

- Added a generic DAQ interface based on named analog and digital channels.
- Added support for the MCC USB-3104 DAQ on Linux using `uldaq`.
- Added support for configurable analog-output ranges.
- Added a dummy DAQ module for development and testing without connected
  hardware.
- Added a generic DAQ-controlled pump module.
- Added support for controlling several pumps from the same DAQ by creating
  separate pump-module instances connected to different named DAQ channels.

#### Changed

- Replaced vendor-specific DAQ task handling in higher-level modules with
  named DAQ channels.
- Moved DAQ channel registration and vendor-specific channel setup into the
  hardware modules.
- Generalized the DAQ pump controller so that the hardware module is not tied
  specifically to rinsing or fluidics applications.
- Completed the MCC driver's `DaqInterface` implementation for named AO, AI
  (on devices that provide AI), DO, and DI channels. MCC digital lines are
  configured individually by bit, and each output is driven low immediately
  after it is configured as an output. The USB-3104 API does not support
  preloading the output latch before direction changes.
- Aligned `DaqInterface.write_to_ao_channel`'s optional range argument with the
  NI and dummy DAQ implementations, and clarified the digital read/write
  contracts. The named AO methods used by the pump and laser interfuses remain
  unchanged.
- Added method docstrings throughout `Measurement_Computing_daq.py`, including
  channel configuration formats, validation errors, low-level and named I/O
  behavior, immediate DI sampling, and the timing of digital output pulses.
- Split the ZEN DAQ trigger interfuse into `DaqTriggerOutput` and
  `DaqTriggerInput`. Their options (`output_trigger_task` and
  `input_trigger_task`) identify named tasks from the DAQ's configured DO/DI
  mappings. Output pulses use the configured pulse width and return with the
  line low; input sampling remains nonblocking so task-level polling retains
  timeout and interruption handling. The former `DaqTriggerSync` interface and
  implementation remain available for compatibility.
- Added `TriggerOutputInterface` and `TriggerInputInterface`, updated the SD ROI
  hardware interfaces and added `TriggerLogic`. The logic uses optional
  connector lists, indexes connected trigger modules by their Qudi module names,
  and forwards `send_trigger()` / `is_triggered()` calls. With exactly one
  trigger of a direction, its name may be omitted; an absent or ambiguous
  requested connection raises a descriptive error.
- Updated the SD ROI task to connect to `TriggerLogic` rather than directly to
  trigger hardware, and updated `Spinning_disk_config.cfg` to wire the logic to
  output, completion-input, and ready-input modules while preserving its DAQ
  channel assignments.

#### Fixed

- Removed the unsupported `set_port_initial_output_val` call from MCC DIO
  initialization; USB-3100 devices expose per-bit direction and bit I/O, but
  not that initial-output configuration operation.
- Fixed DAQ channel-range parsing when ranges were provided using different
  configuration formats.
- Fixed handling of MCC analog-output channels that share the same DAQ
  subsystem object.
- Fixed initialization and cleanup of DAQ channel information.

### Fluidics

#### Added

- Added a shared Fluigent SDK hardware module responsible for SDK
  initialization, hardware discovery, and SDK shutdown.
- Added a separate Fluigent pump module.
- Added a separate Fluigent flow-sensor module.
- Added generic `PumpInterface` and `FlowSensorInterface` interfaces.
- Added support for using either a Fluigent pressure controller or a
  DAQ-controlled pump with a Fluigent flow sensor.
- Added separate connections for:
  - the main fluidics pump;
  - the rinsing pump;
  - the flow sensor.

#### Changed

- Split the previous combined `FluigentFlowboard` module into independent pump
  and flow-sensor responsibilities.
- Updated the fluidics logic so that it no longer expects one hardware module
  to provide both pump control and flow measurement.
- Kept PID flow regulation in the fluidics logic while allowing its output to
  control different pump implementations.
- Changed the rinsing pump from an application-specific hardware module to a
  generic pump controlled by the fluidics logic.
- Updated configuration files to use the new pump and flow-sensor connectors.

#### Fixed

- Fixed Fluigent channel normalization and configured-channel validation.
- Fixed hardware connector initialization in the fluidics logic.
- Fixed cleanup of Fluigent adapter references during deactivation.
- Fixed the valve-combobox callback so that both the valve number and selected
  position are passed correctly.

### Task runner

#### Fixed

- `tasks/dummy_fluidics_task.py` (2026-09-24): removed a non-functional
  `interrupt_task(name)` method that had been added directly to the `TestTask`
  `ModuleTask`. It referenced `self._running_tasks` / `self._thread_lock`,
  which belong to `TaskRunnerLogic`, not to a task - it would have raised
  `AttributeError` if it had ever been called, and in fact nothing called it
  (the GUI's stop button goes through `TaskRunnerLogic.interrupt_task`, not
  through the task itself). This was most likely a confused attempt to port
  the legacy qudi task-abort behaviour, which works very differently:
  qudi-core tasks cannot be stopped from the outside - the task's own `_run()`
  must call `self._check_interrupt()` regularly (as `TestTask._run()` already
  correctly does, via `_interruptible_sleep()`) so that a pending
  `self.interrupt()` request is noticed and unwinds the task, after which
  `_cleanup()` always runs (here: returns the valve to its safe position).
  This part was already correct and is unaffected by this fix.
- `logic/taskrunner_logic.py`: `TaskRunnerLogic.interrupt_task()` used to be
  completely silent; it now logs an info message when an interrupt is
  requested for a running task, and an error message (before raising) when
  asked to interrupt a task that isn't running, so that clicking "abort" in
  the Task Runner GUI is now visible in the log console.
- Verified with a mock test (thread-based, no Qt/qudi-core dependency) that
  interrupting `TestTask` mid-run stops it before its next step, still runs
  `_cleanup()` (valve back to the safe position), and that a normal
  (non-interrupted) run is unaffected by any of the above.
- `gui/task_runner/task_runner_gui.py` (2026-09-25): the above fixes were not
  enough on real hardware - clicking "abort" still had no effect, and the
  "Interrupt requested" log line always carried the same, late timestamp no
  matter when the button was clicked, meaning the click was only reaching
  `TaskRunnerLogic.interrupt_task` once the task had already finished on its
  own. Confirmed against the installed `qudi-core==1.7.0` source
  (`ModuleScript`/`ModuleTask`) that the flag-based interrupt mechanism itself
  is implemented exactly as expected and would take effect immediately once
  actually called - the problem was purely that the call was queued onto
  `TaskRunnerLogic`'s own thread and not being processed in time. Changed the
  `sigInterruptTask` connection from `QueuedConnection` to `DirectConnection`:
  `interrupt_task` only touches state that is already protected by a lock (its
  own `_running_tasks` dict, and the task's own interrupt flag), so there is no
  need to marshal the call through that thread's event queue at all - a direct
  call takes effect immediately regardless of what that queue is doing.
  Confirmed working by JB on real hardware.

### Tasks

#### Added

- **Superseded same-day**: an earlier version of this entry (and of
  `tasks/roi_multicolour_scan_sd_task.py` itself) ported the legacy ROI task's
  autofocus handshake and per-plane laser/camera loop as well. JB clarified
  that on the spinning-disk setup ZEN itself now drives z-stack acquisition,
  autofocus, *and* image acquisition, and that the Lumencor is switched by a
  dedicated TTL box that ZEN controls directly - none of that is qudi's job
  any more. The task below replaces that version; it never shipped to JB or
  was committed, so there is nothing to migrate away from.
- `interface/trigger_sync_interface.py` + `hardware/interfuse_hardware/daq_trigger_sync.py`
  (2026-09-26): new `TriggerSyncInterface` (`send_trigger()` /
  `is_triggered()`) and its DAQ-backed implementation `DaqTriggerSync`, for a
  single start/done trigger handshake with external acquisition software
  (ZEN) over one named DAQ digital-output / digital-input channel pair. Mirrors
  the existing `daq_pump_controller.py` pattern (one interfuse instance per
  physical channel pair, connecting to `daq`) rather than having a task talk
  to the `daq` connector directly - JB's call, matching how the pumps are
  already wired. A setup that needs several independent handshakes (e.g. a
  separate autofocus-start pair later on) connects a separate instance per
  pair, same as `rinsing_pump`/`fluidics_pump` today.
- `tasks/roi_multicolour_scan_sd_task.py` (2026-09-26): new qudi-core
  `ModuleTask` translation of the legacy `tasks/ROI_multicolour_imaging_SD.py`,
  scoped down to exactly two responsibilities per ROI: move the stage there,
  then run one start/done trigger handshake with ZEN through the `sync`
  connector (a `DaqTriggerSync` instance) and wait for it to confirm done. No
  autofocus, laser control, or per-plane loop on qudi's side - see above. The
  legacy file is untouched. Two deliberate differences from a straight port of
  the parts that remain, discussed with JB beforehand:
  - Interruption is exception-based (`self._check_interrupt()`, raising
    `ModuleScriptInterrupted`), matching qudi-core's single-`_run()`-call
    model, instead of manually threading `if not self.aborted` through every
    subsequent block as the legacy `runTaskStep()` did (which is fragile - see
    e.g. the legacy ROI task's own `runTaskStep()` return statement, which
    forgets to `and not self.aborted`, unlike the HiM task's equivalent line).
    `_cleanup()` is called unconditionally by the `ModuleTask` base whenever
    `_run()` finishes, raises, or is interrupted, and always returns the stage
    to the first ROI, resets the stage velocity, and re-enables the ROI GUI
    actions.
  - Resumability: an interrupted run can be relaunched with `resume=True` and
    will skip every ROI already confirmed done by ZEN, continuing in the same
    output directory, instead of requiring the whole ROI list to be redone.
    Progress is checkpointed to a small YAML file next to the run's own
    `save_path` (`.<sample_name>_roi_scan_checkpoint.yaml`, at a location
    stable across runs so it can be found before any new directory is
    created) after every ROI completes; a checkpoint marked `completed: true`
    (or one that does not match the current sample name / ROI list) is not
    resumed from, and `resume=True` with nothing valid to resume from falls
    back to starting fresh (logged as a warning). An ROI only counts as done
    once ZEN's own "done" trigger has been seen for it, so an ROI interrupted
    mid-handshake is simply redone in full on the next launch, never resumed
    partway.
  - The metadata sidecar file (`parameters.yml`) is now purely descriptive
    (sample name + each ROI's stage position) - it no longer records
    `num_z_planes`/`imaging_sequence`, since ZEN now owns those parameters and
    qudi never acts on them. Flagged as an assumption for JB to confirm or
    override.
  - **Resolved (2026-09-28)**: the open question above - JB confirmed the
    one-time "ZEN ready" wait should be kept ("it allows us to make sure the
    task is starting properly before moving to the first ROI") and, when
    asked whether it should reuse the per-ROI start/done pair or a separate
    channel, pointed to the legacy task: "two channels (7 and 8) were used to
    monitor ZEN activity. Please keep the same structure." Implemented as a
    genuinely separate, one-way channel pair, matching the legacy `OUT7_ZEN`
    (ready, qudi only polls it, never triggers it) / `OUT8_ZEN` (per-ROI
    done) structure:
    - `DaqTriggerSync.trigger_channel` is now an optional `ConfigOption`
      (`default=None`, was `missing='error'`); an instance configured with
      only a `done_channel` is watch-only and its `send_trigger()` raises a
      clear `RuntimeError` if ever called, rather than silently doing
      nothing.
    - `RoiScanTask` gained a second connector, `ready` (same
      `TriggerSyncInterface`, a separate `DaqTriggerSync` instance backed by
      the ready-only channel), and a new `_wait_for_ready()` step that runs
      once, before the ROI loop, right after the stage/GUI setup and before
      the run directory is created. Same no-timeout, interruptible-poll shape
      as `_wait_for_done()`, since there is no way to bound how long the user
      takes to select the right ZEN experiment block and click "Start
      Experiment".
    - Using a separate channel (rather than reusing the per-ROI start/done
      pair as a generic ping) was a deliberate physical-safety choice: qudi
      never writes to the ready channel, so this cannot cause ZEN to perform
      a spurious acquisition while the task is only checking connectivity.
  - Verified end-to-end with the mock test suite (46 checks, up from 37):
    normal completion, mid-scan interrupt, resume skipping already-done ROIs
    and reusing the same output directory, resume with no matching
    checkpoint, the ZEN-timeout error path (reported as `RuntimeError`,
    deliberately not treated as an interrupt), `DaqTriggerSync` itself
    against a fake DAQ (including the new watch-only/no-`trigger_channel`
    behaviour), a full integration run of the real task driven by two real
    `DaqTriggerSync` instances (per-ROI `sync` + watch-only `ready`), the
    task waiting through several `ready` polls before touching the ROI list,
    and an interrupt fired while still waiting for `ready` (before any ROI is
    touched) still running cleanup correctly.
  - Also noted in passing while reading `laser_control_logic.py` (independent
    of this task, which no longer touches the laser at all, but still a real,
    contained defect worth fixing separately): `stop_laser_output()` checks
    `if self.enabled:`, but `on_activate()` only ever sets a plain
    `self.enabled = False` that nothing updates afterwards - the real state
    lives in `self._enabled` (via `set_laser_enabled` / `set_laser_disabled`).
    So `stop_laser_output()` currently never does anything, and would raise
    (calling a `self.voltage_off()` that doesn't exist on the class) if
    `self.enabled` were ever `True`.

**TODO (tracked, updated 2026-09-29):**

*ROI scan task / DAQ - blocks running on real spinning-disk hardware:*
- ~~Implement real digital I/O in `MccDAQ`~~ - completed 2026-09-29 using
  the documented `uldaq` DIO API. Syntax and interface contract checks
  pass, but `uldaq` and the USB-3104 are not available in the development
  environment, so hardware verification remains open.
- The current `Spinning_disk_config.cfg` has named ZEN trigger tasks configured
  with the channel assignments supplied by JB, and the SD ROI task now uses
  separate output and input interfaces. Add/verify the `logic:` and
  `task_runner:` connections for this task and validate the actual wiring and
  pulse timing on the spinning-disk hardware. The `DaqTriggerSync` combined
  interfuse remains available to existing configurations.
- ~~Decide whether the one-time "ZEN ready" handshake is actually needed for
  JB's workflow~~ - resolved 2026-09-28: yes, keep it (see Tasks section
  above).

*Cameras - real-hardware verification, updated 2026-09-28:*
- ~~Confirm the `reset_rois()` "New ROI overlaps existing ROI" fix
  (2026-09-22) works on real hardware~~ - confirmed by JB on both the Kinetix
  and the ORCA (`docs/test_plan.md`); everything else in the multi-camera/
  ROI/saving checklist passed too, except the two bugs below, found in the
  same round.
- Re-confirm on real Kinetix hardware that the full-sensor reset now
  measures exactly 3200x3200 (was 3199x3199) - fixed above (see Cameras >
  Fixed), mock-tested, but not yet re-checked on the instrument.
- Re-confirm the multi-camera selector now shows the configured
  `camera_name` (e.g. `widefield_camera` / `opm_camera_1`) instead of the
  cryptic hardware string - also fixed above, not yet re-checked on the
  instrument.
- ROI orientation preserved after a reset - not explicitly reported back
  yet, still open.

*Other, not yet started:*
- Apply the same checkpoint/resume/exception-based-interrupt design to
  `HiM_imaging_SD.py` once the ROI task above is validated on real or dummy
  hardware, extending it to hybridization/photobleaching step-level and
  per-ROI resume (skip completed injection steps except the last
  imaging-buffer step, which is always redone; skip already-imaged ROIs),
  per the design discussed with JB.
- Fix the `self.enabled` / `self._enabled` bug in
  `laser_control_logic.stop_laser_output()` noted above.
