# Convert older image/formats to latest ome-tiff format with pyramid sizes and correct metadata

import argparse
from configparser import ConfigParser
from datetime import datetime
import glob
import json
import os
import re
import sys
import uuid

import tifffile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))

from constants import DEFAULT_IMAGE_FORMAT, DEFAULT_PYRAMID_LEVELS, DEFAULT_PYRAMID_DOWNSAMPLE
from CoordinateSystem import CoordinateSystem
from image_io import imread, imread_metadata, imwrite


# SBEMimage images acquired before this date / version stored the raw stage position (image centre) and possibly
# an incorrect pixel size in their metadata (fixed in commits 684fa51 / 284d9ac, released in version 2026.01.01)
SBEMIMAGE_METADATA_FIX_DATE = datetime(2025, 12, 24)
SBEMIMAGE_METADATA_FIX_VERSION = (2026, 1, 1)

# offset between UUID time (100 ns intervals since 1582-10-15) and unix epoch
UUID_EPOCH_OFFSET = 0x01b21dd213814000


def find_sbemimage_meta_dir(path, max_hops=5):
    folder = os.path.dirname(os.path.abspath(path))
    for _ in range(max_hops):
        meta_dir = os.path.join(folder, 'meta')
        if os.path.isdir(meta_dir):
            return meta_dir
        folder = os.path.dirname(folder)
    return None


def load_sbemimage_config(meta_dir, target_datetime):
    """Load the last config logged at the start of an acquisition run, before the image was acquired."""
    for config_path in sorted(glob.glob(os.path.join(meta_dir, 'logs', 'config_*.txt')), reverse=True):
        match = re.search(r'config_(\d+-\d+-\d+)\.txt$', config_path)
        if match and datetime.strptime(match.group(1), '%Y-%m-%d%H%M%S%f') <= target_datetime:
            cfg = ConfigParser()
            cfg.read(config_path)
            return cfg
    return None


def get_sbemimage_pixel_size_um(path, cfg):
    filename = os.path.basename(path)
    parts = {key: int(value) for key, value in re.findall(r'(?:^|_)([a-z]+)(\d+)(?=_|\.)', filename.lower())}
    pixel_size = None
    if 't' in parts:
        grids = cfg['grids']
        if 'r' in parts:
            grid_index = json.loads(grids['roi_index']).index(parts['r'])
        else:
            grid_index = parts.get('g', 0)
        pixel_size = json.loads(grids['pixel_size'])[grid_index]
    elif 'ov' in parts:
        pixel_size = json.loads(cfg['overviews']['ov_pixel_size'])[parts['ov']]
    elif '_stubov_' in filename.lower():
        pixel_size = float(cfg['overviews']['stub_ov_pixel_size'])
    if pixel_size:
        return [pixel_size * 1e-3] * 2  # nm -> um
    return None


def parse_sbemimage_version(creator):
    # SBEMimage version is its release date, e.g. 'SBEMimage 2025.3.11 dev'
    match = re.search(r'SBEMimage\s+(\d{4})\.(\d{1,2})\.(\d{1,2})', creator)
    if match:
        return tuple(map(int, match.groups()))
    return None


def to_local_naive(dt):
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def get_tiff_datetime(path):
    """Get image creation time from TIFF DateTime tag, or from the time-based (version 1) OME UUID
    generated when the file was written. Returns local time."""
    try:
        with tifffile.TiffFile(path) as tiff:
            tag = tiff.pages.first.tags.get('DateTime')
            if tag is not None:
                try:
                    return datetime.strptime(tag.value.strip(), '%Y:%m:%d %H:%M:%S')
                except ValueError:
                    pass
            if tiff.is_ome:
                match = re.search(r'UUID="urn:uuid:([0-9a-fA-F-]{36})"', tiff.ome_metadata)
                if match:
                    ome_uuid = uuid.UUID(match.group(1))
                    if ome_uuid.version == 1:
                        return datetime.fromtimestamp((ome_uuid.time - UUID_EPOCH_OFFSET) / 1e7)
    except Exception:
        pass
    return None


def get_acquisition_datetime(path, metadata):
    # order: OME acquisition date, TIFF DateTime tag / OME UUID time, file modification time
    try:
        return to_local_naive(datetime.fromisoformat(metadata['acquisition_date']))
    except (KeyError, ValueError):
        pass
    tiff_datetime = get_tiff_datetime(path)
    if tiff_datetime is not None:
        return tiff_datetime
    return datetime.fromtimestamp(os.path.getmtime(path))


def needs_sbemimage_fix(path, metadata):
    creator = metadata.get('creator', '')
    if 'SBEMimage' not in creator:
        return False, None
    acquisition_datetime = get_acquisition_datetime(path, metadata)
    version = parse_sbemimage_version(creator)
    if version is not None:
        return version < SBEMIMAGE_METADATA_FIX_VERSION, acquisition_datetime
    return acquisition_datetime < SBEMIMAGE_METADATA_FIX_DATE, acquisition_datetime


def fix_metadata(path, metadata, pixel_size_um=None):
    """Fix metadata of images written by older SBEMimage versions: convert stage centre position to
    top/left position in SEM coordinates, and use pixel size from the logged acquisition config.
    Based on muvis-align ImageSource.fix_metadata()."""
    needs_fix, acquisition_datetime = needs_sbemimage_fix(path, metadata)
    if not needs_fix:
        return metadata

    meta_dir = find_sbemimage_meta_dir(path)
    cfg = load_sbemimage_config(meta_dir, acquisition_datetime) if meta_dir else None
    if cfg is None:
        print(f'Warning: could not find SBEMimage config for {path}, metadata not fixed')
        return metadata

    device = 'microtome' if cfg['sys'].get('use_microtome', '').lower() == 'true' else 'sem'
    cs = CoordinateSystem.__new__(CoordinateSystem)     # only stage calibration needed
    cs.stage_calibration = [float(cfg[device][key]) for key in
                            ['stage_scale_factor_x', 'stage_scale_factor_y',
                             'stage_rotation_angle_x', 'stage_rotation_angle_y']]
    cs.apply_stage_calibration()

    if pixel_size_um is None:
        pixel_size_um = get_sbemimage_pixel_size_um(path, cfg)
    if pixel_size_um is not None:
        metadata['pixel_size'] = pixel_size_um
    elif metadata.get('pixel_size') and metadata['pixel_size'][0] != metadata['pixel_size'][1]:
        print(f'Warning: SBEMimage pixel size requires correction for {path}, please provide --pixel_size')

    if 'position' in metadata and 'pixel_size' in metadata:
        width, height = [size * pixel_size for size, pixel_size in zip(metadata['size'], metadata['pixel_size'])]
        positions = []
        for position in metadata['position']:
            dx, dy = cs.convert_s_to_d(position[:2])
            # convert centre to top/left
            positions.append([dx - width / 2, dy - height / 2] + list(position[2:]))
        metadata['position'] = positions

    if 'rotation' in metadata:
        # older versions compensated rotation for the stage rotation
        rotation = (metadata['rotation'] + cs.get_rotation()) % 360
        if rotation > 180:
            rotation -= 360
        metadata['rotation'] = rotation
    return metadata


def get_output_path(input_path, output_dir=None):
    folder, filename = os.path.split(input_path)
    base = filename.split('.', 1)[0]
    if output_dir is not None:
        folder = output_dir
    return os.path.join(folder, base + DEFAULT_IMAGE_FORMAT)


def convert_image(input_path, output_path, pixel_size_um=None,
                  npyramid_add=DEFAULT_PYRAMID_LEVELS, pyramid_downsample=DEFAULT_PYRAMID_DOWNSAMPLE):
    metadata = imread_metadata(input_path)
    # keep original acquisition time
    metadata['acquisition_date'] = get_acquisition_datetime(input_path, metadata).isoformat()
    if pixel_size_um is not None:
        metadata['pixel_size'] = pixel_size_um
    metadata = fix_metadata(input_path, metadata, pixel_size_um)
    image = imread(input_path, render=False)
    if image is None:
        raise IOError(f'Unable to read image {input_path}')

    # write to temporary file first, in case output path is the same as the input path
    temp_path = output_path + '.tmp' + DEFAULT_IMAGE_FORMAT
    imwrite(temp_path, image, metadata=metadata,
            npyramid_add=npyramid_add, pyramid_downsample=pyramid_downsample)
    os.replace(temp_path, output_path)


def get_input_paths(inputs, recursive=False):
    paths = []
    for input_path in inputs:
        if os.path.isdir(input_path):
            pattern = os.path.join(input_path, '**', '*') if recursive else os.path.join(input_path, '*')
            paths.extend(path for path in glob.glob(pattern, recursive=recursive) if os.path.isfile(path))
        else:
            paths.extend(glob.glob(input_path))
    return sorted(paths)


def main():
    parser = argparse.ArgumentParser(description='Convert images to ome-tiff with pyramid levels and metadata')
    parser.add_argument('inputs', nargs='+', help='Input image file(s), folder(s) or glob pattern(s)')
    parser.add_argument('-o', '--output', help='Output folder (default: same folder as input)')
    parser.add_argument('-r', '--recursive', action='store_true', help='Search input folders recursively')
    parser.add_argument('--pixel_size', type=float, help='Override pixel size [nm]')
    parser.add_argument('--pyramid_levels', type=int, default=DEFAULT_PYRAMID_LEVELS,
                        help=f'Number of added pyramid levels (default: {DEFAULT_PYRAMID_LEVELS})')
    parser.add_argument('--overwrite', action='store_true', help='Overwrite existing output files')
    args = parser.parse_args()

    pixel_size_um = [args.pixel_size * 1e-3] * 2 if args.pixel_size is not None else None   # nm -> um

    input_paths = get_input_paths(args.inputs, args.recursive)
    if not input_paths:
        print('No input files found')
        return

    nconverted = 0
    for input_path in input_paths:
        output_path = get_output_path(input_path, args.output)
        if os.path.exists(output_path) and not args.overwrite:
            print(f'Skipping {input_path} (output exists: {output_path})')
            continue
        try:
            convert_image(input_path, output_path, pixel_size_um=pixel_size_um, npyramid_add=args.pyramid_levels)
            print(f'Converted {input_path} -> {output_path}')
            nconverted += 1
        except Exception as e:
            print(f'Error converting {input_path}: {e}')
    print(f'Converted {nconverted} / {len(input_paths)} images')


if __name__ == '__main__':
    main()
