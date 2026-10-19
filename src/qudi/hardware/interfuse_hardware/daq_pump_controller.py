# -*- coding: utf-8 -*-
"""
Author: JB Fiche - adapted for qudi-core-HiM by JB Fiche
Created: 2026-07-29

Qudi-core-HiM hardware module for the peristaltic fluidics pump controlled by the DAQ.

The Fluigent SDK is provided by the vendor package and is usually installed
only on acquisition computers. Import it lazily so this module can still be
discovered on development machines where the hardware SDK is absent.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from typing import Dict, Optional, Sequence, Any

from qudi.core.connector import Connector
from qudi.interface.pump_interface import PumpInterface
from qudi.core.configoption import ConfigOption
from qudi.interface.daq_interface import DaqInterface


class DaqPumpController(PumpInterface):
    """Control a voltage-driven pump through a generic DAQ.

    The controller exposes a single logical output channel and maps pump
    setpoints to one analog output task on the configured DAQ backend.

    The configured ``minimum`` / ``maximum`` are the output limits: a requested
    voltage outside them is clamped before it is written to the DAQ, and the
    clamped value is the one stored and reported by ``get_output``. A warning is
    logged when the requests go out of range (not for every request while they
    stay out of range), and one info line when they are back in range.
    """

    daq = Connector(name="daq", interface="DaqInterface")
    _output_task = ConfigOption("output_task", missing="error")
    _pump_kind = ConfigOption("kind", missing="error", converter=str)
    _pump_unit = ConfigOption("unit", missing="error", converter=str)
    _voltage_minimum = ConfigOption("minimum", missing="error", converter=float)
    _voltage_maximum = ConfigOption("maximum", missing="error", converter=float)

    # Attributes
    _daq: Optional[DaqInterface] = None
    _set_voltage: float = 0.0
    _out_of_range: bool = False  # True while the requested voltages are outside [minimum, maximum]

    def on_activate(self):
        """Connect to the DAQ backend and reset the pump output.

        The module stores the connected DAQ backend and immediately drives the
        configured output task to the minimum voltage.
        """
        self._daq = self.daq()
        self.stop()

    def on_deactivate(self):
        """Drive the output to minimum and release the DAQ backend."""
        self.stop()
        self._daq = None

    # Pressure channels
    def set_output(self, param_dict: Dict[int, float]) -> None:
        """Set the pump output voltage.

        Args:
            param_dict: Mapping of ``{channel_id: voltage_setpoint}``. Only a
                single channel is supported; if multiple channels are supplied,
                a warning is logged and no output is written. The voltage is
                clamped to [minimum, maximum] before it is written.

        Raises:
            AttributeError: If the DAQ backend has not been activated.
        """
        if len(param_dict) > 1:
            self.log.warning(f"Multiple channels not supported: {param_dict}")
        elif len(param_dict) == 1:
            (_, voltage), = param_dict.items()
            voltage = self._clamp(float(voltage))
            self._daq.write_named_ao(self._output_task, voltage)
            self._set_voltage = voltage

    def get_output(self, param_list: Optional[Sequence[int]] = None) -> Dict[int, float]:
        """Read the last set pump output voltage.

        Args:
            param_list: Optional list of requested channel IDs. Only a single
                channel is supported. If ``None``, the method returns the
                stored voltage for channel ``0``.

        Returns:
            A mapping of ``{channel_id: voltage_setpoint}`` for the supported
            channel.
        """
        if param_list is None:
            return {0: self._set_voltage}
        else:
            if len(param_list) > 1:
                raise ValueError(f"Multiple channels not supported: {param_list}")
            elif len(param_list) == 1:
                channel = param_list[0]
                return {channel: self._set_voltage}
            else:
                raise ValueError(f"No channel indicated")

    def get_constraints(self) -> Dict[str, Any]:
        """Return native pump-output constraints.

        Returns:
            A mapping with the configured pump kind, unit, minimum voltage,
            and maximum voltage.
        """
        return {
            "kind": self._pump_kind,
            "unit": self._pump_unit,
            "minimum": float(self._voltage_minimum),
            "maximum": float(self._voltage_maximum),
        }

    def stop(self) -> None:
        """Drive the pump to its safe minimum output."""
        self.set_output({0: float(self._voltage_minimum)})
        self._set_voltage = self._voltage_minimum

    def _clamp(self, voltage: float) -> float:
        """Return voltage limited to [minimum, maximum]. Logs a warning when the requests go out of
        range and an info line when they are back in range (the regulation loop writes ~10 times per
        second, so nothing is logged while the state does not change)."""
        low, high = float(self._voltage_minimum), float(self._voltage_maximum)
        clamped = min(max(voltage, low), high)
        if clamped != voltage:
            if not self._out_of_range:
                self._out_of_range = True
                self.log.warning(f'Requested pump output {voltage:g} {self._pump_unit} is outside '
                                 f'[{low:g}, {high:g}] {self._pump_unit} - {clamped:g} '
                                 f'{self._pump_unit} written. Further out-of-range requests are '
                                 f'clamped without a new warning.')
        elif self._out_of_range:
            self._out_of_range = False
            self.log.info(f'Pump output requests back within [{low:g}, {high:g}] {self._pump_unit}.')
        return clamped


