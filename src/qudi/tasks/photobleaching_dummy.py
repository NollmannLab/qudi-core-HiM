# -*- coding: utf-8 -*-
"""
Dummy photobleaching tasks, to test the photobleaching task on custom_config/dummy_config.cfg.

Each class runs the REAL setup code (photobleaching.py: PhotoBleachingSDTask, PhotoBleachingRAMMTask)
on the dummy hardware. The only difference is the location of the YAML written by the experiment
configurator on the dummy computer (user_config_path). In particular the SD dummy keeps the SD
start/end warnings, and the RAMM dummy has none, exactly like the real setups.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------

Modified for qudi-core-HiM (2026-10-09, Modified with Claude code): new file -
  PhotoBleachingSDDummyTask and PhotoBleachingRAMMDummyTask, the dummy counterparts of the SD and
  RAMM photobleaching tasks (only user_config_path is overridden).
"""

from qudi.tasks.photobleaching import PhotoBleachingSDTask, PhotoBleachingRAMMTask


class PhotoBleachingSDDummyTask(PhotoBleachingSDTask):
    """Spinning-disk photobleaching on the dummy hardware (same code and warnings as the SD task).

    Config example for copy-paste (dummy_config.cfg, logic: task_runner: options: module_tasks:):

        photobleaching_sd_dummy:
          module.Class: 'qudi.tasks.photobleaching_dummy.PhotoBleachingSDDummyTask'
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
          module.Class: 'qudi.tasks.photobleaching_dummy.PhotoBleachingRAMMDummyTask'
          connect:
            roi_logic: roi_logic
            laser_logic: laser_control_logic
    """

    # Written by the experiment configurator for the 'photobleaching_RAMM' dummy definition
    # (output_filename of custom_experiments_config/dummy/photobleaching_ramm.yaml)
    user_config_path = '/home/jb/qudi/qudi_task_config_files/photobleaching_task_RAMM.yaml'
