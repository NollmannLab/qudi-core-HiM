# -*- coding: utf-8 -*-

from abc import abstractmethod
from typing import Any, Dict, Tuple

from qudi.core.module import Base


class FluigentSdkInterface(Base):
    """Low-level interface to one initialized Fluigent SDK instance.

    This interface exposes raw Fluigent pressure and flow-sensor capabilities.
    It does not implement PID regulation, volume integration, semantic channel
    names, or experiment-level fluid-delivery operations.
    """

    @abstractmethod
    def get_pressure_channel_ids(self) -> Tuple[int, ...]:
        """Return the pressure-channel IDs exposed by the SDK."""
        pass

    @abstractmethod
    def get_sensor_channel_ids(self) -> Tuple[int, ...]:
        """Return the sensor-channel IDs exposed by the SDK."""
        pass

    @abstractmethod
    def get_pressure_channel_info(self, channel: int) -> Dict[str, Any]:
        """Return range and unit information for one pressure channel."""
        pass

    @abstractmethod
    def get_sensor_channel_info(self, channel: int) -> Dict[str, Any]:
        """Return range and unit information for one sensor channel."""
        pass

    @abstractmethod
    def set_pressure(self, channel: int, pressure: float) -> None:
        """Set the pressure of one Fluigent pressure channel."""
        pass

    @abstractmethod
    def get_pressure(self, channel: int) -> float:
        """Read the pressure of one Fluigent pressure channel."""
        pass

    @abstractmethod
    def get_flowrate(self, channel: int) -> float:
        """Read the flow rate of one Fluigent sensor channel."""
        pass