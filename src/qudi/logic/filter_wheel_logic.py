# -*- coding: utf-8 -*-
"""
Author: F. Barho. Adapted to qudi-core by JB Fiche
Created 2020-11-17 -> Reformatted 2026-08-01.

This module contains the logic to control a motorized filter wheel and provides a security on the laser selection
depending on the mounted filter.

An extension to Qudi.

@author: F. Barho

Created on Tue Nov 17 2020
-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from qudi.core.module import LogicBase
from qudi.core.connector import Connector
from qtpy import QtCore

class FilterWheelLogic(LogicBase):
    """
    Class for the control of a motorized filterwheel.
    """
    # declare connectors
    wheel = Connector(name='filter_wheel', interface='FilterWheelInterface')
    laser_logic = Connector(name='laser_logic', interface='LaserControlLogic')

    # signals
    sigNewFilterSetting = QtCore.Signal(int)  # if position changed using the iPython console, use this signal to update GUI
    sigDeactivateLaserControl = QtCore.Signal()
    sigDisableFilterActions = QtCore.Signal()
    sigEnableFilterActions = QtCore.Signal()

    # attributes
    _wheel = None
    _laser_control = None
    filter_dict = {}

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        self._wheel = self.wheel()
        self._laser_logic = self.laser_logic()
        self.filter_dict = self.get_filter_dict()

    def on_deactivate(self):
        """ Perform required deactivation. """
        self._wheel = None
        self._laser_control = None

    # ----------------------------------------------------------------------------------------------------------------------
    # Getter and setter methods
    # ----------------------------------------------------------------------------------------------------------------------

    def set_position(self, position):
        """ Checks if the filterwheel can move (only if lasers are off), resets the intensity values of all lasers to 0
        to avoid having a laser line which may be forbidden with the newly set filter and changes position if possible.

        :param: int position: new filter wheel position

        :return: None
        """
        if not self._laser_logic.laser_enabled:  # do not allow changing filter while lasers are on
            # Combobox on gui is also disabled but this is an additional security to prevent setting filter via iPython console
            self._laser_logic.reset_laser_intensities()  # set all values to 0 before changing the filter
            err = self._wheel.set_position(position)
            if err == 0:
                self.log.info('Set filter {}'.format(position))
                self.sigNewFilterSetting.emit(position)
        else:
            self.log.warning('Laser is on. Can not change filter')

    def get_position(self):
        """ Get the current position from the hardware.
        :return: int pos: current filter position
        """
        pos = self._wheel.get_position()
        return pos

    def get_filter_dict(self):
        """ Retrieves a dictionary specified in the configuration of the connected filterwheel with the following entries:
            {
                1: {'name': '700 +/- 37 nm', 'allowed_wavelengths_nm': (405, 488, 561, 640)},
                2: {'name': '600 +/- 25 nm', 'allowed_wavelengths_nm': (405, 488, 561, 640)},
                3: {'name': '488 - 491 / 561 nm', 'allowed_wavelengths_nm': (405, 488, 561, 640)},
                4: {'name': '525 +/- 22.5 nm', 'allowed_wavelengths_nm': (405, 488, 561, 640)},
                5: {'name': '617 +/- 36 nm', 'allowed_wavelengths_nm': (405, 488, 561)},
                6: {'name': '460 +/- 25 nm', 'allowed_wavelengths_nm': (405, 561, 640)}
            }
        :return: dict filter dict
        """
        filter_dict = self._wheel.get_filter_dict()
        return filter_dict

    # ----------------------------------------------------------------------------------------------------------------------
    # Methods to handle the user interface state
    # ----------------------------------------------------------------------------------------------------------------------

    def disable_filter_actions(self):
        """ This method provides a security to avoid changing filter from GUI, for example during Tasks. """
        self.sigDisableFilterActions.emit()

    def enable_filter_actions(self):
        """ This method resets filter selection from GUI to callable state, for example after Tasks. """
        self.sigEnableFilterActions.emit()