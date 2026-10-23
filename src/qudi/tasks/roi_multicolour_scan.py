# -*- coding: utf-8 -*-
"""
qudi-core-HiM task: scan a list of ROIs - move the stage to each ROI in turn and image it.

Structure - one file for all setups:
  - RoiScanTaskBase: everything that does not depend on the microscope (parameters, stage moves,
    data folder, metadata, start ROI, cleanup).
  - RoiScanSDTask / RoiScanRAMMTask / RoiScanDummyTask: one subclass per setup. The imaging done at
    each ROI comes from the per-microscope mixins of tasks/common/imaging_steps.py (SDImagingMixin,
    RAMMImagingMixin, DummyImagingMixin), shared with the Hi-M task.
The path of the experiment YAML written by the experiment configurator differs between machines:
each microscope's config sets it in the task's entry with "options: user_config_path: ..." (applied
by logic/taskrunner_logic.py).

Translated from the legacy qudi tasks tasks/ROI_multicolour_imaging_SD.py and
logic/tasks/roi_multicolor_scan_task_RAMM_Celesta.py; tasks/roi_multicolour_scan_sd.py is the
previous single-setup version of the spinning-disk task.

Interruption is exception-based (self._check_interrupt() raises ModuleScriptInterrupted); _cleanup()
is called by the ModuleTask base class whenever _run() finishes, raises or is interrupted.

Start ROI: the task's call parameter start_roi (Task Runner) selects the first ROI to scan - a ROI
name of the list, empty for the first ROI. The scan runs from there to the end
of the list, in list order, into a new data folder.

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
Portions of the docstrings and of the file-path / metadata structure are adapted from
tasks/ROI_multicolour_imaging_SD.py (Copyright (c) the Qudi Developers, GNU GPLv3) and from
qudi-core's qudi.tasks.dummy_fluidics_task (Copyright (c) 2021, the qudi developers, GNU LGPLv3).

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

from qudi.core.connector import Connector
from qudi.tasks.common.imaging_steps import SDImagingMixin, RAMMImagingMixin, DummyImagingMixin
from qudi.tasks.common.progress import ProgressModuleTask


class RoiScanTaskBase(ProgressModuleTask):
    """Shared ROI scan: for each ROI of the list, move the stage, wait until it is idle and image the
    ROI with the setup's imaging mixin (_prepare_imaging / _image_roi / _end_imaging, see
    tasks/common/imaging_steps.py).

    Not meant to be configured directly - use a setup subclass. Option (config "options:"):
        user_config_path    experiment YAML written by the experiment configurator (required)

    User config file (user_config_path) expected keys:
        sample_name: 'Mysample'
        dapi: False            # optional, default False - affects only folder/file naming
        rna: False             # optional, default False - affects only folder/file naming
        save_path: '/path/to/data'
        roi_list_path: 'pathstem/qudi_roi_lists/roilist_20260101.json'
        imaging_sequence: [[488, 50.0], [561, 80.0]]   # [wavelength (nm), intensity (%)]

    Call parameter (Task Runner):
        start_roi   first ROI to scan: a ROI name of the loaded list (e.g. 'ROI_005'); empty =
                    first ROI. The Task Runner shows parameter_hints['start_roi'] in the empty field
                    and as tooltip. Checked right after loading
                    the ROI list, before any hardware call. The scan runs from that ROI to the end
                    of the list, in list order.

    Data: each run creates save_path/YYYY_MM_DD/NNN_Scan_<sample>[_DAPI|_RNA]/ with parameters.yml
    (sample name, start_roi and the positions of the ROIs scanned in this run) and movie_name.txt
    (one file name per imaged ROI).

    Progress (Task Runner window), with M the number of ROIs scanned in this run and j the index in
    this run: '0/M - Preparing imaging' (SD: then 'Waiting for ZEN "ready"'), 'j/M - ROI j/M - <roi>'
    before each move, 'M/M - Done' after the last ROI.

    During the run the lasers are off (unless the imaging switches them), ROI tracking and ROI
    actions are locked and the stage moves at scan_stage_velocity. _cleanup() moves the stage back
    to the first ROI, ends the imaging, restores the stage velocity and unlocks the ROI GUI.
    """

    roi_logic = Connector(interface='RoiLogic')
    laser_logic = Connector(interface='LaserControlLogic')
    trigger_logic = Connector(interface='TriggerLogic', optional=True)

    user_config_path = None  # set by the config: options: user_config_path: ...

    # shown by the Task Runner GUI for the call parameters (placeholder text and tooltip)
    parameter_hints = {'start_roi': 'ROI name, e.g. ROI_005 (empty = first ROI)'}

    def _setup(self) -> None:
        # attributes used by _cleanup(): set first, so that _cleanup() also works if fetching a
        # connector below fails
        self._roi_logic = None
        self._trigger_logic = None
        self._laser_logic = None
        self.sample_name = None
        self.is_dapi = False
        self.is_rna = False
        self.save_path = None
        self.roi_list_path = None
        self.roi_names = []
        self.prefix = None
        self.directory = None
        self.start_roi = ''
        self._scan_rois = []      # ROIs to scan in this run, in list order
        self._scanned_rois = []   # ROIs whose imaging has finished, for the summary
        self.imaging_sequence = None
        self._prev_stage_velocity = None  # stage velocity read before the scan, restored by _cleanup
        self._hardware_touched = False  # True once _run() has started changing the hardware state

        self._roi_logic = self.roi_logic()
        self._trigger_logic = self.trigger_logic()
        self._laser_logic = self.laser_logic()

    # ======================================================================================
    # Imaging hooks - implemented by the imaging mixin of each setup
    # ======================================================================================

    def _prepare_imaging(self) -> None:
        raise NotImplementedError(f'{type(self).__name__} has no imaging mixin.')

    def _image_roi(self, roi_name: str, file_name: str) -> None:
        raise NotImplementedError(f'{type(self).__name__} has no imaging mixin.')

    def _end_imaging(self) -> None:
        pass

    # ======================================================================================
    # Main entry point
    # ======================================================================================

    def _run(self, start_roi: str = '') -> dict:
        """Run the scan from start_roi (ROI name of the list, empty = first ROI) to the end
        of the list (see class docstring).
        """
        # 1. refuse to run, before touching any hardware, if the config gave no YAML path; load the
        #    user parameters and the ROI list
        if self.user_config_path in (None, '', 'TO FILL'):
            raise RuntimeError(f'user_config_path not set for task {type(self).__name__} — add '
                               f'`options: user_config_path: ...` to this task\'s entry in the '
                               f'config file')
        self._load_user_parameters()

        # 2. ROIs of this run, from start_roi to the end of the list - checked before any hardware call
        self.start_roi = str(start_roi if start_roi is not None else '').strip()
        self._scan_rois = self.roi_names[self._start_index(self.start_roi):]
        if self._scan_rois:
            self.log.info(f'Scanning ROIs {self._scan_rois[0]} to {self._scan_rois[-1]} '
                          f'({len(self._scan_rois)} of {len(self.roi_names)})')
        else:
            self.log.info('The ROI list is empty - no ROI to scan.')

        # 3. lasers off, ROI tracking and ROI actions locked, scan stage velocity (restored in
        #    _cleanup)
        self._check_interrupt()
        self._hardware_touched = True
        self._laser_logic.set_laser_disabled()
        self._roi_logic.disable_tracking_mode()
        self._roi_logic.disable_roi_actions()
        self._prev_stage_velocity = dict(self._roi_logic.get_stage_velocity(list(self.scan_stage_velocity)))
        if not self._roi_logic.set_stage_velocity(self.scan_stage_velocity):
            raise RuntimeError(f'Could not set the scan stage velocity {self.scan_stage_velocity} - '
                               f'see the log.')

        # 4. setup-specific preparation of the imaging
        total = len(self._scan_rois)
        self._report_progress(f'0/{total}', 'Preparing imaging')
        self._prepare_imaging()

        # 5. new data folder and metadata
        self.directory = self._create_directory(self.save_path)
        self._save_metadata_file()

        # 6. ROI loop: move, image (progress 'ROI j/M - <name>'; the "Moving to" line is the log)
        for number, roi_name in enumerate(self._scan_rois, 1):
            self._check_interrupt()
            self._report_progress(f'{number}/{total}', f'{roi_name}', log=False)
            self._move_to_roi(roi_name)
            self._image_roi(roi_name, self._file_name(roi_name))
            self._scanned_rois.append(roi_name)

        # 7. summary ("All ROIs done." is the log line of the progress 'Done')
        self._report_progress(f'{total}/{total}', 'Done', log=False)
        self.log.info('All ROIs done.')
        return {'directory': self.directory, 'imaged_rois': list(self._scanned_rois)}

    def _start_index(self, start_roi: str) -> int:
        """Index in self.roi_names of the first ROI to scan. start_roi: '' (first ROI) or a ROI name
        of the list. Raises, with the first and last ROI names, otherwise."""
        if start_roi == '':
            return 0
        if start_roi in self.roi_names:
            return self.roi_names.index(start_roi)
        if self.roi_names:
            valid = (f'a ROI name of the list, from {self.roi_names[0]} to {self.roi_names[-1]} '
                     f'({len(self.roi_names)} ROIs), or empty for the first ROI')
        else:
            valid = 'nothing - the ROI list is empty; leave start_roi empty'
        raise ValueError(f'start_roi {start_roi!r} is not valid: expected {valid}. ROI list: '
                         f'{self.roi_list_path}')

    def _cleanup(self) -> None:
        """Return hardware to a safe idle state. Called unconditionally by the ModuleTask base class
        whether _run() finished normally, raised, or was interrupted. Never raises.
        """
        if not getattr(self, '_hardware_touched', False):
            self.log.info('cleanup: no hardware was touched, nothing to restore')
            return

        self.log.info('cleanup running - restoring hardware to a safe idle state')

        # back to the first ROI
        if self.roi_names:
            try:
                self._roi_logic.set_active_roi(name=self.roi_names[0])
                self._roi_logic.go_to_roi_xy()
            except Exception as e:
                self.log.warning(f'Could not return stage to first ROI during cleanup: {e}')

        # setup-specific end of the imaging (lasers, triggers)
        try:
            self._end_imaging()
        except Exception as e:
            self.log.error(f'Could not end the imaging during cleanup: {e}')

        # stage velocity restored
        try:
            if self._prev_stage_velocity:
                if not self._roi_logic.set_stage_velocity(self._prev_stage_velocity):
                    self.log.error(f'Could not restore the stage velocity {self._prev_stage_velocity} '
                                   f'during cleanup.')
        except Exception as e:
            self.log.error(f'Could not restore the stage velocity during cleanup: {e}')

        # ROI GUI unlocked
        try:
            self._roi_logic.enable_tracking_mode()
            self._roi_logic.enable_roi_actions()
        except Exception as e:
            self.log.warning(f'Could not re-enable ROI GUI actions during cleanup: {e}')

        self.log.info('cleanup finished')

    # ======================================================================================
    # Stage
    # ======================================================================================

    def _move_to_roi(self, roi_name: str) -> None:
        """Move the stage to one ROI and wait until it has arrived."""
        self.log.info(f'Moving to {roi_name}')
        self._roi_logic.set_active_roi(name=roi_name)
        self._roi_logic.go_to_roi_xy()
        self._roi_logic.stage_wait_for_idle()
        self._check_interrupt()

    # ======================================================================================
    # User parameters
    # ======================================================================================

    def _load_user_parameters(self) -> None:
        """Load the user-defined experiment parameters (sample name, ROI list, imaging sequence, ...)
        from the YAML file at self.user_config_path and load the ROI list. See class docstring for
        the expected keys. The lasers are prepared by _prepare_imaging().
        """
        self.log.info(f'Loading ROI scan parameters from {self.user_config_path}')
        with open(self.user_config_path, 'r') as stream:
            user_param_dict = yaml.safe_load(stream)

        self.sample_name = user_param_dict['sample_name']
        self.is_dapi = user_param_dict.get('dapi', False)
        self.is_rna = user_param_dict.get('rna', False)
        self.save_path = user_param_dict['save_path']
        self.roi_list_path = user_param_dict['roi_list_path']
        self.imaging_sequence = user_param_dict['imaging_sequence']

        self._roi_logic.load_roi_list(self.roi_list_path)
        self.roi_names = list(self._roi_logic.roi_names)

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
        """Write a small sidecar file with the sample name, start_roi and the stage position of each
        ROI scanned in this run (purely descriptive, not used by the task).
        """
        metadata = {'Sample name': self.sample_name, 'start_roi': self.start_roi}
        for roi in self._scan_rois:
            pos = self._roi_logic.get_roi_position(roi)
            metadata[roi] = f'X = {pos[0]} - Y = {pos[1]}'

        path = os.path.join(self.directory, 'parameters.yml')
        with open(path, 'w') as outfile:
            yaml.safe_dump(metadata, outfile, default_flow_style=False)
        self.log.info(f'Saved metadata to {path}')


class RoiScanSDTask(SDImagingMixin, RoiScanTaskBase):
    """ROI scan on the spinning disk: one ZEN autofocus block and one ZEN acquisition block per ROI,
    synchronized over DAQ triggers (see SDImagingMixin). trigger_logic is required on this setup.
    Before waiting for ZEN "ready", the log gives the number of acquisition loops to set in ZEN:
    the number of ROIs scanned in this run (from start_roi to the end of the list).

    Config example for copy-paste (logic: task_runner: options: module_tasks:):

        roi_multicolour_scan:
          module.Class: 'qudi.tasks.roi_multicolour_scan.RoiScanSDTask'
          connect:
            roi_logic: roi_logic
            trigger_logic: trigger_logic
            laser_logic: laser_control_logic
          options:
            user_config_path: '/path/to/qudi_task_config_files/roi_multicolor_scan_task_sd.yaml'
            acquisition_timeout_s: 120.0   # optional, max wait for ZEN's "done" trigger per block
            poll_interval_s: 0.1           # optional
    """

    trigger_logic = Connector(interface='TriggerLogic')

    def _prepare_imaging(self) -> None:
        """Log the number of ROIs of this run (the number of acquisition loops to set in ZEN), show
        'Waiting for ZEN "ready"' in the progress line, then the SD imaging preparation
        (SDImagingMixin), which waits for ZEN "ready" (and logs it)."""
        self.log.info(f'ZEN: set the number of acquisition loops to {len(self._scan_rois)}')
        self._report_progress(f'0/{len(self._scan_rois)}', 'Waiting for ZEN "ready"', log=False)
        super()._prepare_imaging()


class RoiScanRAMMTask(RAMMImagingMixin, RoiScanTaskBase):
    """ROI scan on the RAMM - PLACEHOLDER: the imaging is not migrated yet, the task stops at the
    start of the imaging with a clear error (see RAMMImagingMixin).

    Config example for copy-paste (logic: task_runner: options: module_tasks:):

        # roi_multicolour_scan:
        #   module.Class: 'qudi.tasks.roi_multicolour_scan.RoiScanRAMMTask'
        #   connect:
        #     roi_logic: roi_logic
        #     laser_logic: laser_control_logic
        #   options:
        #     user_config_path: 'TO FILL'
    """


class RoiScanDummyTask(DummyImagingMixin, RoiScanTaskBase):
    """ROI scan without imaging hardware, for testing with dummy_config.cfg: a fixed interruptible
    wait per ROI (see DummyImagingMixin).

    Config example (dummy_config.cfg, logic: task_runner: options: module_tasks:):

        roi_multicolour_scan_dummy:
          module.Class: 'qudi.tasks.roi_multicolour_scan.RoiScanDummyTask'
          connect:
            roi_logic: roi_logic
            laser_logic: laser_control_logic
          options:
            user_config_path: '/home/jb/qudi/qudi_task_config_files/ROI_multicolor_scan_task_AIRYSCAN.yaml'
            dummy_imaging_time_s: 2.0      # optional
    """
