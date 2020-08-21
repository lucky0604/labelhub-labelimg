try:
    from PyQt5.QtGui import *
    from PyQt5.QtCore import *
    from PyQt5.QtWidgets import *
except ImportError:
    from PyQt4.QtGui import *
    from PyQt4.QtCore import *

import numpy as np


def point_to_tuple(pt):
    return (pt.x(), pt.y())


# class SerializableBitmap(QBitmap):
#
#     def __setstate__(self, state):
#         import ipdb; ipdb.set_trace()
#         # pass
#
#     def __getstate__(self):
#         image = self.toImage().convertToFormat(QImage.Format_Indexed8)
#         ptr = image.constBits()
#         ptr.setsize(image.byteCount())
#         mask = np.frombuffer(ptr, count=image.byteCount(), dtype=np.uint8).reshape(
#             (image.height(), image.width()))
#         return mask
#         # import ipdb; ipdb.set_trace()


class Brush(object):
    highlightColor = QColor(220, 0, 0)
    highlightBorderColor = QColor(220, 220, 220)
    fillColor = QColor(0, 220, 0)

    def __init__(self, size, label=None, attributes=(), history=(), offset=None):
        self.label = label
        self.attributes = attributes
        self.size = size
        self.bitmap = QBitmap(size)
        self.bitmap.clear()
        self.boundaryBitmap = QBitmap(size)
        self.boundaryBitmap.clear()
        self._image = None
        self._rect = None
        self._mask = None
        self.painter = QPainter()
        self.selected = False
        self.fill = False
        if offset is None:
            self.offset = QPoint(0, 0)
        else:
            self.offset = offset
        self.history = list(history)
        self.loadHistory(history)

    def __getstate__(self):
        return dict(
            label=self.label,
            size=self.size,
            attributes=self.attributes,
            history=self.history,
            offset=self.offset,
            _mask=self._mask,
            _rect=self._rect,
        )

    def __setstate__(self, state):
        self.__init__(size=state['size'], label=state['label'], attributes=state['attributes'],
                      history=state['history'], offset=state['offset'])
        self._mask = state['_mask']
        self._rect = state['_rect']

    @property
    def labelWithAttributes(self):
        if len(self.attributes) > 0:
            return f"{self.label} ({', '.join(self.attributes)})"
        else:
            return self.label

    def addPoint(self, point, radius, erasing, record_history=True):
        if erasing:
            self._addPoint(point, self.bitmap, radius, Qt.color0)
            self._addPoint(point, self.boundaryBitmap, radius - 2, Qt.color0)
        else:
            self._addPoint(point, self.bitmap, radius, Qt.color1)
            self._addPoint(point, self.boundaryBitmap, radius + 2, Qt.color1)
        if record_history:
            self.history.append(('addPoint', (point_to_tuple(point), radius, erasing)))

    def loadHistory(self, history):
        for hist_type, hist_data in history:
            if hist_type == 'addPoint':
                point, radius, erasing = hist_data
                point = QPointF(point[0], point[1])
                self.addPoint(point, radius, erasing, record_history=False)
            elif hist_type == 'addLine':
                pos1, pos2, radius, erasing = hist_data
                pos1 = QPointF(pos1[0], pos1[1])
                pos2 = QPointF(pos2[0], pos2[1])
                self.addLine(pos1, pos2, radius, erasing, record_history=False)
            else:
                raise ValueError(f"Unrecognized history type {hist_type}")

    def _addPoint(self, point, bitmap, radius, color):
        p = self.painter
        p.begin(bitmap)
        p.setPen(color)
        p.setBrush(color)
        p.drawEllipse(point, radius, radius)
        p.end()

    def addLine(self, pos1, pos2, radius, erasing, record_history=True):
        if erasing:
            self._addLine(pos1, pos2, self.bitmap, radius, Qt.color0)
            self._addLine(pos1, pos2, self.boundaryBitmap, radius - 2, Qt.color0)
        else:
            self._addLine(pos1, pos2, self.bitmap, radius, Qt.color1)
            self._addLine(pos1, pos2, self.boundaryBitmap, radius + 2, Qt.color1)
        if record_history:
            self.history.append(('addLine', (point_to_tuple(pos1), point_to_tuple(pos2), radius, erasing)))

    def _addLine(self, pos1, pos2, bitmap, radius, color):
        p = self.painter
        p.begin(bitmap)
        pen = QPen()
        pen.setColor(color)
        pen.setWidth(radius * 2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(color)
        p.drawLine(pos1, pos2)
        p.end()

    def _paint(self, p, bitmap, color):
        pen = QPen(color)
        p.setPen(pen)
        bgMode = p.backgroundMode()
        p.setOpacity(0.5)
        p.setBackgroundMode(Qt.TransparentMode)
        p.drawPixmap(self.offset.x(), self.offset.y(), bitmap)
        p.setBackgroundMode(bgMode)

    def paint(self, p, scale=None, prev_shapes=None):

        """
        import matplotlib.pyplot as plt
        import numpy as np
        color_list = plt.cm.Set1(np.linspace(0, 1, 9))
        color_list = [(x*255).astype(int).tolist()[:3] for x in color_list]
        color_list
        """

        color_list = [[228, 26, 28],
                     [55, 126, 184],
                     [77, 175, 74],
                     [152, 78, 163],
                     [255, 127, 0],
                     [255, 255, 51],
                     [166, 86, 40],
                     [247, 129, 191],
                     [153, 153, 153]]

        fillColor = self.fillColor
        if self.label is not None and self.label.startswith("Rank"):
            fillColor = QColor(*color_list[int(self.label[4])-1])

        if self.fill:
            self._paint(p, self.boundaryBitmap, self.highlightBorderColor)
            self._paint(p, self.bitmap, fillColor)
        else:
            self._paint(p, self.bitmap, fillColor)

    def highlightClear(self):
        pass

    def containsPoint(self, pos):
        assert self._mask is not None
        x = int(pos.x() - self.offset.x())
        y = int(pos.y() - self.offset.y())
        if x < 0 or y < 0 or x >= self._mask.shape[1] or y >= self._mask.shape[0]:
            return False
        return self._mask[y, x]

    def boundingRect(self):
        assert self._rect is not None
        return QRect(
            self._rect.x() + self.offset.x(),
            self._rect.y() + self.offset.y(),
            self._rect.width(),
            self._rect.height(),
        )

    def moveBy(self, offset):
        self.offset += offset

    def close(self):
        # self.bitmap.
        self._image = self.bitmap.toImage().convertToFormat(QImage.Format_Indexed8)
        ptr = self._image.constBits()
        ptr.setsize(self._image.byteCount())
        mask = np.frombuffer(ptr, count=self._image.byteCount(), dtype=np.uint8).reshape(
            self._image.height(), self._image.bytesPerLine())[:self._image.height(), :self._image.width()]
        xs, ys = np.where(mask)
        if len(xs) == 0:
            min_x = 0
            min_y = 0
            max_x = 0
            max_y = 0
        else:
            min_x = xs.min()
            min_y = ys.min()
            max_x = xs.max()
            max_y = ys.max()
        self._mask = mask
        self._rect = QRect(min_x, min_y, max_x - min_x, max_y - min_y)

    def get_unoccluded_mask(self, size):
        assert tuple(self._mask.shape) == (size.height(), size.width())
        return self._mask
