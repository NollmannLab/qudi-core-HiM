# -*- coding: utf-8 -*-
"""
Interface for generic camera hardware used by qudi-core-HiM.
Modified: 2026-09-20 using Claude code

Contract shared by all the camera hardware modules (Kinetix, ORCA, dummy, ...). camera_logic relies only on what is
described here, so that it does not need to know which camera is connected.

- Methods returning a bool report a success : True = the operation succeeded, False = it failed.
- Images are 2D numpy arrays in row-major format [height, width]. Sequences are 3D arrays [n_frames, height, width].
- Live / movie acquisitions are "polled" : the camera fills its own buffer, the logic asks regularly for the most recent
  frame with get_most_recent_image (which also reports how many frames were acquired so far) and retrieves the whole
  sequence with get_acquired_data once the camera is ready again.
- get_size returns the size of the FULL sensor as (width, height), whereas get_image_size returns the size of the
  current image (after a ROI was set) as (height, width).
"""

from abc import abstractmethod
from qudi.core.module import Base


class CameraInterface(Base):
    """Interface for microscope camera hardware."""

    # ------------------------------------------------------------------------------------------------------------------
    # Getter and setter methods
    # ------------------------------------------------------------------------------------------------------------------

    @abstractmethod
    def get_name(self):
        """Return camera name."""
        pass

    @abstractmethod
    def get_size(self):
        """Return the size of the FULL sensor as (width, height)."""
        pass

    @abstractmethod
    def set_exposure(self, exposure):
        """Set exposure time in seconds. Return True on success."""
        pass

    @abstractmethod
    def get_exposure(self):
        """Return exposure time in seconds."""
        pass

    @abstractmethod
    def set_gain(self, gain):
        """Set camera gain. Return True on success."""
        pass

    @abstractmethod
    def get_gain(self):
        """Return camera gain."""
        pass

    def get_gain_limits(self):
        """Return lower and upper gain limits (optional - only relevant if the camera has a gain control).

        Not abstract: cameras without gain (Kinetix, ORCA, ...) inherit this default.
        """
        return 0, 0

    @abstractmethod
    def get_ready_state(self):
        """Return True if the camera is ready for an acquisition, False while it is acquiring (live or movie)."""
        pass

    @abstractmethod
    def set_image(
        self,
        hbin,
        vbin,
        hstart,
        hend,
        vstart,
        vend,
    ):
        """Set the active camera sensor region (ROI).

        Columns and rows are numbered from 1 and the end positions are inclusive (the full sensor is
        set_image(1, 1, 1, width, 1, height)). Return True on success.
        """
        pass

    @abstractmethod
    def get_image_size(self):
        """Return the size of the current image, after a ROI was set, as (height, width)."""
        pass

    @abstractmethod
    def get_progress(self):
        """Return the number of frames acquired since the beginning of the current acquisition.

        Cameras reporting this number through get_most_recent_image may return None. It is only needed by the
        acquisition modes that do not retrieve images (e.g. spooling).
        """
        pass

    @abstractmethod
    def get_max_frames(self):
        """Return maximum supported movie frame counts as a dictionary, e.g. {'video': 200}."""
        pass

    # ------------------------------------------------------------------------------------------------------------------
    # Camera capabilities
    # ------------------------------------------------------------------------------------------------------------------

    @abstractmethod
    def support_live_acquisition(self):
        """Return whether hardware live acquisition is supported.

        If not, the logic obtains the live images by repeatedly calling start_single_acquisition.
        """
        pass

    @abstractmethod
    def has_temp(self):
        """Return whether temperature control is available."""
        pass

    @abstractmethod
    def has_shutter(self):
        """Return whether the camera has a mechanical shutter."""
        pass

    @abstractmethod
    def has_gain(self):
        """Return whether gain control is available."""
        pass

    @abstractmethod
    def support_frame_transfer(self):
        """Return whether frame-transfer mode is supported."""
        pass

    # ------------------------------------------------------------------------------------------------------------------
    # Acquisition control
    # ------------------------------------------------------------------------------------------------------------------

    @abstractmethod
    def start_single_acquisition(self):
        """Acquire one image and return it as a 2D array (blocking). Return None if the acquisition failed."""
        pass

    @abstractmethod
    def start_live_acquisition(self):
        """Start continuous acquisition. Return True if the acquisition started."""
        pass

    @abstractmethod
    def stop_acquisition(self):
        """Stop the current acquisition (live, movie or single). Return True on success."""
        pass

    @abstractmethod
    def start_movie_acquisition(self, n_frames):
        """Start a fixed-length acquisition of n_frames images. Return True if the acquisition started.

        For a synchronized acquisition (see prepare_camera_for_multichannel_imaging) the camera is armed and the
        images are acquired when the trigger signals are received.
        """
        pass

    @abstractmethod
    def finish_movie_acquisition(self):
        """Finish and reset a movie acquisition. Return True on success."""
        pass

    def abort_movie_acquisition(self):
        """Abort a running movie acquisition (optional - the default is to stop the acquisition)."""
        self.stop_acquisition()

    @abstractmethod
    def wait_until_finished(self):
        """Wait until the current acquisition is finished."""
        pass

    # ------------------------------------------------------------------------------------------------------------------
    # Synchronized multichannel imaging
    # ------------------------------------------------------------------------------------------------------------------

    @abstractmethod
    def prepare_camera_for_multichannel_imaging(
        self,
        frames,
        exposure,
        gain,
        save_path,
        file_format,
    ):
        """Prepare camera for externally synchronized multichannel imaging.

        The acquisition itself is started afterwards with start_movie_acquisition(frames).
        """
        pass

    @abstractmethod
    def reset_camera_after_multichannel_imaging(self):
        """Restore normal camera state after synchronized imaging."""
        pass

    # ------------------------------------------------------------------------------------------------------------------
    # Image retrieval
    # ------------------------------------------------------------------------------------------------------------------

    @abstractmethod
    def get_most_recent_image(self, copy=True):
        """Return the most recently acquired image and the number of frames acquired so far, as a tuple
        (image, frame_count).

        image is a 2D array, or None if no frame is available (yet). The argument copy indicates whether the frame must
        be copied out of the camera buffer (only relevant for cameras whose frames are views of the buffer).
        """
        pass

    @abstractmethod
    def get_acquired_data(self):
        """Return all the images of the completed acquisition as an array [n_frames, height, width].

        Return None if the acquisition is not finished or if the data are not available.
        """
        pass
