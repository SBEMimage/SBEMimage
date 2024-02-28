# TODO: Not part of SBEMimage - testing only - remove from repo

import csv
import os
import PyPhenom as ppi
from PyPhenom import OperationalMode


PPAPI_CREDENTIALS_FILENAME = '../credentials/ppapi_credentials.txt'

saveFolder = "tfs_test"

dwell_time = 500E-9  # Seconds
overlap = 0.10
auto_contrast_brightness = False    # Bool Auto / contrast brightness on each image
bit_depth_16bit = False     # False = 8 bit mages, True = 16 bit images

nx = 6
ny = 10


def init_api():
    phenomID, username, password = load_csv(PPAPI_CREDENTIALS_FILENAME)
    if len(username) == 0:
        username = ''
    if len(password) == 0:
        password = ''
    api = ppi.Phenom(phenomID, username, password)
    return api


def lm_test(api, saveFolderFinal):
    print("setting imaging mode")

    mode = api.GetOperationalMode()
    if mode == OperationalMode.Loadpos:
        api.Load()
    if mode != OperationalMode.LiveNavCam:
        api.MoveToNavCam()

    api.MoveTo(0, 0)
    pixel_size = 2500 * 1e-9    # nm -> m
    width = 912
    hfw = width * pixel_size
    print('HFW set:', hfw)
    api.SetHFW(hfw)

    hfw = api.GetHFW()
    print('HFW get:', hfw)

    print_info(api)

    acqCamParams = ppi.CamParams()  # use default size
    acqCamParams.nFrames = 1

    print("starting LM imaging")

    acq = api.NavCamAcquireImage(acqCamParams)
    print("metadata:", acq.metadata)
    ppi.Save(acq, os.path.join(saveFolderFinal, "image_navcam.tiff"))

    print("finished LM imaging")


def em_test(api, saveFolderFinal):
    print("setting imaging mode")

    mode = api.GetOperationalMode()
    if mode == OperationalMode.Loadpos:
        api.Load()
    if mode != OperationalMode.LiveSem:
        api.MoveToSem()
        
    print_info(api)

    scanParams = ppi.ScanParamsEx()
    scanParams.dwellTime = dwell_time
    scanParams.scale = 1.0
    scanParams.size = ppi.Size(1920, 1200)
    scanParams.hdr = bit_depth_16bit
    scanParams.center = ppi.Position(0, 0)
    scanParams.detector = ppi.DetectorMode.All
    scanParams.nFrames = 1

    print("starting EM imaging")

    i = 0
    stepSize = api.GetHFW() * (1 - overlap)
    currentPos = api.GetStageModeAndPosition().position
    for y in range(ny):
        for x in range(nx):
            i += 1
            print("Acquiring image " + str(i) + "/" + str(nx * ny))

            if auto_contrast_brightness:
                api.SemAutoContrastBrightness()

            xPos = x * stepSize + currentPos.x
            yPos = y * stepSize * scanParams.size.height/scanParams.size.width + currentPos.y
            api.MoveTo(xPos, yPos)

            acq = api.SemAcquireImageEx(scanParams)
            print("metadata:", acq.metadata)
            ppi.Save(acq, os.path.join(saveFolderFinal, "image_x_" + str(x) + "_y_" + str(y) + ".tiff"))
            #acq.image = acq.image.__invert__()
            #ppi.Save(acq, os.path.join(saveFolderFinal, "image_x_" + str(x) + "_y_" + str(y) + "inv.tiff"))

    print("finished EM imaging")
    

def print_info(api):
    print("GetStageStroke:", dump_object(api.GetStageStroke()))
    print("GetStageModeAndPosition:", dump_object(api.GetStageModeAndPosition()))
    
    print("GetHFWRange:", dump_object(api.GetHFWRange()))
    print("GetHFW:", dump_object(api.GetHFW()))

    print("GetSemWDRange:", dump_object(api.GetSemWDRange()))
    print("GetSemWD:", dump_object(api.GetSemWD()))

    print("GetNavCamWDRange:", dump_object(api.GetNavCamWDRange()))
    print("GetNavCamWD:", dump_object(api.GetNavCamWD()))

    print("GetSemHighTensionRange:", dump_object(api.GetSemHighTensionRange()))
    print("GetSemHighTension:", dump_object(api.GetSemHighTension()))


def load_csv(file_name):
    with open(file_name, 'r') as file:
        csv_reader = csv.reader(file)
        content = []
        for row in csv_reader:
            if len(row) == 1:
                row = row[0]
            content.append(row)
    while len(content) < 3:
        content.append('')
    return content


def print_object(obj):
    print(dump_object(obj))


def dump_object(obj):
    s = str(obj)
    if s.startswith('<'):
        s = ''
        for attr in dir(obj):
            if not attr.startswith('_'):
                s += f'{attr}: ' + dump_object(getattr(obj, attr)) + ' '
    return s


if __name__ == '__main__':
    i = 1
    saveFolderFinal = saveFolder
    while os.path.exists(saveFolderFinal):
        saveFolderFinal = saveFolder + "_" + str(i)
        i += 1
    os.makedirs(saveFolderFinal)

    api = init_api()
    lm_test(api, saveFolderFinal)
    em_test(api, saveFolderFinal)
