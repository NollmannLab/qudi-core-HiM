# -*- coding: utf-8 -*-

"""
# Author: JB Fiche (from original F.Barho)
# Created: 2026-04-16
# This file contains the dummy for a motorized XY translation stage interface.

qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
"""
from qudi.core.configoption import ConfigOption
from qudi.interface.multi_axis_stage_interface import MultiAxisStageInterface
import time


class DummySingleAxisStage:
    """Generic dummy motor representing one translation axis."""

    def __init__(self, label):
        self.label = label
        self.pos = 0.0
        self.vel = 1000.0
        self.status = True


class DummyMultiAxisStage(MultiAxisStageInterface):
    """Dummy implementation of a two- or three-axis translation stage.

    Positions are expressed in micrometres and velocities in micrometres
    per second. The third axis is optional and, when configured, is always a
    translation axis.

    Example configuration::

        dummy_stage:
          module.Class: 'translation_stage.dummy_multi_axis_stage.DummyMultiAxisStage'
          options:
            first_axis_label: 'x'
            second_axis_label: 'y'
            third_axis_label: 'z'
            x_min: 0.0
            x_max: 100000.0
            y_min: 0.0
            y_max: 100000.0
            z_min: 0.0
            z_max: 1000.0
            delay_after_move: 0.0
    """

    _x_min = ConfigOption(name='x_min', default=0.0)
    _x_max = ConfigOption(name='x_max', default=100000.0)
    _y_min = ConfigOption(name='y_min', default=0.0)
    _y_max = ConfigOption(name='y_max', default=100000.0)
    _z_min = ConfigOption(name='z_min', default=0.0)
    _z_max = ConfigOption(name='z_max', default=1000.0)
    _wait_after_movement = ConfigOption(name='delay_after_move', default=0.0)  # in seconds
    _first_axis_label = ConfigOption(name='first_axis_label', default='x', missing='warn')
    _second_axis_label = ConfigOption(name='second_axis_label', default='y', missing='warn')
    _third_axis_label = ConfigOption(name='third_axis_label', default=None)

    axis_list = None
    _axes = None

    def on_activate(self):
        """Initialize the configured dummy translation axes."""
        axis_labels = [
            self._first_axis_label,
            self._second_axis_label,
            self._third_axis_label,
        ]
        self.axis_list = [label for label in axis_labels if isinstance(label, str)]

        if len(self.axis_list) != len(set(self.axis_list)):
            raise ValueError('Dummy stage axis labels must be unique.')

        self._axes = {
            axis_label: DummySingleAxisStage(axis_label)
            for axis_label in self.axis_list
        }

    def on_deactivate(self):
        """Deactivate the dummy stage."""
        pass

    # ------------------------------------------------------------------------------------------------------------------
    # Motor interface functions
    # ------------------------------------------------------------------------------------------------------------------

    def get_constraints(self):
        """Retrieve the simulated constraints of all configured axes.

        All axes are translations. Positions are expressed in micrometres and
        velocities in micrometres per second.

        :return: Constraint dictionaries indexed by axis label.
        :rtype: dict
        """
        limits = {
            self._first_axis_label: (self._x_min, self._x_max),
            self._second_axis_label: (self._y_min, self._y_max),
        }
        if self._third_axis_label:
            limits[self._third_axis_label] = (self._z_min, self._z_max)

        constraints = {}
        for axis_label in self.axis_list:
            pos_min, pos_max = limits[axis_label]
            constraints[axis_label] = {
                'label': axis_label,
                'type': 'linear',
                'unit': 'um',
                'velocity_unit': 'um/s',
                'ramp': None,
                'pos_min': float(pos_min),
                'pos_max': float(pos_max),
                'pos_step': 0.001,
                'max_step': 1.0,  # retained for compatibility with focus_logic
                'vel_min': 0.0,
                'vel_max': 100000.0,
                'vel_step': 1.0,
                'acc_min': None,
                'acc_max': None,
                'acc_step': None,
            }
        return constraints

    def move_rel(self, param_dict):
        """Move selected dummy axes by relative distances.

        :param dict param_dict: Relative movements in micrometres, indexed by
            axis label.
        :return: ``True`` if at least one movement was applied.
        :rtype: bool
        """
        moved = False
        constraints = self.get_constraints()

        for axis_label, movement in param_dict.items():
            if axis_label not in self._axes:
                self.log.warning(f'Specified axis not available: {axis_label}')
                continue

            current_position = self._axes[axis_label].pos
            target_position = current_position + movement
            axis_constraints = constraints[axis_label]

            if not axis_constraints['pos_min'] <= target_position <= axis_constraints['pos_max']:
                self.log.warning(
                    f'Cannot move axis {axis_label} by {movement}: target {target_position} '
                    f'is outside [{axis_constraints["pos_min"]}, {axis_constraints["pos_max"]}].'
                )
                continue

            self._axes[axis_label].status = False
            self._make_wait_after_movement()
            self._axes[axis_label].pos = target_position
            self._axes[axis_label].status = True
            moved = True

        return moved

    def move_abs(self, param_dict):
        """Move selected dummy axes to absolute positions.

        :param dict param_dict: Absolute targets in micrometres, indexed by
            axis label.
        :return: ``True`` if at least one movement was applied.
        :rtype: bool
        """
        moved = False
        constraints = self.get_constraints()

        for axis_label, target_position in param_dict.items():
            if axis_label not in self._axes:
                self.log.warning(f'Specified axis not available: {axis_label}')
                continue

            axis_constraints = constraints[axis_label]
            if not axis_constraints['pos_min'] <= target_position <= axis_constraints['pos_max']:
                self.log.warning(
                    f'Cannot move axis {axis_label} to {target_position}: target is outside '
                    f'[{axis_constraints["pos_min"]}, {axis_constraints["pos_max"]}].'
                )
                continue

            self._axes[axis_label].status = False
            self._make_wait_after_movement()
            self._axes[axis_label].pos = target_position
            self._axes[axis_label].status = True
            moved = True

        return moved

    def abort(self):
        """Abort all simulated movements.

        Dummy movements are synchronous, so aborting only restores every axis
        to its idle/on-target state.

        :return: ``True`` because the abort request is always handled.
        :rtype: bool
        """
        for axis in self._axes.values():
            axis.status = True
        self.log.info('Dummy stage movement stopped.')
        return True

    def get_pos(self, param_list=None):
        """Get current positions of selected axes.

        :param list param_list: Optional axis labels. All configured axes are
            returned when omitted.
        :return: Positions in micrometres, indexed by axis label.
        :rtype: dict
        """
        return {
            axis_label: self._axes[axis_label].pos
            for axis_label in self._selected_axes(param_list)
        }

    def get_status(self, param_list=None):
        """Get on-target states of selected axes.

        :param list param_list: Optional axis labels. All configured axes are
            returned when omitted.
        :return: On-target states indexed by axis label.
        :rtype: dict
        """
        return {
            axis_label: self._axes[axis_label].status
            for axis_label in self._selected_axes(param_list)
        }

    def calibrate(self, param_list=None):
        """Calibrate selected dummy axes by setting their positions to zero.

        :param list param_list: Optional axis labels. All configured axes are
            calibrated when omitted.
        :return: ``0`` if at least one axis was calibrated, otherwise ``-1``.
        :rtype: int
        """
        selected_axes = self._selected_axes(param_list)
        for axis_label in selected_axes:
            self._axes[axis_label].pos = 0.0
            self._axes[axis_label].status = True
        return 0 if selected_axes else -1

    def get_velocity(self, param_list=None):
        """Get current velocities of selected axes.

        :param list param_list: Optional axis labels. All configured axes are
            returned when omitted.
        :return: Velocities in micrometres per second, indexed by axis label.
        :rtype: dict
        """
        return {
            axis_label: self._axes[axis_label].vel
            for axis_label in self._selected_axes(param_list)
        }

    def set_velocity(self, param_dict):
        """Set velocities of selected axes.

        :param dict param_dict: Velocities in micrometres per second, indexed by
            axis label.
        :return: ``0`` if at least one velocity was set, otherwise ``-1``.
        :rtype: int
        """
        changed = False
        constraints = self.get_constraints()

        for axis_label, target_velocity in param_dict.items():
            if axis_label not in self._axes:
                self.log.warning(f'Specified axis not available: {axis_label}')
                continue

            axis_constraints = constraints[axis_label]
            if not axis_constraints['vel_min'] <= target_velocity <= axis_constraints['vel_max']:
                self.log.warning(
                    f'Cannot set velocity of axis {axis_label} to {target_velocity}: value is outside '
                    f'[{axis_constraints["vel_min"]}, {axis_constraints["vel_max"]}].'
                )
                continue

            self._axes[axis_label].vel = target_velocity
            changed = True

        return 0 if changed else -1

    def wait_for_idle(self):
        """Wait until the dummy stage is idle.

        Dummy movements finish synchronously, therefore this method returns
        immediately.

        :return: ``True`` because the dummy stage is idle after each command.
        :rtype: bool
        """
        return True

    # ------------------------------------------------------------------------------------------------------------------
    # Helper functions
    # ------------------------------------------------------------------------------------------------------------------

    def _selected_axes(self, param_list=None):
        """Return configured axes selected by an optional axis list."""
        if not param_list:
            return list(self.axis_list)

        selected_axes = []
        for axis_label in param_list:
            if axis_label in self._axes:
                selected_axes.append(axis_label)
            else:
                self.log.warning(f'Specified axis not available: {axis_label}')
        return selected_axes

    def _make_wait_after_movement(self):
        """Wait for the configured simulated movement delay."""
        if self._wait_after_movement > 0:
            time.sleep(self._wait_after_movement)
