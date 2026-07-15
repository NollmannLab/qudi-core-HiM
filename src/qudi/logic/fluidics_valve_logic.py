# -*- coding: utf-8 -*-
"""
Author: F. Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2021-03-04 -> translated into qudi-core-HiM on 2026-07-15
This module contains a class for the Logic module of fluidics valve positioners.

The logic is intentionally thin: hardware modules keep the serial protocol and
device-specific routing, while this module exposes a qudi-core style API and
Qt signals for GUIs and higher-level experiment logic.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from qtpy import QtCore

from qudi.core.connector import Connector
from qudi.core.module import LogicBase
from qudi.core.statusvariable import StatusVar


class FluidicsValveLogic(LogicBase):
    """Logic class wrapping a fluidics valve positioner hardware module.

    Example config:

      fluidics_valve_logic:
        module.Class: 'fluidics_valve_logic.FluidicsValveLogic'
        connect:
          valve: 'hamilton_valve'
    """

    valve = Connector(interface="ValvePositionerInterface", name="valve")

    _valve_positions = StatusVar(name="_valve_positions", default=dict())
    _valve_status = StatusVar(name="_valve_status", default=dict())

    sigValveDictUpdated = QtCore.Signal(dict)
    sigValvePositionsUpdated = QtCore.Signal(dict)
    sigValveStatusUpdated = QtCore.Signal(dict)
    sigValvePositionChanged = QtCore.Signal(str, int)

    _required_hardware_methods = (
        "get_valve_dict",
        "get_status",
        "get_valve_position",
        "set_valve_position",
    )

    def on_activate(self):
        """Connect to hardware and publish the initial valve state."""
        self._valve = self.valve()
        self._validate_hardware()
        self._valve_dict = self._valve.get_valve_dict()
        self.refresh_status()
        self.refresh_positions()
        self.sigValveDictUpdated.emit(self.valve_dict)

    def on_deactivate(self):
        """Release the cached hardware reference."""
        self._valve = None

    @property
    def valve_dict(self):
        """Return configured valve metadata.

        Returns:
            dict: Valve metadata indexed by hardware address.
        """
        return dict(getattr(self, "_valve_dict", {}))

    @property
    def valve_positions(self):
        """Return cached valve positions.

        Returns:
            dict: Current cached valve positions indexed by hardware address.
        """
        return dict(self._valve_positions)

    @property
    def valve_status(self):
        """Return cached valve status values.

        Returns:
            dict: Status values indexed by hardware address.
        """
        return dict(self._valve_status)

    @property
    def valve_position_labels(self):
        """Return optional hardware-provided position labels.

        Returns:
            list: Position labels from the hardware module, or an empty list.
        """
        return getattr(self._valve, "valve_positions", [])

    def refresh_status(self):
        """Read and emit the current hardware status for all valves.

        Returns:
            dict: Updated valve status values indexed by hardware address.
        """
        self._valve_status = dict(self._valve.get_status())
        self.sigValveStatusUpdated.emit(self.valve_status)
        return self.valve_status

    def refresh_positions(self):
        """Read and emit the current position of all configured valves.

        Returns:
            dict: Updated valve positions indexed by hardware address.
        """
        positions = {}
        for valve_address in self.valve_dict:
            position = self._valve.get_valve_position(valve_address)
            if position is not None:
                positions[valve_address] = int(position)
        self._valve_positions = positions
        self.sigValvePositionsUpdated.emit(self.valve_positions)
        return self.valve_positions

    def get_valve_position(self, valve_address):
        """Return the current position for a single valve.

        Args:
            valve_address (str): Hardware address, for example ``"a"``.

        Returns:
            int | None: Current valve position, or ``None`` if the hardware did
            not return a position.
        """
        self._check_valve_address(valve_address)
        position = self._valve.get_valve_position(valve_address)
        if position is not None:
            positions = self.valve_positions
            positions[valve_address] = int(position)
            self._valve_positions = positions
            self.sigValvePositionsUpdated.emit(self.valve_positions)
        return position

    def set_valve_position(self, valve_address, target_position, wait=True):
        """Move one valve to a target position.

        Args:
            valve_address (str): Hardware address, for example ``"a"``.
            target_position (int): 1-based target position understood by the hardware.
            wait (bool): If true and the hardware supports it, wait until all valves are idle.

        Returns:
            int | None: Confirmed valve position after the move, or ``None`` if
            the hardware did not return a position.
        """
        self._check_valve_address(valve_address)
        target_position = int(target_position)
        self._check_target_position(valve_address, target_position)

        self._valve.set_valve_position(valve_address, target_position)
        if wait and hasattr(self._valve, "wait_for_idle"):
            self._valve.wait_for_idle()

        position = self._valve.get_valve_position(valve_address)
        if position is not None:
            position = int(position)
            positions = self.valve_positions
            positions[valve_address] = position
            self._valve_positions = positions
            self.sigValvePositionChanged.emit(valve_address, position)
            self.sigValvePositionsUpdated.emit(self.valve_positions)
        self.refresh_status()
        return position

    def set_valve_positions(self, position_dict, wait=True):
        """Move several valves.

        Args:
            position_dict (dict): Mapping ``{valve_address: target_position}``.
            wait (bool): If true and the hardware supports it, wait once after all
                move commands have been issued.

        Returns:
            dict: Updated valve positions indexed by hardware address.
        """
        for valve_address, target_position in position_dict.items():
            self._check_valve_address(valve_address)
            self._check_target_position(valve_address, int(target_position))

        for valve_address, target_position in position_dict.items():
            self._valve.set_valve_position(valve_address, int(target_position))

        if wait and hasattr(self._valve, "wait_for_idle"):
            self._valve.wait_for_idle()

        self.refresh_positions()
        self.refresh_status()
        for valve_address in position_dict:
            if valve_address in self._valve_positions:
                self.sigValvePositionChanged.emit(
                    valve_address, self._valve_positions[valve_address]
                )
        return self.valve_positions

    def _validate_hardware(self):
        """Check whether the connected hardware implements the expected API.

        Raises:
            TypeError: If required valve-positioner methods are missing.
        """
        missing = [
            method
            for method in self._required_hardware_methods
            if not callable(getattr(self._valve, method, None))
        ]
        if missing:
            raise TypeError(
                "Connected valve hardware is missing required method(s): "
                f"{', '.join(missing)}"
            )

    def _check_valve_address(self, valve_address):
        """Validate that a valve address exists in the configured valve map.

        Args:
            valve_address (str): Hardware address to validate.

        Raises:
            ValueError: If the address is not known.
        """
        if valve_address not in self.valve_dict:
            raise ValueError(f"Unknown valve address: {valve_address!r}")

    def _check_target_position(self, valve_address, target_position):
        """Validate a target position against the valve output count.

        Args:
            valve_address (str): Hardware address of the valve.
            target_position (int): 1-based valve position.

        Raises:
            ValueError: If the target position is outside the valve range.
        """
        number_outputs = int(self.valve_dict[valve_address]["number_outputs"])
        if target_position < 1 or target_position > number_outputs:
            raise ValueError(
                f"Target position {target_position} is outside the range "
                f"1..{number_outputs} for valve {valve_address!r}."
            )
