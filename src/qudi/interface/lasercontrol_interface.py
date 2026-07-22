# -*- coding: utf-8 -*-
"""
Interface for laser control modules used by qudi-core-HiM.

This interface exposes the minimal contract required by the laser-control
logic and interfuse layers:

- provide a metadata dictionary describing available laser channels
- apply a control value to one selected laser channel
- switch all laser channels off
"""

from abc import abstractmethod

from qudi.core.module import Base


class LasercontrolInterface(Base):
    """Interface for hardware or interfuse modules controlling lasers."""

    @abstractmethod
    def get_dict(self):
        """Return metadata for the available laser channels."""
        pass

    @abstractmethod
    def apply_voltage(self, voltage, channel):
        """Apply a control voltage/value to one laser channel."""
        pass

    @abstractmethod
    def disable_all(self):
        """Set all laser outputs to a safe inactive state."""
        pass
