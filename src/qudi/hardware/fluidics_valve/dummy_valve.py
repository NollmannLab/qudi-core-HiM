# -*- coding: utf-8 -*-
"""
Author: JB Fiche - adapted for qudi-core-HiM
Created: 2026-07-16
This module contains a class representing a dummy valve.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from time import sleep, time

from qudi.core.configoption import ConfigOption
from qudi.interface.valve_positioner_interface import ValvePositionerInterface


class DummyValve(ValvePositionerInterface):
    """ In-memory dummy implementation of a modular valve positioner. The valve configuration options intentionally
     match HamiltonValve so that the hardware implementation can be exchanged without changing the logic or GUI modules.

    Example config :

  hamilton_valve:
    module.Class: 'fluidics_valve.hamilton_valve.HamiltonValve'
    options :
        com_port: '/dev/ttyUSB0'
        num_valves: 3
        daisychain_ID:
            - 'a'
            - 'b'
            - 'c'
        name:
            - 'Buffer 8-way valve'
            - 'RT rinsing 2-way valve'
            - 'Syringe 2-way valve'
        number_outputs:
            - 8
            - 2
            - 2
        valve_positions:
            - - '1'
              - '2'
              - '3'
              - '4'
              - '5'
              - '6'
              - '7'
              - '8'
            - - '1: Rinse needle'
              - '2: Inject probe'
            - - '1: Syringe'
              - '2: Pump'

    # please specify for all elements corresponding information in the same order,
    # starting from the first valve in the daisychain (valve 'a')
    """
    # config options
    _com_port = None
    _num_valves = ConfigOption('num_valves', missing='warn')
    _valve_names = ConfigOption('name', missing='warn')
    _daisychain_IDs = ConfigOption('daisychain_ID', missing='warn')
    _number_outputs = ConfigOption('number_outputs', missing='warn')
    valve_positions = ConfigOption('valve_positions',
                                   [])  # optional; if labels instead of only valve numbers on the GUI are desired

    # Dummy-specific options
    _initial_position = 1
    _move_delay = 0
    _timeout = 10
    _valve_dict = {}

    # attributes
    _serial_connection = None
    _valve_state = {}  # dict contains the valve names as keys and their status as values # {'a': status_valve1, ..}
    _positions = {}  # dict containing the positions of the valves
    _timeout = 10

    def on_activate(self):
        """ Initialization.
        """
        if self._num_valves < 1:
            self.log.error('Number of valves must be greater than 0')
        else:
            self.log.info(f"Valve dummy initialized with {int(self._num_valves)} valve(s).")

        # Initialized the valves dict
        for address, name, number_outputs in zip(
            self._daisychain_IDs,
            self._valve_names,
            self._number_outputs,
        ):
            self._valve_dict[address] = {
                "daisychain_ID": address,
                "name": str(name),
                "number_outputs": int(number_outputs),
            }

        # Initialize the positions and status of each valve
        for address, valve_info in self._valve_dict.items():
            self._positions[address] = self._initial_position
            self._valve_state[address] = "Y"


    def on_deactivate(self):
        """ Close serial port when deactivating the module.
        """
        pass

    # ----------------------------------------------------------------------------------------------------------------------
    # Valvepositioner interface functions
    # ----------------------------------------------------------------------------------------------------------------------

    def get_valve_dict(self):
        """ This method retrieves a dictionary with the following entries, containing relevant information for each
        valve positioner in a daisychain:
                    {'a': {'daisychain_ID': 'a', 'name': str name, 'number_outputs': int number_outputs},
                    {'b': {'daisychain_ID': 'b', 'name': str name, 'number_outputs': int number_outputs},
                    ...
                    }
        @return: dict valve_dict: dictionary following the example shown above
        """
        return {
            address: dict(valve_info)
            for address, valve_info in self._valve_dict.items()
        }

    def get_status(self):
        """ This method reads the valve status and returns it.

        @return: dict: containing the valve ID as key and the str status code as value (N=not executed - Y=idle - *=busy)
        """
        for n in range(self._num_valves):
            self._valve_state[chr(n + 97)] = "Y"
        return self._valve_state

    def get_valve_position(self, valve_address):
        """ This method gets the current position of the valve positioner.

        @param: str valve_address: ID of the valve positioner
        @return: int position: position of the valve positioner specified by valve_address
        """
        if valve_address in self._daisychain_IDs:
            return self._positions[valve_address]
        else:
            self.log.warning(f'Valve {valve_address} not available.')
            return None

    def set_valve_position(self, valve_address, target_position):
        """ This method sets the valve position for the valve specified by valve_address.

        @param: str valve address: ID of the valve positioner (eg. "a")
        @param: int target_position: new position for the valve at valve_address
        """
        if valve_address in self._daisychain_IDs:
            start_pos = self.get_valve_position(valve_address)
            max_pos = self.get_valve_dict()[valve_address]['number_outputs']
            if target_position > max_pos:
                self.log.warning(f'Target position out of range for valve {valve_address}. Position not set.')
            else:
                self._positions[valve_address] = target_position
                self.wait_for_idle()
                self.log.info(f'Set {self.get_valve_dict()[valve_address]["name"]} to position {target_position}')
        else:
            self.log.warning(f'Valve {valve_address} not available.')

    def wait_for_idle(self, poll_interval=0.2):
        """Wait until all valves are idle.

        Returns:
            bool: True if all valves became idle, False if timeout was reached.
        """
        sleep(1)