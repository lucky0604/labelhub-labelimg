from collections import defaultdict

import sys

from labelImg import loadLabels
import argparse
import lxml.etree
import matplotlib
import numpy as np

matplotlib.use("Qt5Agg")
import matplotlib.pyplot as plt

from libs.pascal_voc_io import PascalVocReader
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QSize


def parse():
    parser = argparse.ArgumentParser()
    parser.add_argument('file', type=str)
    args = parser.parse_args()
    root = lxml.etree.fromstring(open(args.file).read())
    width = int(root.xpath("/annotation/size/width")[0].text)
    height = int(root.xpath("/annotation/size/height")[0].text)
    size = QSize(width, height)

    categories = (
        ("Objects", "object"),
        ("Suction Regions", "suction_region")
    )
    reader = PascalVocReader(args.file, categories)
    raw_shapes = reader.getShapes()

    shapes = defaultdict(list)

    for cat_id, shape in loadLabels(raw_shapes, categories):
        shapes[cat_id].append(shape)
        mask = np.copy(shape.get_unoccluded_mask(size))

        plt.figure()
        plt.title(f"{cat_id} {shape.label} {repr(shape.attributes)}")
        plt.imshow(mask)
        plt.show()


def main():
    app = QApplication(sys.argv)
    parse()
    app.quit()


if __name__ == "__main__":
    main()
