import cv2
import numpy as np
import os
from typing import Tuple, List

from scipy.ndimage import interpolation
from skimage import draw
from skimage.io import ImageCollection, imsave
from skimage.registration import phase_cross_correlation
from skimage.transform import rescale
from skimage.util import crop


def parse_tile_key(tile_key: str) -> Tuple[int, int]:
    """Parses tile_key into g and t, ensuring exactly two components."""
    parts = tile_key.split('.')
    # Check if there are exactly two components
    if len(parts) != 2:
        raise ValueError(f"Invalid tile_key format: {tile_key}. Expected format 'g.t' with exactly two parts.")
    g, t = map(int, parts)
    return g, t


def grad_img(data: np.ndarray) -> np.ndarray:
    scale = 1
    delta = 0
    ddepth = cv2.CV_32F

    # Compute gradients along x and y axes
    grad_x = cv2.Scharr(data, ddepth, 1, 0, scale=scale, delta=delta, borderType=cv2.BORDER_DEFAULT)
    grad_y = cv2.Scharr(data, ddepth, 0, 1, scale=scale, delta=delta, borderType=cv2.BORDER_DEFAULT)

    # Return the magnitude of the gradient (combined gradient in both x and y directions)
    return cv2.magnitude(grad_x, grad_y)


def inspect_masked_img(img: np.ndarray, mask: np.ndarray) -> Tuple[float, float, float]:
    """Calculates image statistics on centered circular region of the image."""

    # Default vals
    ma_mean, ma_stddev, ma_sharp = 0, 0, 0

    if not isinstance(img, np.ndarray):
        return ma_mean, ma_stddev, ma_sharp

    # Apply circular binary mask on original image
    img = np.ma.array(img, mask=mask)

    # Apply circular binary mask on gradient image
    img_grad = np.ma.array(grad_img(img), mask=mask)

    # Calculate mean, stddev, sharpness on center circular region of image
    # ma_mean = img.mean()  not used
    ma_stddev = img.std()
    ma_sharp = img_grad.mean()
    return ma_mean, ma_stddev, ma_sharp


def imread_cv2(path: str) -> np.ndarray:
    return cv2.imread(path, cv2.IMREAD_GRAYSCALE).astype(np.float32)


def create_mask(tile_size):
    width, height = tile_size[:2]
    center = (int(height / 2), int(width / 2))
    radius = int(height / 3)
    rr, cc = draw.disk(center, radius)
    mask = np.ones((height, width), dtype=bool)
    mask[rr, cc] = False
    return mask


def load_image_collection(filenames: list) -> np.ndarray:
    return ImageCollection(filenames, conserve_memory=True).concatenate()


def register_image_collection(ic: np.ndarray) -> np.ndarray:
    shifts = []
    for i, img in enumerate(ic[:-1]):
        # Do not use (upsample_factor > 1) as it spoils the image information!
        shifts.append(phase_cross_correlation(ic[i], ic[i+1], upsample_factor=1))
    cumulative_shifts = np.cumsum(shifts, axis=0)
    return cumulative_shifts


def compute_shifts_cv2(files: List[str]):
    # Computes translation vectors between AFSS images
    def compute_shift(image1, image2):
        def negate_tuple(tup):
            return tuple(-x for x in tup)

        def fix_vec(vec: tuple) -> np.ndarray:
            vec = np.round(vec[::-1])
            vec = np.asarray(negate_tuple(vec))
            vec = np.reshape(vec, [1, 2])
            return vec

        shift_vec, error = cv2.phaseCorrelate(image1, image2)
        return fix_vec(shift_vec), error

    shift = 0.0
    for i in range(1, len(files)):
        ref = imread_cv2(files[i - 1])
        cur = imread_cv2(files[i])
        shift, err = compute_shift(ref, cur)
    return shift


def crop_image_collection(image_collection: np.ndarray, cumm_shifts: np.ndarray) -> np.ndarray:
    sX, sY = np.asarray(cumm_shifts)[:, 1], np.asarray(cumm_shifts)[:, 0]
    sx = np.array(np.round([abs(np.max(sX)), abs(np.min(sX))]), dtype=int)
    sy = np.array(np.round([abs(np.max(sY)), abs(np.min(sY))]), dtype=int)
    crop_vals = ([0, 0], sy, sx)
    return crop(image_collection, crop_vals)


def shift_collection(ic: np.ndarray, cumm_shifts: np.ndarray) -> np.ndarray:
    for i, im in enumerate(ic[1:]):
        ic[i+1] = interpolation.shift(im, cumm_shifts[i])
    return ic


def get_collection_mask(coll_xy_shape: Tuple[int, int]) -> np.ndarray:
    h, w = coll_xy_shape
    y, x = np.ogrid[:h, :w]
    center_y, center_x = h // 2, w // 2
    radius = h // 3
    mask = (y - center_y)**2 + (x - center_x)**2 > radius**2
    return mask


def validate_img_collection(img_coll) -> bool:
    # Verifies tile-image collection after registration and crop operations
    coll_valid = True

    # Check if the input image is valid (non-empty and non-None)
    if any(image is None or image.size == 0 for image in img_coll):
        coll_valid = False
    return coll_valid


def store_reg_coll(img_coll, filenames, prefix):
    # Save sharpness plots to project stats folder
    scale_down = True
    scale_fct = 0.1  # Downscaling the registered series saves disk space

    for j, fn in enumerate(filenames):
        reg_img_path = os.path.join(prefix, os.path.basename(fn))
        if scale_down:
            im_out = rescale(img_coll[j], scale_fct, anti_aliasing=False)
        else:
            im_out = img_coll[j]
        imsave(reg_img_path, im_out)
    return


def get_collection_sharpness(ic: np.ndarray, metric: str) -> list:
    """
    Computes sharpness of series of images to later estimate best focus/stig from AFSS series
    Args:
        ic: image collection of autofocus tile AFSS series
        metric: 'contrast' computes sharpness as standard deviation of image brightness
                'edges' computes sharpness as a mean value of image convolved with Sobel operator
    """
    sh_arr = []

    x, y = np.shape(ic[0])
    mask = get_collection_mask((x, y))

    for img in ic:
        if metric == 'contrast':
            sh_arr.append(np.std(img))
        elif metric == 'edges':
            masked_grad_img = np.ma.array(grad_img(img), mask=mask, dtype=np.float32)
            sh_arr.append(np.mean(masked_grad_img))
    return sh_arr


def filter_outliers(data: np.ndarray, m=2., epsilon=1e-8) -> np.ndarray:
    d = np.abs(data - np.median(data))
    mdev = np.median(d) + epsilon  # Add epsilon to prevent division by very small values
    s = d / mdev
    return data[s < m]


def rmse(predictions: np.ndarray, targets: np.ndarray) -> float:
    """" Computes root mean squared error of fit values (predictions) to measured values (target)"""
    return np.sqrt(np.mean((predictions-targets)**2))


def get_weights(input_array: list, smallest_weight: float) -> list:
    """
    Linear weighing is applied to the input_array (list of diffs from afss_series optima)
    Values are recalibrated to the range [smallest_weight:1], where 1 is given to the
    lowest value from input array
    """
    def norm_data(arr: list) -> np.ndarray:
        arr = np.asarray(arr)
        arr *= -1   # inversion as highest weight (w=1.0) will be given to the lowest RMSE error
        arr -= min(arr)
        return arr/max(arr)
    weights = norm_data(input_array)
    fcts = smallest_weight * (1 - weights)
    return list(weights + fcts)


def afss_fit_linear(x_vals, y_vals, min_slope) -> Tuple[Tuple, bool]:
    """
    Perform linear fit on x AFSS series sharpness values, return max y-value,
    corresponding x-value, and fit RMSE of fitted line over x-range if
    fit_rmse < limit and |slope| >= min_slope.

    Args:
        x_vals: NumPy array of x values.
        y_vals: NumPy array of y values (must be same length as x_vals).
        min_slope: Float, minimum absolute slope for a valid fit.

    Returns:
        Tuple: ((max_y, x_at_max_y, fit_rmse, plot x-range, plot y-range), fit outcome)
            - max_y: Max y-value of fitted line (at min or max x) if successful, else None.
            - x_at_max_y: x-value where max y occurs if successful, else None.
            - fit_rmse: RMSE of the fit if successful, else -1.

    Raises:
        ValueError: If arrays are empty, have fewer than 2 points, or have unequal lengths.
    """
    # Input validation
    if len(x_vals) == 0 or len(y_vals) == 0:
        raise ValueError("Input arrays cannot be empty")
    if len(x_vals) < 2:
        raise ValueError("At least two points are required for linear fit")
    if len(x_vals) != len(y_vals):
        raise ValueError("x_vals and y_vals must have equal length")

    # Ensure NumPy arrays
    x = np.asarray(x_vals)
    y = np.asarray(y_vals)

    # Compute x-range for plotting and max y calculation
    x_min, x_max = np.min(x), np.max(x)

    # Perform linear fit (y = mx + c)
    coefficients = np.polyfit(x, y, 1)  # Degree 1 for linear
    m, c = coefficients  # Slope and intercept

    # Calculate fitted y-values
    y_fitted = m * x + c

    # Calculate RMSE
    mse = np.mean((y - y_fitted) ** 2)
    fit_rmse = np.sqrt(mse)

    # Determine if fit is successful
    is_successful = abs(m) >= min_slope

    # Compute return values
    if is_successful:
        # Determine fit y-val at x-range border
        if m > 0:
            max_y = m * x_max + c
            x_at_max_y = x_max
        else:
            max_y = m * x_min + c
            x_at_max_y = x_min
    else:
        max_y = None
        x_at_max_y = None

    # Smooth line over x range for plotting
    x_fit = np.linspace(x_min, x_max, 100)
    y_fit = m * x_fit + c
    res = x_at_max_y, max_y, fit_rmse, x_fit, y_fit
    return res, is_successful


def afss_fit_poly(x_vals: np.ndarray, y_vals: np.ndarray) -> Tuple[Tuple, bool]:
    """
    Fit AFSS series data with a polynomial and compute optimal point.

    Args:
        x_vals: Input x values
        y_vals: Input y values
    Returns:
        tuple: (x_opt, y_opt, RMSE, plot x-range, plot y-range), fit outcome
    """

    # Fit sharpness values with second-order polynom
    x_min, x_max = min(x_vals), max(x_vals)
    x_fit = np.linspace(x_min, x_max, num=101, endpoint=True)
    cfs = np.polyfit(x_vals, y_vals, deg=2)
    fit = np.poly1d(cfs)
    fit_rmse = rmse(fit(x_vals), y_vals)

    # Verify sharpness values follow expected (negative) quadratic behavior
    is_successful = cfs[0] < 0
    if is_successful:
        x_opt = -cfs[1] / (2 * cfs[0])
        # Limit the resulting optimum to the range of WD/Stig deviation
        if x_opt < x_min:
            x_opt = x_min
        elif x_opt > x_max:
            x_opt = x_max
        y_opt = fit(x_opt)
    else:
        x_opt = None
        y_opt = None

    res = x_opt, y_opt, fit_rmse, x_fit, fit(x_fit)
    return res, is_successful
