# Copyright (c) 2016 Tzutalin
# Create by TzuTaLin <tzu.ta.lin@gmail.com>

try:
    from PyQt5.QtGui import QImage
except ImportError:
    from PyQt4.QtGui import QImage

from base64 import b64encode, b64decode
from libs.pascal_voc_io import PascalVocWriter
from libs.pascal_voc_io import XML_EXT
import os.path
import sys


class LabelFileError(Exception):
    pass


class LabelFile(object):
    # It might be changed as window creates. By default, using XML ext
    # suffix = '.lif'
    suffix = XML_EXT

    def __init__(self, filename=None):
        self.shapes = ()
        self.imagePath = None
        self.imageData = None
        self.verified = False

    def savePascalVocFormat(self, filename, shapes, imagePath, imageData, labelCategories):
        imgFolderPath = os.path.dirname(imagePath)
        imgFolderName = os.path.split(imgFolderPath)[-1]
        imgFileName = os.path.basename(imagePath)
        # imgFileNameWithoutExt = os.path.splitext(imgFileName)[0]
        # Read from file path because self.imageData might be empty if saving to
        # Pascal format
        image = QImage()
        image.load(imagePath)
        imageShape = [image.height(), image.width(),
                      1 if image.isGrayscale() else 3]
        writer = PascalVocWriter(imgFolderName, imgFileName,
                                 imageShape, localImgPath=imagePath, labelCategories=labelCategories)
        writer.verified = self.verified

        for _, categoryId in labelCategories:
            for shape in shapes[categoryId]:
                if shape['type'] == 'rect':
                    points = shape['points']
                    label = shape['label']
                    attributes = shape['attributes']
                    bndbox = LabelFile.convertPoints2BndBox(points)
                    writer.addBndBox(categoryId, bndbox[0], bndbox[1], bndbox[2], bndbox[3], label, attributes)
                elif shape['type'] == 'polygon':
                    points = shape['points']
                    label = shape['label']
                    attributes = shape['attributes']
                    writer.addPolygon(categoryId, points, label, attributes)
                elif shape['type'] == 'brush':
                    history = shape['history']
                    size = shape['size']
                    label = shape['label']
                    offset = shape['offset']
                    attributes = shape['attributes']
                    writer.addBrush(categoryId, size, offset, history, label, attributes)
        writer.save(targetFile=filename)
        return

    def toggleVerify(self):
        self.verified = not self.verified

    @staticmethod
    def isLabelFile(filename):
        fileSuffix = os.path.splitext(filename)[1].lower()
        return fileSuffix == LabelFile.suffix

    @staticmethod
    def convertPoints2BndBox(points):
        xmin = float('inf')
        ymin = float('inf')
        xmax = float('-inf')
        ymax = float('-inf')
        for p in points:
            x = p[0]
            y = p[1]
            xmin = min(x, xmin)
            ymin = min(y, ymin)
            xmax = max(x, xmax)
            ymax = max(y, ymax)

        # # Martin Kersner, 2015/11/12
        # # 0-valued coordinates of BB caused an error while
        # # training faster-rcnn object detector.
        # if xmin < 1:
        #     xmin = 1
        #
        # if ymin < 1:
        #     ymin = 1

        return (int(xmin), int(ymin), int(xmax), int(ymax))
