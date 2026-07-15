# -*- coding: utf-8 -*-
"""
Interface for fluidics valve positioners.
"""

from abc import abstractmethod

from qudi.core.module import Base


class ValvePositionerInterface(Base):
    """Interface for hardware controlling one or more valve positioners."""

    @abstractmethod
    def get_valve_dict(self):
        """Return metadata for all available valves indexed by valve address."""
        pass

    @abstractmethod
    def get_status(self):
        """Return status values for all available valves."""
        pass

    @abstractmethod
    def get_valve_position(self, valve_address):
        """Return the current position of one valve."""
        pass

    @abstractmethod
    def set_valve_position(self, valve_address, target_position):
        """Move one valve to a target position."""
        pass

    @abstractmethod
    def wait_for_idle(self, poll_interval=0.2):
        """Wait until all valves are idle."""
        pass
