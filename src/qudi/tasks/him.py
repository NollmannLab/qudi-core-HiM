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
The path of the experiment YAML written by the experiment configurator differs between machines:
each microscope's config sets it in the task's entry with "options: user_config_path: ..." (applied
by logic/taskrunner_logic.py). The valve outlet of the probe needle is read from the injections file
(its 'Probe' buffer entry, written by the injections configurator from its option probe_valve_outlet).

Translated from the legacy qudi tasks tasks/legacy/HiM_imaging_SD.py and
tasks/legacy/HiM_imaging_RAMM.py. Not in this version: email alert, resume. The task log file is
HiM_task.log (all setups); the autofocus check and the online data transfer to the server
(common/data_transfer.py) are done on the spinning disk (HiMSDTask).

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

import concurrent.futures
import copy
import csv
import logging
import logging.handlers
import math
import multiprocessing
import os
import shutil
import sys
from concurrent.futures.process import BrokenProcessPool
from contextlib import contextmanager
from glob import glob
from time import monotonic

import numpy as np

import yaml
from qtpy import QtCore

from qudi.core.connector import Connector
from qudi.core.scripting.modulescript import ModuleScriptInterrupted
from qudi.tasks.common import autofocus_check
from qudi.tasks.common.data_folders import choose_data_root, create_mirror_folder, create_run_folder, local_dated_root
from qudi.tasks.common.data_transfer import DataTransfer
from qudi.tasks.common.popups import show_warning_popup
from qudi.tasks.common.fluidics_steps import FluidicsStepsMixin
from qudi.util import autofocus_report
from qudi.tasks.common.run_metadata import (experiment_parameters_folder, fill_run_metadata, optional_metadata_template,
                                            set_metadata_field, write_metadata)
from qudi.tasks.common.sample_info import add_sample_to_run, optional_sample
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
        metadata_template   microscope metadata template (YAML, custom_config/custom_metadata_templates/,
                            same file as the basic imaging GUI's metadata_template); optional: not set ->
                            one warning, no metadata.yml; set but missing / unreadable -> reported with the
                            other problems, before any hardware call
    The obsolete option probe_valve_number is accepted but ignored (one warning at the start of the
    task): the probe valve is the outlet of the 'Probe' buffer entry of the injections file.

    Experiment YAML (user_config_path): sample_name, roi_list_path, injections_path,
    imaging_sequence ([[wavelength, intensity %], ...]), num_z_planes, save_path (local data folder),
    save_network_path (server data folder, optional), sample_file (optional; required by the SD definitions:
    YAML describing the sample, tasks/common/sample_info.py; read before any hardware call, a missing or
    unreadable file is reported with the other problems; absent or empty: no sample file), and the keys read
    by the subclass (_read_microscope_parameters). photobleaching_imaging (optional, default false; declared by
    the SD definitions): image after the photobleaching - not implemented, True only gives the warning
    "photobleaching_imaging is not implemented yet - ignored" at the start of the run.

    Data folder (all setups): <root>/YYYY_MM_DD/NNN_HiM_<sample_name>, created by qudi
    (tasks/common/data_folders.py); self.prefix = NNN. <root> is chosen before any hardware call
    (choose_data_root): save_network_path when it is set and writable, otherwise save_path (a server
    folder that is not reachable gives a warning in the log and a non-modal pop-up). qudi writes there:
        <run folder>/
            movie_name.txt, metadata.yml, HiM_task.log
            experiment_parameters/   HiM_parameters.yml (every key of the experiment file, which is not copied),
                                     injections.yml (byte copy of the injections file), sample.yml
    With a metadata template, metadata.yml: the template with Time, the Acquisition fields sample_name,
    laser_lines, laser_power_(%), number_z_planes and roi_list_(xyz) (all ROIs with their positions), and
    Fluidics: hybridization and photobleaching (the lists of the injections file); other fields as in the
    template. With a sample file: experiment_parameters/sample.yml (exact copy of the file read before the run)
    and its content as the 'Sample' section of metadata.yml (appended after the template sections, or filled in the template's
    'Sample' section).
    Injections file (injections configurator): buffer {outlet: name}, probes {tube: name},
    hybridization list, photobleaching list, probe_needle_mode 'next' | 'same' (missing -> 'next').

    Needle: each cycle starts with the needle in the tube of its probe. With 'next', every further
    injection from the probe valve in the hybridization list goes to the next tube (tube + 1, + 2,
    ...); with 'same' the needle stays in the probe tube. The photobleaching list uses the buffer
    valve only (the needle is not moved). Probe valve = outlet of the buffer entry 'Probe' of the
    injections file; without a 'Probe' entry (or without probe step) only buffers are injected and the
    needle is not moved.

    If the hybridization list has probe injections and the needle position (robot origin) is not
    defined, the task logs a warning, shows a message box and ends without an exception, before any
    hardware call (as the fluidics task). The plan is logged before any hardware call. Everything else
    is checked before any hardware call; all problems are reported in one error. During
    the run the GUIs of the valves, flow control, robot, ROIs and lasers are locked and the stage
    moves at scan_stage_velocity. _cleanup() always stops the pressure regulation, volume
    measurement and rinsing, sets the pressure to 0, puts the valves in cleanup_valve_positions,
    ends the imaging, moves the stage back to the first ROI, restores the stage velocity and
    unlocks the GUIs.

    Log file (all setups): the log records of the run (the task and every qudi module: fluidics, robot, ROI,
    lasers, triggers) are kept in memory from the start of _run; as soon as the run folder exists they are
    written to <run folder>/HiM_task.log ('time - level - logger - message', level INFO), then the records go
    straight to the file. _cleanup writes the line 'Hi-M task ended ...' last and closes the file (also after an
    error or an interrupt); without a run folder the records kept in memory are dropped.

    Hi-M hooks (overridden by the setup subclasses):
        _read_microscope_parameters(params)  extra keys of the experiment YAML
        _check_microscope() -> list          problems found (checked with the other problems)
        _confirm_before_start() -> bool      called after all checks, before any hardware call or GUI
                                             lock; False cancels the experiment (result
                                             {'cancelled': True, 'cycles_done': 0}, nothing to restore).
                                             Default: True (no question)
        _choose_data_root() -> str           root of the run folder, before any hardware call (default:
                                             choose_data_root)
        _create_data_folder() -> str         run folder where qudi writes its files (self.directory)
        _file_name(rt, roi_name) -> str      name of the stack of one ROI for one probe
        _end_of_run_files()                  in _cleanup, after the hardware reset, before the last log line
        _after_run_log_closed()              in _cleanup, after HiM_task.log is closed
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
    metadata_template = None  # optional: microscope metadata template (metadata.yml in the run folder)
    # obsolete option: accepted so that a config still setting it loads, ignored (warning in _run) - the
    # probe valve is read from the injections file
    probe_valve_number = None

    needle_rinsing_duration_s = 30  # rinsing of the needle after each cycle (s)

    # required keys of the experiment file; a setup subclass may override it. num_z_planes is read, written in
    # HiM_parameters.yml and in metadata.yml only when it is one of these keys.
    _EXPERIMENT_KEYS = ('sample_name', 'roi_list_path', 'injections_path', 'imaging_sequence', 'num_z_planes',
                        'save_path')
    PHOTOBLEACHING_IMAGING_WARNING = 'photobleaching_imaging is not implemented yet - ignored'
    _RINSE_TIMEOUT_MARGIN_S = 30.0  # the rinse must end within needle_rinsing_duration_s + this margin
    # problems of FluidicsStepsMixin._validate checked once for the whole experiment instead
    _SKIPPED_VALIDATION_PROBLEMS = ('robot origin', 'probe list is empty', 'probe injection(s) from tube')

    def _setup(self) -> None:
        # attributes used by _cleanup(): set first, so that _cleanup() also works if fetching a
        # connector fails
        self._hardware_touched = False
        self._gui_locked = False
        self._log_buffer = None        # records of the run kept until HiM_task.log is opened
        self._log_file_handler = None  # HiM_task.log
        self._arrival_slot = None
        self._needle_arrived_at = None
        self._needle_mode = None
        self._tubes_used = []
        self._prev_stage_velocity = None
        self._cycles_done = 0
        self._cycles = []
        self.roi_names = []
        self.directory = None
        self._parameters_dir = None  # <metadata folder>/experiment_parameters
        self.prefix = ''
        self.sample_name = None
        self.save_path = None
        self.save_network_path = ''
        self._data_root = None
        self._metadata_template = None
        self._sample = None  # sample file of the run (sample_info.SampleFile; None: no sample file)
        self.photobleaching_imaging = False  # image after the photobleaching (not implemented)
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
        self._start_run_log()
        self.log.info(f'Hi-M task started - experiment file {self.user_config_path}')
        self._check_options()

        # 1. parameters: experiment YAML and injections file, no hardware call
        params = self._read_yaml(self.user_config_path, 'experiment file')
        problems = [f'experiment file {self.user_config_path}: {key!r} missing'
                    for key in self._EXPERIMENT_KEYS if params.get(key) is None]
        try:
            self._metadata_template = optional_metadata_template(self)
        except RuntimeError as err:
            problems.append(str(err))
        self.sample_name = params.get('sample_name')
        self.roi_list_path = params.get('roi_list_path')
        self.injections_path = params.get('injections_path')
        self.imaging_sequence = params.get('imaging_sequence') or []
        self.num_z_planes = params.get('num_z_planes') if self._uses_z_planes() else None
        self.save_path = params.get('save_path')
        self.save_network_path = params.get('save_network_path') or ''
        # image after the photobleaching (optional key photobleaching_imaging): not implemented, only a warning
        self.photobleaching_imaging = bool(params.get('photobleaching_imaging') or False)
        if self.photobleaching_imaging:
            self.log.warning(self.PHOTOBLEACHING_IMAGING_WARNING)
        # sample file (optional key sample_file): read before any hardware call, copied with the run files
        try:
            self._sample = optional_sample(params.get('sample_file'))
        except RuntimeError as err:
            problems.append(str(err))
        self._read_microscope_parameters(params)

        # injections file; the probe valve is its 'Probe' buffer entry (None: no probe injection)
        injections = None
        probe_valve = None
        if self.injections_path:
            try:
                buffer_valves, probes, hyb_list, needle_mode = self._read_injections(self.injections_path)
                _, _, pb_list, _ = self._read_injections(self.injections_path, 'photobleaching list')
                probe_valve = self._probe_valve_of(buffer_valves)
                injections = (buffer_valves, probes, hyb_list, pb_list, needle_mode)
            except RuntimeError as err:
                problems.append(str(err))
        self._warn_ignored_probe_option(probe_valve, file_read=injections is not None)

        # needle position (robot origin) needed when the hybridization list has probe injections: warning +
        # message box, task stopped without any hardware call (as the fluidics task). Without a 'Probe' entry
        # (or without probe step) only buffers are injected: no needle move, no origin needed.
        if injections is not None and self._needle_position_missing(injections[0], injections[2], probe_valve):
            self._warn_needle_position()
            return {'aborted': 'needle position not initialised', 'cycles_done': 0}

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

        # setup-specific confirmation, before any hardware call or GUI lock (e.g. ZEN settings on the SD)
        self._check_interrupt()
        if not self._confirm_before_start():
            self.log.info('Hi-M experiment cancelled by the user')
            return {'cancelled': True, 'cycles_done': 0}
        for step in pb_steps:
            step['probe'] = False  # photobleaching: buffer valve only, the needle is not moved

        # 3. plan and data root (server folder or local folder, write-tested), before any hardware call
        self._log_plan(hyb_steps, pb_steps, probe_valve)
        self._check_interrupt()
        self._data_root = self._choose_data_root()

        # 4. lock the GUIs, lasers off, scan stage velocity (restored in _cleanup)
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

        # 5. imaging preparation, data folder, parameters file
        self._prepare_imaging()
        self.directory = self._create_data_folder()
        self._parameters_dir = experiment_parameters_folder(self.directory)  # parameter files of the run
        self._open_run_log()
        self._save_parameters(params, injections)
        self._save_run_files(injections)

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

        # files of the run handled by a setup subclass (e.g. copy to the server), before the last log line
        try:
            self._end_of_run_files()
        except Exception as err:
            self.log.error(f'Cleanup: end-of-run files: {err}')
        self.log.info(f'Hi-M task ended after {getattr(self, "_cycles_done", 0)}/{len(getattr(self, "_cycles", []))} '
                      f'cycle(s).')
        self._close_run_log()
        try:
            self._after_run_log_closed()
        except Exception as err:
            self.log.error(f'Cleanup: after the log of the run: {err}')

    def _end_of_run_files(self) -> None:
        """Hook of _cleanup, after the hardware reset and before the last log line. Default: nothing."""
        pass

    def _after_run_log_closed(self) -> None:
        """Hook of _cleanup, after HiM_task.log is closed. Default: nothing."""
        pass

    # ==============================================================================================
    # Log file of the run (HiM_task.log)
    # ==============================================================================================

    _LOG_FILE_NAME = 'HiM_task.log'
    _LOG_FORMAT = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
    _LOG_BUFFER_CAPACITY = 100000  # records kept in memory before the run folder exists

    @staticmethod
    def _qudi_logger():
        """Common parent of the qudi module loggers (qudi.core.logger.get_logger: 'qudi.<module>.<Class>')."""
        return logging.getLogger('qudi')

    def _start_run_log(self) -> None:
        """Keep the log records of the run (INFO and above) in memory until HiM_task.log is opened."""
        self._close_run_log()
        buffer = logging.handlers.MemoryHandler(self._LOG_BUFFER_CAPACITY, flushLevel=logging.CRITICAL + 1,
                                                flushOnClose=False)
        buffer.setLevel(logging.INFO)
        self._qudi_logger().addHandler(buffer)
        self._log_buffer = buffer

    def _open_run_log(self) -> None:
        """Open <self.directory>/HiM_task.log, write the records kept in memory, then log straight to the file."""
        handler = logging.FileHandler(os.path.join(self.directory, self._LOG_FILE_NAME), encoding='utf-8')
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter(self._LOG_FORMAT))
        buffer, self._log_buffer = self._log_buffer, None
        if buffer is not None:
            self._qudi_logger().removeHandler(buffer)
            buffer.setTarget(handler)
            buffer.flush()
            buffer.close()
        self._qudi_logger().addHandler(handler)
        self._log_file_handler = handler

    def _close_run_log(self) -> None:
        """Remove and close the log handlers of the run; records still in memory (no run folder) are dropped.
        Never raises."""
        for name in ('_log_buffer', '_log_file_handler'):
            handler = getattr(self, name, None)
            setattr(self, name, None)
            if handler is None:
                continue
            try:
                self._qudi_logger().removeHandler(handler)
                if isinstance(handler, logging.handlers.MemoryHandler):
                    handler.buffer.clear()
                handler.close()
            except Exception as err:
                self.log.error(f'Cleanup: could not close the log of the run: {err}')

    # ==============================================================================================
    # Cycle steps
    # ==============================================================================================

    def _cycle_hybridization_steps(self, hyb_steps, tube) -> list:
        """Hybridization steps of the cycle of the probe in tube: copies, with the tube of each probe
        injection (tube, tube + 1, ... with 'next'; tube with 'same')."""
        steps = copy.deepcopy(hyb_steps)
        for count, step in enumerate(step for step in steps if step['probe']):
            step['tube'] = tube + count if self._needle_mode == 'next' else tube
        return steps

    def _hybridization(self, label, rt, tube, hyb_steps) -> None:
        """Needle in the probe tube (only if the list has probe injections), start valve positions,
        hybridization steps, cleanup positions."""
        steps = self._cycle_hybridization_steps(hyb_steps, tube)
        probe_steps = [step for step in steps if step['probe']]

        if probe_steps:
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

    def _check_options(self) -> None:
        """Raise if user_config_path is not set."""
        if self.user_config_path in (None, '', 'TO FILL'):
            raise RuntimeError(f'user_config_path not set for task {type(self).__name__} - add '
                               f'`options: user_config_path: ...` to this task\'s entry in the config file')

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

    def _log_plan(self, hyb_steps, pb_steps, probe_valve) -> None:
        """Plan, logged before any hardware call: probe valve line; the hybridization steps of the first
        cycle in full (probe steps with valve and tube), then one line per further cycle with its tubes;
        the photobleaching steps (buffer valve only)."""
        total = len(self._cycles)
        n_probe = sum(1 for step in hyb_steps if step['probe'])
        self.log.info(f'Hi-M experiment {self.sample_name}: {total} probe(s), {len(self.roi_names)} '
                      f'ROI(s), needle mode {self._needle_mode!r}.')
        self.log.info('  probes: ' + ', '.join(f'{rt} (tube {tube})' for tube, rt in self._cycles))
        self.log.info(self._probe_plan_line(probe_valve, self.injections_path, n_probe))
        n = len(hyb_steps)
        for number, (tube, rt) in enumerate(self._cycles, 1):
            steps = self._cycle_hybridization_steps(hyb_steps, tube)
            tubes = sorted({step['tube'] for step in steps if step['probe']})
            if number == 1:
                self.log.info(f'  cycle {number}/{total} - {rt}: hybridization {n} step(s)')
                for k, step in enumerate(steps, 1):
                    self.log.info(f'    step {k}/{n}: {self._describe(step)}')
            elif tubes:
                self.log.info(f'  cycle {number}/{total} - {rt}: same hybridization steps, probe injection(s) from '
                              f'tube(s) {", ".join(str(t) for t in tubes)}')
            else:
                self.log.info(f'  cycle {number}/{total} - {rt}: same hybridization steps (buffer injections only)')
        self.log.info(f'  photobleaching: {len(pb_steps)} step(s), buffer valve only')
        for number, step in enumerate(pb_steps, 1):
            self.log.info(f'    step {number}/{len(pb_steps)}: {self._describe(step)}')

    def _save_parameters(self, params, injections) -> None:
        """Write HiM_parameters.yml in <self.directory>/experiment_parameters/: every key of the experiment file ('1- global parameters'),
        probes, hybridization and photobleaching lists, imaging parameters, ROI positions."""
        _, probes, hyb_list, pb_list, needle_mode = injections
        rois = {}
        for roi_name in self.roi_names:
            pos = list(self._roi_logic.get_roi_position(roi_name))
            z = pos[2] if len(pos) > 2 else None
            rois[roi_name] = f'X={pos[0]} - Y={pos[1]} - Z={z}'
        # every key of the experiment file, values as read: the known keys first (_EXPERIMENT_KEYS order), then the
        # others in file order (the experiment file itself is not copied into the run folder)
        global_parameters = {key: params[key] for key in self._EXPERIMENT_KEYS if key in params}
        global_parameters.update({key: value for key, value in params.items() if key not in global_parameters})
        param = {'1- global parameters': global_parameters,
                 '2- fluidic parameters': {'probes': probes,
                                           'probe_needle_mode': needle_mode,
                                           'hybridization list': hyb_list,
                                           'photobleaching list': pb_list},
                 '3- imaging parameters': {'number of laser lines': len(self.imaging_sequence),
                                           'imaging sequence': self.imaging_sequence},
                 '4- ROIs': rois}
        if self._uses_z_planes():
            param['3- imaging parameters']['number of z planes'] = self.num_z_planes
        path = os.path.join(self._parameters_dir, 'HiM_parameters.yml')
        with open(path, 'w') as outfile:
            yaml.safe_dump(param, outfile, default_flow_style=False, sort_keys=False)
        self.log.info(f'Saved the Hi-M parameters to {path}')

    def _uses_z_planes(self) -> bool:
        """True when num_z_planes is a required key of the experiment file (_EXPERIMENT_KEYS)."""
        return 'num_z_planes' in self._EXPERIMENT_KEYS

    def _save_run_files(self, injections) -> None:
        """experiment_parameters/injections.yml (byte copy of the injections file) and, with a sample file,
        experiment_parameters/sample.yml; with a metadata template, metadata.yml (with the 'Sample' section when
        there is a sample file) at the top of self.directory. The experiment file is not copied: its keys are in
        HiM_parameters.yml."""
        # exact copy of the injections file
        path = os.path.join(self._parameters_dir, 'injections.yml')
        shutil.copyfile(self.injections_path, path)
        self.log.info(f'Saved a copy of the injections file to {path}')
        metadata = None
        if self._metadata_template is not None:
            _, _, hyb_list, pb_list, _ = injections
            positions = {roi: self._roi_logic.get_roi_position(roi) for roi in self.roi_names}
            metadata = fill_run_metadata(self._metadata_template, self.sample_name, self.imaging_sequence, positions,
                                         self.num_z_planes)
            set_metadata_field(metadata, 'Fluidics', 'hybridization', hyb_list)
            set_metadata_field(metadata, 'Fluidics', 'photobleaching', pb_list)
        # sample file: copied as experiment_parameters/sample.yml, its content added as the 'Sample' section of
        # metadata.yml (top of the metadata folder)
        add_sample_to_run(self._parameters_dir, self._sample, metadata)
        if metadata is not None:
            path = write_metadata(self.directory, metadata)
            self.log.info(f'Saved the microscope metadata to {path}')

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

    def _choose_data_root(self) -> str:
        """Root of the run folder, chosen before any hardware call: save_network_path when it is reachable,
        otherwise save_path (choose_data_root)."""
        return choose_data_root(self, self.save_network_path, self.save_path)

    def _confirm_before_start(self) -> bool:
        """Called after all checks, before any hardware call or GUI lock: False cancels the experiment.
        Default: True (no question)."""
        return True

    def _create_data_folder(self) -> str:
        """Create <root>/YYYY_MM_DD/NNN_HiM_<sample_name> under the root chosen before any hardware call,
        set self.prefix = NNN and return the folder."""
        path, self.prefix = create_run_folder(self._data_root, 'HiM', self.sample_name)
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

    Experiment YAML: the keys of HiMTaskBase except num_z_planes (not required and not read: the z-stack is
    set in ZEN; an old file that still has it is accepted, the value is ignored), plus zen_saving_path
    (required: the folder where ZEN creates the data folder of the experiment, an existing folder that can be
    listed; only read), zen_ref_images_path (reference images of the autofocus), correlation_threshold (ZNCC
    threshold, -1..1) and autofocus_min_fraction (0..1); all checked before any hardware call. Without
    num_z_planes, HiM_parameters.yml has no 'number of z planes' entry and metadata.yml keeps the template's
    number_z_planes field.

    ZEN settings check: after all checks and before any hardware call or GUI lock, the modal box 'ZEN
    settings' of the ROI scan (SDImagingMixin._confirm_zen_settings) lists the settings to check in ZEN
    block 7 - the channels to select (wavelengths of the imaging sequence, in order) and the number of
    loops for blocks 4>9 (number of cycles x number of ROIs) - and waits for the answer: 'Done -
    continue' starts the experiment, Cancel ends the task without touching the hardware (result
    {'cancelled': True, 'cycles_done': 0}). Both values are also logged.

    Data folder: named after the folder ZEN creates for the experiment. The folders of zen_saving_path are
    listed before waiting for ZEN "ready"; once ZEN is ready, the single new folder is the ZEN data folder
    (SDImagingMixin, shared with the ROI scan; error if there is none or several, then the cleanup runs as
    usual). qudi creates <save_path>/<YYYY-MM-DD>/<ZEN folder name>/metadata, always local (local_dated_root,
    created and write-tested before any hardware call, YYYY-MM-DD = start of the task; create_mirror_folder,
    metadata_<HHMMSS> if that folder already holds files), and writes there (sample.yml with a sample file: key
    sample_file, required by the SD definitions; metadata.yml then has the 'Sample' section with its content):
        metadata/
            metadata.yml, movie_name.txt, HiM_task.log
            experiment_parameters/   HiM_parameters.yml, injections.yml (byte copy of the injections file),
                                     sample.yml
            autofocus/               files of the autofocus check (below)
    Nothing is written in the ZEN folder. self.prefix is the number of folders that were in
    zen_saving_path before ZEN started + 1, on 3 digits; file names scan_<prefix>_<RT>_<roi number>_ROI.

    Autofocus check (common/autofocus_check.py): after the ZEN autofocus block of each ROI, the brightfield
    image ZEN saves (*_AcquisitionBlock1_pt*.czi in the ZEN data folder, first plane) is compared with the
    reference image of that ROI by zero-normalised cross-correlation (ZNCC, a Pearson coefficient at every XY
    shift, independent of the intensity and tolerant to drift).
      - Before any hardware call: the references are read from zen_ref_images_path (autofocus_reference.npy
        if present, otherwise the *.czi in acquisition order); their number must equal the number of ROIs
        and they must all have the same shape. correlation_threshold must be in [-1, 1] (values tuned for
        the score of the former qudi-HiM task do not apply), autofocus_min_fraction in [0, 1].
      - Once the ZEN folder is known: copy of the references as autofocus_reference.npy in the metadata
        folder; the list of the autofocus images already seen starts EMPTY (as the legacy task): ZEN creates the
        image file of a block (still empty) as soon as it reaches the block, so the image of the first ROI
        (..._AcquisitionBlock1_pt1.czi) can already exist when ZEN reports "ready".
      - Each check, after ZEN's "done" trigger of the autofocus block: wait (poll every 0.5 s, no timeout,
        interruptible; a warning every _AF_WAIT_WARNING_S with the new matching files) until exactly one
        autofocus image not seen yet exists (several: ZEN is still writing), then that list becomes the
        snapshot for the next check. Then wait until the file is complete: size non-zero and the same on two
        checks FILE_STABLE_PERIOD_S apart (no timeout, interruptible, a warning every _AF_WAIT_WARNING_S).
      - The image is read (first plane, czifile with one decoding thread) and scored in a helper process
        (ProcessPoolExecutor, one 'spawn' process created in _setup, shut down in _cleanup; job
        autofocus_check.read_and_score, waited for at most AUTOFOCUS_JOB_TIMEOUT_S, interruptible), so that a
        native crash of the .czi reader cannot kill qudi. An exception raised by the job (e.g. file not readable
        yet): up to _AF_READ_ATTEMPTS attempts, _AF_READ_RETRY_S apart, a warning each time, the last one stops
        the run. The helper process dies or times out: error, new process, one more try; if that fails too, the
        check counts as FAILED (reference kept, row with an empty score and passed False, NaN in
        correlation.npy) and the minimum-fraction rule below decides. The versions of the reader (czifile,
        imagecodecs, numpy) are logged at the start. Score and shift (px) logged. Pass (score >= correlation_threshold): the image becomes the
        reference of the ROI (autofocus_reference.npy saved again). Fail: the reference is kept, warning
        (and a second one if the ROI already failed in the previous cycle).
      - Abort: as soon as (ROIs - failures of the cycle) / ROIs < autofocus_min_fraction, an error gives the
        counts and the experiment stops (error, cleanup as usual). The counter restarts at each cycle.
      - Files (<metadata folder>/autofocus/, created with the metadata folder; copied to the server with it):
        autofocus_reference.npy, ROI_probe_autofocus_summary.csv (header at creation, one row per check written as
        the run goes: experiment_folder (ZEN folder name), roi_name, probe_name (RT), correlation (score, empty
        when the image could not be read), cycle, shift_y_px, shift_x_px, passed),
        reference_images_<RT>.npy (end of each cycle), correlation.npy (cycles x ROIs, written by the
        cleanup; NaN for the checks not done). Report (qudi.util.autofocus_report, written by the cleanup
        after a normal end or an autofocus abort, not after an interrupt or another error; before the copy of
        the metadata to the server), in autofocus/: autofocus_correlation_heatmap.png (ROIs x probes) and
        autofocus_drift.png (drift of the autofocus images per ROI and cycle); no second CSV. An error while
        making the report is logged as a warning only.

    Copy of the metadata to the server: whenever save_network_path is set (with or without transfer_data), the
    metadata folder is copied to <save_network_path>/<ZEN folder name>/metadata by the cleanup, after the
    hardware reset and the autofocus report, in all cases (normal end, interrupt, error) once the folder exists;
    HiM_task.log is sent last, after its handler is closed. Without transfer_data the background helper
    (common/data_transfer.py) is created only in the cleanup, for these files. The destination is logged once
    the ZEN folder is known. A server problem only gives warnings.

    Online data transfer (experiment key transfer_data, TransferData_checkBox of the experiment configurator;
    common/data_transfer.py): copies of the ZEN acquisition images to <save_network_path>/<ZEN folder name>/
    during the fluidics steps, in a background thread, so that a server or network problem never stops or
    blocks the experiment.
      - transfer_data with an empty save_network_path: error before any hardware call. Then, still before any
        hardware call, the transfer is started on save_network_path with a write test (at most
        _TRANSFER_TEST_S); if it fails, a warning pop-up and the experiment continues (the files go when the
        server is back; test every RETRY_PERIOD_S). The files go to <save_network_path>/<ZEN folder name>/,
        the ZEN folder name being known once ZEN is ready.
      - Server folder <save_network_path>/<ZEN folder name>/ created by the transfer thread as soon as the ZEN
        folder is known (DataTransfer.make_dir: no wait; a failure only marks the server as down).
      - Files sent during the run: the ZEN acquisitions *_AcquisitionBlock2_pt*.czi (recursive, same path
        relative to the ZEN folder), listed at the start of the hybridization and of the photobleaching of each
        cycle and in the cleanup: sorted by their pt number, only the first N are queued (N = ZEN acquisitions
        confirmed done in this run, counted when _image_roi returns), each listing logged (files found, newly
        queued, waiting, sent; a warning when acquisitions were done but no file matches the pattern); copies
        only during the fluidics steps (hybridization; photobleaching + needle rinse). Before the
        imaging of a cycle: pause, and wait for the copy in progress (at most transfer_timeout, not while the
        server is down). Other ZEN files (e.g. the autofocus images) are not sent.
      - Cleanup (after the hardware reset): normal end -> the last czi files are sent (flush, at most
        transfer_timeout); interrupt / error -> no czi file (left for a manual copy); then the metadata as
        above (metadata/..., HiM_task.log once closed), with the same helper. Files not sent: one warning with
        their number and local paths.

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
            metadata_template: '/path/to/custom_metadata_templates/Spinning_Disk_setup.cfg'  # optional
            transfer_timeout: 300          # optional, s: max wait for a copy to the server (imaging, end of run)
    """

    trigger_logic = Connector(interface='TriggerLogic')

    transfer_timeout = 300  # s, longest wait for the copies to the server (before an imaging, at the end of the run)
    _TRANSFER_PATTERN = '*_AcquisitionBlock2_pt*.czi'  # ZEN acquisitions copied to the server during the run
    # (the autofocus images are *_AcquisitionBlock1_pt*.czi, not sent)
    _TRANSFER_TEST_S = 10   # first write test of the server folder
    _LOG_TRANSFER_S = 30    # copy of HiM_task.log at the end of the run

    # the z planes are set in ZEN: num_z_planes is not part of the SD experiment file
    _EXPERIMENT_KEYS = tuple(key for key in HiMTaskBase._EXPERIMENT_KEYS if key != 'num_z_planes')

    start_valve_positions = FluidicsSDTask.start_valve_positions
    needle_move_valve_positions = FluidicsSDTask.needle_move_valve_positions
    needle_moved_valve_positions = FluidicsSDTask.needle_moved_valve_positions
    incubation_valve_positions = FluidicsSDTask.incubation_valve_positions
    incubation_end_valve_positions = FluidicsSDTask.incubation_end_valve_positions
    cleanup_valve_positions = FluidicsSDTask.cleanup_valve_positions

    def _read_microscope_parameters(self, params) -> None:
        self.zen_saving_path = params.get('zen_saving_path')
        self._zen_folders_before = set()
        self._zen_directory = None
        self.zen_ref_images_path = params.get('zen_ref_images_path')
        self.correlation_threshold = params.get('correlation_threshold')
        self.autofocus_min_fraction = params.get('autofocus_min_fraction')
        self.transfer_data = bool(params.get('transfer_data') or False)
        self._acquisitions_done = 0    # ZEN acquisition blocks confirmed done in this run
        self.log.info(f'Autofocus image reader: {autofocus_check.reader_versions()}; single-thread read: '
                      f'{autofocus_check.single_thread_read_form()}; read and scored in a helper process')
        self._transfer = None          # DataTransfer to <save_network_path>/<ZEN folder name>
        self._run_completed = False    # True when _run ended normally (no interrupt, no error)
        self._af_aborted = False       # True when the autofocus check stopped the experiment
        self._af_refs = None           # reference image of each ROI (n_rois, H, W)
        self._af_seen = set()          # autofocus images already used (empty at the start of the run)
        self._af_scores = None         # correlation.npy: cycles x ROIs
        self._af_failures = 0          # failed checks in the current cycle
        self._af_failed_rois = set()   # ROIs that failed in the current cycle
        self._af_failed_before = set()  # ROIs that failed in the previous cycle
        self._af_passed = 0            # passed checks in the current cycle
        self._af_rt = None             # probe of the current cycle

    def _confirm_before_start(self) -> bool:
        """ZEN settings box (SDImagingMixin._confirm_zen_settings) with loops = number of cycles x number of
        ROIs. True: continue, False: cancel."""
        return self._confirm_zen_settings(len(self._cycles) * len(self.roi_names))

    def _check_microscope(self) -> list:
        problems = self._zen_saving_path_problems()
        for key in ('zen_ref_images_path',):
            path = getattr(self, key)
            if not path:
                problems.append(f'experiment file: {key!r} missing')
            elif not os.path.isdir(path):
                problems.append(f'{key} {path} is not an existing folder')
        # online data transfer
        if self.transfer_data and not self.save_network_path:
            problems.append("transfer_data is on but 'save_network_path' is empty")
        if isinstance(self.transfer_timeout, bool) or not isinstance(self.transfer_timeout, (int, float)) \
                or self.transfer_timeout <= 0:
            problems.append(f'transfer_timeout must be a number of seconds > 0 (got {self.transfer_timeout!r})')
        # autofocus check settings
        for key, low, high in (('correlation_threshold', -1.0, 1.0), ('autofocus_min_fraction', 0.0, 1.0)):
            value = getattr(self, key)
            if value is None:
                problems.append(f'experiment file: {key!r} missing')
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                problems.append(f'{key} must be a number between {low:g} and {high:g} (got {value!r})')
        # reference images: one per ROI, all of the same shape
        if self.zen_ref_images_path and os.path.isdir(self.zen_ref_images_path) and self.roi_names:
            try:
                self._af_refs = autofocus_check.load_reference_images(self.zen_ref_images_path)
            except Exception as err:
                problems.append(f'autofocus reference images: {err}')
            else:
                if len(self._af_refs) != len(self.roi_names):
                    problems.append(f'autofocus reference images: {len(self._af_refs)} reference image(s) in '
                                    f'{self.zen_ref_images_path} for {len(self.roi_names)} ROI(s) - one reference '
                                    f'per ROI is required')
                h, w = self._af_refs.shape[1:]
                self.log.info(f'Autofocus references: {len(self._af_refs)} image(s) {h}x{w} loaded from '
                              f'{self.zen_ref_images_path}')
        return problems

    def _prepare_imaging(self) -> None:
        """List the folders of zen_saving_path, SD imaging preparation (laser source, wait for ZEN "ready"),
        then the new folder created by ZEN."""
        self._zen_folders_before = self._zen_folders()
        super()._prepare_imaging()
        self._zen_directory = self._find_new_zen_folder(self._zen_folders_before)

    def _create_data_folder(self) -> str:
        """<root>/<ZEN folder name>/metadata (create_mirror_folder) and its autofocus/ subfolder; self.prefix =
        folders in zen_saving_path before ZEN started + 1, on 3 digits. Then the autofocus check files, in
        autofocus/: copy of the references, the score file with its header; empty list of the autofocus images seen
        (the image of the first ROI may already exist, still empty), empty score table."""
        self.prefix = str(len(self._zen_folders_before) + 1).zfill(3)
        directory = create_mirror_folder(self._data_root, self._zen_directory, self.log)
        # online transfer: the server folder <save_network_path>/<ZEN folder name>/ created now by the transfer
        # thread (no wait here; a failure marks the server as down)
        if getattr(self, '_transfer', None) is not None:
            try:
                self._transfer.make_dir(self._server_path())
                self.log.info(f'Data transfer: server folder {os.path.join(self.save_network_path, self._server_path())}'
                              f' requested')
            except Exception as err:  # the transfer never stops the experiment
                self.log.warning(f'Data transfer: could not request the server folder: {err}')
        # server copy of the metadata announced now that the ZEN folder name is known
        if getattr(self, 'save_network_path', ''):
            self.log.info(f'Metadata will also be copied to '
                          f'{os.path.join(self.save_network_path, self._server_path("metadata"))} at the end of the run')
        # autofocus check files: <metadata folder>/autofocus/
        os.makedirs(os.path.join(directory, autofocus_check.AUTOFOCUS_SUBFOLDER), exist_ok=True)
        np.save(os.path.join(directory, autofocus_check.AUTOFOCUS_SUBFOLDER, autofocus_check.REFERENCE_FILE_NAME),
                self._af_refs)
        self._af_seen = set()  # empty: the image file of the first ROI is created by ZEN before "ready"
        self._af_scores = np.full((len(self._cycles), len(self.roi_names)), np.nan)
        with open(os.path.join(directory, autofocus_check.AUTOFOCUS_SUBFOLDER, self._AF_CSV), 'w', newline='') as f:
            csv.writer(f).writerow(self._AF_CSV_COLUMNS)
        return directory

    def _choose_data_root(self) -> str:
        """<save_path>/<YYYY-MM-DD> (start of the task), always local; the server only gets copies. Before any
        hardware call: also the start of the online transfer (transfer_data)."""
        root = local_dated_root(self.save_path)
        self._start_transfer()
        return root

    def _run(self) -> dict:
        result = super()._run()
        self._run_completed = True  # normal end: the cleanup sends the last acquisitions
        return result

    # ----------------------------------------------------------------------------------------------
    # Online data transfer (common/data_transfer.py)
    # ----------------------------------------------------------------------------------------------

    def _start_transfer(self) -> None:
        """DataTransfer on save_network_path (files under <ZEN folder name>/); first write test, pop-up if it fails.
        Called before any hardware call; never stops the experiment."""
        if not self.transfer_data:
            return
        self._transfer = DataTransfer(self.log, self.save_network_path, timeout_s=self.transfer_timeout)
        if not self._transfer.test(self._TRANSFER_TEST_S):
            show_warning_popup('Server folder not reachable',
                               f'The server folder {self.save_network_path} is not reachable. The experiment '
                               f'continues; the data will be transferred when the server is back.')

    def _server_path(self, *parts) -> str:
        """Path relative to save_network_path: <ZEN folder name>/<parts>."""
        return os.path.join(os.path.basename(os.path.normpath(self._zen_directory)), *parts)

    def _queue_acquisitions(self) -> None:
        """Queue the ZEN acquisitions (_TRANSFER_PATTERN, recursive) of the ROIs already imaged: the matching files
        sorted by their pt number, the first N only (N = acquisitions confirmed done in this run; a later file is
        still being written by ZEN), with their path relative to the ZEN folder. One info line with the counts;
        a warning when acquisitions were done but no file matches the pattern."""
        if getattr(self, '_transfer', None) is None or not getattr(self, '_zen_directory', None):
            return
        done = getattr(self, '_acquisitions_done', 0)
        found = autofocus_check.sort_czi_paths(
            glob(os.path.join(self._zen_directory, '**', self._TRANSFER_PATTERN), recursive=True))
        if done > 0 and not found:
            self.log.warning(f'Data transfer: no ZEN acquisition file matches {self._TRANSFER_PATTERN} in '
                             f'{self._zen_directory} although {done} acquisition(s) were done - check the ZEN block '
                             f'numbers')
        new = 0
        for path in found[:done]:
            if self._transfer.add(path, self._server_path(os.path.relpath(path, self._zen_directory))):
                new += 1
        self.log.info(f'Data transfer: {len(found)} acquisition file(s) ({self._TRANSFER_PATTERN}) in '
                      f'{self._zen_directory}, {new} newly queued, {self._transfer.pending_count} waiting, '
                      f'{self._transfer.sent_count} sent')

    def _image_roi(self, roi_name: str, file_name: str) -> None:
        """Imaging of one ROI (SDImagingMixin), then one more ZEN acquisition counted as done (its file can be sent
        to the server)."""
        super()._image_roi(roi_name, file_name)
        self._acquisitions_done = getattr(self, '_acquisitions_done', 0) + 1

    def _transfer_open(self) -> None:
        """Start of a fluidics step of the cycle: list the acquisitions, allow the copies."""
        if getattr(self, '_transfer', None) is None:
            return
        try:
            self._queue_acquisitions()
            self._transfer.allow()
        except Exception as err:  # the transfer never stops the experiment
            self.log.warning(f'Data transfer: could not start the copies of this step: {err}')

    def _transfer_pause(self) -> None:
        if getattr(self, '_transfer', None) is None:
            return
        try:
            self._transfer.pause()
        except Exception as err:
            self.log.warning(f'Data transfer: could not pause the copies: {err}')

    def _hybridization(self, label, rt, tube, hyb_steps) -> None:
        """Hybridization with the copies to the server allowed."""
        self._transfer_open()
        try:
            super()._hybridization(label, rt, tube, hyb_steps)
        finally:
            self._transfer_pause()

    def _photobleaching(self, label, rt, pb_steps) -> None:
        """Photobleaching with the copies allowed (until the end of the needle rinse)."""
        self._transfer_open()
        super()._photobleaching(label, rt, pb_steps)

    def _rinse_needle(self, label) -> None:
        """Needle rinse, then the copies are paused."""
        try:
            super()._rinse_needle(label)
        finally:
            self._transfer_pause()

    def _end_of_run_files(self) -> None:
        """Cleanup, after the hardware reset: autofocus report (normal end or autofocus abort), then, with
        transfer_data, the last acquisitions (normal end only), and, whenever save_network_path is set, the
        metadata files to the server."""
        self._make_autofocus_report()
        if getattr(self, '_transfer', None) is not None:
            # a. normal end: the acquisitions of the last cycle
            if self._run_completed:
                try:
                    self._queue_acquisitions()
                    self._transfer.flush(self.transfer_timeout)
                except Exception as err:
                    self.log.error(f'Cleanup: transfer of the acquisitions: {err}')
            # b. interrupt / error: the acquisitions stay local (manual copy)
            else:
                try:
                    skipped = self._transfer.discard([p for p in self._transfer.pending()
                                                      if p.startswith(self._zen_directory)])
                    self.log.info(f'Data transfer: run not completed - the ZEN acquisitions are not sent '
                                  f'({len(skipped)} queued file(s) left); copy them from {self._zen_directory}')
                except Exception as err:
                    self.log.error(f'Cleanup: data transfer: {err}')
        # c. the metadata folder, except the log: whenever save_network_path is set (none when the run stopped
        #    before the ZEN folder was known)
        if not getattr(self, 'directory', None) or not getattr(self, 'save_network_path', ''):
            return
        if getattr(self, '_transfer', None) is None:
            # transfer_data off: the background helper is created now, for the metadata only (no write test)
            try:
                self._transfer = DataTransfer(self.log, self.save_network_path, timeout_s=self.transfer_timeout)
            except Exception as err:
                self.log.error(f'Cleanup: transfer of the metadata: {err}')
                return
        try:
            log_path = os.path.join(self.directory, self._LOG_FILE_NAME)
            for folder, _, names in os.walk(self.directory):
                for name in names:
                    path = os.path.join(folder, name)
                    if path != log_path:
                        self._transfer.add(path, self._server_path('metadata', os.path.relpath(path, self.directory)))
            self._transfer.flush(self.transfer_timeout)
        except Exception as err:
            self.log.error(f'Cleanup: transfer of the metadata: {err}')

    def _make_autofocus_report(self) -> None:
        """Autofocus report in <metadata folder>/autofocus/ (qudi.util.autofocus_report.report_run) after a normal end or an
        autofocus abort; any error is logged as a warning only."""
        if not (getattr(self, '_run_completed', False) or getattr(self, '_af_aborted', False)) \
                or not getattr(self, 'directory', None):
            return
        try:
            written = autofocus_report.report_run(self.directory, log=self.log)
            self.log.info('Autofocus report: ' + ', '.join(os.path.basename(path) for path in written))
        except Exception as err:
            self.log.warning(f'Autofocus report could not be created: {err!r}')

    def _after_run_log_closed(self) -> None:
        """Cleanup, once HiM_task.log is closed: send it, stop the transfer, report the files not sent (only when a
        transfer exists: transfer_data, or save_network_path with a metadata folder)."""
        if getattr(self, '_transfer', None) is None:
            return
        left = []
        # d. the log (short time limit), then the transfer thread is stopped
        try:
            if not self.directory:
                raise RuntimeError('no run folder - nothing to send')
            self._transfer.add(os.path.join(self.directory, self._LOG_FILE_NAME),
                               self._server_path('metadata', self._LOG_FILE_NAME))
            left = self._transfer.flush(self._LOG_TRANSFER_S)
        except Exception as err:
            self.log.error(f'Cleanup: transfer of the log: {err}')
        try:
            self._transfer.stop()
        except Exception as err:
            self.log.error(f'Cleanup: stop of the data transfer: {err}')
        # e. files not sent
        if left:
            self.log.warning(f'Data transfer: {len(left)} file(s) not sent to {self._transfer.destination_root} - '
                             f'they are in: ' + ', '.join(left))

    # ----------------------------------------------------------------------------------------------
    # Autofocus check
    # ----------------------------------------------------------------------------------------------

    _AF_CSV = autofocus_check.SCORES_FILE_NAME           # ROI_probe_autofocus_summary.csv, in autofocus/
    _AF_CSV_COLUMNS = autofocus_check.SCORES_COLUMNS
    _AF_POLL_S = 0.5  # poll interval while waiting for the new autofocus image
    _AF_WAIT_WARNING_S = 60  # warning every _AF_WAIT_WARNING_S while the new autofocus image is not found
    _AF_READ_ATTEMPTS = 5    # attempts to read the new autofocus image (ZEN may still be writing it)
    _AF_READ_RETRY_S = 1.0   # pause between two read attempts
    FILE_STABLE_PERIOD_S = 0.5      # the new image is read once its size is the same on two checks this far apart
    AUTOFOCUS_JOB_TIMEOUT_S = 120   # longest wait for the helper process (read + score of one image)
    _AF_JOB_POLL_S = 0.1            # interrupt check period while waiting for the helper process
    # function run in the helper process with (path, reference); None: autofocus_check.read_and_score. A module-level
    # function (it is pickled by name), e.g. a stand-in of the tests.
    _af_worker = None

    def _setup(self) -> None:
        """Setup of all setups, plus the helper process pool of the autofocus check (the process itself starts with
        the first check)."""
        self._af_pool = None
        super()._setup()
        self._af_pool = self._new_af_pool()

    @staticmethod
    def _new_af_pool():
        """One helper process, started with 'spawn' (a fresh interpreter: no thread or memory state of qudi)."""
        return concurrent.futures.ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn'))

    def _af_executor(self):
        """The helper process pool, created when missing (after a crash, or for a task built without _setup)."""
        if getattr(self, '_af_pool', None) is None:
            self._af_pool = self._new_af_pool()
        return self._af_pool

    def _stop_af_pool(self) -> None:
        """Shut the helper process pool down (pending jobs cancelled); a process still alive after 1 s (stuck
        read) is terminated. Never raises."""
        pool, self._af_pool = getattr(self, '_af_pool', None), None
        if pool is None:
            return
        processes = list((getattr(pool, '_processes', None) or {}).values())
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception as err:
            self.log.error(f'Autofocus check: could not shut the image reader process down: {err!r}')
        for process in processes:
            try:
                process.join(timeout=1.0)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=1.0)
            except Exception as err:
                self.log.error(f'Autofocus check: could not stop the image reader process: {err!r}')

    def _af_path(self, name) -> str:
        """<metadata folder>/autofocus/<name> (the subfolder is created when missing)."""
        folder = os.path.join(self.directory, autofocus_check.AUTOFOCUS_SUBFOLDER)
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, name)

    def _af_row(self, cycle, roi_name, score, shift_y, shift_x, passed) -> None:
        """One row of the score file (columns autofocus_check.SCORES_COLUMNS), appended at once (kept after an
        abort); score None: image not read (empty score and shifts)."""
        experiment = os.path.basename(os.path.normpath(self._zen_directory)) if self._zen_directory else ''
        row = (experiment, roi_name, self._af_rt, '' if score is None else f'{score:.6f}', cycle + 1,
               '' if score is None else shift_y, '' if score is None else shift_x, passed)
        with open(self._af_path(self._AF_CSV), 'a', newline='') as f:
            csv.writer(f).writerow(row)

    def _autofocus_images(self) -> list:
        """Autofocus images (*_AcquisitionBlock1_pt*.czi) of the ZEN data folder, recursive search."""
        return glob(os.path.join(self._zen_directory, '**', autofocus_check.AUTOFOCUS_IMAGE_PATTERN), recursive=True)

    def _wait_for_autofocus_image(self, roi_name) -> str:
        """Called after ZEN's "done" trigger of the autofocus block of roi_name: wait until exactly one autofocus
        image of the ZEN folder is not in the snapshot self._af_seen (empty at the start of the run, so the image
        of the first ROI is found even if ZEN created its file before "ready"); several new files: ZEN is still
        writing, wait. Poll every _AF_POLL_S, no timeout, interruptible; a warning every _AF_WAIT_WARNING_S.
        The listing becomes the snapshot for the next check; returns the path of the new image."""
        self.log.info(f'Waiting for the autofocus image of {roi_name} ({autofocus_check.AUTOFOCUS_IMAGE_PATTERN}) '
                      f'in {self._zen_directory}')
        start = next_warning = monotonic()
        next_warning += self._AF_WAIT_WARNING_S
        while True:
            self._check_interrupt()
            current = self._autofocus_images()
            new = sorted(set(current) - self._af_seen)
            if len(new) == 1:
                self._af_seen = set(current)
                self.log.info(f'Autofocus image of {roi_name}: {os.path.basename(new[0])}')
                return new[0]
            if monotonic() >= next_warning:
                next_warning += self._AF_WAIT_WARNING_S
                names = ', '.join(os.path.basename(path) for path in new[:5]) + (', ...' if len(new) > 5 else '')
                self.log.warning(f'Still waiting for the autofocus image of {roi_name} after {monotonic() - start:.0f} '
                                 f's: {len(new)} new matching file(s)' + (f' ({names})' if new else ''))
            self._zen_wait(self._AF_POLL_S)

    def _wait_until_file_stable(self, path, roi_name) -> None:
        """Wait until the size of the new image is non-zero and the same on two checks FILE_STABLE_PERIOD_S apart
        (ZEN may still be writing it, through a network mount). No timeout, interruptible; a warning every
        _AF_WAIT_WARNING_S while it changes."""
        start = monotonic()
        next_warning = start + self._AF_WAIT_WARNING_S
        previous = None
        while True:
            self._check_interrupt()
            try:
                size = os.path.getsize(path)
            except OSError:
                size = None
            if size and size == previous:
                return
            if monotonic() >= next_warning:
                next_warning += self._AF_WAIT_WARNING_S
                self.log.warning(f'Autofocus image of {roi_name} ({os.path.basename(path)}) still being written after '
                                 f'{monotonic() - start:.0f} s (size {size} B)')
            previous = size
            self._zen_wait(self.FILE_STABLE_PERIOD_S)

    def _run_in_helper(self, path, ref):
        """(score, shift_y, shift_x, image) computed by the helper process; waits at most AUTOFOCUS_JOB_TIMEOUT_S,
        checking for an interrupt every _AF_JOB_POLL_S. Raises BrokenProcessPool (process died),
        AutofocusReaderTimeout, or the exception raised inside the job."""
        worker = self._af_worker or autofocus_check.read_and_score
        with _main_script_hidden():  # the helper process starts here (first job, or after a crash)
            future = self._af_executor().submit(worker, path, ref)
        deadline = monotonic() + self.AUTOFOCUS_JOB_TIMEOUT_S
        while True:
            self._check_interrupt()
            try:
                return future.result(timeout=self._AF_JOB_POLL_S)
            except concurrent.futures.TimeoutError:
                if future.done():
                    raise  # a TimeoutError raised inside the job itself
                if monotonic() >= deadline:
                    future.cancel()
                    raise AutofocusReaderTimeout(f'no result after {self.AUTOFOCUS_JOB_TIMEOUT_S:g} s')

    def _score_in_helper(self, path, ref, roi_name):
        """_run_in_helper; when the helper process dies or times out: error, new process, one more try. None when
        the second try fails too (the check then counts as failed). Exceptions raised inside the job go up."""
        for helper_attempt in (1, 2):
            try:
                return self._run_in_helper(path, ref)
            except (BrokenProcessPool, AutofocusReaderTimeout) as err:
                details = (f'timeout: {err}' if isinstance(err, AutofocusReaderTimeout)
                           else f'process died: {err!r}')
                self.log.error(f'Autofocus check of {roi_name}: the image reader process crashed (or timed out) - '
                               f'{details}' + (' - new reader process, second attempt' if helper_attempt == 1 else ''))
                self._stop_af_pool()  # a new pool is created by the next _af_executor()
        self.log.error(f'Autofocus check of {roi_name}: the image reader process failed twice - the check of '
                       f'{os.path.basename(path)} counts as failed')
        return None

    def _read_and_score(self, path, ref, roi_name):
        """Read and score the new image in the helper process; an exception raised inside the job (e.g. file not
        readable yet): up to _AF_READ_ATTEMPTS attempts, _AF_READ_RETRY_S apart (interruptible), a warning at each
        failure, the last one is raised. None when the helper process failed twice."""
        for attempt in range(1, self._AF_READ_ATTEMPTS + 1):
            try:
                return self._score_in_helper(path, ref, roi_name)
            except ModuleScriptInterrupted:
                raise
            except Exception as err:
                if attempt == self._AF_READ_ATTEMPTS:
                    raise
                self.log.warning(f'Could not read the autofocus image {os.path.basename(path)} (attempt {attempt}/'
                                 f'{self._AF_READ_ATTEMPTS}): {err!r} - new attempt in {self._AF_READ_RETRY_S:g} s')
                self._zen_wait(self._AF_READ_RETRY_S)

    def _imaging(self, label, rt) -> None:
        """Imaging of the cycle between the start and the end of its autofocus checks; before it, the copies to the
        server are paused and the copy in progress is waited for (at most transfer_timeout; not when the server
        is down)."""
        if getattr(self, '_transfer', None) is not None:
            try:
                self._transfer.pause()
                if self._transfer.server_ok:
                    self._transfer.wait_idle(self.transfer_timeout)
            except Exception as err:  # the transfer never stops the experiment
                self.log.warning(f'Data transfer: {err}')
        self._start_autofocus_cycle(rt)
        super()._imaging(label, rt)
        self._end_autofocus_cycle(rt)

    def _start_autofocus_cycle(self, rt) -> None:
        """Counters of the autofocus checks reset at the start of each cycle."""
        self._af_rt, self._af_failures, self._af_passed = rt, 0, 0
        self._af_failed_before, self._af_failed_rois = self._af_failed_rois, set()

    def _end_autofocus_cycle(self, rt) -> None:
        """References at the end of the cycle (reference_images_<RT>.npy) and fraction of passed checks."""
        np.save(self._af_path(f'reference_images_{rt}.npy'), self._af_refs)
        n = len(self.roi_names)
        self.log.info(f'Autofocus check {rt}: {self._af_passed}/{n} ROI(s) passed ({self._af_passed / n:.0%})')

    def _check_autofocus(self, roi_name: str) -> None:
        """Compare the image ZEN saved at the end of its autofocus block with the reference of roi_name (ZNCC,
        common/autofocus_check.py); see the class docstring for pass / fail and the abort rule."""
        cycle, index, n = self._cycles_done, self.roi_names.index(roi_name), len(self.roi_names)
        # wait for the new autofocus image, then until ZEN has finished writing it
        path = self._wait_for_autofocus_image(roi_name)
        self._wait_until_file_stable(path, roi_name)
        # read its first plane and score it against the reference of this ROI, in the helper process (a crash of
        # the .czi reader cannot kill qudi)
        result = self._read_and_score(path, self._af_refs[index], roi_name)
        if result is None:
            # reader process failed twice: failed check (reference kept, empty score, NaN in correlation.npy)
            self._af_row(cycle, roi_name, None, None, None, False)
            self._autofocus_failed(roi_name, cycle, n, 'the image could not be read')
            return
        score, shift_y, shift_x, image = result
        passed = score >= self.correlation_threshold
        self._af_scores[cycle, index] = score
        self.log.info(f'Autofocus check cycle {cycle + 1}/{len(self._cycles)} - {self._af_rt} - {roi_name}: score '
                      f'{score:.3f}, shift (y, x) = ({shift_y}, {shift_x}) px - {"pass" if passed else "FAIL"}')
        # one row per check, written at once (kept after an abort)
        self._af_row(cycle, roi_name, score, shift_y, shift_x, passed)
        if passed:
            # pass: the new image becomes the reference of this ROI
            self._af_passed += 1
            self._af_refs[index] = image
            np.save(self._af_path(autofocus_check.REFERENCE_FILE_NAME), self._af_refs)
            return
        self._autofocus_failed(roi_name, cycle, n, f'score {score:.3f} < threshold {self.correlation_threshold}')

    def _autofocus_failed(self, roi_name, cycle, n, reason) -> None:
        """Failed check: reference kept, warnings, then the minimum-fraction rule (RuntimeError when the experiment
        is aborted)."""
        self._af_failures += 1
        self._af_failed_rois.add(roi_name)
        self.log.warning(f'Autofocus check failed for {roi_name} ({reason})')
        if roi_name in self._af_failed_before:
            self.log.warning(f'Autofocus check failed for {roi_name} in the previous cycle too')
        # abort as soon as the minimum fraction of passed ROIs can no longer be reached in this cycle
        if (n - self._af_failures) / n < self.autofocus_min_fraction:
            message = (f'Autofocus check: {self._af_failures} of {n} ROI(s) failed in cycle {cycle + 1} '
                       f'({self._af_rt}) - at most {(n - self._af_failures) / n:.0%} can pass, below the minimum '
                       f'fraction {self.autofocus_min_fraction:.0%}. The Hi-M experiment is aborted.')
            self.log.error(message)
            # TODO: email alert to the user (legacy send_alert_email), not migrated yet
            self._af_aborted = True  # the cleanup still makes the autofocus report
            raise RuntimeError(message)

    def _cleanup(self) -> None:
        """Helper process of the autofocus check stopped, correlation.npy (cycles x ROIs, NaN for the checks not done)
        in <metadata folder>/autofocus/, then the cleanup of all setups."""
        try:
            self._stop_af_pool()
        except Exception as err:
            self.log.error(f'Cleanup: could not stop the autofocus image reader process: {err!r}')
        if getattr(self, '_af_scores', None) is not None and getattr(self, 'directory', None):
            try:
                np.save(self._af_path('correlation.npy'), self._af_scores)
            except Exception as err:
                self.log.error(f'Cleanup: could not save correlation.npy: {err}')
        super()._cleanup()


class AutofocusReaderTimeout(Exception):
    """The helper process of the autofocus check gave no result within AUTOFOCUS_JOB_TIMEOUT_S."""


@contextmanager
def _main_script_hidden():
    """While a helper process is started with the 'spawn' method: the main script of the parent (qudi's start
    script, a test script) is not imported again in the child - spawn imports it as __mp_main__ when
    __main__ has a __spec__ name or a __file__. Both are removed for the time of the start and restored."""
    main = sys.modules.get('__main__')
    if main is None:
        yield
        return
    saved = {key: main.__dict__[key] for key in ('__file__', '__spec__') if key in main.__dict__}
    main.__dict__.pop('__file__', None)
    main.__dict__['__spec__'] = None
    try:
        yield
    finally:
        for key in ('__file__', '__spec__'):
            if key in saved:
                main.__dict__[key] = saved[key]
            else:
                main.__dict__.pop(key, None)


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
        #     metadata_template: 'TO FILL'  # optional, e.g. .../custom_metadata_templates/RAMM_setup.cfg
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
    valves (a, b, c), a fixed interruptible wait per ROI (DummyImagingMixin), data folder as on all
    setups (HiMTaskBase).

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
            metadata_template: '/home/jb/Repositories/qudi-core-HiM/custom_config/custom_metadata_templates/Spinning_Disk_setup.cfg'
    """

    start_valve_positions = FluidicsRAMMTask.start_valve_positions
    needle_move_valve_positions = FluidicsRAMMTask.needle_move_valve_positions
    needle_moved_valve_positions = FluidicsRAMMTask.needle_moved_valve_positions
    incubation_valve_positions = FluidicsRAMMTask.incubation_valve_positions
    incubation_end_valve_positions = FluidicsRAMMTask.incubation_end_valve_positions
    cleanup_valve_positions = FluidicsRAMMTask.cleanup_valve_positions
