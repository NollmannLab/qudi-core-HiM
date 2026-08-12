# -*- coding: utf-8 -*-
"""
Author: JB Fiche
Created: 2026-07-22

This file contains an interfuse representing a three-axis pipetting robot. It
connects to any hardware module implementing MultiAxisStageInterface and adds
robot-specific axis roles, validation, calibration order, and parking.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from typing import Dict, List, Optional
from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.interface.pipetting_robot_interface import PipettingRobotInterface


# ======================================================================================================================
# Hardware interfuse class
# ======================================================================================================================

class PipettingRobot(PipettingRobotInterface):
    """Generic three-axis pipetting robot built on a multi-axis stage backend.

    The connected backend can be the PI hardware, a dummy implementation, or a
    future non-PI device, provided that it implements
    :class:`MultiAxisStageInterface`.

    The first and second axes define the in-plane positioning system. They can
    be either two translations (Cartesian robot) or one translation and one
    rotation (polar robot). The Z axis is mandatory and must always be linear.

    Example configuration for a Cartesian robot::

        pipetting_robot:
            module.Class: 'interfuse_hardware.pipetting_robot.PipettingRobot'
            connect:
                motor: 'dummy_translation_stage'
            options:
                first_axis: 'x'
                second_axis: 'y'
                z_axis: 'z'
                z_safety_position: 0.0
                parking_position:
                    x: 0.0
                    y: 0.0
                    z: 0.0
                park_on_deactivate: false
                tube_types:
                    - '2mL flat tube'
                    - '2mL round tube'
                pos1_x_default: 13.0
                pos1_y_default: 4.0
                pos1_z_default:
                    - 88.0
                    - 87.0
                exp_setup: 'dummy'
                max_number_tubes : 100
    """

    # Generic multi-axis motor backend.
    motor = Connector(interface='MultiAxisStageInterface', name='motor')

    # Robot axis roles. The Z role is always required to be linear.
    _first_axis_label = ConfigOption('first_axis', missing='error')
    _second_axis_label = ConfigOption('second_axis', missing='error')
    _z_axis_label = ConfigOption('z_axis', missing='error')

    # Robot specific grid properties (either cartesian or polar)
    _grid = ConfigOption('grid', missing='error')
    _num_x_positions = ConfigOption('x_positions', default=0,  converter=int)
    _num_y_positions = ConfigOption('y_positions', default=0,  converter=int)
    _num_r_positions = ConfigOption('r_positions', default=0,  converter=int)
    _num_phi_positions = ConfigOption('phi_positions', default=0,  converter=int)
    _delta_x = ConfigOption('delta_x', default=0,  converter=float)
    _delta_y = ConfigOption('delta_y', default=0,  converter=float)
    _delta_r = ConfigOption('delta_r', default=0,  converter=float)
    _delta_phi =  ConfigOption('delta_phi', default=0,  converter=float)

    # Robot-specific safe and parking positions, expressed in interface units.
    _z_safety_position = ConfigOption('z_safety_position', missing='error', converter=float)
    _parking_position = ConfigOption('parking_position', missing='error', converter=dict)
    _park_on_deactivate = ConfigOption('park_on_deactivate', missing='error', converter=bool)

    # Robot-specific position of the first tube
    _pos1_axis_1_default = ConfigOption('pos1_axis_1_default', missing='error', converter=float)
    _pos1_axis_2_default = ConfigOption('pos1_axis_2_default', missing='error', converter=float)
    _pos1_axis_3_default = ConfigOption('pos1_axis_3_default', missing='error', converter=list)
    _setup = ConfigOption('exp_setup', missing='error')
    _tube_types = ConfigOption('tube_types', missing='error')

    # Attributes initialized on activation.
    _motor = None
    axis_list = None
    max_num_probes = 0

    def on_activate(self):
        """Connect to the motor backend and validate the robot axis layout."""
        self._motor = self.motor()
        self.axis_list = [
            self._first_axis_label,
            self._second_axis_label,
            self._z_axis_label,
        ]
        
        # define the maximum number of probes
        if self._grid == 'cartesian':  # for RAMM setup
            self.max_num_probes = self._num_x_positions * self._num_y_positions
            if self.max_num_probes == 0:
                self.log.error("The grid geometry parameters are not properly set.")
        elif self._grid == 'polar':  # for Airyscan setup
            self.max_num_probes = self._num_r_positions * self._num_phi_positions
            if self.max_num_probes == 0:
                self.log.error("The grid geometry parameters are not properly set.")
        else:
            self.log.error('Your grid type is currently not covered.')

        if len(set(self.axis_list)) != 3:
            raise ValueError('The first, second, and Z robot axis labels must be unique.')

        constraints = self._motor.get_constraints()
        missing_axes = [axis for axis in self.axis_list if axis not in constraints]
        if missing_axes:
            raise RuntimeError(
                f'Connected motor does not provide robot axes {missing_axes}. '
                f'Available axes: {list(constraints)}.'
            )

        extra_axes = [axis for axis in constraints if axis not in self.axis_list]
        if extra_axes:
            raise RuntimeError(
                'The connected pipetting-robot motor must expose exactly the '
                f'three configured axes. Unexpected axes: {extra_axes}.'
            )

        z_constraints = constraints[self._z_axis_label]
        if z_constraints.get('type') != 'linear':
            raise RuntimeError(
                f'Pipetting-robot Z axis {self._z_axis_label!r} must be linear.'
            )
        if z_constraints.get('unit') != 'um':
            raise RuntimeError(
                f'Pipetting-robot Z axis {self._z_axis_label!r} must use um.'
            )

        for axis_label in (self._first_axis_label, self._second_axis_label):
            axis_type = constraints[axis_label].get('type')
            if axis_type not in ('linear', 'rotation'):
                raise RuntimeError(
                    f'Robot axis {axis_label!r} must be linear or rotation.'
                )

        self._validate_position(
            self._z_axis_label,
            self._z_safety_position,
            constraints,
            option_name='z_safety_position',
        )

        if self._parking_position is not None:
            if not isinstance(self._parking_position, dict):
                raise TypeError('parking_position must be a mapping indexed by axis label.')
            missing_parking_axes = [
                axis for axis in self.axis_list if axis not in self._parking_position
            ]
            if missing_parking_axes:
                raise ValueError(
                    'parking_position must contain all robot axes. Missing: '
                    f'{missing_parking_axes}.'
                )
            for axis_label in self.axis_list:
                self._validate_position(
                    axis_label,
                    self._parking_position[axis_label],
                    constraints,
                    option_name='parking_position',
                )

        self.log.info(
            f'Pipetting robot activated with axes {self.axis_list}; '
            f'Z safety axis is {self._z_axis_label!r}.'
        )

    def on_deactivate(self):
        """Optionally park the robot before the backend is disconnected."""
        if self._park_on_deactivate and self._parking_position is not None:
            try:
                if not self.park():
                    self.log.error('Pipetting robot could not be parked on deactivation.')
            except Exception as error:
                self.log.error(f'Pipetting robot parking failed on deactivation: {error}')
        self._motor = None

    # ------------------------------------------------------------------------------------------------------------------
    # MultiAxisStageInterface implementation
    # ------------------------------------------------------------------------------------------------------------------

    def get_robot_parameters(self):
        """Return robot-specific parameters needed by logic and GUI."""
        return {
            'pos1_axis_1_default': self._pos1_axis_1_default,
            'pos1_axis_2_default': self._pos1_axis_2_default,
            'pos1_axis_3_default': self._pos1_axis_3_default,
            'exp_setup': self._setup,
            'tube_types': self._tube_types,
            'max_number_tubes': self.max_num_probes,
            'z_safety_position': self._z_safety_position,
            'coordinate_system': self._grid,
        }

    def get_grid_properties(self):
        """Return grid properties needed by logic and GUI."""
        return {
            'grid': self._grid,
            'axis_1': self._first_axis_label,
            'axis_2': self._second_axis_label,
            'axis_3': self._z_axis_label,
            'z_safety_pos': self._z_safety_position,
            'max_number_tubes': self.max_num_probes,
        }

    def map_probe_number_to_grid_coordinates(self):
        """ For a cartesian grid, this method generates a mapping of probe positions to coordinates on a
        serpentine grid (just grid points, no metric coordinates):
        1: (0, 0), 2: (0, 1), 3: (0, 2), etc.. values in (x, y) order, y being the index that varies rapidly.

        For a polar grid, this method generates a mapping of probe positions to coordinates on on a grid using
        using polar coordinates
        1: (0, 0), 2: (1, 0), 3: (2, 0), 4: (0, 1), 5: (1, 1), .. etc. Values in (r, phi) order, r varying rapidly.

        :return dict coord_dict: dictionary mapping the probe position to the corresponding grid position
        """
        if self._grid == 'cartesian':  # for RAMM setup
            # create the coordinate grid
            list_even = [(x, y) for x in range(self._num_x_positions) for y in range(self._num_y_positions) if x % 2 == 0]
            list_odd = [(x, y) for x in range(self._num_x_positions) for y in reversed(range(self._num_y_positions)) if x % 2 != 0]
            list_all = list_even + list_odd
            coords_list = sorted(list_all, key=self.sort_first)

            # associate a grid point to each probe position
            coord_dict = {}
            for key in range(self.max_num_probes):
                coord_dict[key+1] = coords_list[key]

        elif self._grid == 'polar':  # for Airyscan setup

            # coords_list = [(x, y) for y in range(0, -360, -10) for x in [40, 20, 0]]  # this would directly define the metric coordinates
            coords_list = [(x, y) for y in range(self._num_phi_positions) for x in range(self._num_r_positions)]

            coord_dict = {}
            for key in range(self.max_num_probes):
                coord_dict[key+1] = coords_list[key]

        else:
            coord_dict = {}

        return coord_dict

    def map_xy_position_to_probe_number(self, probe_grid_dict, origin):
        """ This method calculates the in-plane coordinates given the metrics of the respective setup
        (spacing of probe positions in x, y directions or r, phi directions) and stores them in a dictionary.

        :param probe_grid_dict: dictionary mapping probe positions to coordinates
        :param origin: origin coordinates of the first tube position on the grid
        :return dict inv_dict: dictionary containing a tuple of in-plane coordinates as key and associated probe number as value.

        This dictionary serves as look-up-table in the fluidics gui module to check if the stage is currently at a probe position.
        """
        probe_xy_position_dict = {}
        if self._grid == 'cartesian':
            for key in probe_grid_dict:
                x_pos = probe_grid_dict[key][0] * self._delta_x + origin[0] + probe_grid_dict[key][1] * -0.11
                y_pos = probe_grid_dict[key][1] * self._delta_y + origin[1] + probe_grid_dict[key][0] * -0.055
                position = (x_pos, y_pos)
                probe_xy_position_dict[key] = position

        elif self._grid == 'polar':
            for key in probe_grid_dict:
                r_pos = probe_grid_dict[key][0] * self._delta_r + origin[0]
                phi_pos = probe_grid_dict[key][1] * self._delta_phi + origin[1]
                position = (r_pos, phi_pos)
                probe_xy_position_dict[key] = position

        else:
            self.log.warning('Your grid type is currently not covered.')

        # invert the keys and values in the dictionary because we want to access the target position by the key
        inv_dict = dict((v, k) for k, v in probe_xy_position_dict.items())
        return inv_dict

    def get_constraints(self):
        """Return constraints of the three robot axes in robot-axis order.

        :return: Constraint dictionaries indexed by robot axis label.
        :rtype: dict
        """
        constraints = self._motor.get_constraints()
        return {axis: dict(constraints[axis]) for axis in self.axis_list}

    def move_rel(self, param_dict):
        """Move selected robot axes by relative distances or angles.

        :param dict param_dict: Relative movements indexed by robot axis label. For example : {'x': 0.0, 'y': 0.0, 'z': 0.0}
        if the axis are defined as x, y, z.
        :return: ``True`` if at least one movement command was accepted.
        :rtype: bool
        """
        return self._motor.move_rel(self._validated_param_dict(param_dict))

    def move_abs(self, param_dict):
        """Move selected robot axes to absolute positions or angles.

        This low-level interface method delegates movements without imposing a
        safety sequence. The positioning logic already performs the Z-safety,
        in-plane, and final-Z sequence. Use :meth:`park` for the dedicated robot
        parking sequence.

        :param dict param_dict: Absolute targets indexed by robot axis label. For example : {'x': 0.0, 'y': 0.0, 'z': 0.0}
        if the axis are defined as x, y, z.
        :return: ``True`` if at least one movement command was accepted.
        :rtype: bool
        """
        return self._motor.move_abs(self._validated_param_dict(param_dict))

    def abort(self):
        """Abort movement of all robot axes.

        :return: ``True`` if the backend handled the abort request.
        :rtype: bool
        """
        return self._motor.abort()

    def get_pos(self, param_list: Optional[List[str]] = None,) -> Dict[str, float]:
        """Return current positions of selected robot axes.

        :param list param_list: Optional robot axis labels. All axes are returned
            when omitted.
        :return: Positions indexed by robot axis label. The format is : {'x': 0.0, 'y': 0.0, 'z': 0.0} or
        {'r': 0.0, 'phi': 0.0, 'z': 0.0} depending on the selected robot axes.
        :rtype: dict
        """
        return self._motor.get_pos(self._selected_axes(param_list))

    def get_status(self, param_list: Optional[List[str]] = None,) -> Dict[str, bool]:
        """Return on-target states of selected robot axes.

        :param list param_list: Optional robot axis labels. All axes are returned
            when omitted.
        :return: On-target states indexed by robot axis label.
        :rtype: dict
        """
        return self._motor.get_status(self._selected_axes(param_list))

    def calibrate(self, param_list: Optional[List[str]] = None,) -> int:
        """Calibrate selected robot axes in a safe order.

        When all robot axes are requested, Z is calibrated first and must become
        idle before the two in-plane axes are calibrated. When an explicit
        subset is supplied, only those axes are calibrated; Z is still handled
        first when present.

        :param list param_list: Optional robot axis labels. All axes are
            calibrated when omitted.
        :return: ``0`` when all requested calibrations succeed, otherwise ``-1``.
        :rtype: int
        """
        selected_axes = self._selected_axes(param_list)
        ordered_axes = []
        if self._z_axis_label in selected_axes:
            ordered_axes.append(self._z_axis_label)
        ordered_axes.extend(axis for axis in selected_axes if axis != self._z_axis_label)

        for axis_label in ordered_axes:
            if self._motor.calibrate([axis_label]) != 0:
                self.log.error(f'Calibration failed for robot axis {axis_label!r}.')
                return -1
            if not self._motor.wait_for_idle():
                self.log.error(
                    f'Robot axis {axis_label!r} did not become idle after calibration.'
                )
                return -1
        return 0

    def get_velocity(self, param_list: Optional[List[str]] = None,) -> Dict[str, float]:
        """Return velocities of selected robot axes.

        :param list param_list: Optional robot axis labels. All axes are returned
            when omitted.
        :return: Velocities indexed by robot axis label.
        :rtype: dict
        """
        return self._motor.get_velocity(self._selected_axes(param_list))

    def set_velocity(self, param_dict):
        """Set velocities of selected robot axes.

        :param dict param_dict: Target velocities indexed by robot axis label.
        :return: ``0`` if at least one velocity was accepted, otherwise ``-1``.
        :rtype: int
        """
        return self._motor.set_velocity(self._validated_param_dict(param_dict))

    def wait_for_idle(self):
        """Wait until all robot axes are idle or a timeout occurs.

        :return: ``True`` when the backend becomes idle, otherwise ``False``.
        :rtype: bool
        """
        return self._motor.wait_for_idle()

    # ------------------------------------------------------------------------------------------------------------------
    # Robot-specific functions
    # ------------------------------------------------------------------------------------------------------------------

    def park(self):
        """Move the robot to its configured parking position safely.

        Z first moves to ``z_safety_position``. Only after Z is on target are
        the first and second axes moved. Finally, Z moves to its configured
        parking coordinate when that value differs from the safety coordinate.

        :return: ``True`` when the complete parking sequence succeeds.
        :rtype: bool
        """
        if self._parking_position is None:
            self.log.error('Cannot park robot because parking_position is not configured.')
            return False

        if not self._motor.move_abs({self._z_axis_label: self._z_safety_position}):
            return False
        if not self._motor.wait_for_idle():
            return False

        in_plane_target = {
            self._first_axis_label: self._parking_position[self._first_axis_label],
            self._second_axis_label: self._parking_position[self._second_axis_label],
        }
        if not self._motor.move_abs(in_plane_target):
            return False
        if not self._motor.wait_for_idle():
            return False

        final_z = self._parking_position[self._z_axis_label]
        if final_z != self._z_safety_position:
            if not self._motor.move_abs({self._z_axis_label: final_z}):
                return False
            if not self._motor.wait_for_idle():
                return False

        return True

    # ------------------------------------------------------------------------------------------------------------------
    # Helper functions
    # ------------------------------------------------------------------------------------------------------------------

    def _selected_axes(self, param_list: Optional[List[str]] = None) -> List[str]:
        """Validate and return selected robot axes in requested order."""
        if not param_list:
            return list(self.axis_list)

        selected = []
        for axis_label in param_list:
            if axis_label not in self.axis_list:
                self.log.warning(f'Axis {axis_label!r} is not a robot axis.')
                continue
            if axis_label not in selected:
                selected.append(axis_label)
        return selected

    def _validated_param_dict(self, param_dict):
        """Reject unknown robot-axis keys before forwarding a command."""
        if not isinstance(param_dict, dict):
            raise TypeError('Stage parameters must be supplied as a dictionary.')

        unknown_axes = [axis for axis in param_dict if axis not in self.axis_list]
        if unknown_axes:
            raise ValueError(f'Unknown pipetting-robot axes: {unknown_axes}.')
        return dict(param_dict)

    @staticmethod
    def _validate_position(axis_label, position, constraints, option_name):
        """Validate a configured robot position against backend constraints."""
        try:
            position = float(position)
        except (TypeError, ValueError) as error:
            raise TypeError(
                f'{option_name} for axis {axis_label!r} must be numeric.'
            ) from error

        axis_constraints = constraints[axis_label]
        lower = axis_constraints.get('pos_min')
        upper = axis_constraints.get('pos_max')
        if lower is not None and position < lower:
            raise ValueError(
                f'{option_name} for axis {axis_label!r} is below {lower}.'
            )
        if upper is not None and position > upper:
            raise ValueError(
                f'{option_name} for axis {axis_label!r} is above {upper}.'
            )

    @staticmethod
    def sort_first(val):
        """ Helper function for sorting a list of tuples by the first element of each tuple,
        used for setting up the serpentine grid

        :return: the first element of value (in the context here, value is a 2dim tuple (x, y))
        """
        return val[0]