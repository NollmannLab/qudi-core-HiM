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

from qudi.core.connector import Connector
from qudi.tasks.common.data_folders import choose_data_root, create_mirror_folder, create_run_folder, local_dated_root
from qudi.tasks.common.run_metadata import (copy_experiment_file, fill_run_metadata, optional_metadata_template,
                                            write_metadata)
from qudi.tasks.common.imaging_steps import SDImagingMixin, RAMMImagingMixin, DummyImagingMixin
from qudi.tasks.common.progress import ProgressModuleTask


class RoiScanTaskBase(ProgressModuleTask):
    """Shared ROI scan: for each ROI of the list, move the stage, wait until it is idle and image the
    ROI with the setup's imaging mixin (_prepare_imaging / _image_roi / _end_imaging, see
    tasks/common/imaging_steps.py).

    Not meant to be configured directly - use a setup subclass. Options (config "options:"):
        user_config_path    experiment YAML written by the experiment configurator (required)
        metadata_template   microscope metadata template (YAML, custom_config/custom_metadata_templates/,
                            same file as the basic imaging GUI's metadata_template); optional: not set ->
                            one warning, no metadata.yml; set but missing / unreadable -> error before any
                            hardware call

    User config file (user_config_path) expected keys:
        sample_name: 'Mysample'
        dapi: False            # optional, default False - affects only folder/file naming
        rna: False             # optional, default False - affects only folder/file naming
        save_path: '/path/to/data'            # local folder (required)
        save_network_path: '/server/data'     # server folder (optional, empty = local folder only)
        roi_list_path: 'pathstem/qudi_roi_lists/roilist_20260101.json'
        imaging_sequence: [[488, 50.0], [561, 80.0]]   # [wavelength (nm), intensity (%)]

    Call parameter (Task Runner):
        start_roi   first ROI to scan: a ROI name of the loaded list (e.g. 'ROI_005'); empty =
                    first ROI. The Task Runner shows parameter_hints['start_roi'] in the empty field
                    and as tooltip. Checked right after loading
                    the ROI list, before any hardware call. The scan runs from that ROI to the end
                    of the list, in list order.

    Data (all setups): qudi creates the run folder <root>/YYYY_MM_DD/NNN_Scan_<sample>[_DAPI|_RNA]/
    (NNN: self.prefix, tasks/common/data_folders.py create_run_folder) and writes there parameters.yml
    (sample name, start_roi and the positions of the ROIs scanned in this run) and movie_name.txt (one
    file name per imaged ROI), experiment_config.yaml (byte copy of the experiment file) and, with a
    metadata template, metadata.yml (the template with Time and the Acquisition fields sample_name,
    laser_lines, laser_power_(%), number_z_planes when the experiment file has it, roi_list_(xyz): the ROIs
    of this run with their positions; other fields as in the template). <root> is chosen before any hardware call, after the confirmation hook
    (hook _choose_data_root; default choose_data_root): save_network_path (server) when it is set and
    writable, otherwise save_path (local; a server folder that is not reachable gives a warning in the log
    and a non-modal pop-up). The spinning-disk task keeps its run folder local (RoiScanSDTask).
    The run folder itself is created after _prepare_imaging(). The data location keys are read and
    checked by the hook _read_data_location(params) (save_path required, save_network_path optional).

    Progress (Task Runner window), with M the number of ROIs scanned in this run and j the index in
    this run: '0/M - Preparing imaging' (SD: then 'Waiting for ZEN "ready"'), 'j/M - <roi>' before
    each move, 'M/M - Done' after the last ROI.

    Confirmation hook: _confirm_before_start() is called once the ROIs of this run are known, before
    any hardware call or GUI lock; if it returns False the scan is cancelled (result
    {'cancelled': True, 'imaged_rois': []}, nothing to restore). Default: True (no question).

    During the run the lasers are off (unless the imaging switches them), ROI tracking and ROI
    actions are locked and the stage moves at scan_stage_velocity. _cleanup() moves the stage back
    to the first ROI, ends the imaging, restores the stage velocity and unlocks the ROI GUI.
    """

    roi_logic = Connector(interface='RoiLogic')
    laser_logic = Connector(interface='LaserControlLogic')
    trigger_logic = Connector(interface='TriggerLogic', optional=True)

    user_config_path = None  # set by the config: options: user_config_path: ...
    metadata_template = None  # optional, set by the config: options: metadata_template: ...

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
        self.save_network_path = None
        self._data_root = None
        self.roi_list_path = None
        self.roi_names = []
        self.prefix = None
        self.directory = None
        self.start_roi = ''
        self._scan_rois = []      # ROIs to scan in this run, in list order
        self._scanned_rois = []   # ROIs whose imaging has finished, for the summary
        self.imaging_sequence = None
        self._user_params = {}          # experiment file content
        self._metadata_template = None  # metadata template (None: no metadata.yml)
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

    def _confirm_before_start(self) -> bool:
        """Called once the ROIs of this run are known, before any hardware call: False cancels the
        scan. Default: True (no question)."""
        return True

    def _read_data_location(self, params) -> None:
        """Read and check the data location keys of the experiment file, before any hardware call:
        save_path (local folder, required), save_network_path (server folder, optional)."""
        self.save_path = params.get('save_path')
        self.save_network_path = params.get('save_network_path') or ''
        if not self.save_path:
            raise RuntimeError(f"Experiment file {self.user_config_path}: 'save_path' missing.")

    def _choose_data_root(self) -> str:
        """Root of the run folder, chosen before any hardware call: save_network_path when it is reachable,
        otherwise save_path (choose_data_root)."""
        return choose_data_root(self, self.save_network_path, self.save_path)

    def _create_data_folder(self) -> str:
        """Run folder, created after _prepare_imaging() under the root chosen before any hardware call:
        <root>/YYYY_MM_DD/NNN_Scan_<sample>[_DAPI|_RNA]; sets self.prefix = NNN."""
        suffix = '_DAPI' if self.is_dapi else '_RNA' if self.is_rna else ''
        path, self.prefix = create_run_folder(self._data_root, 'Scan', self.sample_name, suffix)
        return path

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
        self._metadata_template = optional_metadata_template(self)
        self._load_user_parameters()

        # 2. ROIs of this run, from start_roi to the end of the list - checked before any hardware call
        self.start_roi = str(start_roi if start_roi is not None else '').strip()
        self._scan_rois = self.roi_names[self._start_index(self.start_roi):]
        if self._scan_rois:
            self.log.info(f'Scanning ROIs {self._scan_rois[0]} to {self._scan_rois[-1]} '
                          f'({len(self._scan_rois)} of {len(self.roi_names)})')
        else:
            self.log.info('The ROI list is empty - no ROI to scan.')

        # 3. setup-specific confirmation before any hardware call (e.g. ZEN settings on the SD)
        self._check_interrupt()
        if not self._confirm_before_start():
            self.log.info('ROI scan cancelled by the user')
            return {'cancelled': True, 'imaged_rois': []}

        # data root (server folder or local folder), chosen and write-tested before any hardware call
        self._data_root = self._choose_data_root()

        # 4. lasers off, ROI tracking and ROI actions locked, scan stage velocity (restored in
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

        # 5. setup-specific preparation of the imaging
        total = len(self._scan_rois)
        self._report_progress(f'0/{total}', 'Preparing imaging')
        self._prepare_imaging()

        # 6. new data folder (hook), parameters.yml, experiment file copy and metadata.yml
        self.directory = self._create_data_folder()
        self._save_metadata_file()
        self._save_run_files()

        # 7. ROI loop: move, image (progress 'j/M - <name>'; the "Moving to" line is the log)
        for number, roi_name in enumerate(self._scan_rois, 1):
            self._check_interrupt()
            self._report_progress(f'{number}/{total}', f'{roi_name}', log=False)
            self._move_to_roi(roi_name)
            self._image_roi(roi_name, self._file_name(roi_name))
            self._scanned_rois.append(roi_name)

        # 8. summary ("All ROIs done." is the log line of the progress 'Done')
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
        self.roi_list_path = user_param_dict['roi_list_path']
        self.imaging_sequence = user_param_dict['imaging_sequence']
        self._user_params = user_param_dict
        self._read_data_location(user_param_dict)

        self._roi_logic.load_roi_list(self.roi_list_path)
        self.roi_names = list(self._roi_logic.roi_names)

    # ======================================================================================
    # File path handling
    # ======================================================================================

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

    def _save_run_files(self) -> None:
        """experiment_config.yaml (byte copy of the experiment file) and, with a metadata template, metadata.yml
        in the run folder."""
        copy_experiment_file(self.user_config_path, self.directory)
        if self._metadata_template is None:
            return
        positions = {roi: self._roi_logic.get_roi_position(roi) for roi in self._scan_rois}
        metadata = fill_run_metadata(self._metadata_template, self.sample_name, self.imaging_sequence, positions,
                                     self._user_params.get('num_z_planes'))
        path = write_metadata(self.directory, metadata)
        self.log.info(f'Saved the microscope metadata to {path}')


class RoiScanSDTask(SDImagingMixin, RoiScanTaskBase):
    """ROI scan on the spinning disk: one ZEN autofocus block and one ZEN acquisition block per ROI,
    synchronized over DAQ triggers (see SDImagingMixin). trigger_logic is required on this setup.

    Experiment file: save_path (local folder, required) and zen_saving_path (required: the folder where ZEN
    creates the data folder of the experiment; it must be an existing folder that can be listed - checked
    before any hardware call). zen_saving_path is only read. save_network_path is not used on this setup.

    ZEN settings check: before any hardware call, a modal box 'ZEN settings' (SDImagingMixin
    _confirm_zen_settings, shared with the Hi-M task) lists the ZEN settings to check in block 7 - the channels to select (the
    wavelengths of the imaging sequence, in order) and the number of loops for blocks 4>9 (the number
    of ROIs scanned in this run, from start_roi to the end of the list) - and waits for the answer:
    'Done - continue' starts the scan, Cancel ends the task without touching the hardware. Both values
    are also logged. Then the progress shows 'Waiting for ZEN "ready"' until ZEN is ready.

    Data folder: named after the folder ZEN creates for the experiment. The folders of zen_saving_path
    are listed before waiting for ZEN "ready"; once ZEN is ready, the single new folder is the ZEN data
    folder (SDImagingMixin, shared with the Hi-M task; error if there is none or several, then the cleanup
    runs as usual). qudi creates <save_path>/<YYYY-MM-DD>/<ZEN folder name>/metadata (local_dated_root,
    created and write-tested before any hardware call, YYYY-MM-DD = start of the task; create_mirror_folder,
    metadata_<HHMMSS> if that folder already holds files) - always local - and writes there
    parameters.yml, movie_name.txt, experiment_config.yaml and metadata.yml. Nothing is written in the ZEN
    folder. self.prefix is the number of folders that were in zen_saving_path before ZEN started + 1, on 3
    digits; movie names scan_<prefix>_<roi number>_ROI (scan_<prefix>_DAPI_... / scan_<prefix>_RNA_...).

    Config example for copy-paste (logic: task_runner: options: module_tasks:):

        roi_multicolour_scan:
          module.Class: 'qudi.tasks.roi_multicolour_scan.RoiScanSDTask'
          connect:
            roi_logic: roi_logic
            trigger_logic: trigger_logic
            laser_logic: laser_control_logic
          options:
            user_config_path: '/path/to/qudi_task_config_files/roi_multicolor_scan_task_sd.yaml'
            metadata_template: '/path/to/custom_metadata_templates/Spinning_Disk_setup.cfg'  # optional
            acquisition_timeout_s: 120.0   # optional, max wait for ZEN's "done" trigger per block
            poll_interval_s: 0.1           # optional
    """

    trigger_logic = Connector(interface='TriggerLogic')

    def _confirm_before_start(self) -> bool:
        """ZEN settings box (SDImagingMixin._confirm_zen_settings) with loops = number of ROIs scanned in this
        run. True: continue, False: cancel."""
        return self._confirm_zen_settings(len(self._scan_rois))

    def _read_data_location(self, params) -> None:
        """save_path (required), save_network_path (optional) as on all setups, plus zen_saving_path (required,
        an existing folder that can be listed)."""
        super()._read_data_location(params)
        self.zen_saving_path = params.get('zen_saving_path')
        self._zen_folders_before = set()
        self._zen_directory = None
        problems = self._zen_saving_path_problems()
        if problems:
            raise RuntimeError('; '.join(problems) + f' (experiment file {self.user_config_path}).')

    def _choose_data_root(self) -> str:
        """<save_path>/<YYYY-MM-DD> (start of the task), always local."""
        return local_dated_root(self.save_path)

    def _prepare_imaging(self) -> None:
        """List the folders of zen_saving_path, show 'Waiting for ZEN "ready"' in the progress line, run the SD
        imaging preparation (SDImagingMixin: laser source, wait for ZEN "ready"), then find the new folder
        created by ZEN."""
        self._zen_folders_before = self._zen_folders()
        self._report_progress(f'0/{len(self._scan_rois)}', 'Waiting for ZEN "ready"', log=False)
        super()._prepare_imaging()
        self._zen_directory = self._find_new_zen_folder(self._zen_folders_before)

    def _create_data_folder(self) -> str:
        """<root>/<ZEN folder name>/metadata (create_mirror_folder); self.prefix = folders in zen_saving_path
        before ZEN started + 1, on 3 digits."""
        self.prefix = str(len(self._zen_folders_before) + 1).zfill(3)
        return create_mirror_folder(self._data_root, self._zen_directory, self.log)


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
        #     metadata_template: 'TO FILL'  # optional, e.g. .../custom_metadata_templates/RAMM_setup.cfg
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
            metadata_template: '/home/jb/Repositories/qudi-core-HiM/custom_config/custom_metadata_templates/Spinning_Disk_setup.cfg'
            dummy_imaging_time_s: 2.0      # optional
    """
