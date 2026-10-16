# -*- coding: utf-8 -*-
"""
qudi-core-HiM: fluidics steps shared by the tasks that inject buffers and probes (fluidics task, Hi-M task).

FluidicsStepsMixin holds the valve layout of a setup, the timings, the reading and validation of an
injections file and the step methods (injection, incubation, needle move, valve moves). It defines no
connector and no _setup / _run / _cleanup: the task using it declares the connectors and sets the
attributes listed in the class docstring.

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
import math
from time import monotonic, sleep

import yaml
from qtpy import QtCore, QtWidgets


class _WarningPopup(QtCore.QObject):
    """Shows non-modal warning message boxes in the GUI thread; show() may be called from a task thread."""
    _sigShow = QtCore.Signal(str, str)

    def __init__(self):
        super().__init__()
        self._boxes = []
        self._sigShow.connect(self._show_box)

    def show(self, title, text):
        self._sigShow.emit(title, text)

    @QtCore.Slot(str, str)
    def _show_box(self, title, text):
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, title, text, QtWidgets.QMessageBox.Ok)
        box.setModal(False)
        box.finished.connect(lambda _result, b=box: self._boxes.remove(b) if b in self._boxes else None)
        self._boxes.append(box)
        box.show()


_warning_popup = None


def show_warning_popup(title, text):
    """Show a non-modal warning message box in the GUI thread. Returns False (nothing shown) without a GUI."""
    global _warning_popup
    app = QtWidgets.QApplication.instance()
    if not isinstance(app, QtWidgets.QApplication):
        return False
    if _warning_popup is None:
        popup = _WarningPopup()
        if popup.thread() is not app.thread():
            popup.moveToThread(app.thread())
        _warning_popup = popup
    _warning_popup.show(title, text)
    return True


class FluidicsStepsMixin:
    """Fluidics steps for a ModuleTask (put it before ModuleTask in the bases).

    The task sets, before calling the steps:
        self._valve, self._flow, self._robot   valve, flow and robot logic modules
        self._needle_mode                      'next' or 'same'
        self._tubes_used = []                  tubes used by the probe injections (filled by _inject)
        self._arrival_slot = None              robot arrival slot (connected by _move_needle; the task
        self._needle_arrived_at = None         disconnects it from sigStageMovedToTarget in _cleanup)
    and uses self.log and self._check_interrupt() of ModuleTask, and self._report_progress() /
    self._report_live() of ProgressModuleTask (tasks/common/progress.py).
    The step methods take a progress label (e.g. '2/5') shown in the Task Runner window.

    Injections file (written by the injections configurator):
        buffer: {valve outlet: name}, probes: {tube: name}, 'hybridization list' / 'photobleaching list':
        [steps], probe_needle_mode: 'next' | 'same' (missing -> 'next'). An injection step has a product,
        a volume (µl) and a flowrate (µl/min); an incubation step has no product and a time (s).
    """

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
    _NEEDLE_POSITION_MESSAGE = ('The needle position needs to be initialised first. Please do it in the Fluidics '
                                'GUI ("Set position 1"). The task is aborted for now.')
    _PRESSURE_SETTLE_S = 1.0  # last regulation step after stopping the regulation loop

    # ==============================================================================================
    # Steps
    # ==============================================================================================

    def _inject(self, number, step, probe_steps, label='') -> None:
        """Select the product, move the needle if needed, inject the volume at the flowrate.
        label: progress step label (e.g. '2/5'); the injected volume is reported live."""
        # a. product
        self._set_valve(self.buffer_valve_address, step['valve'])

        # b. next tube for a further probe injection
        if step['probe'] and self._needle_mode == 'next' and step is not probe_steps[0]:
            self._move_needle(step['tube'], label)
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
            self._report_live(label, f'Injecting {step["product"]} - {self._flow.total_volume:.0f}/{volume:g} µl')
            self._interruptible_sleep(self.volume_poll_interval_s)

        # e. stop the regulation, pressure to 0
        self._flow.stop_pressure_regulation_loop()
        sleep(self._PRESSURE_SETTLE_S)
        self._flow.set_pressure(0.0)
        self.log.info(f'Step {number}: {self._flow.total_volume:g} µl injected '
                      f'in {monotonic() - start:.0f} s.')

    def _incubate(self, step, label='') -> None:
        """Wait the incubation time (interruptible), with the incubation valve positions.
        label: progress step label (e.g. '3/5'); the time left is reported live."""
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
            minutes, seconds = divmod(int(math.ceil(duration - elapsed)), 60)
            self._report_live(label, f'Incubating - {minutes}:{seconds:02d} left')
            self._interruptible_sleep(min(1.0, duration - elapsed))

        # c. end positions
        self._set_valves(self.incubation_end_valve_positions)

    def _move_needle(self, tube, label='') -> None:
        """Move the needle to a tube and wait until it has arrived (interruptible, robot_timeout_s).
        label: progress step label (e.g. '0/5' before the first step)."""
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

        self._report_progress(label, f'Moving the needle to tube {tube}')  # also logged
        self._robot.start_move_to_target(tube)
        if not self._robot.moving and self._needle_arrived_at != tube:
            raise RuntimeError(f'The robot did not start the move to tube {tube}.')

        start = monotonic()
        while self._robot.moving:
            if monotonic() - start > self.robot_timeout_s:
                raise RuntimeError(f'The needle did not reach tube {tube} within {self.robot_timeout_s:g} s.')
            self._interruptible_sleep(self._MAX_WAIT_STEP_S)
        if self._needle_arrived_at != tube:
            raise RuntimeError(f'The robot stopped before reaching tube {tube}.')

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

    # ==============================================================================================
    # Injections file and validation
    # ==============================================================================================

    def _needle_position_missing(self, buffer_valves, step_list, probe_valve) -> bool:
        """True if a step of step_list injects from the probe valve while the robot origin (needle position 1)
        is not defined. Malformed entries are ignored here (reported by _validate)."""
        if self._robot.origin is not None or not isinstance(step_list, list):
            return False
        for entry in step_list:
            if not isinstance(entry, dict) or entry.get('product') is None:
                continue
            try:
                if int(buffer_valves.get(entry['product'])) == probe_valve:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def _warn_needle_position(self) -> None:
        """Log the missing needle position as a warning and show it in a message box (GUI only)."""
        self.log.warning(self._NEEDLE_POSITION_MESSAGE)
        show_warning_popup('Needle position not defined', self._NEEDLE_POSITION_MESSAGE)

    def _read_yaml(self, path, what):
        try:
            with open(path, 'r', encoding='utf-8') as stream:
                content = yaml.safe_load(stream)
        except Exception as err:
            raise RuntimeError(f'Could not read the {what} {path}: {err}') from err
        if not isinstance(content, dict):
            raise RuntimeError(f'The {what} {path} is empty or not a YAML mapping.')
        return content

    def _read_injections(self, path, list_key='hybridization list'):
        """Return ({product name: valve}, {tube: probe name}, step list, needle mode).
        list_key: the list of steps to read ('hybridization list' or 'photobleaching list')."""
        content = self._read_yaml(path, 'injections file')
        missing = [key for key in ('buffer', 'probes', list_key) if key not in content]
        if missing:
            raise RuntimeError(f'Injections file {path} is incomplete - missing: {", ".join(missing)}.')
        buffer = content['buffer'] or {}
        probes = content['probes'] or {}
        if not isinstance(buffer, dict) or not isinstance(probes, dict):
            raise RuntimeError(f'Injections file {path}: buffer and probes must be mappings.')
        buffer_valves = {name: valve for valve, name in buffer.items()}
        return buffer_valves, probes, content[list_key] or [], content.get('probe_needle_mode', 'next')

    def _validate(self, buffer_valves, probes, hybridization_list, needle_mode, probe_valve,
                  list_name='hybridization list') -> list:
        """Check the sequence and the setup values without any hardware call. Return the steps;
        raise once listing every problem. list_name names the step list in the messages."""
        problems = []
        steps = []
        valve_dict = self._valve.valve_dict

        if needle_mode not in self.PROBE_NEEDLE_MODES:
            problems.append(f'probe_needle_mode {needle_mode!r} is not valid (valid: {list(self.PROBE_NEEDLE_MODES)})')
        if not isinstance(hybridization_list, list) or not hybridization_list:
            problems.append(f'the {list_name} is empty')
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
