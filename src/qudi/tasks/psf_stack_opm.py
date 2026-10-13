# -*- coding: utf-8 -*-
"""
Author: JB Fiche - written for qudi-core-HiM with Claude code
Created: 2026-10-13

qudi-core-HiM task: acquire PSF z-stacks on the OPM microscope, for a series of galvo positions and
laser lines (first, software-timed version).

Purpose: characterise the OPM point-spread function across the light-sheet sweep. For every galvo
voltage, a z-stack is acquired around the focus position set by the user, one image per laser line
at each z plane.

Sequence
--------
    setup (before any hardware call):
        check the setup options (data_root, metadata_template) and the experiment parameters, build
        the galvo-voltage and z-offset lists, check them against the hardware (galvo limits, laser
        lines allowed, camera available, stage z axis), create the run folder
    then:
        lasers off; lock the GUI controls (laser, camera, filter, ROI / stage, tracking)
        select camera 'opm_camera_1', set the exposure
        x0, y0, z_focus = roi_logic.stage_position  (read once - focus manually before starting)
        lasers off, all intensities 0
    for i, V in enumerate(galvo voltages):            # galvo_start_v -> galvo_stop_v inclusive
        galvo_logic.set_voltage(V)                    # False -> stop the task (raise)
        create galvo_{i:03d}/, open one TIFF per laser_lines ENTRY (index k):
            {k:02d}_{wavelength}nm_{intensity:g}pct.tif
        for each z offset (-z_half_range_um -> +z_half_range_um inclusive, step z_step_um):
            roi_logic.move_stage((x0, y0, z_focus + offset)) and stage_wait_for_idle()  # False -> raise
            _acquire_plane(offset): for each entry k = (wavelength, intensity) in laser_lines, in order:
                check interrupt; reset intensities; set this line's intensity; lasers on;
                snap one image; lasers off; invalid image -> raise
            append each frame (uint16) to its entry's TIFF immediately (no stack kept in memory)
        close the TIFFs, write galvo_{i:03d}/metadata.txt, append a row to galvo_positions.csv
    cleanup (always; each step protected on its own; never raises; nothing if no hardware touched):
        lasers off + intensities reset; galvo to rest; stage back to (x0, y0, z_focus);
        close any open TIFF (partial files are kept); restore the previous camera and its exposure;
        finally unlock the GUI controls (each unlock protected on its own, always attempted)

The per-plane step is the single method _acquire_plane(z_offset) -> {entry index: frame}; a
DAQ-triggered version can replace it later without touching the loops.

Laser lines
-----------
    laser_lines is an ordered list of (wavelength nm, intensity %) entries. The same wavelength may
    appear several times, e.g. [(561, 10.0), (561, 50.0)] images the sample at two powers. Every
    entry gets its own TIFF; files, frames and messages are keyed by the entry's index, never by
    the wavelength.

GUI lock
--------
    While the task runs, the GUI controls of basic_imaging and of the ROI GUI (laser, camera,
    filter, stage / ROI, tracking) are greyed out, so that a click cannot interfere with the
    acquisition. The image display still updates at each snap. The cleanup unlocks them, also after
    an interrupt or an error. A failure before any hardware call locks nothing.

Folder layout
-------------
    <data_root>/<YYYY-MM-DD>/psf_<HHMMSS>/          (never overwritten: _1, _2, ... appended)
        galvo_positions.csv                          one row per COMPLETED galvo position
        timing_log.csv                               one row per timed step (timing_log_enabled)
        timing_summary.txt                           timing statistics per step (timing_log_enabled)
        galvo_000/  00_561nm_10pct.tif  [01_561nm_50pct.tif ...]  metadata.txt
                    (one TIFF per laser_lines entry: {index:02d}_{wavelength}nm_{intensity:g}pct.tif)
        galvo_001/  ...

Timing log (timing_log_enabled = True, default; settable through the config options)
----------
    Instrumentation only - the acquisition sequence, files, checks and cleanup are the same with or
    without it. Durations are measured with time.perf_counter() and written in ms (3 decimals).
    timing_log.csv - columns
        timestamp,galvo_index,galvo_voltage_V,z_index,z_offset_um,line_index,wavelength_nm,
        intensity_pct,step,duration_ms            (empty cells where a column does not apply)
        opened (append mode) before the first hardware action; one row per completed step, flushed
        immediately; os.fsync() after each plane, each galvo position and in cleanup; closed by the
        cleanup - nothing measured is lost if the task is interrupted or qudi crashes.
    steps
        once per run:          setup (from _run start to the first galvo move), cleanup (whole
                               _cleanup)
        per galvo position:    galvo_set, open_writers (folder + TIFF writers), close_writers,
                               write_metadata, write_csv_row
        per z plane:           stage_move_cmd, stage_wait_idle, plane_total (from just before
                               move_stage to the end of the last TIFF write), plane_other
                               (plane_total minus the plane's measured steps = Python / unmeasured
                               overhead, e.g. reading the previous image before the snap)
        per laser_lines entry: laser_set_intensity (reset + set), laser_enable, camera_snap
                               (start_single_acquisition only), camera_get_image (get_last_image +
                               validity check + uint16 conversion), laser_disable, tiff_write
    timing_summary.txt - written at the end of the run, or by the cleanup if the run did not finish
        (marked "run interrupted" / "run stopped by an error"): run parameters (galvo positions,
        planes, lines, images, exposure set and read back, image size), per step count / mean /
        median / min / max / total (s) / % of the total run time, snap overhead per image (mean
        camera_snap - exposure), total run time, time per image, images per second. The same table
        is logged at info level. A progress line (mean plane_total, time remaining) is logged after
        each galvo position.
    If the timing file cannot be written, ONE error is logged and the acquisition continues without
    timing - timing never stops an acquisition.

Config example (logic: task_runner: options: module_tasks:)
--------------
    psf_stack:
      module.Class: 'qudi.tasks.psf_stack_opm.PsfStackTask'
      connect:
        camera_logic: camera_logic
        laser_logic: laser_control_logic
        galvo_logic: galvo_logic
        roi_logic: roi_logic
        filter_wheel_logic: filter_wheel_logic
      options:
        data_root: 'D:\\DATA'
        metadata_template: 'C:\\path\\to\\custom_metadata_templates\\OPM_setup.cfg'
        timing_log_enabled: True      # optional, default True

Experiment parameters are class attributes (see "EXPERIMENT PARAMETERS - edit here" below); the
setup-specific paths come from the config options (qudi-core-HiM task runner).

Known limits of this first version
----------------------------------
    - software-timed: every move, laser switch and snap is a separate software call (slow);
    - the lasers stay on during the camera overhead of each snap, not only during the exposure;
    - one camera only (opm_camera_1);
    - stage positions are used in the stage units returned by roi_logic (µm on the ASI Tiger).

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------

Modified for qudi-core-HiM (2026-10-13, Modified with Claude code): new file - PsfStackTask, a
  software-timed PSF z-stack acquisition on the OPM over galvo positions and laser lines, writing
  one TIFF per galvo position and laser line, a metadata.txt per galvo position and a
  galvo_positions.csv per run.
Modified for qudi-core-HiM (2026-10-13, Modified with Claude code): the same laser line may appear
  several times in laser_lines (files, frames and messages keyed by the entry index, file names
  {index:02d}_{wavelength}nm_{intensity:g}pct.tif); the GUI controls (laser, camera, filter,
  ROI / stage, tracking) are locked during the run and unlocked by the cleanup.
Modified for qudi-core-HiM (2026-10-13, Modified with Claude code): timing instrumentation -
  timing_log.csv (one row per timed step, saved while acquiring) and timing_summary.txt in the run
  folder, a progress line per galvo position; class attribute timing_log_enabled (config option).
  The acquisition itself is unchanged.
"""

import copy
import csv
import os
from contextlib import contextmanager
from datetime import datetime
from time import perf_counter
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np
from ruamel.yaml import YAML
from tifffile import TiffWriter

from qudi.core.connector import Connector
from qudi.core.scripting.moduletask import ModuleTask


class _TimingLog:
    """timing_log.csv writer + in-memory durations for the summary. Never raises: the first I/O
    error is logged once and switches timing off (self.ok = False) for the rest of the run.
    """

    COLUMNS = ['timestamp', 'galvo_index', 'galvo_voltage_V', 'z_index', 'z_offset_um',
               'line_index', 'wavelength_nm', 'intensity_pct', 'step', 'duration_ms']

    def __init__(self, path: str, log) -> None:
        self.path = path
        self.log = log
        self.ok = True
        self.durations: Dict[str, List[float]] = {}  # step -> durations in ms
        self._file = None
        self._writer = None
        try:
            self._file = self._open_file(path)
            self._writer = csv.writer(self._file)
            if self._file.tell() == 0:
                self._write(self.COLUMNS)
        except Exception as err:
            self._fail(err)

    @staticmethod
    def _open_file(path: str):
        return open(path, 'a', newline='', encoding='utf-8')

    def _write(self, row: list) -> None:
        self._writer.writerow(row)
        self._file.flush()

    def _fail(self, err: Exception) -> None:
        if self.ok:
            self.log.error(f'Timing log "{self.path}" cannot be written ({err}) - timing switched '
                           f'off, the acquisition continues.')
        self.ok = False
        file, self._file = self._file, None
        if file is not None:
            try:
                file.close()
            except Exception:
                pass

    def record(self, step: str, duration_s: float, ids: dict) -> None:
        if not self.ok:
            return
        ms = round(duration_s * 1e3, 3)
        try:
            self._write([datetime.now().isoformat(timespec='milliseconds')]
                        + [ids.get(c, '') for c in self.COLUMNS[1:8]] + [step, f'{ms:.3f}'])
        except Exception as err:
            self._fail(err)
            return
        self.durations.setdefault(step, []).append(ms)

    def sync(self) -> None:
        if not self.ok or self._file is None:
            return
        try:
            self._file.flush()
            os.fsync(self._file.fileno())
        except Exception as err:
            self._fail(err)

    def close(self) -> None:
        self.sync()
        file, self._file = self._file, None
        if file is not None:
            try:
                file.close()
            except Exception as err:
                self.log.error(f'Could not close the timing log "{self.path}": {err}')


class PsfStackTask(ModuleTask):
    """PSF z-stacks on the OPM for a series of galvo voltages and laser lines (software-timed).

    See the module docstring for the sequence, the folder layout and the config example. The task has
    no call parameters: experiment parameters are the class attributes below, the setup paths
    (data_root, metadata_template) come from the task's "options:" in the config.
    """

    camera_logic = Connector(interface='CameraLogic')
    laser_logic = Connector(interface='LaserControlLogic')
    galvo_logic = Connector(interface='GalvoLogic')
    roi_logic = Connector(interface='RoiLogic')
    filter_wheel_logic = Connector(interface='FilterWheelLogic')

    # ==========================================================================================
    # EXPERIMENT PARAMETERS - edit here
    # ==========================================================================================
    galvo_start_v = 1.0         # V, first galvo voltage
    galvo_stop_v = 2.0          # V, last galvo voltage (included)
    galvo_step_v = 0.1          # V, galvo voltage step
    z_half_range_um = 5.0       # µm, z-stack from z_focus - z_half_range_um to z_focus + z_half_range_um
    z_step_um = 0.2             # µm, z step
    laser_lines = [(561, 15.0)]  # [(wavelength nm, intensity %), ...] - fired in this order at each z;
    #                             the same wavelength may repeat, e.g. [(561, 10.0), (561, 50.0)]
    exposure_s = 0.05           # s, camera exposure time
    camera_name = 'opm_camera_1'  # camera used (selected at start, previous camera restored at the end)
    timing_log_enabled = True   # write timing_log.csv / timing_summary.txt (also a config option)

    # ==========================================================================================
    # SETUP OPTIONS - set in the config (task options), never hard-coded here
    # ==========================================================================================
    data_root = None            # root data folder, e.g. 'D:\DATA'
    metadata_template = None    # path to the OPM metadata template (YAML), e.g. .../OPM_setup.cfg

    _UNSET = (None, '', 'TO FILL')
    _ROUND_DECIMALS = 4
    _STEP_ORDER = ('setup', 'galvo_set', 'open_writers', 'stage_move_cmd', 'stage_wait_idle',
                   'laser_set_intensity', 'laser_enable', 'camera_snap', 'camera_get_image',
                   'laser_disable', 'tiff_write', 'plane_other', 'plane_total', 'close_writers',
                   'write_metadata', 'write_csv_row', 'cleanup')

    # ------------------------------------------------------------------------------------------
    # ModuleTask
    # ------------------------------------------------------------------------------------------
    def _setup(self) -> None:
        # State used by _cleanup - set first, so that cleanup works even if a connector fails below
        self._hardware_touched = False
        self._writers: Dict[int, TiffWriter] = {}
        self._prev_camera: Optional[str] = None
        self._prev_exposure: Optional[float] = None
        self._focus: Optional[Tuple[float, float, float]] = None
        self._run_folder: Optional[str] = None
        self._completed = 0
        self._lines: List[Tuple[int, float]] = []
        self._line_names: List[str] = []
        # timing instrumentation
        self._tlog: Optional[_TimingLog] = None
        self._t_run_start: Optional[float] = None
        self._plane_acc = 0.0
        self._run_finished = False
        self._timing_info: dict = {}

        self._camera = self.camera_logic()
        self._laser = self.laser_logic()
        self._galvo = self.galvo_logic()
        self._roi = self.roi_logic()
        self._filter = self.filter_wheel_logic()

    def _run(self) -> dict:
        self._t_run_start = perf_counter()
        # ---- checks that do not touch any hardware ------------------------------------------
        self._check_setup_options()
        template = self._load_metadata_template()
        voltages = self._float_steps(self.galvo_start_v, self.galvo_stop_v, self.galvo_step_v,
                                     'galvo')
        z_offsets = self._float_steps(-self.z_half_range_um, self.z_half_range_um, self.z_step_um,
                                      'z')
        lines = self._checked_laser_lines()
        self._validate_against_setup(voltages, lines)
        self._run_folder = self._make_run_folder()
        csv_path = os.path.join(self._run_folder, 'galvo_positions.csv')
        with open(csv_path, 'w', newline='') as f:
            csv.writer(f).writerow(['folder', 'galvo_voltage_V', 'n_z_planes', 'laser_lines_nm',
                                    'completed', 'timestamp'])
        if self.timing_log_enabled:  # opened before the first hardware action
            self._tlog = _TimingLog(os.path.join(self._run_folder, 'timing_log.csv'), self.log)
        self._check_interrupt()

        # ---- hardware set-up -----------------------------------------------------------------
        self._hardware_touched = True
        self._laser.set_laser_disabled()  # lasers off first
        self._lock_gui()
        self._prev_camera = self._camera.get_active_camera()
        self._prev_exposure = self._camera.get_exposure()
        if not self._camera.select_camera(self.camera_name):
            raise RuntimeError(f'Could not select camera "{self.camera_name}" - see the log.')
        self._camera.set_exposure(self.exposure_s)
        exposure = self._camera.get_exposure()
        x0, y0, z_focus = (float(v) for v in self._roi.stage_position)
        self._focus = (x0, y0, z_focus)
        self._laser.set_laser_disabled()
        self._laser.reset_laser_intensities()

        n_images = len(voltages) * len(z_offsets) * len(lines)
        width, height = self._camera.get_size()
        size_gb = n_images * int(width) * int(height) * 2 / 1e9
        self._timing_info = {'galvo positions': len(voltages), 'z planes per position':
                             len(z_offsets), 'laser_lines entries': len(lines),
                             'images planned': n_images, 'exposure set (s)': self.exposure_s,
                             'exposure read back (s)': exposure,
                             'image size (px)': f'{width} x {height}'}
        self.log.info(f'PSF stack: {len(voltages)} galvo positions x {len(z_offsets)} z planes x '
                      f'{len(lines)} laser line(s) = {n_images} images of {width}x{height} px '
                      f'(~{size_gb:.2f} GB), exposure {exposure} s, focus at '
                      f'(x={x0}, y={y0}, z={z_focus}); saving to {self._run_folder}')

        # ---- acquisition ---------------------------------------------------------------------
        t_acq_start = None
        for index, voltage in enumerate(voltages):
            self._check_interrupt()
            gids = {'galvo_index': index, 'galvo_voltage_V': voltage}
            if index == 0:
                self._record('setup', perf_counter() - self._t_run_start, {})
                t_acq_start = perf_counter()
            with self._timed('galvo_set', gids):
                ok = self._galvo.set_voltage(voltage)
            if not ok:
                raise RuntimeError(f'Galvo refused or failed voltage {voltage} V (position {index}) '
                                   f'- see the log. Task stopped.')
            with self._timed('open_writers', gids):
                folder = self._unique_folder(os.path.join(self._run_folder, f'galvo_{index:03d}'))
                os.makedirs(folder)
                self._writers = {k: TiffWriter(os.path.join(folder, f'{name}.tif'))
                                 for k, name in enumerate(self._line_names)}
            self.log.info(f'Galvo position {index + 1}/{len(voltages)}: {voltage} V -> {folder}')

            for z_index, z_offset in enumerate(z_offsets):
                self._check_interrupt()
                zids = dict(gids, z_index=z_index, z_offset_um=z_offset)
                target = (x0, y0, round(z_focus + z_offset, self._ROUND_DECIMALS))
                self._plane_acc = 0.0
                t_plane = perf_counter()
                with self._timed('stage_move_cmd', zids, plane=True):
                    ok = self._roi.move_stage(target)
                if not ok:
                    raise RuntimeError(f'Stage refused the move to {target} - task stopped.')
                with self._timed('stage_wait_idle', zids, plane=True):
                    ok = self._roi.stage_wait_for_idle()
                if not ok:
                    raise RuntimeError(f'Stage did not reach {target} (timeout or communication '
                                       f'error) - task stopped.')
                frames = self._acquire_plane(z_offset, zids)
                for k in range(len(lines)):
                    with self._timed('tiff_write', self._line_ids(zids, k), plane=True):
                        self._writers[k].write(frames[k], contiguous=True)
                if self._timing_on():
                    plane_total = perf_counter() - t_plane
                    self._record('plane_total', plane_total, zids)
                    self._record('plane_other', max(plane_total - self._plane_acc, 0.0), zids)
                    self._tlog.sync()

            with self._timed('close_writers', gids):
                self._close_writers()
            with self._timed('write_metadata', gids):
                self._write_metadata(template, folder, index, voltage, z_focus, z_offsets, lines,
                                     exposure)
            with self._timed('write_csv_row', gids):
                with open(csv_path, 'a', newline='') as f:
                    csv.writer(f).writerow([os.path.basename(folder), voltage, len(z_offsets),
                                            ';'.join(f'{wl}@{p:g}' for wl, p in lines), True,
                                            datetime.now().isoformat(timespec='seconds')])
                    f.flush()
            self._completed += 1
            if self._timing_on():
                self._tlog.sync()
                self._log_progress(index, len(voltages), perf_counter() - t_acq_start)

        self._run_finished = True
        if self._timing_on():
            self._write_timing_summary('completed')
        return {'run_folder': self._run_folder, 'completed_galvo_positions': self._completed}

    def _cleanup(self) -> None:
        """Safe state (_restore_safe_state), then close the timing log - never raises."""
        t0 = perf_counter()
        try:
            self._restore_safe_state()
        finally:
            self._finish_timing(perf_counter() - t0)

    def _finish_timing(self, cleanup_s: float) -> None:
        """Record the cleanup, write the summary if the run did not finish, fsync and close the
        timing log. Every step protected, never raises."""
        tlog = getattr(self, '_tlog', None)
        if tlog is None:
            return
        try:
            self._record('cleanup', cleanup_s, {})
            if not getattr(self, '_run_finished', False) and tlog.ok:
                status = 'run interrupted' if self.interrupted else 'run stopped by an error'
                self._write_timing_summary(status)
        except Exception as err:
            self.log.error(f'Cleanup: could not write the timing summary: {err}')
        try:
            tlog.close()
        except Exception as err:
            self.log.error(f'Cleanup: could not close the timing log: {err}')

    def _restore_safe_state(self) -> None:
        """Safe state - every step protected on its own, never raises."""
        if not getattr(self, '_hardware_touched', False):
            self._close_writers()
            self.log.info('PSF stack cleanup: no hardware was touched, nothing to restore.')
            return
        self.log.info('PSF stack cleanup: restoring a safe state.')
        try:
            self._laser.set_laser_disabled()
            self._laser.reset_laser_intensities()
        except Exception as err:
            self.log.error(f'Cleanup: could not switch the lasers off: {err}')
        try:
            if not self._galvo.go_to_rest():
                self.log.error('Cleanup: the galvo did not go to rest - see the log.')
        except Exception as err:
            self.log.error(f'Cleanup: could not move the galvo to rest: {err}')
        try:
            if self._focus is not None:
                if not (self._roi.move_stage(self._focus) and self._roi.stage_wait_for_idle()):
                    self.log.error(f'Cleanup: the stage did not return to the focus {self._focus}.')
        except Exception as err:
            self.log.error(f'Cleanup: could not move the stage back to the focus: {err}')
        self._close_writers()
        try:
            if self._prev_camera is not None:
                if self._camera.get_active_camera() != self._prev_camera:
                    self._camera.select_camera(self._prev_camera)
                if self._prev_exposure is not None:
                    self._camera.set_exposure(self._prev_exposure)
        except Exception as err:
            self.log.error(f'Cleanup: could not restore the previous camera / exposure: {err}')
        self._unlock_gui()
        self.log.info(f'PSF stack cleanup finished ({self._completed} galvo position(s) completed'
                      f'{", data in " + self._run_folder if self._run_folder else ""}).')

    # ------------------------------------------------------------------------------------------
    # GUI lock
    # ------------------------------------------------------------------------------------------
    def _lock_gui(self) -> None:
        """Grey out the GUI controls that could interfere with the acquisition (the display still
        updates). Called in _run after _hardware_touched is set; an error stops the task, and the
        cleanup then unlocks everything."""
        self._laser.disable_laser_actions()
        self._camera.disable_camera_actions()
        self._filter.disable_filter_actions()
        self._roi.disable_tracking_mode()
        self._roi.disable_roi_actions()

    def _unlock_gui(self) -> None:
        """Re-enable the GUI controls - every call protected on its own, never raises."""
        steps = (('laser', lambda: self._laser.enable_laser_actions()),
                 ('camera', lambda: self._camera.enable_camera_actions()),
                 ('filter', lambda: self._filter.enable_filter_actions()),
                 ('tracking', lambda: self._roi.enable_tracking_mode()),
                 ('ROI / stage', lambda: self._roi.enable_roi_actions()))
        for what, step in steps:
            try:
                step()
            except Exception as err:
                self.log.error(f'Cleanup: could not re-enable the {what} GUI controls: {err}')

    # ------------------------------------------------------------------------------------------
    # Per-plane acquisition - the one step a DAQ-triggered version will replace
    # ------------------------------------------------------------------------------------------
    def _acquire_plane(self, z_offset: float, zids: Optional[dict] = None) -> Dict[int, np.ndarray]:
        """Acquire one image per laser line at the current z plane, in the laser_lines order.

        Returns {entry index in laser_lines: uint16 frame}. Checks for an interrupt before every image; the lasers
        are switched off after each image, also if the snap fails. zids: timing-log ids of the plane.
        """
        zids = zids or {}
        frames = {}
        for k, (wavelength, intensity) in enumerate(self._lines):
            self._check_interrupt()
            ids = self._line_ids(zids, k)
            with self._timed('laser_set_intensity', ids, plane=True):
                self._laser.reset_laser_intensities()
                self._laser.set_laser_line_intensity(wavelength, intensity)
            previous = self._camera.get_last_image()  # unmeasured -> plane_other
            with self._timed('laser_enable', ids, plane=True):
                self._laser.set_laser_enabled()
            try:
                with self._timed('camera_snap', ids, plane=True):
                    self._camera.start_single_acquisition()
                t_get = perf_counter()
                frame = self._camera.get_last_image()
                get_s = perf_counter() - t_get
            finally:
                with self._timed('laser_disable', ids, plane=True):
                    self._laser.set_laser_disabled()
            t_check = perf_counter()
            # camera_logic keeps the previous image when a snap fails: a missing OR unchanged
            # image is an acquisition failure.
            if frame is None or np.size(frame) == 0 or frame is previous:
                raise RuntimeError(f'No new image from the camera at z offset {z_offset} µm, '
                                   f'{self._line_names[k]} - task stopped.')
            frames[k] = np.asarray(frame).astype(np.uint16, copy=False)
            if self._timing_on():  # get_last_image + validity check + uint16 conversion
                self._record('camera_get_image', get_s + perf_counter() - t_check, ids, plane=True)
        return frames

    # ------------------------------------------------------------------------------------------
    # Timing instrumentation (never raises, never changes the acquisition)
    # ------------------------------------------------------------------------------------------
    def _timing_on(self) -> bool:
        return self._tlog is not None and self._tlog.ok

    def _line_ids(self, zids: dict, k: int) -> dict:
        wavelength, intensity = self._lines[k]
        return dict(zids, line_index=k, wavelength_nm=wavelength, intensity_pct=f'{intensity:g}')

    def _record(self, step: str, duration_s: float, ids: dict, plane: bool = False) -> None:
        if plane:
            self._plane_acc += duration_s
        if self._tlog is not None:
            self._tlog.record(step, duration_s, ids)

    @contextmanager
    def _timed(self, step: str, ids: dict, plane: bool = False) -> Iterator[None]:
        """Time the block; a row is written only if the block completes (no exception)."""
        if not self._timing_on():
            yield
            return
        t0 = perf_counter()
        yield
        self._record(step, perf_counter() - t0, ids, plane)

    def _log_progress(self, index: int, n_positions: int, elapsed_s: float) -> None:
        planes = self._tlog.durations.get('plane_total', [])
        mean_plane = float(np.mean(planes)) if planes else float('nan')
        done = index + 1
        remaining = elapsed_s / done * (n_positions - done)
        self.log.info(f'PSF stack: galvo position {done}/{n_positions} done - mean plane_total '
                      f'{mean_plane:.1f} ms - estimated time remaining {remaining:.1f} s')

    def _timing_summary_text(self, status: str) -> str:
        total_s = perf_counter() - self._t_run_start
        durations = self._tlog.durations
        steps = [s for s in self._STEP_ORDER if s in durations]
        steps += sorted(s for s in durations if s not in steps)
        lines = [f'PSF stack timing summary - {status}',
                 f'run folder: {self._run_folder}',
                 f'written: {datetime.now().isoformat(timespec="seconds")}', '',
                 'Run parameters']
        for key, value in self._timing_info.items():
            lines.append(f'  {key}: {value}')
        lines.append(f'  galvo positions completed: {self._completed}')
        lines += ['', f'{"step":<20}{"count":>8}{"mean_ms":>12}{"median_ms":>12}{"min_ms":>12}'
                      f'{"max_ms":>12}{"total_s":>12}{"%_run":>8}']
        for step in steps:
            d = np.asarray(durations[step], dtype=float)
            lines.append(f'{step:<20}{d.size:>8d}{d.mean():>12.3f}{np.median(d):>12.3f}'
                         f'{d.min():>12.3f}{d.max():>12.3f}{d.sum() / 1e3:>12.3f}'
                         f'{100 * d.sum() / 1e3 / total_s:>8.1f}')
        lines.append('  (plane_total contains the per-plane steps; setup/cleanup are separate)')
        n_img = len(durations.get('camera_snap', []))
        lines.append('')
        exposure = self._timing_info.get('exposure read back (s)')
        if n_img and exposure is not None:
            overhead = float(np.mean(durations['camera_snap'])) - float(exposure) * 1e3
            lines.append(f'snap overhead per image (ms): {overhead:.3f}  (mean camera_snap - '
                         f'exposure read back {float(exposure) * 1e3:.3f} ms)')
        lines.append(f'total run time (s): {total_s:.3f}  (from _run start'
                     f'{"" if status == "completed" else " to the cleanup end"})')
        lines.append(f'images acquired: {n_img}')
        if n_img:
            lines.append(f'time per image (ms): {total_s * 1e3 / n_img:.3f}')
            lines.append(f'images per second: {n_img / total_s:.3f}')
        return '\n'.join(lines) + '\n'

    def _write_timing_summary(self, status: str) -> None:
        """Write timing_summary.txt and log the same table - errors logged, never raises."""
        try:
            text = self._timing_summary_text(status)
            path = os.path.join(self._run_folder, 'timing_summary.txt')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            self.log.info('\n' + text)
        except Exception as err:
            self.log.error(f'Could not write the timing summary: {err}')

    # ------------------------------------------------------------------------------------------
    # Checks (no hardware call)
    # ------------------------------------------------------------------------------------------
    def _check_setup_options(self) -> None:
        name = type(self).__name__
        for option in ('data_root', 'metadata_template'):
            if getattr(self, option) in self._UNSET:
                raise RuntimeError(f'{option} not set for task {name} — add `options: {option}: ...` '
                                   f'to this task\'s entry in the config file')
        if not os.path.isdir(self.data_root):
            raise RuntimeError(f'data_root "{self.data_root}" is not an existing folder.')
        if not os.path.isfile(self.metadata_template):
            raise RuntimeError(f'metadata_template "{self.metadata_template}" is not an existing '
                               f'file.')

    def _load_metadata_template(self) -> dict:
        try:
            with open(self.metadata_template, 'r', encoding='utf-8') as f:
                template = YAML().load(f)
        except Exception as err:
            raise RuntimeError(f'Could not read metadata_template "{self.metadata_template}": '
                               f'{err}') from err
        return dict(template or {})

    def _float_steps(self, start: float, stop: float, step: float, what: str) -> List[float]:
        """start -> stop inclusive with a float step, stop included exactly once."""
        start, stop, step = float(start), float(stop), float(step)
        if not step > 0:
            raise ValueError(f'{what} step must be > 0 (got {step}).')
        if not start <= stop:
            raise ValueError(f'{what} start ({start}) must be <= stop ({stop}).')
        values = np.round(np.arange(start, stop + step / 2, step), self._ROUND_DECIMALS)
        return [float(v) for v in values]

    def _checked_laser_lines(self) -> List[Tuple[int, float]]:
        if not self.laser_lines:
            raise ValueError('laser_lines is empty - give at least one (wavelength nm, intensity %).')
        lines = []
        for item in self.laser_lines:
            try:
                wavelength, intensity = int(item[0]), float(item[1])
            except (TypeError, ValueError, IndexError) as err:
                raise ValueError(f'Invalid laser line {item!r}: expected (wavelength nm, '
                                 f'intensity %).') from err
            if not 0 <= intensity <= 100:
                raise ValueError(f'Laser intensity {intensity} % for {wavelength} nm is outside '
                                 f'[0, 100] %.')
            lines.append((wavelength, intensity))
        # The same wavelength may appear several times (e.g. two powers): entries are keyed by index
        self._lines = lines
        self._line_names = [self._line_name(k, wl, p) for k, (wl, p) in enumerate(lines)]
        return lines

    @staticmethod
    def _line_name(index: int, wavelength: int, intensity: float) -> str:
        """File stem / label of a laser_lines entry, e.g. '00_561nm_10pct'."""
        return f'{index:02d}_{wavelength}nm_{intensity:g}pct'

    def _validate_against_setup(self, voltages: List[float],
                                lines: List[Tuple[int, float]]) -> None:
        """Read-only checks against the connected logic modules - nothing is moved or switched."""
        low, high = (float(v) for v in self._galvo.get_limits())
        outside = [v for v in voltages if not low <= v <= high]
        if outside:
            raise ValueError(f'Galvo voltage(s) {outside} outside the galvo limits [{low}, {high}] V.')

        state = self._laser.laser_state
        for wavelength in dict.fromkeys(wl for wl, _ in lines):  # each distinct wavelength once
            if wavelength not in state:
                raise ValueError(f'Laser line {wavelength} nm does not exist on this setup '
                                 f'(available: {sorted(state)}).')
            if not state[wavelength].get('allowed', False):
                raise ValueError(f'Laser line {wavelength} nm is not allowed with the current '
                                 f'dichroic / filter.')

        cameras = list(self._camera.get_available_cameras())
        if self.camera_name not in cameras:
            raise ValueError(f'Camera "{self.camera_name}" not available (available: {cameras}).')
        if getattr(self._camera, 'live_enabled', False):
            raise RuntimeError('Camera live mode is running - stop it before starting the task.')

        # Same test as roi_logic.move_stage: without a z axis it ignores z and still returns True
        z_label = getattr(self._roi, '_z_axis_label', None)
        stage_axes = getattr(self._roi, '_stage_axis_labels', None)
        if z_label is None or stage_axes is None:
            raise RuntimeError('Cannot check the stage z axis on roi_logic.')
        if z_label not in stage_axes:
            raise ValueError(f'The stage has no z axis "{z_label}" (axes: {list(stage_axes)}) - '
                             f'a z-stack is impossible.')

    # ------------------------------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------------------------------
    @staticmethod
    def _unique_folder(path: str) -> str:
        """path, or path_1, path_2, ... - never an existing folder."""
        candidate, n = path, 0
        while os.path.exists(candidate):
            n += 1
            candidate = f'{path}_{n}'
        return candidate

    def _make_run_folder(self) -> str:
        now = datetime.now()
        day_folder = os.path.join(self.data_root, now.strftime('%Y-%m-%d'))
        folder = self._unique_folder(os.path.join(day_folder, now.strftime('psf_%H%M%S')))
        os.makedirs(folder)
        return folder

    def _close_writers(self) -> None:
        names = getattr(self, '_line_names', [])
        for k, writer in list(getattr(self, '_writers', {}).items()):
            try:
                writer.close()
            except Exception as err:
                name = f'{names[k]}.tif' if k < len(names) else f'entry {k}'
                self.log.error(f'Could not close the TIFF file {name}: {err}')
        self._writers = {}

    @staticmethod
    def _set_field(metadata: dict, section: str, key: str, value) -> None:
        """Set metadata[section][key] for the template layout (a section is a list of one-key
        mappings, or a mapping); the key is added if missing. Other fields are left untouched.
        """
        content = metadata.get(section)
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and key in item:
                    item[key] = value
                    return
            content.append({key: value})
        elif isinstance(content, dict):
            content[key] = value
        else:
            metadata[section] = [{key: value}]

    def _write_metadata(self, template: dict, folder: str, index: int, voltage: float,
                        z_focus: float, z_offsets: List[float], lines: List[Tuple[int, float]],
                        exposure: float) -> None:
        metadata = copy.deepcopy(template)
        metadata['Time'] = datetime.now().strftime('%m-%d-%Y, %H:%M:%S')
        acquisition = {
            'number_frames': len(z_offsets),
            'exposure_time_(s)': exposure,
            'laser_lines': [wl for wl, _ in lines],
            'laser_power_(%)': [p for _, p in lines],
            'number_z_planes': len(z_offsets),
            'distance_z_planes_(µm)': float(self.z_step_um),
        }
        for key, value in acquisition.items():
            self._set_field(metadata, 'Acquisition', key, value)
        metadata['PSF'] = [
            {'galvo_voltage_(V)': voltage},
            {'galvo_index': index},
            {'z_focus_(µm)': z_focus},
            {'z_offsets_(µm)': list(z_offsets)},
            {'laser_order': [f'{name}.tif' for name in self._line_names]},
        ]
        with open(os.path.join(folder, 'metadata.txt'), 'w', encoding='utf-8') as f:
            YAML().dump(metadata, f)
