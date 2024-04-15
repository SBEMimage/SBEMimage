import configparser
import io
import itertools
import json
import math
import numpy as np
import os
import statsmodels.api as smapi
import utils
import warnings
import yaml

from scipy.spatial import ConvexHull
from scipy.spatial.distance import cdist
from shapely.geometry import Polygon
from shapely.geometry import Point

warnings.filterwarnings("ignore")


class ArrayData:
    def __init__(self, path=None):
        self.reset()
        if path:
            self.read_data(path)

    def reset(self):
        self.active = False
        self.path = None
        self.sections = {}
        self.landmarks = {}
        self.focus = {}
        self.sbemimage_sections = {}
        self.selected_sections = []
        self.selected = []
        self.checked_sections = []
        self.transform = []
        self.calibrated = False

    def read_data(self, path):
        self.reset()
        self.active = True
        self.path = path
        ext = os.path.splitext(self.path)[-1].lower()
        if ext == '.magc':
            self.read_data_magc()
        elif ext == '.json':
            self.read_data_json()
        else:
            self.read_data_yaml()

        utils.log_info(
            'Array-CTRL',
            f'File successfully read from {self.path}')

    def read_data_json(self):
        with open(self.path, 'r') as infile:
            data = json.load(infile, object_hook=json_keys_to_int)
            for section, contents in data.items():
                if section == 'sections':
                    self.sections = contents
                elif section == 'landmarks':
                    self.landmarks = contents
                elif section == 'serial_order':
                    self.serial_order = contents
                elif section == 'stage_order':
                    self.stage_order = contents

    def read_data_yaml(self):
        with open(self.path, 'r') as infile:
            data = yaml.load(infile, Loader=yaml.Loader)
            for section, contents in data.items():
                if section == 'sections':
                    self.sections = contents
                elif section == 'landmarks':
                    self.landmarks = contents
                elif section == 'serial_order':
                    self.serial_order = contents
                elif section == 'stage_order':
                    self.stage_order = contents

    def read_data_magc(self):
        config = configparser.ConfigParser()

        with open(self.path, 'r') as configfile:
            config.read_file(configfile)

        for header in config.sections():
            headers = header.split('.')
            header0 = headers[0]
            ids = [int(index) for index in headers[1:]] if '.' in header else []
            id = ids[0] if len(ids) > 0 else None
            contents = config.items(header)

            if header.startswith('section.') or header.startswith('sections.'):
                if id not in self.sections:
                    self.sections[id] = {}
                self.sections[id]['sample'] = {}
                sample = self.sections[id]['sample']
                for key, val in contents:
                    if key == 'polygon':
                        values = [float(x) for x in val.split(',')]
                        polygon = np.reshape(values, (-1, 2)).tolist()
                        sample['polygon'] = polygon
                    elif key == 'center':
                        sample['center'] = [float(x) for x in val.split(',')]
                    elif key == 'area':
                        sample['area'] = float(val)
                    elif key == 'angle':
                        sample['angle'] = ((float(val) + 90) % 360) - 180

            elif header.startswith('magnet.') or header.startswith('magnets.'):
                if id not in self.sections:
                    self.sections[id] = {}
                self.sections[id]['magnet'] = {}
                magnet = self.sections[id]['magnet']
                for key, val in contents:
                    value = [float(x) for x in val.split(',')]
                    if key == 'location':
                        value = [value]
                    magnet['polygon'] = value

            elif header.startswith('roi.') or header.startswith('rois.'):
                roi_id = ids[1] if len(ids) > 1 else 0
                if 'rois' not in self.sections[id]:
                    self.sections[id]['rois'] = {}
                self.sections[id]['rois'][roi_id] = {}
                roi = self.sections[id]['rois'][roi_id]
                for key, val in contents:
                    if key == 'polygon':
                        values = [float(x) for x in val.split(',')]
                        polygon = np.reshape(values, (-1, 2)).tolist()
                        roi['polygon'] = polygon
                    elif key == 'center':
                        roi['center'] = [float(x) for x in val.split(',')]
                    elif key == 'area':
                        roi['area'] = float(val)
                    elif key == 'angle':
                        roi['angle'] = ((float(val) + 90) % 360) - 180

            elif header.startswith('focus.'):
                self.sections[id]['focus'] = {}
                focus = self.sections[id]['focus']
                for key, val in contents:
                    if key == 'polygon':
                        values = [float(x) for x in val.split(',')]
                        points = np.reshape(values, (-1, 2)).tolist()
                        for point_index, point in enumerate(points):
                            focus[point_index] = {'location': point}

            elif header.startswith('landmarks.') or header.startswith('landmark.'):
                self.landmarks[id] = {'source': {'location': [float(x) for x in config.get(header, 'location').split(',')]}}

            elif header in ['serial_order', 'serialorder']:
                value = config.get(header0, header0)
                if value != '[]':
                    self.serial_order = [int(x) for x in value.split(',')]

            elif header in ['stage_order', 'tsporder']:
                value = config.get(header0, header0)
                if value != '[]':
                    self.stage_order = [int(x) for x in value.split(',')]

            elif header == 'selected_sections':
                value = config.get('selected_sections', 'selected_sections')
                if value != '[]':
                    self.selected_sections = [int(x) for x in value.split(',')]

            elif header == 'checked_sections':
                value = config.get('checked_sections', 'checked_sections')
                if value != '[]':
                    self.checked_sections = [int(x) for x in value.split(',')]

            elif header == 'transform':
                value = config.get('transform', 'transform')
                if value != '[]':
                    self.transform = np.transpose([int(x) for x in value.split(',')])

            # deprecated
            if header0 == 'sbemimage_sections':
                self.sbemimage_sections[id] = {}
                section = self.sbemimage_sections[id]
                for key, val in contents:
                    if key == 'focus':
                        values = [float(x) for x in val.split(',')]
                        points = [[x, y] for x, y in zip(values[::2], values[1::2])]
                        section['focus'] = points
                    elif key == 'center':
                        section['center'] = [float(x) for x in val.split(',')]
                    elif key == 'angle':
                        section['angle'] = ((-float(val) + 90) % 360) - 180

    # deprecated: save grids instead
    def write_data(self, gm):
        if self.path:
            ext = os.path.splitext(self.path)[-1].lower()
            if ext == '.magc':
                self.write_data_magc(gm)
            elif ext == '.json':
                self.write_data_json()
            else:
                self.write_data_yaml()

    def write_data_json(self):
        if self.path:
            with open(self.path, 'w') as outfile:
                json.dump(self.sections, outfile, indent=4)

    def write_data_yaml(self):
        if self.path:
            with open(self.path, 'w') as outfile:
                yaml.dump(self.sections, outfile, sort_keys=False, default_flow_style=None)

    def write_data_magc(self, gm):
        if not self.path:
            return

        config = configparser.ConfigParser()
        config.add_section('sbemimage_sections')
        config.set(
            'sbemimage_sections',
            'number',
            str(gm.number_grids))

        if self.calibrated:
            transform_angle = -get_affine_rotation(self.transform.T)

        with open(self.path, 'r') as f:
            lines = f.readlines()

        sbemimage_line_index = len(list(itertools.takewhile(
                lambda x: not 'sbemimage_sections' in x,
                lines)))

        for grid_index in range(gm.number_grids):
            target_ROI = gm[grid_index].centre_sx_sy
            target_ROI_angle = gm[grid_index].rotation

            if self.calibrated:
                # transform back the grid coordinates
                # in non-transformed coordinates
                result = apply_affine_t(
                    [target_ROI[0]],
                    [target_ROI[1]],
                    self.transform.T)
                source_ROI = [result[0][0], result[1][0]]
                source_ROI_angle = (
                    (-90 + target_ROI_angle - transform_angle) % 360)
            else:
                source_ROI = target_ROI
                source_ROI_angle = (-90 + target_ROI_angle) % 360

            header = f'sbemimage_sections.{grid_index}'
            config.add_section(header)
            config.set(
                header,
                'center',
                point_to_flat_string(source_ROI))
            config.set(
                header,
                'angle',
                str(float(source_ROI_angle)))

            af_points_source = gm[grid_index].array_autofocus_points_source
            if len(af_points_source) > 0:
                config.set(
                    header,
                    'focus',
                    points_to_flat_string(af_points_source))

        with open(self.path, 'w') as f:
            for line in lines[:sbemimage_line_index]:
                f.write(line)
            # f.write('\n')

            with io.StringIO('') as g:
                config.write(g)
                for line in g.getvalue().splitlines(True):
                    f.write(line)

    def get_nsections(self):
        return len(self.sections)

    def get_nrois(self):
        sections = self.sections
        if isinstance(sections, dict):
            sections = sections.values()
        nrois = 1
        for section in sections:
            nrois = max(len(section.get('rois', [])), nrois)
        return nrois

    def get_rois(self):
        rois = {}
        for array_index, section in self.sections.items():
            if section:
                rois0 = section.get('rois', [])
                if len(rois0) > 0:
                    rois1 = rois0
                else:
                    rois1 = {0: section['sample']}
                rois[array_index] = rois1
        return rois

    def get_roi(self, array_index, roi_index):
        roi = None
        if array_index in self.sections:
            section = self.sections[array_index]
            if section:
                rois = section.get('rois', [])
                if len(rois) > 0:
                    roi = rois[roi_index]
                elif roi_index == 0:
                    roi = section['sample']
        return roi

    def get_roi_stage_properties(self, source, imported_image):
        # Get rectangle: use angle corresponding to rectangle size
        center0, size0, angle0 = utils.calc_rotated_rect(source['polygon'])
        size = np.multiply(size0, imported_image.scale)
        center = utils.apply_transform(source['center'], self.transform)
        if imported_image.flipped:
            rotation = angle0 - imported_image.rotation
        else:
            rotation = -angle0 - imported_image.rotation
        return center, size, rotation % 360

    def get_focus_points_in_roi(self, section_index, roi):
        focus_points = []
        for focus_point in self.sections[section_index].get('focus', {}).values():
            if is_point_inside_polygon(focus_point['location'], roi['polygon']):
                focus_points.append(focus_point)
        return focus_points

    def get_landmarks(self, landmark_type='source'):
        landmarks = {index: landmark[landmark_type]['location']
                     for index, landmark in self.landmarks.items()
                     if landmark_type in landmark}
        return dict(sorted(landmarks.items()))

    def set_landmark(self, landmark_id, location, landmark_type='target'):
        self.landmarks[landmark_id][landmark_type] = {'location': location}


def json_keys_to_int(data0):
    if isinstance(data0, dict):
        data = {}
        for key, value in data0.items():
            if key.isnumeric():
                key = int(key)
            data[key] = value
    else:
        data = data0
    return data


def point_to_flat_string(point):
    flat_string = ','.join(
        [str(round(x, 3)) for x in point])
    return flat_string


def points_to_flat_string(points):
    points_flat = []
    for point in points:
        points_flat.append(point[0])
        points_flat.append(point[1])
    points_string = ','.join(
        [str(round(x, 3)) for x in points_flat])
    return points_string


#####################
# geometric functions
#####################


def affine_t(
    x_in,
    y_in,
    x_out,
    y_out,
    flip_x=False):

    x_in = np.array(x_in)
    x_in = -x_in if flip_x else x_in

    X = np.array([[x, y, 1] for (x, y) in zip(x_in, y_in)])
    Y = np.array([[x, y, 1] for (x, y) in zip(x_out, y_out)])
    aff, res, rank, s = np.linalg.lstsq(X, Y, rcond=None)
    return aff


def apply_affine_t(
    x_in,
    y_in,
    aff,
    flip_x=False):

    x_in = np.array(x_in)
    x_in = -x_in if flip_x else x_in

    input = np.array([ [x, y, 1] for (x,y) in zip(x_in, y_in)])
    output = np.dot(input, aff)
    x_out, y_out = output.T[0:2]

    # x_out = -x_out if flip_x else x_out

    return x_out, y_out


def invert_affine_t(aff):
    return np.linalg.inv(aff)


def get_affine_rotation(aff):
    return np.rad2deg(np.arctan2(aff[1][0], aff[1][1]))


def get_affine_scaling(aff):
    x_out, y_out = apply_affine_t([0, 1000], [0, 1000], aff)
    scaling = np.linalg.norm(
        [
            x_out[1] - x_out[0],
            y_out[1] - y_out[0],
        ]) / np.linalg.norm([1000,1000])
    return scaling


def rigid_t(
    x_in,
    y_in,
    x_out,
    y_out,
    flip_x=False):

    x_in = -x_in if flip_x else x_in

    A_data = []
    for i in range(len(x_in)):
        A_data.append([-y_in[i], x_in[i], 1, 0])
        A_data.append([x_in[i], y_in[i], 0, 1])

    b_data = []
    for i in range(len(x_out)):
        b_data.append(x_out[i])
        b_data.append(y_out[i])

    A = np.matrix(A_data)
    b = np.matrix(b_data).T
    # Solve
    c = np.linalg.lstsq(A, b, rcond=None)[0].T
    c = np.array(c)[0]

    displacements = []
    for i in range(len(x_in)):
        displacements.append(np.sqrt(
        np.square((c[1]*x_in[i] - c[0]*y_in[i] + c[2] - x_out[i]) +
        np.square(c[1]*y_in[i] + c[0]*x_in[i] + c[3] - y_out[i]))))

    # return c, np.mean(displacements)
    return c


def apply_rigid_t(
    x, y,
    coefs,
    flip_x=False):

    x, y = map(lambda x: np.array(x), [x, y])

    x = -x if flip_x else x

    x_out = coefs[1] * x - coefs[0] * y + coefs[2]
    y_out = coefs[1] * y + coefs[0] * x + coefs[3]

    # x_out = -x_out if flip_x else x_out

    return x_out, y_out


def get_rigid_rotation(coefs):
    return np.rad2deg(np.arctan2(coefs[0], coefs[1]))


def get_rigid_scaling(coefs):
    return coefs[1]

#####################
#####################


def is_convex_polygon(polygon):
    """Source: https://stackoverflow.com/a/45372025/10832217
    Return True if the polynomial defined by the sequence of 2D
    points is 'strictly convex': points are valid, side lengths non-
    zero, interior angles are strictly between zero and a straight
    angle, and the polygon does not intersect itself.

    NOTES:  1.  Algorithm: the signed changes of the direction angles
                from one side to the next side must be all positive or
                all negative, and their sum must equal plus-or-minus
                one full turn (2 pi radians). Also check for too few,
                invalid, or repeated points.
            2.  No check is explicitly done for zero internal angles
                (180 degree direction-change angle) as this is covered
                in other ways, including the `n < 3` check.
    """
    try:  # needed for any bad points or direction changes
        # Check for too few points
        if len(polygon) < 3:
            return False
        # Get starting information
        old_x, old_y = polygon[-2]
        new_x, new_y = polygon[-1]
        new_direction = math.atan2(new_y - old_y, new_x - old_x)
        angle_sum = 0.0
        # Check each point (the side ending there, its angle) and accum. angles
        for ndx, newpoint in enumerate(polygon):
            # Update point coordinates and side directions, check side length
            old_x, old_y, old_direction = new_x, new_y, new_direction
            new_x, new_y = newpoint
            new_direction = math.atan2(new_y - old_y, new_x - old_x)
            if old_x == new_x and old_y == new_y:
                return False  # repeated consecutive points
            # Calculate & check the normalized direction-change angle
            angle = new_direction - old_direction
            if angle <= -math.pi:
                angle += (2 * math.pi)  # make it in half-open interval (-Pi, Pi]
            elif angle > math.pi:
                angle -= (2 * math.pi)
            if ndx == 0:  # if first time through loop, initialize orientation
                if angle == 0.0:
                    return False
                orientation = 1.0 if angle > 0.0 else -1.0
            else:  # if other time through loop, check orientation is stable
                if orientation * angle <= 0.0:  # not both pos. or both neg.
                    return False
            # Accumulate the direction-change angle
            angle_sum += angle
        # Check that the total number of full turns is plus-or-minus 1
        return abs(round(angle_sum / (2 * math.pi) )) == 1
    except (ArithmeticError, TypeError, ValueError):
        return False  # any exception means not a proper convex polygon


def is_valid_polygon(polygon):
    p = Polygon(polygon)
    return p.is_valid


def is_point_inside_polygon(point, polygon):
    p = Polygon(polygon)
    point = Point(point)
    return p.contains(point)


def barycenter(points):
    xSum = 0
    ySum = 0
    for i,point in enumerate(points):
        xSum = xSum + point[0]
        ySum = ySum + point[1]
    x = round(xSum/float(i + 1))
    y = round(ySum/float(i + 1))
    return x,y

####################################################
# Plane interpolation functions with outlier removal

def pad_left(a,v):
    return np.pad(
            a,
            (
                (0,0),
                (1,0),
            ),
            constant_values=v,
        )


def get_regression(a):
    ols = smapi.OLS(
        a[:, 2], # z
        pad_left(a[:, :2], 1),
    )
    return ols.fit()


def predict(regression, to_predict):
    return regression.predict(
        pad_left(to_predict, 1)
    )


def focus_points_from_focused_points(focused_points, points_to_focus, verbose=False):
    """
    Tries to focus points based on some focused_points with a linear interpolation.
    Also works when len(focused_points) = 1,2
    Removes outliers automatically with a bonferoni test.
    Input:
        focused_points = [
                [x,y,z],
                ...
                [x,y,z],
            ]
        points_to_focus = [
                [x,y,z], # z not taken into account
                ...
                [x,y,z],
            ]
        or
        points_to_focus = [
                [x,y],
                ...
                [x,y],
            ]
    Output:
        None if too many outliers or newly_focused_points,
        index of the outliers
    """
    points_to_focus = np.array(points_to_focus, dtype=float)
    points_to_focus = points_to_focus[:, :2]

    focused_points = np.array(focused_points, dtype=float)

    if len(focused_points) in (1,2,):
        return np.insert(
            points_to_focus,
            2,
            np.mean(focused_points, axis=0)[2],
            axis=1,
        )
    # first fit
    regression = get_regression(focused_points)
    if verbose:
        print(regression.summary())
    # find outliers
    id_outliers = np.where(
        regression.outlier_test()[:, 2] < 0.5
    )[0]

    if len(id_outliers) > 0:
        # compute the fit again without outliers
        focused_points_without_outliers = np.delete(
            focused_points,
            id_outliers,
            axis=0,
        )
        if len(focused_points) == 1:
            print("ERROR: This case should not happen")
            return np.insert(
                points_to_focus,
                2,
                focused_points_without_outliers[0][2],
                axis=1,
            )
        regression = get_regression(focused_points_without_outliers)
        if verbose:
            print(regression.summary())

    prediction = predict(regression, points_to_focus)
    newly_focused_points = np.insert(
        points_to_focus,  # x,y
        2,                # insert column z
        prediction,
        axis=1,
    )
    return newly_focused_points, id_outliers
####################################################
# # Test of focus_points_from_focused_points
# x = np.array([0,  0, 10, 10,])
# y = np.array([0, 20, 50, 11,])
# z = 3*x + 5*y + 8 + np.random.normal(0, 5,len(x))
# input = np.stack((x,y,z), axis=1)
# input = np.vstack(
#     [
#         input,
#         [10,10,70],
#     ],
# )
# print(f"{input=}")
# a = focus_points_from_focused_points(
#     input[:5],
#     input.T[:2].T,
#     # verbose=True,
# )
# print(f"{a=}")
# print(f"{a[1]=}")
# print(f"{len(a[1])=}")
####################################################


#######################################################
# functions to select focus points for entire substrate
def polygon_area(points):
    """
    from https://stackoverflow.com/a/30408825/10832217
    Points must be ordered (clockwise or counterc)
    """
    points = np.array(points)
    return 0.5*np.abs(
            np.dot(
                points[:, 0],
                np.roll(points[:, 1], 1))
            -np.dot(
                points[:, 1],
                np.roll(points[:, 0], 1)
        ))


def get_substrate_focus_points(focus_points, n_substrate_focus_points):
    """
    input: set of focus points, typically all focus points of all grids on substrate
    outupt:
        n-1 points from the convex hull that maximize area of their polygon
        1 additional point close to the barycenter of all focus points
    These substrate focus points can be used to compute a first focus plane
    for the entire substrate
    """

    if len(focus_points) < n_substrate_focus_points:
        return None

    hull_points = focus_points[
                    ConvexHull(focus_points).vertices]
    if len(hull_points) < n_substrate_focus_points-1:
        return None

    substrate_focus_points = max(
        itertools.combinations(
            hull_points,
            n_substrate_focus_points-1),
        key=polygon_area)

    focus_center_point = focus_points[np.argmin(
                            cdist(
                                [np.mean(
                                    focus_points,
                                    axis=0)],
                                focus_points
                            ))]
    return np.append(
            substrate_focus_points,
            [focus_center_point],
            axis=0)
#######################################################
#######################################################