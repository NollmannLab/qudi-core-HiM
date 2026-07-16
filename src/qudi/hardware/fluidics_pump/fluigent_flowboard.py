# -*- coding: utf-8 -*-
"""
Author: F Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2026-07-15

Qudi-core-HiM hardware module for a Fluigent flowboard.

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

from importlib import import_module

from qudi.core.configoption import ConfigOption
from qudi.interface.fluidics_interface import FluidicsInterface


class FluigentFlowboard(FluidicsInterface):
    """Hardware class representing a Fluigent microfluidics controller.

    Example config:

    fluigent_flowboard:
      module.Class: 'fluidics_pump.fluigent_flowboard.FluigentFlowboard'
      options:
        pressure_channel_IDs:
          - 0
        sensor_channel_IDs:
          - 0
    """

    _pressure_channel_ids = ConfigOption("pressure_channel_IDs", missing="error")
    _sensor_channel_ids = ConfigOption("sensor_channel_IDs", missing="error")

    _fgt = None
    _initialized = False
    _pressure_channels = ()
    _sensor_channels = ()

    def on_activate(self):
        """Initialize the Fluigent SDK and check configured channels."""
        try:
            self._fgt = import_module("Fluigent.SDK")
        except ImportError as exc:
            self.log.error(
                "Fluigent SDK not available. Install the vendor package "
                "providing 'Fluigent.SDK' before activating this module."
            )
            raise exc

        self._pressure_channels = self._normalize_channel_ids(self._pressure_channel_ids)
        self._sensor_channels = self._normalize_channel_ids(self._sensor_channel_ids)

        try:
            serial_numbers, controller_types = self._fgt.fgt_detect()
            self.log.info(f"Detected {len(serial_numbers)} Fluigent controller(s).")
            self.log.info(f"Fluigent controller serial numbers: {serial_numbers}")
            self.log.info(f"Fluigent controller types: {controller_types}")

            init_result = self._fgt.fgt_init()
            self.log.info(f"Fluigent SDK init result: {init_result}")

            controllers_info = self._fgt.fgt_get_controllersInfo()
            self.log.info(f"Initialized Fluigent controllers: {controllers_info}")
            self.log.info(
                f"Initialized Fluigent controllers with status: "
                f"{self._call_noarg_get_with_error('fgt_get_controllersInfo')}"
            )

            num_pressure_channels = self._fgt.fgt_get_pressureChannelCount()
            num_sensor_channels = self._fgt.fgt_get_sensorChannelCount()
            self.log.info(f"Pressure channels : {num_pressure_channels}")
            self.log.info(
                f"Pressure channel count with status: "
                f"{self._call_noarg_get_with_error('fgt_get_pressureChannelCount')}"
            )
            self.log.info(f"Sensor channels : {num_sensor_channels}")
            self.log.info(
                f"Sensor channel count with status: "
                f"{self._call_noarg_get_with_error('fgt_get_sensorChannelCount')}"
            )
            # if num_pressure_channels > 0:
            #     self.log.info(self._fgt.fgt_get_pressure(0))
            #     self.log.info(
            #         f"Initialized pressure channels: "
            #         f"{self._call_noarg_get_with_error('fgt_get_pressureChannelsInfo')}"
            #     )
            # if num_sensor_channels > 0:
            #     self.log.info(
            #         f"Initialized sensor channels: "
            #         f"{self._call_noarg_get_with_error('fgt_get_sensorChannelsInfo')}"
            #     )
            if num_pressure_channels == 0 and num_sensor_channels == 0:
                self.log.warning(
                    "No Fluigent channels were initialized. The controller can "
                    "be detected over USB, but the SDK did not expose any "
                    "pressure or sensor channel in the initialized session."
                )
            self._initialized = True
        except Exception as exc:
            self._initialized = False
            self.log.error(f"Fluigent flowboard initialization failed: {exc}")
            raise

        self._check_configured_channels()

    def on_deactivate(self):
        """Close the Fluigent SDK connection."""
        if self._fgt is not None and self._initialized:
            try:
                self._fgt.fgt_close()
            except Exception as exc:
                self.log.warning(f"Closing the Fluigent SDK failed: {exc}")
            finally:
                self._initialized = False

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

            self._fgt.fgt_set_pressure(channel, pressure)

    def get_pressure(self, param_list=None):
        """Return pressure values for selected or all configured pressure channels."""
        self._require_initialized()
        channels = self._selected_pressure_channels(param_list)
        return {channel: self._fgt.fgt_get_pressure(channel) for channel in channels}

    def get_pressure_unit(self, param_list=None):
        """Return pressure units for selected or all configured pressure channels."""
        self._require_initialized()
        channels = self._selected_pressure_channels(param_list)
        return {channel: self._fgt.fgt_get_pressureUnit(channel) for channel in channels}

    def get_pressure_range(self, param_list=None):
        """Return pressure ranges for selected or all configured pressure channels."""
        self._require_initialized()
        channels = self._selected_pressure_channels(param_list)
        return {channel: self._fgt.fgt_get_pressureRange(channel) for channel in channels}

    # Sensor channels
    def get_flowrate(self, param_list=None):
        """Return flowrate values for selected or all configured sensor channels."""
        self._require_initialized()
        channels = self._selected_sensor_channels(param_list)
        return {channel: self._fgt.fgt_get_sensorValue(channel) for channel in channels}

    def get_sensor_unit(self, param_list=None):
        """Return sensor units for selected or all configured sensor channels."""
        self._require_initialized()
        channels = self._selected_sensor_channels(param_list)
        return {channel: self._fgt.fgt_get_sensorUnit(channel) for channel in channels}

    def get_sensor_range(self, param_list=None):
        """Return sensor ranges for selected or all configured sensor channels."""
        self._require_initialized()
        channels = self._selected_sensor_channels(param_list)
        return {channel: self._fgt.fgt_get_sensorRange(channel) for channel in channels}

    # Helpers
    @staticmethod
    def _normalize_channel_ids(channel_ids):
        return tuple(int(channel_id) for channel_id in channel_ids)

    def _require_initialized(self):
        if self._fgt is None or not self._initialized:
            raise RuntimeError("Fluigent flowboard is not initialized.")

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
