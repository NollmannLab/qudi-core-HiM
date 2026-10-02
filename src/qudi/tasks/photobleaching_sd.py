# -*- coding: utf-8 -*-
"""
Author: F. Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2026-08-06
Modified for qudi-core: 2026-10-02

qudi-core-HiM task: scan a list of ROIs on the spinning-disk setup in order to photobleached the sample and reduce bkg
fluorescence signal

This is a qudi-core ModuleTask translation of the legacy qudi (InterruptableTask) task
tasks/photobleaching_task_AIRYSCAN.py. It is a NEW file - the legacy file is left untouched.

This is code is similar to the roi_multicolour_scan.yaml, except that no trigger is used to synchronize with ZEN.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

import os
import yaml
from datetime import datetime
from time import monotonic, sleep

from qudi.core.scripting.moduletask import ModuleTask
from qudi.core.connector import Connector


class PhotoBleachingTask(ModuleTask):
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

    roi_logic = Connector(interface='RoiLogic')
    trigger_logic = Connector(interface='TriggerLogic')
    laser_logic = Connector(interface='LaserControlLogic')

    user_config_path = '/home/him_spinning/qudi/qudi_task_config_files/photobleaching_task_sd.yml'
    poll_interval_s = 0.1
    scan_stage_velocity = {'x': 1000.0, 'y': 1000.0}  # µm/S
    idle_stage_velocity = {'x': 6000.0, 'y': 6000.0}

    def _setup(self) -> None:
        self._roi_logic = self.roi_logic()
        self._trigger_logic = self.trigger_logic()
        self._laser_logic = self.laser_logic()

        self.roi_list_path = None
        self.roi_names = []
        self._photobleached_rois = set()
        self.imaging_sequence = None
        self.illumination_time = None

    # ======================================================================================
    # Main entry point
    # ======================================================================================

    def _run(self) -> dict:
        """Run the scan. Pass resume=True to continue a previous, interrupted attempt on the same
        sample and ROI list (see class docstring).
        """
        self._load_user_parameters()
        self._check_interrupt()

        # make sure the laser are disabled when starting
        self._laser_logic.set_laser_disabled()

        # disable interfering GUI actions - mirrors legacy startTask()
        self._roi_logic.disable_tracking_mode()
        self._roi_logic.disable_roi_actions()
        self._roi_logic.set_stage_velocity(self.scan_stage_velocity)

        self._check_interrupt()

        # lauch the photobleaching, one roi at a time
        remaining = [name for name in self.roi_names if name not in self._photobleached_rois]
        self.log.info(f'{len(remaining)} of {len(self.roi_names)} ROI(s) remaining.')

        for roi_name in remaining:
            self._check_interrupt()
            self._scan_one_roi(roi_name)
            self._photobleached_rois.add(roi_name)

        return {'imaged_rois': sorted(self._photobleached_rois)}

    def _cleanup(self) -> None:
        """Return hardware to a safe idle state. Called unconditionally by the ModuleTask base class
        whether _run() finished normally, raised, or was interrupted.
        """
        self.log.info('cleanup running - restoring hardware to a safe idle state')

        if self.roi_names:
            try:
                self._roi_logic.set_active_roi(name=self.roi_names[0])
                self._roi_logic.go_to_roi_xy()
            except Exception as e:
                self.log.warning(f'Could not return stage to first ROI during cleanup: {e}')

        if self.imaging_sequence:
            try:
                self._laser_logic.set_laser_disabled()
                self._laser_logic.reset_laser_intensities()
            except Exception as e:
                self.log.warning(f'Could not disable lasers: {e}')

        try:
            self._roi_logic.set_stage_velocity(self.idle_stage_velocity)
        except Exception as e:
            self.log.warning(f'Could not reset stage velocity during cleanup: {e}')

        try:
            self._roi_logic.enable_tracking_mode()
            self._roi_logic.enable_roi_actions()
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

        self._roi_logic.set_active_roi(name=roi_name)
        self._roi_logic.go_to_roi_xy()
        self._roi_logic.stage_wait_for_idle()
        self._check_interrupt()

        # switch ON the laser. All the laser lines at once.
        self._laser_logic.set_laser_enabled()
        self._trigger_logic.send_trigger('trigger_celesta_shutter')
        sleep(self.illumination_time)
        self._laser_logic.set_laser_disabled()


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
    # User parameters
    # ======================================================================================

    def _load_user_parameters(self) -> None:
        """Load the user-defined experiment parameters (sample name, ROI list, ...) from the YAML
        file at self.user_config_path. See class docstring for the expected keys.
        """

        self.log.warning(self.user_config_path)
        with open(self.user_config_path, 'r') as stream:
            user_param_dict = yaml.safe_load(stream)

        self.roi_list_path = user_param_dict['roi_list_path']
        self.imaging_sequence = user_param_dict['imaging_sequence']
        self.illumination_time = user_param_dict['illumination_time'] * 60

        self._trigger_logic.update_pulse_time('trigger_celesta_shutter', self.illumination_time)

        self._roi_logic.load_roi_list(self.roi_list_path)
        self.roi_names = list(self._roi_logic.roi_names)

        self.num_laserlines = len(self.imaging_sequence)
        self._laser_logic.set_external_trigger(False)
        for wavelength, intensity in self.imaging_sequence:
            self._laser_logic.set_laser_line_intensity(int(wavelength), float(intensity))


