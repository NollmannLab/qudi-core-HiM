# -*- coding: utf-8 -*-
"""
Author: JB Fiche - written with Claude code for qudi-core-HiM
Created: 2026-09-21
Written with Claude code (Anthropic) : the whole module (interfuse, camera selection, reset of the selected camera).

Qudi-core-HiM interfuse giving access to several cameras of the same microscope through a single CameraInterface.

camera_logic is connected to this module like to any camera hardware. Only one camera is used at a time : the calls of the
CameraInterface are forwarded to the active camera, which is selected with set_active_camera (in the GUI : the
"Select camera" combo box of the basic imaging GUI, through camera_logic.select_camera).

Up to three cameras can be connected. The first one is mandatory and is active when the module is activated, the two
others are optional. A camera that could not be initialized (a hardware module logs its activation error and reports
is_available() = False, so that the interfuse, the logic and the GUI can still be activated) is not available in the
list of cameras; if no camera is available, the interfuse cannot be activated. The names
of the cameras are the ones given by get_name(); if two cameras have the same name, a number is appended.

When another camera is selected, it is reset to its default state : exposure time and gain measured when the interfuse
was activated, and full sensor size.

Any attribute or method that is not part of the CameraInterface (for example the Andor-specific methods) is forwarded to
the active camera.

Example config for copy-paste:

    camera_interfuse:
      module.Class: 'interfuse_hardware.camera_interfuse.CameraInterfuse'
      connect:
        camera_1: 'orca_camera'
        camera_2: 'kinetix_camera'
        camera_3: 'other_camera'  # optional

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from qudi.core.connector import Connector
from qudi.interface.camera_interface import CameraInterface


class CameraInterfuse(CameraInterface):
    """ Forward the CameraInterface to one camera selected among up to three cameras. """

    # the first camera is mandatory, the two others are optional
    camera_1 = Connector(name='camera_1', interface='CameraInterface')
    camera_2 = Connector(name='camera_2', interface='CameraInterface', optional=True)
    camera_3 = Connector(name='camera_3', interface='CameraInterface', optional=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cameras = {}  # name -> camera hardware module, in the order of the connectors
        self._defaults = {}  # name -> (exposure, gain) measured at activation
        self._active_name = None

    # ------------------------------------------------------------------------------------------------------------------
    # Module activation
    # ------------------------------------------------------------------------------------------------------------------

    def on_activate(self):
        """ Collect the cameras that are available and activate the first one. """
        self._cameras = {}
        self._defaults = {}

        for connector_name in ('camera_1', 'camera_2', 'camera_3'):
            try:
                camera = getattr(self, connector_name)()
            except Exception as e:
                self.log.warning(f'{connector_name} is not available : {e}')
                continue
            if camera is None:  # optional connector that is not configured
                continue
            self._register_camera(connector_name, camera)

        if not self._cameras:
            raise RuntimeError('No camera is available : the camera interfuse cannot be used.')

        self._active_name = next(iter(self._cameras))
        self.log.info(f'Available cameras : {list(self._cameras)} - active camera : {self._active_name}')

    def on_deactivate(self):
        """ The cameras are deactivated by qudi. Nothing to do. """
        self._cameras = {}

    def _register_camera(self, connector_name, camera):
        """ Add a camera to the list of the selectable cameras and store its default settings. A camera that reports an
        initialization failure (is_available) is left out of the list : the error was already logged by its module. """
        try:
            if not camera.is_available():
                self.log.warning(f'{connector_name} could not be initialized : it is not selectable.')
                return
            base_name = str(camera.get_name())
        except Exception as e:
            self.log.warning(f'{connector_name} is not usable and is not selectable : {e}')
            return
        name = base_name
        index = 2
        while name in self._cameras:  # two cameras of the same model : names must be unique to be selectable
            name = f'{base_name} ({index})'
            index += 1
        self._cameras[name] = camera
        try:
            gain = camera.get_gain() if camera.has_gain() else None
            self._defaults[name] = (camera.get_exposure(), gain)
        except Exception as e:
            self.log.warning(f'Default settings of camera {name} could not be read : {e}')
            self._defaults[name] = (None, None)

    @property
    def _active(self):
        """ The camera hardware module that is currently used. """
        return self._cameras[self._active_name]

    def __getattr__(self, item):
        """ Forward what is not defined in the interfuse (Andor-specific methods, private attributes read by the logic
        such as _default_temperature or _shutter, ...) to the active camera. """
        if item.startswith('__') or item in ('_cameras', '_defaults', '_active_name'):
            raise AttributeError(item)
        cameras = self.__dict__.get('_cameras')
        active_name = self.__dict__.get('_active_name')
        if not cameras or active_name not in cameras:
            raise AttributeError(item)
        return getattr(cameras[active_name], item)

    # ------------------------------------------------------------------------------------------------------------------
    # Selection of the camera
    # ------------------------------------------------------------------------------------------------------------------

    def get_available_cameras(self):
        """ Names of the cameras that are available. """
        return list(self._cameras)

    def get_active_camera(self):
        """ Name of the active camera. """
        return self._active_name

    def set_active_camera(self, name):
        """ Select another camera and reset it to its default state (exposure, gain, full sensor). The caller must make
        sure that the cameras are idle.
        @param: (str) name: name of the camera, as given by get_available_cameras
        @return: (bool) True if the camera is now active
        """
        if name not in self._cameras:
            self.log.error(f'Camera {name} is not available.')
            return False
        if name == self._active_name:
            return True

        camera = self._cameras[name]
        try:
            exposure, gain = self._defaults[name]
            if exposure is not None:
                camera.set_exposure(exposure)
            if gain is not None:
                camera.set_gain(gain)
            width, height = camera.get_size()
            camera.set_image(1, 1, 1, width, 1, height)
        except Exception as e:
            self.log.error(f'Camera {name} could not be reset to its default state : {e}')
            return False

        self._active_name = name
        return True

    def get_camera_type(self):
        """ Class name of the hardware module that drives the active camera. """
        return self._active.get_camera_type()

    # ------------------------------------------------------------------------------------------------------------------
    # CameraInterface - everything is forwarded to the active camera
    # ------------------------------------------------------------------------------------------------------------------

    def get_name(self):
        return self._active.get_name()

    def get_size(self):
        return self._active.get_size()

    def set_exposure(self, exposure):
        return self._active.set_exposure(exposure)

    def get_exposure(self):
        return self._active.get_exposure()

    def set_gain(self, gain):
        return self._active.set_gain(gain)

    def get_gain(self):
        return self._active.get_gain()

    def get_gain_limits(self):
        return self._active.get_gain_limits()

    def get_ready_state(self):
        return self._active.get_ready_state()

    def set_image(self, hbin, vbin, hstart, hend, vstart, vend):
        return self._active.set_image(hbin, vbin, hstart, hend, vstart, vend)

    def get_image_size(self):
        return self._active.get_image_size()

    def get_progress(self):
        return self._active.get_progress()

    def get_max_frames(self):
        return self._active.get_max_frames()

    def support_live_acquisition(self):
        return self._active.support_live_acquisition()

    def has_temp(self):
        return self._active.has_temp()

    def has_shutter(self):
        return self._active.has_shutter()

    def has_gain(self):
        return self._active.has_gain()

    def support_frame_transfer(self):
        return self._active.support_frame_transfer()

    def start_single_acquisition(self):
        return self._active.start_single_acquisition()

    def start_live_acquisition(self):
        return self._active.start_live_acquisition()

    def stop_acquisition(self):
        return self._active.stop_acquisition()

    def start_movie_acquisition(self, n_frames):
        return self._active.start_movie_acquisition(n_frames)

    def finish_movie_acquisition(self):
        return self._active.finish_movie_acquisition()

    def abort_movie_acquisition(self):
        return self._active.abort_movie_acquisition()

    def wait_until_finished(self, *args, **kwargs):
        return self._active.wait_until_finished(*args, **kwargs)

    def prepare_camera_for_multichannel_imaging(self, frames, exposure, gain, save_path, file_format):
        return self._active.prepare_camera_for_multichannel_imaging(frames, exposure, gain, save_path, file_format)

    def reset_camera_after_multichannel_imaging(self):
        return self._active.reset_camera_after_multichannel_imaging()

    def get_most_recent_image(self, copy=True):
        return self._active.get_most_recent_image(copy=copy)

    def get_acquired_data(self):
        return self._active.get_acquired_data()
