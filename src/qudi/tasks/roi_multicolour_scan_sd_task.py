# -*- coding: utf-8 -*-
"""
qudi-core-HiM task: scan a list of ROIs on the spinning-disk setup, synchronized with an external
ZEN acquisition program over a DAQ trigger handshake.

This is a qudi-core ModuleTask translation of the legacy qudi (InterruptableTask) task
tasks/ROI_multicolour_imaging_SD.py. It is a NEW file - the legacy file is left untouched.

Compared to the legacy task, the scope is deliberately much smaller, per discussion with JB
(2026-09-26): on the spinning-disk setup, z-stack acquisition, autofocus, and image acquisition
itself are all handled by ZEN; the Lumencor laser source is switched by a dedicated TTL box that ZEN
also controls directly. None of that is qudi's job any more. This task's only two responsibilities
are: (1) move the stage to each ROI in turn, and (2) tell ZEN when to start imaging that ROI and wait
for ZEN to confirm it is done - one start/done trigger handshake per ROI, via TriggerLogic, which
forwards requests to separate TriggerOutputInterface and TriggerInputInterface hardware modules
(hardware/interfuse_hardware/daq_trigger_sync.py). The task does not connect directly to trigger
hardware or the DAQ module. There is no per-plane loop, no laser control, and no autofocus handshake
in this task at all.

Two other things carried over/changed from the legacy design, matching the interrupt/resume work
already done on the taskrunner (see taskrunner_logic.py, tasks/dummy_fluidics_task.py):

1. Interruption is exception-based (self._check_interrupt(), raising ModuleScriptInterrupted),
   matching qudi-core's ModuleTask model, instead of the legacy pattern of manually threading
   "if not self.aborted" through every subsequent block. _cleanup() is called unconditionally by the
   ModuleTask base class whenever _run() finishes, raises, or is interrupted.

2. Resumability: if a run is interrupted partway through the ROI list, a subsequent launch with
   resume=True skips every ROI that was already confirmed done by ZEN and continues with the rest,
   instead of requiring the whole scan to be restarted. Progress is checkpointed to a small YAML file
   next to the run's own output directory (see _load_checkpoint / _save_checkpoint below) after every
   ROI completes, so it survives a qudi restart, not just an in-process retry. An ROI only ever counts
   as done once ZEN's own "done" trigger has been seen for it - if the interrupt happened mid-ROI
   (stage already moved, trigger already sent, still waiting for ZEN), that ROI is simply redone in
   full on the next launch.

One thing NOT simplified away, per JB (2026-09-28): the legacy task also waited, once, for a ZEN
"ready" signal before starting the whole experiment (the user has to manually select the right ZEN
experiment block and click "Start Experiment" first, which can take a while). This version keeps
that as a genuinely separate, one-way handshake - a second connector/channel pair (``ready``,
matching the legacy task's OUT7_ZEN), not a reuse of the per-ROI start/done pair (matching OUT8_ZEN):
qudi only ever polls the ready channel, it never pulses anything to elicit it, so this cannot cause
ZEN to perform a spurious acquisition. See _wait_for_ready() below.

-----------------------------------------------------------------------------------
Portions of the docstrings and file-path/metadata/checkpoint structure are adapted from
tasks/ROI_multicolour_imaging_SD.py (Copyright (c) the Qudi Developers, GNU GPLv3) and from
qudi-core's own qudi.tasks.dummy_fluidics_task (Copyright (c) 2021, the qudi developers, GNU LGPLv3).
This file as a whole is qudi-core-HiM code and follows the same license terms as the rest of this
repository.

Modified for qudi-core-HiM (2026-09-26, Modified with Claude code): new file - qudi-core translation
  of the legacy ROI_multicolour_imaging_SD.py task, scoped down to stage motion + a single ZEN
  trigger handshake per ROI (see module docstring above), with checkpoint-based resume and
  exception-based interruption.
-----------------------------------------------------------------------------------
"""

import os
import yaml
from datetime import datetime
from time import monotonic, sleep

from qudi.core.scripting.moduletask import ModuleTask
from qudi.core.connector import Connector


class RoiScanTask(ModuleTask):
    """Scan a list of ROIs on the spinning-disk setup: move the stage to each ROI in turn and run a
    single start/done trigger handshake with ZEN for each one (see module docstring for why this task
    does nothing else - no autofocus, laser, or per-plane control on qudi's side).

    Config example for copy-paste:

        module_tasks:
          roi_scan:
            module.Class: 'qudi.tasks.roi_multicolour_scan_sd_task.RoiScanTask'
            connect:
              roi: roi_logic
              trigger_logic: trigger_logic
            options:
              path_to_user_config: '/home/him_spinning/qudi_task_config_files/roi_scan_task_sd.yml'
              acquisition_timeout_s: 120.0   # max time to wait for ZEN's "done" trigger on one ROI
              poll_interval_s: 0.1
              scan_stage_velocity: {'x': 1, 'y': 1}
              idle_stage_velocity: {'x': 6, 'y': 6}

    ``trigger_logic`` must be a TriggerLogic instance connected to the required trigger hardware.
    The task addresses its output and input modules by their configured Qudi module names:
    ``trigger_ZEN_start_block``, ``trigger_ZEN_block_finished``, and ``trigger_ZEN_ready``. These
    hardware modules in turn use named DAQ tasks rather than raw channel numbers - see
    hardware/interfuse_hardware/daq_trigger_sync.py. The ready and per-ROI completion inputs
    preserve the legacy task's OUT7_ZEN / OUT8_ZEN structure.

    User config file (path_to_user_config) expected keys:
        sample_name: 'Mysample'
        dapi: False           # optional, default False - affects only folder/file naming
        rna: False             # optional, default False - affects only folder/file naming
        save_path: '/home/him_spinning/data'
        roi_list_path: 'pathstem/qudi_roi_lists/roilist_20260101.json'

    Resuming an interrupted run: start the task with the extra argument resume=True (same task name).
    If a checkpoint from a matching, unfinished previous attempt is found (same sample name and ROI
    list), ROIs already confirmed done by ZEN are skipped and the run continues in the same output
    directory. Otherwise (no checkpoint, or resume=True with nothing to resume) the run starts from
    scratch, same as resume=False.
    """

    roi = Connector(name='roi', interface='RoiLogic')
    trigger_logic = Connector(name='trigger_logic', interface='TriggerLogic')

    user_config_path = '/home/him_spinning/qudi/qudi_task_config_files/roi_multicolor_scan_task_sd.yml'
    acquisition_timeout_s = 120.0  # max time to wait for ZEN's "done" trigger on one ROI
    poll_interval_s = 0.1
    scan_stage_velocity = {'x': 1000.0, 'y': 1000.0}  # µm/S
    idle_stage_velocity = {'x': 6000.0, 'y': 6000.0}

    def _setup(self) -> None:
        self._roi = self.roi()
        self._trigger_logic = self.trigger_logic()

        self.sample_name = None
        self.is_dapi = False
        self.is_rna = False
        self.save_path = None
        self.roi_list_path = None
        self.roi_names = []
        self.prefix = None
        self.directory = None
        self._imaged_rois = set()

    # ======================================================================================
    # Main entry point
    # ======================================================================================

    def _run(self, resume: bool = False) -> dict:
        """Run the scan. Pass resume=True to continue a previous, interrupted attempt on the same
        sample and ROI list (see class docstring).
        """
        self._load_user_parameters()

        checkpoint = self._load_checkpoint() if resume else None
        checkpoint_is_usable = (
            checkpoint is not None
            and not checkpoint.get('completed', True)
            and checkpoint.get('sample_name') == self.sample_name
            and checkpoint.get('roi_list_path') == self.roi_list_path
        )
        if resume and not checkpoint_is_usable:
            self.log.warning('resume=True was requested but no matching, unfinished checkpoint was '
                             'found for this sample/ROI list - starting from scratch.')

        if checkpoint_is_usable:
            self._imaged_rois = set(checkpoint.get('imaged_rois', []))
            self.directory = checkpoint['directory']
            self.log.info(f'Resuming previous run in {self.directory}: {len(self._imaged_rois)} of '
                          f'{len(self.roi_names)} ROI(s) already confirmed done by ZEN.')
        else:
            self._imaged_rois = set()
            self.directory = None

        self._check_interrupt()

        # disable interfering GUI actions - mirrors legacy startTask()
        self._roi.disable_tracking_mode()
        self._roi.disable_roi_actions()
        self._roi.set_stage_velocity(self.scan_stage_velocity)

        self._check_interrupt()

        self.log.info('Waiting for ZEN to signal it is ready (select the right experiment block '
                      'and click "Start Experiment" in ZEN)...')
        self._wait_for_ready()
        self.log.info('ZEN is ready - starting the ROI scan.')

        if self.directory is None:
            self.directory = self._create_directory(self.save_path)
            self._save_metadata_file()
            # write an initial checkpoint right away so an interrupt before the first ROI completes is
            # still resumable (pointing at this directory, with zero ROIs done yet)
            self._save_checkpoint()

        remaining = [name for name in self.roi_names if name not in self._imaged_rois]
        self.log.info(f'{len(remaining)} of {len(self.roi_names)} ROI(s) remaining.')

        for roi_name in remaining:
            self._check_interrupt()
            self._scan_one_roi(roi_name)
            self._imaged_rois.add(roi_name)
            self._save_checkpoint()

        self.log.info('All ROIs done.')
        self._save_checkpoint(completed=True)

        return {'directory': self.directory, 'imaged_rois': sorted(self._imaged_rois)}

    def _cleanup(self) -> None:
        """Return hardware to a safe idle state. Called unconditionally by the ModuleTask base class
        whether _run() finished normally, raised, or was interrupted.
        """
        self.log.info('cleanup running - restoring hardware to a safe idle state')

        if self.roi_names:
            try:
                self._roi.set_active_roi(name=self.roi_names[0])
                self._roi.go_to_roi_xy()
            except Exception as e:
                self.log.warning(f'Could not return stage to first ROI during cleanup: {e}')

        try:
            self._roi.set_stage_velocity(self.idle_stage_velocity)
        except Exception as e:
            self.log.warning(f'Could not reset stage velocity during cleanup: {e}')

        try:
            self._roi.enable_tracking_mode()
            self._roi.enable_roi_actions()
        except Exception as e:
            self.log.warning(f'Could not re-enable ROI GUI actions during cleanup: {e}')

        self.log.info('cleanup finished')

    # ======================================================================================
    # Per-ROI acquisition
    # ======================================================================================

    def _scan_one_roi(self, roi_name: str) -> None:
        """Move to one ROI, then run a single start/done trigger handshake with ZEN for it. Raises on
        interrupt (via self._check_interrupt()) or on a timeout waiting for ZEN's "done" trigger (a
        real synchronization problem, not an interrupt).
        """
        self.log.info(f'Moving to {roi_name}')
        scan_name = self._file_name(roi_name)

        self._roi.set_active_roi(name=roi_name)
        self._roi.go_to_roi_xy()
        self._roi.stage_wait_for_idle()
        self._check_interrupt()

        self.log.info(f'Triggering ZEN acquisition for {roi_name}')
        self._trigger_logic.send_trigger('trigger_ZEN_start_block')
        self._wait_for_done()
        self.log.info(f'{roi_name}: acquisition confirmed done by ZEN.')

        self._append_movie_name(scan_name)

    def _wait_for_ready(self) -> None:
        """One-time wait, before the ROI loop starts, for ZEN's own "ready" signal - a separate,
        one-way channel that ZEN raises once armed (matching the legacy task's OUT7_ZEN). qudi never
        sends anything on this channel (see the ``trigger_ZEN_ready`` input registered with
        TriggerLogic), only polls it, so this cannot cause ZEN to perform a spurious acquisition.

        No timeout, deliberately, same as the legacy task: the user has to manually select the right
        ZEN experiment block and click "Start Experiment" first, which can take an arbitrary amount
        of time. Still checks for interruption on every poll.
        """
        while True:
            self._check_interrupt()
            if self._trigger_logic.is_triggered('trigger_ZEN_ready'):
                return
            sleep(self.poll_interval_s)

    def _wait_for_done(self) -> None:
        """Poll the trigger input interfuse's "done" signal until it appears, checking for
        interruption on every poll via self._check_interrupt().

        If self.acquisition_timeout_s is exceeded, raises RuntimeError - this is a real ZEN
        synchronization problem, not a user-requested interrupt, so it is deliberately NOT reported
        as a ModuleScriptInterrupted (which self._check_interrupt() would raise for an actual
        interrupt).
        """
        deadline = monotonic() + self.acquisition_timeout_s
        while True:
            self._check_interrupt()
            if self._trigger_logic.is_triggered('trigger_ZEN_block_finished'):
                return
            if monotonic() > deadline:
                raise RuntimeError(
                    f'Timed out after {self.acquisition_timeout_s} s waiting for ZEN to confirm it '
                    'is done. No "done" trigger was detected - check the ZEN synchronization.')
            sleep(self.poll_interval_s)

    # ======================================================================================
    # Checkpoint / resume
    # ======================================================================================

    def _checkpoint_path(self) -> str:
        """Stable path (independent of the per-run dated/incrementing output directory) so a
        resume=True launch can find it before any new directory is created.
        """
        return os.path.join(self.save_path, f'.{self.sample_name}_roi_scan_checkpoint.yaml')

    def _load_checkpoint(self):
        path = self._checkpoint_path()
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.log.warning(f'Could not read checkpoint file {path}: {e}')
            return None

    def _save_checkpoint(self, completed: bool = False) -> None:
        path = self._checkpoint_path()
        data = {
            'sample_name': self.sample_name,
            'roi_list_path': self.roi_list_path,
            'directory': self.directory,
            'imaged_rois': sorted(self._imaged_rois),
            'completed': completed,
        }
        try:
            with open(path, 'w') as f:
                yaml.safe_dump(data, f, default_flow_style=False)
        except Exception as e:
            self.log.warning(f'Could not write checkpoint file {path}: {e}')

    # ======================================================================================
    # User parameters
    # ======================================================================================

    def _load_user_parameters(self) -> None:
        """Load the user-defined experiment parameters (sample name, ROI list, ...) from the YAML
        file at self.user_config_path. See class docstring for the expected keys.
        """

        self.log.warning(self.user_config_path)
        with open(self.user_config_path, 'r') as stream:
            user_param_dict = yaml.safe_load(stream)

        self.sample_name = user_param_dict['sample_name']
        self.is_dapi = user_param_dict.get('dapi', False)
        self.is_rna = user_param_dict.get('rna', False)
        self.save_path = user_param_dict['save_path']
        self.roi_list_path = user_param_dict['roi_list_path']

        self._roi.load_roi_list(self.roi_list_path)
        self.roi_names = list(self._roi.roi_names)

    # ======================================================================================
    # File path handling
    # ======================================================================================

    def _create_directory(self, path_stem: str) -> str:
        """Create path_stem/YYYY_MM_DD/NNN_Scan_samplename (or _DAPI / _RNA), same layout as the
        legacy task.
        """
        cur_date = datetime.today().strftime('%Y_%m_%d')
        path_stem_with_date = os.path.join(path_stem, cur_date)

        if not os.path.exists(path_stem_with_date):
            os.makedirs(path_stem_with_date)

        dir_list = [folder for folder in os.listdir(path_stem_with_date)
                   if os.path.isdir(os.path.join(path_stem_with_date, folder))]
        prefix = str(len(dir_list) + 1).zfill(3)
        self.prefix = prefix

        if self.is_dapi:
            foldername = f'{prefix}_Scan_{self.sample_name}_DAPI'
        elif self.is_rna:
            foldername = f'{prefix}_Scan_{self.sample_name}_RNA'
        else:
            foldername = f'{prefix}_Scan_{self.sample_name}'

        path = os.path.join(path_stem_with_date, foldername)
        os.makedirs(path)
        return path

    def _file_name(self, roi_name: str) -> str:
        roi_number_inv = roi_name.strip('ROI_') + '_ROI'
        if self.is_dapi:
            return f'scan_{self.prefix}_DAPI_{roi_number_inv}'
        elif self.is_rna:
            return f'scan_{self.prefix}_RNA_{roi_number_inv}'
        else:
            return f'scan_{self.prefix}_{roi_number_inv}'

    def _append_movie_name(self, movie_name: str) -> None:
        with open(os.path.join(self.directory, 'movie_name.txt'), 'a+') as outfile:
            outfile.write(movie_name)
            outfile.write('\n')

    # ======================================================================================
    # Metadata
    # ======================================================================================

    def _save_metadata_file(self) -> None:
        """Write a small sidecar file recording the sample name and each ROI's stage position -
        purely descriptive, qudi does not act on any of this (see module docstring: ZEN owns the
        actual imaging parameters).
        """
        metadata = {'Sample name': self.sample_name}
        for roi in self.roi_names:
            pos = self._roi.get_roi_position(roi)
            metadata[roi] = f'X = {pos[0]} - Y = {pos[1]}'

        path = os.path.join(self.directory, 'parameters.yml')
        with open(path, 'w') as outfile:
            yaml.safe_dump(metadata, outfile, default_flow_style=False)
        self.log.info(f'Saved metadata to {path}')
