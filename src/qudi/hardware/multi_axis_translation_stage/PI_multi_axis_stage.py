# -*- coding: utf-8 -*-
"""
Author: F Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2021-03-03 -> refactored as a generic PI multi-axis stage in 2026-07-22

This file contains a hardware module for a Physik Instrumente two- or
three-axis stage. Each configured logical axis is controlled by one PI
controller and can be connected through a shared USB daisy chain or through an
individual USB connection.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from time import sleep, time
from typing import Dict, List, Optional
from pathlib import Path

import numpy as np
from pipython import GCSDevice, pitools

from qudi.core.configoption import ConfigOption
from qudi.interface.multi_axis_stage_interface import MultiAxisStageInterface


# ======================================================================================================================
# Hardware class
# ======================================================================================================================

class PIMultiAxisStage(MultiAxisStageInterface):
    """Generic PI two- or three-axis stage.

    Each item in ``axes`` maps a logical Qudi axis label to one PI controller.
    Linear axes are exposed in micrometres and micrometres per second, while
    rotational axes are exposed in degrees and degrees per second. PI native
    linear units are assumed to be millimetres and are converted internally.

    The module only owns PI communication and generic stage operations. It does
    not know which axis is the pipetting-robot safety axis, and it never parks
    the robot automatically. Those responsibilities belong to the pipetting
    robot interfuse.

    Daisy-chain example::

        pi_multi_axis_stage:
          module.Class: 'multi_axis_stage.pi_multi_axis_stage.PIMultiAxisStage'
          options:
            connection_mode: 'daisychain'
            daisychain_description: '0019550121'
            master_axis: 'z'
            timeout: 30.0
            poll_interval: 0.05
            axes:
              x:
                controller_name: 'C-863'
                stage_name: null
                type: 'linear'
                daisychain_id: 2
                reference_mode: 'FNL'
                velocity_max: 20000.0
              y:
                controller_name: 'C-863'
                stage_name: null
                type: 'linear'
                daisychain_id: 3
                reference_mode: 'FNL'
                velocity_max: 20000.0
              z:
                controller_name: 'C-863'
                stage_name: null
                type: 'linear'
                daisychain_id: 1
                reference_mode: 'FNL'
                velocity_max: 20000.0

    Individual USB example::

        pi_multi_axis_stage:
          module.Class: 'multi_axis_stage.pi_multi_axis_stage.PIMultiAxisStage'
          options:
            connection_mode: 'individual'
            axes:
              r:
                controller_name: 'C-863'
                serialnumber: '0019550121'
                stage_name: null
                type: 'linear'
                reference_mode: 'FNL'
                velocity_max: 20000.0
              phi:
                controller_name: 'C-863'
                serialnumber: '0019550124'
                stage_name: null
                type: 'rotation'
                reference_mode: 'FRF'
                velocity_max: 20.0
              z:
                controller_name: 'C-863'
                serialnumber: '0019550119'
                stage_name: null
                type: 'linear'
                reference_mode: 'FNL'
                velocity_max: 20000.0
    """

    # Connection configuration.
    _connection_mode = ConfigOption('connection_mode', missing='error')
    _daisychain_description = ConfigOption('daisychain_description', default=None)
    _master_axis = ConfigOption('master_axis', default=None)

    # Logical-axis mapping. See the class docstring for the supported fields.
    _axes_config = ConfigOption('axes', missing='error')

    # Waiting behaviour used by wait_for_idle and calibration.
    _timeout = ConfigOption('timeout', 30.0, missing='warn')
    _poll_interval = ConfigOption('poll_interval', 0.5, missing='warn')

    # Attributes initialized on activation.
    axis_list = None
    _devices = None
    _device_axes = None
    _axis_types = None
    _reference_modes = None
    _daisychain_id = None

    # PI generally exposes linear positions in mm. The public HiM interface uses um.
    _linear_conversion_factor = 1000.0

    def on_activate(self):
        """Validate configuration, connect all PI controllers, and initialize stages.

        Connections can be opened through one shared USB daisy chain or through
        individual USB links. The module supports two or three configured axes.
        Stage referencing is intentionally not performed automatically; callers
        must invoke :meth:`calibrate` explicitly.
        """
        self._devices = {}
        self._device_axes = {}
        self._axis_types = {}
        self._reference_modes = {}
        self._daisychain_id = None

        try:
            self._validate_configuration()

            # Create one GCSDevice object per logical axis/controller.
            for axis_label in self.axis_list:
                controller_name = self._axes_config[axis_label]['controller_name']
                self._devices[axis_label] = GCSDevice(controller_name)

            if self._connection_mode == 'daisychain_windows':
                self._connect_daisychain()
            elif self._connection_mode == 'individual_linux':
                self._connect_individually_linux()
            else:
                self._connect_individually()

            # Initialize the connected stage/controller pairs without starting
            # a reference move. Referencing remains an explicit operation.
            for axis_label in self.axis_list:
                self._initialize_axis(axis_label)
                self._device_axes[axis_label] = self._resolve_device_axis(axis_label)
                ref = self._get_reference_status(axis_label)
                if not ref:
                    self.log.info(f"Axis {axis_label} is being referenced...")
                    self.calibrate([axis_label])

                device = self._devices[axis_label]
                self.log.info(
                    f'PI axis {axis_label!r} connected through '
                    f'{device.GetInterfaceDescription()}: {device.qIDN().strip()}'
                )

            self.log.info(
                f'PI multi-axis stage activated with axes {self.axis_list} '
                f'using {self._connection_mode} communication.'
            )

        except Exception as error:
            self.log.error(f'PI multi-axis stage activation failed: {error}')
            self._close_connections()
            raise

    def on_deactivate(self):
        """Close PI communication without moving or parking any axis."""
        self._close_connections()

    # ------------------------------------------------------------------------------------------------------------------
    # Motor interface functions
    # ------------------------------------------------------------------------------------------------------------------

    def get_constraints(self):
        """Retrieve constraints for all configured axes.

        PI travel limits are queried from each controller. Optional velocity and
        step constraints are read from the corresponding entry in ``axes``.
        Linear controller values are converted from millimetres to micrometres.

        :return: Constraint dictionaries indexed by logical axis label.
        :rtype: dict
        """
        constraints = {}

        for axis_label in self.axis_list:
            config = self._axes_config[axis_label]
            device = self._devices[axis_label]
            device_axis = self._device_axes[axis_label]
            axis_type = self._axis_types[axis_label]

            controller_min = device.qTMN(device_axis)[device_axis]
            controller_max = device.qTMX(device_axis)[device_axis]
            pos_min = self._from_controller_units(axis_label, controller_min)
            pos_max = self._from_controller_units(axis_label, controller_max)

            constraints[axis_label] = {
                'label': axis_label,
                'type': axis_type,
                'unit': 'um' if axis_type == 'linear' else 'degree',
                'velocity_unit': 'um/s' if axis_type == 'linear' else 'degree/s',
                'ramp': None,
                'pos_min': pos_min,
                'pos_max': pos_max,
                'pos_step': config.get('position_step'),
                'max_step': config.get('max_step'),
                'vel_min': config.get('velocity_min', 0.0),
                'vel_max': config.get('velocity_max'),
                'vel_step': config.get('velocity_step'),
                'acc_min': None,
                'acc_max': None,
                'acc_step': None,
            }

        return constraints

    def move_rel(self, param_dict):
        """Move selected axes by relative distances or angles.

        :param dict param_dict: Relative movements in micrometres for linear
            axes and degrees for rotational axes, indexed by logical label.
        :return: ``True`` if at least one movement command was accepted.
        :rtype: bool
        """
        moved = False
        constraints = self.get_constraints()
        current_positions = self.get_pos(list(param_dict))

        for axis_label, movement in param_dict.items():
            if axis_label not in self.axis_list:
                self.log.warning(f'Axis {axis_label!r} is not configured.')
                continue

            movement = float(np.round(movement, decimals=6))
            target = current_positions[axis_label] + movement
            axis_constraints = constraints[axis_label]
            max_step = axis_constraints['max_step']

            if max_step is not None and abs(movement) > max_step:
                self.log.warning(
                    f'Relative movement of axis {axis_label!r} exceeds its '
                    f'maximum step of {max_step}.'
                )
                continue

            if not self._position_is_allowed(target, axis_constraints):
                self.log.warning(
                    f'Relative target {target} for axis {axis_label!r} is outside '
                    f'[{axis_constraints["pos_min"]}, {axis_constraints["pos_max"]}].'
                )
                continue

            controller_step = self._to_controller_units(axis_label, movement)
            self._devices[axis_label].MVR(
                self._device_axes[axis_label],
                controller_step,
            )
            moved = True

        return moved

    def move_abs(self, param_dict):
        """Move selected axes to absolute positions or angles.

        :param dict param_dict: Absolute targets in micrometres for linear axes
            and degrees for rotational axes, indexed by logical label.
        :return: ``True`` if at least one movement command was accepted.
        :rtype: bool
        """
        moved = False
        constraints = self.get_constraints()

        for axis_label, target in param_dict.items():
            if axis_label not in self.axis_list:
                self.log.warning(f'Axis {axis_label!r} is not configured.')
                continue

            target = float(np.round(target, decimals=6))
            axis_constraints = constraints[axis_label]
            if not self._position_is_allowed(target, axis_constraints):
                self.log.warning(
                    f'Absolute target {target} for axis {axis_label!r} is outside '
                    f'[{axis_constraints["pos_min"]}, {axis_constraints["pos_max"]}].'
                )
                continue

            controller_target = self._to_controller_units(axis_label, target)
            self._devices[axis_label].MOV(
                self._device_axes[axis_label],
                controller_target,
            )
            moved = True

        return moved

    def abort(self):
        """Stop movement of all configured PI axes.

        :return: ``True`` when all stop commands were issued successfully.
        :rtype: bool
        """
        success = True
        for axis_label in self.axis_list:
            try:
                self._devices[axis_label].HLT(noraise=True)
            except Exception as error:
                success = False
                self.log.error(f'Could not abort PI axis {axis_label!r}: {error}')
        return success

    def get_pos(self, param_list: Optional[List[str]] = None,) -> Dict[str, float]:
        """Get current positions of selected axes.

        :param list param_list: Optional logical axis labels. All configured
            axes are returned when omitted.
        :return: Positions in interface units, indexed by logical label.
        :rtype: dict
        """
        positions = {}
        for axis_label in self._selected_axes(param_list):
            device = self._devices[axis_label]
            device_axis = self._device_axes[axis_label]
            controller_position = device.qPOS(device_axis)[device_axis]
            positions[axis_label] = self._from_controller_units(
                axis_label,
                controller_position,
            )
        return positions

    def get_status(self, param_list: Optional[List[str]] = None,) -> Dict[str, bool]:
        """Get on-target states of selected axes.

        :param list param_list: Optional logical axis labels. All configured
            axes are returned when omitted.
        :return: ``True`` for on-target axes and ``False`` for moving axes.
        :rtype: dict
        """
        status = {}
        for axis_label in self._selected_axes(param_list):
            device = self._devices[axis_label]
            device_axis = self._device_axes[axis_label]
            status[axis_label] = bool(device.qONT(device_axis)[device_axis])
        return status

    def calibrate(self, param_list: Optional[List[str]] = None,) -> int:
        """Reference selected axes using their configured PI reference modes.

        The generic hardware follows the requested/configured axis order and
        contains no pipetting-specific Z-first policy. The robot interfuse adds
        that ordering when all robot axes are calibrated together.

        :param list param_list: Optional logical axis labels. All configured
            axes are referenced when omitted.
        :return: ``0`` if all requested axes were referenced, otherwise ``-1``.
        :rtype: int
        """
        selected_axes = self._selected_axes(param_list)
        if not selected_axes:
            return -1

        success = True
        for axis_label in selected_axes:
            reference_mode = self._reference_modes[axis_label]
            if reference_mode is None:
                self.log.warning(
                    f'No reference_mode is configured for PI axis {axis_label!r}.'
                )
                success = False
                continue

            device = self._devices[axis_label]
            device_axis = self._device_axes[axis_label]

            try:
                # RON enables referencing mode on controllers that support it.
                # Some PI devices do not expose RON, so it remains optional.
                ron_command = getattr(device, 'RON', None)
                if callable(ron_command):
                    ron_command(device_axis, values=1)
                else:
                    self.log.warning(f"RON command not available for {device}")

                reference_command = getattr(device, reference_mode, None)
                if not callable(reference_command):
                    raise RuntimeError(
                        f'Controller {device} does not support reference command {reference_mode!r}.'
                    )
                else:
                    reference_command(device_axis)

                if not self._wait_for_axes([axis_label]):
                    raise TimeoutError(
                        f'Referencing PI axis {axis_label!r} exceeded {self._timeout} s.'
                    )

            except Exception as error:
                success = False
                self.log.error(f'Calibration of PI axis {axis_label!r} failed: {error}')

        return 0 if success else -1

    def get_velocity(self, param_list: Optional[List[str]] = None,) -> Dict[str, float]:
        """Get current velocities of selected axes.

        :param list param_list: Optional logical axis labels. All configured
            axes are returned when omitted.
        :return: Velocities in interface units, indexed by logical label.
        :rtype: dict
        """
        velocities = {}
        for axis_label in self._selected_axes(param_list):
            device = self._devices[axis_label]
            device_axis = self._device_axes[axis_label]
            controller_velocity = device.qVEL(device_axis)[device_axis]
            velocities[axis_label] = self._from_controller_units(
                axis_label,
                controller_velocity,
            )
        return velocities

    def set_velocity(self, param_dict):
        """Set velocities of selected axes.

        :param dict param_dict: Velocities in micrometres per second for linear
            axes and degrees per second for rotational axes.
        :return: ``0`` if at least one velocity was set, otherwise ``-1``.
        :rtype: int
        """
        changed = False
        constraints = self.get_constraints()

        for axis_label, velocity in param_dict.items():
            if axis_label not in self.axis_list:
                self.log.warning(f'Axis {axis_label!r} is not configured.')
                continue

            velocity = float(velocity)
            axis_constraints = constraints[axis_label]
            if not self._velocity_is_allowed(velocity, axis_constraints):
                self.log.warning(
                    f'Velocity {velocity} for axis {axis_label!r} is outside '
                    f'[{axis_constraints["vel_min"]}, {axis_constraints["vel_max"]}].'
                )
                continue

            controller_velocity = self._to_controller_units(axis_label, velocity)
            self._devices[axis_label].VEL(
                self._device_axes[axis_label],
                controller_velocity,
            )
            changed = True

        return 0 if changed else -1

    def wait_for_idle(self):
        """Wait until all configured axes are on target or timeout occurs.

        :return: ``True`` when every axis is on target, otherwise ``False``.
        :rtype: bool
        """
        return self._wait_for_axes(self.axis_list)

    # ------------------------------------------------------------------------------------------------------------------
    # Helper functions
    # ------------------------------------------------------------------------------------------------------------------

    def _validate_configuration(self):
        """Validate connection and per-axis configuration."""
        if self._connection_mode not in ('daisychain_windows', 'individual_windows', 'individual_linux'):
            raise ValueError(
                "connection_mode must be either 'daisychain_windows', 'individual_windows' or 'individual_linux'."
            )

        if not isinstance(self._axes_config, dict):
            raise TypeError('axes must be a mapping indexed by logical axis label.')

        self.axis_list = list(self._axes_config)
        if len(self.axis_list) not in (2, 3):
            raise ValueError('PIMultiAxisStage requires exactly two or three axes.')
        if len(self.axis_list) != len(set(self.axis_list)):
            raise ValueError('PI logical axis labels must be unique.')

        daisychain_ids = []
        for axis_label in self.axis_list:
            config = self._axes_config[axis_label]
            if not isinstance(axis_label, str) or not axis_label:
                raise ValueError('Every PI logical axis label must be a non-empty string.')
            if not isinstance(config, dict):
                raise TypeError(f'Configuration of axis {axis_label!r} must be a mapping.')
            if not config.get('controller_name'):
                raise ValueError(f'Axis {axis_label!r} requires controller_name.')

            axis_type = str(config.get('type', 'linear')).lower()
            if axis_type not in ('linear', 'rotation'):
                raise ValueError(
                    f'Axis {axis_label!r} type must be linear or rotation.'
                )
            self._axis_types[axis_label] = axis_type

            default_reference = 'FNL' if axis_type == 'linear' else 'FRF'
            reference_mode = config.get('reference_mode', default_reference)
            if reference_mode is not None:
                reference_mode = str(reference_mode).upper()
            self._reference_modes[axis_label] = reference_mode

            if self._connection_mode == 'daisychain_windows':
                if config.get('daisychain_id') is None:
                    raise ValueError(f'Axis {axis_label!r} requires daisychain_id.')
                daisychain_ids.append(config['daisychain_id'])
            elif not config.get('serialnumber'):
                raise ValueError(f'Axis {axis_label!r} requires serialnumber.')

        if self._connection_mode == 'daisychain':
            if self._master_axis not in self.axis_list:
                raise ValueError('master_axis must identify one configured logical axis.')
            if not self._daisychain_description:
                raise ValueError('daisychain_description is required in daisychain mode.')
            if len(daisychain_ids) != len(set(daisychain_ids)):
                raise ValueError('PI daisy-chain device IDs must be unique.')

    def _connect_daisychain(self):
        """Open the shared USB daisy chain and connect every controller."""
        master_device = self._devices[self._master_axis]
        master_device.OpenUSBDaisyChain(description=self._daisychain_description)
        self._daisychain_id = master_device.dcid

        for axis_label in self.axis_list:
            daisychain_id = self._axes_config[axis_label]['daisychain_id']
            self._devices[axis_label].ConnectDaisyChainDevice(
                daisychain_id,
                self._daisychain_id,
            )

    def _connect_individually(self):
        """Open one USB connection per configured controller. This method is used on WINDOWS """
        for axis_label in self.axis_list:
            serialnumber = self._axes_config[axis_label]['serialnumber']
            self._devices[axis_label].ConnectUSB(serialnum=serialnumber)

    def _connect_individually_linux(self):
        """Open one USB connection per configured controller. This method is used on LINUX since USB ports are
         emulated as COM ports """
        for axis_label in self.axis_list:
            serial_path = self._axes_config[axis_label]['serialnumber']
            serial_number = self.resolve_linux_serial_port(serial_path)
            self._devices[axis_label].ConnectRS232(comport=serial_number, baudrate=9600)

    @staticmethod
    def resolve_linux_serial_port(by_id_path: str) -> str:
        port_path = Path(by_id_path)

        if not port_path.exists():
            raise FileNotFoundError(f'Serial device not found: {by_id_path}')

        resolved_path = port_path.resolve()

        if not resolved_path.name.startswith(('ttyUSB', 'ttyACM')):
            raise RuntimeError(
                f'Unexpected serial-device target: {resolved_path}'
            )

        return str(resolved_path)

    def _initialize_axis(self, axis_label):
        """Initialize one PI stage/controller without referencing it."""
        device = self._devices[axis_label]
        pitools.startup(device, refmodes=None)

    def _resolve_device_axis(self, axis_label):
        """Resolve the PI controller axis associated with one logical label."""
        device = self._devices[axis_label]
        available_axes = list(device.axes)
        configured_axis = self._axes_config[axis_label].get('device_axis')

        if configured_axis is None:
            if len(available_axes) != 1:
                raise RuntimeError(
                    f'Controller for logical axis {axis_label!r} exposes axes '
                    f'{available_axes}; configure device_axis explicitly.'
                )
            return available_axes[0]

        for device_axis in available_axes:
            if device_axis == configured_axis or str(device_axis) == str(configured_axis):
                return device_axis

        raise RuntimeError(
            f'Configured device_axis {configured_axis!r} for logical axis '
            f'{axis_label!r} is not among {available_axes}.'
        )

    def _get_reference_status(self, axis_label):
        """Return reference state of each configured axis."""

        device = self._devices[axis_label]
        device_axis = self._device_axes[axis_label]

        try:
            status = bool(device.qFRF(device_axis)[device_axis])
        except Exception as error:
            self.log.warning(f"Could not determine reference state of axis {axis_label}: {error}")
            status = None

        return status

    def _selected_axes(self,  param_list: Optional[List[str]] = None) -> List[str]:
        """Return valid selected axes while warning about unknown labels."""
        if not param_list:
            return list(self.axis_list)

        selected = []
        for axis_label in param_list:
            if axis_label in self.axis_list:
                if axis_label not in selected:
                    selected.append(axis_label)
            else:
                self.log.warning(f'Axis {axis_label!r} is not configured.')
        return selected

    def _to_controller_units(self, axis_label, value):
        """Convert an interface position or velocity to PI native units."""
        if self._axis_types[axis_label] == 'linear':
            return float(value) / self._linear_conversion_factor
        return float(value)

    def _from_controller_units(self, axis_label, value):
        """Convert a PI native position or velocity to interface units."""
        if self._axis_types[axis_label] == 'linear':
            return float(value) * self._linear_conversion_factor
        return float(value)

    @staticmethod
    def _position_is_allowed(position, constraints):
        """Check a position against optional lower and upper limits."""
        lower = constraints['pos_min']
        upper = constraints['pos_max']
        if lower is not None and position < lower:
            return False
        if upper is not None and position > upper:
            return False
        return True

    @staticmethod
    def _velocity_is_allowed(velocity, constraints):
        """Check a velocity against optional lower and upper limits."""
        lower = constraints['vel_min']
        upper = constraints['vel_max']
        if lower is not None and velocity < lower:
            return False
        if upper is not None and velocity > upper:
            return False
        return True

    def _wait_for_axes(self, axis_labels):
        """Poll selected axes until all are on target or timeout expires."""
        t0 = time()
        while True:
            try:
                status = self.get_status(axis_labels)
                if status and all(status.values()):
                    return True
            except Exception as error:
                self.log.error(f'Could not query PI stage status: {error}')
                return False

            if time() - t0 >= self._timeout:
                self.log.error(
                    f'PI multi-axis stage timeout occurred after {self._timeout} s.'
                )
                return False
            sleep(self._poll_interval)

    def _close_connections(self):
        """Close all opened PI connections and reset runtime state."""
        if not self._devices:
            return

        if self._connection_mode == 'daisychain_windows':
            # Close subordinate GCSDevice connections before closing the shared
            # chain through the configured master device.
            for axis_label, device in self._devices.items():
                if axis_label == self._master_axis:
                    continue
                try:
                    device.CloseConnection()
                except Exception as error:
                    self.log.warning(
                        f'Could not close PI axis {axis_label!r} connection: {error}'
                    )

            master_device = self._devices.get(self._master_axis)
            if master_device is not None:
                try:
                    master_device.CloseDaisyChain()
                except Exception as error:
                    self.log.warning(f'Could not close PI daisy chain: {error}')
                try:
                    master_device.CloseConnection()
                except Exception as error:
                    self.log.warning(f'Could not close PI master connection: {error}')
        else:
            for axis_label, device in self._devices.items():
                try:
                    device.CloseConnection()
                except Exception as error:
                    self.log.warning(
                        f'Could not close PI axis {axis_label!r} connection: {error}'
                    )

        self._devices = {}
        self._device_axes = {}
        self._daisychain_id = None

