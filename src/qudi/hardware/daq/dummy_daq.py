# -*- coding: utf-8 -*-
"""
Author: F Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2026-07-16

Dummy implementation of the generic NI DAQ hardware.

This module mirrors the public API of :mod:`qudi.hardware.daq.NI_daq` but keeps
all state in memory. It is intended for GUI and logic testing without connected
DAQ hardware.
"""

from time import sleep

import numpy as np

from qudi.core.configoption import ConfigOption
from qudi.interface.daq_interface import DaqInterface


class DummyDaq(DaqInterface):
    """In-memory DAQ used for development and testing.

    The dummy uses the same named channel configuration as the real hardware
    driver:

    - ``ao_channels``
    - ``ai_channels``
    - ``do_channels``
    - ``di_channels``

    Each mapping associates a semantic task name to a physical channel string.
    In the dummy implementation the physical channel string is stored for
    completeness but not used to communicate with hardware.
    """

    _rw_timeout = ConfigOption("read_write_timeout", default=10)
    _ao_voltage_range = ConfigOption("ao_voltage_range", default=(0, 10))
    _ao_channels = ConfigOption("ao_channels", default={})
    _ai_channels = ConfigOption("ai_channels", default={})
    _do_channels = ConfigOption("do_channels", default={})
    _di_channels = ConfigOption("di_channels", default={})

    def on_activate(self):
        """Populate the dummy task registry from the configured channels."""
        self._tasks = {}
        self._channel_data = {}
        self._channel_metadata = {}

        self._register_channels(self._ao_channels, channel_type="ao", default_value=0.0)
        self._register_channels(self._ai_channels, channel_type="ai", default_value=0.0)
        self._register_channels(self._do_channels, channel_type="do", default_value=np.uint8(0))
        self._register_channels(self._di_channels, channel_type="di", default_value=np.uint8(0))

        self.log.info("Dummy DAQ activated.")

    def on_deactivate(self):
        """Clear the in-memory task registry."""
        self._tasks.clear()
        self._channel_data.clear()
        self._channel_metadata.clear()
        self.log.info("Dummy DAQ deactivated.")

    def _register_channels(self, channel_map, channel_type, default_value):
        """Register configured channels in the dummy task registry.

        Args:
            channel_map (dict): Mapping of task name to physical channel string.
            channel_type (str): One of ``ao``, ``ai``, ``do`` or ``di``.
            default_value: Initial value cached for the task.
        """
        for task_name, channel in dict(channel_map).items():
            self._tasks[task_name] = task_name
            self._channel_metadata[task_name] = {
                "channel": channel,
                "type": channel_type,
            }
            self._channel_data[task_name] = default_value

    def get_taskhandle(self, task_name):
        """Return the dummy task handle for ``task_name``."""
        if task_name not in self._tasks:
            raise KeyError(f"Unknown DAQ task '{task_name}'.")
        return self._tasks[task_name]

    def set_up_ao_channel(self, taskhandle, channel, voltage_range):
        """Store metadata for a dummy analog-output channel."""
        self._channel_metadata[taskhandle] = {
            "channel": channel,
            "type": "ao",
            "voltage_range": tuple(voltage_range),
        }
        self._channel_data[taskhandle] = 0.0

    def write_to_ao_channel(self, taskhandle, voltage, timeout=None, autostart=True):
        """Cache the analog-output voltage in memory."""
        _ = timeout if timeout is not None else self._rw_timeout
        _ = autostart
        self._channel_data[taskhandle] = float(voltage)

    def set_up_ai_channel(self, taskhandle, channel, voltage_range):
        """Store metadata for a dummy analog-input channel."""
        self._channel_metadata[taskhandle] = {
            "channel": channel,
            "type": "ai",
            "voltage_range": tuple(voltage_range),
        }
        self._channel_data[taskhandle] = 0.0

    def read_ai_channel(self, taskhandle):
        """Return the cached analog-input value.

        The dummy returns the last cached value if one has been written. This
        keeps the behavior predictable for logic and GUI testing.
        """
        return float(self._channel_data.get(taskhandle, 0.0))

    def set_up_do_channel(self, taskhandle, channel):
        """Store metadata for a dummy digital-output channel."""
        self._channel_metadata[taskhandle] = {
            "channel": channel,
            "type": "do",
        }
        self._channel_data[taskhandle] = np.uint8(0)

    def write_to_do_channel(self, taskhandle, num_samp, digital_write):
        """Cache the last digital output state."""
        _ = num_samp
        value = np.asarray(digital_write, dtype=np.uint8)
        self._channel_data[taskhandle] = value.copy()
        return value.size

    def set_up_di_channel(self, taskhandle, channel):
        """Store metadata for a dummy digital-input channel."""
        self._channel_metadata[taskhandle] = {
            "channel": channel,
            "type": "di",
        }
        self._channel_data[taskhandle] = np.zeros((1,), dtype=np.uint8)

    def read_di_channel(self, taskhandle, num_samp):
        """Return the cached digital input state."""
        value = self._channel_data.get(taskhandle, np.zeros((num_samp,), dtype=np.uint8))
        return np.asarray(value, dtype=np.uint8)

    def close_task(self, taskhandle):
        """Remove a task and its cached value from the dummy registry."""
        self._channel_data.pop(taskhandle, None)
        self._channel_metadata.pop(taskhandle, None)
        if taskhandle in self._tasks:
            self._tasks.pop(taskhandle, None)

    def write_named_ao(self, task_name, voltage):
        """Write a value to a named dummy analog-output task."""
        self._channel_data[task_name] = float(voltage)

    def read_named_ai(self, task_name):
        """Read a value from a named dummy analog-input task."""
        return float(self._channel_data.get(task_name, 0.0))

    def write_named_do(self, task_name, value):
        """Write a value to a named dummy digital-output task."""
        self._channel_data[task_name] = np.uint8(value)
        return np.uint8(value)

    def read_named_di(self, task_name, num_samp=1):
        """Read a value from a named dummy digital-input task."""
        value = self._channel_data.get(task_name, np.zeros((num_samp,), dtype=np.uint8))
        return np.asarray(value, dtype=np.uint8)

    def pulse_named_do(self, task_name, low=0, high=1, pulse_time=0.001):
        """Simulate a low-high-low pulse on a named digital-output task."""
        self.write_named_do(task_name, low)
        sleep(pulse_time)
        self.write_named_do(task_name, high)
        sleep(pulse_time)
        self.write_named_do(task_name, low)
        return True
