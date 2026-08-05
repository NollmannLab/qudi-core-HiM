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
    _laser_channels_by_wavelength = {}
    # _laser_dict = {}

    def on_activate(self):
        """Connect to the generic DAQ module."""

        # connect to daq
        self._daq = self.daq()

        # # initialize laser dict for daq communication
        # self._laser_dict = self._build_laser_dict()

        # initialize wavelengths list for the logic
        self._laser_channels_by_wavelength = {
            int(wavelength): dict(channel_config)
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
        return tuple(self._laser_channels_by_wavelength)


    def set_intensity_selected_laser_line(self, wavelength, intensity):
        """Apply voltage to one DAQ-controlled laser channel."""
        channel_config = self._laser_channels_by_wavelength[wavelength]
        task_name = channel_config["daq_task"]
        task_voltage_range = self._daq.get_task_range(task_name)
        max_voltage = max(task_voltage_range)

        voltage = float(intensity * max_voltage / 100)

        self._daq.write_named_ao(
            channel_config["daq_task"],
            voltage,
        )

    def set_intensity_all_laser_lines(self, intensity_dict):
        for wavelength, intensity in intensity_dict.items():
            self.set_intensity_selected_laser_line(self, wavelength, intensity)

    # def _build_laser_dict(self):
    #     """Build metadata consumed by LaserControlLogic."""
    #     laser_dict = {}
    #
    #     for index, (laser_name, config) in enumerate(
    #         self._laser_channels.items(),
    #         start=1,
    #     ):
    #         laser_dict[laser_name] = {
    #             "label": laser_name,
    #             "wavelength": config["wavelength"],
    #             "channel": config["daq_task"],
    #         }
    #
    #     return laser_dict

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

    # def disable_all(self):
    #     """Set all laser-control outputs to zero volts."""
    #     for config in self._laser_dict.values():
    #         self._daq.write_named_ao(voltage
    #             config["channel"],
    #             0.0,
    #         )

# ----------------------------------------------------------------------------------------------------------------------
# Private methods
# ----------------------------------------------------------------------------------------------------------------------

    def _validate_laser_channels(self) -> None:
        """Validate wavelength keys and DAQ task assignments."""
        if not self._laser_channels_by_wavelength:
            raise ValueError("No DAQ-controlled laser channels are configured.")

        for wavelength, channel_config in self._laser_channels_by_wavelength.items():
            if wavelength <= 0:
                raise ValueError(f"Invalid laser wavelength: {wavelength!r}.")

            if not isinstance(channel_config, dict):
                raise TypeError(
                    f"Configuration for {wavelength} nm must be a dictionary."
                )

            daq_task = channel_config.get("daq_task")

            if not daq_task:
                raise ValueError(
                    f"No DAQ task is configured for the {wavelength} nm laser."
                )