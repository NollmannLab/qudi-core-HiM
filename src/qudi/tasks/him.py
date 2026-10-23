# -*- coding: utf-8 -*-
"""
qudi-core-HiM task: Hi-M experiment - for each probe (RT): hybridization, imaging of every ROI,
photobleaching and needle rinse.

Structure - one file for all setups:
  - HiMTaskBase: the shared sequence (checks, GUI locks, cycles, cleanup). The fluidics steps
    (injection, incubation, needle, valves, injections-file reading and validation) come from
    FluidicsStepsMixin (tasks/common/fluidics_steps.py), the progress display from
    ProgressModuleTask (tasks/common/progress.py).
  - HiMSDTask / HiMRAMMTask / HiMDummyTask: one subclass per setup. The imaging at each ROI comes
    from the per-microscope mixins of tasks/common/imaging_steps.py (SDImagingMixin,
    RAMMImagingMixin, DummyImagingMixin), shared with the ROI scan task; the valve layout is the
    one of the fluidics task of the same setup.
The path of the experiment YAML written by the experiment configurator and the valve outlet of the
probe needle differ between machines: each microscope's config sets them in the task's entry with
"options: user_config_path: ... probe_valve_number: ..." (applied by logic/taskrunner_logic.py).

Translated from the legacy qudi tasks tasks/legacy/HiM_imaging_SD.py and
tasks/legacy/HiM_imaging_RAMM.py. Not in this version: email alert, task log file, data transfer
to the network, resume, autofocus image comparison (HiMSDTask._check_autofocus is a placeholder).

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

import copy
import math
import os
from datetime import datetime
from glob import glob
from time import monotonic

import yaml
from qtpy import QtCore

from qudi.core.connector import Connector
from qudi.tasks.common.fluidics_steps import FluidicsStepsMixin
from qudi.tasks.common.imaging_steps import SDImagingMixin, RAMMImagingMixin, DummyImagingMixin
from qudi.tasks.common.progress import ProgressModuleTask
from qudi.tasks.fluidics import FluidicsSDTask, FluidicsRAMMTask


class _Invoker(QtCore.QObject):
    """Runs a callable in the thread this object lives in; the caller waits for the end of the call."""
    _sigCall = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self._sigCall.connect(self._run, QtCore.Qt.BlockingQueuedConnection)

    @QtCore.Slot(object)
    def _run(self, job):
        job()


def _call_in_thread_of(obj, func):
    """Call func() in the thread of the QObject obj and return its result (exceptions re-raised).
    Used for logic methods that start or stop a QTimer of the logic module (e.g. the rinsing
    timer of the flow logic), which only works from the thread the timer lives in."""
    if QtCore.QThread.currentThread() == obj.thread():
        return func()
    outcome = {}

    def job():
        try:
            outcome['result'] = func()
        except Exception as err:
            outcome['error'] = err

    invoker = _Invoker()
    invoker.moveToThread(obj.thread())
    invoker._sigCall.emit(job)
    invoker.deleteLater()
    if 'error' in outcome:
        raise outcome['error']
    return outcome.get('result')


class HiMTaskBase(FluidicsStepsMixin, ProgressModuleTask):
    """Shared Hi-M experiment: checks, then for each probe (RT), sorted by tube: hybridization ->
    imaging of every ROI -> photobleaching -> needle rinse.

    Not meant to be configured directly - use a setup subclass. Options (config "options:"):
        user_config_path    experiment YAML written by the experiment configurator (required)
        probe_valve_number  outlet of the buffer valve connected to the probe needle (required, int)

    Experiment YAML (user_config_path): sample_name, roi_list_path, injections_path,
    imaging_sequence ([[wavelength, intensity %], ...]), num_z_planes, and the keys read by the
    subclass (_read_microscope_parameters).
    Injections file (injections configurator): buffer {outlet: name}, probes {tube: name},
    hybridization list, photobleaching list, probe_needle_mode 'next' | 'same' (missing -> 'next').

    Needle: each cycle starts with the needle in the tube of its probe. With 'next', every further
    injection from the probe valve in the hybridization list goes to the next tube (tube + 1, + 2,
    ...); with 'same' the needle stays in the probe tube. The photobleaching list uses the buffer
    valve only (the needle is not moved).

    Everything is checked before any hardware call; all problems are reported in one error. During
    the run the GUIs of the valves, flow control, robot, ROIs and lasers are locked and the stage
    moves at scan_stage_velocity. _cleanup() always stops the pressure regulation, volume
    measurement and rinsing, sets the pressure to 0, puts the valves in cleanup_valve_positions,
    ends the imaging, moves the stage back to the first ROI, restores the stage velocity and
    unlocks the GUIs.

    Hi-M hooks (overridden by the setup subclasses):
        _read_microscope_parameters(params)  extra keys of the experiment YAML
        _check_microscope() -> list          problems found (checked with the other problems)
        _create_data_folder() -> str         folder where qudi writes its files (self.directory)
        _file_name(rt, roi_name) -> str      name of the stack of one ROI for one probe
    Imaging hooks (imaging mixin): _prepare_imaging(), _image_roi(roi, file_name),
    _end_imaging(), scan_stage_velocity.
    """

    valve_logic = Connector(interface='FluidicsValveLogic')
    flow_logic = Connector(interface='FluidicsFlowLogic')
    robot_logic = Connector(interface='FluidicsRobotLogic')
    roi_logic = Connector(interface='RoiLogic')
    laser_logic = Connector(interface='LaserControlLogic')
    trigger_logic = Connector(interface='TriggerLogic', optional=True)

    # options, set by the config ("options:")
    user_config_path = None
    probe_valve_number = None

    needle_rinsing_duration_s = 30  # rinsing of the needle after each cycle (s)

    _EXPERIMENT_KEYS = ('sample_name', 'roi_list_path', 'injections_path', 'imaging_sequence', 'num_z_planes')
    _RINSE_TIMEOUT_MARGIN_S = 30.0  # the rinse must end within needle_rinsing_duration_s + this margin
    # problems of FluidicsStepsMixin._validate checked once for the whole experiment instead
    _SKIPPED_VALIDATION_PROBLEMS = ('robot origin', 'probe list is empty', 'probe injection(s) from tube')

    def _setup(self) -> None:
        # attributes used by _cleanup(): set first, so that _cleanup() also works if fetching a
        # connector fails
        self._hardware_touched = False
        self._gui_locked = False
        self._arrival_slot = None
        self._needle_arrived_at = None
        self._needle_mode = None
        self._tubes_used = []
        self._prev_stage_velocity = None
        self._cycles_done = 0
        self._cycles = []
        self.roi_names = []
        self.directory = None
        self.prefix = ''
        self.sample_name = None
        self.save_path = None
        self.imaging_sequence = None
        self.num_z_planes = None
        self._valve = self._flow = self._robot = None
        self._roi_logic = self._laser_logic = self._trigger_logic = None

        self._valve = self.valve_logic()
        self._flow = self.flow_logic()
        self._robot = self.robot_logic()
        self._roi_logic = self.roi_logic()
        self._laser_logic = self.laser_logic()
        self._trigger_logic = self.trigger_logic()

    # ==============================================================================================
    # Main entry point
    # ==============================================================================================

    def _run(self) -> dict:
        probe_valve = self._check_options()

        # 1. parameters: experiment YAML and injections file, no hardware call
        params = self._read_yaml(self.user_config_path, 'experiment file')
        problems = [f'experiment file {self.user_config_path}: {key!r} missing'
                    for key in self._EXPERIMENT_KEYS if params.get(key) is None]
        self.sample_name = params.get('sample_name')
        self.roi_list_path = params.get('roi_list_path')
        self.injections_path = params.get('injections_path')
        self.imaging_sequence = params.get('imaging_sequence') or []
        self.num_z_planes = params.get('num_z_planes')
        self._read_microscope_parameters(params)

        injections = None
        if self.injections_path:
            try:
                buffer_valves, probes, hyb_list, needle_mode = self._read_injections(self.injections_path)
                _, _, pb_list, _ = self._read_injections(self.injections_path, 'photobleaching list')
                injections = (buffer_valves, probes, hyb_list, pb_list, needle_mode)
            except RuntimeError as err:
                problems.append(str(err))

        # 2. checks, all problems in one error before any hardware call
        hyb_steps, pb_steps, probes = [], [], {}
        if injections is not None:
            buffer_valves, probes, hyb_list, pb_list, needle_mode = injections
            self._needle_mode = needle_mode
            hyb_steps = self._validated(problems, 'hybridization list', buffer_valves, probes, hyb_list,
                                        needle_mode, probe_valve)
            # an empty photobleaching list is allowed (no photobleaching step)
            if pb_list:
                pb_steps = self._validated(problems, 'photobleaching list', buffer_valves, probes, pb_list,
                                           needle_mode, probe_valve)
            if not probes:
                problems.append('the probe list of the injections file is empty')
            else:
                problems.extend(self._check_probe_tubes(probes, self._count_probe_injections(
                    hyb_list, buffer_valves, probe_valve), needle_mode))

        if self._robot.origin is None:
            self._warn_needle_position()
            problems.append('the needle position (robot origin) is not defined - set it in the Fluidics GUI '
                            '("Set position 1")')

        if self.roi_list_path:
            try:
                self._roi_logic.load_roi_list(self.roi_list_path)
                self.roi_names = list(self._roi_logic.roi_names)
            except Exception as err:
                problems.append(f'the ROI list {self.roi_list_path} could not be loaded: {err}')
            else:
                if not self.roi_names:
                    problems.append(f'the ROI list {self.roi_list_path} is empty or could not be loaded')

        problems.extend(self._check_microscope())
        problems = list(dict.fromkeys(problems))  # same problem found twice (both lists) reported once
        if problems:
            raise RuntimeError(f'Hi-M task not started - {len(problems)} problem(s):\n  - ' + '\n  - '.join(problems))

        # one cycle per probe, sorted by tube
        self._cycles = sorted(probes.items())
        for step in pb_steps:
            step['probe'] = False  # photobleaching: buffer valve only, the needle is not moved

        # 3. lock the GUIs, lasers off, scan stage velocity (restored in _cleanup)
        self._check_interrupt()
        self._hardware_touched = True
        self._gui_locked = True
        self._valve.disable_valve_positioning()
        self._flow.disable_flowcontrol_actions()
        self._robot.disable_positioning_actions()
        self._roi_logic.disable_tracking_mode()
        self._roi_logic.disable_roi_actions()
        self._laser_logic.stop_laser_output()
        self._laser_logic.disable_laser_actions()
        self._prev_stage_velocity = dict(self._roi_logic.get_stage_velocity(list(self.scan_stage_velocity)))
        if not self._roi_logic.set_stage_velocity(self.scan_stage_velocity):
            raise RuntimeError(f'Could not set the scan stage velocity {self.scan_stage_velocity} - see the log.')

        # 4. plan
        self._log_plan(hyb_steps, pb_steps)
        self._check_interrupt()

        # 5. imaging preparation, data folder, parameters file
        self._prepare_imaging()
        self.directory = self._create_data_folder()
        self._save_parameters(params, injections)

        # 6. cycles: hybridization -> imaging -> photobleaching -> needle rinse
        total = len(self._cycles)
        for number, (tube, rt) in enumerate(self._cycles, 1):
            self._check_interrupt()
            self._report_progress(f'Cycle {number}/{total}', rt)
            label = f'Cycle {number}/{total} - {rt}'
            self._hybridization(label, rt, tube, hyb_steps)
            self._imaging(label, rt)
            self._photobleaching(label, rt, pb_steps)
            self._rinse_needle(label)
            self._cycles_done = number

        # 7. summary
        self._report_progress(f'{total}/{total}', 'Done')
        return {'cycles_done': self._cycles_done,
                'cycles_total': total,
                'probes': [rt for _, rt in self._cycles],
                'rois': len(self.roi_names),
                'directory': self.directory,
                'probe_needle_mode': self._needle_mode,
                'tubes_used': list(self._tubes_used)}

    def _cleanup(self) -> None:
        """Stop the fluidics, valves to cleanup_valve_positions, end of the imaging, stage back to the
        first ROI at its previous velocity, GUIs unlocked. Each step is protected on its own; never
        raises."""
        if getattr(self, '_arrival_slot', None) is not None:
            try:
                self._robot.sigStageMovedToTarget.disconnect(self._arrival_slot)
            except Exception as err:
                self.log.error(f'Cleanup: could not disconnect from the robot signal: {err}')
            self._arrival_slot = None

        if getattr(self, '_hardware_touched', False):
            # fluidics: regulation, volume measurement, rinsing, pressure
            for action, call in (('stop the pressure regulation', lambda: self._flow.stop_pressure_regulation_loop()),
                                 ('stop the volume measurement', lambda: self._flow.stop_volume_measurement()),
                                 ('stop the rinsing', self._stop_rinsing),
                                 ('set the pressure to 0', lambda: self._flow.set_pressure(0.0))):
                try:
                    call()
                except Exception as err:
                    self.log.error(f'Cleanup: could not {action}: {err}')

            # valves
            for address, position in self.cleanup_valve_positions.items():
                try:
                    self._set_valve(address, position)
                except Exception as err:
                    self.log.error(f'Cleanup: {err}')

            # setup-specific end of the imaging (lasers, triggers)
            try:
                self._end_imaging()
            except Exception as err:
                self.log.error(f'Cleanup: could not end the imaging: {err}')

            # stage: back to the first ROI, previous velocity
            if self.roi_names:
                try:
                    self._roi_logic.set_active_roi(name=self.roi_names[0])
                    self._roi_logic.go_to_roi_xy()
                except Exception as err:
                    self.log.error(f'Cleanup: could not move the stage back to the first ROI: {err}')
            if self._prev_stage_velocity:
                try:
                    if not self._roi_logic.set_stage_velocity(self._prev_stage_velocity):
                        self.log.error(f'Cleanup: could not restore the stage velocity {self._prev_stage_velocity}.')
                except Exception as err:
                    self.log.error(f'Cleanup: could not restore the stage velocity: {err}')

        # GUIs locked in step 3
        if getattr(self, '_gui_locked', False):
            for name, unlock in (('valve', lambda: self._valve.enable_valve_positioning()),
                                 ('flow control', lambda: self._flow.enable_flowcontrol_actions()),
                                 ('robot', lambda: self._robot.enable_positioning_actions()),
                                 ('ROI tracking', lambda: self._roi_logic.enable_tracking_mode()),
                                 ('ROI', lambda: self._roi_logic.enable_roi_actions()),
                                 ('laser', lambda: self._laser_logic.enable_laser_actions())):
                try:
                    unlock()
                except Exception as err:
                    self.log.error(f'Cleanup: could not unlock the {name} GUI: {err}')
            self._gui_locked = False

        self.log.info(f'Hi-M task ended after {getattr(self, "_cycles_done", 0)}/{len(getattr(self, "_cycles", []))} '
                      f'cycle(s).')

    # ==============================================================================================
    # Cycle steps
    # ==============================================================================================

    def _hybridization(self, label, rt, tube, hyb_steps) -> None:
        """Needle in the probe tube, start valve positions, hybridization steps, cleanup positions."""
        steps = copy.deepcopy(hyb_steps)
        probe_steps = [step for step in steps if step['probe']]
        for count, step in enumerate(probe_steps):
            step['tube'] = tube + count if self._needle_mode == 'next' else tube

        self._move_needle(tube, label)
        self._set_valves(self.start_valve_positions)
        n = len(steps)
        for number, step in enumerate(steps, 1):
            self._check_interrupt()
            self.log.info(f'{rt} - hybridization step {number}/{n}: {self._describe(step)}')
            if step['kind'] == 'injection':
                self._report_progress(label, f'Hybridization {number}/{n} - Injecting {step["product"]}', log=False)
                self._inject(number, step, probe_steps, label)
            else:
                self._report_progress(label, f'Hybridization {number}/{n} - Incubating {step["time"]:g} s', log=False)
                self._incubate(step, label)
        self._set_valves(self.cleanup_valve_positions)

    def _imaging(self, label, rt) -> None:
        """Image every ROI, then move the stage back to the first ROI."""
        m = len(self.roi_names)
        for number, roi_name in enumerate(self.roi_names, 1):
            self._check_interrupt()
            self._report_progress(label, f'ROI {number}/{m}', log=False)
            self.log.info(f'{rt} - moving to {roi_name} ({number}/{m})')
            self._roi_logic.set_active_roi(name=roi_name)
            self._roi_logic.go_to_roi_xy()
            self._roi_logic.stage_wait_for_idle()
            self._check_interrupt()
            self._image_roi(roi_name, self._file_name(rt, roi_name))
        self._roi_logic.set_active_roi(name=self.roi_names[0])
        self._roi_logic.go_to_roi_xy()

    def _photobleaching(self, label, rt, pb_steps) -> None:
        """Start valve positions, photobleaching steps (buffer valve only), cleanup positions."""
        if not pb_steps:
            return
        steps = copy.deepcopy(pb_steps)
        self._set_valves(self.start_valve_positions)
        n = len(steps)
        for number, step in enumerate(steps, 1):
            self._check_interrupt()
            self.log.info(f'{rt} - photobleaching step {number}/{n}: {self._describe(step)}')
            if step['kind'] == 'injection':
                self._report_progress(label, f'Photobleaching {number}/{n} - Injecting {step["product"]}', log=False)
                self._inject(number, step, [], label)
            else:
                self._report_progress(label, f'Photobleaching {number}/{n} - Incubating {step["time"]:g} s',
                                      log=False)
                self._incubate(step, label)
        self._set_valves(self.cleanup_valve_positions)

    def _rinse_needle(self, label) -> None:
        """Rinse the needle (flow logic rinsing pump and rinsing valve positions) and wait for the end
        of the rinse (interruptible); raise if it has not ended within the duration + 30 s."""
        duration = float(self.needle_rinsing_duration_s)
        self._report_progress(label, f'Rinsing needle ({duration:g} s)')
        _call_in_thread_of(self._flow, lambda: self._flow.start_rinsing(duration))
        start = monotonic()
        while self._flow.rinsing_enabled:
            elapsed = monotonic() - start
            if elapsed > duration + self._RINSE_TIMEOUT_MARGIN_S:
                raise RuntimeError(f'The needle rinse did not end within {duration + self._RINSE_TIMEOUT_MARGIN_S:g} s.')
            self._report_live(label, f'Rinsing needle - {max(0, math.ceil(duration - elapsed))} s left')
            self._interruptible_sleep(self._MAX_WAIT_STEP_S)

    def _stop_rinsing(self) -> None:
        if self._flow.rinsing_enabled:
            _call_in_thread_of(self._flow, lambda: self._flow.stop_rinsing(emit_signal=True))

    # ==============================================================================================
    # Checks, options, files
    # ==============================================================================================

    def _check_options(self) -> int:
        """Return probe_valve_number as an int; raise if an option is not set."""
        if self.user_config_path in (None, '', 'TO FILL'):
            raise RuntimeError(f'user_config_path not set for task {type(self).__name__} - add '
                               f'`options: user_config_path: ...` to this task\'s entry in the config file')
        if self.probe_valve_number in (None, ''):
            raise RuntimeError(f'probe_valve_number not set for task {type(self).__name__} - add '
                               f'`options: probe_valve_number: ...` to this task\'s entry in the config file')
        try:
            return int(self.probe_valve_number)
        except (TypeError, ValueError):
            raise RuntimeError(f'probe_valve_number must be an integer, got {self.probe_valve_number!r}.')

    def _validated(self, problems, list_name, buffer_valves, probes, step_list, needle_mode, probe_valve) -> list:
        """Steps of step_list checked by FluidicsStepsMixin._validate. Its problems are added to problems
        instead of being raised: step problems prefixed with the list name; the robot origin, empty
        probe list and tube range are left out (checked once for the whole experiment by _run and
        _check_probe_tubes)."""
        try:
            return self._validate(buffer_valves, probes, step_list, needle_mode, probe_valve, list_name=list_name)
        except RuntimeError as err:
            for line in str(err).split('\n')[1:]:
                text = line.strip()
                text = text[2:] if text.startswith('- ') else text
                if not text or any(skip in text for skip in self._SKIPPED_VALIDATION_PROBLEMS):
                    continue
                problems.append(f'{list_name}: {text}' if text.startswith('step ') else text)
            return []

    @staticmethod
    def _count_probe_injections(step_list, buffer_valves, probe_valve) -> int:
        """Number of entries of step_list injecting from the probe valve (malformed entries ignored, so
        that the tubes are also checked when another step of the list has a problem)."""
        count = 0
        for entry in step_list if isinstance(step_list, list) else []:
            if isinstance(entry, dict) and entry.get('product') in buffer_valves:
                try:
                    count += int(buffer_valves[entry['product']]) == probe_valve
                except (TypeError, ValueError):
                    pass
        return count

    def _check_probe_tubes(self, probes, n_probe, needle_mode) -> list:
        """Tubes used by each cycle: the probe tube and, with 'next', one further tube per further
        probe-valve injection (n_probe injections per cycle). They must not be another listed probe
        nor beyond the last tube of the robot."""
        problems = []
        n_tubes = max(1, n_probe) if needle_mode == 'next' else 1
        max_tubes = getattr(self._robot, 'max_num_probes', 0)
        for tube, rt in sorted(probes.items()):
            last = tube + n_tubes - 1
            for other in range(tube + 1, last + 1):
                if other in probes:
                    problems.append(f"probe {rt} (tube {tube}): with probe_needle_mode 'next' its {n_probe} probe "
                                    f"injections use tubes {tube}-{last}, but tube {other} is probe {probes[other]}")
            if max_tubes and last > max_tubes:
                problems.append(f'probe {rt} (tube {tube}): needs tube {last}, the robot has {max_tubes} tubes')
        return problems

    def _log_plan(self, hyb_steps, pb_steps) -> None:
        self.log.info(f'Hi-M experiment {self.sample_name}: {len(self._cycles)} probe(s), {len(self.roi_names)} '
                      f'ROI(s), needle mode {self._needle_mode!r}.')
        self.log.info('  probes: ' + ', '.join(f'{rt} (tube {tube})' for tube, rt in self._cycles))
        self.log.info(f'  hybridization: {len(hyb_steps)} step(s)')
        for number, step in enumerate(hyb_steps, 1):
            self.log.info(f'    {number}. {self._describe(step)}')
        self.log.info(f'  photobleaching: {len(pb_steps)} step(s)')
        for number, step in enumerate(pb_steps, 1):
            self.log.info(f'    {number}. {self._describe(step)}')

    def _save_parameters(self, params, injections) -> None:
        """Write HiM_parameters.yml in self.directory: experiment parameters, probes, hybridization and
        photobleaching lists, imaging parameters, ROI positions."""
        _, probes, hyb_list, pb_list, needle_mode = injections
        rois = {}
        for roi_name in self.roi_names:
            pos = list(self._roi_logic.get_roi_position(roi_name))
            z = pos[2] if len(pos) > 2 else None
            rois[roi_name] = f'X={pos[0]} - Y={pos[1]} - Z={z}'
        param = {'1- global parameters': params,
                 '2- fluidic parameters': {'probes': probes,
                                           'probe_needle_mode': needle_mode,
                                           'hybridization list': hyb_list,
                                           'photobleaching list': pb_list},
                 '3- imaging parameters': {'number of laser lines': len(self.imaging_sequence),
                                           'imaging sequence': self.imaging_sequence,
                                           'number of z planes': self.num_z_planes},
                 '4- ROIs': rois}
        path = os.path.join(self.directory, 'HiM_parameters.yml')
        with open(path, 'w') as outfile:
            yaml.safe_dump(param, outfile, default_flow_style=False, sort_keys=False)
        self.log.info(f'Saved the Hi-M parameters to {path}')

    def _append_movie_name(self, movie_name: str) -> None:
        with open(os.path.join(self.directory, 'movie_name.txt'), 'a+') as outfile:
            outfile.write(movie_name)
            outfile.write('\n')

    # ==============================================================================================
    # Hi-M hooks - defaults, overridden by the setup subclasses
    # ==============================================================================================

    def _read_microscope_parameters(self, params) -> None:
        """Read the setup-specific keys of the experiment YAML (none by default)."""
        pass

    def _check_microscope(self) -> list:
        """Setup-specific checks before any hardware call; return the problems found."""
        return []

    def _create_data_folder(self) -> str:
        """Create save_path/YYYY_MM_DD/{prefix}_HiM_{sample_name} (prefix: next 3-digit number in the
        day folder, sets self.prefix) and return it."""
        if not self.save_path:
            raise RuntimeError('No save_path for the data folder.')
        day_folder = os.path.join(self.save_path, datetime.today().strftime('%Y_%m_%d'))
        os.makedirs(day_folder, exist_ok=True)
        folders = [name for name in os.listdir(day_folder) if os.path.isdir(os.path.join(day_folder, name))]
        self.prefix = str(len(folders) + 1).zfill(3)
        path = os.path.join(day_folder, f'{self.prefix}_HiM_{self.sample_name}')
        os.makedirs(path)
        return path

    def _file_name(self, rt: str, roi_name: str) -> str:
        """scan_{prefix}_{rt}_{roi_number}_ROI, e.g. ROI_007 -> scan_001_RT1_007_ROI."""
        roi_number = roi_name.strip('ROI_')
        return f'scan_{self.prefix}_{rt}_{roi_number}_ROI'

    # imaging hooks - implemented by the imaging mixin of each setup
    def _prepare_imaging(self) -> None:
        raise NotImplementedError(f'{type(self).__name__} has no imaging mixin.')

    def _image_roi(self, roi_name: str, file_name: str) -> None:
        raise NotImplementedError(f'{type(self).__name__} has no imaging mixin.')

    def _end_imaging(self) -> None:
        pass


class HiMSDTask(SDImagingMixin, HiMTaskBase):
    """Hi-M on the spinning disk: the imaging of each ROI is done by ZEN (autofocus block, then
    acquisition block, synchronized over DAQ triggers - see SDImagingMixin); trigger_logic is
    required. Valve layout of FluidicsSDTask.

    Experiment YAML, extra keys: zen_saving_path (folder where ZEN creates the folder of the
    experiment), zen_ref_images_path (reference images of the autofocus), correlation_threshold.
    Before waiting for ZEN "ready", the log gives the ZEN settings: number of acquisition loops
    (probes x ROIs), C (laser lines) and Z (planes). The new folder created by ZEN in
    zen_saving_path when the experiment starts is found by comparing the folders before and after;
    qudi writes its files (HiM_parameters.yml, movie_name.txt) in its "metadata" subfolder. As no
    data folder is created by qudi, self.prefix stays '' and the file names are
    scan__<RT>_<roi number>_ROI.

    Config example for copy-paste (logic: task_runner: options: module_tasks:):

        him:
          module.Class: 'qudi.tasks.him.HiMSDTask'
          connect:
            valve_logic: fluidics_valve_logic
            flow_logic: fluidics_flow_logic
            robot_logic: pipetting_robot_logic
            roi_logic: roi_logic
            laser_logic: laser_control_logic
            trigger_logic: trigger_logic
          options:
            user_config_path: '/path/to/qudi_task_config_files/him_task_sd_epi.yaml'
            probe_valve_number: 3
    """

    trigger_logic = Connector(interface='TriggerLogic')

    start_valve_positions = FluidicsSDTask.start_valve_positions
    needle_move_valve_positions = FluidicsSDTask.needle_move_valve_positions
    needle_moved_valve_positions = FluidicsSDTask.needle_moved_valve_positions
    incubation_valve_positions = FluidicsSDTask.incubation_valve_positions
    incubation_end_valve_positions = FluidicsSDTask.incubation_end_valve_positions
    cleanup_valve_positions = FluidicsSDTask.cleanup_valve_positions

    _ZEN_FOLDER_ATTEMPTS = 10  # attempts to find the new ZEN folder, 1 s apart

    def _read_microscope_parameters(self, params) -> None:
        self.zen_saving_path = params.get('zen_saving_path')
        self.zen_ref_images_path = params.get('zen_ref_images_path')
        self.correlation_threshold = params.get('correlation_threshold')
        self._zen_directory = None
        self._autofocus_check_logged = False

    def _check_microscope(self) -> list:
        problems = []
        for key in ('zen_saving_path', 'zen_ref_images_path'):
            path = getattr(self, key)
            if not path:
                problems.append(f'experiment file: {key!r} missing')
            elif not os.path.isdir(path):
                problems.append(f'{key} {path} is not an existing folder')
        return problems

    def _prepare_imaging(self) -> None:
        """ZEN settings in the log, SD imaging preparation (laser source, wait for ZEN "ready"), then
        the new folder created by ZEN."""
        folders_before = self._zen_folders()
        self.log.warning(f'ZEN: number of acquisition loops = {len(self._cycles)} x {len(self.roi_names)} = '
                         f'{len(self._cycles) * len(self.roi_names)}, C = {len(self.imaging_sequence)}, '
                         f'Z = {self.num_z_planes}')
        super()._prepare_imaging()
        self._zen_directory = self._find_new_zen_folder(folders_before)

    def _zen_folders(self) -> set:
        return {path for path in glob(os.path.join(self.zen_saving_path, '*')) if os.path.isdir(path)}

    def _find_new_zen_folder(self, folders_before) -> str:
        """The single folder of zen_saving_path that was not there before ZEN started; checked up to
        _ZEN_FOLDER_ATTEMPTS times, 1 s apart."""
        for attempt in range(self._ZEN_FOLDER_ATTEMPTS):
            new = sorted(self._zen_folders() - folders_before)
            if len(new) == 1:
                self.log.info(f'ZEN will save the data in the following folder : {new[0]}')
                return new[0]
            if len(new) > 1:
                raise RuntimeError(f'More than one folder were found ({", ".join(new)}). The acquisition is aborted.')
            if attempt < self._ZEN_FOLDER_ATTEMPTS - 1:
                self._interruptible_sleep(1.0)
        raise RuntimeError(f'No new file was created by ZEN in {self.zen_saving_path} - check if the reference '
                           f'folder indicated in the parameters is correct. The acquisition is aborted.')

    def _create_data_folder(self) -> str:
        """<new ZEN folder>/metadata (created)."""
        path = os.path.join(self._zen_directory, 'metadata')
        os.makedirs(path, exist_ok=True)
        return path

    def _check_autofocus(self, roi_name: str) -> None:
        """PLACEHOLDER - logs once per run that the check is not implemented.

        To do (legacy HiM_imaging_SD.py, check_focus / init_autofocus_safety):
          - at start, load the reference autofocus images from zen_ref_images_path
            (autofocus_reference.npy, or the czi images sorted in acquisition order);
          - after the ZEN autofocus block, wait for the new autofocus image saved by ZEN in the ZEN
            folder (*_AcquisitionBlock1_pt*.czi);
          - compute the correlation score between this image and the reference image of this ROI;
          - score below correlation_threshold: a warning the first time, stop the experiment if it
            happens twice in a row; otherwise the new image replaces the reference of this ROI;
          - save the scores (correlation.npy) and the reference images (autofocus_reference.npy,
            reference_images_<RT>.npy) in the metadata folder.
        """
        if not self._autofocus_check_logged:
            self._autofocus_check_logged = True
            self.log.warning('Autofocus check not implemented yet (zen_ref_images_path, correlation_threshold)')


class HiMRAMMTask(RAMMImagingMixin, HiMTaskBase):
    """Hi-M on the RAMM - PLACEHOLDER: the imaging is not migrated yet; _check_microscope reports it, so
    the task stops before any hardware call. Valve layout of FluidicsRAMMTask.

    To do, following legacy/HiM_imaging_RAMM.py:
      - checks: autofocus calibrated and setpoint defined; free disk space for
        probes x ROIs x planes x laser lines images (size per image by file format) x 1.1;
      - camera prepared for multichannel imaging (frames = planes x laser lines, below the camera
        maximum), FPGA session with the HiM bitfile, laser line intensities;
      - for each ROI: axial correction (z difference between the ROIs, not for the very first ROI),
        autofocus search with a stop after two failures in a row, piezo position correction,
        z-stack driven by the FPGA (piezo positioned, DAQ 'piezo ready' pulse, wait for the FPGA
        'acquisition done' with timeout), piezo back to the start position;
      - saving in <folder>/<ROI>/<RT>/ as tif, npy, hdf5 or fits, file names
        scan_{prefix}_{RT}_{roi number}_ROI.<format> with a metadata file
        scan_{prefix}_{RT}_{roi number}_ROI_metadata.yaml (metadata template + acquisition,
        autofocus, filter, laser, ROI and fluidics values).

    Config example for copy-paste (logic: task_runner: options: module_tasks:):

        # him:
        #   module.Class: 'qudi.tasks.him.HiMRAMMTask'
        #   connect:
        #     valve_logic: fluidics_valve_logic
        #     flow_logic: fluidics_flow_logic
        #     robot_logic: pipetting_robot_logic
        #     roi_logic: roi_logic
        #     laser_logic: laser_control_logic
        #   options:
        #     user_config_path: 'TO FILL'
        #     probe_valve_number: 7
    """

    start_valve_positions = FluidicsRAMMTask.start_valve_positions
    needle_move_valve_positions = FluidicsRAMMTask.needle_move_valve_positions
    needle_moved_valve_positions = FluidicsRAMMTask.needle_moved_valve_positions
    incubation_valve_positions = FluidicsRAMMTask.incubation_valve_positions
    incubation_end_valve_positions = FluidicsRAMMTask.incubation_end_valve_positions
    cleanup_valve_positions = FluidicsRAMMTask.cleanup_valve_positions

    def _check_microscope(self) -> list:
        return ['Hi-M imaging on the RAMM is not migrated yet (focus logic, FPGA) - see legacy/HiM_imaging_RAMM.py']


class HiMDummyTask(DummyImagingMixin, HiMTaskBase):
    """Hi-M without imaging hardware, for testing with dummy_config.cfg: RAMM valve layout on the dummy
    valves (a, b, c), a fixed interruptible wait per ROI (DummyImagingMixin), data folder
    save_path/YYYY_MM_DD/NNN_HiM_<sample_name> (experiment YAML key save_path).

    Config example (dummy_config.cfg, logic: task_runner: options: module_tasks:):

        him_dummy:
          module.Class: 'qudi.tasks.him.HiMDummyTask'
          connect:
            valve_logic: fluidics_valve_logic
            flow_logic: fluidics_flow_logic
            robot_logic: pipetting_robot_logic
            roi_logic: roi_logic
            laser_logic: laser_control_logic
          options:
            user_config_path: '/home/jb/qudi/qudi_task_config_files/him_task_dummy.yaml'
            probe_valve_number: 7
    """

    start_valve_positions = FluidicsRAMMTask.start_valve_positions
    needle_move_valve_positions = FluidicsRAMMTask.needle_move_valve_positions
    needle_moved_valve_positions = FluidicsRAMMTask.needle_moved_valve_positions
    incubation_valve_positions = FluidicsRAMMTask.incubation_valve_positions
    incubation_end_valve_positions = FluidicsRAMMTask.incubation_end_valve_positions
    cleanup_valve_positions = FluidicsRAMMTask.cleanup_valve_positions

    def _read_microscope_parameters(self, params) -> None:
        self.save_path = params.get('save_path')

    def _check_microscope(self) -> list:
        return [] if self.save_path else ["experiment file: 'save_path' missing"]
