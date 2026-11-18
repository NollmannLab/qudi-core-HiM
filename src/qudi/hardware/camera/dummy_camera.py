# -*- coding: utf-8 -*-
"""
Author: F. Barho - adapted for qudi-core-HiM by JB Fiche
Created: 2026-08-06
Modified with Claude code (Anthropic)

This module was available in Qudi legacy version and was extended. It simulates a microscope camera following the
contract defined in camera_interface.py, so that the GUI and the logic can be tested without any hardware.

The camera "observes" a fixed synthetic sample - a field of cells with a faint cytoplasm, a textured nucleus and a few
bright foci, on a background of ~100 counts - that is cropped by the ROI, with a noise level that depends on the
exposure and the gain. The cells are placed at a fixed density, so their number grows with the sensor size (about 14
at 512 x 512, 28 at 1024 x 1024, 88 at 3200 x 3200); their size follows the module constants REFERENCE_SIZE,
CELL_RADIUS_PX, CELL_SIZE_EXPONENT and CELL_SPACING. The field is built from a fixed random seed, so the image is the
same at every start for a given sensor size. Frames are produced at the rate imposed by the exposure time, starting
when an acquisition is launched - like a real camera filling its buffer.

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
from scipy.ndimage import gaussian_filter
from qudi.interface.camera_interface import CameraInterface
from qudi.core.configoption import ConfigOption


# simulated sample of the camera (field of cells, see CameraDummy._create_scene)
REFERENCE_SIZE = 512  # sensor size (px) for which CELL_RADIUS_PX is defined
CELL_RADIUS_PX = 44  # mean cell semi-axis (px) on a 512 px sensor
CELL_SIZE_EXPONENT = 0.5  # cell size ~ (sensor size / 512) ** exponent; 0: fixed size in px
CELL_SPACING = 2.0  # minimum distance between cell centres, in mean cell radii


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

    # simulated sample: field of cells (see _create_scene and the module constants)
    SCENE_SEED = 7  # fixed seed: the same field of cells at every start
    SCENE_BACKGROUND = 100.  # background level (counts at the default exposure)

    @staticmethod
    def _cell_centres(height, width, rng):
        """ Mean cell radius and cell centres of the simulated sample: random positions at a fixed density, at least
        CELL_SPACING mean radii apart (dart throwing with a grid lookup, fast on large sensors), so that the number of
        cells grows with the sensor area. The mean radius is CELL_RADIUS_PX on a REFERENCE_SIZE sensor and scales as
        (sensor size / REFERENCE_SIZE) ** CELL_SIZE_EXPONENT.

        :param: int height, width: size of the sensor
        :param: numpy.random.Generator rng: random generator (consumed)
        :return: (float radius, list of numpy arrays (y, x) of the centres)
        """
        scale = min(height, width)
        radius = CELL_RADIUS_PX * (scale / REFERENCE_SIZE) ** CELL_SIZE_EXPONENT
        spacing = CELL_SPACING * radius
        n_target = int(0.55 * height * width / (np.pi * (spacing / 2) ** 2) * 0.6)
        cell = spacing / np.sqrt(2)  # grid step: at most one centre per grid cell
        grid, centres, attempts = {}, [], 0
        while len(centres) < n_target and attempts < 30 * n_target:
            attempts += 1
            c = rng.uniform((0.5 * radius, 0.5 * radius), (height - 0.5 * radius, width - 0.5 * radius))
            gy, gx = int(c[0] // cell), int(c[1] // cell)
            if any(np.hypot(*(c - grid[(gy + i, gx + j)])) < spacing
                   for i in range(-2, 3) for j in range(-2, 3) if (gy + i, gx + j) in grid):
                continue
            grid[(gy, gx)] = c
            centres.append(c)
        return radius, centres

    @classmethod
    def _create_scene(cls, height, width, seed=None):
        """ Create the image of the simulated sample: a field of fixed cells on a uniform background (SCENE_BACKGROUND).
        Each cell is an ellipse with a faint cytoplasm and a soft edge, a nucleus slightly off-centre with a
        chromatin-like texture and, in most cells, one to three bright foci. The cells are placed at a fixed density
        (see _cell_centres), so their number grows with the sensor size (about 14 at 512 x 512, 28 at 1024 x 1024,
        88 at 3200 x 3200); their size follows REFERENCE_SIZE, CELL_RADIUS_PX, CELL_SIZE_EXPONENT and CELL_SPACING.
        The random generator uses a fixed seed, so the scene is the same at every start for a given sensor size
        (built once, at activation: ~0.1 s at 1024 x 1024, ~1 s at 3200 x 3200).

        :param: int height, width: size of the sensor
        :param: int seed: seed of the random generator (default SCENE_SEED)
        :return: numpy array (float32) of shape (height, width)
        """
        rng = np.random.default_rng(cls.SCENE_SEED if seed is None else seed)
        scene = np.full((height, width), cls.SCENE_BACKGROUND, dtype=np.float32)
        radius, centres = cls._cell_centres(height, width, rng)

        # chromatin-like texture of the nuclei, computed once on the full frame
        texture = gaussian_filter(rng.normal(size=(height, width)).astype(np.float32), radius * 0.035)
        texture /= texture.std() or 1.

        for (cy, cx) in centres:
            a = radius * rng.uniform(0.8, 1.15)  # semi-axes and orientation of the cell
            b = a * rng.uniform(0.6, 0.9)
            th = rng.uniform(0, np.pi)
            r0, r1 = int(max(cy - a * 1.3, 0)), int(min(cy + a * 1.3, height))
            c0, c1 = int(max(cx - a * 1.3, 0)), int(min(cx + a * 1.3, width))
            yy, xx = np.mgrid[r0:r1, c0:c1].astype(np.float32)
            dy, dx = yy - cy, xx - cx
            u = dx * np.cos(th) + dy * np.sin(th)
            v = -dx * np.sin(th) + dy * np.cos(th)
            rc = np.sqrt((u / a) ** 2 + (v / b) ** 2)
            cyto = 400 / (1 + np.exp((rc - 1) * 12))  # faint cytoplasm, soft edge
            ox, oy = rng.uniform(-0.15, 0.15, 2) * a  # nucleus slightly off-centre
            rn = np.sqrt(((u - ox) / (0.45 * a)) ** 2 + ((v - oy) / (0.40 * a)) ** 2)
            nmask = 1 / (1 + np.exp((rn - 1) * 15))
            patch = cyto + nmask * (1500 + 350 * texture[r0:r1, c0:c1])
            if rng.random() < 0.7:  # one to three bright foci in most nuclei
                spot = 0.05 * radius
                for _ in range(rng.integers(1, 4)):
                    rr, ang = rng.uniform(0, 0.3 * a), rng.uniform(0, 2 * np.pi)
                    sy, sx = cy + oy + rr * np.sin(ang), cx + ox + rr * np.cos(ang)
                    patch += 3500 * np.exp(-((yy - sy) ** 2 + (xx - sx) ** 2) / (2 * spot ** 2))
            scene[r0:r1, c0:c1] += patch
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
# Simulation of andor camera
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
