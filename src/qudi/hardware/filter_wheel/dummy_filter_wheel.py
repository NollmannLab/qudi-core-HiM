# -*- coding: utf-8 -*-

"""
Author: F. Barho. Adapted to qudi-core by JB Fiche with chatGPT.
Created 2020-07-20 -> Reformatted 2026-08-01.

This module contains the dummy implementation of a motorized filterwheel.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

import numpy as np

from qudi.core.configoption import ConfigOption
from qudi.interface.filter_wheel_interface import FilterWheelInterface


class DummyFilterWheel(FilterWheelInterface):
    """ Hardware class representing a dummy filterwheel.

    Example config for copy-paste:

    dummy_filter_wheel:
      module.Class: 'filter_wheel.dummy_filter_wheel.DummyFilterWheel'
      options:
        num_filters: 6
        filter_definitions:
          - position: 1
            name: 700 +/- 37 nm
            allowed_wavelengths_nm:
              - 405
              - 488
              - 561
              - 640

          - position: 2
            name: 600 +/- 25 nm
            allowed_wavelengths_nm:
              - 405
              - 488
              - 561
              - 640

          - position: 3
            name: 488 - 491 / 561 nm
            allowed_wavelengths_nm:
              - 405
              - 488
              - 561
              - 640

          - position: 4
            name: 525 +/- 22.5 nm
            allowed_wavelengths_nm:
              - 405
              - 488
              - 561
              - 640

          - position: 5
            name: 617 +/- 36 nm
            allowed_wavelengths_nm:
              - 405
              - 488
              - 561

          - position: 6
            name: 460 +/- 25 nm
            allowed_wavelengths_nm:
              - 405
              - 561
              - 640

    # please specify for all elements corresponding information in the same order.
    # allowed lasers:
    # entries corresponding to [laser1_allowed, laser2_allowed, laser3_allowed, laser4_allowed, ..]
    # see also the config for the daq ao output to associate a laser number to a wavelength
    """
    # config options
    _filter_definitions = ConfigOption('filter_definitions', missing='error')

    # attributes
    _filters_by_position = {}

    position = np.random.randint(1, 7)  # generate an arbitrary start value from 1 to 6

    def on_activate(self):
        """Activate the module and validate & store the configured filter definitions. The dictionary
        is structured as follows:
        _filters_by_position [{'position': 1, 'name': '700 +/- 37 nm', 'allowed_wavelengths_nm': [405, 488, 561, 640]},
                              {'position': 2, 'name': '600 +/- 25 nm', 'allowed_wavelengths_nm': [405, 488, 561, 640]},
                              {'position': 3, 'name': '488 - 491 / 561 nm', 'allowed_wavelengths_nm': [405, 488, 561, 640]},
                              {'position': 4, 'name': '525 +/- 22.5 nm', 'allowed_wavelengths_nm': [405, 488, 561, 640]},
                              {'position': 5, 'name': '617 +/- 36 nm', 'allowed_wavelengths_nm': [405, 488, 561]},
                              {'position': 6, 'name': '460 +/- 25 nm', 'allowed_wavelengths_nm': [405, 561, 640]}]
        """

        for definition in self._filter_definitions:
            position = int(definition["position"])

            if position in self._filters_by_position:
                self.log.error(f"Filter position {position} is defined more than once.")

            self._filters_by_position[position] = {
                "name": str(definition["name"]),
                "allowed_wavelengths_nm": tuple(
                    int(wavelength)
                    for wavelength
                    in definition["allowed_wavelengths_nm"]
                ),
            }

    def on_deactivate(self):
        """ Module deactivation method. """
        pass

# ----------------------------------------------------------------------------------------------------------------------
# Filterwheel interface functions
# ----------------------------------------------------------------------------------------------------------------------

    def get_position(self):
        """ Get the current position.
         :return int position: number of the filterwheel position that is currently set """
        return self.position

    def set_position(self, target_position):
        """ Set the position to a given value.

        :param: int target_position: position number
        :return: int error code: ok = 0
        """
        if target_position in self._filters_by_position:
            self.position = target_position
            err = 0
        else:
            self.log.error(f'Can not go to filter {target_position}. No filter was defined for the selected position')
            err = -1
        return err

    def get_filter_dict(self):
        """ Return the filter definition as a dictionary.
        {
            1: {'name': '700 +/- 37 nm', 'allowed_wavelengths_nm': (405, 488, 561, 640)},
            2: {'name': '600 +/- 25 nm', 'allowed_wavelengths_nm': (405, 488, 561, 640)},
            3: {'name': '488 - 491 / 561 nm', 'allowed_wavelengths_nm': (405, 488, 561, 640)},
            4: {'name': '525 +/- 22.5 nm', 'allowed_wavelengths_nm': (405, 488, 561, 640)},
            5: {'name': '617 +/- 36 nm', 'allowed_wavelengths_nm': (405, 488, 561)},
            6: {'name': '460 +/- 25 nm', 'allowed_wavelengths_nm': (405, 561, 640)}
       }
        """
        return self._filters_by_position