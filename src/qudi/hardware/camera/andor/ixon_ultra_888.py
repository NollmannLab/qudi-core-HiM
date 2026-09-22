# -*- coding: utf-8 -*-
"""
Qudi-CBS

This file contains the hardware class representing an andor iXon Ultra camera.

This module was first created by F.Barho for the Ixon-897 and then adapted for the 888-ultra. Note that all error codes
can be found here: "C:\Program Files\andor SDK\Python\pyAndorSDK2\pyAndorSDK2\atmcd_errors.py", together with examples.

@author: JB. Fiche (original code from F. Barho)
Created on Wed Nov 27 2024
Last modified 2026-09-22: adapt hardware to qudi-core - make sure the code follows the format defined
  from the Interface and used for other cameras. In particular make sure that error handling
  follows the same rule everywhere : return True when success (Modified with Claude code)
-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""
import numpy as np
# from enum import Enum
# from ctypes import *
from pyAndorSDK2 import atmcd
from pyAndorSDK2.atmcd_errors import Error_Codes
from pyAndorSDK2.atmcd_codes import Read_Mode, Trigger_Mode, Acquisition_Mode
from time import sleep
from qudi.core.configoption import ConfigOption
from qudi.interface.camera_interface import CameraInterface

verbose = True

# ======================================================================================================================
# Decorator (for debugging)
# ======================================================================================================================
def decorator_print_function(function):
    global verbose

    def new_function(*args, **kwargs):
        if verbose:
            print(f'*** DEBUGGING *** Executing {function.__name__}')
        return function(*args, **kwargs)

    return new_function


# ======================================================================================================================
# Hardware class
# ======================================================================================================================
class IxonUltra(CameraInterface):
    """ Hardware class for andor Ixon Ultra 897. Example config for copy-paste:

    andor_ultra_camera:
        module.Class: 'camera.andor.iXon888_ultra.IxonUltra'
        sdk_location: 'C:\Program Files\andor SDK\Python\pyAndorSDK2'
        default_exposure: 0.05  # en s
        default_read_mode: 'FULLIMAGE'
        default_temperature: -60
        default_cooler_on: True
        default_acquisition_mode: 'KINETIC'
        default_trigger_mode: 'INTERNAL'
    """
    # config options
    _sdk_location = ConfigOption('sdk_location', missing='error')
    _default_exposure = ConfigOption('default_exposure', 0.05)  # default exposure value 0.1 s
    _default_read_mode = ConfigOption('default_read_mode', 'IMAGE')
    _default_temperature = ConfigOption('default_temperature', -60)
    _default_cooler_on = ConfigOption('default_cooler_on', True)
    _default_acquisition_mode = ConfigOption('default_acquisition_mode', 'KINETICS')
    _default_trigger_mode = ConfigOption('default_trigger_mode', 'INTERNAL')
    _max_frames_number_video = ConfigOption('max_N_images_movie', missing='error')
    _max_frames_number_spool = ConfigOption('max_N_images_spool', missing='error')
    _has_temp = ConfigOption('temperature_control', False)
    _has_shutter = ConfigOption('mechanical_shutter', False)
    _has_gain = ConfigOption('gain_control', False)
    _support_live_acquisition = ConfigOption('support_live_acquisition', False)
    _camera_name = ConfigOption('camera_name', missing='error')
    _frame_transfer = ConfigOption('frame_transfer', missing='error')

    # camera attributes
    _sdk = None
    _exposure = _default_exposure
    _temperature = _default_temperature
    _cooler_on = _default_cooler_on
    _read_mode = _default_read_mode
    _acquisition_mode = _default_acquisition_mode
    _trigger_mode = _default_trigger_mode

    _preamp_gain = None
    _vertical_shift_speed = None
    _vertical_clock = None
    _output_amplifier = None
    _set_horizontal_readout_rate = None

    _gain = 0
    _width = 0
    _height = 0
    _full_width = 0  # store this for default sensor size
    _full_height = 0  # for default sensor size
    # _last_acquisition_mode = None  # useful if config changes during acquisition
    _max_cooling = -80
    _shutter = "Closed"

    _live = False
    _acquiring = False
    _scans = 1
    _cur_image = None
    _available = False  # True only once on_activate has fully succeeded - see is_available()

    def on_activate(self):
        """ Initialisation performed during activation of the module. Note that for the moment, only one camera is
        handled by the setup. If anything fails here, the error is logged and the module is left inactive
        (is_available() returns False) instead of raising, so that a camera that cannot be initialized does not bring
        down the interfuse, the logic and the GUI that depend on it (see camera_interface.is_available).
        """
        self._available = False

        try:
            self._sdk = atmcd("")  # Load the atmcd library
            ret = self._sdk.Initialize(self._sdk_location)  # Initialize camera
        except Exception as e:
            self.log.error(f'andor iXon Ultra 888 Camera: could not load the SDK or initialise the camera: {e}.')
            return

        # note: comparing "Error_Codes.DRV_SUCCESS == ret" directly (as this used to do) never matches, since ret is
        # the plain integer value returned by the SDK, not an Error_Codes member - use check_error/get_key_from_value
        # like everywhere else in this module, which compares by .value and also logs the error code.
        if self.check_error(ret, 'Initialize'):
            return

        err, serial = self._get_camera_serialnumber()
        if not err:
            self.log.info(f'andor iXon Ultra 888 Camera: connected to camera with serial number {serial}.')

        try:
            # open the external shutter
            err = self._set_shutter(1, 1, 100, 100, 1)
            if not err:
                self._shutter = "Open"

            # below are the default parameters that can also be accessed through the GUI
            self._width, self._height = self._get_detector()
            self._full_width, self._full_height = self._width, self._height
            self._set_read_mode(self._read_mode)
            self._set_trigger_mode(self._trigger_mode)
            self._set_exposuretime(self._exposure)
            self._set_acquisition_mode(self._acquisition_mode)
            self._set_cooler(self._cooler_on)
            self._set_temperature(self._default_temperature)

            # the following parameters will define a default configuration of the camera. Those parameters are not
            # accessible through the GUI. They have been copied from SOLIS default configuration.
            self._set_preamp_gain(1)
            self._set_vertical_shift_speed(1)
            self._set_vertical_clock(0)
            self._set_output_amplifier(0)
            self._set_horizontal_readout_rate(0)
        except Exception as e:
            self.log.error(f'andor iXon Ultra 888 Camera: error while configuring the camera: {e}.')
            return

        self._available = True

    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module. Guarded so that it does not fail if
        on_activate did not complete (self._available stayed False).
        """
        if not self._available:
            return
        self.stop_acquisition()
        # self._set_shutter(1, 2, 100, 100, 2)  # Leave the shutter ON
        self._set_cooler(False)
        self._shut_down()
        self._available = False

    def is_available(self):
        """ Whether the camera was successfully initialized during on_activate (see camera_interface.py).
        @return: (bool) True if the camera is available
        """
        return self._available

    # ======================================================================================================================
    # Camera Interface functions
    # ======================================================================================================================

    # ----------------------------------------------------------------------------------------------------------------------
    # Methods for handling error message
    # ----------------------------------------------------------------------------------------------------------------------

    @staticmethod
    def get_key_from_value(value):
        for error in Error_Codes:
            if error.value == value:
                return error.name
        return None  # Return None if value is not found

    def check_error(self, ret, func, pass_returns=['DRV_SUCCESS']):
        """
        Error handling function returning an error message if drv_success not working
        @return : return False if no error and True if an error was detected
        """
        if self.get_key_from_value(ret) not in pass_returns:
            error_code = self.get_key_from_value(ret)
            self.log.error(f'The command issued by {func} returned the following error message : {error_code}')
            return True
        else:
            return False

    # ----------------------------------------------------------------------------------------------------------------------
    # Getter and setter methods
    # ----------------------------------------------------------------------------------------------------------------------
    def get_name(self):
        """
        Retrieve an identifier of the camera that the GUI can print.
        @return: (str) name for the camera
        """
        return self._camera_name

    def get_size(self):
        """
        Retrieve the size of the FULL sensor in pixel, regardless of any ROI that was set (see camera_interface.py).
        @return: (tuple (int, int))  Size (width, height)
        """
        return self._full_width, self._full_height

    def get_image_size(self):
        """
        Retrieve the size of the current image, i.e. after a ROI was set (see camera_interface.py).
        @return: (tuple (int, int)) Size (height, width)
        """
        return self._height, self._width

    def set_exposure(self, exposure):
        """ Set the exposure time in seconds.
        @param: (float) exposure: desired new exposure time
        @return: (bool) True on success
        """
        err = self._set_exposuretime(exposure)
        if err:
            return False
        self._exposure = exposure
        return True

    def get_exposure(self):
        """ Get the exposure time in seconds.
        @return: (float) exposure time
        """
        self._get_acquisition_timings()
        return self._exposure

    def set_gain(self, gain):
        """ Set the electron multiplying gain.
        @param: (int) gain: desired new gain.
        @return (bool): True on success
        """
        err = self._set_emccd_gain(gain)
        if err:
            return False
        self._gain = gain
        return True

    def get_gain(self):
        """ Get the electron multiplying gain
        @return (int): em gain """
        self._gain = self._get_emccd_gain()
        return self._gain

    def get_gain_limits(self):
        """ Get the electron multiplying gain limits
        @return: (int) return the low and high limits
        """
        return self._get_em_gain_range()

    def get_ready_state(self):
        """ Is the camera ready for an acquisition ?
        @return: (bool) ready ?
        """
        status = self._get_status()
        if status == 'DRV_IDLE':
            return True
        else:
            return False

    def set_image(self, hbin, vbin, hstart, hend, vstart, vend):
        """  Sets a ROI on the sensor surface. We don't use the binning parameters but they are needed in the function
        call to be conform with syntax of andor camera.
        @param: (int) hbin: number of pixels to bin horizontally
        @param: (int) vbin: number of pixels to bin vertically.
        @param: (int) hstart: Start column (inclusive)
        @param: (int) hend: End column (inclusive)
        @param: (int) vstart: Start row (inclusive)
        @param: (int) vend: End row (inclusive).
        @return: (bool) True on success
        """
        err = self._set_image(hbin, vbin, hstart, hend, vstart, vend)
        return not err

    def get_progress(self):
        """ Retrieves the total number of acquired images during a movie acquisition.
        @return: (int) progress: total number of acquired images.
        """
        ret, index = self._sdk.GetTotalNumberImagesAcquired()
        err = self.check_error(ret, "get_progress")
        if err:
            return
        else:
            return index

    def get_max_frames(self):
        """ Return the maximum number of frames that can be handled by the camera for a single movie acquisition. Two
        values are returned, depending on which methods is used for the acquisition (video or spooling)
        @return:
            max frames video mode (int)
            max frames spool mode (int)
        """
        max_frames_dict = {'video': self._max_frames_number_video,
                           'spool': self._max_frames_number_spool}
        return max_frames_dict

    def set_spool(self, active, method, path, buffer):
        """ Set the spool mode for the camera
        @return: error (bool)
        """
        err = self._set_spool(active, method, path, buffer)
        return err

    # ----------------------------------------------------------------------------------------------------------------------
    # Methods to query the camera properties
    # ----------------------------------------------------------------------------------------------------------------------

    def support_live_acquisition(self):
        """ Return whether or not the camera can take care of live acquisition.
        @return: bool: True if supported, False if not
        """
        return self._support_live_acquisition

    def has_temp(self):
        """ Does the camera support setting of the temperature?
        @return: bool: has temperature ?
        """
        return self._has_temp

    def has_shutter(self):
        """ Is the camera equipped with a mechanical shutter?
        If this function returns true, the attribute _shutter must also be defined in the hardware module
        @return: (bool) has shutter ?
        """
        return self._has_shutter

    def has_gain(self):
        """ Is the camera allowing gain control?
        If this function returns true, the attribute _has_gain must also be defined in the hardware module
        @return: (bool) has gain ?
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

    # Methods for displaying images on the GUI -------------------------------------------------------------------------
    def start_single_acquisition(self):
        """ Start a single acquisition and block until it is finished (see camera_interface.py).
        @return: (numpy.ndarray | None) the acquired 2D frame, or None if the camera is busy with a live
        acquisition, or if the acquisition could not be started or the frame could not be retrieved.
        """
        # if self._shutter == 'Closed':
        #     err = self._set_shutter(1, 0, 100, 100, 1)
        #     if not err:
        #         self._shutter = 'Open'
        #     else:
        #         self.log.error('Shutter did not open in start_single_acquisition.')

        if self._live:
            self.log.warning('start_single_acquisition: a live acquisition is already running.')
            return None

        # self._acquiring = True  # do we need this here?
        self._set_acquisition_mode('SINGLE_SCAN')
        err = self._start_acquisition()
        if err:
            self.log.error('start_single_acquisition: the acquisition could not be started.')
            return None
        return self.get_acquired_data()

    def start_live_acquisition(self):
        """ Start a continuous acquisition.
        @return: (bool) True on success
        """
        # handle the variables indicating the status
        if self.support_live_acquisition():
            self._live = True
            self._acquiring = False

        # # make sure shutter is opened
        # if self._shutter == 'Closed':
        #     err = self._set_shutter(1, 1, 100, 100, 1)
        #     if not err:
        #         self._shutter = 'Open'
        #     else:
        #         self.log.error(f'Shutter did not open!')

        self._set_acquisition_mode('RUN_TILL_ABORT')
        err = self._start_acquisition()
        if err:
            self._live = False
            return False
        return True

    def stop_acquisition(self):
        """ Stop/abort live or single acquisition
        @return: (bool) Success ?
        """
        err = self._abort_acquisition()
        self._set_acquisition_mode(self._default_acquisition_mode)  # reset to default (run till abort typically)
        if not err:
            self._live = False
            self._acquiring = False
            # self._set_shutter(1, 0, 100, 100, 2)
            # self._shutter == 'Closed'
            return True
        else:
            return False

    # Methods for saving image data ------------------------------------------------------------------------------------
    def start_movie_acquisition(self, n_frames):
        """ Set the conditions to save a movie and start the acquisition (typically kinetic / fixed length mode).
        @param: (int) n_frames: number of frames
        @return: (bool) True on success
        """
        # handle the variables indicating the status
        if self.support_live_acquisition():
            self._live = True
            self._acquiring = False

        # # make sure shutter is opened
        # if self._shutter == 'Closed':
        #     msg = self._set_shutter(1, 1, 100, 100, 1)
        #     if msg == 'DRV_SUCCESS':
        #         self._shutter = 'Open'
        #     else:
        #         self.log.error('shutter did non open. {}'.format(msg))

        self._set_acquisition_mode('KINETICS')
        self.set_exposure(
            self._exposure)  # make sure this is taken into account, call it after acquisition mode setting
        self._set_number_kinetics(n_frames)
        self._scans = n_frames  # set this attribute to get the right dimension for get_acquired_data method
        err = self._start_acquisition()
        if err:
            self._live = False
            return False
        return True

    def abort_movie_acquisition(self):
        """ Abort an acquisition.
        @return: (bool) True on success
        """
        err = self._abort_acquisition()
        self._set_acquisition_mode(self._default_acquisition_mode)
        self._scans = 1
        self._live = False
        self._acquiring = False
        return not err

    def finish_movie_acquisition(self):
        """ Reset the conditions used to save a movie to default.
        @return: (bool) Success ?
        """
        # no abort_acquisition needed because acquisition finishes when the number of frames is reached
        self._set_acquisition_mode(self._default_acquisition_mode)  # reset to default (run till abort typically)
        self._scans = 1  # reset to default number of scans. Important for the other acquisition modes to run correctly
        self._live = False
        self._acquiring = False
        return True
        # or return True only if _set_aquisition_mode terminates without error ? to test which is the better option

    def wait_until_finished(self):
        """ Wait until an acquisition is finished. To be used with kinetic acquisition mode.
        """
        status = self._get_status()
        print(status)
        while status != 'DRV_IDLE':
            sleep(0.05)
            status = self._get_status()
            print(status)
        return

    # Methods for acquiring image data using synchronization between lightsource and camera-----------------------------
    def prepare_camera_for_multichannel_imaging(self, frames, exposure, gain, save_path, file_format):
        """ Set the camera state for an experiment using synchronization between lightsources and the camera.
        Using typically an external trigger.
        @param: (int) frames: number of frames in a kinetic series / fixed length mode
        @param: (float) exposure: exposure time in seconds
        @param: (int) gain: gain setting
        @param: (str) save_path: complete path (without fileformat suffix) where the image data will be saved
        @param: (str) file_format: selected fileformat such as 'tiff', 'fits', ..
        """
        self._abort_acquisition()  # as safety
        self._set_acquisition_mode('KINETICS')
        self._set_trigger_mode('EXTERNAL')
        self.set_gain(gain)
        self.set_exposure(exposure)

        # check the number of frames is not too high
        if frames > self._max_frames_number_spool:
            self.log.warn(f'The requested number of frames might be too high for the spooling mode (max number '
                          f'indicated in the config file is {self._max_frames_number_spool}). Images might be lost '
                          f'or overwritten during the process!')

        # set the number of frames
        self._set_number_kinetics(frames)

        # set spooling
        if file_format == 'fits':
            self._set_spool(1, 5, save_path, 10)
        else:  # use 'tiff' as default case # add other options if needed
            self._set_spool(1, 7, save_path, 10)

        # open the shutter
        if self._shutter == 'Closed':
            msg = self._set_shutter(1, 0, 100, 100, 1)
            if msg == 'DRV_SUCCESS':
                self._shutter = 'Open'
            else:
                self.log.error('shutter did non open. {}'.format(msg))
        sleep(1.5)  # wait until shutter is opened

        # start the acquisition. Camera waits for trigger
        self._start_acquisition()

    def reset_camera_after_multichannel_imaging(self):
        """ Reset the camera to a default state after an experiment using synchronization between lightsources and
         the camera.
         """
        self._abort_acquisition()
        self._set_spool(0, 7, '', 10)
        self._set_acquisition_mode('RUN_TILL_ABORT')
        self._set_trigger_mode('INTERNAL')

    # ----------------------------------------------------------------------------------------------------------------------
    # Methods for image data retrieval
    # ----------------------------------------------------------------------------------------------------------------------
    def get_most_recent_image(self, copy=True):
        """ Return the last acquired image and the total number of images acquired so far. Used mainly for live
        display on the GUI during a live or a movie acquisition (see camera_interface.py).
        @param: (bool) copy: if True, return a copy of the image array rather than a reference to internal data
        @return: (tuple (numpy.ndarray | None, int)) (image, frame_count); image is None if no frame could be
        retrieved
        """
        width = self._width
        height = self._height
        dim = width * height

        # dim = int(dim)
        # image_array = np.zeros(dim)
        # cimage_array = c_int * dim
        # cimage = cimage_array()

        ret, arr = self._sdk.GetMostRecentImage16(dim)
        err = self.check_error(ret, "GetMostRecentImage")
        if err:
            self.log.error("Impossible to get the most recent image!")
            return None, 0

        image_array = np.reshape(arr, (self._height, self._width))
        if copy:
            image_array = image_array.copy()
        frame_count = self.get_progress()
        return image_array, (frame_count if frame_count is not None else 0)

    def get_acquired_data(self):
        """ Return an array of the acquired data.
        Depending on the acquisition mode, this can be just one frame (single scan, run_till_abort)
        or the entire data as a 3D stack (kinetic series)
        @return: (numpy.ndarray | None) image data in format [[row],[row]...] (or [n_frames, row, row...] for a
        kinetic series). Each pixel might be a float, integer or sub-pixels. None if the acquisition mode/read mode
        combination is not supported, or if the data could not be retrieved.
        """
        width = self._width
        height = self._height

        if self._read_mode == 'IMAGE':
            if self._acquisition_mode == 'SINGLE_SCAN':
                dim = width * height
            elif self._acquisition_mode == 'KINETICS':
                dim = width * height * self._scans
            elif self._acquisition_mode == 'RUN_TILL_ABORT':
                dim = width * height
            else:
                self.log.error('Your acquisition mode is not covered currently')
                return

        elif self._read_mode == 'SINGLE_TRACK' or self._read_mode == 'FVB':
            if self._acquisition_mode == 'SINGLE_SCAN':
                dim = width
            elif self._acquisition_mode == 'KINETICS':
                dim = width * self._scans
            else:
                self.log.error('Your acquisition mode is not covered currently')
                return
        else:
            self.log.error('Your acquisition mode is not covered currently')
            return

        if self._acquisition_mode == 'RUN_TILL_ABORT':
            ret, arr = self._sdk.GetMostRecentImage(dim)
        else:
            ret, arr = self._sdk.GetAcquiredData(dim)

        err = self.check_error(ret, "get_acquired_data")

        if err:
            self.log.warning("Could not retrieve the acquired data.")
            return None

        # for i in range(dim):
        #     # could be problematic for 'FVB' or 'SINGLE_TRACK' readmode
        #     image_array[i] = arr[i]

        if self._scans > 1:  # distinguish between 3D and 2D case
            image_array = np.reshape(arr, (self._scans, self._height, self._width))
        else:
            image_array = np.reshape(arr, (self._height, self._width))

        self._cur_image = image_array
        return image_array

    # ==================================================================================================================
    # Non-Interface functions
    # ==================================================================================================================

    # pseudo-interface functions (called from camera logic when camera name is iXon Ultra or when has_temp returns true)
    def get_kinetic_time(self):
        """ Get the kinetic time in seconds.
        @return: (float) kinetic time
        """
        self._get_acquisition_timings()
        return self._kinetic

    # def set_temperature(self, temp):
    #     """ Set the temperature setpoint for the camera cooler
    #     @param: temp (int): desired new temperature
    #     """
    #     ret = self._set_temperature(temp)
    #     if msg == "DRV_SUCCESS":
    #         return True
    #     else:
    #         return False

    def get_temperature(self):
        """ Get the current temperature. Note this is one of the rare methods where the error is handled locally since
        multiple error message are specific to this action.
        @return int: temperature
        """
        ret, temperature = self._sdk.GetTemperature()
        pass_returns = ['DRV_TEMPERATURE_STABILIZED', 'DRV_TEMPERATURE_NOT_REACHED', 'DRV_TEMPERATURE_DRIFT',
                        'DRV_TEMPERATURE_NOT_STABILIZED']
        self.check_error(ret, "get_temperature", pass_returns=pass_returns)
        return temperature

    def is_cooler_on(self):
        """ Checks the status of the cooler.
        @return: (int) 0: cooler is off, 1: cooler is on
        """
        ret, cooler_status = self._sdk.IsCoolerOn()
        err = self.check_error(ret, "is_cooler_on")
        if err:
            self.log.error("The status of the cooler could not be retrieved.")
            return None
        else:
            return cooler_status

    # ----------------------------------------------------------------------------------------------------------------------
    # Non-interface functions to handle acquisitions
    # ----------------------------------------------------------------------------------------------------------------------
    def _start_acquisition(self):
        """ Launch an acquisition in two steps. If the trigger is set as INTERNAL, the function will wait for the
        acquisition actually starts.
        @return: err (bool): indicate if an error occured during the process
        """
        ret = self._sdk.StartAcquisition()
        err = self.check_error(ret, "StartAcquisition in _start_acquisition")

        if (not err) and (self._trigger_mode == 'INTERNAL'):
            ret = self._sdk.WaitForAcquisition()
            err = self.check_error(ret, "WaitForAcquisition in _start_acquisition")
        return err

    # def wait_for_acquisition(self):
    #     error_code = self.dll.WaitForAcquisition()
    #     if ERROR_DICT[error_code] != 'DRV_SUCCESS':
    #         self.log.info('non-acquisition event occured')
    #     return ERROR_DICT[error_code]

    def _abort_acquisition(self):
        ret = self._sdk.AbortAcquisition()
        err = self.check_error(ret, "_abort_acquisition", pass_returns=['DRV_SUCCESS', 'DRV_IDLE'])
        return err

    def _shut_down(self):
        ret = self._sdk.ShutDown()
        self.check_error(ret, "_shut_down")

    # ----------------------------------------------------------------------------------------------------------------------
    # Non-interface setter functions
    # ----------------------------------------------------------------------------------------------------------------------
    def _set_shutter(self, typ, mode, closing_time, opening_time, ext_shutter):
        """
        @param int typ:   0 Output TTL low signal to open shutter
                          1 Output TTL high signal to open shutter
        @param int mode:  0 - Automatic
                          1 - Open
                          2 - Close
        @closing_time - Time shutter takes to close (milliseconds)
        @opening_time - Time shutter takes to open (milliseconds)
        @ext_shutter : 0 - Automatic
                       1 - Open
                       2 - Close
        """
        ret = self._sdk.SetShutterEx(typ, mode, closing_time, opening_time, ext_shutter)
        err = self.check_error(ret, "_set_shutter")
        return err

    def _set_exposuretime(self, time):
        """
        @param time: (float) exposure duration in s
        """
        ret = self._sdk.SetExposureTime(time)
        err = self.check_error(ret, "_set_exposuretime")
        return err

    def _set_read_mode(self, mode):
        """ This function will set the read mode of the camera. Note that if the read mode is set to "Image", then the
        size of the output image is also set using the values width / height (not the default values, in case a ROI was
        defined before)

        @param mode : (string) string corresponding to certain ReadMode
        """
        if hasattr(Read_Mode, mode):
            n_mode = getattr(Read_Mode, mode).value
            ret = self._sdk.SetReadMode(n_mode)
            err = self.check_error(ret, "_set_read_mode")

            if mode == 'IMAGE':
                self._set_image(1, 1, 1, self._width, 1, self._height)

            if err:
                self.log.warning('Camera Readmode was not set!')
            else:
                self._read_mode = mode

        else:
            self.log.warning(f'{mode} readmode is not supported')

        # check_val = 0
        # if hasattr(ReadMode, mode):
        #     n_mode = getattr(ReadMode, mode).value
        #     n_mode = c_int(n_mode)
        #     error_code = self.dll.SetReadMode(n_mode)
        #     if mode == 'IMAGE':
        #         self.log.debug("width:{0}, height:{1}".format(self._width, self._height))
        #         msg = self._set_image(1, 1, 1, self._width, 1, self._height)
        #         if msg != 'DRV_SUCCESS':
        #             self.log.warning('{0}'.format(ERROR_DICT[error_code]))
        #     # put the condition on error_code here
        #     if ERROR_DICT[error_code] != 'DRV_SUCCESS':
        #         self.log.warning('Readmode was not set: {0}'.format(ERROR_DICT[error_code]))
        #         check_val = -1
        #     else:
        #         self._read_mode = mode
        # else:
        #     self.log.warning('{} readmode is not supported'.format(mode))
        #     check_val = -1
        #
        # return check_val

    def _set_trigger_mode(self, mode):
        """
        @param mode: (string) indicate the selected TriggerMode
        """
        if hasattr(Trigger_Mode, mode):
            n_mode = getattr(Trigger_Mode, mode).value
            ret = self._sdk.SetTriggerMode(n_mode)
            err = self.check_error(ret, "_set_trigger_mode")

            if err:
                self.log.warning('Camera trigger was not set')
            else:
                self._trigger_mode = mode
        else:
            self.log.warning(f'{mode} trigger mode is not supported')

    def _set_image(self, hbin, vbin, hstart, hend, vstart, vend):
        """
        This function allows to select a subimage on the sensor.

        @param int hbin: number of pixels to bin horizontally
        @param int vbin: number of pixels to bin vertically.
        @param int hstart: Start column (inclusive)
        @param int hend: End column (inclusive)
        @param int vstart: Start row (inclusive)
        @param int vend: End row (inclusive).
        @return (bool) Return True if an error is detected
        """
        ret = self._sdk.SetImage(hbin, vbin, hstart, hend, vstart, vend)
        err = self.check_error(ret, "_set_image")
        if not err:
            self._hbin = hbin
            self._vbin = vbin
            self._hstart = hstart
            self._hend = hend
            self._vstart = vstart
            self._vend = vend
            self._width = int((self._hend - self._hstart + 1) / self._hbin)
            self._height = int((self._vend - self._vstart + 1) / self._vbin)
        return err

    def _set_preamp_gain(self, index):
        """
        @param index (int): indicate the preamp gain value
        """
        ret = self._sdk.SetPreAmpGain(index)
        err = self.check_error(ret, "_set_preamp_gain")
        if not err:
            ret, self._preamp_gain = self._sdk.GetPreAmpGain(index)
            print(f'PreAmpGain was set to {self._preamp_gain}')

    def _set_vertical_shift_speed(self, index):
        """
        @param index (int): indicate the value of the default vertical shift speed
        """
        ret = self._sdk.SetFKVShiftSpeed(index)
        err = self.check_error(ret, "_set_vertical_shift_speed")
        if not err:
            ret, self._vertical_shift_speed = self._sdk.GetFKVShiftSpeed(index)
            self._vertical_shift_speed = float(self._vertical_shift_speed)
            print(f'The Vertical shift speed was set to {self._vertical_shift_speed}µs')

    def _set_vertical_clock(self, index):
        """
        @param index (int): indicate the index associate to thevertical clock range selected
        """
        ret = self._sdk.SetVSAmplitude(index)
        err = self.check_error(ret, "_set_vertical_clock")
        if not err:
            ret = self._sdk.GetVSAmplitudeString(0)
            self._vertical_clock = ret[1].value.decode("utf-8")
            print(f'The vertical clock is set to {self._vertical_clock}')

    def _set_output_amplifier(self, index):
        """
        @param index (int): indicate which amplifier output mode is selected. 0:EMCCD gain, 1:Conventional CCD register
        """
        ret = self._sdk.SetOutputAmplifier(index)
        err = self.check_error(ret, "_set_output_amplifier")
        if not err:
            self._output_amp = index
            if index == 0:
                self._output_amplifier = "Electron Multiplying standard mode"
            else:
                self._output_amplifier = "conventional CCD register/Extended NIR mode"
            print(f'The output amplifier was set to {self._output_amplifier}')

    def _set_horizontal_readout_rate(self, index):
        """
        @param index (int): indicate the horizontal readout rate to use (0=30MHz; 1=20MHz; 2=10MHz; 3=1MHz)
        """
        ret = self._sdk.SetHSSpeed(self._output_amp, index)
        err = self.check_error(ret, "_set_horizontal_readout_rate")
        if not err:
            ret, self._set_horizontal_readout_rate = self._sdk.GetHSSpeed(0, self._output_amp, index)
            print(f'The horizontal readout rate was set to {self._set_horizontal_readout_rate}MHz')

    def _set_temperature(self, temp):
        """ Sets a new temperature setpoint for the camera cooler
        @param: temp (int): temperature setpoint
        """
        ret = self._sdk.SetTemperature(temp)
        self.check_error(ret, "_set_temperature")

    def _set_acquisition_mode(self, mode):
        """
        Function to set the acquisition mode
        @param mode: (str) acquisition mode
        @return: error code: ok = 0, error = -1
        """
        if hasattr(Acquisition_Mode, mode):
            n_mode = getattr(Acquisition_Mode, mode).value
            ret = self._sdk.SetAcquisitionMode(n_mode)
            err = self.check_error(ret, "_set_acquisition_mode")
            if not err:
                self._acquisition_mode = mode
        else:
            self.log.warning(f'{mode} acquisition mode is not supported')

    def _set_cooler(self, state):
        """ This method is called to switch the cooler on or off
        @param: state (bool): cooler on = True, cooler off = False
        @return: error message
        """
        if state:
            ret = self._sdk.CoolerON()
        else:
            ret = self._sdk.CoolerOFF()
        self.check_error(ret, "_set_cooler")

    # modified jb : this mode was not accessible after modifications in 2024 due to artefacts in several experiments.
    # Now it is control directly in the config file, using the "support_frame_transfer" variable.
    def _set_frame_transfer(self, transfer_mode):
        """ set the frame transfer mode.  If the acquisition mode is Single Scan or Fast Kinetics this call will have no
        effect.
        @param: (int) tranfer_mode: 0: off, 1: on
        @return: (bool) error?
        """
        acq_mode = self._acquisition_mode
        if (acq_mode == 'SINGLE_SCAN') | (acq_mode == 'FAST_KINETICS'):
            self.log.warning('Setting of frame transfer mode has no effect in acquisition mode \'SINGLE_SCAN\' or '
                             '\'FAST_KINETICs\'.')
            return True
        else:
            ret = self._sdk.SetFrameTransferMode(transfer_mode)
            err = self.check_error(ret, "_set_frame_transfer")
            return err

    # def _set_em_gain_mode(self, mode):
    #     """ possible settings:
    #         mode = 0: the em gain is controlled by DAQ settings in the range 0-255. Default mode
    #         mode = 1: the em gain is controlled by DAQ settings in the range 0-4095.
    #         mode = 2: Linear mode.
    #         mode = 3: Real EM gain.
    #     """
    #     mode = c_int(mode)
    #     error_code = self.dll.SetEMGainMode(mode)
    #     return ERROR_DICT[error_code]

    def _set_emccd_gain(self, gain):
        """ allows to change the gain value. The allowed range depends on the gain mode currently used.
        @param: (int) new gain value
        @return: (bool) return True if an error is detected
        """
        ret = self._sdk.SetEMCCDGain(gain)
        err = self.check_error(ret, "_set_emccd_gain")
        return err

    def _set_spool(self, active, method, name, framebuffersize):
        """
        @param: int active: 0: disable spooling, 1: enable spooling
        @param: int method: indicates the format of the files written to disk.
                             0: sequence of 32-bit integers
                             1: 32-bit integer if data is being accumulated each scan, otherwise 16-bit integers
                             2: sequence of 16-bit integers
                             3: multiple directory structure with multiple images per file and multiple files per directory
                             4: spool to RAM disk
                             5: spool to 16-bit fits file
                             6: spool to andor sif format
                             7: spool to 16-bit tiff file
                             8: similar to method 3 but with data compression
                str name: filename stem (can include path) such as 'C:\\Users\\admin\\qudi-cbs-testdata\\images\\img'
                int framebuffersize: size of the internal circular buffer used as temporary storage (number of images).
                                     typical value = 10
        @return: err (bool) error message
        """
        ret = self._sdk.SetSpool(active, method, name, framebuffersize)
        err = self.check_error(ret, "_set_spool")
        return err

    def _set_number_kinetics(self, number):
        """ set the number of scans for a kinetic series acquisition
        @param: (int) number of frames to acquire
        """
        ret = self._sdk.SetNumberKinetics(number)
        self.check_error(ret, '_set_number_kinetics')

    def get_non_interfaced_parameters(self):
        """ Get the values of the parameters that have been interfaced by default.
        @return: (dic) dictionary containing all the parameters
        """
        param = {"preamp_gain": self._preamp_gain, "vertical_shift_speed_(µs)": self._vertical_shift_speed,
                 "vertical_clock": self._vertical_clock, "output_amplifier": self._output_amplifier,
                 "horizontal_readout_rate_(MHz)": self._set_horizontal_readout_rate}
        return param

    # ----------------------------------------------------------------------------------------------------------------------
    # Non-interface getter functions
    # ----------------------------------------------------------------------------------------------------------------------

    def _get_status(self):
        """
        This function is used to query the status of the camera. The following status are available :
                DRV_IDLE - waiting on instructions.
                DRV_TEMPCYCLE - Executing temperature cycle.
                DRV_ACQUIRING - Acquisition in progress.
                DRV_ACCUM_TIME_NOT_MET - Unable to meet Accumulate cycle time.
                DRV_KINETIC_TIME_NOT_MET - Unable to meet Kinetic cycle time.
                DRV_ERROR_ACK - Unable to communicate with card.
                DRV_ACQ_BUFFER - Computer unable to read the data via the ISA slot at the required rate.
                DRV_SPOOLERROR - Overflow of the spool buffer.
        @return: (str) status of the camera
        """
        ret, status_code = self._sdk.GetStatus()
        status = self.get_key_from_value(status_code)
        self.check_error(ret, "_get_status")
        return status

    def _get_detector(self):
        """ retrieves the size of the detector in pixels
        @params: c_int nx_px
        @params: c_int ny_px
        @returns: error message
                  nx_px, ny_px (int) : number of pixels along the width and height of the detector
        """
        error_code, nx_px, ny_px = self._sdk.GetDetector()
        self.check_error(error_code, "_get_detector")
        return nx_px, ny_px

    def _get_camera_serialnumber(self):
        """
        Gives serial number
        @return: (int) serial : return the camera serial number
                 (bool) err : return True if an error is detected
        """
        ret, serial = self._sdk.GetCameraSerialNumber()
        err = self.check_error(ret, "_get_camera_serialnumber")
        return err, serial

    def _get_acquisition_timings(self):
        """ Retrieves the current valid acquisition timing information.
        This method should be called after all the acquisition settings have been made (set exposuretime, set readmode)

        Updates the private attributes _exposure, _accumulate, _kinetic
        @return: (str) error message
        """
        ret, exposure, accumulate, kinetic = self._sdk.GetAcquisitionTimings()
        err = self.check_error(ret, "_get_acquisition_timings")
        if not err:
            self._exposure = exposure
            self._accumulate = accumulate
            self._kinetic = kinetic
        else:
            self._exposure = None
            self._accumulate = None
            self._kinetic = None

    def _get_em_gain_range(self):
        """ Retrieves the minimum and maximum values of the current selected electron multiplying gain mode

        @return: (int) low: minimum value
        @return: (int) high: maximum value
        """
        ret, low, high = self._sdk.GetEMGainRange()
        err = self.check_error(ret, "_get_em_gain_range")
        if not err:
            return low, high
        else:
            self.log.error("Could not retrieve the limits for the em gain")
            return None

    def _get_emccd_gain(self):
        """
        Returns the current gain setting
        @return: (int) value of the gain
        """
        ret, gain = self._sdk.GetEMCCDGain()
        err = self.check_error(ret, "_get_emccd_gain")
        if not err:
            return gain
        else:
            self.log.error("Could not retrieve the value of the emCCD gain.")
            return None