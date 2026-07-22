# -*- coding: utf-8 -*-
"""
Author: F.Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2020-10-26 -> translated into qudi-core-HiM on 2026-04-30
This file contains a class for the ASI MS2000 translation stage.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

import numpy as np
import serial
from time import sleep, time
import re

from qudi.core.configoption import ConfigOption
from qudi.interface.multi_axis_stage_interface import MultiAxisStageInterface
# from interface.brightfield_interface import BrightfieldInterface


# ======================================================================================================================
# Hardware class
# ======================================================================================================================

class MS2000(MultiAxisStageInterface):
    """ Class representing the ASI MS 2000 xy or xyz translation stage.

  ms2000:
    module.Class: 'multi_axis_translation_stage.MS2000_ASI.MS2000'
    options:
        com_port: 'COM6'
        baud_rate: '9600' #'115200'
        first_axis_label: 'x'
        second_axis_label: 'y'
        third_axis_label: 'z'
        delay_after_move: 0.5
        LED connected: True
    """
    # config options
    _com_port = ConfigOption("com_port", missing="error")
    _baud_rate = ConfigOption("baud_rate", 9600, missing="warn")

    # axis definition: the default case is intended for 2 axes' stage, for 3 axes specify in config
    _first_axis_property = ConfigOption("first_axis_property", missing="error")
    _second_axis_property = ConfigOption("second_axis_property", missing="error")
    _third_axis_property = ConfigOption("third_axis_property", None, missing="warn")

    # for some model, ASI also provides a LED control
    _has_led = ConfigOption("LED connected", False, missing="warn")
    _led_mode = "Internal"

    # attributes
    _conversion_factor = 10.0  # user will send positions in um, stage uses 0.1 um
    _velocity_conversion_factor = 1000.0  # interface uses um/s, stage uses mm/s
    _timeout = 30
    axis_list = None
    max_velocity_list = None
    _serial_connection = None
    _first_axis_label = None
    _first_axis_max_velocity = None
    _second_axis_label = None
    _second_axis_max_velocity = None
    _third_axis_label = None
    _third_axis_max_velocity = None

    def on_activate(self):
        """ Initialization: opening serial port and setting internal attributes.
        """
        try:
            self._serial_connection = serial.Serial(
                self._com_port, baudrate=self._baud_rate, bytesize=8, parity="N", stopbits=1, xonxoff=True
            )
            # parsing axis properties
            self._first_axis_label = self._first_axis_property['label']
            self._first_axis_max_velocity = self._first_axis_property['max_velocity']
            self._second_axis_label = self._second_axis_property['label']
            self._second_axis_max_velocity = self._second_axis_property['max_velocity']
            if self._third_axis_property is not None:
                self._third_axis_label = self._third_axis_property['label']
                self._third_axis_max_velocity = self._third_axis_property['max_velocity']

            # create a list as iterator for methods that need a specified axis to apply to
            axis_list = [self._first_axis_label, self._second_axis_label, self._third_axis_label]
            max_velocity_list = [self._first_axis_max_velocity, self._second_axis_max_velocity, self._third_axis_max_velocity]
            self.axis_list = []
            self.max_velocity_list = []
            for axis, max_vel in zip(axis_list, max_velocity_list):
                if isinstance(axis, str):
                    self.axis_list.append(axis)
                    self.max_velocity_list.append(max_vel)

            # if the z axis is available, define the default speed for this axis
            if self._third_axis_label:
                self.set_velocity({self._third_axis_label: 1900.0})

            # if the stage is also controlling the bright-field, initiate the mode to "Internal"
            if self._has_led:
                self.led_mode('Internal')

        except Exception as error:
            self.log.error(f'ASI MS2000 initialization failed: {error}')
            self.log.error('ASI MS2000 automated stage not connected. Check if the device is switched on.')
            raise

    def on_deactivate(self):
        """ Close serial port when deactivating the module.
        """
        if self._serial_connection is None:
            return

        if self._serial_connection.is_open:
            self._serial_connection.close()

        # safety check - to explore when problem with stage arises again
        t0 = time()
        while self._serial_connection.is_open:
            sleep(0.5)
            if time() - t0 > 5.0:
                self.log.warning('ASI MS2000 serial port did not close within 5 seconds.')
                break

    # ----------------------------------------------------------------------------------------------------------------------
    # Motor interface functions
    # ----------------------------------------------------------------------------------------------------------------------

    @property
    def get_constraints(self):
        """ Retrieve the hardware constraints from the motor device. ASI Stage has no fixed pos_min and pos_max due to
        variable home position.
        @return dict constraints
        """
        constraints = {}

        for axis_label, max_velocity in zip(self.axis_list, self.max_velocity_list):
            constraints[axis_label] = {
                'label': axis_label,
                'type': 'linear',
                'unit': 'um',
                'velocity_unit': 'um/s',
                'ramp': None,
                'pos_min': None,
                'pos_max': None,
                'pos_step': None,
                'max_step': None,
                'vel_min': 0.0,
                'vel_max': max_velocity,
                'vel_step': None,
                'acc_min': None,
                'acc_max': None,
                'acc_step': None,
            }

        return constraints

    def move_abs(self, param_dict):
        """ Moves stage to absolute position (absolute movement).

        @param dict param_dict: Dictionary with axis name and target position (in um units) as key - value pairs
        @return bool: error code (True: ok, False: error)
        """
        moved = False
        try:
            for axis_label, target_position in param_dict.items():
                if axis_label not in self.axis_list:
                    self.log.warning(f'Axis {axis_label} is not configured.')
                    continue

                controller_position = np.round(
                    target_position * self._position_conversion_factor,
                    decimals=4,
                )
                cmd = f'M {axis_label}={controller_position}\r'
                moved = self.write(cmd) or moved

        except Exception as error:
            self.log.error(f'Absolute movement of ASI MS2000 stage failed: {error}')

        return moved

    def move_rel(self, param_dict):
        """ Moves stage in a given direction (relative movement).

        @param dict param_dict: Dictionary with axis name and step (in um units) as key - value pairs
        @return bool: error code (True: ok, False: not ok)
        """
        moved = False
        try:
            for axis_label, movement in param_dict.items():
                if axis_label not in self.axis_list:
                    self.log.warning(f'Axis {axis_label} is not configured.')
                    continue

                controller_step = np.round(
                    movement * self._position_conversion_factor,
                    decimals=4,
                )
                cmd = f'R {axis_label}={controller_step}\r'
                moved = self.write(cmd) or moved

        except Exception as error:
            self.log.error(f'Relative movement of ASI MS2000 stage failed: {error}')

        return moved

    def abort(self):
        """ Stops movement of the stage.
        The ASI controller handles all configured axes as one coordinated
        device, so a single abort command stops the stage.

        :return bool: error code (True: ok, False: error)
        """
        cmd = "\\r"
        return self.write(cmd)

    def get_pos(self, param_list=None):
        """ Gets current position of the stage.

        :param list param_list: optional, if a specific position of an axis
        is desired, then the labels of the needed axis should be passed in the param_list.
        If nothing is passed, then from each axis the position is asked.

        :return dict pos: Dictionary with axis name and current position of the translation stage
        """
        pos = {}
        for axis_label in self._selected_axes(param_list):
            cmd = f'W {axis_label}\r'
            controller_position = self._parse_numeric_response(self.query(cmd))
            pos[axis_label] = controller_position / self._position_conversion_factor
        return pos

    def get_status(self, param_list=None):
        """ Queries if any motors are still busy moving following a serial command.

        :param list param_list: optional, if a specific status of an axis
        is desired, then the labels of the needed axis should be passed in the param_list.
        If nothing is passed, then from each axis the status is asked.
        Not used here because all axes are treated as a unity for ASI stage.

        :return: ``True`` for idle/on-target axes and ``False`` while busy.
        """
        selected_axes = self._selected_axes(param_list)
        status_answer = self.query('/ \r').strip()

        if status_answer == 'N':
            on_target = True
        elif status_answer == 'B':
            on_target = False
        else:
            self.log.warning(f'Unexpected ASI MS2000 status response: {status_answer!r}')
            on_target = False

        return {axis_label: on_target for axis_label in selected_axes}

    def calibrate(self, param_list=None):
        # to be defined what should be done here: ALIGN, ZEROING, HOMING ?
        """ Performs self-calibration of the axis motor drive circuit.
        The ASI ``AA`` command aligns the motor drive circuit; it does not home
        an axis or redefine its origin.

        :param list param_list: optional, if a specific status of an axis
        is desired, then the labels of the needed axis should be passed in the param_list.
        If nothing is passed, then all axis will be calibrated.

        :return: ``0`` if at least one alignment command was accepted, otherwise ``-1``.
        """
        calibrated = False
        for axis_label in self._selected_axes(param_list):
            cmd = f'AA {axis_label}\r'
            calibrated = self.write(cmd) or calibrated
        return 0 if calibrated else -1

    def get_velocity(self, param_list=None):
        """ Gets the current velocity of the translation stage for the specified axes or all axes.

        :param list param_list: list param_list: optional, if a specific status of an axis
        is desired, then the labels of the needed axis should be passed in the param_list.
        If nothing is passed, then the velocity of all axis will be queried.

        :return dict: Dictionary with axis name and current velocity of the specified axis.
        """
        velocity = {}
        for axis_label in self._selected_axes(param_list):
            cmd = f'S {axis_label}?\r'
            controller_velocity = self._parse_numeric_response(self.query(cmd))
            velocity[axis_label] = controller_velocity * self._velocity_conversion_factor
        return velocity

    def set_velocity(self, param_dict):
        """ Sets the velocity at which the stage moves.
        Velocity is set in millimeters per second. Maximum speed is 7.5 mm/s for standard 6.5 mm pitch leadscrews.
        Interface values are expressed in micrometres per second and converted to the controller's millimetres-per-second unit.

        @param (dict) param_dict: Dictionary with axis name and target velocity in mm/s
        @return (int) error code (0:OK, -1:error)
        """
        changed = False
        constraints = self.get_constraints()

        try:
            for axis_label, target_velocity in param_dict.items():
                if axis_label not in self.axis_list:
                    self.log.warning(f'Specified axis {axis_label} is not available.')
                    continue

                axis_constraints = constraints[axis_label]
                if not axis_constraints['vel_min'] <= target_velocity <= axis_constraints['vel_max']:
                    self.log.warning(
                        f'Cannot set velocity of axis {axis_label} to {target_velocity}: value is outside '
                        f'[{axis_constraints["vel_min"]}, {axis_constraints["vel_max"]}].'
                    )
                    continue

                controller_velocity = target_velocity / self._velocity_conversion_factor
                cmd = f'S {axis_label}={controller_velocity}\r'
                changed = self.write(cmd) or changed

        except Exception as error:
            self.log.error(f'Could not set ASI MS2000 velocity: {error}')

        return 0 if changed else -1

    def wait_for_idle(self):
        """ Wait until a motorized stage is in idle state.
        Checks every 1 s until timeout if a motor is running from a serial command 'B' or not 'N'
        @return ``True`` when the stage becomes idle, otherwise ``False``.
        """
        t0 = time()

        while True:
            status = self.get_status()
            if status and all(status.values()):
                return True

            waiting_time = time() - t0
            if waiting_time >= self._timeout:
                self.log.error(
                    f'ASI MS2000 stage timeout occurred after {waiting_time:.1f} seconds.'
                )
                return False

            sleep(0.5)

    # # ----------------------------------------------------------------------------------------------------------------------
    # # Additional custom functions not on the interface
    # # ----------------------------------------------------------------------------------------------------------------------
    #
    # def homing_xy(self):
    #     """ Moves the stage to homeposition on x and y axes.
    #     Motor stops when hardware or firmware limit switch is encountered.
    #
    #     :return: error code (ok: 0)
    #     """
    #     cmd = "! X Y \r"
    #     self.write(cmd)
    #     return 0
    #
    # def set_to_zero(self):
    #     """ Sets the current position as the origin.
    #
    #     :return: error code (ok: 0)
    #     """
    #     cmd = "Z \r"
    #     self.write(cmd)
    #     return 0

    # ----------------------------------------------------------------------------------------------------------------------
    # Bright-field interface functions
    # ----------------------------------------------------------------------------------------------------------------------

    def led_mode(self, mode):
        """Define the operating mode of the optional bright-field LED.

        :param str mode: Either ``'Internal'`` or ``'Triggered'``.
        :return: ``True`` if the requested command was accepted. ``False`` otherwise or if no LED is configured.
        """
        if not self._has_led:
            return False

        if self._led_mode == 'Internal':
            self.led_control(0)

        if mode == 'Internal':
            success = self.write('TTL X=0 Y=9 \r')
            success = self.led_control(0) and success
        elif mode == 'Triggered':
            success = self.write('TTL X=10 Y=0 \r')
        else:
            self.log.warning(f'Unsupported LED mode: {mode}')
            return False

        if success:
            self._led_mode = mode
        return success

    def led_control(self, intens):
        """Set the optional LED intensity between 0 and 99 percent.

        :param int intens: Percentage of maximum LED intensity.
        :return: ``True`` if the command was accepted or no LED is configured.
        """
        if not self._has_led:
            return True

        value = int(min(max(intens, 0), 99))
        return self.write(f'LED X={value}? \r')

    # ----------------------------------------------------------------------------------------------------------------------
    # Helper functions
    # ----------------------------------------------------------------------------------------------------------------------

    def query(self, command):
        """ Clears the input buffer and queries an utf-8 encoded command.

        :param: string command: message to send to the serial port, typically in the format
        'COMMANDSHORTCUT [AXIS=value]\r'
        :return: string answer: formatted and decoded response from serial port
        """
        self._serial_connection.reset_input_buffer()
        self._serial_connection.reset_output_buffer()
        self._serial_connection.write(command.encode())
        return self._serial_connection.readline().decode().strip()

    def write(self, command):
        """ Clears the input buffer and writes an utf-8 encoded command to the serial port .

        :param string command: message to send to the serial port, typically in the format
        'COMMANDSHORTCUT [AXIS=value]\r'
        :return: ``True`` if the controller acknowledged the command.
        """
        for _ in range(10):
            self._serial_connection.reset_input_buffer()
            self._serial_connection.reset_output_buffer()
            self._serial_connection.write(command.encode())
            answer = self._serial_connection.readline().decode().strip()

            if re.match(r':A', answer):
                return True

            sleep(0.1)

        self.log.warning(f'The ASI stage was unable to execute command: {command!r}')
        return False

    def _selected_axes(self, param_list=None):
        """Return configured axes selected by an optional axis list."""
        if not param_list:
            return list(self.axis_list)

        selected_axes = []
        for axis_label in param_list:
            if axis_label in self.axis_list:
                selected_axes.append(axis_label)
            else:
                self.log.warning(f'Specified axis not available: {axis_label}')
        return selected_axes

    @staticmethod
    def _parse_numeric_response(answer):
        """Extract a floating-point value from an ASI controller response."""
        stripped_answer = answer.strip()
        if '=' in stripped_answer:
            value = stripped_answer.rsplit('=', 1)[1]
        elif stripped_answer.startswith(':A'):
            value = stripped_answer[2:]
        else:
            value = stripped_answer
        return float(value.strip())
