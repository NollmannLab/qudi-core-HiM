# Changelog

This file records the main changes made to the project.

## [Unreleased]

Last updated: 2026-07-30

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