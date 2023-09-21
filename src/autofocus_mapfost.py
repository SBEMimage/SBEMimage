# -*- coding: utf-8 -*-

# ==============================================================================
#   This source file is part of SBEMimage (github.com/SBEMimage)
#   (c) 2018-2020 Friedrich Miescher Institute for Biomedical Research, Basel,
#   and the SBEMimage developers.
#   This software is licensed under the terms of the MIT License.
#   See LICENSE.txt in the project root folder.
# ==============================================================================

"""This module contains all the functions related to mapfost autofocus routine on SBEMimage.

"""

import os
import time
import glob
import shutil
import tempfile
import numpy as np

from PIL import Image
from typing import Union
from multiprocessing import Pool
from mapfost import mapfost as mf
from scipy.optimize import minimize

try:
    import pythoncom
    import win32com.client  # required to use CZEMApi.ocx (Carl Zeiss EM API)
    from win32com.client import VARIANT  # required for API function calls
except:
    pass


class RunAutoFoc:

    def __init__(self, exps_dir, exp_id, sem_api):
        self.exps_dir = exps_dir
        self.exp_id = exp_id
        self.additional_cycle_time = 0
        self.path_to_exp = self.exps_dir + self.exp_id
        self.result_path = self.path_to_exp + "/Result"
        self.perturbed_ims_path = self.path_to_exp + "/Test_Images" + "_" + self.exp_id
        self.sem_api = sem_api
        self.create_exps_dir()

    def create_exps_dir(self):
        if not os.path.exists(self.path_to_exp):
            os.mkdir(self.path_to_exp)
        if not os.path.exists(self.result_path):
            os.mkdir(self.result_path)
        if not os.path.exists(self.perturbed_ims_path):
            os.mkdir(self.perturbed_ims_path)

    def predict_refresh_time(self):
        no_of_pixels = np.multiply(*self.get_store_resolution())
        dwell_time_ns = 50.*2**(int(self.sem_api.Get("DP_SCANRATE")[1]))
        refresh_time_sec = dwell_time_ns*no_of_pixels*10**-9*1.1 + 0.08
        # print("refresh_time_sec", refresh_time_sec,dwell_time_ns*no_of_pixels, dwell_time_ns, no_of_pixels)
        return refresh_time_sec

    def delete_exps_dir(self):
        if os.path.isdir(self.path_to_exp):
            shutil.rmtree(self.path_to_exp)

    def get_store_resolution(self):
        store_resolution_response = self.sem_api.Get('DP_IMAGE_STORE')
        store_resolution_tuple = tuple([int(sr) for sr in store_resolution_response[1].replace(" ","").split("*")])
        # print("store_resolution",  store_resolution_tuple)
        return store_resolution_tuple

    def acquire_frame(self, save_as):
        t0 = time.time()
        self.sem_api.Execute('CMD_UNFREEZE_ALL')
        time.sleep(self.predict_refresh_time())
        res = self.sem_api.Grab(0, 0, 1024, 768, 0, save_as)
        # print("time taken for grab", time.time()-t0)
        if res != 0:
            raise ValueError(f'Error during image acquisiton: {res}')

    def get_wd(self):
        return float(self.sem_api.Get('AP_WD', 0)[1])

    def get_mag(self):
        return float(self.sem_api.Get('AP_MAG', 0)[1])

    def set_wd(self, target_wd):
        variant = VARIANT(pythoncom.VT_R4, target_wd)
        ret_val = self.sem_api.Set('AP_WD', variant)[0]
        if ret_val == 0:
            return True
        else:
            return False

    def get_pix_size_um(self):
        pix_size_um = self.sem_api.Get('AP_PIXEL_SIZE')[1]*10**6
        corrected_pix_size_um = pix_size_um / int(self.get_store_resolution()[0]/1024)
        return corrected_pix_size_um

    def get_stig_y(self):
        return float(self.sem_api.Get('AP_STIG_Y', 0)[1])

    def set_stig_y(self, target_stig_y):
        variant_y = VARIANT(pythoncom.VT_R4, target_stig_y)
        ret_val = self.sem_api.Set('AP_STIG_Y', variant_y)[0]
        if ret_val == 0:
            return True
        else:
            return False

    def get_stig_x(self):
        return float(self.sem_api.Get('AP_STIG_X', 0)[1])

    def set_stig_x(self, target_stig_x):
        variant_x = VARIANT(pythoncom.VT_R4, target_stig_x)
        ret_val = self.sem_api.Set('AP_STIG_X', variant_x)[0]
        if ret_val == 0:
            return True
        else:
            return False

    def get_wd_and_stig_vals(self):
        ax = self.sem_api.Get('AP_STIG_X', 0)[1]
        ay = self.sem_api.Get('AP_STIG_Y', 0)[1]
        z = self.sem_api.Get('AP_WD', 0)[1]*1e6
        return np.array([z,ax,ay])

    def set_wd_and_stig_vals(self, aberr):
        self.sem_api.Set("AP_STIG_X", VARIANT(pythoncom.VT_R4, aberr[1]))
        self.sem_api.Set("AP_STIG_Y", VARIANT(pythoncom.VT_R4, aberr[2]))
        self.sem_api.Set("AP_WD", VARIANT(pythoncom.VT_R4, aberr[0]*1e-6))
        time.sleep(0.2) # very imp, otherwise the scans can be discontinuous in case of large shifts
        return True

    def induce_aberration(self,induce_aberration):
        self.sem_api.Execute('CMD_UNFREEZE_ALL')
        time.sleep(self.predict_refresh_time())
        current_aberr_params = self.get_wd_and_stig_vals()
        final_aberr_params = np.add(induce_aberration, current_aberr_params)
        aberr_normed = np.linalg.norm(induce_aberration)
        time.sleep(0.1 + np.min([0.01*aberr_normed,1]))# very imp, otherwise the scans can be discontinuous in case of large shifts
        self.set_wd_and_stig_vals(final_aberr_params)

    def grab_and_save_perturbed_ims(self, aberr_perturbation):
        current_aberr_params = self.get_wd_and_stig_vals()
        final_aberr_params = [np.add(aberr, current_aberr_params) for aberr in aberr_perturbation]
        for key, par in enumerate(final_aberr_params):
            self.set_wd_and_stig_vals(par)
            save_as = self.perturbed_ims_path + "/" + "_".join( [str(ab) for ab in aberr_perturbation[key]]) + ".tif"
            self.acquire_frame(save_as)
        self.set_wd_and_stig_vals(current_aberr_params)
        return 0

    def reverse_aberr(self, save_result=False):
        current_aberr_params = self.get_wd_and_stig_vals()
        final_aberr_params = np.add([-1 * self.final_res[0], -1 * self.final_res[1],
                                     -1 * self.final_res[2]], current_aberr_params)
        self.set_wd_and_stig_vals(final_aberr_params)
        self.sem_api.Execute('CMD_UNFREEZE_ALL')
        time.sleep(self.predict_refresh_time())
        self.sem_api.Execute('CMD_FREEZE_ALL')
        if save_result:
            self.acquire_frame(self.result_path + "//result.tif")
        return final_aberr_params

    def freeze_frame(self, waitTillComplete=0):
        self.sem_api.Execute('CMD_FREEZE_ALL')
        if waitTillComplete:
            time.sleep(self.predict_refresh_time())

def est_aberr_proc(perturbed_ims, aberr_perturbations, crop_ref, mapfost_params):
    mapfost_params['crop_ref'] = crop_ref
    cr_valid , crop_ref, res = mf.est_aberr([perturbed_ims[0], perturbed_ims[1]], aberr_perturbations, **mapfost_params)
    # print(" cr_valid, crop_ref, res",  cr_valid, crop_ref, res)
    return cr_valid, crop_ref, res

def process_ims_and_est_aberr(aberr_perturbations, test_imarrs, mapfost_params={}):

    """
    Returns the estimated aberration using two test images which are split into smaller patches of size
    mapfost_params['crop_size']. The pairs are then aligned (single pixel accuracy) and are passed to
    the mapfost pypi library to estimate aberrations.
    The final estimation is the mean of the multiple estimations returned from multiple patch pairs.

    Args:
        aberr_perturbations: the pair of test defocus in um eg. [4,-4]
        test_imarrs: the pair of test images as numpy array. eg. [np_arr, np_arr]
        mapfost_params: dict containing the following keys and their values.
                        'num_aperture' : eg. 0.002, the numerical aperture of the imaging system
                        'stig_rot_deg' : eg. -20, the rotation between the stigmation plane and imaging plane in degrees
                        'stig_scale' : eg. 2, the correction factor to convert the stig % unit (as in SEM) to um.
                        'test_ims_aligned': 0, set this to 0 if the test_ims are not already aligned.
                        'use_bessel' : 1, bessel MTF is used if True, the Gaussian approx is used if False, (recommended Gaussian)
                        'crop_size': [768,768], the fov will be split into smaller patches of this size (regular only)

    Returns:
        the estimated aberration vector of length 3. [defocus(um), astigx(%), astigy(%)]. None in case of exception.
    """

    result_procs = []

    def proc_res(ret_val):
        if ret_val[0]:
            if ret_val[2].success:
                result_procs.append([True, ret_val[2].x])
            else:
                print("optimizer failed for crop ref ", ret_val[1])
        else:
            print("cropping not valid for crop ref ", ret_val[1])

    crop_refs = get_crop_refs_from_scan_size(test_imarrs[0].shape, mapfost_params['crop_size'])

    p = Pool(len(crop_refs))
    _ = [p.apply_async(est_aberr_proc, args=[test_imarrs, aberr_perturbations, crop_refs[i][::-1], mapfost_params], callback=proc_res)
         for i in range(len(crop_refs))]

    p.close()
    p.join()
    if len(result_procs) > 0:
        est_aberr = np.mean(np.array(result_procs, dtype=object)[:,1], axis=0)
    else:
        est_aberr = None

    return est_aberr


def run(sem_api, working_distance_perturbations, exps_dir=None, mapfost_params={},
        induce_aberration_vec=[0,0,0], max_iters=7, convergence_threshold = 0.2,
        aberr_mode_bools = [1,1,1],large_aberrations=0, max_wd_stigx_stigy=None):

    exps_dir = [exps_dir, tempfile.gettempdir()][exps_dir is None]

    corrections = []
    iter = 0
    aberr_estimation = [10,10,10]
    while np.linalg.norm(aberr_estimation) > convergence_threshold and iter < max_iters:
        iter+=1
        if large_aberrations:
            if iter < 3:
                mapfost_params['radial_aperture'] = 0.1
                working_distance_perturbations = [20]
            else:
                mapfost_params['radial_aperture'] = 0.25
                working_distance_perturbations = [4]
        for exp_itr, ta in enumerate(working_distance_perturbations):
            aberr_perturbation = [[-1*ta, 0, 0], [ta, 0, 0]]
            exp_id =  str(int(time.time())) + "_" + str(exp_itr)
            af = RunAutoFoc(exps_dir, exp_id, sem_api=sem_api)

            if np.any(induce_aberration_vec) !=0:
                af.induce_aberration(induce_aberration_vec)
                print("induced aberr, ", induce_aberration_vec)
                induce_aberration_vec = [0,0,0]

            af.grab_and_save_perturbed_ims(aberr_perturbation)
            pix_size_um = af.get_pix_size_um()
            mapfost_params['pix_size_um'] = pix_size_um
            perturbed_ims, aberr_perturbation = get_perturbed_ims(af.perturbed_ims_path)

            aberr_perturbation_defocus = [aberr_perturbation[0][0], aberr_perturbation[1][0]]

            aberr_estimation = process_ims_and_est_aberr(aberr_perturbation_defocus, perturbed_ims, mapfost_params)

            if aberr_estimation is not None:
                try:
                    af.final_res = np.multiply(aberr_estimation,aberr_mode_bools)
                    print("max_wd_stigx_stigy", max_wd_stigx_stigy)
                    if max_wd_stigx_stigy is not None:
                        clipped_res = [np.clip(-1*max_wd_stigx_stigy[ii],
                                                  max_wd_stigx_stigy[ii],
                                                  af.final_res[ii]) for ii in range(3)]
                        af.final_res = clipped_res
                    aberr_estimation = af.final_res
                except Exception as e:
                    print("Could not multiply aberr_mode_bools (#1) on aberr est(#2) ",aberr_mode_bools, aberr_estimation)
                af.reverse_aberr(save_result=False)
                corrections.append(list(np.round(af.final_res,3)))
            print("corrections", corrections[-1])
    return corrections

def calibrate(sem_api, mapfost_params={},
              calib_mode=None,exps_dir=None):

    working_distance_perturbations = [4]

    exps_dir = [exps_dir, tempfile.gettempdir()][exps_dir is None]

    if calib_mode == "defocus":
        induce_aberration_vec = [8,0,0]
    elif calib_mode == "astig":
        induce_aberration_vec = [0,2,2]
    else:
        return "No calibration mode (defocus or astig) given"
    for exp_itr, ta in enumerate(working_distance_perturbations):
        aberr_perturbation = [[-1*ta, 0, 0], [ta, 0, 0]]
        exp_id =  str(int(time.time())) + "_" + str(exp_itr)
        af = RunAutoFoc(exps_dir, exp_id, sem_api=sem_api)
        if np.any(induce_aberration_vec) !=0:
            af.induce_aberration(induce_aberration_vec)
            print("induced aberr, ", induce_aberration_vec)
            cp_induce_aberr= induce_aberration_vec
            induce_aberration_vec = [0,0,0]
        af.grab_and_save_perturbed_ims(aberr_perturbation)
        pix_size_um = af.get_pix_size_um()
        mapfost_params['pix_size_um'] = pix_size_um
        perturbed_ims, aberr_perturbation = get_perturbed_ims(af.perturbed_ims_path)

        aberr_perturbation_defocus = [aberr_perturbation[0][0], aberr_perturbation[1][0]]

        calib_params = get_caliberation_for_mapfost_routine(cp_induce_aberr, aberr_perturbation_defocus,
                                                            perturbed_ims, mapfost_params,calib_mode=calib_mode)
        af.induce_aberration(np.multiply(cp_induce_aberr,-1))
    af.freeze_frame(waitTillComplete=1)
    return calib_params

def get_calibrated_probe_convergence_angle(target_defocus, estimated_defocus, mapfost_params):
    prior_probe_convergence_angle = mapfost_params['num_aperture']
    if estimated_defocus*target_defocus>0:
        cpca = np.round(np.sqrt(prior_probe_convergence_angle**2*estimated_defocus/target_defocus),5)
    else:cpca = None
    return cpca

def rotate_astigxy(astig_vec, alpha_deg):
    ax, ay = astig_vec
    axr = np.subtract(ax * np.cos(np.radians(2*alpha_deg)), ay * np.sin(np.radians(-2*alpha_deg)))
    ayr = np.add(ax * np.sin(np.radians(-2*alpha_deg)), ay * np.cos(np.radians(2*alpha_deg)))
    return axr, ayr

def get_astig_scaling_rotation_param(target_astig, est_astig, mapfost_params):
    def cost_rot(x, est_astig, target_astig, scale):
        axr, ayr = rotate_astigxy(np.multiply(est_astig, scale), x)
        return np.linalg.norm(np.subtract([axr, ayr], target_astig))

    scale = np.linalg.norm(target_astig) / np.linalg.norm(est_astig)
    scale_signs = [[1, 1]]
    print("SCALE", scale)
    astig_params = mapfost_params['stig_rot_deg']
    resS = [minimize(cost_rot, astig_params, args=(est_astig, target_astig, np.multiply(scale, scale_signs[ix])),
                     method="L-BFGS-B") for ix in range(len(scale_signs))]
    final_costs = [res.fun for res in resS]
    print("final_costs", final_costs)
    min_cost_arg = np.argsort(final_costs)[0]
    scale_sign_est = scale_signs[min_cost_arg]
    return list([float(np.round(resS[min_cost_arg].x, 2)), list(np.round(np.multiply(scale_sign_est, [1 / scale, 1 / scale]),2))])

def get_caliberation_for_mapfost_routine(target_aberration, aberr_perturbations, test_imarrs, mapfost_params={}, calib_mode=None):

    result_procs = []

    crop_refs = get_crop_refs_from_scan_size(test_imarrs[0].shape, mapfost_params['crop_size'])

    def proc_res(ret_val):
        if ret_val[0]:
            if ret_val[2].success:
                result_procs.append([True, ret_val[2].x])
            else:
                print("optimizer failed for crop ref ", ret_val[1])
        else:
            print("cropping not valid for crop ref ", ret_val[1])

    p = Pool(len(crop_refs))
    _ = [p.apply_async(est_aberr_proc, args=[test_imarrs, aberr_perturbations, crop_refs[i][::-1], mapfost_params],
                       callback=proc_res)
         for i in range(len(crop_refs))]

    p.close()
    p.join()
    if len(result_procs) > 0:
        est_aberr = np.mean(np.array(result_procs, dtype=object)[:, 1], axis=0)
    else:
        est_aberr = None
    if calib_mode=="defocus":
        calr = get_calibrated_probe_convergence_angle(target_aberration[0], est_aberr[0], mapfost_params)
    elif calib_mode=="astig":
        calr = get_astig_scaling_rotation_param(target_aberration[1:], est_aberr[1:], mapfost_params)
    return calr

def get_crop_refs_from_scan_size(scan_size:Union[list,np.ndarray], crop_size:Union[list, np.ndarray])->np.ndarray:

    nrow, ncol = [int(ssz/crop_size[issz]) for issz, ssz in enumerate(scan_size)]
    crop_refs = [[nr*crop_size[0], nc*crop_size[1]] for nr in range(nrow) for nc in range(ncol)]

    return crop_refs


def get_masks(edge_len,in_out_cross=[1,1,1], reverse=False, in_rad=None):

    radius = int(edge_len/2)
    maskS = []
    if in_out_cross[0]:

        if reverse:
            in_circle_binary_mask = np.sign(np.abs(np.add(np.sign(np.subtract(radius ** 2,
                                                                            np.add(*np.square(
                                                                                np.meshgrid(range(-1 * radius, radius),
                                                                                            range(-1 * radius, radius)
                                                                                            )
                                                                                )))), -1))).astype(float)
        else:


            in_circle_binary_mask = np.sign(np.add(np.sign(np.subtract(radius ** 2,
                                              np.add(*np.square(np.meshgrid(range(-1 * radius, radius),
                                                                            range(-1 * radius, radius)
                                                                            )
                                                                )))),1)).astype(float)
        maskS.append(in_circle_binary_mask)

    if in_out_cross[1]:

        if reverse:
            out_circle_binary_mask = np.sign(np.add(np.sign(np.subtract(radius ** 2,
                                              np.add(*np.square(np.meshgrid(range(-1 * radius, radius),
                                                                            range(-1 * radius, radius)
                                                                            )
                                                                )))),1)).astype(float)
        else:

            out_circle_binary_mask = np.sign(np.abs(np.add(np.sign(np.subtract(radius ** 2,
                                              np.add(*np.square(np.meshgrid(range(-1 * radius, radius),
                                                                            range(-1 * radius, radius)
                                                                            )
                                                                )))),-1))).astype(float)
        maskS.append(out_circle_binary_mask)
    if in_out_cross[2]:

        if reverse:
            cross_mask = np.abs(np.sign(np.abs(np.multiply(*np.meshgrid(range(-1 * radius, radius),
                                                                       range(-1 * radius, radius)
                                                                       )
                                                          )))).astype(float)
        else:
            cross_mask = np.abs(np.subtract(np.sign(np.abs(np.multiply(*np.meshgrid(range(-1 * radius, radius),
                                                                       range(-1 * radius, radius)
                                                                       )
                                                          ))), 1)).astype(float)


        maskS.append(cross_mask)
    if in_rad is not None:
            # radius = in_rad
            if reverse:
                inner_rad_binary_mask = np.sign(np.abs(np.add(np.sign(np.subtract(in_rad ** 2,
                                                                                  np.add(*np.square(
                                                                                      np.meshgrid(
                                                                                          range(-1 * radius, radius),
                                                                                          range(-1 * radius, radius)
                                                                                          )
                                                                                  )))), -1))).astype(float)
            else:

                inner_rad_binary_mask = np.sign(np.add(np.sign(np.subtract(in_rad ** 2,
                                                                           np.add(*np.square(
                                                                               np.meshgrid(range(-1 * radius, radius),
                                                                                           range(-1 * radius, radius)
                                                                                           )
                                                                               )))), 1)).astype(float)
            maskS.append(inner_rad_binary_mask)

    return maskS


def crop_from_ref(perturbed_ims, crop_size, ref=(0, 0)):
    perturbed_ims = np.array(perturbed_ims)
    perturbed_ims = perturbed_ims[ref[0]:ref[0]+int(crop_size[0]), ref[1]:ref[1] + int(crop_size[1])]
    return perturbed_ims

def aberr_perturbation_from_tifname(name):
    aberr_perturbation = [float(aa) for aa in os.path.basename(name).split(".")[0].split("_")]
    return aberr_perturbation

def get_perturbed_ims(perturbed_ims_path):

    perturbed_ims_abs_paths = glob.glob(perturbed_ims_path + "/*.tif")
    perturbed_ims = [np.array(Image.open(imgPath)) for imgPath in perturbed_ims_abs_paths]
    aberr_perturbation = [aberr_perturbation_from_tifname(t) for t in perturbed_ims_abs_paths]

    return perturbed_ims, aberr_perturbation
