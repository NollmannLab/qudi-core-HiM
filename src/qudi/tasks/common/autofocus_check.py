# -*- coding: utf-8 -*-
"""
qudi-core-HiM: autofocus quality check of the spinning disk - comparison of the brightfield image that ZEN
saves at the end of its autofocus block with the reference image of the same ROI.

Pure functions (numpy / scipy only, no qudi or ZEN dependency), shared by the Hi-M task (HiMSDTask) and the
calibration script (qudi.util.autofocus_calibration):

  - load_reference_images(folder) -> (n, H, W) array: autofocus_reference.npy if the folder has it,
    otherwise every *.czi of the folder in acquisition order (last number of the file name), first plane.
  - read_autofocus_image(path) -> (H, W) array: first plane of a ZEN .czi image (image[0, 0, :, :, 0]).
  - sort_czi_paths(paths) -> list: paths sorted by the last number of the file name (acquisition order).
  - preprocess(image): binning by BIN_FACTOR, minus its gaussian blur (background removal).
  - autofocus_score(ref, new) -> (score, shift_y, shift_x): zero-normalised cross-correlation (ZNCC, a
    Pearson coefficient computed at every XY shift) of the central TEMPLATE_FRACTION of the preprocessed
    reference over the preprocessed new image. score = maximum of the map, in [-1, 1]; it does not depend
    on the intensity scale or offset and tolerates a drift up to about (1 - TEMPLATE_FRACTION) / 2 of the
    image size. shift = position of that maximum relative to the centred position, in pixels of the
    original (unbinned) image.

Modified with Claude code (Anthropic)

-----------------------------------------------------------------------------------
qudi-core is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License
as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with Qudi. If not, see <http://www.gnu.org/licenses/>.
-----------------------------------------------------------------------------------
"""

__all__ = ['BIN_FACTOR', 'BACKGROUND_SIGMA', 'TEMPLATE_FRACTION', 'REFERENCE_FILE_NAME', 'AUTOFOCUS_IMAGE_PATTERN',
           'load_reference_images', 'read_autofocus_image', 'sort_czi_paths', 'preprocess', 'autofocus_score']

import os
import re
from glob import glob

import numpy as np
from scipy.ndimage import gaussian_filter
from scipy.signal import fftconvolve

BIN_FACTOR = 2            # binning of both images before the comparison (speed, noise)
BACKGROUND_SIGMA = 10     # sigma (binned pixels) of the gaussian blur subtracted as background
TEMPLATE_FRACTION = 500 / 1024  # central part of the reference used as template (1024 binned px -> [262:762])
REFERENCE_FILE_NAME = 'autofocus_reference.npy'  # reference images of all the ROIs, in ROI order
AUTOFOCUS_IMAGE_PATTERN = '*_AcquisitionBlock1_pt*.czi'  # image saved by ZEN at the end of the autofocus block


def sort_czi_paths(paths) -> list:
    """Paths sorted by the last number of the file name (acquisition order of ZEN: ..._pt12.czi)."""
    def last_number(path):
        numbers = re.findall(r'\d+', os.path.basename(path))
        if not numbers:
            raise ValueError(f'No number in the file name {path} - cannot sort it in acquisition order.')
        return int(numbers[-1])
    return sorted(paths, key=last_number)


def read_autofocus_image(path) -> np.ndarray:
    """First plane of a ZEN .czi image (image[0, 0, :, :, 0]). Needs the czifile package."""
    from czifile import imread  # imported here: only needed when a .czi image is read
    return np.asarray(imread(path)[0, 0, :, :, 0])


def load_reference_images(folder) -> np.ndarray:
    """Reference images of the ROIs, (n, H, W): <folder>/autofocus_reference.npy when it exists (other .npy files
    of the folder are ignored), otherwise every *.czi of the folder in acquisition order (first plane of each).
    Raises ValueError when there is no reference image or the images do not all have the same shape."""
    npy = os.path.join(folder, REFERENCE_FILE_NAME)
    if os.path.isfile(npy):
        images = np.asarray(np.load(npy))
        if images.ndim == 2:
            images = images[np.newaxis]
    else:
        paths = sort_czi_paths(glob(os.path.join(folder, '*.czi')))
        if not paths:
            raise ValueError(f'No reference image in {folder} (neither {REFERENCE_FILE_NAME} nor *.czi files).')
        planes = [read_autofocus_image(path) for path in paths]
        shapes = sorted({plane.shape for plane in planes})
        if len(shapes) > 1:
            raise ValueError(f'The reference images of {folder} do not all have the same shape: {shapes}.')
        images = np.stack(planes)
    if images.ndim != 3 or len(images) == 0:
        raise ValueError(f'Reference images of {folder}: expected an (n, H, W) array, got shape {images.shape}.')
    return images


def preprocess(image, bin_factor=BIN_FACTOR, sigma=BACKGROUND_SIGMA) -> np.ndarray:
    """Image binned by bin_factor (mean of bin_factor x bin_factor pixels; the last rows / columns are cropped when
    the size is not a multiple of bin_factor), minus its gaussian blur of the given sigma."""
    image = np.asarray(image, dtype=np.float64)
    if image.ndim != 2:
        raise ValueError(f'Expected a 2D image, got shape {image.shape}.')
    h, w = (image.shape[0] // bin_factor) * bin_factor, (image.shape[1] // bin_factor) * bin_factor
    if h == 0 or w == 0:
        raise ValueError(f'Image {image.shape} smaller than the binning factor {bin_factor}.')
    binned = image[:h, :w].reshape(h // bin_factor, bin_factor, w // bin_factor, bin_factor).mean(axis=(1, 3))
    return binned - gaussian_filter(binned, sigma=sigma)


def _template_box(shape):
    """(y0, x0, th, tw): position and size of the central TEMPLATE_FRACTION of an image of this shape."""
    th = max(1, int(round(shape[0] * TEMPLATE_FRACTION)))
    tw = max(1, int(round(shape[1] * TEMPLATE_FRACTION)))
    return (shape[0] - th) // 2, (shape[1] - tw) // 2, th, tw


def _window_sums(image, th, tw):
    """Sum of image over every th x tw window (valid positions), from the integral image."""
    integral = np.pad(np.cumsum(np.cumsum(image, axis=0), axis=1), ((1, 0), (1, 0)))
    return integral[th:, tw:] - integral[:-th, tw:] - integral[th:, :-tw] + integral[:-th, :-tw]


def _zncc_map(image, template) -> np.ndarray:
    """Zero-normalised cross-correlation of template over image at every valid position (same definition as
    skimage.feature.match_template): Pearson coefficient between the template and the image window."""
    th, tw = template.shape
    t = template - template.mean()
    t_norm = np.sqrt(np.sum(t * t))
    n = th * tw
    numerator = fftconvolve(image, t[::-1, ::-1], mode='valid')   # sum(window * t); t has zero mean
    s1 = _window_sums(image, th, tw)
    s2 = _window_sums(image * image, th, tw)
    window_norm = np.sqrt(np.maximum(s2 - s1 * s1 / n, 0.0))
    denominator = window_norm * t_norm
    ncc = np.zeros_like(numerator)
    valid = denominator > 1e-12 * max(1.0, float(np.max(denominator)) if denominator.size else 1.0)
    ncc[valid] = numerator[valid] / denominator[valid]
    return np.clip(ncc, -1.0, 1.0)


def autofocus_score(ref, new):
    """(score, shift_y, shift_x): ZNCC of the central part of the preprocessed reference over the preprocessed new
    image; score = maximum of the map in [-1, 1]; shift = position of the maximum relative to the centred position,
    in pixels of the original image (positive: the new image content moved down / right). Raises ValueError when
    the two images do not have the same shape."""
    ref, new = np.asarray(ref), np.asarray(new)
    if ref.shape != new.shape:
        raise ValueError(f'Autofocus check: the reference image {ref.shape} and the new image {new.shape} do not have '
                         f'the same shape.')
    ref_p, new_p = preprocess(ref), preprocess(new)
    y0, x0, th, tw = _template_box(ref_p.shape)
    ncc = _zncc_map(new_p, ref_p[y0:y0 + th, x0:x0 + tw])
    peak_y, peak_x = np.unravel_index(int(np.argmax(ncc)), ncc.shape)
    return float(ncc[peak_y, peak_x]), int((peak_y - y0) * BIN_FACTOR), int((peak_x - x0) * BIN_FACTOR)
