# -*- coding: utf-8 -*-
"""
Author: F Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2026-07-15

Qudi-core-HiM hardware module for a Fluigent flow sensor.

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
from typing import Dict, Optional, Sequence, Tuple

from qudi.core.connector import Connector
from qudi.interface.flow_sensor_interface import FlowSensorInterface
from qudi.core.configoption import ConfigOption
from qudi.interface.fluigent_sdk_interface import FluigentSdkInterface


class FluigentFlowSensor(FlowSensorInterface):
    """Hardware class representing a Fluigent microfluidics controller.

    Example config:

      fluigent_flow_sensor:
        module.Class: 'interfuse_hardware.fluigent_flow_sensor.FluigentFlowSensor'
        connect:
          sdk: 'fluigent_sdk'
        options:
          sensor_channel_IDs:
            - 0
    """

    _sensor_channel_ids = ConfigOption("sensor_channel_IDs", missing="error")
    _sensor_unit = ConfigOption("unit", missing="error")
    sdk = Connector(interface="FluigentSdkInterface", name="sdk")

    _sdk = None
    _sensor_channels = ()

    def on_activate(self):
        """Initialize the Fluigent SDK and verify the configured channels.

        The configured sensor channels are normalized and checked against the
        connected SDK backend before the module is considered active.
        """

        self._sdk = self.sdk()
        self._sensor_channels = self._normalize_channel_ids(self._sensor_channel_ids)

        try:
            self._validate_configured_channels()
        except Exception:
            self._sdk = None
            self._sensor_channels = ()
            raise

        self.log.info(
            "Fluigent flowboard adapter activated with sensor channels {self._sensor_channels}.")

    def on_deactivate(self):
        """Reset the cached SDK backend and configured sensor channel list."""
        self._sdk = None
        self._sensor_channels = ()

    # Sensor channels
    def get_flowrate(
        self,
        param_list: Optional[Sequence[int]] = None,
    ) -> Dict[int, float]:
        """Read flowrate values from configured sensor channels.

        Args:
            param_list: Optional sequence of configured sensor channels to
                read, or a single channel ID. If ``None``, the method reads
                all configured sensor channels.

        Returns:
            A mapping of ``{sensor_channel_id: flowrate_value}`` for the
            selected channels.

        Raises:
            RuntimeError: If the Fluigent SDK backend is not connected.
            ValueError: If one of the requested channels is not configured.
        """
        sdk = self._require_sdk()
        channels = self._selected_sensor_channels(param_list)

        return {
            channel: sdk.get_flowrate(channel)
            for channel in channels
        }

    def get_sensor_unit(
        self,
        param_list: Optional[Sequence[int]] = None,
    ) -> Dict[int, str]:
        """Return the configured unit for selected sensor channels.

        Args:
            param_list: Optional sequence of configured sensor channels to
                query, or a single channel ID. If ``None``, the method returns
                the unit for all configured sensor channels.

        Returns:
            A mapping of ``{sensor_channel_id: unit_string}`` for the selected
            channels.

        Raises:
            ValueError: If one of the requested channels is not configured.
        """
        channels = self._selected_sensor_channels(param_list)

        return {
            channel: self._sensor_unit
            for channel in channels
        }

    # helper private functions
    def _require_sdk(self) -> FluigentSdkInterface:
        """Return the connected SDK backend.

        Raises:
            RuntimeError: If the Fluigent SDK backend is not connected.
        """
        if self._sdk is None:
            raise RuntimeError(
                "The Fluigent SDK backend is not connected."
            )
        return self._sdk

    @staticmethod
    def _normalize_channel_ids(channel_ids: Sequence[int]) -> Tuple[int, ...]:
        """Normalize channel IDs and reject duplicates.

        Args:
            channel_ids: Sequence of configured channel identifiers.

        Returns:
            A tuple of normalized integer channel IDs.

        Raises:
            ValueError: If duplicate channel IDs are provided.
        """
        normalized = tuple(int(channel_id) for channel_id in channel_ids)
        if len(normalized) != len(set(normalized)):
            raise ValueError(f"Duplicate Fluigent channel IDs: {normalized}.")

        return normalized

    def _validate_configured_channels(self) -> None:
        """Check configured channels against sensor channels exposed by the SDK.

        Raises:
            ValueError: If one or more configured sensor channels are not
                available on the connected Fluigent backend.
        """
        sdk = self._require_sdk()
        available_sensors = tuple(sdk.get_sensor_channel_ids())

        missing_sensors = [
            channel
            for channel in self._sensor_channels
            if channel not in available_sensors
        ]

        if missing_sensors:
            raise ValueError(
                f"Configured sensor channels {missing_sensors} are not "
                f"available. Available channels: {available_sensors}."
            )

    def _selected_sensor_channels(
        self,
        channels: Optional[Sequence[int]],
    ) -> Tuple[int, ...]:
        """Resolve requested sensor channels against configured channels.

        Args:
            channels: Optional sequence of requested sensor channels, or a
                single channel ID. If ``None``, all configured sensor channels
                are returned.

        Returns:
            The requested sensor channels, normalized to integers.

        Raises:
            ValueError: If one of the requested channels is not configured.
        """
        return self._selected_channels(channels, self._sensor_channels, "sensor")

    @staticmethod
    def _selected_channels(
        channels: Optional[Sequence[int]],
        configured_channels: Tuple[int, ...],
        channel_type: str,
    ) -> Tuple[int, ...]:
        """Resolve requested channels against a configured channel set.

        Args:
            channels: Optional sequence of requested channel identifiers, or a
                single channel ID. If ``None``, all configured channels are
                returned.
            configured_channels: Tuple of channel identifiers that are
                configured for this device.
            channel_type: Human-readable channel label used in error messages.

        Returns:
            The requested channels, normalized to integers.

        Raises:
            ValueError: If one of the requested channels is not configured.
        """

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
