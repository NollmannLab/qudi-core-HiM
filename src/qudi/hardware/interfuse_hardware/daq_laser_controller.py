# -*- coding: utf-8 -*-
"""
Author: JB Fiche - adapted for qudi-core-HiM from the previous daq script used in qudi-HiM
Created: 2026-07-21

Interfuse to control the laser using a DAQ or an FPGA device.

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
from qudi.interface.lasercontrol_interface import LasercontrolInterface


class DaqLaserController(LasercontrolInterface):
    """Expose named DAQ outputs as a laser controller."""

    daq = Connector(
        name="daq",
        interface="DaqInterface",
    )

    _laser_channels = ConfigOption(
        "laser_channels",
        missing="error",
    )

    def on_activate(self):
        """Connect to the generic DAQ module."""
        self._daq = self.daq()
        self._laser_dict = self._build_laser_dict()

        # Ensure safe initial state.
        self.disable_all()

    def on_deactivate(self):
        """Switch all laser-control voltages off."""
        self.disable_all()
        self._daq = None

    def _build_laser_dict(self):
        """Build metadata consumed by LaserControlLogic."""
        laser_dict = {}

        for index, (laser_name, config) in enumerate(
            self._laser_channels.items(),
            start=1,
        ):
            laser_dict[laser_name] = {
                "label": laser_name,
                "wavelength": config["wavelength"],
                "channel": config["daq_task"],
            }

        return laser_dict

    def get_dict(self):
        """Return configured laser metadata."""
        return {
            name: dict(metadata)
            for name, metadata in self._laser_dict.items()
        }

    def apply_voltage(self, voltage, channel):
        """Apply voltage to one DAQ-controlled laser channel."""
        channel_config = self._laser_dict[channel]
        voltage = float(voltage)

        self._daq.write_named_ao(
            channel_config["channel"],
            voltage,
        )

    def disable_all(self):
        """Set all laser-control outputs to zero volts."""
        for config in self._laser_dict.values():
            self._daq.write_named_ao(
                config["channel"],
                0.0,
            )