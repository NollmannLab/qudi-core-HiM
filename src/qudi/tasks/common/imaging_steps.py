# -*- coding: utf-8 -*-
"""
qudi-core-HiM: imaging steps done at one ROI, per microscope, shared by the tasks that scan a list of
ROIs (ROI multicolour scan task, Hi-M task).

Each mixin implements the same three hooks, called by the task:
    _prepare_imaging()                 once, before the first ROI
    _image_roi(roi_name, file_name)    at one ROI, after the stage has arrived
    _end_imaging()                     in _cleanup (logs errors, never raises)
and sets the class attribute scan_stage_velocity (stage velocity during the scan, µm/s).

The mixins define no connector and no _setup / _run / _cleanup. The task using them sets
self._roi_logic, self._laser_logic and self._trigger_logic (None if not connected), self.directory
(data folder) and self.imaging_sequence, and provides self.log, self._check_interrupt() (ModuleTask)
and self._append_movie_name(file_name).

  - SDImagingMixin: spinning disk. Autofocus, z-stack and image acquisition are done by ZEN; the
    camera fire trigger drives the Lumencor shutter directly, so qudi does not switch the laser
    lines during the acquisition. qudi only runs the ZEN trigger handshakes (via TriggerLogic).
  - RAMMImagingMixin: placeholder, the RAMM imaging is not migrated yet.
  - DummyImagingMixin: no hardware, a fixed interruptible wait per ROI.

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

from time import monotonic, sleep


class SDImagingMixin:
    """Imaging at one ROI on the spinning disk, synchronized with ZEN over DAQ triggers (put it before
    the task base class in the bases).

    TriggerLogic addresses the trigger modules by their configured qudi module names:
    ``trigger_ZEN_start_block`` (output, start of a ZEN experiment block), ``trigger_ZEN_block_finished``
    (input, block done) and ``trigger_ZEN_ready`` (input, ZEN armed). The ready and done inputs keep
    the legacy OUT7_ZEN / OUT8_ZEN structure.

    _prepare_imaging: external trigger of the laser source on, intensities of the imaging sequence
        loaded, then wait for ZEN "ready" (no timeout: the user selects the experiment block and
        clicks "Start Experiment" in ZEN first).
    _image_roi: ZEN autofocus block (start trigger + wait for done), 2 s, laser source ready check,
        ZEN acquisition block (start trigger + wait for done), 2 s, file name appended to
        movie_name.txt. A ROI only counts as done once ZEN's "done" trigger has been seen for it.
    _end_imaging: lasers disabled, external trigger off, intensities reset to 0.
    """

    acquisition_timeout_s = 120.0  # max time to wait for ZEN's "done" trigger on one block
    poll_interval_s = 0.1
    scan_stage_velocity = {'x': 1000.0, 'y': 1000.0}  # µm/s during the scan, restored afterwards

    def _prepare_imaging(self) -> None:
        # laser source: external trigger (camera fire trigger) and line intensities
        self.num_laserlines = len(self.imaging_sequence)
        self._laser_logic.set_external_trigger(True)
        for wavelength, intensity in self.imaging_sequence:
            self._laser_logic.set_laser_line_intensity(int(wavelength), float(intensity))

        # handshake with ZEN
        self._check_interrupt()
        self.log.info('Waiting for ZEN to signal it is ready (select the right experiment block '
                      'and click "Start Experiment" in ZEN)...')
        self._wait_for_ready()
        self.log.info('ZEN is ready - starting the ROI scan.')

    def _image_roi(self, roi_name: str, file_name: str) -> None:
        """Two start/done handshakes with ZEN (autofocus, then acquisition). Raises on interrupt or
        on a timeout waiting for ZEN's "done" trigger.
        """
        self.log.info(f'Triggering ZEN autofocus for {roi_name}')
        self._trigger_logic.send_trigger('trigger_ZEN_start_block')
        self._wait_for_done()
        self.log.info(f'{roi_name}: autofocus confirmed done by ZEN.')

        sleep(2)
        # confirm the laser source is ready (e.g. wake the Celesta from standby) without enabling
        # any line: set_laser_enabled() / set_laser_disabled() would briefly switch every allowed
        # line on with the loaded intensities, an emission pulse unrelated to the readiness check.
        self._laser_logic.ensure_ready()

        self.log.info(f'Triggering ZEN acquisition for {roi_name}')
        self._trigger_logic.send_trigger('trigger_ZEN_start_block')
        self._wait_for_done()
        self.log.info(f'{roi_name}: acquisition confirmed done by ZEN.')

        sleep(2)
        self._append_movie_name(file_name)

    def _end_imaging(self) -> None:
        if self.imaging_sequence:
            try:
                self._laser_logic.set_laser_disabled()
                self._laser_logic.set_external_trigger(False)
                self._laser_logic.reset_laser_intensities()
            except Exception as e:
                self.log.error(f'Could not disable lasers: {e}')

    def _wait_for_ready(self) -> None:
        """Wait for ZEN's "ready" signal, a separate one-way channel that ZEN raises once armed
        (legacy OUT7_ZEN). qudi only polls it and never sends anything on it, so this cannot make
        ZEN start a spurious acquisition. No timeout; checks for an interrupt on every poll.
        """
        while True:
            self._check_interrupt()
            if self._trigger_logic.is_triggered('trigger_ZEN_ready'):
                return
            sleep(self.poll_interval_s)

    def _wait_for_done(self) -> None:
        """Poll ZEN's "done" signal until it appears, checking for an interrupt on every poll.

        Raises RuntimeError after acquisition_timeout_s: a ZEN synchronization problem, not an
        interrupt, so it is not reported as ModuleScriptInterrupted.
        """
        deadline = monotonic() + self.acquisition_timeout_s
        while True:
            self._check_interrupt()
            if self._trigger_logic.is_triggered('trigger_ZEN_block_finished'):
                return
            if monotonic() > deadline:
                raise RuntimeError(
                    f'Timed out after {self.acquisition_timeout_s} s waiting for ZEN to confirm it '
                    'is done. No "done" trigger was detected - check the ZEN synchronization.')
            sleep(self.poll_interval_s)


class RAMMImagingMixin:
    """Imaging at one ROI on the RAMM - PLACEHOLDER, not migrated yet: _prepare_imaging stops the
    task before any hardware call of the imaging.

    To do, following legacy/roi_multicolor_scan_task_RAMM_Celesta.py, for each ROI:
      1. axial correction: move the focus stage by dz (z difference between the ROIs, computed at
         start from the ROI list; not applied to the first ROI);
      2. autofocus: start the focus search and wait for its end; the first failure is logged, a
         second failure stops the experiment;
      3. piezo position correction when the piezo is close to the limits of its travel range;
      4. z-stack driven by the FPGA: camera started, for each plane the piezo is positioned, a DAQ
         start pulse is sent ('piezo ready'), then the FPGA 'acquisition done' input is waited for,
         with a timeout (number of laser lines * exposure + 0.1 s); piezo back to the start position;
      5. saving: tif (one file per laser line), npy, hdf5 or fits, with z_positions.yaml (target and
         actual z positions) and the metadata (template + acquisition / autofocus values).
    Before the first ROI the legacy task also checks the autofocus calibration and the free disk
    space, prepares the camera, the lasers and the FPGA, and loads the metadata template.
    """

    scan_stage_velocity = {'x': 1000.0, 'y': 1000.0}  # µm/s during the scan, restored afterwards

    _NOT_MIGRATED = ('ROI imaging on the RAMM is not migrated yet (focus logic, FPGA) - see '
                     'legacy/roi_multicolor_scan_task_RAMM_Celesta.py')

    def _prepare_imaging(self) -> None:
        raise NotImplementedError(self._NOT_MIGRATED)

    def _image_roi(self, roi_name: str, file_name: str) -> None:
        raise NotImplementedError(self._NOT_MIGRATED)

    def _end_imaging(self) -> None:
        pass


class DummyImagingMixin:
    """Imaging at one ROI without hardware, for testing: an interruptible wait of dummy_imaging_time_s,
    then the file name appended to movie_name.txt.
    """

    dummy_imaging_time_s = 2.0
    scan_stage_velocity = {'x': 1000.0, 'y': 1000.0}  # µm/s during the scan, restored afterwards

    _MAX_WAIT_STEP_S = 0.1  # maximum time between two interrupt checks while waiting

    def _prepare_imaging(self) -> None:
        pass

    def _image_roi(self, roi_name: str, file_name: str) -> None:
        self.log.info(f'{roi_name}: dummy imaging ({self.dummy_imaging_time_s:g} s)')
        deadline = monotonic() + float(self.dummy_imaging_time_s)
        while True:
            self._check_interrupt()
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            sleep(min(self._MAX_WAIT_STEP_S, remaining))
        self._append_movie_name(file_name)

    def _end_imaging(self) -> None:
        pass
