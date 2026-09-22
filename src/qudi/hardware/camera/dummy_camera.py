# -*- coding: utf-8 -*-
"""
Author: F. Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2026-08-06
Modified with Claude code (Anthropic) - functionalities modified or added by Claude:
  2026-09-20    : module rewritten as a time-based simulation following the contract of camera_interface.py (frames
                  produced at the rate imposed by the exposure, synthetic scene with orientation marker, live, movie,
                  ROI (1-based, inclusive), abort, no-live mode, wait_until_finished, gain limits, True = success).
                  The Andor-specific simulation helpers were kept unchanged.
  2026-09-22    : is_available() reports the failure of a simulated activation (resolution with less than 100 rows, the
                  error is logged and not raised), to test a camera interfuse with a camera that is not accessible.

This module was available in Qudi legacy version and was extended. It simulates a microscope camera following the
contract defined in camera_interface.py, so that the GUI and the logic can be tested without any hardware.

The camera "observes" a fixed synthetic scene (intensity gradient, blobs and a bright marker in the top-left corner)
that is cropped by the ROI, with a noise level that depends on the exposure and the gain. Frames are produced at the
rate imposed by the exposure time, starting when an acquisition is launched - like a real camera filling its buffer.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

import numpy as np
import time
from qudi.interface.camera_interface import CameraInterface
from qudi.core.configoption import ConfigOption


class CameraDummy(CameraInterface):
    """ Dummy implementation of a microscope camera.

    Example config for copy-paste:

    camera_dummy:
        module.Class: 'camera.dummy_camera.CameraDummy'
        options:
            camera_name: 'Dummy camera'
            resolution:  # (number of rows, number of columns)
                - 512
                - 512
            support_live: True
            default_exposure: 0.05  # in s
            max_N_images_movie: 200
    """
    # config options
    _support_live = ConfigOption('support_live_acquisition', True)  # a camera without live mode is simulated when False
    _resolution = ConfigOption('resolution', (720, 1280))  # (nb rows, nb cols) because row-major format is used
    _default_exposure = ConfigOption('default_exposure', 0.05)  # in seconds
    _max_frames_number_video = ConfigOption('max_N_images_movie', missing='error')
    _has_temp = ConfigOption('temperature_control', False)
    _has_shutter = ConfigOption('mechanical_shutter', False)
    _has_gain = ConfigOption('gain_control', False)
    _camera_name = ConfigOption('camera_name', missing='error')
    _frame_transfer = ConfigOption('frame_transfer', False)
    # the options below are not used by the dummy camera - they are only declared so that the same configuration can
    # be used for the real cameras
    _default_acquisition_mode = ConfigOption('default_acquisition_mode', 'Dynamic Range')
    camera_id = ConfigOption('camera_id', 0)
    _default_trigger_mode = ConfigOption('default_trigger_mode', 'INTERNAL')
    _default_exposure_out_mode = ConfigOption('default_exposure_out_mode', 'ALL_ROWS')
    # the following option was only introduced to simulate a failure in the activation
    _simulate_activation_failure = ConfigOption('simulate_activation_failure', False)

    # camera attributes
    _full_width = 0  # maximum width of the sensor
    _full_height = 0  # maximum height of the sensor
    _exposure = 0.05
    _gain = 1
    _trigger_mode = 'INTERNAL'
    n_frames = 1
    image_size = ()  # (height, width) of the current image
    _roi = None  # (row start, row end, column start, column end) of the ROI, in python (0-based, end excluded) indices
    _scene = None  # image of the simulated sample
    _mode = None  # None (idle), 'live' or 'sequence'
    _available = True  # False if the simulated camera failed to initialize (see on_activate)
    _t_start = 0.  # time at which the current acquisition started
    _frame_offset = 0  # number of frames acquired before the last change of the exposure time

    # only needed for simulations with _has_temp = True
    temperature = 17
    _default_temperature = 12

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        self._full_height = int(self._resolution[0])
        self._full_width = int(self._resolution[1])
        self._roi = (0, self._full_height, 0, self._full_width)
        self.image_size = (self._full_height, self._full_width)
        self._exposure = self._default_exposure
        self._gain = 1
        self._trigger_mode = 'INTERNAL'
        self.n_frames = 1
        self._mode = None
        self._frame_offset = 0
        self._scene = self._create_scene(self._full_height, self._full_width)

        # simulation of a camera that cannot be initialized : a resolution with less than 100 rows. Like the real
        # cameras, the error is logged (not raised) and reported by is_available(), so that a camera interfuse can leave
        # the camera out of its list
        self._available = True
        if self._simulate_activation_failure:
            self.log.error("camera is not accessible")
            self._available = False

    def is_available(self):
        """ Return False if the simulated camera could not be initialized in on_activate (resolution < 100 rows). """
        return self._available

    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        self.stop_acquisition()

# ======================================================================================================================
# Camera Interface functions
# ======================================================================================================================

# ----------------------------------------------------------------------------------------------------------------------
# Getter and setter methods
# ----------------------------------------------------------------------------------------------------------------------

    def get_name(self):
        """ Retrieve an identifier of the camera that the GUI can print.

        :return: string: name for the camera
        """
        return self._camera_name

    def get_size(self):
        """ Retrieve size of the FULL sensor in pixel.

        :return: list (int, int): Size (width, height)
        """
        return [self._full_width, self._full_height]

    def set_exposure(self, exposure):
        """ Set the exposure time in seconds.

        :param: float exposure: desired new exposure time

        :return: bool: Success ?
        """
        if self._mode is not None:  # keep the count of the frames acquired so far consistent
            self._frame_offset = self._frame_count()
            self._t_start = time.monotonic()
        self._exposure = float(exposure)
        return True

    def get_exposure(self):
        """ Get the exposure time in seconds.

        :return: float exposure time
        """
        return self._exposure

    def set_gain(self, gain):
        """ Set the gain.

        :param: int gain: desired new gain

        :return: bool: Success ?
        """
        self._gain = gain
        return True

    def get_gain(self):
        """ Get the gain.

        :return: int gain
        """
        return self._gain

    def get_gain_limits(self):
        """ Get the gain limits
        @return: (int) return the low and high limits
        """
        return 1, 100

    def get_ready_state(self):
        """ Is the camera ready for an acquisition ? The camera is busy during a live acquisition and until all the
        frames of a sequence were acquired.

        :return: bool: ready ?
        """
        if self._mode == 'live':
            return False
        if self._mode == 'sequence':
            return self._frame_count() >= self.n_frames
        return True

    def set_image(self, hbin, vbin, hstart, hend, vstart, vend):
        """ Sets a ROI on the sensor surface. The binning parameters are not used but they are needed in the
        function call to be conform with the other cameras.

        :param: int hbin: number of pixels to bin horizontally
        :param: int vbin: number of pixels to bin vertically.
        :param: int hstart: Start column (first column of the sensor = 1)
        :param: int hend: End column (inclusive)
        :param: int vstart: Start row (first row of the sensor = 1)
        :param: int vend: End row (inclusive).

        :return: bool: Success ?
        """
        row_start = max(int(vstart) - 1, 0)
        row_end = min(int(vend), self._full_height)
        col_start = max(int(hstart) - 1, 0)
        col_end = min(int(hend), self._full_width)
        if row_end <= row_start or col_end <= col_start:
            self.log.warning('Camera dummy: the requested region is empty.')
            return False
        self._roi = (row_start, row_end, col_start, col_end)
        self.image_size = (row_end - row_start, col_end - col_start)  # rows, cols
        return True

    def get_image_size(self):
        """
        Get the size of the image (after setting an ROI for example)
        @return: (tuple) height and width of the image
        """
        return self.image_size

    def get_progress(self):
        """ Retrieves the total number of acquired images during an acquisition.

        :return: int progress: total number of acquired images.
        """
        return self._frame_count()

    def get_max_frames(self):
        max_frames_dict = {'video': self._max_frames_number_video}
        return max_frames_dict

# ----------------------------------------------------------------------------------------------------------------------
# Methods to query the camera properties
# ----------------------------------------------------------------------------------------------------------------------

    def support_live_acquisition(self):
        """ Return whether or not the camera can take care of live acquisition.

        :return: bool: True if supported, False if not
        """
        return self._support_live

    def has_temp(self):
        """ Does the camera support setting of the temperature?

        :return: bool: has temperature ?
        """
        return self._has_temp

    def has_shutter(self):
        """ Is the camera equipped with a mechanical shutter?

        :return: bool: has shutter ?
        """
        return self._has_shutter

    def has_gain(self):
        """ Is the camera allowing gain control?
        @return: (bool) has gain ?
        """
        return self._has_gain

    def support_frame_transfer(self):
        """ Is frame transfer mode allowed?
        @return: (bool) frame transfer possible?
        """
        return self._frame_transfer

# ----------------------------------------------------------------------------------------------------------------------
# Methods to handle camera acquisitions
# ----------------------------------------------------------------------------------------------------------------------

# Methods for displaying images on the GUI -----------------------------------------------------------------------------
    def start_single_acquisition(self):
        """ Acquire a single image (blocking during the exposure time).

        :return: numpy array: the acquired image - None if the camera is busy
        """
        if self._mode is not None:
            self.log.warning('Camera dummy: the camera is busy, no single image can be acquired.')
            return None
        time.sleep(self._exposure + 0.001)
        return self._create_frame()

    def start_live_acquisition(self):
        """ Start a continuous acquisition

        :return: bool: Success ?
        """
        if not self._support_live or self._mode == 'sequence':
            return False
        self._start_timer('live')
        return True

    def stop_acquisition(self):
        """ Stop/abort live or single acquisition

        :return: bool: Success ?
        """
        self._mode = None
        return True

# Methods for saving image data ----------------------------------------------------------------------------------------
    def start_movie_acquisition(self, n_frames):
        """ Set the conditions to save a movie and start the acquisition (fixed length mode).

        :param: int n_frames: number of frames

        :return: bool: True if the acquisition started
        """
        if self._mode is not None:  # video can only be started if not yet in live or acquisition mode
            self.log.warning('Camera dummy: the camera is busy, the movie acquisition cannot start.')
            return False
        self.n_frames = int(n_frames)
        self._start_timer('sequence')
        self.log.info('Camera dummy: started movie acquisition')
        return True

    def finish_movie_acquisition(self):
        """ Reset the conditions used to save a movie to default.

        :return: bool: Success ?
        """
        self._mode = None
        self.n_frames = 1
        self.log.info('Camera dummy: movie acquisition finished')
        return True

    def abort_movie_acquisition(self):
        """ Abort a movie acquisition. """
        self.finish_movie_acquisition()

    def wait_until_finished(self, timeout=None):
        """ Wait until an acquisition is finished.

        :param: float timeout: maximum waiting time in s (default : the time needed to acquire n_frames + 10 s)
        """
        if timeout is None:
            timeout = self.n_frames * (self._exposure + 0.001) + 10
        start = time.monotonic()
        while not self.get_ready_state() and time.monotonic() - start < timeout:
            time.sleep(0.01)

# Methods for acquiring image data using synchronization between lightsource and camera---------------------------------
    def prepare_camera_for_multichannel_imaging(self, frames, exposure, gain, save_path, file_format):
        """ Set the camera state for an experiment using synchronization between lightsources and the camera.
        Using typically an external trigger. The triggers are not simulated : once started, the sequence is acquired as
        if the trigger signals were received at the rate imposed by the exposure time.

        :param: int frames: number of frames in a kinetic series / fixed length mode
        :param: float exposure: exposure time in seconds
        :param: int gain: gain setting
        :param: str save_path: complete path (without fileformat suffix) where the image data will be saved
        :param: str file_format: selected fileformat such as 'tiff', 'fits', ..

        :return: None
        """
        self.stop_acquisition()
        self.set_exposure(exposure)
        self.n_frames = int(frames)
        self._trigger_mode = 'EXTERNAL'

    def reset_camera_after_multichannel_imaging(self):
        """ Reset the camera to a default state after an experiment using synchronization between lightsources and
         the camera.

         :return: None
         """
        self.stop_acquisition()
        self._trigger_mode = 'INTERNAL'
        self.n_frames = 1

# ----------------------------------------------------------------------------------------------------------------------
# Methods for image data retrieval
# ----------------------------------------------------------------------------------------------------------------------

    def get_most_recent_image(self, copy=True):
        """ Return the last acquired image and the number of images acquired so far.

        :param: bool copy: not used (the images are always new arrays)
        :return: (numpy array, int): image data in format [[row],[row]...] (None if no image is available yet) and
        number of acquired images
        """
        count = self._frame_count()
        if self._mode is None or count == 0:
            return None, 0
        return self._create_frame(), count

    def get_acquired_data(self):
        """ Return the complete data of a finished fixed length acquisition.

        :return: numpy array: image data in format [n_frames, rows, cols] - None if the acquisition is not finished
        """
        if self._mode != 'sequence':
            self.log.error('Camera dummy: no movie acquisition was started - no data available.')
            return None
        if not self.get_ready_state():
            self.log.error('Camera dummy: acquisition is still in process. Data are not accessible.')
            return None
        data = np.empty((self.n_frames,) + tuple(self.image_size), dtype=np.uint16)
        for i in range(self.n_frames):
            data[i] = self._create_frame()
        return data

# ======================================================================================================================
# Non-Interface functions
# ======================================================================================================================

# ----------------------------------------------------------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------------------------------------------------------

    def _start_timer(self, mode):
        """ Start an acquisition: from now on, one frame is produced every exposure time. """
        self._mode = mode
        self._frame_offset = 0
        self._t_start = time.monotonic()

    def _frame_count(self):
        """ Number of frames produced since the beginning of the current acquisition. A sequence stops when all its
        frames were acquired."""
        if self._mode is None:
            return 0
        count = self._frame_offset + int((time.monotonic() - self._t_start) / (self._exposure + 0.001))
        if self._mode == 'sequence':
            count = min(count, self.n_frames)
        return count

    @staticmethod
    def _create_scene(height, width):
        """ Create the image of the simulated sample: an intensity gradient, three blobs of different sizes and a bright
        marker in the top-left corner (to check the orientation of the image and the ROI).

        :param: int height, width: size of the sensor
        :return: numpy array (float32) of shape (height, width)
        """
        rows, cols = np.mgrid[0:height, 0:width].astype(np.float32)
        scene = 100 + 500 * cols / max(width - 1, 1)  # horizontal gradient
        for (row, col, size, amplitude) in [(0.30, 0.30, 0.04, 3000), (0.65, 0.70, 0.08, 2000), (0.80, 0.25, 0.02, 4000)]:
            sigma = size * max(height, width)
            scene += amplitude * np.exp(-((rows - row * height) ** 2 + (cols - col * width) ** 2) / (2 * sigma ** 2))
        scene[:max(int(0.08 * height), 1), :max(int(0.15 * width), 1)] = 5000  # marker of the top-left corner
        return scene

    def _create_frame(self):
        """ Simulate one frame : the part of the scene defined by the ROI, scaled by the exposure and the gain, plus
        a noise.

        :return: numpy array (uint16) of shape (rows, cols)
        """
        row_start, row_end, col_start, col_end = self._roi
        signal = self._scene[row_start:row_end, col_start:col_end] * (self._exposure / 0.05) * self._gain
        frame = signal + np.random.normal(scale=15, size=signal.shape)
        return np.clip(frame, 0, 65535).astype(np.uint16)

# ----------------------------------------------------------------------------------------------------------------------
# Simulation of Andor camera
# ----------------------------------------------------------------------------------------------------------------------

    def _set_spool(self, active, mode, filenamestem, framebuffer):
        """ Simulates the spooling functionality of the andor camera.
         This function must be available if camera name is set to iXon Ultra 897
         """
        if active == 1:
            self.log.info('camera dummy: started spooling')
        elif active == 0:
            self.log.info('camera dummy: spooling finished')
        else:
            pass

    def get_kinetic_time(self):
        """ Simulates kinetic time method of andor camera.
        This function must be available if camera name is set to iXon Ultra 897.

        :return: float kinetic time """
        if self._frame_transfer:
            return self._exposure + 0.123
        else:
            return self._exposure + 0.7654321

    def _set_frame_transfer(self, transfer_mode):
        """ set the frame transfer mode

        :param: int tranfer_mode: 0: off, 1: on
        :returns: int error code 0 = ok, -1 = error
        """
        if transfer_mode == 1:
            self._frame_transfer = True
            self.log.info('Camera dummy: activated frame transfer mode, transfer_mode {}'.format(transfer_mode))
            err = 0
        elif transfer_mode == 0:
            self._frame_transfer = False
            self.log.info('Camera dummy: deactivated frame transfer mode, transfer_mode {}'.format(transfer_mode))
            err = 0
        else:
            self.log.info('Camera dummy: specify the transfer_mode to set frame transfer, transfer_mode {}'.format(transfer_mode))
            err = -1
        return err

    # temperature getter / setter functions
    def set_temperature(self, temp):
        """ Set the temperature setpoint.

        :param int temp: desired new temperature

        :return: bool: success ?
        """
        self.temperature = temp
        return True

    def get_temperature(self):
        """ Get the current temperature.

        :return int: temperature
        """
        return self.temperature

    def is_cooler_on(self):
        """ Checks the status of the cooler.

        :return: int: 0: cooler is off, 1: cooler is on
        """
        return 1

    def _set_cooler(self, state):
        """ This method is called to switch the cooler on or off

        :params: bool state: cooler on = True, cooler off = False

        :return: error message: ok = 0 """
        return 0
