import csv
import os
import time
import PyPhenom as ppi


PPAPI_CREDENTIALS_FILENAME = 'credentials/ppapi_credentials.txt'

saveFolder = "tfs_test"

dwellTime = 500E-9 # Seconds
waitTime = 0 # Seconds
overlap = 10 # %
ACB = False # Bool Auto / contrast brightness on each image
bitDepth16Bit = False # False = 8 bit mages, True = 16 bit images

numberInX = 6
numberInY = 10


def load_csv(file_name):
    with open(file_name, 'r') as file:
        csv_reader = csv.reader(file)
        content = []
        for row in csv_reader:
            if len(row) == 1:
                row = row[0]
            content.append(row)
    return content


if __name__ == '__main__':
    i = 1
    saveFolderFinal = saveFolder
    while os.path.exists(saveFolderFinal):
        saveFolderFinal = saveFolder + "_" + str(i)
        i += 1
    os.makedirs(saveFolderFinal)

    phenomID, username, password = load_csv(PPAPI_CREDENTIALS_FILENAME)

    phenom = ppi.Phenom(phenomID, username, password)

    scanParams = ppi.ScanParamsEx()
    scanParams.dwellTime = dwellTime
    scanParams.scale = 1.0
    scanParams.size = ppi.Size(1920,1200)
    scanParams.hdr = bitDepth16Bit
    scanParams.center = ppi.Position(0,0)
    scanParams.detector = ppi.DetectorMode.All
    scanParams.nFrames = 2

    i = 0
    stepSize = phenom.GetHFW() * (100 - overlap)/100
    currentPos = phenom.GetStageModeAndPosition().position
    for y in range(numberInY):
        for x in range(numberInX):
            i += 1
            print("Acquiring image " + str(i) + "/" + str(numberInX*numberInY))

            time.sleep(waitTime)

            if (ACB):
                phenom.SemAutoContrastBrightness()

            xPos = x * stepSize + currentPos.x
            yPos = y * stepSize * scanParams.size.height/scanParams.size.width + currentPos.y
            phenom.MoveTo(xPos,yPos)
            acq = phenom.SemAcquireImageEx(scanParams)

            ppi.Save(acq, os.path.join(saveFolderFinal, "image_x_" + str(x) + "_y_" + str(y) + ".tiff"))
            acq.image = acq.image.__invert__()
            ppi.Save(acq, os.path.join(saveFolderFinal, "image_x_" + str(x) + "_y_" + str(y) + "inv.tiff"))

    print("finished")
