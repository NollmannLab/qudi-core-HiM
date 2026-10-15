# -*- coding: utf-8 -*-
"""
qudi-core-HiM task: run the hybridization injection sequence of an injections file (buffers, probes
and incubation steps) with the valves, the flow control and the pipetting robot.

Structure - one file for all setups:
  - FluidicsTaskBase: the shared sequence. The valve positions that depend on the setup are class
    attributes, set by the subclasses.
  - FluidicsRAMMTask / FluidicsSDTask: one subclass per setup (data only).
  - FluidicsDummyTask: RAMM layout, for testing with dummy_config.cfg.
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

from numbers import Real
from time import monotonic, sleep

import yaml
from qtpy import QtCore

from qudi.core.connector import Connector
from qudi.core.scripting.moduletask import ModuleTask


class FluidicsTaskBase(ModuleTask):
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

    # setup-specific valve positions {address: position}, applied in the given order
    start_valve_positions = {}         # before the first step
    needle_move_valve_positions = {}   # before a needle move
    needle_moved_valve_positions = {}  # after a needle move
    incubation_valve_positions = {}    # at the start of an incubation
    incubation_end_valve_positions = {}  # at the end of an incubation
    cleanup_valve_positions = {}       # at the end of the task (also after an error / interrupt)

    buffer_valve_address = 'a'  # valve selecting the product (buffer outlet)

    volume_poll_interval_s = 1.0
    robot_timeout_s = 120.0
    injection_timeout_factor = 3.0
    injection_timeout_margin_s = 60.0
    incubation_log_interval_s = 30

    PROBE_NEEDLE_MODES = ('next', 'same')
    _MAX_WAIT_STEP_S = 0.1  # maximum time between two interrupt checks while waiting
    _PRESSURE_SETTLE_S = 1.0  # last regulation step after stopping the regulation loop

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

    # ==============================================================================================
    # Steps
    # ==============================================================================================

    def _inject(self, number, step, probe_steps) -> None:
        """Select the product, move the needle if needed, inject the volume at the flowrate."""
        # a. product
        self._set_valve(self.buffer_valve_address, step['valve'])

        # b. next tube for a further probe injection
        if step['probe'] and self._needle_mode == 'next' and step is not probe_steps[0]:
            self._move_needle(step['tube'])
        if step['probe'] and step['tube'] not in self._tubes_used:
            self._tubes_used.append(step['tube'])

        # c. regulation and volume count
        volume, flowrate = step['volume'], step['flowrate']
        self._flow.set_pressure(0.0)
        self._flow.start_pressure_regulation_loop(flowrate)
        self._flow.start_volume_measurement(volume)

        # d. wait for the volume (volume / flowrate is in minutes)
        timeout_s = self.injection_timeout_factor * volume / flowrate * 60.0 + self.injection_timeout_margin_s
        start = monotonic()
        while not self._flow.target_volume_reached:
            if monotonic() - start > timeout_s:
                raise RuntimeError(f'Step {number}: volume not reached - check the line '
                                   f'({self._flow.total_volume:g} of {volume:g} µl after {timeout_s:.0f} s).')
            self._interruptible_sleep(self.volume_poll_interval_s)

        # e. stop the regulation, pressure to 0
        self._flow.stop_pressure_regulation_loop()
        sleep(self._PRESSURE_SETTLE_S)
        self._flow.set_pressure(0.0)
        self.log.info(f'Step {number}: {self._flow.total_volume:g} µl injected '
                      f'in {monotonic() - start:.0f} s.')

    def _incubate(self, step) -> None:
        """Wait the incubation time (interruptible), with the incubation valve positions."""
        # a. incubation positions
        self._set_valves(self.incubation_valve_positions)

        # b. interruptible wait, progress logged every incubation_log_interval_s
        duration = step['time']
        start = monotonic()
        next_log = self.incubation_log_interval_s
        while True:
            elapsed = monotonic() - start
            if elapsed >= duration:
                break
            if elapsed >= next_log:
                self.log.info(f'Incubation: {elapsed:.0f} / {duration:g} s')
                next_log += self.incubation_log_interval_s
            self._interruptible_sleep(min(1.0, duration - elapsed))

        # c. end positions
        self._set_valves(self.incubation_end_valve_positions)

    def _move_needle(self, tube) -> None:
        """Move the needle to a tube and wait until it has arrived (interruptible, robot_timeout_s)."""
        self._set_valves(self.needle_move_valve_positions)

        if self._arrival_slot is None:
            def arrived(position, target):
                # runs in the robot logic thread right after the arrival signal, so the lock reaches
                # the GUI right after the arrival (the GUI re-enables its buttons on arrival)
                self._needle_arrived_at = target
                self._robot.disable_positioning_actions()
            self._arrival_slot = arrived
            self._robot.sigStageMovedToTarget.connect(arrived, QtCore.Qt.DirectConnection)
        self._needle_arrived_at = None

        self.log.info(f'Moving the needle to tube {tube}')
        self._robot.start_move_to_target(tube)
        if not self._robot.moving and self._needle_arrived_at != tube:
            raise RuntimeError(f'The robot did not start the move to tube {tube} - see the log.')

        start = monotonic()
        while self._robot.moving:
            if monotonic() - start > self.robot_timeout_s:
                raise RuntimeError(f'The needle did not reach tube {tube} within {self.robot_timeout_s:g} s.')
            self._interruptible_sleep(self._MAX_WAIT_STEP_S)
        if self._needle_arrived_at != tube:
            raise RuntimeError(f'The robot stopped before reaching tube {tube} - see the log.')

        # the fluidics GUI re-enables its robot buttons at the end of every move
        self._robot.disable_positioning_actions()
        self._set_valves(self.needle_moved_valve_positions)

    # ==============================================================================================
    # Helpers
    # ==============================================================================================

    def _set_valves(self, positions) -> None:
        for address, position in positions.items():
            self._set_valve(address, position)

    def _set_valve(self, address, position) -> None:
        """Move one valve; raise naming the valve and the position if it does not get there."""
        try:
            reached = self._valve.set_valve_position(address, position)
        except Exception as err:
            raise RuntimeError(f'Could not set valve {address} to position {position}: {err}') from err
        if reached is False or reached is None or int(reached) != int(position):
            raise RuntimeError(f'Valve {address} did not reach position {position} (reported: {reached}).')

    def _interruptible_sleep(self, duration_s) -> None:
        """Sleep duration_s seconds, checking for an interrupt at least every 0.1 s."""
        deadline = monotonic() + max(0.0, float(duration_s))
        while True:
            self._check_interrupt()
            remaining = deadline - monotonic()
            if remaining <= 0:
                return
            sleep(min(self._MAX_WAIT_STEP_S, remaining))

    def _describe(self, step) -> str:
        if step['kind'] == 'incubation':
            return f'incubation {step["time"]:g} s'
        tube = f', tube {step["tube"]}' if step['probe'] else ''
        return (f'inject {step["product"]} (valve {step["valve"]}{tube}), {step["volume"]:g} µl '
                f'at {step["flowrate"]:g} µl/min')

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

    def _read_yaml(self, path, what):
        try:
            with open(path, 'r', encoding='utf-8') as stream:
                content = yaml.safe_load(stream)
        except Exception as err:
            raise RuntimeError(f'Could not read the {what} {path}: {err}') from err
        if not isinstance(content, dict):
            raise RuntimeError(f'The {what} {path} is empty or not a YAML mapping.')
        return content

    def _read_injections_path(self) -> str:
        config = self._read_yaml(self.user_config_path, 'experiment file')
        injections_path = config.get('injections_path')
        if not injections_path:
            raise RuntimeError(f'No injections_path in the experiment file {self.user_config_path}.')
        return str(injections_path)

    def _read_injections(self, path):
        """Return ({product name: valve}, {tube: probe name}, hybridization list, needle mode)."""
        content = self._read_yaml(path, 'injections file')
        missing = [key for key in ('buffer', 'probes', 'hybridization list') if key not in content]
        if missing:
            raise RuntimeError(f'Injections file {path} is incomplete - missing: {", ".join(missing)}.')
        buffer = content['buffer'] or {}
        probes = content['probes'] or {}
        if not isinstance(buffer, dict) or not isinstance(probes, dict):
            raise RuntimeError(f'Injections file {path}: buffer and probes must be mappings.')
        buffer_valves = {name: valve for valve, name in buffer.items()}
        return buffer_valves, probes, content['hybridization list'] or [], content.get('probe_needle_mode', 'next')

    def _validate(self, buffer_valves, probes, hybridization_list, needle_mode, probe_valve) -> list:
        """Check the sequence and the setup values without any hardware call. Return the steps;
        raise once listing every problem."""
        problems = []
        steps = []
        valve_dict = self._valve.valve_dict

        if needle_mode not in self.PROBE_NEEDLE_MODES:
            problems.append(f'probe_needle_mode {needle_mode!r} is not valid (valid: {list(self.PROBE_NEEDLE_MODES)})')
        if not isinstance(hybridization_list, list) or not hybridization_list:
            problems.append('the hybridization list is empty')
            hybridization_list = []

        for number, entry in enumerate(hybridization_list, 1):
            if not isinstance(entry, dict):
                problems.append(f'step {number}: not a valid entry ({entry!r})')
                continue
            product = entry.get('product')
            if product is None:
                duration = entry.get('time')
                if not _is_number(duration) or duration < 0:
                    problems.append(f'step {number} (incubation): time must be >= 0 s, got {duration!r}')
                    continue
                steps.append({'kind': 'incubation', 'time': float(duration), 'probe': False})
                continue
            volume, flowrate = entry.get('volume'), entry.get('flowrate')
            ok = True
            if product not in buffer_valves:
                problems.append(f'step {number}: product {product!r} is not in the buffer list')
                ok = False
            if not _is_number(volume) or volume <= 0:
                problems.append(f'step {number} ({product}): volume must be > 0 µl, got {volume!r}')
                ok = False
            if not _is_number(flowrate) or flowrate <= 0:
                problems.append(f'step {number} ({product}): flowrate must be > 0 µl/min, got {flowrate!r}')
                ok = False
            if ok:
                valve = int(buffer_valves[product])
                steps.append({'kind': 'injection', 'product': product, 'valve': valve,
                              'volume': float(volume), 'flowrate': float(flowrate),
                              'probe': valve == probe_valve, 'tube': None})

        n_probe = sum(1 for s in steps if s['probe'])
        if n_probe:
            if not probes:
                problems.append('the sequence uses the probe valve but the probe list is empty')
            if self._robot.origin is None:
                problems.append('the sequence uses the probe valve but the robot origin (position 1) is not defined')
            if probes and needle_mode == 'next':
                last_tube = min(probes) + n_probe - 1
                max_tubes = getattr(self._robot, 'max_num_probes', 0)
                if max_tubes and last_tube > max_tubes:
                    problems.append(f'{n_probe} probe injection(s) from tube {min(probes)} need tube {last_tube}, '
                                    f'the robot has {max_tubes}')

        problems.extend(self._check_valve_positions(valve_dict, buffer_valves, probe_valve))

        if problems:
            raise RuntimeError(f'Fluidics task not started - {len(problems)} problem(s):\n  - '
                               + '\n  - '.join(problems))
        return steps

    def _check_valve_positions(self, valve_dict, buffer_valves, probe_valve) -> list:
        """Check that every address / position used exists on the valves."""
        problems = []

        def outputs(address):
            try:
                return int(valve_dict[address]['number_outputs'])
            except (KeyError, TypeError, ValueError):
                return None

        if outputs(self.buffer_valve_address) is None:
            problems.append(f'buffer valve {self.buffer_valve_address!r} is not configured on the valve logic')
        else:
            n = outputs(self.buffer_valve_address)
            for name, valve in buffer_valves.items():
                if not 1 <= int(valve) <= n:
                    problems.append(f'buffer {name!r}: outlet {valve} outside 1..{n} of valve '
                                    f'{self.buffer_valve_address}')
            if not 1 <= probe_valve <= n:
                problems.append(f'probe_valve_number {probe_valve} outside 1..{n} of valve {self.buffer_valve_address}')

        for attribute in ('start_valve_positions', 'needle_move_valve_positions', 'needle_moved_valve_positions',
                          'incubation_valve_positions', 'incubation_end_valve_positions', 'cleanup_valve_positions'):
            for address, position in getattr(self, attribute).items():
                n = outputs(address)
                if n is None:
                    problems.append(f'{attribute}: valve {address!r} is not configured on the valve logic')
                elif not 1 <= int(position) <= n:
                    problems.append(f'{attribute}: position {position} outside 1..{n} of valve {address}')
        return problems


def _is_number(value) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool)


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
