# -*- coding: utf-8 -*-
"""
Author: F Barho - adapted for qudi-core-HiM by JB Fiche with codex
Created: 2021-03-04 -> translated into qudi-core-HiM on 2026-0<è-11
Logic module for pressure and flow-rate control.

This is the qudi-core adaptation of the original HiM flowcontrol logic.  The
logic talks to a hardware module implementing ``FluidicsInterface`` and keeps
GUI-facing signals and method names close to the original module.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from math import inf
from time import sleep

from qtpy import QtCore

from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.core.module import LogicBase
from qudi.core.statusvariable import StatusVar
from simple_pid import PID

# ======================================================================================================================
# Worker classes
# ======================================================================================================================

class WorkerSignals(QtCore.QObject):
    sigFinished = QtCore.Signal()
    sigRegulationWaitFinished = QtCore.Signal(float)
    sigIntegrationIntervalFinished = QtCore.Signal(float)


class WaitWorker(QtCore.QRunnable):
    """Sleeps outside the main thread, then emits a signal."""

    def __init__(self, interval, payload=None):
        """Create a worker that emits a signal after a delay.

        Args:
            interval (float): Wait duration in seconds.
            payload (float | None): Optional value emitted after waiting.
        """
        super().__init__()
        self.signals = WorkerSignals()
        self.interval = float(interval)
        self.payload = payload

    @QtCore.Slot()
    def run(self):
        """Execute the wait operation and emit the completion signal."""
        sleep(self.interval)
        if self.payload is None:
            self.signals.sigFinished.emit()
        else:
            self.signals.sigRegulationWaitFinished.emit(float(self.payload))


class VolumeCountWorker(QtCore.QRunnable):
    """Wait worker for volume integration."""

    def __init__(self, sampling_interval):
        """Create a worker for one volume-integration interval.

        Args:
            sampling_interval (float): Integration interval in seconds.
        """
        super().__init__()
        self.signals = WorkerSignals()
        self.sampling_interval = float(sampling_interval)

    @QtCore.Slot()
    def run(self):
        """Wait for one integration interval and emit its duration."""
        sleep(self.sampling_interval)
        self.signals.sigIntegrationIntervalFinished.emit(self.sampling_interval)

# ======================================================================================================================
# Logic class
# ======================================================================================================================

class FluidicsFlowLogic(LogicBase):
    """Logic class for pressure control, flow monitoring, and volume counting.

    Example config:

      fluidics_flow_logic:
        module.Class: 'fluidics_flow_logic.FluidicsFlowLogic'
        options:
          default_pressure_channel: 0
          default_sensor_channel: 0
        connect:
          flowboard: 'fluigent_flowboard'
    """

    flowboard = Connector(interface="FluidicsInterface", name="flowboard")
    rinsing_pump = Connector(interface="PumpInterface", name="rinsing_pump")

    p_gain = ConfigOption("p_gain", 0.005, missing="warn")
    i_gain = ConfigOption("i_gain", 0.01, missing="warn")
    d_gain = ConfigOption("d_gain", 0.0, missing="warn")
    pid_sample_time = ConfigOption("pid_sample_time", 0.1, missing="warn")
    pid_output_min = ConfigOption("pid_output_min", 0.0, missing="warn")
    pid_output_max = ConfigOption("pid_output_max", 15.0, missing="warn")
    sampling_interval = ConfigOption("sampling_interval", 1.0, missing="warn")
    default_pressure_channel = ConfigOption("default_pressure_channel", 0, missing="warn")
    default_sensor_channel = ConfigOption("default_sensor_channel", 0, missing="warn")

    _latest_pressure = StatusVar(name="_latest_pressure", default=list())
    _latest_flowrate = StatusVar(name="_latest_flowrate", default=list())
    _pressure_setpoint = StatusVar(name="_pressure_setpoint", default=0.0)
    _total_volume = StatusVar(name="_total_volume", default=0.0)
    _time_since_start = StatusVar(name="_time_since_start", default=0.0)

    sigUpdateFlowMeasurement = QtCore.Signal(list, list)
    sigUpdatePressureSetpoint = QtCore.Signal(float)
    sigUpdateVolumeMeasurement = QtCore.Signal(float, float, float, float)
    sigTargetVolumeReached = QtCore.Signal()
    sigRinsingFinished = QtCore.Signal()
    sigDisableFlowActions = QtCore.Signal()
    sigEnableFlowActions = QtCore.Signal()

    measuring_flowrate = False
    regulating = False
    measuring_volume = False
    target_volume = 0.0
    target_volume_reached = True
    rinsing_enabled = False

    def on_activate(self):
        """Connect the flowboard and initialize cached readings."""
        self._flowboard = self.flowboard()
        self.threadpool = QtCore.QThreadPool.globalInstance()
        self.pid = None
        self.set_pressure(0.0)
        self.update_flow_measurement()

    def on_deactivate(self):
        """Stop active loops, reset pressure, and release the flowboard reference."""
        self.stop_flow_measurement()
        self.stop_pressure_regulation_loop()
        self.stop_volume_measurement()
        try:
            self.set_pressure(0.0)
        except Exception as exc:
            self.log.warning(f"Could not reset pressure during deactivation: {exc}")
        self._flowboard = None

    # ----------------------------------------------------------------------------------------------------------------------
    # Low level methods for pressure settings
    # ----------------------------------------------------------------------------------------------------------------------

    @property
    def latest_pressure(self):
        """Return the latest cached pressure values."""
        return list(self._latest_pressure)

    @property
    def pressure_setpoint(self):
        """Return the latest pressure setpoint."""
        return float(self._pressure_setpoint)

    # Pressure API
    def get_pressure(self, channels=None):
        """Read pressure values from the selected channels.

        Args:
            channels (list[int] | int | None): Pressure channels to read. If
                ``None``, all configured channels are read.

        Returns:
            list: Pressure values ordered by channel.
        """
        pressure = self._flowboard.get_pressure(self._normalize_channels(channels))
        values = self._dict_values(pressure)
        self._latest_pressure = values
        return values

    def set_pressure(self, pressures, log_entry=True, channels=None):
        """Set pressure on one or more channels.

        Args:
            pressures (float | list[float]): Pressure setpoint or setpoints.
            log_entry (bool): Whether to log the pressure update.
            channels (list[int] | int | None): Pressure channels to set. If
                ``None``, the default pressure channel is used.
        """
        channels = self._normalize_channels(channels)
        pressure_values = self._normalize_values(pressures)

        if channels is None:
            channels = [int(self.default_pressure_channel)]
        if len(pressure_values) == 1 and len(channels) > 1:
            pressure_values = pressure_values * len(channels)
        if len(pressure_values) != len(channels):
            raise ValueError("Number of pressures must match number of channels.")

        pressure_by_channel = {
            int(channel): float(pressure)
            for channel, pressure in zip(channels, pressure_values)
        }
        self._flowboard.set_pressure(pressure_by_channel)

        if len(pressure_values) == 1:
            self._pressure_setpoint = float(pressure_values[0])
            self.sigUpdatePressureSetpoint.emit(float(pressure_values[0]))
        if log_entry:
            self.log.info(f"Pressure setpoints updated: {pressure_by_channel}")

    def get_pressure_range(self, channels=None):
        """Return pressure ranges for selected channels.

        Args:
            channels (list[int] | int | None): Pressure channels to query. If
                ``None``, all configured channels are queried.

        Returns:
            list: Pressure ranges ordered by channel.
        """
        pressure_range = self._flowboard.get_pressure_range(self._normalize_channels(channels))
        return self._dict_values(pressure_range)

    def get_pressure_unit(self, channels=None):
        """Return pressure units for selected channels.

        Args:
            channels (list[int] | int | None): Pressure channels to query. If
                ``None``, all configured channels are queried.

        Returns:
            list: Pressure unit strings ordered by channel.
        """
        pressure_unit = self._flowboard.get_pressure_unit(self._normalize_channels(channels))
        return self._dict_values(pressure_unit)

    # ----------------------------------------------------------------------------------------------------------------------
    # Low level methods for flowrate measurement
    # ----------------------------------------------------------------------------------------------------------------------

    @property
    def total_volume(self):
        """Return the current integrated volume."""
        return float(self._total_volume)

    @total_volume.setter
    def total_volume(self, value):
        """Cache the current integrated volume.

        Args:
            value (float): Integrated volume.
        """
        self._total_volume = float(value)

    @property
    def time_since_start(self):
        """Return the elapsed volume-counting time in seconds."""
        return float(self._time_since_start)

    @time_since_start.setter
    def time_since_start(self, value):
        """Cache the elapsed volume-counting time.

        Args:
            value (float): Elapsed time in seconds.
        """
        self._time_since_start = float(value)

    @property
    def latest_flowrate(self):
        """Return the latest cached flow-rate values."""
        return list(self._latest_flowrate)

    # Flow-rate API
    def get_flowrate(self, channels=None):
        """Read flow-rate values from selected sensor channels.

        Args:
            channels (list[int] | int | None): Sensor channels to read. If
                ``None``, all configured channels are read.

        Returns:
            list: Flow-rate values ordered by channel.
        """
        flowrate = self._flowboard.get_flowrate(self._normalize_channels(channels))
        values = self._dict_values(flowrate)
        self._latest_flowrate = values
        return values

    def get_flowrate_range(self, channels=None):
        """Return flow-rate ranges for selected sensor channels.

        Args:
            channels (list[int] | int | None): Sensor channels to query. If
                ``None``, all configured channels are queried.

        Returns:
            list: Flow-rate ranges ordered by channel.
        """
        flowrate_range = self._flowboard.get_sensor_range(self._normalize_channels(channels))
        return self._dict_values(flowrate_range)

    def get_flowrate_unit(self, channels=None):
        """Return flow-rate units for selected sensor channels.

        Args:
            channels (list[int] | int | None): Sensor channels to query. If
                ``None``, all configured channels are queried.

        Returns:
            list: Flow-rate unit strings ordered by channel.
        """
        flowrate_unit = self._flowboard.get_sensor_unit(self._normalize_channels(channels))
        return self._dict_values(flowrate_unit)

    # ----------------------------------------------------------------------------------------------------------------------
    # Methods for continuous processes (flowrate measurement loop, pressure regulation loop, volume count, needle rinsing)
    # ----------------------------------------------------------------------------------------------------------------------

    # Flowrate measurement loop --------------------------------------------------------------------------------------------
    def start_flow_measurement(self):
        """Start continuous pressure and flow-rate measurement."""
        if self.measuring_flowrate:
            return
        self.measuring_flowrate = True
        self._schedule_flow_measurement()

    def flow_measurement_loop(self):
        """Read one measurement sample and schedule the next sample if active."""
        self.update_flow_measurement()
        if self.measuring_flowrate:
            self._schedule_flow_measurement()

    def stop_flow_measurement(self):
        """Stop continuous pressure and flow-rate measurement."""
        self.measuring_flowrate = False
        if getattr(self, "_flowboard", None) is not None:
            self.update_flow_measurement()

    def update_flow_measurement(self):
        """Read pressure and flow-rate values and emit an update signal.

        Returns:
            tuple: Pressure values and flow-rate values as two lists.
        """
        pressure = self.get_pressure()
        flowrate = self.get_flowrate()
        self.sigUpdateFlowMeasurement.emit(pressure, flowrate)
        return pressure, flowrate

    # Pressure regulation loop ----------------------------------------------------------------------------------------------

    def init_pid(self, setpoint):
        """Create and configure the PID controller.

        Args:
            setpoint (float): Target flow-rate for pressure regulation.

        Returns:
            PID: Configured PID controller.
        """
        pid = PID(self.p_gain, self.i_gain, self.d_gain, setpoint=setpoint)
        pid.sample_time = self.pid_sample_time
        pid.output_limits = (self.pid_output_min, self.pid_output_max)
        return pid

    def regulate_pressure_pid(self):
        """Run one PID step and apply the calculated pressure.

        Returns:
            float: Newly calculated pressure setpoint.
        """
        flowrate = self.get_flowrate([int(self.default_sensor_channel)])
        if not flowrate:
            raise RuntimeError("No flow-rate value available for PID regulation.")
        new_pressure = float(self.pid(flowrate[0]))
        self.set_pressure(new_pressure, log_entry=False)
        return new_pressure

    def start_pressure_regulation_loop(self, target_flowrate):
        """Start the PID pressure-regulation loop.

        Args:
            target_flowrate (float): Flow-rate setpoint for PID regulation.
        """
        if self.regulating:
            self.stop_pressure_regulation_loop()
        self.regulating = True
        self.pid = self.init_pid(setpoint=float(target_flowrate))
        self._schedule_pressure_regulation(float(target_flowrate))

    def stop_pressure_regulation_loop(self):
        """Stop the PID pressure-regulation loop."""
        self.regulating = False

    def pressure_regulation_loop(self, target_flowrate):
        """Run one pressure-regulation step and schedule the next one.

        Args:
            target_flowrate (float): Flow-rate setpoint for PID regulation.
        """
        if not self.regulating:
            return
        self.regulate_pressure_pid()
        if self.regulating:
            self._schedule_pressure_regulation(target_flowrate)

    # Volume count ---------------------------------------------------------------------------------------------------------

    def start_volume_measurement(self, target_volume=inf):
        """Start integrating injected volume from the flow-rate signal.

        Args:
            target_volume (float): Volume threshold at which counting stops.
        """
        self.measuring_volume = True
        self.total_volume = 0.0
        self.time_since_start = 0.0
        self.target_volume = float(target_volume)
        self.target_volume_reached = False
        self._schedule_volume_measurement()

    def volume_measurement_loop(self, sampling_interval=None):
        """Run one volume-integration step and schedule the next one.

        Args:
            sampling_interval (float | None): Integration interval in seconds.
                If ``None``, the configured sampling interval is used.
        """
        if not self.measuring_volume:
            return

        sampling_interval = (
            float(self.sampling_interval)
            if sampling_interval is None
            else float(sampling_interval)
        )
        flowrate = self.get_flowrate([int(self.default_sensor_channel)])
        pressure = self.get_pressure([int(self.default_pressure_channel)])
        if not flowrate:
            raise RuntimeError("No flow-rate value available for volume measurement.")

        flowrate_value = float(flowrate[0])
        pressure_value = float(pressure[0]) if pressure else 0.0
        self.total_volume = round(self.total_volume + flowrate_value * sampling_interval / 60.0, 3)
        self.time_since_start = round(self.time_since_start + sampling_interval, 3)

        self.sigUpdateVolumeMeasurement.emit(
            self.total_volume,
            self.time_since_start,
            flowrate_value,
            pressure_value,
        )

        if self.total_volume >= self.target_volume:
            self.target_volume_reached = True
            self.measuring_volume = False
            self.sigTargetVolumeReached.emit()
            return

        self.target_volume_reached = False
        self._schedule_volume_measurement()

    def stop_volume_measurement(self):
        """Stop volume integration."""
        self.measuring_volume = False
        self.target_volume_reached = True

    # Rinse needle ---------------------------------------------------------------------------------------------------------

    def start_rinsing(self, duration):
        """Start needle rinsing.

        Args:
            duration (float): Rinsing duration in seconds.
        """
        self.rinsing_enabled = True
        self.rinsing_pump.rinsing(duration)

    def stop_rinsing(self):
        """Stop needle rinsing and notify listeners."""
        self.rinsing_enabled = False
        self.sigRinsingFinished.emit()

    def rinsing_finished(self):
        """Handle completion of a timed rinsing operation."""
        self.rinsing_enabled = False
        self.sigRinsingFinished.emit()

    # ----------------------------------------------------------------------------------------------------------------------
    # Methods to handle the user interface state
    # ----------------------------------------------------------------------------------------------------------------------

    def disable_flowcontrol_actions(self):
        """Disable GUI flow actions and stop active continuous operations."""
        self.sigDisableFlowActions.emit()
        self.stop_flow_measurement()
        self.stop_pressure_regulation_loop()
        self.stop_volume_measurement()

    def enable_flowcontrol_actions(self):
        """Enable GUI flow actions."""
        self.sigEnableFlowActions.emit()

    def _schedule_flow_measurement(self):
        """Schedule the next flow-measurement update."""
        worker = WaitWorker(self.sampling_interval)
        worker.signals.sigFinished.connect(self.flow_measurement_loop)
        self.threadpool.start(worker)

    def _schedule_pressure_regulation(self, target_flowrate):
        """Schedule the next pressure-regulation step.

        Args:
            target_flowrate (float): Flow-rate setpoint emitted to the next loop.
        """
        worker = WaitWorker(self.sampling_interval, payload=target_flowrate)
        worker.signals.sigRegulationWaitFinished.connect(self.pressure_regulation_loop)
        self.threadpool.start(worker)

    def _schedule_volume_measurement(self):
        """Schedule the next volume-integration step."""
        worker = VolumeCountWorker(self.sampling_interval)
        worker.signals.sigIntegrationIntervalFinished.connect(self.volume_measurement_loop)
        self.threadpool.start(worker)

    @staticmethod
    def _dict_values(mapping):
        """Return mapping values ordered by sorted channel key.

        Args:
            mapping (dict): Channel-indexed values.

        Returns:
            list: Values ordered by sorted channel key.
        """
        return [mapping[key] for key in sorted(mapping)]

    @staticmethod
    def _normalize_values(values):
        """Normalize scalar or iterable values to a list of floats.

        Args:
            values (float | list[float]): Scalar or iterable values.

        Returns:
            list[float]: Normalized float values.
        """
        if isinstance(values, (int, float)):
            return [float(values)]
        return [float(value) for value in values]

    @staticmethod
    def _normalize_channels(channels):
        """Normalize channel selection to a list of integers.

        Args:
            channels (int | list[int] | None): Channel selection.

        Returns:
            list[int] | None: Normalized channel selection.
        """
        if channels is None:
            return None
        if isinstance(channels, int):
            return [channels]
        return [int(channel) for channel in channels]
