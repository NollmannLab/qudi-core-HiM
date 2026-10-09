# -*- coding: utf-8 -*-
"""
Author: F. Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2026-08-06
Modified for qudi-core: 2026-10-02

qudi-core-HiM task: scan a list of ROIs in order to photobleach the sample and reduce the background
fluorescence signal.

This is a qudi-core ModuleTask translation of the legacy qudi (InterruptableTask) tasks
tasks/photobleaching_task_AIRYSCAN.py, logic/tasks/photobleaching_task_RAMM.py and
logic/tasks/photobleaching_task_Celesta.py. The legacy files are left untouched.

Structure - all five classes live in this one file, for all setups:
  - PhotoBleachingBase: all the shared code. For each ROI: move the stage, wait until it is idle,
    switch the lasers on, wait for the illumination time (interruptible), switch the lasers off.
  - PhotoBleachingSDTask / PhotoBleachingRAMMTask: one subclass per setup. They only set class
    attributes (YAML location, and on the SD the start/end warnings).
  - PhotoBleachingSDDummyTask / PhotoBleachingRAMMDummyTask: one dummy subclass per setup, at the
    end of this file, running the same code on the dummy hardware (dummy_config.cfg); only the
    YAML location differs.
Per-setup differences are class attributes because qudi-core 1.7.0 does not pass the task config
options to ModuleTasks.

Modified for qudi-core-HiM (2026-10-08, Modified with Claude code): added the class attributes
  start_warning / end_warning. The task only works if the TTL cable has been manually disconnected
  from the Lumencor (Celesta) shutter input beforehand, and the cable must be reconnected afterwards.
  The Task Runner GUI shows start_warning as a confirmation dialog when Run is clicked and
  end_warning as a reminder when the task ends (dialogs are opened by the GUI, never by the task,
  which runs in a worker thread). No other change to this task.

Modified for qudi-core-HiM (2026-10-09, Modified with Claude code): unified photobleaching task.
  Renamed from photobleaching_sd.py (git mv). The shared code moved to PhotoBleachingBase, with
  PhotoBleachingSDTask (the former PhotoBleachingTask: same YAML path and warnings) and the new
  PhotoBleachingRAMMTask (YAML path still 'TO FILL': the task refuses to run, before touching any
  hardware, until it is filled in). Illumination time is now in SECONDS everywhere (the "* 60"
  conversion is gone). The illumination wait checks for an interrupt at least every 0.1 s, so a
  stop from the Task Runner takes effect during illumination too; _cleanup then switches the
  lasers off. Removed the trigger_logic connector and the Celesta shutter trigger pulse (it was
  only a test - on the SD the shutter TTL cable is disconnected by hand, see the warnings), the
  unused ZEN handshake methods _wait_for_ready / _wait_for_done, the resume text and unused
  imports. The config path is now logged at info level. Returns {'photobleached_rois': [...]}.

Modified for qudi-core-HiM (2026-10-09, Modified with Claude code): dummy classes moved here from
  photobleaching_dummy.py (one file for all setups).

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

import yaml
from time import monotonic, sleep

from qudi.core.scripting.moduletask import ModuleTask
from qudi.core.connector import Connector


class PhotoBleachingBase(ModuleTask):
    """Shared photobleaching code: scan a list of ROIs and illuminate each one for a fixed time.

    Not meant to be configured directly - use a setup subclass (PhotoBleachingSDTask,
    PhotoBleachingRAMMTask) or one of the dummies at the end of this file. A subclass sets
    ``user_config_path`` (and, if the setup needs a manual step, ``start_warning`` /
    ``end_warning``, shown by the Task Runner GUI). Nothing is passed through the Task Runner: the
    task has no call parameters, everything comes from the YAML written by the experiment
    configurator.

    For each ROI: move the stage, wait until it is idle, switch all the laser lines of the imaging
    sequence on, wait ``illumination_time`` seconds (interruptible), switch them off.

    User config file (user_config_path) expected keys:
        roi_list_path: 'pathstem/qudi_roi_lists/roilist_20260101.json'
        imaging_sequence: [[561, 50.0], [640, 80.0]]   # [wavelength (nm), intensity (%)]
        illumination_time: 30.0                        # SECONDS, per ROI

    Interrupt: the illumination wait checks for an interrupt at least every 0.1 s. After an
    interrupt (or any error) the base class runs _cleanup(), which switches the lasers off and puts
    the stage and ROI GUI back in their idle state.
    """

    roi_logic = Connector(interface='RoiLogic')
    laser_logic = Connector(interface='LaserControlLogic')

    user_config_path = None   # set by each setup subclass
    poll_interval_s = 0.1
    scan_stage_velocity = {'x': 1000.0, 'y': 1000.0}  # µm/S
    idle_stage_velocity = {'x': 6000.0, 'y': 6000.0}

    _UNSET_PATHS = (None, '', 'TO FILL')
    _MAX_WAIT_STEP_S = 0.1  # maximum time between two interrupt checks while illuminating

    def _setup(self) -> None:
        # False until _run() starts touching the hardware; _cleanup() then has nothing to restore.
        # Set first, so that _cleanup() also works if fetching a connector below fails.
        self._hardware_touched = False
        self.roi_list_path = None
        self.roi_names = []
        self.imaging_sequence = None
        self.illumination_time = None
        self._photobleached_rois = []

        self._roi_logic = self.roi_logic()
        self._laser_logic = self.laser_logic()

    # ======================================================================================
    # Main entry point
    # ======================================================================================

    def _run(self) -> dict:
        """Photobleach every ROI of the list, one after the other."""
        self._check_user_config_path()

        self._hardware_touched = True
        self._load_user_parameters()
        self._check_interrupt()

        # make sure the lasers are disabled when starting
        self._laser_logic.set_laser_disabled()

        # disable interfering GUI actions - mirrors legacy startTask()
        self._roi_logic.disable_tracking_mode()
        self._roi_logic.disable_roi_actions()
        self._roi_logic.set_stage_velocity(self.scan_stage_velocity)

        self._check_interrupt()

        # launch the photobleaching, one ROI at a time
        self.log.info(f'{len(self.roi_names)} ROI(s) to photobleach, '
                      f'{self.illumination_time:g} s each.')
        for roi_name in self.roi_names:
            self._check_interrupt()
            self._move_to_roi(roi_name)
            self._illuminate_roi()
            self._photobleached_rois.append(roi_name)

        return {'photobleached_rois': list(self._photobleached_rois)}

    def _cleanup(self) -> None:
        """Return hardware to a safe idle state. Called unconditionally by the ModuleTask base class
        whether _run() finished normally, raised, or was interrupted. Each step is protected on its
        own and this method never raises.
        """
        if not getattr(self, '_hardware_touched', False):
            self.log.info('cleanup: no hardware was touched, nothing to restore')
            return

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
    # Per-ROI steps
    # ======================================================================================

    def _move_to_roi(self, roi_name: str) -> None:
        """Move the stage to one ROI and wait until it has arrived."""
        self.log.info(f'Moving to {roi_name}')
        self._roi_logic.set_active_roi(name=roi_name)
        self._roi_logic.go_to_roi_xy()
        self._roi_logic.stage_wait_for_idle()
        self._check_interrupt()

    def _illuminate_roi(self) -> None:
        """Switch all the laser lines on, wait illumination_time seconds, switch them off. If the
        task is interrupted during the wait, the lasers are switched off by _cleanup().
        """
        self._laser_logic.set_laser_enabled()
        self._interruptible_wait(self.illumination_time)
        self._laser_logic.set_laser_disabled()

    def _interruptible_wait(self, duration_s: float) -> None:
        """Wait duration_s seconds, checking for an interrupt at least every 0.1 s."""
        step_s = min(float(self.poll_interval_s), self._MAX_WAIT_STEP_S)
        deadline = monotonic() + float(duration_s)
        while True:
            self._check_interrupt()
            remaining_s = deadline - monotonic()
            if remaining_s <= 0:
                return
            sleep(min(step_s, remaining_s))

    # ======================================================================================
    # User parameters
    # ======================================================================================

    def _check_user_config_path(self) -> None:
        """Refuse to run, before touching any hardware, if the setup subclass has no YAML path."""
        if self.user_config_path in self._UNSET_PATHS:
            raise RuntimeError(f'user_config_path not set for {type(self).__name__} — fill it in '
                               f'photobleaching.py')

    def _load_user_parameters(self) -> None:
        """Load the user-defined experiment parameters (ROI list, imaging sequence, illumination
        time) from the YAML file at self.user_config_path. See class docstring for the expected keys.
        """
        self.log.info(f'Loading photobleaching parameters from {self.user_config_path}')
        with open(self.user_config_path, 'r') as stream:
            user_param_dict = yaml.safe_load(stream)

        self.roi_list_path = user_param_dict['roi_list_path']
        self.imaging_sequence = user_param_dict['imaging_sequence']
        self.illumination_time = float(user_param_dict['illumination_time'])  # seconds

        self._roi_logic.load_roi_list(self.roi_list_path)
        self.roi_names = list(self._roi_logic.roi_names)

        self.num_laserlines = len(self.imaging_sequence)
        self._laser_logic.set_external_trigger(False)
        for wavelength, intensity in self.imaging_sequence:
            self._laser_logic.set_laser_line_intensity(int(wavelength), float(intensity))


class PhotoBleachingSDTask(PhotoBleachingBase):
    """Photobleaching on the spinning-disk setup.

    The lasers only emit if the TTL cable has been manually disconnected from the Lumencor (Celesta)
    shutter input before starting, and it must be reconnected afterwards: the Task Runner GUI asks
    for confirmation before starting (start_warning) and shows a reminder when the task ends
    (end_warning).

    Config example for copy-paste (logic: task_runner: options: module_tasks:):

        photobleaching:
          module.Class: 'qudi.tasks.photobleaching.PhotoBleachingSDTask'
          connect:
            roi_logic: roi_logic
            laser_logic: laser_control_logic
    """

    user_config_path = '/home/him_spinning/qudi/qudi_task_config_files/photobleaching_task_sd.yaml'
    # Shown by the Task Runner GUI (see gui/task_runner/taskwidget.py): confirmation before start,
    # reminder when the task ends.
    start_warning = ('Before starting the photobleaching: manually disconnect the TTL cable from the '
                     'Lumencor (Celesta) shutter input. Otherwise the task will run but the lasers '
                     'will not emit.')
    end_warning = ('Photobleaching finished: reconnect the TTL cable to the Lumencor (Celesta) '
                   'shutter input before running any imaging task.')


class PhotoBleachingRAMMTask(PhotoBleachingBase):
    """Photobleaching on the RAMM setup. No manual step, so no start/end warning.

    The location of the YAML written by the experiment configurator on the RAMM computer is not
    known yet: user_config_path is 'TO FILL', and the task refuses to run (clear error, before any
    hardware call) until it is filled in here.

    Config example for copy-paste (logic: task_runner: options: module_tasks:) - not in
    RAMM_config.cfg yet, which has no laser_control_logic so far:

        # photobleaching:
        #   module.Class: 'qudi.tasks.photobleaching.PhotoBleachingRAMMTask'
        #   connect:
        #     roi_logic: roi_logic
        #     laser_logic: laser_control_logic
    """

    user_config_path = 'TO FILL'


# ==========================================================================================
# Dummy versions — same code, dummy-setup YAML path, for testing on dummy_config.cfg
# ==========================================================================================

class PhotoBleachingSDDummyTask(PhotoBleachingSDTask):
    """Spinning-disk photobleaching on the dummy hardware (same code and warnings as the SD task).

    Config example for copy-paste (dummy_config.cfg, logic: task_runner: options: module_tasks:):

        photobleaching_sd_dummy:
          module.Class: 'qudi.tasks.photobleaching.PhotoBleachingSDDummyTask'
          connect:
            roi_logic: roi_logic
            laser_logic: laser_control_logic
    """

    # Written by the experiment configurator for the 'photobleaching_SD' dummy definition
    user_config_path = '/home/jb/qudi/qudi_task_config_files/photobleaching_task_sd.yaml'


class PhotoBleachingRAMMDummyTask(PhotoBleachingRAMMTask):
    """RAMM photobleaching on the dummy hardware (same code as the RAMM task, no warnings).

    Config example for copy-paste (dummy_config.cfg, logic: task_runner: options: module_tasks:):

        photobleaching_ramm_dummy:
          module.Class: 'qudi.tasks.photobleaching.PhotoBleachingRAMMDummyTask'
          connect:
            roi_logic: roi_logic
            laser_logic: laser_control_logic
    """

    # Written by the experiment configurator for the 'photobleaching_RAMM' dummy definition
    # (output_filename of custom_experiments_config/dummy/photobleaching_ramm.yaml)
    user_config_path = '/home/jb/qudi/qudi_task_config_files/photobleaching_task_RAMM.yaml'
