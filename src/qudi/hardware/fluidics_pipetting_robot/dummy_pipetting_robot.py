# -*- coding: utf-8 -*-
"""
Author: JB Fiche - adapted for qudi-core-HiM using original code from F Barho
Created: 2026-07-16

This module contains a dummy implementation of a two- or three-axis pipetting
robot. It reproduces the public API of the Physik Instrumente stage driver
without establishing a hardware connection.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

import numpy as np

from qudi.core.module import Base
from qudi.core.configoption import ConfigOption


# ======================================================================================================================
# Hardware class
# ======================================================================================================================
class DummyPipettingRobot(Base):
    """Dummy implementation of the PI two- or three-axis pipetting robot.

    The module preserves the public API of the real PI stage driver while
    storing positions, velocities, and motion states in memory. It can
    therefore be used to test logic and GUI modules without connected hardware.

    Example configuration::

        dummy_pipetting_robot:
          module.Class: 'motor.dummy_pipetting_robot.DummyPipettingRobot'
          options:
            daisychain_connection: true
            serialnumber_master: 'dummy-master'
            first_axis_controllername: 'dummy-controller'
            second_axis_controllername: 'dummy-controller'
            third_axis_controllername: 'dummy-controller'
            first_axis_label: 'x'
            second_axis_label: 'y'
            third_axis_label: 'z'
            first_axis_daisychain_id: 1
            second_axis_daisychain_id: 2
            third_axis_daisychain_id: 3
            first_axis_type: 'linear'
            second_axis_type: 'linear'
            third_axis_type: 'linear'
    """

    # Configuration options retained from the real PI driver. Connection and
    # controller values are accepted for configuration compatibility but are
    # not used to communicate with hardware in this dummy implementation.
    _daisychain_connection = ConfigOption('daisychain_connection', missing='error')
    _serialnum_master = ConfigOption('serialnumber_master', missing='error')
    _serialnum_second_axis = ConfigOption('serialnumber_second_axis')  # Optional for individual connections.
    _serialnum_third_axis = ConfigOption('serialnumber_third_axis')  # Optional for individual connections.
    _first_axis_controllername = ConfigOption('first_axis_controllername', missing='error')
    _second_axis_controllername = ConfigOption('second_axis_controllername', missing='error')
    _third_axis_controllername = ConfigOption('third_axis_controllername', None)
    _first_axis_label = ConfigOption('first_axis_label', missing='error')
    _second_axis_label = ConfigOption('second_axis_label', missing='error')
    _third_axis_label = ConfigOption('third_axis_label', None)  # Optional third axis.
    _first_axis_daisychain_id = ConfigOption('first_axis_daisychain_id')  # Retained for daisy-chain compatibility.
    _second_axis_daisychain_id = ConfigOption('second_axis_daisychain_id')
    _third_axis_daisychain_id = ConfigOption('third_axis_daisychain_id')
    _first_axis_type = ConfigOption('first_axis_type', 'linear', missing='warn')
    _second_axis_type = ConfigOption('second_axis_type', 'linear', missing='warn')
    _third_axis_type = ConfigOption('third_axis_type', None)

    # Public attributes retained for compatibility with code using the real PI
    # driver. Dummy object instances replace the physical PI device objects.
    first_axis_label = None
    second_axis_label = None
    third_axis_label = None
    pidevice_1st_axis = None
    pidevice_2nd_axis = None
    pidevice_3rd_axis = None
    daisychainid = None
    first_axis_ID = None
    second_axis_ID = None
    third_axis_ID = None

    def on_activate(self):
        """Initialize the simulated axes and their in-memory state.

        Axis labels are read from the module configuration. Every configured
        axis starts at position zero, with a velocity of 1.0 and an on-target
        status of ``True``.
        """
        # Copy configured labels to the public attributes used by the real
        # driver and by external logic modules.
        self.first_axis_label = self._first_axis_label
        self.second_axis_label = self._second_axis_label
        self.third_axis_label = self._third_axis_label

        # Placeholder objects emulate the presence of PI device instances.
        self.pidevice_1st_axis = object()
        self.pidevice_2nd_axis = object()
        self.pidevice_3rd_axis = object() if self._third_axis_label else None

        # In the dummy, the configured labels also serve as axis identifiers.
        self.first_axis_ID = self.first_axis_label
        self.second_axis_ID = self.second_axis_label
        self.third_axis_ID = self.third_axis_label

        # Store the simulated position of every configured axis.
        self._positions = {
            self.first_axis_label: 0.0,
            self.second_axis_label: 0.0,
        }
        if self.third_axis_label:
            self._positions[self.third_axis_label] = 0.0

        # Store the simulated velocity of every configured axis.
        self._velocities = {
            self.first_axis_label: 1.0,
            self.second_axis_label: 1.0,
        }
        if self.third_axis_label:
            self._velocities[self.third_axis_label] = 1.0

        # ``True`` indicates that an axis has reached its target position.
        self._on_target = {axis: True for axis in self._positions}

        # Initialize all axes at their simulated home position.
        self.calibrate()
        self.log.info('Dummy pipetting robot activated.')

    def on_deactivate(self):
        """Deactivate the dummy module.

        No hardware connection needs to be closed and the simulated state is
        discarded automatically with the module instance.
        """
        pass

    # ------------------------------------------------------------------------------------------------------------------
    # Motor interface functions
    # ------------------------------------------------------------------------------------------------------------------

    def get_constraints(self):
        """Return the simulated motion constraints for all configured axes.

        Each axis is represented by a dictionary containing its label, type,
        unit, position limits, velocity limits, and unsupported acceleration
        parameters. Linear axes use metres and rotational axes use degrees.

        :return: Constraints indexed by axis label.
        :rtype: dict
        """
        constraints = {}

        def axis_dict(label, axis_type):
            """Create the constraint dictionary for one simulated axis.

            :param str label: Axis label used throughout the module.
            :param str axis_type: Axis type, normally ``'linear'`` or ``'rotation'``.
            :return: Constraint values for the requested axis.
            :rtype: dict
            """
            unit = 'degree' if axis_type == 'rotation' else 'mm'
            return {
                'label': label,
                'type': axis_type,
                'unit': unit,
                'ramp': None,
                'pos_min': 0.0,
                'pos_max': 1000.0,
                'pos_step': 1.0,
                'vel_min': 0.0,
                'vel_max': 20.0,
                'vel_step': 0.01,
                'acc_min': None,
                'acc_max': None,
                'acc_step': None,
            }

        constraints[self.first_axis_label] = axis_dict(self.first_axis_label, self._first_axis_type)
        constraints[self.second_axis_label] = axis_dict(self.second_axis_label, self._second_axis_type)
        if self.third_axis_label:
            constraints[self.third_axis_label] = axis_dict(
                self.third_axis_label, self._third_axis_type
            )
        return constraints

    def move_rel(self, param_dict):
        """Move one or more simulated axes by relative distances.

        Requested positions are rounded to four decimal places and applied only
        when the resulting target remains within the configured constraints.

        :param dict param_dict: Mapping of axis labels to relative movements.
        :return: ``True`` if at least one movement was applied, otherwise ``False``.
        :rtype: bool
        """
        err = False
        constraints = self.get_constraints()
        cur_pos = self.get_pos()

        # Example input: {'x': 20, 'y': 0, 'z': 10}.
        for key, value in param_dict.items():
            # Avoid floating-point overflow effects in position comparisons.
            value = np.round(value, decimals=4)
            if (
                key in constraints
                and constraints[key]['pos_min']
                <= cur_pos[key] + value
                <= constraints[key]['pos_max']
            ):
                # The dummy movement is instantaneous, but the status briefly
                # reproduces the busy/on-target transition of a real stage.
                self._positions[key] = cur_pos[key] + value
                self._on_target[key] = False
                err = True
                self._on_target[key] = True
            else:
                print('Target value not in allowed range. Relative movement not done.')
        return err

    def move_abs(self, param_dict):
        """Move one or more simulated axes to absolute positions.

        Requested positions are rounded to four decimal places and applied only
        when they are within the configured position limits.

        :param dict param_dict: Mapping of axis labels to absolute target positions.
        :return: ``True`` if at least one movement was applied, otherwise ``False``.
        :rtype: bool
        """
        err = False
        constraints = self.get_constraints()

        for key, value in param_dict.items():
            # Avoid floating-point overflow effects in position comparisons.
            value = np.round(value, decimals=4)
            if (
                key in constraints
                and constraints[key]['pos_min'] <= value <= constraints[key]['pos_max']
            ):
                self._positions[key] = value
                self._on_target[key] = False
                err = True
                self._on_target[key] = True
            else:
                print('Target value not in allowed range. Absolute movement not done.')
        return err

    def abort(self):
        """Abort all simulated movements.

        Since dummy movements are instantaneous, aborting simply marks every
        axis as being on target.

        :return: ``True`` to indicate that the abort request was handled.
        :rtype: bool
        """
        for axis in self._on_target:
            self._on_target[axis] = True
        print('Movement aborted.')
        return True

    def get_pos(self, param_list=None):
        """Return the current simulated position of selected axes.

        :param list param_list: Optional list of axis labels. If omitted, the
            positions of all configured axes are returned.
        :return: Positions indexed by axis label.
        :rtype: dict
        """
        if not param_list:
            # Return a copy so callers cannot modify the internal state directly.
            return dict(self._positions)

        pos_dict = {}
        for item in param_list:
            if item in self._positions:
                pos_dict[item] = self._positions[item]
            else:
                print(f'Given axis not available: {item}.')
        return pos_dict

    def get_status(self, param_list=None):
        """Return the on-target status of selected simulated axes.

        A value of ``True`` means that the corresponding axis has reached its
        target position.

        :param list param_list: Optional list of axis labels. If omitted, the
            status of all configured axes is returned.
        :return: On-target states indexed by axis label.
        :rtype: dict
        """
        if not param_list:
            return dict(self._on_target)

        status_dict = {}
        for item in param_list:
            if item in self._on_target:
                status_dict[item] = self._on_target[item]
            else:
                print('Given axis not available.')
        return status_dict

    def calibrate(self, param_list=None):
        """Calibrate selected simulated axes to their home position.

        Calibration sets the position of each selected axis to zero and marks
        it as on target. If no axis list is supplied, all axes are calibrated.

        :param list param_list: Optional list of axis labels to calibrate.
        :return: Error code; always ``0`` for the dummy implementation.
        :rtype: int
        """
        if not param_list:
            targets = list(self._positions.keys())
        else:
            # Ignore labels that are not configured in this dummy instance.
            targets = [item for item in param_list if item in self._positions]

        for axis in targets:
            self._positions[axis] = 0.0
            self._on_target[axis] = True
        return 0

    def get_velocity(self, param_list=None):
        """Return the current simulated velocity of selected axes.

        :param list param_list: Optional list of axis labels. If omitted, the
            velocities of all configured axes are returned.
        :return: Velocities indexed by axis label.
        :rtype: dict
        """
        if not param_list:
            return dict(self._velocities)

        vel_dict = {}
        for item in param_list:
            if item in self._velocities:
                vel_dict[item] = self._velocities[item]
            else:
                print('Given axis not available.')
        return vel_dict

    def set_velocity(self, param_dict):
        """Set the simulated velocity of one or more axes.

        A velocity is applied only when the axis exists and the requested value
        lies within the corresponding velocity limits.

        :param dict param_dict: Mapping of axis labels to velocity values.
        :return: ``0`` if at least one velocity was set, otherwise ``-1``.
        :rtype: int
        """
        err = -1
        constraints = self.get_constraints()

        # Example input: {'x': 20, 'y': 5, 'z': 10}.
        for key, value in param_dict.items():
            if (
                key in constraints
                and constraints[key]['vel_min'] <= value <= constraints[key]['vel_max']
            ):
                self._velocities[key] = value
                err = 0
            else:
                print('Target value not in allowed range. Velocity not set.')
        return err

    def wait_for_idle(self):
        """Wait until the simulated stage is idle.

        Dummy movements complete immediately, so this method returns without
        blocking and is provided only for API compatibility with the real driver.
        """
        return None

