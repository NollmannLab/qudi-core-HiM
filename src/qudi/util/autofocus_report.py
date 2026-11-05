# -*- coding: utf-8 -*-
"""
Summary of the autofocus scores of Hi-M runs on the spinning disk: ROI x probe heatmap and CSV, plus the drift of
the autofocus images per ROI and cycle when the run has autofocus_scores.csv (qudi-core Hi-M task).

Works on one run (one metadata folder) or on several past experiments found under a folder, including runs of the
legacy qudi-HiM software. No GUI backend: the figures are built with matplotlib.figure.Figure (no pyplot, no
window), so the module runs in a qudi task thread and on a computer without a display.

Inputs of one run (metadata folder):
  - HiM_parameters.yml: ROI names ('4- ROIs'), probes ('2- fluidic parameters' -> 'probes') and
    correlation_threshold ('1- global parameters'), when present;
  - correlation.npy: cycles x ROIs (qudi-core task) or probes x ROIs (legacy), transposed to ROIs x probes when
    needed; NaN = check not done (aborted run);
  - autofocus_scores.csv (qudi-core task; columns cycle, RT, roi, score, shift_y_px, shift_x_px, passed), when
    present: probe label of each cycle (RT column) and drift (shift_y_px / shift_x_px).
Probe labels: the rows of correlation.npy follow the cycle order. With autofocus_scores.csv, cycle -> RT;
otherwise (legacy) the probes sorted by their key (tube number), a note says that this order is assumed.

  - report_run(metadata_folder, threshold=None, vmin=0.5, vmax=1.0, log=None) -> list of written paths, in the
    metadata folder: autofocus_correlation_heatmap.png, ROI_probe_autofocus_summary.csv and, with
    autofocus_scores.csv, autofocus_drift.png.
  - summarize_folder(root_folder, threshold=None, vmin=0.5, vmax=1.0, log=None) -> list of written paths: every
    metadata folder under root_folder with HiM_parameters.yml and correlation.npy (same ROIs required), probes
    concatenated as "<probe> | <experiment folder>", global heatmap and CSV in root_folder.
threshold: correlation_threshold of the run when present, otherwise DEFAULT_THRESHOLD; ROIs whose mean score is
below it are highlighted in red. vmin / vmax: colour scale of the score.

Usage examples:

    # one run (metadata folder of a Hi-M experiment)
    python -m qudi.util.autofocus_report /data/2026-11-05/2026-11-05_HiM_sample1/metadata

    # every run found under an experiment folder, threshold 0.6, colour scale 0.3 - 1
    python -m qudi.util.autofocus_report /mnt/aguila/rawData_2026/Experiment_231 --all --threshold 0.6 --vmin 0.3

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

__all__ = ['DEFAULT_THRESHOLD', 'HEATMAP_NAME', 'SUMMARY_NAME', 'DRIFT_NAME', 'load_run', 'report_run',
           'summarize_folder', 'main']

import argparse
import csv
import logging
import os
import sys
from pathlib import Path

import numpy as np
import yaml
from matplotlib.figure import Figure

DEFAULT_THRESHOLD = 0.7   # threshold when the run has no correlation_threshold
HEATMAP_NAME = 'autofocus_correlation_heatmap.png'
SUMMARY_NAME = 'ROI_probe_autofocus_summary.csv'
DRIFT_NAME = 'autofocus_drift.png'
PARAMETERS_NAME = 'HiM_parameters.yml'
CORRELATION_NAME = 'correlation.npy'
SCORES_NAME = 'autofocus_scores.csv'
MAX_PROBE_LABELS = 80     # probe labels shown on the heatmap up to this number of columns

_log = logging.getLogger(__name__)


# ======================================================================================================================
# Reading one run
# ======================================================================================================================

def _read_scores_csv(path) -> list:
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def load_run(metadata_folder, log=None) -> dict:
    """Content of one metadata folder: roi_names, probe_names (cycle order), corr (ROIs x probes), threshold (None
    when the run has none), scores (rows of autofocus_scores.csv or None), experiment_folder, metadata_folder."""
    log = log or _log
    folder = Path(metadata_folder)
    with open(folder / PARAMETERS_NAME, 'r', encoding='utf-8') as f:
        params = yaml.safe_load(f) or {}
    roi_names = list((params.get('4- ROIs') or {}).keys())
    probes = (params.get('2- fluidic parameters') or {}).get('probes') or {}
    threshold = (params.get('1- global parameters') or {}).get('correlation_threshold')
    corr = np.asarray(np.load(folder / CORRELATION_NAME), dtype=float)
    scores = _read_scores_csv(folder / SCORES_NAME) if (folder / SCORES_NAME).is_file() else None

    n_rois = len(roi_names)
    # rows of correlation.npy = cycles (qudi-core) or probes (legacy), in cycle order
    if corr.ndim != 2:
        raise ValueError(f'{folder / CORRELATION_NAME}: expected a 2D array, got shape {corr.shape}.')
    if corr.shape[1] == n_rois:
        cycles_x_rois = corr
    elif corr.shape[0] == n_rois:
        log.info(f'Transposing correlation matrix from {corr.shape} to {corr.T.shape} for {folder / CORRELATION_NAME}')
        cycles_x_rois = corr.T
    else:
        raise ValueError(f'Unexpected shape for {folder / CORRELATION_NAME}: {corr.shape}. Expected (n_cycles, '
                         f'{n_rois}) or ({n_rois}, n_cycles) for the {n_rois} ROIs of {PARAMETERS_NAME}.')
    n_cycles = cycles_x_rois.shape[0]

    # probe label of each cycle
    if scores:
        rt_of_cycle = {}
        for row in scores:
            rt_of_cycle.setdefault(int(row['cycle']), row['RT'])
        missing = [c for c in range(1, n_cycles + 1) if c not in rt_of_cycle]
        if missing:
            # cycles without any check (aborted run): label from the probes in tube order when it fits
            ordered = [probes[k] for k in sorted(probes, key=lambda x: int(x))]
            if len(ordered) != n_cycles:
                raise ValueError(f'{folder}: {SCORES_NAME} has no RT for cycle(s) {missing} and the {len(ordered)} '
                                 f'probe(s) of {PARAMETERS_NAME} do not match the {n_cycles} cycle(s) of '
                                 f'{CORRELATION_NAME}.')
            for c in missing:
                rt_of_cycle[c] = ordered[c - 1]
        probe_names = [rt_of_cycle[c] for c in range(1, n_cycles + 1)]
    else:
        probe_names = [probes[k] for k in sorted(probes, key=lambda x: int(x))]
        log.info(f'{folder}: no {SCORES_NAME} - probe order assumed to be the order of the probe keys (tube number)')
    if len(probe_names) != n_cycles:
        raise ValueError(f'{folder}: {len(probe_names)} probe label(s) for the {n_cycles} cycle(s) of '
                         f'{CORRELATION_NAME} ({cycles_x_rois.shape}).')

    return {'metadata_folder': str(folder), 'experiment_folder': str(folder.parent), 'roi_names': roi_names,
            'probe_names': probe_names, 'corr': cycles_x_rois.T, 'threshold': threshold, 'scores': scores}


# ======================================================================================================================
# Figures and CSV
# ======================================================================================================================

def _heatmap(corr, roi_names, probe_labels, path, vmin, vmax, threshold, title):
    """ROIs x probes heatmap; ROIs whose mean score is below threshold between red lines."""
    n_rois, n_probes = corr.shape
    fig = Figure(figsize=(max(10, n_probes * 0.25), max(6, n_rois * 0.35)))
    ax = fig.add_subplot(111)
    im = ax.imshow(corr, aspect='auto', interpolation='nearest', vmin=vmin, vmax=vmax)
    fig.colorbar(im, ax=ax).set_label('Autofocus score')
    ax.set_xlabel('Probe')
    ax.set_ylabel('ROI')
    ax.set_title(title)
    ax.set_yticks(np.arange(n_rois))
    ax.set_yticklabels(roi_names)
    ax.set_xticks(np.arange(n_probes))
    ax.set_xticklabels(probe_labels if n_probes <= MAX_PROBE_LABELS else [], rotation=90, fontsize=8)
    with np.errstate(all='ignore'):
        roi_mean = np.array([np.nanmean(row) if np.isfinite(row).any() else np.nan for row in corr])
    for i, mean in enumerate(roi_mean):
        if np.isfinite(mean) and mean < threshold:
            ax.axhline(i - 0.5, color='red', linewidth=1.0)
            ax.axhline(i + 0.5, color='red', linewidth=1.0)
    fig.tight_layout()
    fig.savefig(path, dpi=300, bbox_inches='tight')


def _summary_csv(runs, path):
    """One row per ROI / probe: experiment_folder, roi_name, probe_name, correlation."""
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['experiment_folder', 'roi_name', 'probe_name', 'correlation'])
        for run in runs:
            for i, roi in enumerate(run['roi_names']):
                for j, probe in enumerate(run['probe_names']):
                    writer.writerow([run['experiment_folder'], roi, probe, float(run['corr'][i, j])])


def _drift_figure(run, path):
    """Drift of the autofocus images per ROI and cycle (sqrt(dy^2 + dx^2), px): heatmap ROIs x cycles and drift vs
    cycle (one line per ROI, median over the ROIs in bold)."""
    roi_names = run['roi_names']
    n_cycles = run['corr'].shape[1]
    drift = np.full((len(roi_names), n_cycles), np.nan)
    for row in run['scores']:
        if row['roi'] in roi_names and 1 <= int(row['cycle']) <= n_cycles:
            drift[roi_names.index(row['roi']), int(row['cycle']) - 1] = np.hypot(float(row['shift_y_px']),
                                                                             float(row['shift_x_px']))
    cycles = np.arange(1, n_cycles + 1)
    fig = Figure(figsize=(max(10, n_cycles * 0.5 + 6), max(5, len(roi_names) * 0.3)))
    ax1, ax2 = fig.add_subplot(121), fig.add_subplot(122)
    im = ax1.imshow(drift, aspect='auto', interpolation='nearest')
    fig.colorbar(im, ax=ax1).set_label('Drift (px)')
    ax1.set_xticks(np.arange(n_cycles))
    ax1.set_xticklabels([f'{c} ({p})' for c, p in zip(cycles, run['probe_names'])], rotation=90, fontsize=8)
    ax1.set_yticks(np.arange(len(roi_names)))
    ax1.set_yticklabels(roi_names, fontsize=8)
    ax1.set_xlabel('Cycle')
    ax1.set_ylabel('ROI')
    ax1.set_title('Autofocus image drift')
    for i, roi in enumerate(roi_names):
        ax2.plot(cycles, drift[i], linewidth=0.8, alpha=0.6)
    with np.errstate(all='ignore'):
        median = np.array([np.nanmedian(col) if np.isfinite(col).any() else np.nan for col in drift.T])
    ax2.plot(cycles, median, color='k', linewidth=2.5, label='median over the ROIs')
    ax2.set_xlabel('Cycle')
    ax2.set_ylabel('Drift (px)')
    ax2.set_title('Drift per ROI vs cycle')
    ax2.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches='tight')


# ======================================================================================================================
# Entry points
# ======================================================================================================================

def report_run(metadata_folder, threshold=None, vmin=0.5, vmax=1.0, log=None) -> list:
    """Heatmap and CSV (and the drift figure when autofocus_scores.csv exists) of one run, written in its metadata
    folder; returns the written paths."""
    run = load_run(metadata_folder, log)
    folder = run['metadata_folder']
    thr = threshold if threshold is not None else (run['threshold'] if run['threshold'] is not None
                                                   else DEFAULT_THRESHOLD)
    written = [os.path.join(folder, HEATMAP_NAME), os.path.join(folder, SUMMARY_NAME)]
    _heatmap(run['corr'], run['roi_names'], run['probe_names'], written[0], vmin, vmax, thr,
             f'Autofocus score - {os.path.basename(run["experiment_folder"])} (threshold {thr:g})')
    _summary_csv([run], written[1])
    if run['scores']:
        written.append(os.path.join(folder, DRIFT_NAME))
        _drift_figure(run, written[-1])
    return written


def summarize_folder(root_folder, threshold=None, vmin=0.5, vmax=1.0, log=None) -> list:
    """Every metadata folder under root_folder with HiM_parameters.yml and correlation.npy (same ROIs required):
    global heatmap and CSV in root_folder; returns the written paths."""
    log = log or _log
    root = Path(root_folder)
    folders = sorted({p.parent for p in root.rglob(PARAMETERS_NAME) if (p.parent / CORRELATION_NAME).is_file()})
    for p in sorted({p.parent for p in root.rglob(PARAMETERS_NAME)} - set(folders)):
        log.warning(f'Missing {CORRELATION_NAME} in {p}')
    if not folders:
        raise FileNotFoundError(f'No metadata folder with {PARAMETERS_NAME} and {CORRELATION_NAME} under {root}')
    runs = [load_run(folder, log) for folder in folders]
    for run in runs[1:]:
        if run['roi_names'] != runs[0]['roi_names']:
            raise ValueError(f'ROI mismatch in {run["metadata_folder"]}: the ROI names are not identical to those '
                             f'of {runs[0]["metadata_folder"]}.')
    with_csv = [run for run in runs if run['scores']]
    if with_csv and len(with_csv) < len(runs):
        log.warning(f'{len(with_csv)} run(s) with {SCORES_NAME} (qudi-core ZNCC score) and {len(runs) - len(with_csv)} '
                    f'without (legacy score): the two scores are not on the same scale.')
    labels = [f'{probe} | {os.path.basename(run["experiment_folder"])}' for run in runs for probe in run['probe_names']]
    thresholds = {run['threshold'] for run in runs if run['threshold'] is not None}
    thr = threshold if threshold is not None else (thresholds.pop() if len(thresholds) == 1 else DEFAULT_THRESHOLD)
    for run in runs:
        log.info(f'{run["metadata_folder"]}: {len(run["roi_names"])} ROI(s), {len(run["probe_names"])} probe(s), '
                 f'mean score {np.nanmean(run["corr"]) if np.isfinite(run["corr"]).any() else float("nan"):.3f}')
    written = [str(root / HEATMAP_NAME), str(root / SUMMARY_NAME)]
    _heatmap(np.concatenate([run['corr'] for run in runs], axis=1), runs[0]['roi_names'], labels, written[0], vmin,
             vmax, thr, f'Autofocus score across all ROIs and probes (threshold {thr:g})')
    _summary_csv(runs, written[1])
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Autofocus score summary of Hi-M runs (heatmap, CSV, drift).')
    parser.add_argument('folder', help='metadata folder of a run, or (with --all) a folder holding several runs')
    parser.add_argument('--all', action='store_true', help='every run found under the folder (global heatmap / CSV)')
    parser.add_argument('--threshold', type=float, default=None,
                        help=f'highlight threshold (default: correlation_threshold of the run, else {DEFAULT_THRESHOLD})')
    parser.add_argument('--vmin', type=float, default=0.5, help='colour scale minimum (default 0.5)')
    parser.add_argument('--vmax', type=float, default=1.0, help='colour scale maximum (default 1.0)')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    function = summarize_folder if args.all else report_run
    for path in function(args.folder, threshold=args.threshold, vmin=args.vmin, vmax=args.vmax):
        print(f'Written: {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
