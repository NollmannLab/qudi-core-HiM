# -*- coding: utf-8 -*-
"""
Interface for microfluidics controllers used by qudi-core-HiM.
"""

from abc import abstractmethod

from qudi.core.module import Base


class FluidicsInterface(Base):
    """Interface for hardware controlling pressure and flowrate channels."""

    @abstractmethod
    def set_pressure(self, param_dict):
        """Set pressure values on pressure channels.

        Args:
            param_dict: Mapping of ``{pressure_channel_id: pressure_setpoint}``.
        """
        pass

    @abstractmethod
    def get_pressure(self, param_list=None):
        """Return pressure values for selected or all pressure channels."""
        pass

    @abstractmethod
    def get_pressure_unit(self, param_list=None):
        """Return pressure units for selected or all pressure channels."""
        pass

    @abstractmethod
    def get_pressure_range(self, param_list=None):
        """Return pressure ranges for selected or all pressure channels."""
        pass

    @abstractmethod
    def get_flowrate(self, param_list=None):
        """Return flowrate values for selected or all sensor channels."""
        pass

    @abstractmethod
    def get_sensor_unit(self, param_list=None):
        """Return sensor units for selected or all sensor channels."""
        pass

    @abstractmethod
    def get_sensor_range(self, param_list=None):
        """Return sensor ranges for selected or all sensor channels."""
        pass
