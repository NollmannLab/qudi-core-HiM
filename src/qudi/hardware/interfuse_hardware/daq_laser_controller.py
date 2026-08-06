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
from qudi.interface.laser_control_interface import LaserControlInterface


class DaqLaserController(LaserControlInterface):
    """Expose named DAQ outputs as a laser controller. Typical parameters are:

        daq_laser:
            module.Class: 'interfuse_hardware.daq_laser_controller.DaqLaserController'
            connect:
                daq: 'dummy_daq'
            options:
              laser_channels:
                405:
                  daq_task: 'laser_405'
                488:
                  daq_task: 'laser_488'
                561:
                  daq_task: 'laser_561'
                640:
                  daq_task: 'laser_640'

    """

    daq = Connector(name="daq", interface="DaqInterface")
    _laser_channels = ConfigOption("laser_channels", missing="error")

    # attributes
    _daq = None
    _laser_dict = {}

    def on_activate(self):
        """Connect to the generic DAQ module."""

        # connect to daq
        self._daq = self.daq()

        # initialize wavelengths list for the logic
        self._laser_dict = {
            int(wavelength): {
                "channel": dict(channel_config),
                "voltage": 0.0,
                "enabled": False
            }
            for wavelength, channel_config in self._laser_channels.items()
        }
        self._validate_laser_channels()

        # Ensure safe initial state.
        self.disable_all()

    def on_deactivate(self):
        """Switch all laser-control voltages off."""
        self.disable_all()
        self._daq = None

# ----------------------------------------------------------------------------------------------------------------------
# DAQ / laser controller / logic communication methods
# ----------------------------------------------------------------------------------------------------------------------

    def get_available_wavelengths(self) -> tuple[int, ...]:
        """Return the nominal wavelengths controlled through the DAQ."""
        return tuple(self._laser_dict)

    def update_intensity(self, wavelength, intensity):
        """ Update the dictionary for the different laser lines controlled by the DAQ.
            Intensity is converted to voltage accordinf to the selected DAQ channel
            properties
        """
        voltage = self._convert_intensity_to_voltage(wavelength, intensity)
        self._laser_dict[wavelength]["voltage"] = voltage

    def apply_line_intensity(self, wavelength, intensity):
        """Apply voltage to one DAQ-controlled laser channel."""
        # update the _laser_dict
        self.update_intensity(wavelength, intensity)

        # enable the laser (as a security since it should be already enabled)
        self._laser_dict[wavelength]['enabled'] = True

        # write voltage to the corresponding DAQ channel
        voltage = self._laser_dict[wavelength]['voltage']
        channel_config = self._laser_dict[wavelength]['channel']
        self._daq.write_named_ao(channel_config["daq_task"], voltage)

    def ensure_ready(self):
        """ For the DAQ this command does nothing """
        pass

    def enable_all_lines(self):
        """ Enable all the channels, according to the intensity values previously defined """
        for wavelength, channel_state in self._laser_dict.items():
            voltage = self._laser_dict[wavelength]['voltage']
            self._laser_dict[wavelength]['enabled'] = True
            if voltage > 0 :
                channel_config = self._laser_dict[wavelength]['channel']
                self._daq.write_named_ao(channel_config["daq_task"], voltage)

    def disable_all_lines(self):
        """ Disable all laser lines BUT do not change the intensity
        saved in _laser_dict
        """
        for wavelength in self._laser_dict:
            self._laser_dict[wavelength]['enabled'] = False
            channel_config = self._laser_dict[wavelength]['channel']
            self._daq.write_named_ao(channel_config["daq_task"], 0)

    def set_ttl(self, ttl_state):
        pass


# ----------------------------------------------------------------------------------------------------------------------
# Private methods
# ----------------------------------------------------------------------------------------------------------------------

    def _validate_laser_channels(self) -> None:
        """Validate wavelength keys and DAQ task assignments."""
        if not self._laser_dict:
            raise ValueError("No DAQ-controlled laser channels are configured.")

        for wavelength, property in self._laser_dict.items():
            if wavelength <= 0:
                raise ValueError(f"Invalid laser wavelength: {wavelength!r}.")

            channel_config = property['channel']
            if not isinstance(channel_config, dict):
                raise TypeError(
                    f"Configuration for {wavelength} nm must be a dictionary."
                )

            daq_task = channel_config.get("daq_task")

            if not daq_task:
                raise ValueError(
                    f"No DAQ task is configured for the {wavelength} nm laser."
                )

    def _get_voltage_range(self, wavelength):
        channel_config = self._laser_dict[wavelength]["channel"]
        task_name = channel_config["daq_task"]
        task_voltage_range = self._daq.get_task_range(task_name)
        return max(task_voltage_range)

    def _convert_intensity_to_voltage(self, wavelength, intensity):
        max_voltage = self._get_voltage_range(wavelength)
        return float(intensity * max_voltage / 100)
