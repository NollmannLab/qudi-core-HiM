# -*- coding: utf-8 -*-
"""
qudi-core-HiM task: run the hybridization injection sequence of an injections file (buffers, probes
and incubation steps) with the valves, the flow control and the pipetting robot.

Structure - one file for all setups:
  - FluidicsTaskBase: the shared sequence. The valve positions that depend on the setup are class
    attributes, set by the subclasses.
  - FluidicsRAMMTask / FluidicsSDTask: one subclass per setup (data only).
  - FluidicsDummyTask: RAMM layout, for testing with dummy_config.cfg.
The steps (valve moves, injection, incubation, needle move), the valve layout and timing attributes
and the reading / validation of the injections file come from FluidicsStepsMixin
(tasks/common/fluidics_steps.py), shared with the Hi-M task.
The path of the experiment YAML written by the experiment configurator and the valve outlet of the
probe needle differ between machines: each microscope's config sets them in the task's entry with
"options: user_config_path: ... probe_valve_number: ..." (applied by logic/taskrunner_logic.py).

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from qudi.core.connector import Connector
from qudi.core.scripting.moduletask import ModuleTask
from qudi.tasks.common.fluidics_steps import FluidicsStepsMixin


class FluidicsTaskBase(FluidicsStepsMixin, ModuleTask):
    """Shared fluidics sequence: inject the buffers and probes of the 'hybridization list' of an
    injections file, with incubation steps in between.

    Not meant to be configured directly - use a setup subclass. Options (config "options:"):
        user_config_path    experiment YAML written by the experiment configurator; its key
                            'injections_path' points to the injections file (required)
        probe_valve_number  outlet of the buffer valve connected to the probe needle (required, int)

    Injections file (written by the injections configurator):
        buffer: {valve outlet: name}, probes: {tube: name}, hybridization list: [steps],
        probe_needle_mode: 'next' | 'same' (missing -> 'next').
        An injection step has a product, a volume (µl) and a flowrate (µl/min); an incubation step
        has no product and a time (s). Only the hybridization list is used.

    Needle: the first probe injection uses the lowest probe tube. With 'next', every further
    injection from the probe valve moves the needle to the next tube (tube + 1); with 'same' the
    needle stays in the first tube.

    The injections file is fully checked before any hardware call: all problems are reported in
    one error. During the run the GUIs of the valves, the flow control and the robot are locked.
    An injection that has not reached its volume after
    injection_timeout_factor * volume / flowrate + injection_timeout_margin_s stops the task.
    Interrupt: checked at least every 0.1 s while waiting (injection, incubation, needle move).
    _cleanup() always sets the pressure to 0, puts the valves in cleanup_valve_positions and
    unlocks the GUIs. A needle move in progress when the task stops is left to finish.
    """

    valve_logic = Connector(interface='FluidicsValveLogic')
    flow_logic = Connector(interface='FluidicsFlowLogic')
    robot_logic = Connector(interface='FluidicsRobotLogic')

    # options, set by the config ("options:")
    user_config_path = None
    probe_valve_number = None

    def _setup(self) -> None:
        # attributes used by _cleanup(): set first, so that _cleanup() also works if fetching a
        # connector fails
        self._hardware_touched = False
        self._gui_locked = False
        self._arrival_slot = None
        self._needle_arrived_at = None
        self._steps = []
        self._steps_done = 0
        self._needle_mode = None
        self._tubes_used = []

        self._valve = self.valve_logic()
        self._flow = self.flow_logic()
        self._robot = self.robot_logic()

    # ==============================================================================================
    # Main entry point
    # ==============================================================================================

    def _run(self) -> dict:
        probe_valve = self._check_options()

        # 1. experiment YAML -> path of the injections file
        injections_path = self._read_injections_path()

        # 2. injections file
        buffer_valves, probes, hybridization_list, needle_mode = self._read_injections(injections_path)

        # needle position (robot origin) needed for the probe injections: warning + message box, task stopped
        # without any hardware call
        if self._needle_position_missing(buffer_valves, hybridization_list, probe_valve):
            self._warn_needle_position()
            return {'aborted': 'needle position not initialised', 'steps_done': 0}

        # 3. validation, no hardware call - all problems in one error
        self._steps = self._validate(buffer_valves, probes, hybridization_list, needle_mode, probe_valve)
        self._needle_mode = needle_mode

        # 4. needle tube for each probe injection
        probe_steps = [step for step in self._steps if step['probe']]
        if probe_steps:
            first_tube = min(probes)
            for count, step in enumerate(probe_steps):
                step['tube'] = first_tube + count if needle_mode == 'next' else first_tube

        # 5. plan
        self._log_plan(injections_path, probes)
        self._check_interrupt()

        # 6. lock the GUIs
        self._hardware_touched = True
        self._gui_locked = True
        self._valve.disable_valve_positioning()
        self._flow.disable_flowcontrol_actions()
        self._robot.disable_positioning_actions()

        # 7. needle in the first tube
        if probe_steps:
            self._move_needle(probe_steps[0]['tube'])

        # 8. start positions
        self._set_valves(self.start_valve_positions)

        # 9. steps
        total = len(self._steps)
        for number, step in enumerate(self._steps, 1):
            self.log.info(f'Step {number}/{total}: {self._describe(step)}')
            self._check_interrupt()
            if step['kind'] == 'injection':
                self._inject(number, step, probe_steps)
            else:
                self._incubate(step)
            self._steps_done = number

        # 10. summary
        return {'steps_done': self._steps_done,
                'steps_total': total,
                'probe_needle_mode': self._needle_mode,
                'tubes_used': list(self._tubes_used)}

    def _cleanup(self) -> None:
        """Pressure to 0, valves to cleanup_valve_positions, GUIs unlocked. Each step is protected
        on its own; never raises."""
        if self._arrival_slot is not None:
            try:
                self._robot.sigStageMovedToTarget.disconnect(self._arrival_slot)
            except Exception as err:
                self.log.error(f'Cleanup: could not disconnect from the robot signal: {err}')
            self._arrival_slot = None

        if getattr(self, '_hardware_touched', False):
            for action, call in (('stop the pressure regulation', lambda: self._flow.stop_pressure_regulation_loop()),
                                 ('stop the volume measurement', lambda: self._flow.stop_volume_measurement()),
                                 ('set the pressure to 0', lambda: self._flow.set_pressure(0.0))):
                try:
                    call()
                except Exception as err:
                    self.log.error(f'Cleanup: could not {action}: {err}')

            for address, position in self.cleanup_valve_positions.items():
                try:
                    self._set_valve(address, position)
                except Exception as err:
                    self.log.error(f'Cleanup: {err}')

        if getattr(self, '_gui_locked', False):
            for name, unlock in (('valve', lambda: self._valve.enable_valve_positioning()),
                                 ('flow control', lambda: self._flow.enable_flowcontrol_actions()),
                                 ('robot', lambda: self._robot.enable_positioning_actions())):
                try:
                    unlock()
                except Exception as err:
                    self.log.error(f'Cleanup: could not unlock the {name} GUI: {err}')
            self._gui_locked = False

        self.log.info(f'Fluidics task ended after {self._steps_done}/{len(self._steps)} step(s).')

    def _log_plan(self, injections_path, probes) -> None:
        self.log.info(f'Fluidics sequence from {injections_path} - needle mode {self._needle_mode!r}, '
                      f'{len(self._steps)} step(s):')
        for number, step in enumerate(self._steps, 1):
            self.log.info(f'  {number}. {self._describe(step)}')
        for tube in sorted({step['tube'] for step in self._steps if step['probe']}):
            if tube not in probes:
                self.log.warning(f'Tube {tube} is used but not listed in the probes of the injections file.')

    # ==============================================================================================
    # Options, files and validation
    # ==============================================================================================

    def _check_options(self) -> int:
        """Return probe_valve_number as an int; raise if an option is not set."""
        if self.user_config_path in (None, ''):
            raise RuntimeError(f'user_config_path not set for task {type(self).__name__} - add '
                               f'`options: user_config_path: ...` to this task\'s entry in the config file')
        if self.probe_valve_number in (None, ''):
            raise RuntimeError(f'probe_valve_number not set for task {type(self).__name__} - add '
                               f'`options: probe_valve_number: ...` to this task\'s entry in the config file')
        try:
            return int(self.probe_valve_number)
        except (TypeError, ValueError):
            raise RuntimeError(f'probe_valve_number must be an integer, got {self.probe_valve_number!r}.')

    def _read_injections_path(self) -> str:
        config = self._read_yaml(self.user_config_path, 'experiment file')
        injections_path = config.get('injections_path')
        if not injections_path:
            raise RuntimeError(f'No injections_path in the experiment file {self.user_config_path}.')
        return str(injections_path)


class FluidicsRAMMTask(FluidicsTaskBase):
    """Fluidics sequence on the RAMM: valve a = buffers, b = RT rinsing (2 = inject probe),
    c = syringe (1 = syringe / closed, 2 = pump). The syringe valve is closed while the needle moves
    and during incubations.

    Config example for copy-paste (logic: task_runner: options: module_tasks:):

        fluidics:
          module.Class: 'qudi.tasks.fluidics.FluidicsRAMMTask'
          connect:
            valve_logic: fluidics_valve_logic
            flow_logic: fluidics_flow_logic
            robot_logic: pipetting_robot_logic
          options:
            user_config_path: '/path/to/qudi_task_config_files/fluidics_task_ramm.yaml'
            probe_valve_number: 7
    """
    start_valve_positions = {'b': 2, 'c': 2}
    needle_move_valve_positions = {'c': 1}
    needle_moved_valve_positions = {'c': 2}
    incubation_valve_positions = {'c': 1}
    incubation_end_valve_positions = {'c': 2}
    cleanup_valve_positions = {'c': 1, 'b': 1, 'a': 1}


class FluidicsSDTask(FluidicsTaskBase):
    """Fluidics sequence on the spinning disk: valve a = buffers, b = second valve (1 at start and
    at the end). No valve change around needle moves or incubations.

    Config example for copy-paste (logic: task_runner: options: module_tasks:):

        fluidics:
          module.Class: 'qudi.tasks.fluidics.FluidicsSDTask'
          connect:
            valve_logic: fluidics_valve_logic
            flow_logic: fluidics_flow_logic
            robot_logic: pipetting_robot_logic
          options:
            user_config_path: '/path/to/qudi_task_config_files/fluidics_task_sd.yaml'
            probe_valve_number: 3
    """
    start_valve_positions = {'b': 1}
    needle_move_valve_positions = {}
    needle_moved_valve_positions = {}
    incubation_valve_positions = {}
    incubation_end_valve_positions = {}
    cleanup_valve_positions = {'b': 1, 'a': 1}


class FluidicsDummyTask(FluidicsRAMMTask):
    """RAMM valve layout on the dummy valve (a, b, c), for testing with dummy_config.cfg.

    Config example (dummy_config.cfg, logic: task_runner: options: module_tasks:):

        fluidics_dummy:
          module.Class: 'qudi.tasks.fluidics.FluidicsDummyTask'
          connect:
            valve_logic: fluidics_valve_logic
            flow_logic: fluidics_flow_logic
            robot_logic: pipetting_robot_logic
          options:
            user_config_path: '/home/jb/qudi/qudi_task_config_files/fluidics_task.yaml'
            probe_valve_number: 7
    """
