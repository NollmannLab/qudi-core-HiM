# Changelog

This file records the main changes made to the project.

## [Unreleased]

Last updated: 2026-10-16

### Documentation

#### Changed

- Docstrings and comments in `src/` (2026-10-14): they describe the code (what,
  why, constraints), never who asked for it or where it was discussed.
  Attributions such as "per discussion with JB", "per JB (date)", "found by
  JB" were removed and the technical reason kept
  (`tasks/roi_multicolour_scan_sd.py`, `hardware/camera/teledyne/kinetix.py`,
  `hardware/camera/hamamatsu/orca_flash4.py`). The dated "Modified with Claude
  code ..." change histories in 24 module headers were replaced by the single
  line "Modified with Claude code (Anthropic)"; the history lives in this
  changelog. The constraints those histories mentioned were checked to be
  documented next to the code concerned (e.g. kinetix `set_image` 1-based ->
  0-based ROI conversion, `get_name` returning the configured camera name, the
  task-runner "options:" rules, the photobleaching interrupt / TTL warnings).
  Kept unchanged: Author lines, license headers, `TODO (JB, date)` notes,
  config paths and user-facing strings. Comments / docstrings only: for every
  modified file, `ast.dump` with docstrings removed is identical before and
  after.

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

- `logic/camera_logic.py` (2026-10-14): `start_single_acquisition()` returns
  the acquired image when it is valid, otherwise None. Shutter handling,
  `_last_image` / `sigUpdateDisplay`, the "no image" warning,
  `stop_acquisition` and `sigAcquisitionFinished` are unchanged; the snap
  button (Qt signal) ignores the return value.

- Debug prints silenced (2026-10-14): the `*** DEBUGGING ***` prints are off
  by default, each module keeps its own switch. `hardware/camera/teledyne/kinetix.py`:
  new module flag `verbose = False` (set True to print every decorated
  hardware call); `decorator_print_function` prints only when `verbose` is
  True, and now uses `functools.wraps` so the decorated methods keep their
  names and docstrings. `logic/camera_logic.py`,
  `gui/basic_imaging/basic_imaging_gui.py` and
  `hardware/camera/andor/ixon_ultra_888.py`: `verbose = True` -> `False`
  (the `mouse_area_selected` print in basic_imaging_gui was already gated by
  `if verbose:`). Decorators kept; nothing converted to logging.

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

### Stages

#### Changed

- `hardware/multi_axis_translation_stage/tiger_ASI.py` + `OPM_config.cfg`
  (2026-10-13): **fast idle detection on the ASI Tiger (OPM stage)**. The
  OPM PSF timing log showed `roi_logic.stage_wait_for_idle()` taking
  513-528 ms for every 0.2 µm z step (79 % of the acquisition time):
  `wait_for_idle()` queried the status once, the stage was still busy right
  after the move, and the loop slept a fixed 0.5 s before the next query.
  - New config options, validated at activation (out of range -> clear
    error, module stays deactivated): `idle_poll_interval_s` (default
    0.02 s, range [0.005, 1.0]) and `settle_time_s` (default 0 s, range
    [0, 1.0]).
  - `wait_for_idle()`: first status query immediately, then one query every
    `idle_poll_interval_s` while busy; once idle, waits `settle_time_s` once
    (if > 0) so the position is stable before an image. Timeout
    (`_timeout`) logic, error message and `False` return unchanged.
    Docstring fixed (it said "checks every 1 s").
  - Unchanged: the 0.5 s wait in `on_deactivate` (waits for the serial port
    to close, not a status-polling loop), `write()`'s 0.1 s retry delay, the
    serial settings. `MS2000_ASI.py` keeps the 0.5 s poll for now.
  - Class docstring: Tiger config example (was an MS2000 one) with both
    options. `OPM_config.cfg`: `tiger` gets `idle_poll_interval_s: 0.02` and
    `settle_time_s: 0.0`.

### ROI logic

#### Changed

- `logic/roi_logic.py` (2026-10-14): new `get_stage_velocity(axes=None)`
  (wraps the stage's `get_velocity`). `set_stage_velocity` returns a bool:
  True when the stage accepted the command (interface code 0), otherwise an
  error is logged and False returned.

- `logic/roi_logic.py` (2026-10-13): **`move_stage` skips the axes given as
  `None`**. Only the non-None entries of `(x, y, z)` are sent (z only if the
  z axis is a stage axis), so a z-only move `(None, None, z)` never commands
  x / y: no serial time on them (~24 ms per plane on the OPM) and no lateral
  correction / anti-backlash motion. If nothing would be sent (all `None`, or
  only z on a 2-axis stage) the stage is not called, an error is logged and
  `False` is returned (before: z silently ignored, `True`). `sigStageMoved`
  still carries a full `(x, y, z)`: for a partial move the missing axes are
  read from `stage_position` (one extra query). Full positions, `go_to_roi`
  and `go_to_roi_xy` behave exactly as before.

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

### Galvo

#### Added

- `interface/galvo_interface.py`, `hardware/interfuse_hardware/daq_galvo_controller.py`,
  `logic/galvo_logic.py` (2026-10-12): control of the OPM beam-sweep galvo
  mirror, driven by one analog output of the DAQ (AO1 of `nidaq_6738`,
  tested by hand so far but not controlled by any code). Standard hardware →
  logic chain modelled on the DAQ pump; hardware + logic + config only (no
  GUI, no task yet).
  - `GalvoInterface`: `set_voltage`, `get_voltage` (last value written - an
    AO cannot be read back), `get_limits`, `get_rest_voltage`, `go_to_rest`;
    all in V.
  - `DaqGalvoController`: GalvoInterface over one named DAQ AO task
    (`write_named_ao`). Options `output_task` (required), `min_voltage` /
    `max_voltage` (default -5 / 5 V), `rest_voltage` (default 0 V).
    Activation checks `min < max`, `min <= rest <= max`, that the limits fit
    inside the DAQ task's own range and that the task exists - any
    inconsistency stops activation with an error naming the option and
    values (raised, so qudi logs it and leaves the module deactivated) -
    then moves the galvo to rest; deactivation moves it to rest. At run time
    errors follow the qudi convention - logged, not raised: `set_voltage` /
    `go_to_rest` return `True` on success and, for a voltage outside the
    limits, a non-number or a failed DAQ write, log an error, write nothing
    and return `False`. Write + stored value are protected by a mutex (task
    and GUI threads).
  - `GalvoLogic`: delegates to the hardware and returns its `True`/`False`,
    emits `sigVoltageChanged` after each successful write only, moves the
    galvo to rest on deactivation. A task using it must check the return
    value and stop if it is `False`.
  - `OPM_config.cfg`: AO task `galvo: ['/Dev1/AO1', [-5, 5]]` on
    `nidaq_6738`, hardware `galvo` and logic `galvo_logic`.
    `dummy_config.cfg`: the same on `dummy_daq` (AO task on `/Dev1/AO5`).
  - Verified against `qudi-core==1.7.0` and 1.8.0 with the real `DummyDaq`,
    modules built and activated the way qudi does (47/47 checks):
    activation writes the rest voltage; `set_voltage(2.5)` writes 2.5,
    returns `True` and `get_voltage()` returns it; 6, -5.01, 5.000001 V, a
    string and `None` return `False` with an error logged, no exception and
    nothing written; a failing DAQ write returns `False` with the DAQ error
    logged and the stored value unchanged; rest outside the limits,
    `min >= max`, limits wider than the DAQ task range, an unknown
    `output_task` and a failing DAQ at activation each leave the module
    deactivated with a clear message; deactivation writes the rest voltage,
    and with a failing DAQ it logs the error without raising; the logic
    returns the same `True`/`False` and emits `sigVoltageChanged` once per
    successful write and not on a refused one; concurrent writers keep the
    stored value consistent. Both configs pass qudi-core's config validation on both
    versions, and the dummy-config entries run end to end. Still to be
    checked by JB on the OPM.

### Bright-field

#### Added

- `interface/brightfield_interface.py`, `logic/brightfield_logic.py`
  (2026-10-15): bright-field LED control, so that the BF controls of the
  basic imaging GUI (optional `brightfield` connector) appear when the logic
  is connected.
  - `BrightfieldInterface`: one abstract method `led_control(intensity)`
    returning `True`/`False` (intensity in percent, clamped by the hardware).
  - `Tiger` (`tiger_ASI.py`) and `MS2000` (`MS2000_ASI.py`) now also derive
    from `BrightfieldInterface` (second base, after
    `MultiAxisStageInterface`). No other driver change: the LED command,
    the 0-99 % clamp and the `LED connected` gate are unchanged.
  - `BrightfieldLogic` (API used by the GUI and the RAMM tasks): `enabled` (read-only)
    and the stored `intensity`; `led_control(intensity)` stores the value,
    sends it and sets `enabled`; `led_off()` sends 0, clears `enabled` and
    emits `sigBrightfieldStopped`; `update_intensity(value)` stores the value
    and sends it only while the LED is on; `stop_brightfield_output()`
    switches the LED off if it is on (task preparation); the LED is
    switched off on deactivation. A command refused by the hardware logs an
    error and returns `False` (a refused switch-on emits
    `sigBrightfieldStopped` so the GUI button is reset). GUI buttons are
    disabled during tasks by `disable_laser_actions()`, as before.
  - `OPM_config.cfg`: logic `brightfield_logic` connected to `tiger`;
    `basic_imaging` connects `brightfield: 'brightfield_logic'`. RAMM and
    spinning-disk configs unchanged.

#### Fixed

- Basic imaging GUI:
  - `sigBFOn` is `Signal(float)`: the BF spinbox value was truncated to an
    int (37.5 -> 37). The BF spinbox range is now 0-99 (hardware range).
  - Closing the window really switches the lasers off: the close handler
    called `laser_logic.voltage_off()` (does not exist) behind a test of
    `laser_logic.enabled` (never updated, so always `False`). It now calls
    `set_laser_disabled()` when `laser_enabled` is `True` or the laser
    button is checked, then resets the button.
- Verified offscreen with `qudi-core==1.7.0` and 1.8.0 (43/43 checks): real
  `BasicImagingGUI`, `LaserControlLogic` and `BrightfieldLogic` with fake
  hardware, plus the real `Tiger` / `MS2000` drivers on a fake serial port.
  BF button and spinbox shown; on / intensity change / off reach
  `led_control` with 37.5, 50, 99 and 0; a change while off is stored, not
  sent; closing the window switches LED and lasers off (also lasers enabled
  from the logic only); without the brightfield connection the BF controls
  are absent and the GUI works; Tiger / MS2000 still send
  `<card>LED X=<0-99>? `; `OPM_config.cfg` passes the qudi-core config
  validator. The same test on the previous GUI fails 9 checks (lasers left
  on at close, intensity truncated).

### Lasers

#### Fixed

- `LaserControlLogic.stop_laser_output()` (2026-10-16) never switched the
  lasers off: it tested `self.enabled` (set to `False` in `on_activate()`
  and never updated; the state is `_enabled`, exposed by `laser_enabled`)
  and called `self.voltage_off()`, which does not exist. It now calls
  `set_laser_disabled()` and emits `sigLaserStopped` when `laser_enabled` is
  `True`, and does nothing when the lasers are already off. The stale
  `self.enabled` attribute is removed.
- `BasicImagingGUI`: the laser button state at start-up reads
  `laser_logic.laser_enabled` (was the stale `enabled`, so the button stayed
  unchecked when the lasers were already on).
- Remaining uses, in tasks not migrated yet and left unchanged:
  `tasks/legacy/HiM_imaging_SD.py` calls `voltage_off()` (line 700);
  `tasks/legacy/HiM_imaging_RAMM.py`, `HiM_imaging_SD.py` and
  `ROI_multicolour_imaging_RAMM.py` call `stop_laser_output()` (now working).
- Verified offscreen with `qudi-core==1.7.0` and 1.8.0 (11/11 checks, real
  `LaserControlLogic` and `BasicImagingGUI`, fake laser hardware): lasers on
  -> `stop_laser_output()` -> `laser_enabled` `False`, `disable_all_lines`
  called once, `sigLaserStopped` emitted once; lasers off -> no hardware
  call, no signal; the GUI opens with the laser button matching
  `laser_enabled` (off and on) and resets it on `sigLaserStopped`. The same
  test on the previous code fails 6 checks. Bright-field GUI test
  unchanged (43/43).

### Basic imaging GUI

#### Fixed

- Task lock of the camera and laser controls (2026-10-16). During a task the
  controls became clickable again after the first image: every snap
  (`sigAcquisitionFinished` -> `acquisition_finished()`) and every
  `sigVideoFinished` called `enable_camera_toolbuttons()`. Some controls were
  never locked.
  - Two flags, changed only by the logic lock signals: `_camera_locked`
    (`sigDisableCameraActions` / `sigEnableCameraActions`, now connected to
    the new slots `lock_camera_actions()` / `unlock_camera_actions()`) and
    `_laser_locked` (set in `disable_laser_toolbuttons()` /
    `enable_laser_toolbuttons()`, still the slots of `sigDisableLaserActions`
    / `sigEnableLaserActions`). Filter-wheel lock unchanged.
  - While `_camera_locked`, `enable_camera_toolbuttons()` (end of a snap,
    `sigVideoFinished`, save dialog cancelled, end / abort of a saved video)
    only resets the checked states and enables nothing; stopping live does
    not re-enable Snap. Locked: Snap, Live, Save last image, Save video,
    Quickstart video, Set / reset sensor region, Reuse last sensor ROI,
    Camera settings, Piezo settings and the camera combobox
    (`_camera_switch_allowed()` returns `False`); a rubber-band selection on
    the image is ignored.
  - While `_laser_locked`: Laser on, Zero all, every laser intensity spinbox
    (also after a filter change) and, with a brightfield logic, the
    brightfield button and spinbox.
  - On unlock each control gets its normal state back: Snap disabled while
    live runs, Reuse last sensor ROI only if a previous ROI exists, camera
    combobox from `_camera_switch_allowed()`, laser spinboxes from the
    current filter.
  - Display-only controls (image rotation, contrast, dock views) stay
    available. The Abort button keeps its previous behaviour (enabled by
    `disable_camera_toolbuttons()`).
- Verified offscreen with `qudi-core==1.7.0` and 1.8.0 (33/33 checks): real
  `BasicImagingGUI`, fake camera logic with the same signals as
  `CameraLogic` (names and signatures checked), real `LaserControlLogic`
  and `BrightfieldLogic` on fake hardware. Without a lock, snap and live
  behave as before. Locked: every listed control stays disabled after 3x
  `sigAcquisitionFinished`, 3x `sigVideoFinished`, a live stop / start from
  the logic and a cancelled save dialog; a rubber-band selection and a
  camera switch do not reach the camera logic; display controls stay
  enabled. Unlock with live running and a previous ROI, then with live off
  and no ROI: Snap, Reuse last sensor ROI, the camera combobox and the
  laser spinboxes get their normal states. The same test on the previous
  GUI fails 8 checks. Bright-field (43/43) and laser-stop (11/11) tests
  unchanged.

### Fluidics

#### Added

- `hardware/interfuse_hardware/dummy_flow_sensor.py` (2026-10-15):
  `DummyFlowSensor` (`FlowSensorInterface`), same options and return format
  as `FluigentFlowSensor` (`sensor_channel_IDs`, `unit`; `get_flowrate` ->
  `{channel: float}`, `get_sensor_unit` -> `{channel: str}`). Optional
  connector `pump` (`PumpInterface`): flow = `flow_per_unit` (default 100,
  sensor unit per pump output unit) * pump output + gaussian noise
  (`noise_std`, default 5), never negative; without a pump `mean_flow`
  (default 200) + noise. A requested channel that is not configured is
  logged as an error and left out (no exception).
- `dummy_config.cfg`: the dummy fluidics setup now mirrors the spinning-disk
  one, with only the flow sensor simulated:
  - AO task `fluidics_pump` (`/Dev1/AO6`, [0, 10] V) on `dummy_daq`;
    `fluidics_pump` (`DaqPumpController`, voltage 0-3 V);
  - `rinsing_pump` updated to the current `DaqPumpController` options
    (`kind`, `unit`, `minimum`, `maximum`; `stop_voltage` /
    `rinsing_voltage` removed);
  - `dummy_flow_sensor` connected to `fluidics_pump`;
  - `fluidics_flow_logic` connects `flow_sensor`, `fluidics_pump`,
    `rinsing_pump` and `valve_logic` (`flowboard` removed; it no longer
    matched the logic's connectors). `pid_output_max: 3` (pump maximum);
    `p_gain` / `i_gain` halved (0.0025 / 0.005): with 100 µl/min per V the
    spinning-disk gains put the 1 s regulation loop at the edge of
    stability (sustained oscillation between ~30 and ~250 µl/min at a
    150 µl/min setpoint);
  - `fluidics_gui` connect keys corrected to the GUI connector names
    (`fluidics_logic`, `pipetting_robot_logic`, as in the spinning-disk
    config); with the previous keys the GUI could not be connected.
  - `dummy_flowboard` kept but no longer connected; task-runner entry
    `dummy_fluidics` (`dummy_fluidics_task.TestTask`) removed from the config
    (the file `tasks/dummy_fluidics_task.py` is kept).
- Verified with `qudi-core==1.7.0` and 1.8.0, every module created from its
  `dummy_config.cfg` entry (20/20 checks): `fluidics_flow_logic`, the
  fluidics GUI and the `fluidics_dummy` task activate without error; a
  pressure set in the GUI reaches the pump and the measured flow follows
  (1 V -> ~100, 2.5 V -> ~250, 0 V -> ~2 µl/min); regulation at 150 µl/min
  settles at ~150 µl/min (sd 4-7) at ~1.5 V within ~8 s; a 60 µl volume
  measurement reaches its target; the fluidics dummy task runs buffer /
  probe / incubation / buffer to the end (~20-23 µl per injection) and ends
  with pressure 0, valves c=1 b=1 a=1 and the GUIs unlocked. The config
  passes the qudi-core validator on both versions.

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

### Injections configurator

#### Added

- Probe needle mode (2026-10-15): records how the needle behaves when the
  probe valve is used several times in one sequence.
  - `injections_gui.py`: `probe_handling_comboBox` (with
    `needle_handling_Label`, both in `ui_injection_setup.ui`) lists
    "Move to the next tube" (`'next'`, default) and "Stay in the same tube"
    (`'same'`); the code is stored as item data and sent to the logic on
    every selection change (`sigProbeNeedleModeChanged` ->
    `set_probe_needle_mode`). Tooltip: "When the probe valve is used several
    times in the sequence: move the needle to the next tube (tube + 1) for
    each new probe injection, or keep it in the same tube."
  - `injections_configurator_logic.py`: `probe_needle_mode` (default
    `'next'`, valid values `'next'` / `'same'`); the setter and
    `set_probe_needle_mode()` reject any other value with `log.error` and
    return `False`. `save_injections()` writes the top-level key
    `probe_needle_mode` next to `buffer`, `probes`, `hybridization list` and
    `photobleaching list`. `load_injections()` reads it: a missing key gives
    `'next'` (files written before the key existed), an invalid value logs an
    error and falls back to `'next'`; `sigProbeNeedleModeChanged` updates the
    combobox (signals blocked, so the value is not sent back).
    `check_injection_sequence_consistency()` unchanged. The Hi-M tasks read
    the injection file key by key, so the new key does not affect them; they
    do not use the mode yet.
  - Verified offscreen with `qudi-core==1.7.0` and 1.8.0 (21/21 checks): real
    `InjectionsLogic` + `InjectionsGUI` with fake valve / robot logic; entries
    and order, default `'next'`, tooltip, GUI -> logic in both directions,
    setter rejection, saved file contains `probe_needle_mode`, reload of a
    `'same'` file selects "Stay in the same tube", an old file without the
    key selects "Move to the next tube" without any warning, an invalid value
    logs one error and falls back to `'next'`, an incomplete file leaves the
    mode unchanged.

### Fluidics task

#### Added

- `tasks/fluidics.py` (2026-10-15): runs the hybridization list of an
  injections file with the valves, the flow control and the pipetting robot.
  - `FluidicsTaskBase(ModuleTask)`, connectors `valve_logic`, `flow_logic`,
    `robot_logic`; options `user_config_path` (experiment YAML, key
    `injections_path`) and `probe_valve_number` (both required). Setup values
    are class attributes set by the subclasses: `start_`, `needle_move_`,
    `needle_moved_`, `incubation_`, `incubation_end_` and
    `cleanup_valve_positions` (applied in the given order); shared
    `volume_poll_interval_s` 1 s, `robot_timeout_s` 120 s,
    `injection_timeout_factor` 3, `injection_timeout_margin_s` 60 s,
    `incubation_log_interval_s` 30 s.
  - Sequence: read the experiment YAML and the injections file (buffer,
    probes, hybridization list, `probe_needle_mode`, missing -> `'next'`);
    validate without any hardware call and report every problem in one error
    (unknown product, volume / flowrate <= 0, negative incubation time, probe
    valve used without probes or without robot origin, invalid needle mode,
    too many tubes for the robot, valve addresses / positions not on the
    valves); plan the needle tube of each probe injection (lowest probe tube,
    then +1 per injection in `'next'`, always the first tube in `'same'`);
    log the plan; lock the valve, flow-control and robot GUIs; needle to the
    first tube; start positions; then each step: injection (valve `a` to the
    product, needle move if needed, pressure 0, PID regulation, volume count,
    poll until reached with an interrupt check every 0.1 s and a timeout of
    factor * volume / flowrate (min -> s) + margin raising "volume not reached
    - check the line", stop regulation, 1 s, pressure 0, injected volume
    logged) or incubation (incubation positions, interruptible wait with
    progress logged, end positions). Returns
    `{steps_done, steps_total, probe_needle_mode, tubes_used}`.
  - Needle move: needle-move positions, `start_move_to_target`, wait while
    `moving` (interruptible, `robot_timeout_s`), check the arrival at the
    tube (`sigStageMovedToTarget`), robot GUI locked again (the fluidics GUI
    re-enables its robot buttons on arrival; the lock is sent from the arrival
    signal itself, so the buttons never show as enabled), needle-moved
    positions.
  - Every valve move is checked: a position not reached (or an exception)
    raises naming the valve and the position.
  - `_cleanup`: stop the regulation and the volume count, pressure 0,
    `cleanup_valve_positions` one by one, unlock the three GUIs; each step in
    its own try/except (`log.error`, never raises). A needle move in progress
    is left to finish.
  - Subclasses: `FluidicsRAMMTask` (start b=2 c=2, syringe valve c closed
    around needle moves and incubations, cleanup c=1 b=1 a=1),
    `FluidicsSDTask` (start b=1, cleanup b=1 a=1), `FluidicsDummyTask`
    (RAMM layout, for `dummy_config.cfg`).
- `FluidicsValveLogic`: `sigDisableValveActions` / `sigEnableValveActions`,
  `disable_valve_positioning()` / `enable_valve_positioning()`, connected in
  `fluidics_gui.py` to the existing GUI slots (same pattern as the flow logic).
- Configs: `fluidics_dummy` task in `dummy_config.cfg`
  (`probe_valve_number: 7`); commented `fluidics` entries (path TO FILL) in
  `RAMM_config.cfg` (7) and `Spinning_disk_config.cfg` (3). Example
  injections file
  `custom_config/custom_experiments_config/dummy/fluidics_test_injections.yml`.
- Verified with `qudi-core==1.7.0` and 1.8.0 (60/60 checks), offscreen, the
  task in its own thread and the logic in the main event loop: real
  `DummyValve`, `DummyMultiAxisStage` + `PipettingRobot`, valve / flow /
  robot logic and `FluidicsGUI`; pump and flow sensor from test modules with
  the dummy flowboard behaviour (~200 µl/min). Full run (~75 s): mode
  `'next'` uses tubes 1 then 2, `'same'` tube 1 only; exact valve sequence;
  4 injections of >= 20 µl; pressure 0, valves c=1 b=1 a=1 and GUIs unlocked
  at the end; robot buttons never seen enabled during the run (sampled
  every 20 ms). Interrupt during an injection and during an incubation:
  cleanup starts ~0.1 s later. Unknown product + missing origin (+ bad
  volume and time): one error listing the 4 problems, no hardware call.
  Missing options, experiment file or injections file, refused valve
  position and injection timeout each stop the task with a clear message.

#### Changed

- Fluidics steps moved to a shared helper (2026-10-16), so that the Hi-M task
  can use the same code. Pure refactor: the fluidics task behaves as before.
  - New `tasks/common/fluidics_steps.py` (+ empty `tasks/common/__init__.py`):
    `FluidicsStepsMixin` with the valve-layout and timing class attributes,
    the injections-file reading and validation (`_read_yaml`,
    `_read_injections`, `_validate`, `_check_valve_positions`, `_is_number`)
    and the step methods (`_inject`, `_incubate`, `_move_needle`,
    `_set_valves`, `_set_valve`, `_interruptible_sleep`, `_describe`). No
    connector, no `_setup` / `_run` / `_cleanup`; it uses `self._valve`,
    `self._flow`, `self._robot` and the step state (`_needle_mode`,
    `_tubes_used`, `_arrival_slot`, `_needle_arrived_at`) set by the task.
  - Moved unchanged (identical AST), except: `_read_injections(path,
    list_key='hybridization list')` and `_validate(...,
    list_name='hybridization list')` take the list to read / name in the
    messages, so a caller can also use 'photobleaching list'; the defaults
    give the previous behaviour and messages.
  - `fluidics.py`: `FluidicsTaskBase(FluidicsStepsMixin, ModuleTask)` keeps
    the connectors, the options, `_setup` / `_run` / `_cleanup`, the option
    checks (`_check_options`, `_read_injections_path`) and `_log_plan`;
    subclasses unchanged. Task-runner options, attribute values and
    connectors of the four classes identical before / after.
- Verified on `qudi-core==1.7.0` and 1.8.0 with the `fluidics_dummy` task
  built from `dummy_config.cfg` (modes `'next'` and `'same'`, interrupt
  during the second injection), recorded before and after the change: the
  logic calls of the task (valve, flow, robot; 50 / 46 / 30), the valve and
  stage hardware commands (21 / 16 / 12), the task log lines (18 / 17 / 12),
  results, errors and end states are identical; the only differences are
  the measured volumes and durations in "µl injected" lines (flow-sensor
  noise and timing, which also differ between two runs of the same code).
  The fluidics task test passes 60/60 on both versions.
- Needle position not defined (2026-10-16): when the sequence injects from
  the probe valve and the robot origin (needle position 1) is not set, the
  task no longer stops with a validation error. It logs a warning and shows a
  non-modal warning box: "The needle position needs to be initialised first.
  Please do it in the Fluidics GUI ("Set position 1"). The task is aborted for
  now." It then ends without an exception and before any hardware call or
  GUI lock (result `{'aborted': 'needle position not initialised',
  'steps_done': 0}`).
  - `fluidics_steps.py`: `_needle_position_missing(buffer_valves, step_list,
    probe_valve)`, `_warn_needle_position()`, and the private constant
    `_NEEDLE_POSITION_MESSAGE` (not a task-runner option). The module function
    `show_warning_popup(title, text)` shows the box in the GUI thread, through
    a QObject living in the application thread and a queued signal, so it can
    be called from the task thread. It returns False and shows nothing when
    there is no QApplication. The box is kept referenced until it is closed.
  - `fluidics.py` `_run`: the check runs after reading the injections file,
    before `_validate`. The origin line in `_validate` stays as a fallback.
    Sequences without a probe injection still run without an origin.
  - Test (1.7.0 and 1.8.0): fluidics task test 68/68. The former "unknown
    product + missing origin" case now runs with the origin set (3 problems).
    New checks cover the warning log, the absence of an error log, no logic
    call, one non-modal box created in the GUI thread, the GUIs left enabled,
    and a buffers-only run without origin.

### Task runner

#### Added

- `gui/task_runner/taskwidget.py`, `gui/task_runner/main_window.py`
  (2026-10-08): optional start confirmation and end reminder declared by a
  task. Some tasks need a manual hardware step before and after running
  (photobleaching on the SD setup: unplug, then re-plug, the Celesta shutter
  TTL cable). A `ModuleTask` can now define the plain class attributes
  `start_warning` / `end_warning` (task config options are not passed to
  ModuleTasks in qudi-core 1.7.0, hence class attributes, like
  `user_config_path`). The Task Runner GUI, not the task (which runs in a
  worker thread), shows them: `start_warning` in a modal warning dialog
  every time Run is clicked ("Done — start task" / Cancel; Cancel is the
  default and escape button, and Cancel/Esc/closing emits nothing and keeps
  the button enabled); `end_warning` in a non-modal reminder (OK,
  `WA_DeleteOnClose`) when a run this widget saw start ends - success,
  failure or interrupt. The initialising `task_finished()` call made by
  `TaskRunnerGui.on_activate` shows no reminder (gated by a flag set in
  `task_started()`). Confirmation, cancellation and reminder are logged at
  info level. `TaskWidget` gets an optional `task_name` argument (dialog
  titles / log messages), passed by `TaskMainWindow`. Tasks without the
  attributes behave exactly as before; signals, `get_parameters`, the
  interrupt path and `task_runner_gui.py` are unchanged.
- Verified offscreen against `qudi-core==1.7.0` (PySide6) with dummy tasks
  with and without the attributes (dialogs auto-answered, 40/40 checks): no
  dialog and immediate start without attributes; Cancel and Esc emit nothing
  and leave the button enabled; confirm emits `sigStartTask` once with the
  editor values; the dialog is shown on every Run but never on interrupt; no
  reminder on the on_activate-style initialisation (also through
  `TaskMainWindow`); exactly one reminder after a started run for success,
  failure and interrupt. Also checked once with the real modal `exec()`
  (timer-clicked buttons), the compact-layout smoke test, and `py_compile`.
  Still to be checked by JB on the SD microscope.
- `logic/taskrunner_logic.py` (2026-10-12): task `options:` from the config.
  qudi-core's task runner ignored a task entry's `options:` block and
  created every task with no arguments, so machine-specific values (the
  YAML path written by the experiment configurator) had to be hard-coded in
  the task classes. Each task entry may now carry `options:`; they are
  validated in `on_activate` - a mapping with str keys, each key a public
  class attribute the task already declares and not a method, `Connector`,
  Qt signal or property - otherwise activation fails with a clear error
  naming the task, the key and the allowed attributes. The values are set
  with `setattr()` on each new task instance in `__init_task`, so they
  override the class default for that instance only. Run / interrupt
  logic, signals, threading and the Task Runner GUI are unchanged (the GUI
  still reads `start_warning` / `end_warning` from the class). Example:
  `options: user_config_path: '/path/to/photobleaching_task_sd.yaml'`.
  Verified with the real `on_activate` / `__init_task` methods against
  `qudi-core==1.7.0` and 1.8.0: both real configs activate; the option is
  set on the instance and not on the class or on another entry of the same
  class; a task without `options:` is created as before; an unknown key, a
  `_private` key, a method, a Connector, a property, a Qt signal, a
  non-mapping and a non-str key each fail at `on_activate` with a clear
  message.

#### Changed

- `gui/task_runner/taskwidget.py`, `gui/task_runner/main_window.py`
  (2026-10-08): compact Task Runner layout. Each task took far more vertical
  space than its 0-1 parameters needed, so with several tasks per microscope
  the user had to scroll to find the one to run. Causes: no stretch at the end
  of `tasks_layout` (group boxes expanded to share all spare height), a
  run/stop button sized as a square of twice the state-label width with its
  icon scaled to fill it, controls stacked vertically, a parameter grid with
  row stretch / minimum row heights, and a bold +2 pt group-box title that was
  inherited by every label and editor. Now each task is one thin `QGroupBox`
  (bold title at normal size, tight margins) holding a single row
  `[parameters] | [state label] [busy indicator] [run/stop button]`, with the
  controls right-aligned on the first line. Parameters are placed row-major,
  at most 3 label/editor pairs per line, wrapping onto extra lines; a task
  without parameters only shows the controls. The run/stop button is a normal
  `QToolButton` of standard line height with a 16-24 px icon; the
  `CircleLoadingIndicator` has the same size and still retains its space when
  hidden; the state label has a minimum width fitting the longest state text
  so the controls never shift. A trailing stretch packs the tasks at the top
  (new group boxes are inserted before it; the `QScrollArea` is kept). The
  unused `TestToolButton` class was removed (class only, no file deleted).
  **Meaning change**: `TaskWidget(max_columns=...)` is now the maximum number
  of label/editor *pairs per line* (default 3), and `max_rows=...` the maximum
  number of lines (pairs per line = ceil(n_params / max_rows)); previously the
  grid was filled column-major with `max_rows` defaulting to 8. Nothing in the
  repo passes either argument. Unchanged: all signals/slots and connections,
  the start/interrupt logic, `get_parameters`, `task_runner_gui.py` (incl. the
  `DirectConnection` interrupt fix), and the known `_clear_task_widgets` bug
  (iterates over task-name strings and calls `.parent()` on them; still open).
- Verified with an offscreen Qt smoke test (`QT_QPA_PLATFORM=offscreen`,
  PySide6 6.12 + `qudi-core==1.8.0` installed in the dev environment) building
  `TaskMainWindow` with `TestTask`, `TestTask2`, `roi_multicolour_scan_sd` and
  `photobleaching_sd` (`HiM_imaging_SD` could not be imported there: no
  `tkinter`): group-box `sizeHint().height()` went from 258 px for every task
  to 54 px for tasks with 0-1 parameters and 79 px for `TestTask2` (4
  parameters, wrapped onto 2 lines). The run/start/stop/finish slots still
  switch the state label, busy indicator and icon, and the start/interrupt
  signals still emit with the right task name and parameters. The
  `max_columns`/`max_rows` variants and their mutual-exclusion error were also
  checked. Still to be checked by JB on the real setup (qudi-core 1.7.0); the
  saved window geometry may restore the old, large window size the first time.

#### Fixed

- `gui/task_runner/task_runner_gui.py` (2026-10-14): **traceback at qudi
  shutdown** (`AttributeError: 'NoneType' object has no attribute
  'sigStartTask'`, preceded by a PySide "Failed to disconnect" warning).
  `on_deactivate` closed the window before disconnecting `sigClosed`; the close
  emitted `sigClosed` -> `_deactivate_self` -> a second, re-entrant
  `on_deactivate` that set `self._mw = None`, and the outer call then carried
  on with `None`. `on_deactivate` is now idempotent (returns at once without a
  window), disconnects `sigClosed` first, then `sigStartTask` /
  `sigInterruptTask`, then the task-runner signals with `disconnect(slot)`;
  each disconnect goes through `_safe_disconnect`, which ignores
  `RuntimeError` / `TypeError` from an already-gone connection. Then the
  geometry is saved, the window closed and `self._mw` reset. `on_activate`
  (and the direct connection of `sigInterruptTask`) unchanged. Checked
  offscreen with the real task runner: shutdown, closing the window by
  itself, reopening and shutting down again - no traceback, no warning.

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

- ROI scan task: base class + one subclass per setup (2026-10-16), same
  structure as the photobleaching and fluidics tasks.
  - New `tasks/common/imaging_steps.py`: imaging done at one ROI, per
    microscope, as mixins with three hooks - `_prepare_imaging()` (once, before
    the first ROI), `_image_roi(roi_name, file_name)` (at one ROI, after the
    stage has arrived), `_end_imaging()` (in the cleanup, logs errors, never
    raises) - and the class attribute `scan_stage_velocity`. To be reused by the
    Hi-M task.
    - `SDImagingMixin`: moved from `roi_multicolour_scan_sd.py` without
      changing the ZEN handshakes - laser preparation (external trigger on,
      line intensities of `imaging_sequence`) and wait for ZEN "ready"; per ROI
      ZEN autofocus block + `_wait_for_done`, 2 s, `ensure_ready`, ZEN
      acquisition block + `_wait_for_done`, 2 s, file name appended to
      `movie_name.txt`; end: lasers off, external trigger off, intensities
      reset. Options `acquisition_timeout_s`, `poll_interval_s`.
    - `RAMMImagingMixin`: placeholder - `_prepare_imaging` raises
      `NotImplementedError` (RAMM imaging not migrated yet: focus logic, FPGA);
      the docstring lists the legacy RAMM per-ROI steps as the to-do.
    - `DummyImagingMixin`: interruptible wait `dummy_imaging_time_s` (2 s) per
      ROI, then the file name appended to `movie_name.txt`.
  - New `tasks/roi_multicolour_scan.py`: `RoiScanTaskBase` (connectors
    `roi_logic`, `laser_logic`, `trigger_logic` optional; option
    `user_config_path`; parameters, checkpoint / resume with `resume_from_roi`,
    data folder, `parameters.yml`, `movie_name.txt`; stage moves; cleanup) and
    `RoiScanSDTask` (`trigger_logic` mandatory), `RoiScanRAMMTask`,
    `RoiScanDummyTask`.
  - Difference from `roi_multicolour_scan_sd.py` on the spinning disk: the
    laser preparation (`set_external_trigger(True)` and the line intensities)
    now runs in `_prepare_imaging`, i.e. after the lasers are disabled, the ROI
    GUI locked and the scan velocity set, instead of while loading the user
    parameters. With the lasers disabled first, the intensities are stored
    (`update_line_intensity`) and no longer applied to lines that may still be
    on. The cleanup's "Could not disable lasers" message is now logged as an
    error (was a warning). Stage moves, ZEN triggers, waits, files and the
    other log lines are identical (offscreen comparison with a fake
    TriggerLogic: 3-ROI run, interrupt during `_wait_for_done`, done timeout,
    resume).
  - Config: `Spinning_disk_config.cfg` ROI scan entry now points to
    `qudi.tasks.roi_multicolour_scan.RoiScanSDTask` (same connectors and
    options); `dummy_config.cfg` gets `roi_multicolour_scan_dummy`
    (`RoiScanDummyTask`); `RAMM_config.cfg` gets a commented-out
    `RoiScanRAMMTask` entry. `tasks/roi_multicolour_scan_sd.py` is left
    unchanged (not used by the configs any more).
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
- `laser_control_logic.LaserControlLogic.ensure_ready()` (2026-10-01): JB's
  own extension of `roi_multicolour_scan_sd_task.py` (connecting it to
  `TriggerLogic` and a laser, see the DAQ section above) needed to confirm
  the laser source itself is ready before an acquisition, without actually
  enabling any line - but the only way to reach the hardware's
  `ensure_ready()` was `set_laser_enabled()` immediately followed by
  `set_laser_disabled()`, which JB found "quite convoluted" and asked about.
  Worth noting why it was more than just convoluted: `set_laser_enabled()`
  also calls `enable_all_lines()`, and since the task already loads the
  imaging sequence's intensities before this point
  (`_load_user_parameters()`), that briefly wrote real non-zero voltage to
  the DAQ-controlled source for every allowed line - a genuine, if brief,
  physical emission pulse that had nothing to do with checking readiness,
  immediately undone by the following `set_laser_disabled()`. Added
  `ensure_ready()` to `LaserControlLogic` as a direct passthrough to
  `self._laser.ensure_ready()`, touching nothing else (`_enabled`,
  `enable_all_lines()`, `disable_all_lines()` are untouched) - confirmed
  safe by checking both `LaserControlInterface` implementations:
  `DaqLaserController.ensure_ready()` is a no-op, while
  `LumencorCelesta.ensure_ready()` wakes the source from standby and waits
  for it to report ready, with no line-state side effects either way.
  `roi_multicolour_scan_sd_task.py` now calls `self._laser_logic.ensure_ready()`
  directly instead of the enable/disable pair. Verified with a new mock test
  (`t16_laser_ensure_ready.py`, loading the real `laser_control_logic.py`):
  `ensure_ready()` reaches the hardware and never touches
  `enable_all_lines()`/`disable_all_lines()`/`_enabled`, and
  `set_laser_enabled()`/`set_laser_disabled()` are unaffected.
- `roi_multicolour_scan_sd.py._checkpoint_path()` (2026-10-02): the resume
  checkpoint was being written as a hidden dotfile
  (`.<sample_name>_roi_scan_checkpoint.yaml` in `self.save_path`) - JB
  flagged that saving it like a cache file isn't ideal and asked for it as
  a regular file if nothing argues against that. Nothing does: `_load_checkpoint()`/
  `_save_checkpoint()` only ever go through `os.path.exists()`/`open()`/
  `yaml.safe_load()`/`yaml.safe_dump()`, none of which treat a leading dot
  specially - the only effect of the dot was hiding the file from `ls`,
  file managers, and any `glob()`-based tooling that doesn't special-case
  dotfiles. Dropped the leading dot, so the file is now
  `<sample_name>_roi_scan_checkpoint.yaml`, sitting as a plain, visible
  file directly in `self.save_path` (alongside the dated per-run output
  folders). One minor side effect worth knowing about: it'll now show up
  in that directory listing like any other file - previously it didn't.
  Also worth knowing, unrelated to today's change but adjacent: this file
  is never deleted, even once `completed=True` is reached, so one
  `<sample_name>_roi_scan_checkpoint.yaml` will persist indefinitely per
  sample name in `self.save_path` - happy to clean that up too if wanted,
  but leaving it as-is for now since it wasn't what was asked. Verified by
  direct diff (one line changed, only the leading dot removed) plus
  `py_compile` - a literal filename change like this has no behavior to
  exercise beyond that.
- `tasks/photobleaching_sd.py` (2026-10-08): `PhotoBleachingTask` declares
  `start_warning` (disconnect the TTL cable from the Lumencor/Celesta shutter
  input before starting, otherwise the lasers will not emit) and
  `end_warning` (reconnect it before any imaging task), shown by the Task
  Runner GUI (see Task runner > Added). No other change to the task.
- `tasks/photobleaching.py` (2026-10-09):
  new `PhotoBleachingRAMMTask` (no warnings; `user_config_path = 'TO FILL'`
  until the RAMM YAML location is known - the task then refuses to run with
  "user_config_path not set for PhotoBleachingRAMMTask — fill it in
  photobleaching.py", before any hardware call; commented config example in
  its docstring, not added to `RAMM_config.cfg`, which has no
  `laser_control_logic` yet). New dummy subclasses, at the end of
  `photobleaching.py` (one file for all setups),
  `PhotoBleachingSDDummyTask` / `PhotoBleachingRAMMDummyTask`: the real
  SD/RAMM code on the dummy hardware, only `user_config_path` differs
  (`/home/jb/qudi/qudi_task_config_files/photobleaching_task_sd.yaml` /
  `..._RAMM.yaml`). They first lived in a separate dummy file, folded into
  `photobleaching.py` the same day. Registered in `dummy_config.cfg` as
  `photobleaching_sd_dummy` / `photobleaching_ramm_dummy` (connecting
  `roi_logic` and `laser_control_logic`). New experiment definition
  `custom_experiments_config/dummy/photobleaching_sd.yaml` (copy of the SD
  one, named `photobleaching_SD` so it does not clash with the dummy
  `photobleaching_RAMM`), added to the dummy configurator's `experiments`.
- `tasks/psf_stack_opm.py` + `OPM_config.cfg` (2026-10-13): new
  `PsfStackTask`, a first, software-timed PSF z-stack acquisition on the OPM
  over galvo positions and laser lines. For each galvo voltage
  (`galvo_start_v` → `galvo_stop_v`, step `galvo_step_v`; the task stops if
  `galvo_logic.set_voltage` returns `False`), a z-stack around the focus the
  user set by hand (`z_focus` read once from `roi_logic.stage_position`,
  ±`z_half_range_um`, step `z_step_um`; x and y never change), one image per
  laser line at each plane (`laser_lines`, fired in order: reset, set
  intensity, lasers on, snap, lasers off). Experiment parameters are class
  attributes ("EXPERIMENT PARAMETERS - edit here"); `data_root` and
  `metadata_template` come from the task `options:` in the config (clear
  error at run start if missing). Before any hardware call it checks the
  steps, the galvo limits, the laser lines (exist + allowed), the camera,
  the stage z axis and the live mode, then logs the totals and the disk
  estimate. Output: `<data_root>/<YYYY-MM-DD>/psf_<HHMMSS>/` (never
  overwritten), one `galvo_NNN/` per position with one uint16 TIFF per laser
  line (`{wavelength}nm.tif`, frames appended as they arrive with
  `tifffile.TiffWriter`, z order) and a `metadata.txt` from the OPM template
  (Acquisition fields + a new `PSF` section), plus `galvo_positions.csv`
  (one row per completed position). The per-plane step is one method,
  `_acquire_plane`, to be replaced by a DAQ-triggered version later. A
  failed snap is detected even though `camera_logic` keeps the previous
  image. Interrupt is checked before every image; cleanup (never raises)
  switches the lasers off, sends the galvo to rest, the stage back to focus,
  closes the TIFFs (partial files kept, only complete planes written) and
  restores the previous camera and exposure. Known limits: software-timed,
  lasers on during the camera overhead, one camera. Registered as
  `psf_stack` in `OPM_config.cfg` (same `D:\DATA` and template path as
  `basic_imaging`). Verified against `qudi-core==1.7.0` and 1.8.0 with fake
  camera / laser / galvo / ROI logic connected through qudi's connectors
  (52/52 checks): call order per plane, x/y fixed, 3 folders × 2 TIFFs ×
  5 frames in z order, metadata and CSV content, end state; 1.0 → 2.0 V at
  0.1 V gives exactly 11 voltages; galvo outside its limits, a blocked or
  unknown laser line, missing `data_root` / `metadata_template`, a stage
  without z axis, bad steps and an unknown camera all fail with no hardware
  action and no folder; a galvo failure mid-run stops the task with only the
  completed positions in the CSV; an interrupt stops before the next image
  with a safe end state and readable partial TIFFs; a stale camera image is
  detected. Still to be checked by JB on the OPM.
- `logic/roi_logic.py` (2026-10-13): `roi_logic._move_stage` made public as
  `move_stage` (no behaviour change: `(x, y, z)` in ROI order, x/y always
  sent, z only if the stage has a z axis, returns `True` if accepted, emits
  `sigStageMoved`), for tasks that need absolute moves - e.g. the PSF task's
  z-only moves. Its only callers, `go_to_roi` / `go_to_roi_xy`, were updated
  and send exactly the same stage commands as before (checked against the
  previous file, with and without a z axis).

#### Changed

- `tasks/psf_stack_opm.py`, `tasks/roi_multicolour_scan_sd.py` (2026-10-14):
  scan stage speed, camera from the experiment configurator, snap check.
  - Stage speed: `scan_stage_velocity` is a class attribute (PSF:
    `{'z': 500.0}` µm/s, slow z moves avoid stage ringing between planes; SD:
    `{'x': 1000.0, 'y': 1000.0}`). At run start the current velocity of these
    axes is read (`roi_logic.get_stage_velocity`) and the scan velocity set
    (a refusal stops the task); the cleanup restores the velocity read at
    start (error logged on failure). `idle_stage_velocity` removed (and from
    the SD config example).
  - PSF cleanup sends the galvo to the optical axis
    (`galvo_logic.go_to_optical_axis()`), no longer to rest.
  - PSF camera: the `camera_name` option is gone; the camera comes from the
    experiment YAML (key `camera`, in `_CONFIG_KEYS`), still checked against
    `get_available_cameras()`, selected at start, previous camera + exposure
    restored by the cleanup.
  - PSF setup options: `_UNSET` removed; `user_config_path` and
    `metadata_template` must be set (None / empty -> error naming the option)
    and point to existing files.
  - PSF snap: `_acquire_plane` uses the frame returned by
    `camera_logic.start_single_acquisition()` (no `get_last_image()`, no
    "previous image" comparison); a missing frame stops the task.
  - PSF metadata: Acquisition `selected_camera` (template key) and PSF
    `z_scan_velocity_(µm/s)`. Unused `from time import sleep` removed.

- `tasks/psf_stack_opm.py` (2026-10-13): **timing instrumentation removed from
  the PSF task** (diagnosis done; the stage wait was fixed in the Tiger
  driver). Removed: `_TimingLog`, the `timing_log_enabled` option,
  `timing_log.csv` / `timing_summary.txt`, and every timing-only helper,
  attribute and import. `_cleanup` is one method again (same steps, same
  order, each protected on its own); `_acquire_plane(z_offset)` takes no timing
  ids. A plain progress line `PSF stack: galvo position i/N (V volts) done` is
  logged after each galvo position. The acquisition is unchanged: hardware
  call log identical to `main` over 15 scenarios (1090 calls). `OPM_config.cfg`
  did not set `timing_log_enabled`: no config change. 917 -> 644 lines.

- `tasks/psf_stack_opm.py` (2026-10-13): **z-only stage moves**. Every stage
  move in the run and in the cleanup is `move_stage((None, None, z))`: x and y
  are never commanded during the task. `x0` / `y0` are still read once at
  start and logged; the "stage has a z axis" check stays (fails before any
  hardware call).

- `tasks/psf_stack_opm.py` + `OPM_config.cfg` (2026-10-13): **PSF parameters
  from the experiment configurator**. The hard-coded class attributes
  (`galvo_start_v`, `galvo_stop_v`, `galvo_step_v`, `z_half_range_um`,
  `z_step_um`, `laser_lines`, `exposure_s`) and the `data_root` option are
  gone. New required option `user_config_path` (missing / `TO FILL` -> early,
  hardware-free error, like `metadata_template`); `metadata_template`,
  `camera_name`, `timing_log_enabled` stay options. At run start, before any
  hardware call, the YAML is loaded and checked (`experiment` must be
  `psf_stack`; missing key / wrong type -> error naming the file and the key):
  galvo start / stop / step; `num_z_planes` N (odd, >= 1, so the focus plane
  is acquired) and `z_step` (> 0) -> offsets `(k - (N-1)/2) * z_step`;
  `imaging_sequence` -> laser lines (string wavelengths accepted, repeats
  allowed, non-laser sources such as `Brightfield` refused); `exposure`;
  `save_path` (must exist) replaces `data_root`. The galvo-limit, laser,
  camera and stage checks still run on these values. The YAML is copied
  byte-for-byte into the run folder as `experiment_config.yaml`; the metadata
  `PSF` section records `experiment_config` (original path). Sequence, file
  names, CSV, GUI lock, timing log and cleanup unchanged. `OPM_config.cfg`:
  `psf_stack` options `data_root` -> `user_config_path`
  (`C:\Users\JB\qudi_files\qudi_task_config_files\psf_stack_task_opm.yaml`).

- `tasks/psf_stack_opm.py` (2026-10-13): **timing log** to find where the
  time goes before a hardware-triggered redesign. Instrumentation only - the
  acquisition sequence, files, checks and cleanup are unchanged.
  - `timing_log.csv` in the run folder (columns `timestamp, galvo_index,
    galvo_voltage_V, z_index, z_offset_um, line_index, wavelength_nm,
    intensity_pct, step, duration_ms`; `time.perf_counter()`, ms with 3
    decimals). Opened in append mode before the first hardware action, one
    row per completed step flushed immediately, `os.fsync()` after each plane,
    each galvo position and in cleanup, closed by the cleanup - nothing
    measured is lost on an interrupt or a crash.
  - Steps: `setup`, `cleanup` (per run); `galvo_set`, `open_writers`,
    `close_writers`, `write_metadata`, `write_csv_row` (per galvo position);
    `stage_move_cmd`, `stage_wait_idle`, `plane_total`, `plane_other` =
    plane_total minus the plane's measured steps (per plane);
    `laser_set_intensity`, `laser_enable`, `camera_snap`
    (`start_single_acquisition` only), `camera_get_image` (get + check +
    uint16), `laser_disable`, `tiff_write` (per laser_lines entry).
  - `timing_summary.txt` (end of run, or written by the cleanup marked "run
    interrupted" / "run stopped by an error"): run parameters, per step count
    / mean / median / min / max / total / % of run time, snap overhead per
    image (mean `camera_snap` - exposure), total run time, time per image,
    images per second; the same table is logged at info level. A progress
    line (mean `plane_total`, estimated time remaining) after each galvo
    position.
  - Class attribute `timing_log_enabled = True` (settable through the task
    `options:`); `False` -> nothing timed or written. A timing-file I/O
    error logs ONE error and switches timing off; the acquisition continues.
  - Only the task measures; `camera_logic` and the hardware are untouched.
- `tasks/psf_stack_opm.py` + `OPM_config.cfg` (2026-10-13): two changes
  after the first successful test on the OPM.
  - **Repeated laser lines**: the same wavelength may appear several times
    in `laser_lines` (e.g. `[(561, 10.0), (561, 50.0)]`, same sample at two
    powers); the duplicate-wavelength check is gone. TIFF writers, the frames
    returned by `_acquire_plane` and the z-loop writes are keyed by the
    entry's index, never by wavelength. File names
    `{index:02d}_{wavelength}nm_{intensity:g}pct.tif` (e.g.
    `00_561nm_10pct.tif`, `01_561nm_50pct.tif`), also used in log and error
    messages. `metadata.txt`: `laser_lines` / `laser_power_(%)` list every
    entry in order; `PSF > laser_order` lists the file names. CSV
    `laser_lines_nm` column: `wavelength@intensity` per entry, `;`-separated
    (`561@10;561@50`). The setup checks (line exists, allowed by the filter)
    run once per distinct wavelength.
  - **GUI lock during the run**: new connector `filter_wheel_logic`. Right
    after `_hardware_touched` is set, lasers off, then
    `disable_laser_actions`, `disable_camera_actions`,
    `disable_filter_actions`, `disable_tracking_mode`, `disable_roi_actions`
    (as in `roi_multicolour_scan_sd.py`). The cleanup re-enables the five as
    its last steps, each in its own try/except with `log.error`, also after
    an interrupt or an error. A failure before any hardware call locks and
    unlocks nothing. The live image still updates at each snap.
    `OPM_config.cfg`: `filter_wheel_logic: filter_wheel_logic` added under
    `psf_stack` > `connect:`.
- `tasks/photobleaching_sd.py` → `tasks/photobleaching.py` (2026-10-09,
  `git mv`, rename authorized by JB): one photobleaching task file for all
  setups. Shared code in `PhotoBleachingBase`; `PhotoBleachingSDTask` is the
  former `PhotoBleachingTask` (same YAML path, same start/end warnings, which
  stay on the SD class only). Per-setup differences are class attributes
  because qudi-core 1.7.0 does not pass task config options to ModuleTasks.
  `Spinning_disk_config.cfg`: the `photobleaching` entry now points to
  `qudi.tasks.photobleaching.PhotoBleachingSDTask` and no longer connects
  `trigger_logic` (the trigger modules and `trigger_logic` stay, the ROI
  scan task uses them). Behaviour changes:
  - **Illumination time in seconds** (the `* 60` conversion is gone).
    **YAMLs saved before this change hold minutes: re-save them from the
    configurator** (see Experiment configurator > Changed).
  - **Interruptible illumination**: the wait checks for an interrupt at
    least every 0.1 s (it was one blocking `sleep()`), so a stop from the
    Task Runner takes effect during illumination too; `_cleanup` then
    switches the lasers off.
  - **No shutter trigger**: removed the `trigger_logic` connector and the
    `trigger_celesta_shutter` pulse (only a test; on the SD the shutter TTL
    cable is disconnected by hand, covered by the warnings).
  - Dead code removed: `_wait_for_ready` / `_wait_for_done` (ZEN handshake,
    never called), the resume / ZEN text in the docstrings, unused
    `os` / `datetime` imports. The config path is logged at info level
    (was warning). Result key `imaged_rois` → `photobleached_rois`.
  - `_cleanup` keeps the same safe-state steps (first ROI, lasers off +
    intensities reset, idle velocity, ROI GUI actions back on, each in its
    own try/except). New: it does nothing if `_run` stopped before touching
    any hardware (e.g. the 'TO FILL' error), and it no longer raises if
    `_setup` failed (found by the test below).
- Verified offscreen against `qudi-core==1.7.0` (62/63 checks) and 1.8.0
  (63/63), with fake ROI/laser logic connected through `connect_modules` and
  the real `_run` / `_cleanup`: 2 ROIs × 0.3 s take 0.60 s (move → wait idle
  → lasers on → 0.3 s → lasers off, per ROI); an interrupt during a 10 s
  illumination switches the lasers off within ~50 ms; the RAMM 'TO FILL'
  error is raised with no hardware call at all; all classes have empty
  `call_parameters()` and exactly the `roi_logic` / `laser_logic`
  connectors; warnings only on SD and SD dummy; dummies override only
  `user_config_path`; all changed `.cfg` / `.yaml` files parse, and both
  configs pass qudi-core's config validation on 1.8.0. The one 1.7.0
  failure is `Spinning_disk_config.cfg`, which already failed before this
  change: its multi-module `trigger_logic` connections need qudi-core 1.8.0.
- `tasks/photobleaching.py`, `tasks/roi_multicolour_scan_sd.py`,
  `Spinning_disk_config.cfg`, `dummy_config.cfg` (2026-10-12): the YAML path
  of these tasks now comes from the config, through the task runner's new
  `options:` (see Task runner > Added), instead of being hard-coded per
  class. **Each microscope's `.cfg` must now set
  `options: user_config_path: ...` in the entry of every photobleaching /
  ROI-scan task it uses** - otherwise the task stops at run start with
  "user_config_path not set for task <class> — add `options:
  user_config_path: ...` to this task's entry in the config file", before
  touching any hardware (a `'TO FILL'` placeholder is refused the same way).
  - Photobleaching: `PhotoBleachingSDTask` and `PhotoBleachingRAMMTask`
    inherit `user_config_path = None`; the RAMM `'TO FILL'` default and the
    dummy classes `PhotoBleachingSDDummyTask` / `PhotoBleachingRAMMDummyTask`
    are removed - `dummy_config.cfg` keeps the entries
    `photobleaching_sd_dummy` / `photobleaching_ramm_dummy` but now uses the
    real SD / RAMM classes with the dummy paths as options. The SD
    start/end warnings are unchanged.
  - ROI scan (`RoiScanTask`): `user_config_path = None` with the same early
    error in `_run` (its `_cleanup` still restores stage velocity and ROI
    GUI actions afterwards, unchanged); the config path is logged at info
    level (was warning); docstring example updated to
    `options: user_config_path` (and to the real module and connector names).
  - `Spinning_disk_config.cfg`: `photobleaching` and `roi_multicolour_scan`
    get `options: user_config_path:` with exactly the paths removed from the
    code. `RAMM_config.cfg` unchanged (no laser logic there yet).
  - Verified against `qudi-core==1.7.0` and 1.8.0 with fake ROI / laser
    logic and the path given through options: 2 ROIs × 0.3 s take 0.60 s;
    an interrupt during illumination switches the lasers off within ~50 ms
    and cleanup completes; a missing or `'TO FILL'` path fails with the new
    message and no hardware call. Config validation: `dummy_config.cfg`
    passes on both versions, `Spinning_disk_config.cfg` on 1.8.0 (it
    already failed on 1.7.0 before this change - `trigger_logic`).

#### Fixed

- `tasks/roi_multicolour_scan.py` resume (2026-10-16): after a resume the
  file names written to `movie_name.txt` were `scan_None_002_ROI` instead of
  `scan_001_002_ROI` - the folder number (`prefix`) is only set when a new
  data folder is created. It is now read back from the checkpoint's data folder
  name (`NNN_Scan_...`). The same bug existed in
  `tasks/roi_multicolour_scan_sd.py`. Also, a checkpoint whose data folder no
  longer exists is not resumed (warning, run from scratch) instead of failing
  after the first ROI is imaged.
- `tasks/roi_multicolour_scan.py` cleanup (2026-10-16): `_cleanup()` raised
  an `AttributeError` when `_setup()` stopped while fetching a connector (the
  attributes it reads were set after the connectors). The attributes are now
  set first, and the cleanup only restores the hardware once `_run()` has
  started changing it (`_hardware_touched`, as in the photobleaching task). A
  run stopped before that (missing `user_config_path`, unreadable experiment
  file, bad ROI list) no longer moves the stage to the first ROI or touches the
  lasers / ROI GUI in the cleanup. The same bug existed in
  `tasks/roi_multicolour_scan_sd.py`.

### Experiment configurator

#### Added

- `exp_configurator_gui.py`, `experiment_configurator_logic.py`,
  `opm/psf_stack.yaml` (2026-10-14): field `camera` (camera section) on the
  `select_camera_comboBox` / `Camera_Label` widgets of the `.ui`. The logic
  lists `camera_logic.get_available_cameras()` (empty without a camera logic:
  the combobox is then empty and disabled). For an experiment with the field
  and no camera yet, the first camera is selected (a single camera is shown
  and selected); the choice is saved under `camera` and selected again when a
  YAML is loaded. Hidden for experiments without the field. `psf_stack.yaml`:
  `camera` (visible, required).

- `exp_configurator_gui.py` + `experiment_configurator_logic.py` (2026-10-13):
  new **Galvo section** (`galvo`): fields `galvo_start`, `galvo_stop`,
  `galvo_step` (V) mapped to `galvo_settings_Label` and the
  `galvo_start/stop/step_Label` / `_DSpinBox` widgets added by JB in
  `ui_exp_configurator.ui`; `set_visibility_galvo_settings`; logic slots
  `update_galvo_start/stop/step` (same style as `update_z_step`); spinbox
  `valueChanged` connected, values refreshed in `update_entries` (defaults
  0.0 / 0.0 / 0.1) and signal-blocked during refreshes. Definitions without
  galvo fields are unchanged.
- `custom_experiments_config/opm/psf_stack.yaml` (2026-10-13): experiment
  definition `psf_stack` for the OPM (output `psf_stack_task_opm.yaml`):
  galvo start / stop / step (1.0 / 2.0 / 0.1 V), `num_z_planes` (51),
  `z_step` (0.2 µm), `centered_focal_plane` (hidden, true),
  `imaging_sequence` (standard model), `exposure` (0.05 s), `save_path`
  (`default_from: default_path_imagedata`). Sections galvo, camera, imaging,
  scan, save.
- `OPM_config.cfg` (2026-10-13): `experiments_configurator_logic` (camera,
  laser and filter logic connected; definitions from
  `custom_experiments_config\opm\`; `psf_stack.yaml`; `tif`; `D:\DATA`) and
  `experiments_configurator_gui` (`default_path: C:\Users\JB\qudi_files`).

- Moved the ZEN-specific controls into their own dock widget (2026-10-05).
  Context: JB is bringing two new microscopes onto qudi-core (an OPM
  light-sheet setup and a fly-training arena, the latter on hold for now)
  and asked how to keep `ui_exp_configurator.ui`'s single shared form from
  getting harder to maintain as more microscope-specific fields accumulate.
  Looked at the real configs (`OPM_config.cfg`, `RAMM_config.cfg`,
  `camera_interfuse.py`) before proposing anything: the Experiment
  Configurator isn't wired into OPM or RAMM yet, OPM's two cameras go
  through `CameraInterfuse` as a one-at-a-time *selector* (not simultaneous
  dual-camera settings, so no new per-camera fields are needed there), and
  no galvo-scan hardware exists yet - so there was nothing concrete to add
  for OPM this round. What *is* real today is that `Zen_saving_folder_*`,
  `Autofocus_security_Label`, `reference_image_folder_Label`,
  `reference_images_*` and `Correlation_threshold_Label`/
  `Zen_correlation_DSpinBox` are already exclusively used by the ZEN/
  Zeiss-driven spinning-disk Hi-M epifluorescence experiment, just sitting
  as ordinary rows in the single `gridLayout` alongside every generic
  field. Agreed with JB to do this relocation first, as the safe template
  for grouping future microscope-specific fields by function (e.g. a later
  "camera selection" or "galvo scan" dock for OPM) instead of forking the
  `.ui` file per microscope.
  - `ui_exp_configurator.ui`: added a `QDockWidget`
    (`zen_autofocus_saving_DockWidget`, titled "ZEN autofocus & saving",
    docked right, movable/floatable but not closable) and moved those 9
    widgets into its own small `QGridLayout`, unchanged (same object
    names, same properties) - just relocated out of `formWidget`'s grid.
  - `exp_configurator_gui.py`: no change was needed to relocate the
    widgets themselves - `FIELD_WIDGETS`, `_set_named_widgets_visible` and
    every `on_activate()` signal connection already address widgets purely
    by object name, never by grid position. The one thing a dock needs
    that a plain grid row doesn't: something to collapse the dock itself
    to nothing when none of its fields apply (otherwise it would sit on
    screen as an empty panel). Added a generic `_sync_dock_widgets_visibility()`
    that, for every `QDockWidget` under `mainWindow`, shows it iff any of
    its own field widgets (excluding its internal content wrapper - see
    below) ended up visible; called at the end of `_hide_experiment_form()`
    and at the end of `apply_experiment_definition()`. Generic on purpose:
    a future dock needs no new wiring here, just `FIELD_SECTIONS`/
    `FIELD_WIDGETS` entries as usual.
  - Verified: the edited `.ui` parses as valid XML with the same 70 field
    widgets plus the one new dock and its one content wrapper, no
    duplicates, nothing lost (checked programmatically by diffing widget
    names). `py_compile` on the edited GUI module. Built a standalone
    simulation importing the real `exp_configurator_gui.py` (stubbing the
    `qtpy`/`qudi.core` imports, not installed in this environment) against
    a fake widget tree with faithful `isHidden()`/`isVisible()` semantics,
    then ran all 38 real experiment-definition YAML files in the repo
    through `apply_experiment_definition()`: zero exceptions, zero
    "widget not found" warnings, and the ZEN dock came out visible only
    for the two experiments that actually declare ZEN fields
    (`spinning_disk/him_epi.yaml`, `dummy/him_epi_sd.yaml`), hidden for
    the other 36. That test caught a real bug before it shipped: the
    dock's own content-wrapper widget (the implicit `QWidget` `uic.loadUi`
    sets as `QDockWidget.widget()`) is never explicitly hidden by
    anything, so the first version of the visibility check always saw it
    as "visible" regardless of the actual field widgets inside - fixed by
    excluding `dock.widget()` from the check.
  - Not done yet, by design: no new fields were added for OPM (camera
    selection, galvo scan) or the fly arena - this round was only the ZEN
    relocation JB asked to go ahead with. `experiments_configurator_logic`/
    `experiments_configurator_gui` still aren't wired into `OPM_config.cfg`
    or `RAMM_config.cfg` at all.

#### Changed

- `gui/experiments_setup/ui_exp_configurator.ui` (2026-10-09): the
  illumination time is now entered in seconds, matching the photobleaching
  task and the experiment definitions (`unit: s`). Label "Illumination time
  (min)" → "Illumination time (s)", `illumination_time_DSpinBox` maximum
  100 → 3600 (1 h; still 1 decimal). Minimal XML edit (two values), no
  Designer re-save. **Photobleaching YAMLs saved before this change hold the
  time in minutes and must be re-saved from the configurator** (5 would now
  mean 5 s).

#### Fixed

- `exp_configurator_gui.py` (2026-10-13): **ZEN section after the ZEN dock
  removal** in `ui_exp_configurator.ui`. `set_visibility_ZEN_security_settings`
  referenced `Autofocus_security_Label`, which no longer exists; since every
  definition hides all sections first, selecting ANY experiment raised
  `AttributeError`. The header is now `zen_settings_Label`; the ZEN
  saving-folder field (`zen_saving_path`) moved from the "save" to the
  "zen_security" section, and the three hard-coded `Zen_saving_folder_*`
  lines left `set_visibility_save_settings`. The ZEN section now shows / hides
  header, reference images, correlation threshold and saving folder together.
  Checked on all SD, RAMM, PALM and dummy definitions: no ZEN widget unless a
  ZEN field is declared. `_sync_dock_widgets_visibility` kept (no-op without
  docks). The uncommitted widget renames in the `.ui` (galvo widgets,
  `zen_settings_Label`) are part of this change.

- `logic/experiment_configurator_logic.py` (2026-10-01): `ExpConfigLogic.on_activate()`
  built `self.lasers` (the list backing the imaging-sequence editor's
  `laser_ComboBox`, see `gui/experiments_setup/exp_configurator_gui.py`) from
  every key of `laser_control_logic`'s `laser_dict`, regardless of each
  entry's `allowed` flag - so the combo box offered every wavelength the
  laser source supports, not only the ones the configured dichroic actually
  allows (`optical_path['dichroic_allowed_wavelengths_nm']`). Found by JB
  while setting up the imaging sequence on the OPM. `basic_imaging_gui.py`'s
  own laser selector already filtered on `laser_dict[...]['allowed']` - this
  fix makes `self.lasers` do the same, so both of `laser_ComboBox`'s
  population sites (the general configuration form and the per-experiment
  imaging-sequence editor, both of which just read `self._exp_logic.lasers`)
  are fixed by the one change. Verified with a new mock test
  (`t15_laser_combobox_fix.py`, loading the real
  `experiment_configurator_logic.py`): `lasers` only includes the allowed
  wavelengths, and stays an empty list when no laser logic is connected.
- Standardized the generated/loaded experiment task-config files on `.yaml`
  (2026-10-02): JB flagged that these files were being saved as `.yml`
  while he's now consistently using `.yaml`. Root cause: every
  `output_filename:` field in the experiment-definition files under
  `custom_config/custom_experiments_config/{spinning_disk,dummy}/` (the
  filename `ExpConfigLogic.save_to_exp_config_file()` writes to when the
  Experiment Configurator's "Save" button is used) ended in `.yml`, while
  the GUI's own "Save copy"/"Load experiment configuration" dialogs
  (`exp_configurator_gui.py`) filter on `'yaml files (*.yaml)'` - so a
  normally-saved file wouldn't show up by default in the Open dialog.
  Changed the extension (content and filename stem otherwise untouched) in
  all 22 definition files affected: 6 under `spinning_disk/` (2 of them -
  `him_epi.yaml`, `roi_multicolour_scan.yaml` - are the ones actually
  enabled in `Spinning_disk_config.cfg` today) and 16 under `dummy/` (12 of
  them enabled in `dummy_config.cfg`); `sequential_injections.yaml` and
  `him_ramm.yaml`/`him.yaml` were already `.yaml` and left alone. Also
  updated the matching `user_config_path` class-attribute default in each
  active task to agree with the file its own experiment definition now
  points to: `roi_multicolour_scan_sd.py` (`RoiScanTask`,
  `roi_multicolor_scan_task_sd.yml` -> `.yaml`) and `photobleaching_sd.py`
  (`PhotoBleachingTask`, new this round - `photobleaching_task_sd.yml` ->
  `.yaml`), both now wired into `Spinning_disk_config.cfg`'s
  `module_tasks:`. Picked up mid-fix that JB had, in parallel, renamed
  `roi_multicolour_scan_sd_task.py` to `roi_multicolour_scan_sd.py` and
  already applied the `resume` -> `resume_from_roi` rename discussed
  earlier today himself (plus two new `_cleanup()` lines resetting the
  laser's external-trigger flag and cached intensities) - re-staged
  everything fresh before editing so this fix lands on top of his changes
  rather than clobbering them. Left `ramm/` and `palm/`
  experiment-definition files alone for now: `experiments_configurator_logic`
  isn't wired into `RAMM_config.cfg` or `OPM_config.cfg` yet, so those
  files aren't loaded by anything at the moment - same fix is trivial to
  apply there once that part of the migration happens. Also NOT touched:
  the legacy-style `HiM_imaging_SD.py`, `HiM_imaging_RAMM.py`,
  `ROI_multicolour_imaging_SD.py`, `ROI_multicolour_imaging_RAMM.py` still
  reference `.yml` in places, but none of them are wired into any active
  `module_tasks` config right now, and most of their `.yml` references are
  write-once output/metadata files rather than loaded configuration.
  Verified: each of the 22 YAML edits is a single-line, single-character
  diff (confirmed file-by-file); both task-file edits verified by a direct
  diff (one line each, extension only) plus `py_compile`
  - a literal default-value change like this has no behavior to exercise
  beyond that.

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
