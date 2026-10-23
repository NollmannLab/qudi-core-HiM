# -*- coding: utf-8 -*-
"""
Write a ROI list file with N randomly placed ROIs, in the format saved and loaded by the ROI logic
(RegionOfInterestList.to_dict() written as json). Meant for testing ROI features (path
optimization, ROI scans, ...) on a computer without a stage.

ROI names are ROI_001, ROI_002, ... (3-digit zero padding, starting at --first-number), the list
origin is (0, 0, 0). Positions are drawn uniformly in the given x / y ranges (µm); z is fixed
(--z) or random (--z-range). An existing file is never overwritten (error, exit code 1).

Usage examples:

    # 25 ROIs on a 10 x 10 mm field, z = 0, written to ./random_25_rois.json
    python -m qudi.util.make_random_roi_list --n 25 --x-range 0 10000 --y-range 0 10000

    # 40 ROIs with a random z between 0 and 50 µm, written to ~/qudi/roi_lists/test_40.json
    python -m qudi.util.make_random_roi_list --n 40 --z-range 0 50 --seed 3 --name test_40 \\
        --folder ~/qudi/roi_lists

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

__all__ = ['make_random_roi_list', 'main']

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np

from qudi.logic.roi_logic import RegionOfInterestList


def make_random_roi_list(n=25, x_range=(0.0, 10000.0), y_range=(0.0, 10000.0), z=0.0, z_range=None,
                         seed=0, name=None, first_number=1, creation_time=None) -> RegionOfInterestList:
    """ Build a RegionOfInterestList with n ROIs at random positions.

    @param int n: number of ROIs (>= 0)
    @param x_range: (min, max) of x in µm
    @param y_range: (min, max) of y in µm
    @param float z: z of every ROI when z_range is None
    @param z_range: (min, max) of a random z in µm, or None for a fixed z
    @param int seed: seed of the random generator (same seed -> same positions)
    @param str name: list name, default 'random_<n>_rois'
    @param int first_number: number of the first ROI (ROI_001 for 1)
    @param creation_time: datetime or 'YYYY-MM-DD HH:MM:SS.ffffff' string, default now
    @return: RegionOfInterestList
    """
    n = int(n)
    if n < 0:
        raise ValueError(f'number of ROIs must be >= 0, got {n}')
    if int(first_number) < 0:
        raise ValueError(f'first ROI number must be >= 0, got {first_number}')
    for label, rng_ in (('x', x_range), ('y', y_range), ('z', z_range)):
        if rng_ is not None and not float(rng_[0]) <= float(rng_[1]):
            raise ValueError(f'{label} range must be MIN MAX with MIN <= MAX, got {tuple(rng_)}')
    if name is None:
        name = f'random_{n}_rois'

    rng = np.random.default_rng(seed)
    x = rng.uniform(float(x_range[0]), float(x_range[1]), n)
    y = rng.uniform(float(y_range[0]), float(y_range[1]), n)
    if z_range is None:
        zs = np.full(n, float(z))
    else:
        zs = rng.uniform(float(z_range[0]), float(z_range[1]), n)

    roi_list = RegionOfInterestList(name=name, creation_time=creation_time)
    for position in zip(x, y, zs):
        # names ROI_<first_number>, ROI_<first_number + 1>, ... (zero padding to 3 digits)
        roi_list.add_roi(np.array(position, dtype=float), first_digit=int(first_number))
    return roi_list


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        prog='python -m qudi.util.make_random_roi_list',
        description='Write a ROI list file (json, ROI logic format) with N randomly placed ROIs.')
    parser.add_argument('--n', type=int, default=25, help='number of ROIs (default 25)')
    parser.add_argument('--x-range', type=float, nargs=2, default=(0.0, 10000.0), metavar=('MIN', 'MAX'),
                        help='x range in µm (default 0 10000)')
    parser.add_argument('--y-range', type=float, nargs=2, default=(0.0, 10000.0), metavar=('MIN', 'MAX'),
                        help='y range in µm (default 0 10000)')
    z_group = parser.add_mutually_exclusive_group()
    z_group.add_argument('--z', type=float, default=0.0, help='fixed z in µm (default 0)')
    z_group.add_argument('--z-range', type=float, nargs=2, default=None, metavar=('MIN', 'MAX'),
                         help='random z in µm, uniform in [MIN, MAX]')
    parser.add_argument('--seed', type=int, default=0, help='random seed (default 0)')
    parser.add_argument('--name', default=None, help="list name and file name (default 'random_<n>_rois')")
    parser.add_argument('--folder', default=os.getcwd(), help='output folder (default: current folder)')
    parser.add_argument('--first-number', type=int, default=1, help='number of the first ROI (default 1)')
    parser.add_argument('--creation-time', default=None, metavar="'YYYY-MM-DD HH:MM:SS.ffffff'",
                        help='creation time stored in the list (default: now); a fixed value makes the file '
                             'identical for identical arguments')
    return parser.parse_args(argv)


def main(argv=None) -> int:
    """ Command-line entry point. Returns the exit code: 0 written, 1 error (nothing written). """
    args = _parse_args(argv)
    try:
        creation_time = None
        if args.creation_time is not None:
            creation_time = datetime.strptime(args.creation_time, '%Y-%m-%d %H:%M:%S.%f')
        roi_list = make_random_roi_list(n=args.n, x_range=args.x_range, y_range=args.y_range, z=args.z,
                                        z_range=args.z_range, seed=args.seed, name=args.name,
                                        first_number=args.first_number, creation_time=creation_time)
    except ValueError as e:
        print(f'Error: {e}', file=sys.stderr)
        return 1

    folder = os.path.expanduser(args.folder)
    path = os.path.join(folder, roi_list.name + '.json')
    try:
        os.makedirs(folder, exist_ok=True)
        # mode 'x': fails if the file already exists, so an existing list is never replaced
        with open(path, 'x') as file:
            json.dump(roi_list.to_dict(), file)
    except FileExistsError:
        print(f'Error: {path} already exists - not overwritten.', file=sys.stderr)
        return 1
    except OSError as e:
        print(f'Error: could not write {path}: {e}', file=sys.stderr)
        return 1

    print(f'{path}: {len(roi_list.roi_names)} ROI(s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
