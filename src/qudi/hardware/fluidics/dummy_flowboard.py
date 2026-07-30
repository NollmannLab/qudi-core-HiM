# -*- coding: utf-8 -*-
"""
Author: F Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2026-07-16

Qudi-core-HiM hardware module for a dummy flowboard.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from numpy.random import normal
from qudi.core.configoption import ConfigOption
from qudi.interface.deprecated.fluidics_interface import FluidicsInterface


class DummyFlowboard(FluidicsInterface):
    """Hardware class representing a Fluigent microfluidics controller.

    Example config:

    fluigent_flowboard:
      module.Class: 'fluidics.fluigent_flowboard.FluigentFlowboard'
      options:
        pressure_channel_IDs:
          - 0
        sensor_channel_IDs:
          - 0
    """

    _pressure_channel_ids = ConfigOption("pressure_channel_IDs", missing="error")
    _sensor_channel_ids = ConfigOption("sensor_channel_IDs", missing="error")

    # store here the values that would normally be queried from the device
    pressure_dict = {}
    pressure_unit_dict = {}
    pressure_range_dict = {}

    sensor_unit_dict = {}
    sensor_range_dict = {}
    max_pressure = 350   # in mbar
    max_flow = 11000  # in ul/min
    mean_flow = 200  # in ul/min

    # communication
    _pressure_channels = ()
    _sensor_channels = ()

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """

        self._pressure_channels = self._normalize_channel_ids(self._pressure_channel_ids)
        self._sensor_channels = self._normalize_channel_ids(self._sensor_channel_ids)

        for i in range(len(self._pressure_channel_ids)):
            self.pressure_dict[i] = 0
            self.pressure_unit_dict[i] = 'mbar'
            self.pressure_range_dict[i] = (0, self.max_pressure)

        for i in range(len(self._sensor_channel_ids)):
            self.sensor_unit_dict[i] = 'ul/min'
            self.sensor_range_dict[i] = (-self.max_flow, self.max_flow)

    def on_deactivate(self):
        """Close the connection."""
        pass

    # Pressure channels
    def set_pressure(self, param_dict):
        """Set pressure values on pressure channels.

        Args:
            param_dict: Mapping of ``{pressure_channel_id: pressure_setpoint}``.
        """
        self._require_initialized()

        for channel, pressure in param_dict.items():
            channel = int(channel)
            if not self._is_pressure_channel(channel):
                self.log.warning(f"Pressure channel {channel} is not configured.")
                continue

            pressure_min, pressure_max = self.get_pressure_range([channel])[channel]
            if pressure < pressure_min or pressure > pressure_max:
                self.log.warning(
                    f"Pressure {pressure} is outside the allowed range "
                    f"[{pressure_min}, {pressure_max}] for channel {channel}."
                )
                continue

            self.pressure_dict[channel] = pressure

    def get_pressure(self, param_list=None):
        """Return pressure values for selected or all configured pressure channels."""
        self._require_initialized()
        channels = self._selected_pressure_channels(param_list)
        return {channel: self.pressure_dict[channel] for channel in channels}

    def get_pressure_unit(self, param_list=None):
        """Return pressure units for selected or all configured pressure channels."""
        self._require_initialized()
        channels = self._selected_pressure_channels(param_list)
        return {channel: self.pressure_unit_dict[channel] for channel in channels}

    def get_pressure_range(self, param_list=None):
        """Return pressure ranges for selected or all configured pressure channels."""
        self._require_initialized()
        channels = self._selected_pressure_channels(param_list)
        return {channel: self.pressure_range_dict[channel] for channel in channels}

    # Sensor channels
    def get_flowrate(self, param_list=None):
        """Return flowrate values for selected or all configured sensor channels."""
        self._require_initialized()
        channels = self._selected_sensor_channels(param_list)
        flowrate = int(self.mean_flow + normal(0, 10))
        return {channel: flowrate for channel in channels}

    def get_sensor_unit(self, param_list=None):
        """Return sensor units for selected or all configured sensor channels."""
        self._require_initialized()
        channels = self._selected_sensor_channels(param_list)
        return {channel: self.sensor_unit_dict[channel] for channel in channels}

    def get_sensor_range(self, param_list=None):
        """Return sensor ranges for selected or all configured sensor channels."""
        self._require_initialized()
        channels = self._selected_sensor_channels(param_list)
        return {channel: self.sensor_range_dict[channel] for channel in channels}

    # Helpers
    @staticmethod
    def _normalize_channel_ids(channel_ids):
        return tuple(int(channel_id) for channel_id in channel_ids)

    def _require_initialized(self):
        pass

    def _call_noarg_get_with_error(self, function_name):
        func = getattr(self._fgt, function_name)
        try:
            return func(get_error=True)
        except TypeError:
            return func()

    def _check_configured_channels(self):
        pressure_count = self._fgt.fgt_get_pressureChannelCount()
        sensor_count = self._fgt.fgt_get_sensorChannelCount()

        self.log.info(pressure_count)
        self.log.info(sensor_count)

        missing_pressure = [
            channel
            for channel in self._pressure_channels
            if channel < 0 or channel >= pressure_count
        ]
        missing_sensors = [
            channel
            for channel in self._sensor_channels
            if channel < 0 or channel >= sensor_count
        ]

        if missing_pressure:
            self.log.warning(
                f"Configured pressure channel(s) {missing_pressure} are outside "
                f"the detected channel range 0..{pressure_count - 1}."
            )
        if missing_sensors:
            self.log.warning(
                f"Configured sensor channel(s) {missing_sensors} are outside "
                f"the detected channel range 0..{sensor_count - 1}."
            )

    def _selected_pressure_channels(self, channels):
        return self._selected_channels(channels, self._pressure_channels, "pressure")

    def _selected_sensor_channels(self, channels):
        return self._selected_channels(channels, self._sensor_channels, "sensor")

    def _selected_channels(self, channels, configured_channels, channel_type):
        if channels is None:
            return configured_channels

        selected_channels = []
        for channel in self._normalize_channel_ids(channels):
            if channel in configured_channels:
                selected_channels.append(channel)
            else:
                self.log.warning(
                    f"{channel_type.capitalize()} channel {channel} is not configured."
                )
        return tuple(selected_channels)

    def _is_pressure_channel(self, channel):
        return channel in self._pressure_channels
