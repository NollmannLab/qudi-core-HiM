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

from typing import Dict, Optional, List, Sequence, Tuple

from qudi.core.connector import Connector
from qudi.interface.fluigent_sdk_interface import FluigentSdkInterface
from qudi.core.configoption import ConfigOption
from qudi.interface.fluidics_interface import FluidicsInterface


class FluigentFlowboard(FluidicsInterface):
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
    sdk = Connector(interface="FluigentSdkInterface", name="sdk")

    _sdk = None
    _pressure_channels = ()
    _sensor_channels = ()

    def on_activate(self):
        """Initialize the Fluigent SDK and check configured channels."""

        self._sdk = self.sdk()
        self._pressure_channels = self._normalize_channel_ids(self._pressure_channel_ids)
        self._sensor_channels = self._normalize_channel_ids(self._sensor_channel_ids)

        try:
            self._validate_configured_channels()
        except Exception:
            self._sdk = None
            self._pressure_channels = ()
            self._sensor_channels = ()
            raise

        self.log.info(
            "Fluigent flowboard adapter activated with pressure channels "
            f"{self._pressure_channels} and sensor channels "
            f"{self._sensor_channels}."
        )

    def on_deactivate(self):
        """Close the Fluigent SDK connection."""
        self._sdk = None
        self._pressure_channels = ()
        self._sensor_channels = ()

    # Pressure channels
    def set_pressure(self, param_dict: Dict[int, float]) -> None:
        sdk = self._require_sdk()

        for channel, pressure in param_dict.items():
            channel = int(channel)

            if channel not in self._pressure_channels:
                raise ValueError(
                    f"Pressure channel {channel} is not configured."
                )

            sdk.set_pressure(channel, float(pressure))

    def get_pressure(self,param_list: Optional[List[int]] = None,) -> Dict[int, float]:
        sdk = self._require_sdk()
        channels = self._selected_pressure_channels(param_list)

        return {
            channel: sdk.get_pressure(channel)
            for channel in channels
        }

    # Sensor channels
    def get_flowrate(self, param_list: Optional[List[int]] = None) -> Dict[int, float]:
        sdk = self._require_sdk()
        channels = self._selected_sensor_channels(param_list)

        return {
            channel: sdk.get_flowrate(channel)
            for channel in channels
        }

    # helper private functions
    def _require_sdk(self) -> FluigentSdkInterface:
        """Return the connected SDK backend or raise if unavailable."""
        if self._sdk is None:
            raise RuntimeError(
                "The Fluigent SDK backend is not connected."
            )
        return self._sdk

    @staticmethod
    def _normalize_channel_ids(channel_ids: Sequence[int]) -> Tuple[int, ...]:
        """Normalize channel IDs and reject duplicates."""
        normalized = tuple(int(channel_id) for channel_id in channel_ids)
        if len(normalized) != len(set(normalized)):
            raise ValueError(f"Duplicate Fluigent channel IDs: {normalized}.")

        return normalized

    def _validate_configured_channels(self) -> None:
        """Check configured channels against channels exposed by the SDK."""
        sdk = self._require_sdk()
        available_pressure = tuple(sdk.get_pressure_channel_ids())
        available_sensors = tuple(sdk.get_sensor_channel_ids())

        missing_pressure = [
            channel
            for channel in self._pressure_channels
            if channel not in available_pressure
        ]
        missing_sensors = [
            channel
            for channel in self._sensor_channels
            if channel not in available_sensors
        ]

        if missing_pressure:
            raise ValueError(
                f"Configured pressure channels {missing_pressure} are not "
                f"available. Available channels: {available_pressure}."
            )
        if missing_sensors:
            raise ValueError(
                f"Configured sensor channels {missing_sensors} are not "
                f"available. Available channels: {available_sensors}."
            )

    def _selected_pressure_channels(self,channels: Optional[Sequence[int]],) -> Tuple[int, ...]:
        return self._selected_channels(channels, self._pressure_channels,"pressure")

    def _selected_sensor_channels(self,channels: Optional[Sequence[int]],) -> Tuple[int, ...]:
        return self._selected_channels(channels, self._sensor_channels,"sensor")

    @staticmethod
    def _selected_channels(channels: Optional[Sequence[int]], configured_channels: Tuple[int, ...],
        channel_type: str,) -> Tuple[int, ...]:

        if channels is None:
            return configured_channels

        if isinstance(channels, int):
            requested_channels = (int(channels),)
        else:
            requested_channels = tuple(
                int(channel)
                for channel in channels
            )

        unknown_channels = [
            channel
            for channel in requested_channels
            if channel not in configured_channels
        ]
    
        if unknown_channels:
            raise ValueError(
                f"{channel_type.capitalize()} channels {unknown_channels} "
                f"are not configured. Configured channels: "
                f"{configured_channels}."
            )

        return requested_channels

