# Changelog

This file records the main changes made to the project.

## [Unreleased]

Last updated: 2026-09-22

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

#### Fixed

- Fixed the undefined variable `exc` in the exception handler of the live loop
  of `camera_logic`.
- Fixed the ORCA imports and the duplicated `get_size` definition.
- Removed the duplicated call of `init_save_settings_ui()` in `basic_imaging_gui.on_activate`, which created the save dialog twice.
- Kinetix `set_image` now clears the previous ROI (`reset_rois()`) before setting the new one: pyvcam appends ROIs on sensors supporting several regions, which made the reset to full sensor fail with "New ROI overlaps existing ROI".

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

#### Fixed

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