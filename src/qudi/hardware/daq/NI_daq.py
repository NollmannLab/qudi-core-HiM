# -*- coding: utf-8 -*-
"""
Author: F Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2020-06-30 -> refactored on 2026-07-16

Generic National Instruments DAQ hardware driver for qudi-core.

This module intentionally contains only low-level DAQ operations:
- create and close tasks
- configure AI/AO/DI/DO channels
- read and write scalar values

Higher-level experiment behavior such as laser control, piezo motion, trigger
sequences, or pump control are defined as interfuse hardware instruments.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from time import sleep
import PyDAQmx as daq
import numpy as np

from qudi.core.configoption import ConfigOption
from qudi.interface.daq_interface import DaqInterface


class NIDAQ(DaqInterface):
    """Generic NI DAQ hardware driver.

    The driver exposes only low-level DAQ functionality. It does not encode
    experiment semantics such as laser control, pump logic, or trigger
    sequencing. Those belong in logic modules.

    Configuration expects named channel mappings so the logic layer can refer
    to channels semantically instead of hard-coding physical NI channel strings.
    Example:

    code-block:: yaml

        nidaq:
           module.Class: 'daq.NI_daq.NIDAQ'
           options:
               read_write_timeout: 10

          ao_channels:
              piezo_write:
                - '/Dev1/AO1'
                - [0, 10]
              pump_write:
                - '/Dev1/AO0'
                - [0, 10]

          ai_channels:
              piezo_read:
                - '/Dev1/AI0'
                - [0, 10]

          do_channels:
              start_acquisition: '/Dev1/port0/line7'

          di_channels:
              acquisition_done: '/Dev1/port0/line8'
    """

    _rw_timeout = ConfigOption("read_write_timeout", default=10)
    _ao_channels = ConfigOption("ao_channels", default={})
    _ai_channels = ConfigOption("ai_channels", default={})
    _do_channels = ConfigOption("do_channels", default={})
    _di_channels = ConfigOption("di_channels", default={})

    def on_activate(self):
        """Create and configure all tasks declared in the configuration."""
        if daq is None:
            raise RuntimeError("PyDAQmx is not available on this system.")

        self._reset_task_registry()

        if self._ao_channels:
            self._register_channels(self._ao_channels, channel_type="ao", default_value=0.0)

        if self._ai_channels:
            self._register_channels(self._ai_channels, channel_type="ai", default_value=0.0)

        if self._do_channels:
            self._register_channels(self._do_channels, channel_type="do", default_value=np.uint8(0))

        if self._di_channels:
            self._register_channels(self._di_channels, channel_type="di", default_value=np.uint8(0))

        self.log.info("NI DAQ activated.")

    def on_deactivate(self):
        """Close all tasks and release the internal task registry."""
        for task_name, task in list(self._tasks.items()):
            try:
                self.close_task(task["task_handle"])
            except Exception as exc:
                self.log.warning(f"Could not close DAQ task '{task_name}': {exc}")

        self._reset_task_registry()
        self.log.info("NI DAQ deactivated.")

    # ------------------------------------------------------------------------------------------------------------------
    # private methods handling tasks
    # ------------------------------------------------------------------------------------------------------------------

    def _reset_task_registry(self):
        """Create a fresh in-memory registry for all configured tasks."""
        self._tasks = {}
        self._channel_data = {}

    def _register_channels(self, channel_map, channel_type, default_value):
        """Register configured channels in the NI-DAQ task registry.

        Args:
            channel_map (dict): Mapping of task name to physical channel string.
            channel_type (str): One of ``ao``, ``ai``, ``do`` or ``di``.
            default_value: Initial value cached for the task.
        """
        for task_name, spec in dict(channel_map).items():
            if channel_type in {"ao", "ai"}:
                channel, voltage_range = spec
            else:
                channel = spec
                voltage_range = None

            taskhandle = self.create_taskhandle()

            # Configure the physical NI channel
            if channel_type == "ao":
                self.set_up_ao_channel(taskhandle, channel, voltage_range)
            elif channel_type == "ai":
                self.set_up_ai_channel(taskhandle, channel, voltage_range)
            elif channel_type == "do":
                self.set_up_do_channel(taskhandle, channel)
            elif channel_type == "di":
                self.set_up_di_channel(taskhandle, channel)
            else:
                self.log.error( f"Unknown DAQ channel type: {channel_type!r}")

            # Register metadata
            self._tasks[task_name] = {
                "task_handle": taskhandle,
                "task_name": task_name,
                "channel": channel,
                "type": channel_type,
            }

            if channel_type in {"ao", "ai"}:
                self._tasks[task_name]["voltage_range"] = tuple(voltage_range)
            self._channel_data[task_name] = default_value

    def _get_task(self, task_name):
        """Return the stored task metadata for ``task_name``."""
        if task_name not in self._tasks:
            raise KeyError(f"Unknown DAQ task '{task_name}'.")
        return self._tasks[task_name]

    def _get_task_name_from_handle(self, taskhandle):
        """Return the task name associated with ``taskhandle``."""
        for task_name, task in self._tasks.items():
            if task["task_handle"] is taskhandle:
                return task_name
        raise RuntimeError("Error: No task handle specified.")

    # ------------------------------------------------------------------------------------------------------------------
    # callable methods to get task properties
    # ------------------------------------------------------------------------------------------------------------------

    def get_taskhandle(self, task_name):
        """Return the NI-DAQ task handle for ``task_name``."""
        if task_name not in self._tasks:
            raise KeyError(f"Unknown DAQ task '{task_name}'.")
        return self._tasks[task_name]["task_handle"]

    def get_task_range(self, task_name):
        """Return the task range for ``task_name``, if task is associated to an analog channel."""
        if task_name not in self._tasks:
            raise KeyError(f"Unknown DAQ task '{task_name}'.")

        task = self._tasks[task_name]
        if task["type"] == "ao":
            return task["voltage_range"]
        else:
            return None

    # ------------------------------------------------------------------------------------------------------------------
    # create and close tasks
    # ------------------------------------------------------------------------------------------------------------------

    @staticmethod
    def create_taskhandle():
        """Create a new DAQmx task handle.

        The helper mirrors the legacy code style so the setup methods can stay
        close to the original PyDAQmx usage.
        """
        taskhandle = daq.TaskHandle()
        if taskhandle.value is not None:
            daq.DAQmxStopTask(taskhandle)
            daq.DAQmxClearTask(taskhandle)
            taskhandle.value = None
        return taskhandle

    @staticmethod
    def close_task(taskhandle):
        """Stop and clear a DAQ task, then reset the handle to ``None``."""
        daq.DAQmxStopTask(taskhandle)
        daq.DAQmxClearTask(taskhandle)
        taskhandle.value = None

    @staticmethod
    def set_up_ao_channel(taskhandle, channel, voltage_range):
        """Create and configure one analog-output virtual channel."""
        daq.DAQmxCreateTask('', daq.byref(taskhandle))
        daq.DAQmxCreateAOVoltageChan(
            taskhandle,
            channel,
            '',
            voltage_range[0],
            voltage_range[1],
            daq.DAQmx_Val_Volts,
            None,
        )

    @staticmethod
    def set_up_ai_channel(taskhandle, channel, voltage_range):
        """Create and configure one analog-input virtual channel."""
        daq.DAQmxCreateTask('', daq.byref(taskhandle))
        daq.DAQmxCreateAIVoltageChan(
            taskhandle,
            channel,
            '',
            daq.DAQmx_Val_RSE,
            voltage_range[0],
            voltage_range[1],
            daq.DAQmx_Val_Volts,
            None,
        )

    @staticmethod
    def set_up_do_channel(taskhandle, channel):
        """Create and configure one digital-output virtual channel."""
        daq.DAQmxCreateTask('DigitalOut', daq.byref(taskhandle))
        daq.DAQmxCreateDOChan(taskhandle, channel, '', daq.DAQmx_Val_ChanForAllLines)

    @staticmethod
    def set_up_di_channel(taskhandle, channel):
        """Create and configure one digital-input virtual channel."""
        daq.DAQmxCreateTask('DigitalIn', daq.byref(taskhandle))
        daq.DAQmxCreateDIChan(taskhandle, channel, '', daq.DAQmx_Val_ChanPerLine)

    # ------------------------------------------------------------------------------------------------------------------
    # read / write tasks
    # ------------------------------------------------------------------------------------------------------------------

    def write_to_ao_channel(self, taskhandle, voltage, voltage_range=None, timeout=None, autostart=True):
        """Write a scalar voltage to an analog-output task."""
        if timeout is None:
            timeout = self._rw_timeout
        if voltage_range is not None:
            min_voltage, max_voltage = voltage_range
            if not (min_voltage <= float(voltage) <= max_voltage):
                raise ValueError(
                    f"AO voltage {voltage} V is outside the allowed range "
                    f"[{min_voltage}, {max_voltage}] V."
                )

        daq.WriteAnalogScalarF64(taskhandle, autostart, timeout, float(voltage), None)
        daq.DAQmxStartTask(taskhandle)
        daq.DAQmxStopTask(taskhandle)

    def read_ai_channel(self, taskhandle):
        """Read one scalar voltage from an analog-input task."""
        data = np.zeros((1,), dtype=np.float64)
        read = daq.c_int32()
        daq.DAQmxStartTask(taskhandle)
        daq.DAQmxReadAnalogF64(
            taskhandle,
            1,
            self._rw_timeout,
            daq.DAQmx_Val_GroupByChannel,
            data,
            1,
            daq.byref(read),
            None,
        )
        daq.DAQmxStopTask(taskhandle)
        return float(data[0])

    def write_to_do_channel(self, taskhandle, num_samp, digital_write):
        """Write one or more digital values to a digital-output task."""
        num_samples_per_channel = daq.c_int32(num_samp)
        digital_read = daq.c_int32()
        daq.DAQmxStartTask(taskhandle)
        daq.DAQmxWriteDigitalLines(
            taskhandle,
            num_samples_per_channel,
            True,
            self._rw_timeout,
            daq.DAQmx_Val_GroupByChannel,
            digital_write,
            daq.byref(digital_read),
            None,
        )
        daq.DAQmxStopTask(taskhandle)
        return digital_read

    def read_di_channel(self, taskhandle, num_samp):
        """Read one or more digital values from a digital-input task."""
        num_samples_per_channel = daq.c_int32(num_samp)
        samps_per_chan_read = daq.c_int32()
        num_bytes_per_samp = daq.c_int32()
        data = np.zeros((num_samp,), dtype=np.uint8)
        daq.DAQmxStartTask(taskhandle)
        daq.DAQmxReadDigitalLines(
            taskhandle,
            num_samples_per_channel,
            self._rw_timeout,
            daq.DAQmx_Val_GroupByChannel,
            data,
            num_samp,
            samps_per_chan_read,
            num_bytes_per_samp,
            None,
        )
        daq.DAQmxStopTask(taskhandle)
        return data

    def write_named_ao(self, task_name, voltage):
        """Write a scalar voltage to the named analog-output task."""
        task = self._get_task(task_name)
        return self.write_to_ao_channel(
            task["task_handle"],
            voltage,
            task.get("voltage_range"),
        )

    def read_named_ai(self, task_name):
        """Read and cache the latest scalar voltage from the named AI task."""
        task = self._get_task(task_name)
        value = float(self.read_ai_channel(task["task_handle"]))
        self._channel_data[task_name] = value
        return value

    def write_named_do(self, task_name, value):
        """Write a single digital value to the named DO task."""
        digital_value = np.array([np.uint8(value)], dtype=np.uint8)
        task = self._get_task(task_name)
        self._channel_data[task_name] = np.uint8(value)
        return self.write_to_do_channel(task["task_handle"], 1, digital_value)

    def read_named_di(self, task_name, num_samp=1):
        """Read and cache one or more digital values from the named DI task."""
        task = self._get_task(task_name)
        value = self.read_di_channel(task["task_handle"], num_samp)
        self._channel_data[task_name] = value
        return value

    def pulse_named_do(self, task_name, low=0, high=1, pulse_time=0.001):
        """Emit a low-high-low pulse on the named DO task."""
        self.write_named_do(task_name, low)
        sleep(pulse_time)
        self.write_named_do(task_name, high)
        sleep(pulse_time)
        self.write_named_do(task_name, low)
