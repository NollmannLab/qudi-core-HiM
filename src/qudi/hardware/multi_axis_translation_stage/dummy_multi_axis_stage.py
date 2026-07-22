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
from qudi.core.module import Base
from qudi.core.configoption import ConfigOption
from qudi.interface.multi_axis_stage_interface import RoiStageInterface
import time


class DummySingleAxisStage:
    """ Generic dummy motor representing one axis. """
    def __init__(self, label):
        self.label = label


class DummyXYStage(RoiStageInterface):

    _x_min = ConfigOption(name='x_min', default=0.0)
    _x_max = ConfigOption(name='x_max', default=100000.0)
    _y_min = ConfigOption(name='y_min', default=0.0)
    _y_max = ConfigOption(name='y_max', default=100000.0)
    _z_min = ConfigOption(name='z_min', default=0.0)
    _z_max = ConfigOption(name='z_max', default=1000.0)
    _wait_after_movement = ConfigOption(name='delay_after_move', default=1000.0) # in seconds
    _first_axis_label = ConfigOption(name='first_axis_label', missing='error')
    _second_axis_label = ConfigOption(name='second_axis_label', missing='error')
    _third_axis_label = ConfigOption(name='third_axis_label', missing='error')
    _position: dict = {}
    _x_axis: object = None
    _y_axis: object = None
    _z_axis: object = None
    _phi_axis: object = None

    def on_activate(self):
        self._position = {'x': 0.0, 'y': 0.0, 'z': 0.0}
        self._x_axis = DummySingleAxisStage(self._first_axis_label)
        self._y_axis = DummySingleAxisStage(self._second_axis_label)
        self._z_axis = DummySingleAxisStage(self._third_axis_label)
        self._phi_axis = DummySingleAxisStage('phi')

        self._x_axis.pos = 0.0
        self._y_axis.pos = 0.0
        self._z_axis.pos = 0.0
        self._phi_axis.pos = 0.0

        self._x_axis.vel = 1.0
        self._y_axis.vel = 1.0
        self._z_axis.vel = 1.0
        self._phi_axis.vel = 1.0

        self._x_axis.status = True   # 0
        self._y_axis.status = True   # 0
        self._z_axis.status = True   # 0
        self._phi_axis.status = 0

    def on_deactivate(self):
        pass

    def get_constraints(self):
        """ Retrieve the hardware constraints from the motor device.

        @return dict: dict with constraints for the magnet hardware. These constraints will be passed via the logic to
        the GUI so that proper display elements with boundary conditions could be made.

        Provides all the constraints for each axis of a motorized stage (like total travel distance, velocity, ...).
        Each axis has its own dictionary, where the label is used as the identifier throughout the whole module. The
        dictionaries for each axis are again grouped together in a constraint dictionary in the form
        {'<label_axis0>': axis0 } where axis0 is again a dict with the possible values defined below. The possible keys
        in the constraint are defined here in the interface file. If the hardware does not support the values for the
        constraints, then insert just None. If you are not sure about the meaning, look in other hardware files to get
         an impression.
        """
        constraints = {}

        axis0 = {'label': self._first_axis_label,
                 'unit': 'm',
                 'ramp': ['Sinus', 'Linear'],
                 'pos_min': -1000,
                 'pos_max': 1000,
                 'pos_step': 0.001,
                 'max_step': 1,  # added for compatibility with focus_logic
                 'vel_min': 0,
                 'vel_max': 100,
                 'vel_step': 0.01,
                 'acc_min': 0.1,
                 'acc_max': 0.0,
                 'acc_step': 0.0}

        axis1 = {'label': self._second_axis_label,
                 'unit': 'm',
                 'ramp': ['Sinus', 'Linear'],
                 'pos_min': -1000,
                 'pos_max': 1000,
                 'pos_step': 0.001,
                 'max_step': 1,  # added for compatibility with focus_logic
                 'vel_min': 0,
                 'vel_max': 100,
                 'vel_step': 0.01,
                 'acc_min': 0.1,
                 'acc_max': 0.0,
                 'acc_step': 0.0}

        axis2 = {'label': self._third_axis_label,
                 'unit': 'm',
                 'ramp': ['Sinus', 'Linear'],
                 'pos_min': -1000,
                 'pos_max': 1000,
                 'pos_step': 0.001,
                 'max_step': 1,  # added for compatibility with focus_logic
                 'vel_min': 0,
                 'vel_max': 100,
                 'vel_step': 0.01,
                 'acc_min': 0.1,
                 'acc_max': 0.0,
                 'acc_step': 0.0}

        # assign the parameter container for x to a name which will identify it
        constraints[axis0['label']] = axis0
        constraints[axis1['label']] = axis1
        constraints[axis2['label']] = axis2
        return constraints

    def move_rel(self, param_dict):
        """ Moves stage in given direction (relative movement)

        @param dict param_dict: dictionary, which passes all the relevant parameters, which should be changed. With
        get_constraints() you can obtain all possible parameters of that stage. According to this parameter set you have
        to pass a dictionary with keys that are called like the parameters from get_constraints() and assign a SI value
        to that. For a movement in x the dict should e.g. have the form: dict = { 'x' : 23 } where the label 'x'
        corresponds to the chosen axis label.

        todo : A smart idea would be to ask the position after the movement.
        """
        curr_pos_dict = self.get_pos()
        constraints = self.get_constraints()

        if param_dict.get(self._first_axis_label) is not None:
            move_x = param_dict[self._first_axis_label]
            curr_pos_x = curr_pos_dict[self._first_axis_label]

            if (curr_pos_x + move_x > constraints[self._first_axis_label]['pos_max']) or \
                    (curr_pos_x + move_x < constraints[self._first_axis_label]['pos_min']):

                self.log.warning(f'Cannot make further movement of the axis {self._first_axis_label} '
                                 f'with the step {move_x}, since the border '
                                 f'[{constraints[self._first_axis_label]["pos_min"]},'
                                 f'{constraints[self._first_axis_label]["pos_max"]}] '
                                 f'was reached! Ignore command!')
            else:
                self._make_wait_after_movement()
                self._x_axis.pos = self._x_axis.pos + move_x

        if param_dict.get(self._second_axis_label) is not None:
            move_y = param_dict[self._second_axis_label]
            curr_pos_y = curr_pos_dict[self._second_axis_label]

            if (curr_pos_y + move_y > constraints[self._second_axis_label]['pos_max']) or \
                    (curr_pos_y + move_y < constraints[self._second_axis_label]['pos_min']):

                self.log.warning('Cannot make further movement of the axis '
                                 '"{0}" with the step {1}, since the border [{2},{3}] '
                                 'was reached! Ignore command!'.format(self._second_axis_label, move_y,
                                                                       constraints[self._second_axis_label]['pos_min'],
                                                                       constraints[self._second_axis_label]['pos_max']))
            else:
                self._make_wait_after_movement()
                self._y_axis.pos = self._y_axis.pos + move_y

        if param_dict.get(self._third_axis_label) is not None:
            move_z = param_dict[self._third_axis_label]
            curr_pos_z = curr_pos_dict[self._third_axis_label]

            if (curr_pos_z + move_z > constraints[self._third_axis_label]['pos_max']) or \
                    (curr_pos_z + move_z < constraints[self._third_axis_label]['pos_min']):

                self.log.warning('Cannot make further movement of the axis '
                                 '"{0}" with the step {1}, since the border [{2},{3}] '
                                 'was reached! Ignore command!'.format(self._third_axis_label, move_z,
                                                                       constraints[self._third_axis_label]['pos_min'],
                                                                       constraints[self._third_axis_label]['pos_max']))
            else:
                self._make_wait_after_movement()
                self._z_axis.pos = self._z_axis.pos + move_z

        if param_dict.get(self._phi_axis.label) is not None:
            move_phi = param_dict[self._phi_axis.label]
            curr_pos_phi = curr_pos_dict[self._phi_axis.label]

            if (curr_pos_phi + move_phi > constraints[self._phi_axis.label]['pos_max']) or \
                    (curr_pos_phi + move_phi < constraints[self._phi_axis.label]['pos_min']):

                self.log.warning('Cannot make further movement of the axis '
                                 '"{0}" with the step {1}, since the border [{2},{3}] '
                                 'was reached! Ignore command!'.format(
                    self._phi_axis.label, move_phi,
                    constraints[self._phi_axis.label]['pos_min'],
                    constraints[self._phi_axis.label]['pos_max']))
            else:
                self._make_wait_after_movement()
                self._phi_axis.pos = self._phi_axis.pos + move_phi

    def move_abs(self, param_dict):
        """ Moves stage to absolute position (absolute movement)

        @param dict param_dict: dictionary, which passes all the relevant
                                parameters, which should be changed. Usage:
                                 {'axis_label': <a-value>}.
                                 'axis_label' must correspond to a label given
                                 to one of the axis.
        A smart idea would be to ask the position after the movement.
        """
        constraints = self.get_constraints()

        if param_dict.get(self._first_axis_label) is not None:
            desired_pos = param_dict[self._first_axis_label]
            constr = constraints[self._first_axis_label]

            if not (constr['pos_min'] <= desired_pos <= constr['pos_max']):
                self.log.warning('Cannot make absolute movement of the axis '
                                 '"{0}" to possition {1}, since it exceeds the limits '
                                 '[{2},{3}] ! Command is ignored!'.format(
                    self._first_axis_label, desired_pos,
                    constr['pos_min'],
                    constr['pos_max']))
            else:
                self._make_wait_after_movement()
                self._x_axis.pos = desired_pos

        if param_dict.get(self._second_axis_label) is not None:
            desired_pos = param_dict[self._second_axis_label]
            constr = constraints[self._second_axis_label]

            if not (constr['pos_min'] <= desired_pos <= constr['pos_max']):
                self.log.warning('Cannot make absolute movement of the axis '
                                 '"{0}" to possition {1}, since it exceeds the limits '
                                 '[{2},{3}] ! Command is ignored!'.format(
                    self._second_axis_label, desired_pos,
                    constr['pos_min'],
                    constr['pos_max']))
            else:
                self._make_wait_after_movement()
                self._y_axis.pos = desired_pos

        if param_dict.get(self._third_axis_label) is not None:
            desired_pos = param_dict[self._third_axis_label]
            constr = constraints[self._third_axis_label]

            if not (constr['pos_min'] <= desired_pos <= constr['pos_max']):
                self.log.warning('Cannot make absolute movement of the axis '
                                 '"{0}" to possition {1}, since it exceeds the limits '
                                 '[{2},{3}] ! Command is ignored!'.format(
                    self._third_axis_label, desired_pos,
                    constr['pos_min'],
                    constr['pos_max']))
            else:
                self._make_wait_after_movement()
                self._z_axis.pos = desired_pos

        if param_dict.get(self._phi_axis.label) is not None:
            desired_pos = param_dict[self._phi_axis.label]
            constr = constraints[self._phi_axis.label]

            if not (constr['pos_min'] <= desired_pos <= constr['pos_max']):
                self.log.warning('Cannot make absolute movement of the axis '
                                 '"{0}" to possition {1}, since it exceeds the limits '
                                 '[{2},{3}] ! Command is ignored!'.format(
                    self._phi_axis.label, desired_pos,
                    constr['pos_min'],
                    constr['pos_max']))
            else:
                self._make_wait_after_movement()
                self._phi_axis.pos = desired_pos

    def abort(self):
        """Stops movement of the stage

        @return int: error code (0:OK, -1:error)
        """
        self.log.info('MotorDummy: Movement stopped!')
        return 0

    def get_pos(self, param_list=None):
        """ Gets current position of the stage arms

        @param list param_list: optional, if a specific position of an axis
                                is desired, then the labels of the needed
                                axis should be passed as the param_list.
                                If nothing is passed, then from each axis the
                                position is asked.

        @return dict: with keys being the axis labels and item the current
                      position.
        """
        pos = {}
        if param_list is not None:
            if self._first_axis_label in param_list:
                pos[self._first_axis_label] = self._x_axis.pos

            if self._second_axis_label in param_list:
                pos[self._second_axis_label] = self._y_axis.pos

            if self._third_axis_label in param_list:
                pos[self._third_axis_label] = self._z_axis.pos

            if self._phi_axis.label in param_list:
                pos[self._phi_axis.label] = self._phi_axis.pos

        else:
            pos[self._first_axis_label] = self._x_axis.pos
            pos[self._second_axis_label] = self._y_axis.pos
            pos[self._third_axis_label] = self._z_axis.pos
            pos[self._phi_axis.label] = self._phi_axis.pos

        return pos

    def get_status(self, param_list=None):
        """ Get the status of the position

        @param list param_list: optional, if a specific status of an axis
                                is desired, then the labels of the needed
                                axis should be passed in the param_list.
                                If nothing is passed, then from each axis the
                                status is asked.

        @return dict: with the axis label as key and the status number as item.
        """

        status = {}
        if param_list is not None:
            if self._first_axis_label in param_list:
                status[self._first_axis_label] = self._x_axis.status

            if self._second_axis_label in param_list:
                status[self._second_axis_label] = self._y_axis.status

            if self._third_axis_label in param_list:
                status[self._third_axis_label] = self._z_axis.status

            if self._phi_axis.label in param_list:
                status[self._phi_axis.label] = self._phi_axis.status

        else:
            status[self._first_axis_label] = self._x_axis.status
            status[self._second_axis_label] = self._y_axis.status
            status[self._third_axis_label] = self._z_axis.status
            status[self._phi_axis.label] = self._phi_axis.status

        return status

    def calibrate(self, param_list=None):
        """ Calibrates the stage.

        @param dict param_list: param_list: optional, if a specific calibration
                                of an axis is desired, then the labels of the
                                needed axis should be passed in the param_list.
                                If nothing is passed, then all connected axis
                                will be calibrated.

        @return int: error code (0:OK, -1:error)

        After calibration the stage moves to home position which will be the
        zero point for the passed axis. The calibration procedure will be
        different for each stage.
        """
        if param_list is not None:
            if self._first_axis_label in param_list:
                self._x_axis.pos = 0.0

            if self._second_axis_label in param_list:
                self._y_axis.pos = 0.0

            if self._third_axis_label in param_list:
                self._z_axis.pos = 0.0

            if self._phi_axis.label in param_list:
                self._phi_axis.pos = 0.0

        else:
            self._x_axis.pos = 0.0
            self._y_axis.pos = 0.0
            self._z_axis.pos = 0.0
            self._phi_axis.pos = 0.0

        return 0

    def get_velocity(self, param_list=None):
        """ Gets the current velocity for all connected axes.

        @param dict param_list: optional, if a specific velocity of an axis
                                is desired, then the labels of the needed
                                axis should be passed as the param_list.
                                If nothing is passed, then from each axis the
                                velocity is asked.

        @return dict : with the axis label as key and the velocity as item.
        """
        vel = {}
        if param_list is not None:
            if self._first_axis_label in param_list:
                vel[self._first_axis_label] = self._x_axis.vel
            if self._second_axis_label in param_list:
                vel[self._first_axis_label] = self._y_axis.vel
            if self._third_axis_label in param_list:
                vel[self._first_axis_label] = self._z_axis.vel
            if self._phi_axis.label in param_list:
                vel[self._phi_axis.label] = self._phi_axis.vel

        else:
            vel[self._first_axis_label] = self._x_axis.get_vel
            vel[self._second_axis_label] = self._y_axis.get_vel
            vel[self._third_axis_label] = self._z_axis.get_vel
            vel[self._phi_axis.label] = self._phi_axis.vel

        return vel

    def set_velocity(self, param_dict=None):
        """ Write new value for velocity.

        @param dict param_dict: dictionary, which passes all the relevant
                                parameters, which should be changed. Usage:
                                 {'axis_label': <the-velocity-value>}.
                                 'axis_label' must correspond to a label given
                                 to one of the axis.
        """
        constraints = self.get_constraints()

        if param_dict.get(self._first_axis_label) is not None:
            desired_vel = param_dict[self._first_axis_label]
            constr = constraints[self._first_axis_label]

            if not (constr['vel_min'] <= desired_vel <= constr['vel_max']):
                self.log.warning('Cannot make absolute movement of the axis '
                                 '"{0}" to possition {1}, since it exceeds the limits '
                                 '[{2},{3}] ! Command is ignored!'.format(
                    self._first_axis_label, desired_vel,
                    constr['vel_min'],
                    constr['vel_max']))
            else:
                self._x_axis.vel = desired_vel

        if param_dict.get(self._second_axis_label) is not None:
            desired_vel = param_dict[self._second_axis_label]
            constr = constraints[self._second_axis_label]

            if not (constr['vel_min'] <= desired_vel <= constr['vel_max']):
                self.log.warning('Cannot make absolute movement of the axis '
                                 '"{0}" to possition {1}, since it exceeds the limits '
                                 '[{2},{3}] ! Command is ignored!'.format(
                    self._second_axis_label, desired_vel,
                    constr['vel_min'],
                    constr['vel_max']))
            else:
                self._y_axis.vel = desired_vel

        if param_dict.get(self._third_axis_label) is not None:
            desired_vel = param_dict[self._third_axis_label]
            constr = constraints[self._third_axis_label]

            if not (constr['vel_min'] <= desired_vel <= constr['vel_max']):
                self.log.warning('Cannot make absolute movement of the axis '
                                 '"{0}" to possition {1}, since it exceeds the limits '
                                 '[{2},{3}] ! Command is ignored!'.format(
                    self._third_axis_label, desired_vel,
                    constr['pos_min'],
                    constr['pos_max']))
            else:
                self._z_axis.vel = desired_vel

        if param_dict.get(self._phi_axis.label) is not None:
            desired_vel = param_dict[self._phi_axis.label]
            constr = constraints[self._phi_axis.label]

            if not (constr['vel_min'] <= desired_vel <= constr['vel_max']):
                self.log.warning('Cannot make absolute movement of the axis '
                                 '"{0}" to possition {1}, since it exceeds the limits '
                                 '[{2},{3}] ! Command is ignored!'.format(
                    self._phi_axis.label, desired_vel,
                    constr['pos_min'],
                    constr['pos_max']))
            else:
                self._phi_axis.vel = desired_vel

    @staticmethod
    def wait_for_idle():
        time.sleep(0.1)

    def _make_wait_after_movement(self):
        """ Define a time which the dummy should wait after each movement. """
        time.sleep(self._wait_after_movement)