# -*- coding: utf-8 -*-
"""Logic module routing named trigger requests to configured trigger hardware.

The module accepts any number of trigger output and input modules through optional connector lists.
Each connected hardware module is addressed by its Qudi module name. This keeps the task independent
of DAQ channel numbers and allows configurations to provide only the trigger directions they use.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from qudi.core.connector import ConnectorList
from qudi.core.module import LogicBase

from qudi.interface.trigger_sync_interface import TriggerInputInterface, TriggerOutputInterface


class TriggerLogic(LogicBase):
    """Route trigger output and input operations to hardware modules by module name.

    Both connector lists are optional, so this logic can be configured with outputs only, inputs
    only, both directions, or neither. A missing or unknown trigger name raises a descriptive
    error when an operation is requested.

    Example configuration::

        trigger_logic:
          module.Class: 'trigger_logic.TriggerLogic'
          connect:
            trigger_outputs: ['trigger_ZEN_start_block']
            trigger_inputs: ['trigger_ZEN_ready', 'trigger_ZEN_block_finished']
    """

    trigger_outputs = ConnectorList(
        name='trigger_outputs', interface=TriggerOutputInterface, optional=True
    )
    trigger_inputs = ConnectorList(
        name='trigger_inputs', interface=TriggerInputInterface, optional=True
    )

    def on_activate(self) -> None:
        """Collect configured trigger modules and index them by their Qudi module names."""
        self._trigger_outputs = {
            self.trigger_outputs(index).module_name: self.trigger_outputs(index)
            for index in range(len(self.trigger_outputs))
        }
        self._trigger_inputs = {
            self.trigger_inputs(index).module_name: self.trigger_inputs(index)
            for index in range(len(self.trigger_inputs))
        }

    def on_deactivate(self) -> None:
        """Release the trigger hardware references held by this logic module."""
        self._trigger_outputs = {}
        self._trigger_inputs = {}

    def send_trigger(self, trigger_name: str | None = None) -> None:
        """Send one pulse through a named output trigger.

        Args:
            trigger_name: Qudi module name of the connected output trigger. If omitted, the only
                configured output is used when exactly one is available.

        Raises:
            RuntimeError: If no output is connected or the requested name is not connected.
            ValueError: If the name is omitted while more than one output is connected.
        """
        trigger_name = self._resolve_trigger_name(trigger_name, self._trigger_outputs, 'output')
        self._trigger_outputs[trigger_name].send_trigger()

    def update_pulse_time(self, trigger_name: str | None, pulse_time: float | int) -> None:
        """Set value for the trigger pulse length"""
        trigger_name = self._resolve_trigger_name(trigger_name, self._trigger_outputs, 'output')
        self._trigger_outputs[trigger_name].update_pulse_time(pulse_time)

    def is_triggered(self, trigger_name: str | None = None) -> bool:
        """Return the current state of a named input trigger without waiting for an edge.

        Args:
            trigger_name: Qudi module name of the connected input trigger. If omitted, the only
                configured input is sampled when exactly one is available.

        Returns:
            bool: Current sampled state of the selected input.

        Raises:
            RuntimeError: If no input is connected or the requested name is not connected.
            ValueError: If the name is omitted while more than one input is connected.
        """
        trigger_name = self._resolve_trigger_name(trigger_name, self._trigger_inputs, 'input')
        return self._trigger_inputs[trigger_name].is_triggered()

    @staticmethod
    def _resolve_trigger_name(
        trigger_name: str | None,
        triggers: dict,
        direction: str,
    ) -> str:
        """Resolve an explicit trigger name or infer it when exactly one is connected."""
        if trigger_name is None:
            if len(triggers) == 1:
                return next(iter(triggers))
            if not triggers:
                raise RuntimeError(f'No trigger {direction} modules are connected.')
            names = ', '.join(sorted(triggers))
            raise ValueError(
                f'The trigger {direction} name is required because multiple modules are connected: '
                f'{names}.'
            )
        if trigger_name not in triggers:
            names = ', '.join(sorted(triggers)) or 'none'
            raise RuntimeError(
                f'Trigger {direction} module {trigger_name!r} is not connected. '
                f'Connected {direction} modules: {names}.'
            )
        return trigger_name
