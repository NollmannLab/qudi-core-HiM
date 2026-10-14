# -*- coding: utf-8 -*-
"""
Author: JB Fiche - written for qudi-core-HiM with Claude code
Created: 2026-10-12
Logic module for a galvo mirror (OPM beam-sweep galvo).

Thin logic layer over a hardware module implementing GalvoInterface, so that tasks (and a future
GUI) never talk to the hardware directly. All voltages are in volts (V).

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------

Modified with Claude code (Anthropic)
"""

from typing import Tuple

from qtpy import QtCore

from qudi.core.connector import Connector
from qudi.core.module import LogicBase


class GalvoLogic(LogicBase):
    """Control a galvo mirror through a GalvoInterface hardware module.

    set_voltage() / go_to_rest() return True on success and False if the hardware refused or
    failed the command (out-of-range voltage, DAQ error); the hardware logs the reason as an error
    and nothing is written. sigVoltageChanged(voltage) is emitted after every successful write
    only. A task must check the return value and stop (e.g. raise) if it is False, otherwise it
    would carry on with the galvo at its previous position.

    Config example for copy-paste (logic:):

        galvo_logic:
            module.Class: 'galvo_logic.GalvoLogic'
            connect:
                galvo: 'galvo'
    """

    galvo = Connector(name='galvo', interface='GalvoInterface')

    sigVoltageChanged = QtCore.Signal(float)  # new galvo voltage (V)

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        """Move the galvo to rest (errors are logged by the hardware)."""
        self.go_to_rest()

    def set_voltage(self, voltage: float) -> bool:
        """Move the galvo to the given voltage (V). Returns True on success, False if refused or
        failed (the reason is logged as an error, nothing is written).
        """
        ok = self.galvo().set_voltage(voltage)
        if ok:
            self.sigVoltageChanged.emit(self.galvo().get_voltage())
        return bool(ok)

    def get_voltage(self) -> float:
        """Return the last voltage written to the galvo (V)."""
        return self.galvo().get_voltage()

    def get_limits(self) -> Tuple[float, float]:
        """Return the allowed voltage range (minimum, maximum) in V."""
        return self.galvo().get_limits()

    def get_rest_voltage(self) -> float:
        """Return the galvo rest voltage (V)."""
        return self.galvo().get_rest_voltage()

    def get_optical_axis_voltage(self) -> float:
        """Return the galvo optical axis voltage (V)."""
        return self.galvo().get_optical_axis_voltage()

    def go_to_rest(self) -> bool:
        """Move the galvo to its rest voltage. Returns True on success, False otherwise."""
        ok = self.galvo().go_to_rest()
        if ok:
            self.sigVoltageChanged.emit(self.galvo().get_voltage())
        return bool(ok)

    def go_to_optical_axis(self) -> bool:
        """Move the galvo to its central position (for the microscope optical axis). Returns True on success, False
        otherwise."""
        ok = self.galvo().go_to_optical_axis()
        if ok:
            self.sigVoltageChanged.emit(self.galvo().get_voltage())
        return bool(ok)
