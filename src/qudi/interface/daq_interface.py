# -*- coding: utf-8 -*-
"""
Interface for generic DAQ hardware used by qudi-core-HiM.

The interface intentionally exposes only low-level DAQ primitives. Higher-level
experiment semantics such as trigger sequences, laser control, piezo motion, or
pump control should be implemented in logic modules on top of this interface.
"""

from abc import abstractmethod

from qudi.core.module import Base


class DaqInterface(Base):
    """Interface for hardware providing generic DAQ read/write capabilities."""

    @abstractmethod
    def get_taskhandle(self, task_name):
        """Return the task handle associated with a configured task name."""
        pass

    @abstractmethod
    def write_to_ao_channel(self, taskhandle, voltage, timeout=None, autostart=True):
        """Write a scalar voltage to an analog-output channel."""
        pass

    @abstractmethod
    def read_ai_channel(self, taskhandle):
        """Read a scalar voltage from an analog-input channel."""
        pass

    @abstractmethod
    def write_to_do_channel(self, taskhandle, num_samp, digital_write):
        """Write one or more digital values to a digital-output channel."""
        pass

    @abstractmethod
    def read_di_channel(self, taskhandle, num_samp):
        """Read one or more digital values from a digital-input channel."""
        pass

    @abstractmethod
    def write_named_ao(self, task_name, voltage):
        """Write a voltage to the configured analog-output task."""
        pass

    @abstractmethod
    def read_named_ai(self, task_name):
        """Read a voltage from the configured analog-input task."""
        pass

    @abstractmethod
    def write_named_do(self, task_name, value):
        """Write a digital value to the configured digital-output task."""
        pass

    @abstractmethod
    def read_named_di(self, task_name, num_samp=1):
        """Read digital values from the configured digital-input task."""
        pass

    @abstractmethod
    def pulse_named_do(self, task_name, low=0, high=1, pulse_time=0.001):
        """Emit a low-high-low pulse on the configured digital-output task."""
        pass
