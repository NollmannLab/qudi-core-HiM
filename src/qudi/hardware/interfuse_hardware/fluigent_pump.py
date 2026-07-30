# -*- coding: utf-8 -*-
"""
Author: JB Fiche - adapted for qudi-core-HiM by JB Fiche
Created: 2026-07-29

Qudi-core-HiM hardware module for a Fluigent pump.

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

from typing import Dict, Optional, Sequence, Tuple, Any

from qudi.core.connector import Connector

from qudi.hardware.fluidics.fluigent_sdk import FluigentSDK
from qudi.interface.pump_interface import PumpInterface
from qudi.core.configoption import ConfigOption


class FluigentPump(PumpInterface):
    """Hardware class representing a Fluigent microfluidics controller.

    Example config:

      fluigent_pump:
        module.Class: 'interfuse_hardware.fluigent_pump.FluigentPump'
        connect:
          sdk: 'fluigent_sdk'
        options:
          kind: "pressure"
          unit: "mbar"
          minimum: 0.0
          maximum: 50.0
          pressure_channel_IDs:
            - 0
    """

    _pressure_channel_ids = ConfigOption("pressure_channel_IDs", missing="error")
    _pump_kind = ConfigOption("kind", missing="error")
    _pump_unit = ConfigOption("unit", missing="error")
    _pressure_minimum = ConfigOption("minimum", missing="error")
    _pressure_maximum = ConfigOption("maximum", missing="error")
    sdk = Connector(interface="FluigentSdkInterface", name="sdk")

    _sdk = None
    _pressure_channels = ()

    def on_activate(self):
        """Initialize the Fluigent SDK and verify the configured channels.

        The configured pressure channels are normalized and checked against the
        connected SDK backend before the module is marked ready.
        """

        self._sdk = self.sdk()
        self._pressure_channels = self._normalize_channel_ids(self._pressure_channel_ids)

        try:
            self._validate_configured_channels()
        except Exception:
            self._sdk = None
            self._pressure_channels = ()
            raise

        self.log.info(
            "Fluigent flowboard adapter activated with pressure channels "
            f"{self._pressure_channels}."
        )

    def on_deactivate(self):
        """Reset the cached SDK backend and configured channel list."""
        self._sdk = None
        self._pressure_channels = ()

    # Pressure channels
    def set_output(self, param_dict: Dict[int, float]) -> None:
        """Set pressure values on configured pressure channels.

        Args:
            param_dict: Mapping of ``{pressure_channel_id: pressure_setpoint}``.
                Channel IDs are coerced to ``int`` and pressure values are
                coerced to ``float`` before they are sent to the SDK. The
                requested pressure must stay within the configured minimum and
                maximum values.

        Raises:
            RuntimeError: If the Fluigent SDK backend is not connected.
            ValueError: If one of the requested channels is not configured.
            ValueError: If a pressure setpoint is outside the configured
                range.
        """
        sdk = self._require_sdk()

        for channel, pressure in param_dict.items():
            channel = int(channel)

            if channel not in self._pressure_channels:
                raise ValueError(f"Pressure channel {channel} is not configured.")
            if self._pressure_minimum <= pressure <= self._pressure_maximum:
                sdk.set_pressure(channel, float(pressure))
            else:
                raise ValueError(f"Pressure setpoint outside of min/max range defined in config.")

    def get_output(self, param_list: Optional[Sequence[int]] = None) -> Dict[int, float]:
        """Read pressure values from configured pressure channels.

        Args:
            param_list: Optional sequence of configured pressure channels to
                read, or a single channel ID. If ``None``, the method reads
                all configured pressure channels.

        Returns:
            A mapping of ``{pressure_channel_id: pressure_value}`` for the
            selected channels.

        Raises:
            RuntimeError: If the Fluigent SDK backend is not connected.
            ValueError: If one of the requested channels is not configured.
        """
        sdk = self._require_sdk()
        channels = self._selected_pressure_channels(param_list)

        return {
            channel: sdk.get_pressure(channel)
            for channel in channels
        }

    def stop(self):
        """Stop all configured pressure channels by setting them to minimum."""
        for channel in self._pressure_channels:
            self.set_output({channel: self._pressure_minimum})

    def get_constraints(self) -> Dict[str, Any]:
        """Return native pump-output constraints.

        Returns:
            A mapping with the configured output kind, unit, minimum, and
            maximum pressure values.
        """
        return {
            "kind": self._pump_kind,
            "unit": self._pump_unit,
            "minimum": float(self._pressure_minimum),
            "maximum": float(self._pressure_maximum),
        }

    # helper private functions
    def _require_sdk(self) -> Optional[FluigentSDK]:
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
        """Check configured channels against pressure channels exposed by the SDK.

        Raises:
            ValueError: If one or more configured pressure channels are not
                available on the connected Fluigent backend.
        """
        sdk = self._require_sdk()
        available_pressure = tuple(sdk.get_pressure_channel_ids())

        missing_pressure = [
            channel
            for channel in self._pressure_channels
            if channel not in available_pressure
        ]

        if missing_pressure:
            raise ValueError(
                f"Configured pressure channels {missing_pressure} are not "
                f"available. Available channels: {available_pressure}."
            )

    def _selected_pressure_channels(
        self,
        channels: Optional[Sequence[int]],
    ) -> Tuple[int, ...]:
        """Resolve requested pressure channels against configured channels.

        Args:
            channels: Optional sequence of requested pressure channels, or a
                single channel ID. If ``None``, all configured pressure
                channels are returned.

        Returns:
            The requested pressure channels, normalized to integers.

        Raises:
            ValueError: If one of the requested channels is not configured.
        """
        return self._selected_channels(channels, self._pressure_channels, "pressure")

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
