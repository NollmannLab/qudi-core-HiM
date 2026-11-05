# -*- coding: utf-8 -*-
"""
Replay the autofocus check of the Hi-M task on the spinning disk (HiMSDTask) on a past ZEN experiment, to
choose correlation_threshold.

The reference images (autofocus_reference.npy, or the *.czi in acquisition order - same rule as the task)
are compared with the autofocus images of the past experiment (*_AcquisitionBlock1_pt*.czi, searched
recursively and sorted in acquisition order; read in this process with one czifile decoding thread, the reader
versions are printed at the start): image k is checked against the reference of ROI k mod n_rois,
cycle k // n_rois + 1, with the same rolling update as the task (a passed image becomes the reference of its
ROI). The score is the one of the task: qudi.tasks.common.autofocus_check.autofocus_score (ZNCC, -1..1).

Output: a CSV with the columns of the task's ROI_probe_autofocus_summary.csv (experiment_folder, roi_name,
probe_name, correlation, cycle, shift_y_px, shift_x_px, passed - autofocus_check.SCORES_COLUMNS; experiment_folder
is the name of the --images folder, probe_name is empty, roi_name is ROI_<index in the reference list>,
correlation is the score), a summary (min / median / max of
the score, fraction of passed ROIs per cycle for the given threshold) and, with --plot, a PNG of the score per
image (one colour per cycle).

Usage examples:

    # references from a DAPI run, images of a past Hi-M experiment, rolling update at 0.5
    python -m qudi.util.autofocus_calibration --reference /data/2026-10-20_DAPI_ref \\
        --images /data/2026-10-21_HiM_sample1 --out scores_sample1.csv

    # same with threshold 0.7 and a plot (scores_sample1.png next to the CSV)
    python -m qudi.util.autofocus_calibration --reference /data/2026-10-20_DAPI_ref \\
        --images /data/2026-10-21_HiM_sample1 --threshold 0.7 --out scores_sample1.csv --plot

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

__all__ = ['CSV_COLUMNS', 'find_autofocus_images', 'replay', 'summary', 'main']

import argparse
import csv
import os
import sys
from glob import glob

import numpy as np

from qudi.tasks.common.autofocus_check import (AUTOFOCUS_IMAGE_PATTERN, SCORES_COLUMNS, autofocus_score,
                                               load_reference_images,
                                               read_autofocus_image, reader_versions, single_thread_read_form,
                                               sort_czi_paths)

CSV_COLUMNS = SCORES_COLUMNS  # as the task's ROI_probe_autofocus_summary.csv


def find_autofocus_images(folder) -> list:
    """Autofocus images of a ZEN experiment folder (recursive), in acquisition order."""
    return sort_czi_paths(glob(os.path.join(folder, '**', AUTOFOCUS_IMAGE_PATTERN), recursive=True))


def replay(references, image_paths, threshold, read=read_autofocus_image, experiment_folder='') -> list:
    """One row per image (dict with the CSV_COLUMNS keys): image k against the reference of ROI k mod n, rolling
    update of the reference when the check passes (as HiMSDTask)."""
    refs = np.array(references, copy=True)
    n = len(refs)
    rows = []
    for k, path in enumerate(image_paths):
        print(f"Analyzing image #{k}/{len(image_paths)}")
        index = k % n
        image = read(path)
        score, shift_y, shift_x = autofocus_score(refs[index], image)
        passed = score >= threshold
        if passed:
            refs[index] = image
        rows.append({'experiment_folder': experiment_folder, 'roi_name': f'ROI_{index:03d}', 'probe_name': '',
                     'correlation': score, 'cycle': k // n + 1, 'shift_y_px': shift_y, 'shift_x_px': shift_x,
                     'passed': passed})
    return rows


def summary(rows, n_rois) -> str:
    """Min / median / max of the score and the fraction of passed ROIs per cycle."""
    scores = np.array([row['correlation'] for row in rows])
    lines = [f'{len(rows)} image(s), {n_rois} ROI(s): score min {scores.min():.3f}, median {np.median(scores):.3f}, '
             f'max {scores.max():.3f}']
    for cycle in sorted({row['cycle'] for row in rows}):
        of_cycle = [row for row in rows if row['cycle'] == cycle]
        passed = sum(row['passed'] for row in of_cycle)
        lines.append(f'  cycle {cycle}: {passed}/{len(of_cycle)} passed ({passed / len(of_cycle):.0%})')
    return '\n'.join(lines)


def _plot(rows, path, threshold) -> None:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4))
    for cycle in sorted({row['cycle'] for row in rows}):
        points = [(k, row['correlation']) for k, row in enumerate(rows) if row['cycle'] == cycle]
        ax.plot(*zip(*points), 'o-', label=f'cycle {cycle}')
    ax.axhline(threshold, color='k', linestyle='--', linewidth=1, label=f'threshold {threshold:g}')
    ax.set_xlabel('image index (acquisition order)')
    ax.set_ylabel('autofocus score (ZNCC)')
    ax.legend(fontsize='small', ncol=2)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Replay the Hi-M autofocus check on a past ZEN experiment.')
    parser.add_argument('--reference', required=True,
                        help='folder of the reference images (autofocus_reference.npy or *.czi; for a run of the '
                             'Hi-M task: its <metadata folder>/autofocus)')
    parser.add_argument('--images', required=True, help='folder of a past ZEN experiment (searched recursively)')
    parser.add_argument('--threshold', type=float, default=0.5,
                        help='threshold of the rolling reference update and of the pass / fail (default 0.5)')
    parser.add_argument('--out', default='autofocus_calibration_scores.csv',
                        help='CSV file written (default autofocus_calibration_scores.csv)')
    parser.add_argument('--plot', action='store_true', help='also save a PNG of the scores next to the CSV')
    args = parser.parse_args(argv)

    # reader of the .czi images (read in this process, one decoding thread)
    print(f'Image reader: {reader_versions()}; single-thread read: {single_thread_read_form()}')
    references = load_reference_images(args.reference)
    paths = find_autofocus_images(args.images)
    if not paths:
        print(f'No {AUTOFOCUS_IMAGE_PATTERN} image in {args.images}.', file=sys.stderr)
        return 1
    rows = replay(references, paths, args.threshold,
                  experiment_folder=os.path.basename(os.path.normpath(args.images)))
    with open(args.out, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(summary(rows, len(references)))
    print(f'Scores written to {args.out}')
    if args.plot:
        png = os.path.splitext(args.out)[0] + '.png'
        _plot(rows, png, args.threshold)
        print(f'Plot written to {png}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
