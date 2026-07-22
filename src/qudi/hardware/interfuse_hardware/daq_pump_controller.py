# -*- coding: utf-8 -*-
"""
Author: JB Fiche with codex - adapted for qudi-core-HiM from the previous daq script used in qudi-HiM
Created: 2026-07-21

Interfuse hardware controller for the rinsing pump -> control the pump through DAQ

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.interface.pump_interface import PumpInterface


class DaqPumpController(PumpInterface):
    """Control a voltage-driven pump through a generic DAQ."""

    daq = Connector(name="daq", interface="DaqInterface")
    _output_task = ConfigOption("output_task", missing="error")
    _stop_voltage = ConfigOption("stop_voltage",0.0)
    _rinsing_voltage = ConfigOption("rinsing_voltage",0.0)

    def on_activate(self):
        self._daq = self.daq()
        self.stop()

    def on_deactivate(self):
        self.stop()
        self._daq = None

    def rinsing(self):
        self._daq.write_named_ao(
            self._output_task,
            self._stop_voltage,
        )

    def stop(self):
        self._daq.write_named_ao(
            self._output_task,
            float(self._stop_voltage),
        )