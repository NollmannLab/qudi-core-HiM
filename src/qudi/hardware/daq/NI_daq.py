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

        self._tasks = {}
        self._channel_data = {}
        self._ao_voltage_ranges = {}

        for task_name, ao_spec in dict(self._ao_channels).items():
            channel, voltage_range = ao_spec
            self._tasks[task_name] = self.create_taskhandle()
            self.set_up_ao_channel(self._tasks[task_name], channel, voltage_range)
            self._ao_voltage_ranges[task_name] = tuple(voltage_range)
            self._channel_data[task_name] = 0.0

        for task_name, ai_spec in dict(self._ai_channels).items():
            channel, voltage_range = ai_spec
            self._tasks[task_name] = self.create_taskhandle()
            self.set_up_ai_channel(self._tasks[task_name], channel, voltage_range)
            self._channel_data[task_name] = 0.0

        for task_name, channel in dict(self._do_channels).items():
            self._tasks[task_name] = self.create_taskhandle()
            self.set_up_do_channel(self._tasks[task_name], channel)
            self._channel_data[task_name] = np.uint8(0)

        for task_name, channel in dict(self._di_channels).items():
            self._tasks[task_name] = self.create_taskhandle()
            self.set_up_di_channel(self._tasks[task_name], channel)
            self._channel_data[task_name] = np.uint8(0)

        self.log.info("NI DAQ activated.")

    def on_deactivate(self):
        """Close all tasks and release the internal task registry."""
        for task_name, taskhandle in list(self._tasks.items()):
            try:
                self.close_task(taskhandle)
            except Exception as exc:
                self.log.warning(f"Could not close DAQ task '{task_name}': {exc}")
        self._tasks = {}
        self._channel_data = {}
        self._ao_voltage_ranges = {}

    def get_taskhandle(self, task_name):
        """Return the DAQ task handle registered under ``task_name``."""
        if task_name not in self._tasks:
            raise KeyError(f"Unknown DAQ task '{task_name}'.")
        return self._tasks[task_name]

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

    @staticmethod
    def set_up_do_channel(taskhandle, channel):
        """Create and configure one digital-output virtual channel."""
        daq.DAQmxCreateTask('DigitalOut', daq.byref(taskhandle))
        daq.DAQmxCreateDOChan(taskhandle, channel, '', daq.DAQmx_Val_ChanForAllLines)

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

    @staticmethod
    def set_up_di_channel(taskhandle, channel):
        """Create and configure one digital-input virtual channel."""
        daq.DAQmxCreateTask('DigitalIn', daq.byref(taskhandle))
        daq.DAQmxCreateDIChan(taskhandle, channel, '', daq.DAQmx_Val_ChanPerLine)

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

    @staticmethod
    def close_task(taskhandle):
        """Stop and clear a DAQ task, then reset the handle to ``None``."""
        daq.DAQmxStopTask(taskhandle)
        daq.DAQmxClearTask(taskhandle)
        taskhandle.value = None

    def write_named_ao(self, task_name, voltage):
        """Write a scalar voltage to the named analog-output task."""
        self._channel_data[task_name] = float(voltage)
        self.write_to_ao_channel(
            self.get_taskhandle(task_name),
            voltage,
            self._ao_voltage_ranges.get(task_name, self._ao_voltage_range),
        )

    def read_named_ai(self, task_name):
        """Read and cache the latest scalar voltage from the named AI task."""
        value = self.read_ai_channel(self.get_taskhandle(task_name))
        self._channel_data[task_name] = float(value)
        return value

    def write_named_do(self, task_name, value):
        """Write a single digital value to the named DO task."""
        digital_value = np.array([np.uint8(value)], dtype=np.uint8)
        self._channel_data[task_name] = np.uint8(value)
        return self.write_to_do_channel(self.get_taskhandle(task_name), 1, digital_value)

    def read_named_di(self, task_name, num_samp=1):
        """Read and cache one or more digital values from the named DI task."""
        value = self.read_di_channel(self.get_taskhandle(task_name), num_samp)
        self._channel_data[task_name] = value
        return value

    def pulse_named_do(self, task_name, low=0, high=1, pulse_time=0.001):
        """Emit a low-high-low pulse on the named DO task."""
        self.write_named_do(task_name, low)
        sleep(pulse_time)
        self.write_named_do(task_name, high)
        sleep(pulse_time)
        self.write_named_do(task_name, low)
