# -*- coding: utf-8 -*-
"""
Dummy flow sensor for qudi-core-HiM: same options and return format as FluigentFlowSensor, with a
simulated flowrate.

With a pump connected, the flow follows the pump output: flow_per_unit * pump output + gaussian
noise (never negative), so the flow logic PID regulation and volume count behave as on a real setup.
Without a pump, the flow is mean_flow + gaussian noise.

Config example:

    dummy_flow_sensor:
        module.Class: 'interfuse_hardware.dummy_flow_sensor.DummyFlowSensor'
        connect:
            pump: 'fluidics_pump'   # optional
        options:
            unit: "µl/min"
            sensor_channel_IDs:
                - 0
            flow_per_unit: 100.0    # flow (sensor unit) per pump output unit, e.g. µl/min per V
            mean_flow: 200.0        # flow without pump
            noise_std: 5.0

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""
from typing import Dict, Optional, Sequence, Tuple

from numpy.random import normal

from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector
from qudi.interface.flow_sensor_interface import FlowSensorInterface


class DummyFlowSensor(FlowSensorInterface):
    """Simulated flow sensor. get_flowrate() -> {channel: float}, get_sensor_unit() -> {channel: str}.
    A requested channel that is not configured is logged as an error and left out of the result."""

    pump = Connector(interface='PumpInterface', name='pump', optional=True)

    _sensor_channel_ids = ConfigOption('sensor_channel_IDs', missing='error')
    _sensor_unit = ConfigOption('unit', missing='error')
    _flow_per_unit = ConfigOption('flow_per_unit', default=100.0, converter=float)
    _mean_flow = ConfigOption('mean_flow', default=200.0, converter=float)
    _noise_std = ConfigOption('noise_std', default=5.0, converter=float)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pump = None
        self._sensor_channels: Tuple[int, ...] = ()

    def on_activate(self):
        channels = tuple(int(channel) for channel in self._sensor_channel_ids)
        if len(channels) != len(set(channels)):
            raise ValueError(f'Duplicate sensor channel IDs: {channels}.')
        self._sensor_channels = channels
        self._pump = self.pump()
        source = 'pump output' if self._pump is not None else f'mean flow {self._mean_flow:g}'
        self.log.info(f'Dummy flow sensor active on channels {channels} (flow from {source}).')

    def on_deactivate(self):
        self._pump = None
        self._sensor_channels = ()

    def get_flowrate(self, param_list: Optional[Sequence[int]] = None) -> Dict[int, float]:
        """Return {channel: flowrate} for the selected (or all configured) channels."""
        base = self._base_flow()
        return {channel: max(0.0, base + float(normal(0.0, self._noise_std)))
                for channel in self._selected_channels(param_list)}

    def get_sensor_unit(self, param_list: Optional[Sequence[int]] = None) -> Dict[int, str]:
        """Return {channel: unit} for the selected (or all configured) channels."""
        return {channel: self._sensor_unit for channel in self._selected_channels(param_list)}

    def _base_flow(self) -> float:
        """Noise-free flow: from the pump output if a pump is connected, else mean_flow."""
        if self._pump is None:
            return self._mean_flow
        try:
            output = self._pump.get_output()
            value = float(next(iter(output.values()))) if output else 0.0
        except Exception as err:
            self.log.error(f'Could not read the pump output: {err}')
            return 0.0
        return self._flow_per_unit * value

    def _selected_channels(self, channels) -> Tuple[int, ...]:
        """Requested channels that are configured; unknown channels are logged and ignored."""
        if channels is None:
            return self._sensor_channels
        try:
            requested = (int(channels),) if isinstance(channels, int) else tuple(int(c) for c in channels)
        except (TypeError, ValueError):
            self.log.error(f'Invalid sensor channel list: {channels!r}.')
            return ()
        unknown = [channel for channel in requested if channel not in self._sensor_channels]
        if unknown:
            self.log.error(f'Sensor channels {unknown} are not configured (configured: '
                           f'{self._sensor_channels}) - ignored.')
        return tuple(channel for channel in requested if channel in self._sensor_channels)
