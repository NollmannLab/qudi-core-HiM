# -*- coding: utf-8 -*-
"""
Qudi-HiM

This file contains the hardware class representing a Hamamatsu ORCA-Flash4.0 camera.
It is built on the official Hamamatsu DCAM-API v4 python bindings (dcamapi4.py / dcam.py, located in the same folder).
The structure and the conventions (return values, image formats, acquisition workflow) follow the Kinetix hardware
module (camera/teledyne/kinetix.py), so that camera_logic can drive both cameras in the same way.

An extension to Qudi.

@author: F. Barho - adapted for qudi-core-HiM by JB Fiche
Modified: 2026-09-20 using Claude code
-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

import numpy as np
from time import sleep, monotonic
from qudi.core.configoption import ConfigOption
from qudi.interface.camera_interface import CameraInterface
from qudi.hardware.camera.hamamatsu.dcam import Dcam, Dcamapi
from qudi.hardware.camera.hamamatsu.dcamapi4 import (DCAM_IDPROP, DCAM_IDSTR, DCAMCAP_STATUS, DCAMERR, DCAMPROP,
                                                      DCAM_PIXELTYPE)

# ======================================================================================================================
# Lookup tables translating the (user-friendly) keywords used in the configuration file into DCAM values
# ======================================================================================================================
# All keywords are normalized before the look-up (upper case, no space, no underscore).
_TRIGGER_SOURCES = {
    'INTERNAL': DCAMPROP.TRIGGERSOURCE.INTERNAL,
    'EXTERNAL': DCAMPROP.TRIGGERSOURCE.EXTERNAL,
    'SOFTWARE': DCAMPROP.TRIGGERSOURCE.SOFTWARE,
    'MASTERPULSE': DCAMPROP.TRIGGERSOURCE.MASTERPULSE,
}

_TRIGGER_ACTIVES = {
    'EDGE': DCAMPROP.TRIGGERACTIVE.EDGE,
    'LEVEL': DCAMPROP.TRIGGERACTIVE.LEVEL,
    'SYNCREADOUT': DCAMPROP.TRIGGERACTIVE.SYNCREADOUT,
    'POINT': DCAMPROP.TRIGGERACTIVE.POINT,
}

_TRIGGER_POLARITIES = {
    'NEGATIVE': DCAMPROP.TRIGGERPOLARITY.NEGATIVE,
    'POSITIVE': DCAMPROP.TRIGGERPOLARITY.POSITIVE,
}

# Kind of signal sent on an output trigger connector. 'EXPOSURE' is kept as an alias of 'GLOBALEXPOSURE' for
# compatibility with the former qudi-HiM configuration.
_OUTPUT_TRIGGER_KINDS = {
    'LOW': DCAMPROP.OUTPUTTRIGGER_KIND.LOW,
    'HIGH': DCAMPROP.OUTPUTTRIGGER_KIND.HIGH,
    'EXPOSURE': DCAMPROP.OUTPUTTRIGGER_KIND.GLOBALEXPOSURE,
    'GLOBALEXPOSURE': DCAMPROP.OUTPUTTRIGGER_KIND.GLOBALEXPOSURE,
    'ANYROWEXPOSURE': DCAMPROP.OUTPUTTRIGGER_KIND.ANYROWEXPOSURE,
    'TRIGGERREADY': DCAMPROP.OUTPUTTRIGGER_KIND.TRIGGERREADY,
    'PROGRAMABLE': DCAMPROP.OUTPUTTRIGGER_KIND.PROGRAMABLE,
    'PROGRAMMABLE': DCAMPROP.OUTPUTTRIGGER_KIND.PROGRAMABLE,
}

# Exposure-out modes, using the same keywords as the Kinetix camera. The ORCA can only signal "all rows exposing" and
# "at least one row exposing".
_EXPOSURE_OUT_MODES = {
    'ALLROWS': 'GLOBALEXPOSURE',  # signal is high only when ALL rows are exposing
    'FIRSTROW': 'ANYROWEXPOSURE',  # signal is high as soon as the first row starts exposing
    'ANYROW': 'ANYROWEXPOSURE',
}

# In DCAM-API, the properties of the Nth output trigger connector are found at (property id + N * offset)
_OUTPUT_TRIGGER_OFFSET = 0x100

# Time (in ms) added to the exposure time when waiting for a single frame. It should cover the readout time of the
# sensor and the time needed by the DCAM driver to transfer the frame.
_SNAP_TIMEOUT_MARGIN_MS = 5000


def _normalize(keyword):
    """ Normalize a keyword (upper case, no space, no underscore) before a look-up in the tables above."""
    return str(keyword).upper().replace(' ', '').replace('_', '')


# ======================================================================================================================
# Class for controlling the ORCA-Flash4.0 camera
# ======================================================================================================================
class HCam(CameraInterface):
    """ Hardware class for Hamamatsu ORCA-Flash4.0 camera

    Example config for copy-paste:

      widefield_camera:
        module.Class: 'camera.hamamatsu.orca_flash4.HCam'
        options:
          camera_name: 'widefield_camera'
          camera_id: 0  # index of the camera in the DCAM-API device list
          temperature_control: False
          gain_control: False
          mechanical_shutter: False
          support_live_acquisition: True
          frame_transfer: False
          default_exposure: 0.05  # in s
          default_trigger_mode: 'INTERNAL'  # 'INTERNAL', 'EXTERNAL', 'SOFTWARE' or 'MASTERPULSE'
          default_exposure_out_mode: 'ALL_ROWS'  # 'ALL_ROWS' or 'FIRST_ROW' (same keywords as the Kinetix camera)
          max_N_images_movie: 1000
          live_buffer_frames: 10  # size (in frames) of the DCAM ring buffer used during live acquisition
          trigger_ready_channel: 1  # output trigger connector (0-based) sending the 'trigger ready' signal
          exposure_out_channel: 2  # output trigger connector (0-based) sending the 'exposure' signal
          output_trigger_polarity: 'NEGATIVE'  # polarity of the two output triggers
    """
    # config options
    _default_exposure = ConfigOption('default_exposure', 0.05)  # in seconds
    camera_id = ConfigOption('camera_id', 0)
    _max_frames_number_video = ConfigOption('max_N_images_movie', missing='error')
    _default_trigger_mode = ConfigOption('default_trigger_mode', 'INTERNAL')
    _default_exposure_out_mode = ConfigOption('default_exposure_out_mode', 'ALL_ROWS')
    _has_temp = ConfigOption('temperature_control', False)
    _has_shutter = ConfigOption('mechanical_shutter', False)
    _has_gain = ConfigOption('gain_control', False)
    _support_live_acquisition = ConfigOption('support_live_acquisition', True)
    _camera_name = ConfigOption('camera_name', missing='error')
    _frame_transfer = ConfigOption('frame_transfer', False)
    _live_buffer_frames = ConfigOption('live_buffer_frames', 10)
    _trigger_ready_channel = ConfigOption('trigger_ready_channel', 1)
    _exposure_out_channel = ConfigOption('exposure_out_channel', 2)
    _output_trigger_polarity = ConfigOption('output_trigger_polarity', 'NEGATIVE')

    # camera attributes
    _camera = None
    _device_name = None  # model and serial number, read from the camera
    _width = 0  # current width
    _height = 0  # current height
    _full_width = 0  # maximum width of the sensor
    _full_height = 0  # maximum height of the sensor
    _exposure = 0.05
    _trigger_mode = 'INTERNAL'
    _exposure_out_mode = 'ALL_ROWS'
    _gain = 0
    _buffer_frames = 0  # number of frames of the DCAM buffer currently allocated (0 = no buffer)
    n_frames = 1

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        self._exposure = self._default_exposure
        self._trigger_mode = 'INTERNAL'
        self._exposure_out_mode = 'ALL_ROWS'
        self._buffer_frames = 0
        self.n_frames = 1

        # Initialize the DCAM-API (a previous initialization by another module is not an error)
        if not Dcamapi.init() and Dcamapi.lasterr() != DCAMERR.ALREADYINITIALIZED:
            error = Dcamapi.lasterr()
            Dcamapi.uninit()
            raise RuntimeError(f"Hamamatsu DCAM-API initialization failed. DCAM error: {error}")

        # Look for the camera
        n_cam = Dcamapi.get_devicecount()
        if not n_cam:
            Dcamapi.uninit()
            raise RuntimeError('No Hamamatsu camera detected - check the camera is switched ON and properly connected, '
                               'and that HCImageLive is closed.')
        if self.camera_id >= n_cam:
            Dcamapi.uninit()
            raise RuntimeError(f'Camera {self.camera_id} was requested but only {n_cam} camera(s) were detected.')
        if n_cam > 1:
            self.log.info(f'{n_cam} cameras were detected - the camera with index {self.camera_id} is used.')

        # Open the connection to the camera
        self._camera = Dcam(self.camera_id)
        if not self._camera.dev_open():
            error = self._camera.lasterr()
            self._camera = None
            Dcamapi.uninit()
            raise RuntimeError(f"Could not open the Hamamatsu camera. DCAM error: {error}")

        # Set the default parameters. Failures are logged by the setters but are not fatal.
        self.get_size()  # update the values _full_width, _full_height of the full sensor when starting the cam
        self._width = self._full_width
        self._height = self._full_height
        self._prop_set(DCAM_IDPROP.IMAGE_PIXELTYPE, DCAM_PIXELTYPE.MONO16, 'Setting the pixel type to 16-bit')
        self._prop_set(DCAM_IDPROP.SUBARRAYMODE, DCAMPROP.MODE.OFF, 'Setting the full-sensor region')
        self.set_exposure(self._exposure)
        self._set_trigger_source(self._default_trigger_mode)  # Set the camera in 'Internal Trigger' mode
        self._set_exposure_out_mode(self._default_exposure_out_mode)  # Set the exposure out mode to the default value

    def on_deactivate(self):
        """ Camera will be deactivated and stopped during execution of this module.
        """
        if self._camera is not None:
            self._free_buffers()
            self._camera.dev_close()
            self._camera = None
        Dcamapi.uninit()

    # ==================================================================================================================
    # Camera Interface functions
    # ==================================================================================================================

    # ------------------------------------------------------------------------------------------------------------------
    # Getter and setter methods
    # ------------------------------------------------------------------------------------------------------------------

    def get_name(self):
        """
        Retrieve an identifier of the camera that the GUI can print.
        @return: string: name for the camera (model and serial number)
        """
        if self._device_name is None:
            model = self._camera.dev_getstring(DCAM_IDSTR.MODEL)
            camera_id = self._camera.dev_getstring(DCAM_IDSTR.CAMERAID)
            if model is False or camera_id is False:
                self._log_dcam_error('Reading the camera model and id')
                return self._camera_name
            self._device_name = f"{model}_{camera_id}"
            self.log.info(f"Camera #{self.camera_id}: MODEL={model}, CAMERAID={camera_id}")
        return self._device_name

    def get_size(self):
        """
        Retrieve size of the FULL sensor in pixel
        @return: (list) full sensor size [width, height]
        """
        width = self._prop_get(DCAM_IDPROP.IMAGEDETECTOR_PIXELNUMHORZ)
        height = self._prop_get(DCAM_IDPROP.IMAGEDETECTOR_PIXELNUMVERT)
        if width is not None and height is not None:
            self._full_width = int(width)
            self._full_height = int(height)
        return [self._full_width, self._full_height]

    def set_exposure(self, exposure):
        """
        Set the exposure time in seconds.
        @param: exposure (float): desired new exposure time in s
        @return: (bool) True when the exposure time has been set, False otherwise.
        """
        new_exposure = self._camera.prop_setgetvalue(DCAM_IDPROP.EXPOSURETIME, exposure)
        if new_exposure is False:
            self._log_dcam_error(f"Setting the exposure to {exposure} s")
            return False
        self._exposure = new_exposure  # the camera returns the value it actually applied
        return True

    def get_exposure(self):
        """
        Get the exposure time in seconds.
        @return: exposure time (float)
        """
        exposure = self._prop_get(DCAM_IDPROP.EXPOSURETIME)
        if exposure is not None:
            self._exposure = exposure
        return self._exposure

    @staticmethod
    def is_cooler_on():
        """
        Get the status of the camera cooler. For the ORCA-Flash4.0, the cooling is always ON.
        @return: (int) 0 = cooler is OFF - 1 = cooler is ON
        """
        return 1

    def get_temperature(self):
        """
        Get the sensor temperature in degrees Celsius.
        @return: temp (float) sensor temperature (None if it could not be read)
        """
        return self._prop_get(DCAM_IDPROP.SENSORTEMPERATURE)

    def set_gain(self, gain):
        """
        Set the gain - gain is not available for the ORCA camera.
        @param: gain: (int) desired new gain
        @return: (bool)
        """
        return False

    def get_gain(self):
        """
        Get the gain
        @return: gain: (int)
        """
        return self._gain

    def get_ready_state(self):
        """
        Is the camera ready for an acquisition ? The camera is busy as long as a capture (live, sequence or snap) is
        running.
        @return: ready ? (bool)
        """
        status = self._camera.cap_status()
        if status is False:  # status could not be read - do not block the logic waiting for the camera
            return True
        return status != DCAMCAP_STATUS.BUSY

    def set_image(self, hbin, vbin, hstart, hend, vstart, vend):
        """
        Sets a ROI on the sensor surface. The ORCA only accepts positions and sizes that are multiples of a given step
        (4 pixels). The ROI is enlarged to the nearest valid values so that it always contains the requested region.
        Binning is not handled yet.
        @param: hbin: (int) number of pixels to bin horizontally (not used)
        @param: vbin: (int) number of pixels to bin vertically (not used)
        @param: hstart: (int) Start column (first column of the sensor = 1)
        @param: hend: (int) End column (inclusive)
        @param: vstart: (int) Start row (first row of the sensor = 1)
        @param: vend: (int) End row (inclusive)
        @return: (bool) return True if the ROI was set, False if an error was detected
        """
        try:
            if hbin != 1 or vbin != 1:
                self.log.warning('Binning is not handled by the ORCA hardware module yet - binning is ignored.')

            # the ROI cannot be changed while the camera is capturing or a buffer is allocated
            self._free_buffers()

            hpos, hsize = self._align_roi(DCAM_IDPROP.SUBARRAYHPOS, DCAM_IDPROP.SUBARRAYHSIZE,
                                          int(hstart) - 1, int(hend) - int(hstart) + 1, self._full_width)
            vpos, vsize = self._align_roi(DCAM_IDPROP.SUBARRAYVPOS, DCAM_IDPROP.SUBARRAYVSIZE,
                                          int(vstart) - 1, int(vend) - int(vstart) + 1, self._full_height)

            ok = self._prop_set(DCAM_IDPROP.SUBARRAYMODE, DCAMPROP.MODE.OFF, 'Deactivating the sub-array mode')
            if (hpos, hsize, vpos, vsize) != (0, self._full_width, 0, self._full_height):
                ok = ok and self._prop_set(DCAM_IDPROP.SUBARRAYHPOS, hpos, 'Setting the ROI horizontal position')
                ok = ok and self._prop_set(DCAM_IDPROP.SUBARRAYHSIZE, hsize, 'Setting the ROI width')
                ok = ok and self._prop_set(DCAM_IDPROP.SUBARRAYVPOS, vpos, 'Setting the ROI vertical position')
                ok = ok and self._prop_set(DCAM_IDPROP.SUBARRAYVSIZE, vsize, 'Setting the ROI height')
                ok = ok and self._prop_set(DCAM_IDPROP.SUBARRAYMODE, DCAMPROP.MODE.ON, 'Activating the sub-array mode')
            if not ok:
                return False

            self._width = hsize
            self._height = vsize
            self.log.info(f'Set subarray: {vsize} x {hsize} pixels (rows x cols)')
            return True
        except Exception as e:
            self.log.error(f"The following error was encountered in set_image : {e}")
            return False

    def get_image_size(self):
        """
        Get the size of the image (after setting an ROI for example)
        @return: (tuple) height and width of the image
        """
        height = self._prop_get(DCAM_IDPROP.IMAGE_HEIGHT)
        width = self._prop_get(DCAM_IDPROP.IMAGE_WIDTH)
        if height is None or width is None:
            return self._height, self._width
        return int(height), int(width)

    def get_progress(self):
        """
        Retrieves the total number of images acquired since the beginning of the current acquisition.
        @return: (int) number of acquired images
        """
        info = self._camera.cap_transferinfo()
        if info is False:
            return 0
        return int(info.nFrameCount)

    def get_max_frames(self):
        """ Return the maximum number of frames that can be handled by the camera for a single movie acquisition.
        Depending on the camera, multiple acquisition modes can be handled. A dictionary is used as output.
        @return:
            max_frames_dict (dict)
        """
        max_frames_dict = {'video': self._max_frames_number_video}
        return max_frames_dict

    # ------------------------------------------------------------------------------------------------------------------
    # Methods to query the camera properties
    # ------------------------------------------------------------------------------------------------------------------

    def support_live_acquisition(self):
        """ Return whether the camera handle live acquisition.
        @return: (bool) True if supported, False if not
        """
        return self._support_live_acquisition

    def has_temp(self):
        """
        Does the camera support setting of the temperature?
        @return: (bool): has temperature ?
        """
        return self._has_temp

    def has_shutter(self):
        """
        Is the camera equipped with a mechanical shutter?
        @return: (bool): has shutter ?
        """
        return self._has_shutter

    def has_gain(self):
        """
        Is the camera enabling electronic gain control?
        @return: (bool): has gain ?
        """
        return self._has_gain

    def support_frame_transfer(self):
        """ Is frame transfer mode allowed?
        @return: (bool) frame transfer possible?
        """
        return self._frame_transfer

    # ------------------------------------------------------------------------------------------------------------------
    # Methods to handle camera acquisitions
    # ------------------------------------------------------------------------------------------------------------------

    # Methods for displaying images on the GUI -----------------------------------------------------------------------
    def start_single_acquisition(self):
        """
        Start acquisition for a single frame (snap mode) and return the acquired frame
        @return: frame (numpy array): acquired frame (None if the acquisition failed)
        """
        return self._start_acquisition(mode='Single image')

    def start_live_acquisition(self):
        """
        Start a continuous acquisition.
        @return: Success ? (bool)
        """
        return self._start_acquisition(mode='Live')

    def stop_acquisition(self):
        """
        Stop/abort live or single acquisition and release the DCAM buffer.
        @return: bool: Success ?
        """
        try:
            self._free_buffers()
            return True
        except Exception as e:
            self.log.error(f"The following error was encountered in stop_acquisition : {e}")
            return False

    # Methods for saving image data ----------------------------------------------------------------------------------
    def start_movie_acquisition(self, n_frames):
        """
        Set the conditions to save a movie and start the acquisition (fixed length mode).

        @param: (int) n_frames: number of frames
        @return: bool: True if the acquisition started, False if an error was detected
        """
        self.n_frames = int(n_frames)  # needed to choose the correct number of frames in get_acquired_data method
        return self._start_acquisition(mode='Sequence')

    def finish_movie_acquisition(self):
        """
        Reset the conditions used to save a movie to default.
        @return: bool: Success ?
        """
        try:
            self._free_buffers()
            self.n_frames = 1  # reset to default
            return True
        except Exception as e:
            self.log.error(e)
            return False

    def abort_movie_acquisition(self):
        """ Abort an acquisition.
        """
        self._abort_acquisition()
        self.n_frames = 1

    def wait_until_finished(self, timeout=None):
        """ Wait until an acquisition is finished.
        @param: (float) timeout: maximum waiting time in s (default : the time needed to acquire n_frames + 10 s)
        """
        if timeout is None:
            timeout = self.n_frames * (self._exposure + 0.1) + 10
        start = monotonic()
        while not self.get_ready_state():
            if monotonic() - start > timeout:
                self.log.warning(f'The camera is still acquiring after {timeout:.1f} s.')
                return
            sleep(0.01)

    # Methods for acquiring image data using synchronization between lightsource and camera --------------------------
    def prepare_camera_for_multichannel_imaging(self, frames, exposure, gain, save_path, file_format):
        """ Set the camera state for an experiment using synchronization between lightsources and the camera. Using
        typically an external trigger. Each trigger pulse starts the exposure of one frame. The camera is not started
        here - the acquisition is launched afterwards (see camera_logic.start_acquisition).

        @param: int frames: number of frames in a kinetic series / fixed length mode
        @param: float exposure: exposure time in seconds

        The following parameters are not needed for this camera. Only for compatibility with abstract function signature
        @param: int gain: gain setting
        @param: str save_path: complete path (without fileformat suffix) where the image data will be saved
        @param: str file_format: selected fileformat such as 'tiff', 'fits', ..
        """
        self.stop_acquisition()
        self.set_exposure(exposure)
        self.n_frames = int(frames)

        # external trigger: one exposure for each rising edge
        self._set_trigger_source('EXTERNAL')
        self._set_trigger_active('EDGE')
        self._set_trigger_polarity('POSITIVE')

        # output triggers : 'trigger ready' and exposure signal
        self._configure_output_trigger(self._trigger_ready_channel, 'TRIGGERREADY', self._output_trigger_polarity)
        self._set_exposure_out_mode(self._exposure_out_mode)

    def reset_camera_after_multichannel_imaging(self):
        """
        Reset the camera to a default state after an experiment using synchronization between lightsources and the
        camera.
        """
        self.stop_acquisition()
        self._set_trigger_source('INTERNAL')
        self.n_frames = 1  # reset to default

    # ------------------------------------------------------------------------------------------------------------------
    # Methods for image data retrieval
    # ------------------------------------------------------------------------------------------------------------------

    def get_most_recent_image(self, copy=True):
        """
        Return the last acquired image and the total number of acquired images. Used mainly for live display on gui
        during video saving. Note that DCAM always returns a copy of the frame, the argument "copy" is only kept for
        compatibility with the Kinetix camera.

        @param: (bool) copy : not used
        @return:
        frame (numpy array): latest acquired frame (None if no frame is available yet)
        frame_count (int): number of acquired frames
        """
        try:
            info = self._camera.cap_transferinfo()
            if info is False or info.nFrameCount == 0:
                return None, 0
            frame = self._camera.buf_getframedata(-1)  # -1 = most recent frame
            if frame is False:
                self._log_dcam_error('Reading the most recent frame')
                return None, 0
            return frame, int(info.nFrameCount)
        except Exception as e:
            self.log.error(f"The following error was encountered in get_most_recent_image : {e}")
            return None, 0

    def get_acquired_data(self):
        """
        Return an array of the acquired data. This function is only used at the end of a sequence acquisition (not for
        live mode) and for the tasks. It returns all the n_frames images of the sequence. If the acquisition is not
        finished or if some frames are missing, the function returns None.

        @return: (numpy ndarray) im_seq : data in format [n_frames, height, width]
        """
        if self._buffer_frames == 0:
            self.log.error('No acquisition was started - no data available.')
            return None

        if not self.get_ready_state():
            self.log.error('Acquisition is still in process. Data are not accessible and cannot be saved.')
            return None

        info = self._camera.cap_transferinfo()
        if info is False:
            self._log_dcam_error('Reading the transfer information')
            return None
        if min(info.nFrameCount, self._buffer_frames) < self.n_frames:
            self.log.error(f'Only {info.nFrameCount} frames out of {self.n_frames} were acquired.')
            return None

        self.log.info(f'Loading {self.n_frames} frames ...')
        im_seq = None
        for frame in range(self.n_frames):
            data = self._camera.buf_getframedata(frame)
            if data is False:
                self._log_dcam_error(f'Reading frame {frame}')
                return None
            if im_seq is None:  # preallocate the full stack once the frame size is known
                im_seq = np.empty((self.n_frames,) + data.shape, dtype=data.dtype)
            im_seq[frame] = data
        return im_seq

    # ==================================================================================================================
    # Non-Interface functions
    # ==================================================================================================================

    # ------------------------------------------------------------------------------------------------------------------
    # Non-interface functions to handle acquisitions
    # ------------------------------------------------------------------------------------------------------------------
    def _start_acquisition(self, mode='Live'):
        """
        Launch an acquisition according to the indicated mode. The DCAM buffer is (re)allocated each time so that the
        ROI, the number of frames and the trigger settings can be freely modified between two acquisitions.
        @param mode: (str) 'Live' (continuous acquisition in a ring buffer), 'Sequence' (n_frames images) or
                     'Single image' (one image)
        @return: - 'Live' and 'Sequence' : (bool) True if the acquisition started
                 - 'Single image' : frame (numpy array) - None if the acquisition failed
        """
        if mode == 'Live':
            return self._start_capture(int(self._live_buffer_frames), continuous=True)
        elif mode == 'Sequence':
            return self._start_capture(self.n_frames, continuous=False)
        elif mode == 'Single image':
            return self._snap()
        else:
            self.log.warning("The mode requested does not exist - Acquisition will not start")
            return False

    def _start_capture(self, n_frames, continuous):
        """ Allocate a buffer of n_frames and start the capture.
        @param: (int) n_frames: size of the buffer. For a sequence, it is also the number of images acquired.
        @param: (bool) continuous: True = the buffer is used as a ring buffer until the capture is stopped (live),
                                   False = the capture stops when the buffer is full (sequence, snap)
        @return: (bool) True if the capture started
        """
        self._free_buffers()
        if not self._camera.buf_alloc(n_frames):
            self._log_dcam_error(f"Allocating a buffer of {n_frames} frames (the number of images might be too large "
                                 f"for the memory - try using a smaller ROI)")
            return False
        self._buffer_frames = n_frames
        if not self._camera.cap_start(bSequence=continuous):
            self._log_dcam_error('Starting the capture')
            self._free_buffers()
            return False
        return True

    def _snap(self):
        """ Acquire one image and return it.
        @return: frame (numpy array) - None if the acquisition failed
        """
        if not self._start_capture(1, continuous=False):
            return None
        timeout_ms = int(self._exposure * 1000) + _SNAP_TIMEOUT_MARGIN_MS
        if not self._camera.wait_capevent_frameready(timeout_ms):
            self._log_dcam_error('Waiting for the frame')
            self._free_buffers()
            return None
        frame = self._camera.buf_getframedata(0)
        if frame is False:
            self._log_dcam_error('Reading the frame')
            return None
        return frame

    def _abort_acquisition(self):
        """ Abort an acquisition prior completion.
        """
        try:
            self._free_buffers()
        except Exception as e:
            self.log.error(f"Error in _abort_acquisition : {e}")

    def _free_buffers(self):
        """ Stop the capture (if any) and release the DCAM buffer. It is safe to call this function at any time. Errors
        returned by DCAM (e.g. 'not busy') when nothing has to be stopped or released are expected and ignored.
        """
        if self._camera is None or not self._camera.is_opened():
            return
        self._camera.cap_stop()
        self._camera.buf_release()
        self._buffer_frames = 0

    def _align_roi(self, pos_prop, size_prop, start, size, full_size):
        """ Enlarge a (start, size) range along one axis to the nearest values accepted by the camera.
        @param: pos_prop, size_prop: DCAM properties of the position and of the size along the axis
        @param: (int) start: first pixel (0-based)
        @param: (int) size: number of pixels
        @param: (int) full_size: size of the sensor along the axis
        @return: (int, int) position and size accepted by the camera
        """
        pos_step = self._get_step(pos_prop)
        size_step = self._get_step(size_prop)
        start = max(0, min(start, full_size - size_step))
        end = min(start + max(size, 1), full_size)
        pos = (start // pos_step) * pos_step  # round the start down ...
        size = -(-(end - pos) // size_step) * size_step  # ... and the size up to a valid value
        size = min(size, full_size - pos)
        if (pos, size) != (start, end - start):
            self.log.info(f'ROI adapted to the camera constraints : position {start} -> {pos}, size {end - start} -> '
                          f'{size}')
        return pos, size

    def _get_step(self, prop):
        """ Get the increment step of a property (4 pixels for the ROI properties of the ORCA-Flash4.0 by default)."""
        attr = self._camera.prop_getattr(prop)
        if attr is False or attr.valuestep < 1:
            return 4
        return int(attr.valuestep)

    # ------------------------------------------------------------------------------------------------------------------
    # Trigger
    # ------------------------------------------------------------------------------------------------------------------
    def _set_exposure_out_mode(self, source):
        """
        Set the exposure out mode, i.e. the kind of signal sent on the exposure output trigger connector. The same
        keywords as for the Kinetix camera are used:
        'ALL_ROWS': the signal is high only when all the rows of the sensor are exposing - this makes sure the signal
                    is not sent before the end of the previous image acquisition,
        'FIRST_ROW': the signal is high as soon as the first row starts to expose.
        @param string source: 'ALL_ROWS' or 'FIRST_ROW'
        @return bool: True when the operation was completed with success
        """
        mode = _EXPOSURE_OUT_MODES.get(_normalize(source))
        if mode is None:
            self.log.warning(f'The exposure out mode {source} is not available for this camera.')
            return False
        self._exposure_out_mode = source
        return self._configure_output_trigger(self._exposure_out_channel, mode, self._output_trigger_polarity)

    def _set_trigger_source(self, source):
        """
        Set the trigger source. Four modes are available for this camera :
        'INTERNAL': the camera exposes continuously, 'EXTERNAL': the exposure is started by the signal received on the
        trigger input, 'SOFTWARE': the exposure is started by the software, 'MASTERPULSE'.

        @param string source: 'INTERNAL', 'EXTERNAL', 'SOFTWARE', 'MASTERPULSE'
        @return bool: True when the operation was completed with success - False otherwise
        """
        requested = _TRIGGER_SOURCES.get(_normalize(source))
        if requested is None:
            self.log.error(f"The requested trigger source {source} is not available.")
            return False

        # the trigger source cannot be modified while a capture is running
        self._free_buffers()
        value = self._camera.prop_setgetvalue(DCAM_IDPROP.TRIGGERSOURCE, float(requested))
        if value is False:
            self._log_dcam_error(f"Setting the trigger source to {source}")
            return False
        if int(value) != int(requested):
            self.log.warning(f"The trigger source returned by the camera is not the one requested ({source}).")
            return False
        self._trigger_mode = _normalize(source)
        return True

    def _get_trigger_source(self):
        """
        Return the trigger source currently used for the camera
        @return: trigger_source (str): 'INTERNAL', 'EXTERNAL', 'SOFTWARE' or 'MASTERPULSE' (None if unknown)
        """
        value = self._prop_get(DCAM_IDPROP.TRIGGERSOURCE)
        if value is None:
            return None
        return self._name_from_value(_TRIGGER_SOURCES, value)

    def _set_trigger_active(self, active):
        """ Set the trigger active mode (how the trigger signal starts the exposure).
        @param: str active: 'EDGE' (an exposure is started on each trigger edge), 'LEVEL', 'SYNCREADOUT', 'POINT'
        @return: bool: True when the operation was completed with success
        """
        requested = _TRIGGER_ACTIVES.get(_normalize(active))
        if requested is None:
            self.log.error(f"The requested trigger active mode {active} is not available.")
            return False
        return self._prop_set(DCAM_IDPROP.TRIGGERACTIVE, requested, f"Setting the trigger active mode to {active}")

    def _set_trigger_polarity(self, polarity):
        """ Set the trigger polarity (default is negative)
        @param: str polarity: 'NEGATIVE', 'POSITIVE'
        @return: bool: True when the operation was completed with success
        """
        requested = _TRIGGER_POLARITIES.get(_normalize(polarity))
        if requested is None:
            self.log.error(f"The requested trigger polarity {polarity} is not available.")
            return False
        return self._prop_set(DCAM_IDPROP.TRIGGERPOLARITY, requested, f"Setting the trigger polarity to {polarity}")

    def _get_trigger_polarity(self):
        """
        Return the trigger polarity currently used for the camera
        @return: (str) 'NEGATIVE' or 'POSITIVE' (None if unknown)
        """
        value = self._prop_get(DCAM_IDPROP.TRIGGERPOLARITY)
        if value is None:
            return None
        return self._name_from_value(_TRIGGER_POLARITIES, value)

    def _configure_output_trigger(self, channel, output_trigger_kind, output_trigger_polarity):
        """
        Configure the output trigger for the specified output channel
        @param: int channel: index (0-based) ranging up to the number of output trigger connectors - 1
        @param: str output_trigger_kind: supported values 'LOW', 'HIGH', 'GLOBALEXPOSURE' (or 'EXPOSURE'),
                'ANYROWEXPOSURE', 'TRIGGERREADY', 'PROGRAMABLE'
        @param: str output_trigger_polarity: supported values 'NEGATIVE', 'POSITIVE'
        @return: bool: True when the operation was completed with success
        """
        kind = _OUTPUT_TRIGGER_KINDS.get(_normalize(output_trigger_kind))
        polarity = _TRIGGER_POLARITIES.get(_normalize(output_trigger_polarity))
        if kind is None or polarity is None:
            self.log.error(f"Output trigger configuration ({output_trigger_kind}, {output_trigger_polarity}) is not "
                           f"available.")
            return False

        n_connectors = self._prop_get(DCAM_IDPROP.NUMBEROF_OUTPUTTRIGGERCONNECTOR)
        if n_connectors is not None and not 0 <= channel < n_connectors:
            self.log.error(f"Output trigger channel {channel} does not exist (the camera has {int(n_connectors)} "
                           f"connectors, numbered from 0).")
            return False

        offset = channel * _OUTPUT_TRIGGER_OFFSET
        ok = self._prop_set(DCAM_IDPROP.OUTPUTTRIGGER_KIND + offset, kind,
                            f"Setting the kind of output trigger {channel} to {output_trigger_kind}")
        ok = ok and self._prop_set(DCAM_IDPROP.OUTPUTTRIGGER_POLARITY + offset, polarity,
                                   f"Setting the polarity of output trigger {channel} to {output_trigger_polarity}")
        return ok

    # ------------------------------------------------------------------------------------------------------------------
    # Helpers for the DCAM properties and error handling
    # ------------------------------------------------------------------------------------------------------------------
    def _prop_get(self, prop):
        """ Read a DCAM property.
        @return: (float) value of the property - None if it could not be read
        """
        value = self._camera.prop_getvalue(prop)
        if value is False:
            self._log_dcam_error(f"Reading the property {prop}")
            return None
        return value

    def _prop_set(self, prop, value, operation):
        """ Set a DCAM property.
        @param: prop: DCAM property id
        @param: value: value to set
        @param: (str) operation: description of the operation, used in the error message
        @return: (bool) True when the value was set
        """
        if self._camera.prop_setvalue(prop, float(value)) is False:
            self._log_dcam_error(operation)
            return False
        return True

    @staticmethod
    def _name_from_value(table, value):
        """ Reverse look-up of a keyword table."""
        for name, item in table.items():
            if int(item) == int(value):
                return name
        return None

    def _log_dcam_error(self, operation):
        """Log the latest DCAM API error."""
        error = self._camera.lasterr()
        self.log.error(f"{operation} failed. DCAM error: {error}")
