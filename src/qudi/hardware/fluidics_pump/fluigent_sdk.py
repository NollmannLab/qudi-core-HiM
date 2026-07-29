# -*- coding: utf-8 -*-
"""
Author: JB Fiche
Created: 2026-07-29

Qudi-core-HiM hardware module to access Fluigent SDK.

The Fluigent SDK is provided by the vendor package and is usually installed
only on acquisition computers. Import it lazily so this module can still be
discovered on development machines where the hardware SDK is absent.

A single script is used to handle the Fluigent SDK (called by import_module) and to
define low-level commands. Interfuse hardware are used to emulate the pump and the flow
sensor, even though they will be controlled through the same SDK.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from importlib import import_module
from typing import Any, Dict, Tuple
from qudi.interface.fluigent_sdk_interface import FluigentSdkInterface


class FluigentSDK(FluigentSdkInterface):
    """Hardware class allowing control on Fluigent hardware through SDK.

    Example config:
      fluigent_sdk:
        module.Class: 'fluidics.fluigent_sdk.FluigentSdkHardware'
    """

    _fgt = None
    _initialized = False
    _pressure_channels = ()
    _sensor_channels = ()
    _num_pressure_channels = 0
    _num_sensor_channels = 0
    _controllers_info = ""

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

        try:
            serial_numbers, controller_types = self._fgt.fgt_detect()
            init_result = self._fgt.fgt_init()
            self._initialized = True

            self._num_pressure_channels = self._fgt.fgt_get_pressureChannelCount()
            self._num_sensor_channels = self._fgt.fgt_get_sensorChannelCount()
            self._controllers_info = self._fgt.fgt_get_controllersInfo()

            self.log.info(
                f"Fluigent SDK initialized with {len(serial_numbers)} Fluigent controller(s):"
                f"{self._num_pressure_channels} pressure channel(s) and "
                f"{self._num_sensor_channels} sensor channel(s)."
                ""
                f"Fluigent controller serial numbers: {serial_numbers}"
                f"Fluigent controller info: {self._controllers_info}"
            )

            self.log.debug(
                f"Fluigent SDK initialization result: {init_result}"
            )

            if self._num_pressure_channels == 0 and self._num_sensor_channels == 0:
                self.log.warning(
                    "No Fluigent channels were initialized. The SDK did not expose any "
                    "pressure or sensor channel in the initialized session."
                )
        except Exception as exc:
            self._initialized = False
            self.log.error(f"Fluigent flowboard initialization failed: {exc}")
            raise

    def on_deactivate(self):
        """Close the Fluigent SDK connection."""
        self._close_sdk()

    # -------------------------------------------------------------------------
    # Channel discovery
    # -------------------------------------------------------------------------
    def get_pressure_channel_ids(self) -> Tuple[int, ...]:
        """Return all discovered pressure-channel IDs."""
        self._require_initialized()
        pressure_channels = tuple(range(self._num_pressure_channels))
        return tuple(pressure_channels)

    def get_sensor_channel_ids(self) -> Tuple[int, ...]:
        """Return all discovered sensor-channel IDs."""
        self._require_initialized()
        sensor_channels = tuple(range(self._num_sensor_channels))
        return tuple(sensor_channels)

    def get_pressure_channel_info(self, channel: int,) -> Dict[str, Any]:
        """Return range and unit information for one pressure channel."""
        channel = self._validate_pressure_channel(channel)

        return {
            "channel": channel,
            "range": self._sdk_call(
                "fgt_get_pressureRange",
                channel,
            ),
            "unit": self._sdk_call(
                "fgt_get_pressureUnit",
                channel,
            ),
        }

    def get_sensor_channel_info(self, channel: int,) -> Dict[str, Any]:
        """Return range and unit information for one flow-sensor channel."""
        channel = self._validate_sensor_channel(channel)

        return {
            "channel": channel,
            "range": self._sdk_call(
                "fgt_get_sensorRange",
                channel,
            ),
            "unit": self._sdk_call(
                "fgt_get_sensorUnit",
                channel,
            ),
        }

    # -------------------------------------------------------------------------
    # Pressure-controller operations
    # -------------------------------------------------------------------------

    # Pressure channels
    def set_pressure(self, channel: int, pressure: float) -> None:
        """Set pressure values on pressure channels.

        Args:
            param_dict: Mapping of ``{pressure_channel_id: pressure_setpoint}``.
        """
        channel = self._validate_pressure_channel(channel)
        pressure = float(pressure)

        pressure_range = self._sdk_call("fgt_get_pressureRange",channel)
        pressure_min, pressure_max = pressure_range
        if not pressure_min <= pressure <= pressure_max:
            raise ValueError(
                f"Pressure {pressure} is outside [{pressure_min}, {pressure_max}] "
                f"for Fluigent channel {channel}."
            )

        self._sdk_call("fgt_set_pressure",channel, pressure,)

    def get_pressure(self, channel: int) -> float:
        """Read one pressure channel."""
        channel = self._validate_pressure_channel(channel)
        return float(self._sdk_call("fgt_get_pressure",channel))

    # -------------------------------------------------------------------------
    # Flow-sensor operations
    # -------------------------------------------------------------------------

    def get_flowrate(self, channel: int) -> float:
        """Read one flow-sensor channel."""
        channel = self._validate_sensor_channel(channel)

        return float(self._sdk_call("fgt_get_sensorValue",channel))

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _close_sdk(self) -> None:
        """Close the SDK and reset runtime state."""
        if self._fgt is not None and self._initialized:
            try:
                with self._sdk_lock:
                    self._fgt.fgt_close()
            except Exception as error:
                self.log.warning(
                    f"Closing the Fluigent SDK failed: {error}"
                )

    def _validate_pressure_channel(self, channel: int) -> int:
        """Validate and normalize one pressure-channel ID."""
        channel = int(channel)
        pressure_channels = tuple(range(self._num_pressure_channels))

        if channel not in pressure_channels:
            raise ValueError(
                f"Unknown Fluigent pressure channel {channel}. "
                f"Available channels: {pressure_channels}."
            )

        return channel

    def _validate_sensor_channel(self, channel: int) -> int:
        """Validate and normalize one sensor-channel ID."""
        channel = int(channel)
        sensor_channels = tuple(range(self._num_sensor_channels))

        if channel not in sensor_channels:
            raise ValueError(
                f"Unknown Fluigent sensor channel {channel}. "
                f"Available channels: {sensor_channels}."
            )

        return channel

    def _sdk_call(self, function_name: str, *args):
        """Execute one SDK call through the shared SDK lock."""
        self._require_initialized()
        function = getattr(self._fgt, function_name)
        return function(*args)

    def _require_initialized(self):
        if self._fgt is None or not self._initialized:
            raise RuntimeError("Fluigent flowboard is not initialized.")
