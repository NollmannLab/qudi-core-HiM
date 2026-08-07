# -*- coding: utf-8 -*-
"""
Interface for generic camera hardware used by qudi-core-HiM.
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
        """Return sensor/image size as (width, height)."""
        pass

    @abstractmethod
    def set_exposure(self, exposure):
        """Set exposure time in seconds."""
        pass

    @abstractmethod
    def get_exposure(self):
        """Return exposure time in seconds."""
        pass

    @abstractmethod
    def set_gain(self, gain):
        """Set camera gain."""
        pass

    @abstractmethod
    def get_gain(self):
        """Return camera gain."""
        pass

    @abstractmethod
    def get_gain_limits(self):
        """Return lower and upper gain limits."""
        pass

    @abstractmethod
    def get_ready_state(self):
        """Return whether the camera is ready for acquisition."""
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
        """Set the active camera sensor region."""
        pass

    @abstractmethod
    def get_image_size(self):
        """Return current image size."""
        pass

    @abstractmethod
    def get_progress(self):
        """Return acquisition progress."""
        pass

    @abstractmethod
    def get_max_frames(self):
        """Return maximum supported movie frame counts."""
        pass

    # ------------------------------------------------------------------------------------------------------------------
    # Camera capabilities
    # ------------------------------------------------------------------------------------------------------------------

    @abstractmethod
    def support_live_acquisition(self):
        """Return whether hardware live acquisition is supported."""
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
        """Start acquisition of one image."""
        pass

    @abstractmethod
    def start_live_acquisition(self):
        """Start continuous acquisition."""
        pass

    @abstractmethod
    def stop_acquisition(self):
        """Stop the current acquisition."""
        pass

    @abstractmethod
    def start_movie_acquisition(self, n_frames):
        """Start a fixed-length movie acquisition."""
        pass

    @abstractmethod
    def finish_movie_acquisition(self):
        """Finish and reset a movie acquisition."""
        pass

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
        """Prepare camera for externally synchronized multichannel imaging."""
        pass

    @abstractmethod
    def reset_camera_after_multichannel_imaging(self):
        """Restore normal camera state after synchronized imaging."""
        pass

    # ------------------------------------------------------------------------------------------------------------------
    # Image retrieval
    # ------------------------------------------------------------------------------------------------------------------

    @abstractmethod
    def get_most_recent_image(self):
        """Return the most recently acquired image."""
        pass

    @abstractmethod
    def get_acquired_data(self):
        """Return data from the completed/current acquisition."""
        pass