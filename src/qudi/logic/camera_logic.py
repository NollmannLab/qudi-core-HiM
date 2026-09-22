# -*- coding: utf-8 -*-
"""
Author: F. Barho & JB Fiche - adapted for qudi-core-HiM by JB Fiche
Created: 2026-08-06
Modified with Claude code (Anthropic) - functionalities modified or added by Claude:
  2026-09-19/20 : logic independent of the camera type (no more cam_type / POLLING_CAMERAS branching) following the
                  common contract of camera_interface.py: get_max_size, set_sensor_region, reset_sensor_region,
                  start_single_acquisition, start_loop, loop, stop_loop, start_save_video, save_video_loop,
                  start_spooling, spooling_loop, start_acquisition (uses _n_frames_prepared, set in
                  prepare_camera_for_multichannel_imaging), abort_acquisition; new _is_valid_image guard; fix of the
                  undefined variable 'exc' in the live loop.
  2026-09-21    : selection of the camera among several cameras: get_available_cameras, get_active_camera,
                  select_camera, signal sigCameraChanged; on_activate split into on_activate and
                  _init_from_hardware (re-read at each camera change); cam_type read with get_camera_type.
  2026-09-22    : on_activate raises a clear error if the (single) camera is not available (is_available).

This module contains the logic to control a microscope camera.

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

import time
import h5py
import numpy as np
import os

from time import sleep
from tifffile import TiffWriter
from astropy.io import fits
from ome_types.model import OME, Image, Pixels, Channel, Plane
from ruamel.yaml import YAML

from qtpy import QtCore
from qudi.core.module import LogicBase
from qudi.core.configoption import ConfigOption
from qudi.core.connector import Connector

verbose = True


# ======================================================================================================================
# Decorator (for debugging)
# ======================================================================================================================
def decorator_print_function(function):
    global verbose

    def new_function(*args, **kwargs):
        if verbose:
            print(f'*** DEBUGGING *** Executing {function.__name__} from camera_logic.py')
        return function(*args, **kwargs)

    return new_function


# ======================================================================================================================
# Worker class for camera live display
# ======================================================================================================================


class WorkerSignals(QtCore.QObject):
    """ Defines the signals available from a running worker thread """
    sigFinished = QtCore.Signal()
    sigStepFinished = QtCore.Signal(str, str, str, int, bool, dict, bool, bool)
    sigSpoolingStepFinished = QtCore.Signal(str, str, str, bool, dict)


class LiveImageWorker(QtCore.QRunnable):
    """ Worker thread to update the live image at the desired frame rate

    The worker handles only the waiting time, and emits a signal that serves to trigger the update indicators
    """

    def __init__(self, time_constant):
        super(LiveImageWorker, self).__init__()
        self.signals = WorkerSignals()
        self.time_constant = time_constant

    @QtCore.Slot()
    def run(self):
        """ """
        sleep(self.time_constant)  # Simulate work
        self.signals.sigFinished.emit()


class SaveProgressWorker(QtCore.QRunnable):
    """ Worker thread to update the progress during video saving and eventually handle the image display.

    The worker handles only the waiting time, and emits a signal that serves to trigger the update indicators """

    def __init__(self, time_constant, filenamestem, filename, fileformat, n_frames, is_display, metadata, addfile,
                 emit_signal):
        super(SaveProgressWorker, self).__init__()
        self.signals = WorkerSignals()
        self.time_constant = time_constant
        # the following attributes need to be transmitted by the worker to the finish_save_video method
        self.filenamestem = filenamestem
        self.filename = filename
        self.fileformat = fileformat
        self.n_frames = n_frames
        self.is_display = is_display
        self.metadata = metadata
        self.addfile = addfile
        self.emit_signal = emit_signal

    @QtCore.Slot()
    def run(self):
        """ """
        sleep(self.time_constant)
        self.signals.sigStepFinished.emit(self.filenamestem, self.filename, self.fileformat, self.n_frames,
                                          self.is_display, self.metadata, self.addfile, self.emit_signal)


class SpoolProgressWorker(QtCore.QRunnable):
    """ Worker thread to update the progress during spooling and eventually handle the image display.

    The worker handles only the waiting time, and emits a signal that serves to trigger the update indicators. """

    def __init__(self, time_constant, filenamestem, path, fileformat, is_display, metadata):
        super(SpoolProgressWorker, self).__init__()
        self.signals = WorkerSignals()
        self.time_constant = time_constant
        # the following attributes need to be transmitted by the worker to the finish_spooling method
        self.filenamestem = filenamestem
        self.path = path
        self.fileformat = fileformat
        self.is_display = is_display
        self.metadata = metadata

    @QtCore.Slot()
    def run(self):
        """ """
        sleep(self.time_constant)
        self.signals.sigSpoolingStepFinished.emit(self.filenamestem, self.path, self.fileformat, self.is_display,
                                                  self.metadata)


# ======================================================================================================================
# Logic class
# ======================================================================================================================
class CameraLogic(LogicBase):
    """
    Class containing the logic to control a microscope camera.

    Example config for copy-paste:

    camera_logic:
        module.Class: 'camera_logic2.CameraLogic'
        default_exposure: 20
        connect:
            hardware: 'andor_ultra_camera'
    """
    # declare connectors
    hardware = Connector(interface='CameraInterface')
    shutter = Connector(interface='ShutterInterface', optional=True)

    # declare available file formats
    fileformat_list = ConfigOption('fileformat_list', missing='error')

    # maximum speed for the live
    _max_fps = ConfigOption('max_live_speed_(fps)', 20)

    # signals
    sigUpdateDisplay = QtCore.Signal()
    sigAcquisitionFinished = QtCore.Signal()
    sigVideoFinished = QtCore.Signal()
    sigVideoSavingFinished = QtCore.Signal()
    sigSpoolingFinished = QtCore.Signal()
    sigExposureChanged = QtCore.Signal()
    sigGainChanged = QtCore.Signal(float)
    sigTemperatureChanged = QtCore.Signal(float)
    sigProgress = QtCore.Signal(int)  # sends the number of already acquired images
    sigSaving = QtCore.Signal()
    sigCleanStatusbar = QtCore.Signal()
    sigUpdateCamStatus = QtCore.Signal(str, str, str, str)
    sigLiveStarted = QtCore.Signal()  # informs the GUI that live mode was started programmatically
    sigLiveStopped = QtCore.Signal()  # informs the GUI that live mode was stopped programmatically
    sigDisableCameraActions = QtCore.Signal()
    sigEnableCameraActions = QtCore.Signal()
    sigDisableFrameTransfer = QtCore.Signal()
    sigCameraChanged = QtCore.Signal(str)  # name of the camera that is active after a call of select_camera

    # worker lock to avoid race conditions
    worker_locks = {}
    termination_flags = {}  # Track termination states
    stop_condition = QtCore.QWaitCondition()  # For waiting until the worker finishes
    stop_mutex = QtCore.QMutex()  # Mutex for synchronization

    # attributes
    cam_type = None  # indicated the type of camera used
    live_enabled = False  # indicates if the camera is currently in live mode
    saving = False  # indicates if the camera is currently saving a movie
    restart_live = False
    frame_transfer = False  # indicates whether the frame transfer mode is activated
    acquisition_aborted = False

    has_temp = False
    has_shutter = False
    has_gain = False
    support_frame_transfer = False
    _fps = 20
    _exposure = 1.
    _gain = 1.
    _temperature = 0  # use any value. It will be overwritten during on_activate if sensor temperature is available
    temperature_setpoint = _temperature
    _last_image = None
    _n_frames_prepared = None  # number of frames requested in prepare_camera_for_multichannel_imaging
    _kinetic_time = None
    _max_frames_movie = None
    _max_frames_spool = None

    _hardware = None
    _security_shutter = None

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self.threadpool = QtCore.QThreadPool()

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        self._hardware = self.hardware()
        self._security_shutter = self.shutter()

        if not self._hardware.is_available():
            raise RuntimeError('The camera could not be initialized (see the error logged by the hardware module).')

        self.live_enabled = False
        self.saving = False
        self.restart_live = False

        # read the properties and the current settings of the camera
        self._init_from_hardware()

    def _init_from_hardware(self):
        """ Read the type, the capabilities and the current settings of the (active) camera. It is called when the module
        is activated and each time another camera is selected (select_camera), since these properties depend on the
        camera.
        """
        # indicate the type of camera used (the class of the hardware module that really drives the active camera)
        self.cam_type = self._hardware.get_camera_type()

        self._last_image = None
        self._kinetic_time = None
        self.has_temp = self._hardware.has_temp()
        if self.has_temp:
            self.temperature_setpoint = self._hardware._default_temperature
        else:
            self.temperature_setpoint = 0
        self.has_shutter = self._hardware.has_shutter()
        self.has_gain = self._hardware.has_gain()
        self.support_frame_transfer = self._hardware.support_frame_transfer()
        self.frame_transfer = False

        # update the private variables _exposure, _gain, _temperature
        self.get_exposure()
        self.get_gain()
        self.get_temperature()

        # inquire the maximum number of images to acquire for movies acquisition
        max_frames_dict = self._hardware.get_max_frames()
        self._max_frames_movie = max_frames_dict['video']
        if 'spool' in max_frames_dict:
            self._max_frames_spool = max_frames_dict['spool']
        else:
            self._max_frames_spool = None

    def on_deactivate(self):
        """ Perform required deactivation. """
        pass

    # ----------------------------------------------------------------------------------------------------------------------
    # (Low-level) methods making the camera interface functions accessible from the GUI.
    # Getter and setter methods for camera attributes.
    # ----------------------------------------------------------------------------------------------------------------------

    # ----------------------------------------------------------------------------------------------------------------------
    # Selection of the camera (only relevant if several cameras are available on the microscope)
    # ----------------------------------------------------------------------------------------------------------------------

    def get_available_cameras(self):
        """ Get the names of the cameras that can be selected (a single name if only one camera is available).
        @return: (list of str) names of the cameras
        """
        return list(self._hardware.get_available_cameras())

    def get_active_camera(self):
        """ Get the name of the camera that is currently used.
        @return: (str) name of the active camera
        """
        return self._hardware.get_active_camera()

    @QtCore.Slot(str)
    def select_camera(self, name):
        """ Switch to another camera. The camera can only be changed when it is idle (no live, no movie, no synchronized
        acquisition armed). All the settings are reset : the new camera starts with its default exposure, gain and the
        full sensor size, and the properties of the logic are read again from the new camera. The signal
        sigCameraChanged is emitted with the name of the camera that is active at the end of the call, also if the
        switch was refused, so that the GUI can restore its selection.
        @param: (str) name: name of the camera to activate
        @return: (bool) True if the requested camera is active
        """
        current = self._hardware.get_active_camera()
        if name == current:
            return True

        if name not in self._hardware.get_available_cameras():
            self.log.warning(f'Camera {name} is not available - the camera is not changed.')
            self.sigCameraChanged.emit(current)
            return False

        if self.live_enabled or self.saving or not self._hardware.get_ready_state():
            self.log.warning('The camera cannot be changed while an acquisition is running.')
            self.sigCameraChanged.emit(current)
            return False

        if not self._hardware.set_active_camera(name):
            self.log.error(f'The camera could not be changed to {name}.')
            self.sigCameraChanged.emit(self._hardware.get_active_camera())
            return False

        self._n_frames_prepared = None
        self._init_from_hardware()
        self.log.info(f'Camera changed to {name}.')
        self.sigCameraChanged.emit(name)
        return True

    def get_name(self):
        """ Retrieve an identifier of the camera that the GUI can print.
        @return: (string) name for the camera
        """
        return self._hardware.get_name()

    def get_size(self):
        """ Retrieve size of the image in pixel.
        @return: tuple (int, int): Size (width, height)
        """
        return self._hardware.get_size()

    def get_max_size(self):
        """ Retrieve maximum size of the sensor in pixel.
        @return tuple (int, int): Size (width, height)
        """
        width, height = self._hardware.get_size()
        return width, height

    def set_exposure(self, time):
        """ Set the exposure time of the camera. Inform the GUI that a new value was set.
        @param: time (float): desired new exposure time in seconds
        """
        self._hardware.set_exposure(time)
        self.get_exposure()  # updates also the attribute self._exposure and self._fps
        self.sigExposureChanged.emit()

    def get_exposure(self):
        """ Get the exposure time of the camera and update the class attributes _exposure and _fps.
        @return: (float) exposure time (in seconds)
        """
        self._exposure = self._hardware.get_exposure()
        self._fps = min(1 / self._exposure, self._max_fps)
        return self._exposure

    # this function is specific to andor camera
    def get_kinetic_time(self):
        """ andor camera only: Get the kinetic time of the camera and update the class attribute _kinetic_time.
        @return: (float) kinetic time (in seconds)
        """
        if (self.get_name() == 'iXon Ultra 897') or (self.get_name() == 'iXon Ultra 888'):
            self._kinetic_time = self._hardware.get_kinetic_time()
            return self._kinetic_time
        else:
            return

    def set_gain(self, gain):
        """ Set the gain of the camera. Inform the GUI that a new gain value was set.
        @param: (int) gain: desired new gain.
        """
        self._hardware.set_gain(gain)
        gain_value = self.get_gain()  # called to update the attribute self._gain
        self.sigGainChanged.emit(gain_value)

    def get_gain(self):
        """ Get the gain setting of the camera and update the class attribute _gain.
        @return: (int) gain: current gain setting.
        """
        gain = self._hardware.get_gain()
        self._gain = gain
        return gain

    def get_gain_range(self):
        """ Get the limits for the gain.
        @return: (int) low and high limits
        """
        low, high = self._hardware.get_gain_limits()
        return low, high

    def get_progress(self):
        """ Retrieves the total number of acquired images by the camera (during a movie acquisition).
        @return: (int) progress: total number of acquired images.
        """
        return self._hardware.get_progress()

    def set_temperature(self, temperature):
        """
        Set temperature of the camera, if accessible.
        @param: int temperature: desired new temperature setpoint
        """
        if (not self.has_temp) or (self.cam_type != "IxonUltra"):
            pass
        else:
            # make sure the cooler is on
            if self._hardware.is_cooler_on() == 0:
                self._hardware._set_cooler(True)

            self.temperature_setpoint = temperature  # store the new setpoint to compare against actual temperature
            self._hardware._set_temperature(temperature)

    def get_temperature(self):
        """
        Get temperature of the camera, if accessible, and update the class attribute _temperature.
        @return: int temperature: current sensor temperature
        """
        if not self.has_temp:
            self.log.warn('Sensor temperature control not available')
        else:
            temp = self._hardware.get_temperature()
            self._temperature = temp
            return temp

    def get_max_frames(self):
        """ Return the maximum number of frames that can be handled by the camera for a single movie acquisition. Two
        values are returned, depending on which methods is used for the acquisition (video or spooling if it exists)
        @return:
            max frames video mode (int)
            max frames spool mode (int)
        """
        return self._max_frames_movie, self._max_frames_spool

    def get_non_interfaced_parameters(self):
        """ Return the values of all the non-interfaced parameters of the camera
        """
        return self._hardware.get_non_interfaced_parameters()

    # ----------------------------------------------------------------------------------------------------------------------
    # Methods to access camera state
    # ----------------------------------------------------------------------------------------------------------------------

    def get_ready_state(self):
        """ Is the camera ready for an acquisition ?

        @return: ready ? (str) 'True', 'False'
        """
        return str(self._hardware.get_ready_state())

    def get_shutter_state(self):
        """ Retrieves the status of the shutter if there is one.

        :returns str: shutter status: 'open', 'closed' """
        if not self.has_shutter:
            return
        else:
            return self._hardware._shutter

    def get_cooler_state(self):
        """
        Retrieves the status of the cooler if there is one (only if "has_temp" is True).
        @returns str: cooler on, cooler off """
        if not self.has_temp:
            return
        else:
            cooler_status = self._hardware.is_cooler_on()
            idle = self._hardware.get_ready_state()
            # first check if camera is recording
            if not idle:
                return 'NA'
            else:  # _hardware.is_cooler_on only returns an adapted value when camera is idle
                if cooler_status == 0:
                    return 'Off'
                if cooler_status == 1:
                    return 'On'

    def update_camera_status(self):
        """ Retrieves an ensemble of camera status values:
        ready: if camera is idle, shutter: open / closed if available, cooler: on / off if available, temperature value.
        Emits a signal containing the 4 retrieved status informations as str.

        :return: None
        """
        ready_state = self.get_ready_state()
        shutter_state = self.get_shutter_state()
        cooler_state = self.get_cooler_state()
        temperature = str(self.get_temperature())
        self.sigUpdateCamStatus.emit(ready_state, shutter_state, cooler_state, temperature)

    # ----------------------------------------------------------------------------------------------------------------------
    # Methods to set advanced configurations of the camera
    # ----------------------------------------------------------------------------------------------------------------------

    def get_sensor_region(self):
        """
        Get the size of the image (after setting an ROI for example)
        @return: (tuple) height and width of the image
        """
        sensor_size = self._hardware.get_image_size()
        return sensor_size

    @decorator_print_function
    def set_sensor_region(self, hbin, vbin, hstart, hend, vstart, vend, exp):
        """ Defines a limited region on the sensor surface, hence accelerating the acquisition.
        @param (int) hbin: number of pixels to bin horizontally
        @param (int) vbin: number of pixels to bin vertically.
        @param (int) hstart: Start column (inclusive)
        @param (int) hend: End column (inclusive)
        @param (int) vstart: Start row (inclusive)
        @param (int) vend: End row (inclusive)
        @param (float) exp: exposure time (in s)
        """
        # if self.live_enabled:  # live mode is on
        #     # self.interrupt_live()  # interrupt live to allow access to camera settings
        #     self.stop_loop()
        #     sleep(1)

        # update the new sensor limits
        success = self._hardware.set_image(hbin, vbin, hstart, hend, vstart, vend)
        if success:
            self.log.info('Sensor region set to {} x {}'.format(vend - vstart + 1, hend - hstart + 1))
        else:
            self.log.warning('Sensor region not set')

        # update the exposure time (required for certain camera since the time between two acquisition strongly depends
        # on the sensor size (e.g emCCD)
        self.set_exposure(exp)

        # if self.live_enabled:
        #     # self.resume_live()  # restart live in case it was activated
        #     self.start_loop()

    def reset_sensor_region(self, exp):
        """ Reset to full sensor size.
        @param (float) exp: exposure time (in s)
        """

        # if self.live_enabled:  # live mode is on
        #     self.interrupt_live()

        # reset the sensor to its default size
        width, height = self._hardware.get_size()
        success = self._hardware.set_image(1, 1, 1, width, 1, height)
        if success:
            self.log.info('Sensor region reset to default: {} x {}'.format(height, width))
        else:
            self.log.warning('Sensor region not reset to default')

        # update the exposure time
        self.set_exposure(exp)

        # if self.live_enabled:
        #     self.resume_live()

    @QtCore.Slot(bool)
    def set_frametransfer(self, activate):
        """ Activate frametransfer mode for ixon ultra camera: the boolean activate is stored in a variable in the
        camera module. When an acquisition is started, frame transfer is set accordingly.
        @params: (bool) activate ?
        """
        err = self._hardware._set_frame_transfer(int(activate))
        if err:
            self.log.warning(f'Frametransfer is disabled!')
            self.disable_frame_transfer()
        else:
            self.log.info(f'Frametransfer mode activated: {activate}')
            self.frame_transfer = bool(activate)
            self.sigExposureChanged.emit()  # update exposure time

    def disable_frame_transfer(self):
        """ For specific tasks, the frame transfer mode should be disabled."""
        self.sigDisableFrameTransfer.emit()

    # ----------------------------------------------------------------------------------------------------------------------
    # Methods to handle camera acquisition and snap / live display
    # ----------------------------------------------------------------------------------------------------------------------

    # Method invoked by snap button on GUI ---------------------------------------------------------------------------------
    def start_single_acquisition(self):
        """ Take a single camera image.
        """
        # For the RAMM microscope, a shutter is used to block the IR laser
        if self._security_shutter is not None:
            self._security_shutter.camera_security(acquiring=True)

        # Take the image (the hardware returns the frame, or None if the acquisition failed)
        image = self._hardware.start_single_acquisition()

        # Send signal to GUi for image display
        if self._is_valid_image(image):
            self._last_image = image
            self.sigUpdateDisplay.emit()
        else:
            self.log.warning('The camera did not return any image.')
        self._hardware.stop_acquisition()  # this in needed to reset the acquisition mode to default
        self.sigAcquisitionFinished.emit()

    # Methods invoked to handle workers ------------------------------------------------------------------------------------
    def worker_finished(self, worker_id):
        """Handle worker completion.
        """
        if worker_id in self.worker_locks:
            lock = self.worker_locks[worker_id]
            if lock.tryLock():  # Ensure the lock is actually locked
                lock.unlock()
            else:
                print(f"Worker {worker_id} finished, but lock was not active.")
        else:
            print(f"Worker lock for {worker_id} not found.")

    def wait_for_worker_lock(self, worker_id):
        """ Based on the worker id, make sure that all workers with the same id are properly terminated.
            @param worker_id: (obj) id of the worker
        """
        # check if the worker id was in the termination flag list
        if worker_id not in self.termination_flags:
            print(f"No active worker found for ID: {worker_id}")
            return

        # Signal the worker to stop
        self.termination_flags[worker_id] = True

        # Acquire the mutex and wait until the worker finishes
        self.stop_mutex.lock()
        print(f"Waiting for worker {worker_id} to finish...")
        if not self.stop_condition.wait(self.stop_mutex, 500):
            print(f"Timeout (0.5) reached while waiting for worker {worker_id} to finish.")
        self.stop_mutex.unlock()

        # Clean up worker-related resources - note it is possible in that case that the lock is realeased even before
        # the worker finishes its task.
        if worker_id in self.worker_locks:
            lock = self.worker_locks[worker_id]
            if lock.tryLock():  # Ensure no thread is actively using the lock
                lock.unlock()
            del self.worker_locks[worker_id]
            del self.termination_flags[worker_id]
            print(f"Lock for worker {worker_id} released in stop_loop.")

    # Methods invoked by live button on GUI --------------------------------------------------------------------------------

    def _schedule_live_update(self):
        worker = LiveImageWorker(1 / self._fps)
        worker.signals.sigFinished.connect(self.loop)
        self.threadpool.start(worker)

    def start_loop(self, worker_id="live_worker"):
        """ Start the live display mode.
        """
        # For safety - make sure there is no multiple live being launched at the same time
        if self.live_enabled:
            self.log.warning('Live display is already running - skip start_loop in camera_logic!')
            return

        # Indicate that a live acquisition is starting
        self.live_enabled = True
        if self._security_shutter is not None:
            self._security_shutter.camera_security(acquiring=True)

        # start the camera. If the camera cannot handle live acquisition, the images are obtained by repeated single
        # acquisitions in the loop method.
        if self._hardware.support_live_acquisition():
            if not self._hardware.start_live_acquisition():
                self.log.warning('The live acquisition did not start properly.')

        # Start display polling
        self._schedule_live_update()

    def loop(self, worker_id="live_worker"):
        """ Execute one step in the live display loop.
        """

        # Skip if live mode is disabled
        if not self.live_enabled:
            return

        try:
            # Get the latest image acquired by the camera (or take a new one if live acquisition isn't supported).
            # No copy of the images is performed during live acquisition (to avoid lagging).
            if self._hardware.support_live_acquisition():
                image, _ = self._hardware.get_most_recent_image(copy=False)
            else:
                image = self._hardware.start_single_acquisition()

            # The display is updated only if a frame is available (none is available right after the acquisition was
            # started, or if the exposure time is long) - otherwise the previous image is kept.
            if self._is_valid_image(image):
                self._last_image = image
                self.sigUpdateDisplay.emit()

        except Exception as e:
            self.log.exception(f"Error during live camera update: {e}")
            self.live_enabled = False
            return

        if self.live_enabled:
            self._schedule_live_update()

    def stop_loop(self, worker_id="live_worker"):
        """ Stop the live display loop.
        """
        # Safety - avoid trying finishing live loop multiple times
        if not self.live_enabled:
            print("Live display is already stopped.")
            return

        # Turn live_enabled to False and stop the loop
        self.live_enabled = False

        # no copy of the images is performed during live acquisition (to avoid lagging). However, a copy is performed
        # before stopping the camera and removing all the images from the buffer. This copy is required for the GUI's
        # display.
        if self._hardware.support_live_acquisition():
            image, _ = self._hardware.get_most_recent_image(copy=True)
            if self._is_valid_image(image):
                self._last_image = image

        # stop acquisition
        self._hardware.stop_acquisition()
        if self._security_shutter is not None:
            self._security_shutter.camera_security(acquiring=False)

    # Method invoked by save last image button on GUI ----------------------------------------------------------------------
    def save_last_image(self, path, metadata, fileformat='.tif'):
        """
        saves a single image to disk
        @param: str path: path stem, such as '/home/barho/images/2020-12-16/samplename'
        @param: dict metadata: dictionary containing the metadata
        @param: str fileformat: default '.tif' but can be modified if needed.
        """
        if self._last_image is None:
            self.log.warning('No image available to save')
        else:
            image_data = self._last_image

            complete_path = self.create_generic_filename(path, '_Image', 'image', fileformat, addfile=False)
            self.save_to_tiff(1, complete_path, image_data)
            self.save_metadata_txt_file(path, '_Image', metadata)

    # Methods invoked by start video button on GUI--------------------------------------------------------------------------
    @decorator_print_function
    def start_save_video(self, filenamestem, filename, fileformat, n_frames, is_display, metadata, addfile=False,
                         emit_signal=True):
        """ Starts saving n_frames to disk as a stack (tiff of fits formats supported)

        @param: (str) filenamestem, such as /home/barho/images/2020-12-16/samplename
        @param: (str) filename, such as movie_00
        @param: (str) fileformat (including the dot, such as '.tif', '.fits')
        @param: (int) n_frames: number of frames to be saved
        @param: (bool) is_display: show images on live display on gui
        @param: (dict) metadata: meta information to be saved with the image data (in a separate txt file if tiff
                                fileformat, or in the header if fits format)
        @param: (bool) addfile: indicate if the images are saved in a new folder or appended to the last created
        @param: (bool) emit_signal: can be set to False in order to avoid sending the signal for gui interaction,
                for example when function is called from ipython console or in a task
                #leave the default value True when function is called from gui
        """
        # live is switched off from the GUI when an acquisition is launched. However, checked the camera is ready for an
        # acquisition
        status = self._hardware.get_ready_state()
        while not status:
            status = self._hardware.get_ready_state()
            sleep(0.25)

        self.saving = True

        # handle IR laser shutter security
        if self._security_shutter is not None:
            self._security_shutter.camera_security(acquiring=True)

        # start movie acquisition
        started = self._hardware.start_movie_acquisition(n_frames)
        if not started:
            self.log.warning('Video acquisition did not start')
            self.finish_save_video(filenamestem, filename, fileformat, n_frames, metadata, addfile, emit_signal=True)
            return

        # wait at least a full exposure time to make sure at least one image was acquired.
        time.sleep(self._exposure * 2)

        # start a worker thread that will monitor the status of the saving
        worker = SaveProgressWorker(1 / self._fps, filenamestem, filename, fileformat, n_frames, is_display, metadata,
                                    addfile, emit_signal)
        worker.signals.sigStepFinished.connect(self.save_video_loop)
        self.threadpool.start(worker)

    def save_video_loop(self, filenamestem, filename, fileformat, n_frames, is_display, metadata, addfile, emit_signal):
        """ This method performs one step in saving procedure until the last image is saved.
        Handles also the update of the live display if activated.

        @param: (str) filenamestem, such as /home/barho/images/2020-12-16/samplename
        @param: (str) filename, such as movie_00
        @param: (str) fileformat (including the dot, such as '.tif', '.fits')
        @param: (int) n_frames: number of frames to be saved
        @param: (bool) is_display: show images on live display on gui
        @param: (dict) metadata: meta information to be saved with the image data (in a separate txt file if tiff
                                fileformat, or in the header if fits format)
        @param: (bool) addfile: indicate if the images are saved in a new folder or appended to the last created
        @param: (bool) emit_signal: can be set to False in order to avoid sending the signal for gui interaction,
                for example when function is called from ipython console or in a task
                #leave the default value True when function is called from gui
        """
        # Check if the camera is still acquiring
        ready = self._hardware.get_ready_state()

        # Handle progress and display - progress & display are handled in the same function, since the camera returns
        # the number of acquired frames together with the most recent image.
        if (not ready) and (not self.acquisition_aborted):
            image, progress = self._hardware.get_most_recent_image()
            self.sigProgress.emit(int(progress))
            if self._is_valid_image(image):
                self._last_image = image
                if is_display:
                    self.sigUpdateDisplay.emit()

            # restart a worker if acquisition still ongoing
            worker = SaveProgressWorker(1 / self._fps, filenamestem, filename, fileformat, n_frames, is_display,
                                        metadata, addfile, emit_signal)
            worker.signals.sigStepFinished.connect(self.save_video_loop)
            self.threadpool.start(worker)

        elif self.acquisition_aborted:
            self.abort_save_video()

        # finish the save procedure when hardware is ready
        else:
            self.finish_save_video(filenamestem, filename, fileformat, n_frames, metadata, addfile, emit_signal)

    def abort_save_video(self, emit_signal=True):
        """ This method is used when an acquisition is aborted

        @param: (bool) emit_signal: can be set to False in order to avoid sending the signal for gui interaction,
        for example when function is called from ipython console or in a task
        #leave the default value True when function is called from gui
        """
        self._hardware.abort_movie_acquisition()
        self.acquisition_aborted = False
        self.saving = False

        # if there is a shutter, release the shutter
        if self._security_shutter is not None:
            self._security_shutter.camera_security(acquiring=False)

        # restart live in case it was activated
        if self.restart_live:
            self.restart_live = False  # reset to default value
            self.start_live_mode()
            # self.start_loop()

        if emit_signal:
            self.sigVideoSavingFinished.emit()
        else:  # needed to clean up the info on statusbar when gui is opened without calling video_saving_finished
            self.sigCleanStatusbar.emit()

    @decorator_print_function
    def finish_save_video(self, filenamestem, filename, fileformat, n_frames, metadata, addfile, emit_signal=True):
        """ This method finishes the saving procedure. Live mode of the camera is eventually restarted.

        @param: (str) filenamestem, such as /home/barho/images/2020-12-16/samplename
        @param: (str) filename, such as movie_00
        @param: (str) fileformat (including the dot, such as '.tif', '.fits')
        @param: (int) n_frames: number of frames to be saved
        @param: (dict) metadata: meta information to be saved with the image data (in a separate txt file if tiff
                                fileformat, or in the header if fits format)
        @param: (bool) addfile: indicate if the images are saved in a new folder or appended to the last created
        @param: (bool) emit_signal: can be set to False in order to avoid sending the signal for gui interaction,
                for example when function is called from ipython console or in a task
                #leave the default value True when function is called from gui
        """
        self._hardware.wait_until_finished()  # this is important especially if display is disabled
        self.sigSaving.emit()  # for info message on statusbar of GUI

        # get the acquired data before resetting the acquisition mode of the camera
        image_data = self._hardware.get_acquired_data()

        # reset the attributes and the default acquisition mode
        self._hardware.finish_movie_acquisition()
        if self._security_shutter is not None:
            self._security_shutter.camera_security(acquiring=False)
        self.saving = False

        # data handling
        if image_data is not None:
            complete_path = self.create_generic_filename(filenamestem, '_Movie', filename, fileformat, addfile=addfile)
            if fileformat == '.tif':
                self.save_to_tiff(n_frames, complete_path, image_data)
                self.save_metadata_txt_file(filenamestem, '_Movie', metadata)
            elif fileformat == '.fits':
                fits_metadata = self.convert_to_fits_metadata(metadata)
                self.save_to_fits(complete_path, image_data, fits_metadata)
            elif fileformat == '.npy':
                self.save_to_npy(complete_path, image_data)
                self.save_metadata_txt_file(filenamestem, '_Movie', metadata)
            elif fileformat == '.hdf5':
                hdf5_metadata = {'exposure': self._exposure, 'n_channels': 1}
                self.save_to_hdf5(complete_path, image_data, hdf5_metadata)
            elif fileformat == '.ome-tif':
                self.save_to_ome_tif(complete_path, image_data, metadata)
            else:
                self.log.error(f'Your fileformat {fileformat} is currently not covered')

        # send signal to GUI
        if emit_signal:
            self.sigVideoSavingFinished.emit()
        else:  # needed to clean up the info on statusbar when gui is opened without calling video_saving_finished
            self.sigCleanStatusbar.emit()

        # # restart live in case it was activated
        # if self.restart_live:
        #     self.restart_live = False  # reset to default value
        #     self.start_live_mode()
        #     # self.start_loop()

    # methods specific for andor ixon ultra camera for video saving ----------------------------------------------------
    def start_spooling(self, filenamestem, filename, fileformat, n_frames, is_display, metadata, addfile=False):
        """ Starts saving n_frames to disk as a tiff stack without need of data handling within this function.
        Available for andor camera. Useful for large data sets which would be overwritten in the buffer.
        @param: (str) filenamestem, such as '/home/barho/images/2020-12-16/samplename'
        @param: (str) fileformat: including the dot, such as '.tif', '.fits'
        @param: (int) n_frames: number of frames to be saved
        @param: (bool) is_display: show images on live display on gui
        @param: (dict) metadata: meta information to be saved with the image data (in a separate txt file if tiff
                fileformat, or in the header if fits format)
        @param: (bool) addfile: indicate if the images are saved in a new folder or appended to the last created
        """
        # if self.live_enabled:  # live mode is on
        #     # store the state of live mode in a helper variable
        #     self.restart_live = True
        #     self.live_enabled = False  # live mode will stop then
        #     self._hardware.stop_acquisition()

        self.saving = True
        if self._security_shutter is not None:
            self._security_shutter.camera_security(acquiring=True)
        path = self.create_generic_filename(filenamestem, '_Movie', filename, '', addfile=addfile)
        # Depending on the selected format, set the correct spool method
        if fileformat == '.tif':
            method = 7
        elif fileformat == '.fits':
            method = 5
        else:
            self.log.info(f'Your fileformat {fileformat} is currently not covered for spool conditions')
            return
        err_spool = self._hardware.set_spool(1, method, path, 10)

        # Start acquisition
        started = self._hardware.start_movie_acquisition(n_frames)  # setting kinetics acquisition mode, make sure
        if err_spool or not started:
            self.log.warning('Spooling did not start')

        # start a worker thread that will monitor the status of the saving
        worker = SpoolProgressWorker(1 / self._fps, filenamestem, path, fileformat, is_display, metadata)
        worker.signals.sigSpoolingStepFinished.connect(self.spooling_loop)
        self.threadpool.start(worker)

    def spooling_loop(self, filenamestem, path, fileformat, is_display, metadata):
        """ This method performs one step in spooling procedure.
        Handles also the update of the live display if activated.
        NB : most of the parameters are only needed to hand them over to finish_spooling method.
        @param: (str) filenamestem, such as '/home/barho/images/2020-12-16/samplename'
        @param: (str) path: generic filepath created in start_spooling using the filenamestem
        @param: (str) fileformat: including the dot, such as '.tif', '.fits'
        @param: (bool) is_display: show images on live display on gui - True, False
        @param: (dict) metadata: meta information to be saved with the image data (in a separate txt file if tiff
                fileformat, or in the header if fits format)
        """
        ready = self._hardware.get_ready_state()

        if (not ready) and (not self.acquisition_aborted):
            spoolprogress = self._hardware.get_progress()
            self.sigProgress.emit(spoolprogress)

            if is_display:
                image, _ = self._hardware.get_most_recent_image()
                if self._is_valid_image(image):
                    self._last_image = image
                    self.sigUpdateDisplay.emit()

            # restart a worker if acquisition still ongoing
            worker = SpoolProgressWorker(1 / self._fps, filenamestem, path, fileformat, is_display, metadata)
            worker.signals.sigSpoolingStepFinished.connect(self.spooling_loop)
            self.threadpool.start(worker)

        elif self.acquisition_aborted:
            self.abort_save_video()

        # finish the save procedure when hardware is ready
        else:
            self.finish_spooling(filenamestem, path, fileformat, metadata)

    def finish_spooling(self, filenamestem, path, fileformat, metadata):
        """ This method finishes the spooling procedure.
        @param: (str) filenamestem, such as '/home/barho/images/2020-12-16/samplename'
        @param: (str) path: generic filepath created in start_spooling using the filenamestem
        @param: (str) fileformat: including the dot, such as '.tif', '.fits'
        @param: (bool) is_display: show images on live display on gui - True, False
        @param: (dict) metadata: meta information to be saved with the image data (in a separate txt file if tiff
                fileformat, or in the header if fits format)
        """
        if fileformat == '.tif':
            method = 7
        elif fileformat == '.fits':
            method = 5
        else:
            pass

        self._hardware.wait_until_finished()
        self._hardware.finish_movie_acquisition()
        self._hardware.set_spool(0, method, path, 10)  # deactivate spooling
        self.log.info(f'Saved data to file {path}{fileformat}')

        # metadata saving
        if fileformat == '.tif':
            self.save_metadata_txt_file(filenamestem, '_Movie', metadata)
        elif fileformat == '.fits':
            try:
                complete_path = path + '.fits'
                fits_metadata = self.convert_to_fits_metadata(metadata)
                self.add_fits_header(complete_path, fits_metadata)
            except Exception as e:
                self.log.warn(f'Metadata not saved: {e}.')
        else:
            pass

        self.saving = False
        if self._security_shutter is not None:
            self._security_shutter.camera_security(acquiring=False)

        # # restart live in case it was activated
        # if self.restart_live:
        #     self.restart_live = False  # reset to default value
        #     self.start_loop()

        # send signal to the GUI to either stop the acquisition or start the following block
        self.sigSpoolingFinished.emit()

    # ----------------------------------------------------------------------------------------------------------------------
    # Methods for Qudi tasks / experiments requiring synchronization between camera and lightsources
    # ----------------------------------------------------------------------------------------------------------------------
    def prepare_camera_for_multichannel_imaging(self, frames, exposure, gain, save_path, file_format):
        """ Method used for camera in external trigger mode, used for tasks with synchonization between
        lightsources and camera. Prepares the camera setting the required parameters. Camera waits for trigger.

        @param: int frames:
        @param: float exposure:
        @param: int gain:
        @param: str save_path:
        @param: str file_format:
        """
        self._n_frames_prepared = frames  # number of frames of the sequence launched by start_acquisition
        self._hardware.prepare_camera_for_multichannel_imaging(frames, exposure, gain, save_path, file_format)

    def reset_camera_after_multichannel_imaging(self):
        """
        Reset the camera default state at the end of a synchronized acquisition mode.
        """
        self._hardware.reset_camera_after_multichannel_imaging()

    def get_acquired_data(self):  # used in Hi-M Task RAMM
        return self._hardware.get_acquired_data()

    def start_acquisition(self):
        """
        This method is only used for the task, to launch an acquisition without connections to the GUI (no display and
        no possible interactions with the user).
        """
        # close the shutter for IR laser (only for the RAMM setup)
        if self._security_shutter is not None:
            self._security_shutter.camera_security(acquiring=True)

        # launch the acquisition of the sequence defined in prepare_camera_for_multichannel_imaging
        if self._n_frames_prepared is None:
            self.log.error('The camera was not prepared (prepare_camera_for_multichannel_imaging) - the acquisition '
                           'cannot start.')
            return False
        started = self._hardware.start_movie_acquisition(self._n_frames_prepared)
        if not started:
            self.log.error('The acquisition did not start.')
        return started

    def stop_acquisition(self):  # used in Hi-M Task RAMM
        self._hardware.stop_acquisition()
        if self._security_shutter is not None:
            self._security_shutter.camera_security(acquiring=False)

    def abort_acquisition(self):  # used in multicolor imaging PALM  -> can this be combined with stop_acquisition ?
        self._hardware.abort_movie_acquisition()

    # ----------------------------------------------------------------------------------------------------------------------
    # Filename and data handling
    # ----------------------------------------------------------------------------------------------------------------------

    def get_last_image(self):  # is this method needed ??
        """ Return last acquired image.

        :return: np.ndarray self._last_image """
        return self._last_image

    @staticmethod
    def _is_valid_image(image):
        """ Check that the camera returned an image. None (or an empty array) is returned by the cameras when no frame
        is available.

        :param: image: object returned by the camera
        :return: bool: True if image contains data """
        return image is not None and np.size(image) > 0

    def create_generic_filename(self, filenamestem, folder, file, fileformat, addfile):
        """ This method creates a generic filename using the following format:
        filenamestem/001_folder/file.tif example: /home/barho/images/2020-12-16/samplename/000_Movie/movie.tif

        filenamestem is typically generated by the save settings dialog in basic gui but can also entered manually if
        function is called in the console

        @param: (str) filenamestem  (example /home/barho/images/2020-12-16/samplename)
        @param: (str) folder: specify the type of experiment (ex. Movie, Snap)
        @param: (str) file: filename (ex movie, image). do not specify the fileformat.
        @param: (str) fileformat: specify the type of file (.tif, .txt, ..) including the dot !
        @param: (bool) addfile: if True, the last created folder will again be accessed (needed for metadata saving)
        @return: (str) complete path
        """
        # Check if folder filenamestem exists, if not create it
        if not os.path.exists(filenamestem):
            try:
                os.makedirs(filenamestem)  # recursive creation of all directories on the path
            except Exception as e:
                self.log.error('Error {0}'.format(e))

        # Count the subdirectories in the directory filenamestem (non recursive !) to generate an incremental prefix
        dir_list = [name for name in os.listdir(filenamestem) if os.path.isdir(os.path.join(filenamestem, name))]
        number_dirs = len(dir_list)
        if addfile:
            number_dirs -= 1
        prefix = str(number_dirs).zfill(3)
        folder_name = prefix + folder
        path = os.path.join(filenamestem, folder_name)

        # Create this folder (since addfile is possible, need to check first whether the folder already exists)
        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except Exception as e:
                self.log.error('Error creating the target folder: {}'.format(e))

        # Count the number of files in the folder
        filename = f"{file}{fileformat}"
        complete_path = os.path.join(path, filename)
        return complete_path

    def save_to_tiff(self, n_frames, path, data):
        """ Save the image data to a tiff file.

        @param: (int) n_frames: number of frames (needed to distinguish between 2D and 3D data)
        @param: (str) path: complete path where the object is saved to (including the suffix .tif)
        @param: data: (np.array) image stack
        """
        try:
            with TiffWriter(path) as tif:
                tif.write(data.astype(np.uint16))
            self.log.info('Saved data to file {}'.format(path))
        except Exception as e:
            self.log.warning(f'Data not saved: {e}')

    def save_to_tiff_separate(self, n_channels, path, data):
        """ For each separate channel (laser line), save the image data to a tiff file.

        @param: int n_channels: number of acquisition channels
        @param: str path: complete path where the object is saved to (including the suffix .tif)
        @param: data: (np.array) image stack
        """
        try:
            for channel in range(n_channels):
                new_path, filename = os.path.split(path)
                filename, _ = os.path.splitext(filename)
                new_path = os.path.join(new_path, f'{filename}_ch{str(channel).zfill(2)}.tif')

                with TiffWriter(new_path) as tif:
                    tif.write(data[channel::n_channels].astype(np.uint16))
                self.log.info('Saved data to file {}'.format(new_path))
        except Exception as e:
            self.log.warning(f'Data not saved: {e}')

    def save_metadata_txt_file(self, filenamestem, datatype, metadata):
        """"Save a txt file containing the metadata.
        @param: (str) filenamestem (example /home/barho/images/2020-12-16/samplename)
        @param: (str) datatype: string identifier of the data shape: _Movie or _Image
        @param: (dict) metadata: dictionary containing the annotations
        """
        complete_path = self.create_generic_filename(filenamestem, datatype, 'parameters', '.txt', addfile=True)
        with open(complete_path, 'w') as file:
            # file.write(str(metadata))  # for standard txt file
            # yaml file. can use suffix .txt. change if .yaml preferred.
            yaml = YAML()
            yaml.dump(metadata, file)
        self.log.info('Saved metadata to {}'.format(complete_path))

    def save_to_fits(self, path, data, metadata):
        """ Save the image data to a fits file, including the metadata in the header
        See also https://docs.astropy.org/en/latest/io/fits/index.html#creating-a-new-image-file

        Works for 2D data and stacks

        :param: str path: complete path where the object is saved to, including the suffix .fits
        :param: data: np.array (2D or 3D)
        :param: dict metadata: dictionary containing the metadata that shall be saved with the image data
        """

        data = data.astype(np.int16)  # data conversion because 16 bit image shall be saved
        hdu = fits.PrimaryHDU(data)  # PrimaryHDU object encapsulates the data
        hdul = fits.HDUList([hdu])
        # add the header
        hdr = hdul[0].header
        for key in metadata:
            hdr[key] = metadata[key]
        # write to file
        try:
            hdul.writeto(path)
            self.log.info('Saved data to file {}'.format(path))
        except Exception as e:
            self.log.warning(f'Data not saved: {e}')
        #
        # t1 = time()
        # print(f'Saving time : {t1-t0}s')

    def save_to_hdf5(self, path, data, metadata):
        """ Save the data in h5 format. This function was specifically created for the Kinetix camera. Considering the
        size of the images, a gzip compression is applied (this method is a lossless method - the decompressed images
        should be identical to the original). Note the metadata are also saved in the same file and the images are
        separated according to acquisition channels.

        @param path: (str) complete path where to save the data
        @param data: (numpy array) array containing the images to be saved
        @param metadata: (dict) contains all the metadata regarding the acquisition parameters
        """
        n_channels = int(metadata['n_channels'])
        with h5py.File(path, 'w') as hf:
            for channel in range(n_channels):
                self.log.info(f"Saving images for channel {channel}")
                dataset = hf.create_dataset(f'image_ch{channel}', data=data[channel::n_channels],
                                            compression='gzip', compression_opts=1)
                # dataset = hf.create_dataset(f'image_ch{channel}', data=data[channel::n_channels],
                #                             compression='lzf')
                # dataset = hf.create_dataset(f'image_ch{channel}', data=data[channel::n_channels],
                #                             **hdf5plugin.Blosc())

            self.log.info(f"Saving metadata.")
            for key, value in metadata.items():
                dataset.attrs[key] = value

    @staticmethod
    def add_fits_header(path, dictionary):
        """ After spooling to fits format, this method accesses the file and adds the metadata in the header.
        This method is to be used only in combination with spooling.
        :params str path: complete path where the object is saved to, including the suffix .fits
        :params dict dictionary: containing metadata with fits compatible keys and values
        """
        with fits.open(path, mode='update') as hdul:
            hdr = hdul[0].header
            for key in dictionary:
                hdr[key] = dictionary[key]

    @staticmethod
    def convert_to_fits_metadata(metadata):
        """ Convert a dictionary in arbitrary format to fits compatible format, using keys with max. 8 letters,
        capitals and no spaces. If several values are stored under one key, each list item gets its proper key
        using a numerotation.
        :param: dict metadata: dictionary to convert to fits compatible format

        :return: dict fits_metadata: dictionary converted to fits compatible format """
        fits_metadata = {}
        for key, value in metadata.items():
            key = key.replace(' ', '_')
            if isinstance(value, list):
                for i in range(len(value)):
                    fits_key = key[:7].upper() + str(i + 1)
                    fits_value = (value[i], key + str(i + 1))
                    fits_metadata[fits_key] = fits_value
            else:
                fits_key = key[:8].upper()
                fits_value = (value, key)
                fits_metadata[fits_key] = fits_value

        return fits_metadata

    def save_to_npy(self, path, data):
        """ Save the image data to a npy file. The images are reformated to uint16, in order to optimize the saving
        time.
        @param: str path: complete path where the object is saved to (including the suffix .tif)
        @param: data: np.array
        """
        try:
            np.save(path, data.astype(np.uint16))
            self.log.info('Saved data to file {}'.format(path))
        except Exception as e:
            self.log.warning(f'Data not saved: {e}')

    def save_to_ome_tif(self, path, data, metadata):
        """Save a NumPy array as an OME-TIFF file.
        @param: path (str): indicate the complete file path were to save the data
        @param: data (numpy array): acquired data
        @param: metadata (dict): contains all the metadata associated to the acquisition
        """
        # Read the parameters from the metadata
        acquisition = metadata.get('Acquisition', [])
        exposure = None
        kinetic = None
        excitation_wavelength = []

        for item in acquisition:
            if 'exposure_time_(s)' in item:
                exposure = item['exposure_time_(s)']
            if 'laser_lines' in item:
                excitation_wavelength = item['laser_lines']
                if len(excitation_wavelength) > 0:
                    excitation_wavelength = int(excitation_wavelength[0].split()[0])
                else:
                    excitation_wavelength = None
            if 'kinetic_time_(s)' in item:
                kinetic = item['kinetic_time_(s)']

        # Create the metadata
        Nframes, Lx, Ly = data.shape
        planes = [Plane(delta_t=kinetic * i, delta_t_unit="s",
                        exposure_time=exposure, exposure_time_unit="s",
                        the_z=0, the_c=0, the_t=i)
                  for i in range(Nframes)]

        channel = Channel(
            id='Channel:0:0',
            name='CH1',
            illumination_type='Epifluorescence'
        )
        if excitation_wavelength is not None:
            channel.excitation_wavelength = excitation_wavelength

        pixels = Pixels(
            id='Pixels:0',
            dimension_order='XYZCT',
            size_c=1,
            size_t=Nframes,
            size_x=Ly,
            size_y=Lx,
            size_z=1,
            type='uint16',
            channels=[channel],
            planes=planes,
        )
        ome = OME(images=[Image(id="Image:0", pixels=pixels)])

        # Save the data as TIFF
        with TiffWriter(path) as tif:
            tif.write(data.astype(np.uint16), metadata={"axes": "TXY", "OME": ome.to_xml()})

    # ----------------------------------------------------------------------------------------------------------------------
    # Methods to handle the user interface state
    # ----------------------------------------------------------------------------------------------------------------------
    def start_live_mode(self):
        """ Allows to start the live mode programmatically.
        """
        if not self.live_enabled:
            print('Launching live!')
            self.sigLiveStarted.emit()  # to inform the GUI that live mode has been started programmatically

    def stop_live_mode(self):
        """ Allows to stop the live mode programmatically, for example in the preparation steps of a task
        where live mode would interfere with the new camera settings. """
        if self.live_enabled:
            self.stop_loop()
            self.sigLiveStopped.emit()  # to inform the GUI that live mode has been stopped programmatically

    def disable_camera_actions(self):
        """ This method provides a security to avoid all camera related actions from GUI, for example during Tasks. """
        self.sigDisableCameraActions.emit()

    def enable_camera_actions(self):
        """ This method resets all camera related actions from GUI to callable state, for example after Tasks. """
        self.sigEnableCameraActions.emit()