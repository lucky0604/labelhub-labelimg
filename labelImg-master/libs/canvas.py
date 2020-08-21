from collections import defaultdict

try:
    from PyQt5.QtGui import *
    from PyQt5.QtCore import *
    from PyQt5.QtWidgets import *
except ImportError:
    from PyQt4.QtGui import *
    from PyQt4.QtCore import *

# from PyQt4.QtOpenGL import *

from libs.shape import Shape
from libs.polygon import Polygon
from libs.brush import Brush
from libs.lib import distance

CURSOR_DEFAULT = Qt.ArrowCursor
CURSOR_POINT = Qt.PointingHandCursor
CURSOR_DRAW = Qt.CrossCursor
CURSOR_MOVE = Qt.ClosedHandCursor
CURSOR_GRAB = Qt.OpenHandCursor

laterOnTop = True


# class Canvas(QGLWidget):


class Canvas(QWidget):
    zoomRequest = pyqtSignal(int)
    scrollRequest = pyqtSignal(int, int)
    dragRequest = pyqtSignal(int, int)
    newShape = pyqtSignal()
    selectionChanged = pyqtSignal(bool)
    shapeMoved = pyqtSignal()
    drawingShape = pyqtSignal(bool)

    CREATE, CREATE_POLYGON, CREATE_BRUSH, EDIT, EDIT_BRUSH = list(range(5))

    epsilon = 20  # 420  # 11.0

    def __init__(self, *args, **kwargs):
        super(Canvas, self).__init__(*args, **kwargs)
        # Initialise local state.
        self.mode = self.EDIT
        self.shapes = defaultdict(list)
        self.current = None
        self.selectedShape = None  # save the selected shape here
        self.selectedShapeCopy = None
        self.lineColor = QColor(0, 0, 255)
        self.line = Shape(line_color=self.lineColor)
        self.prevPoint = QPointF()
        self.offsets = QPointF(), QPointF()
        self._scale = 1.0
        self.pixmap = QPixmap()
        self.visible = {}
        self._hideBackround = False
        self.hideBackround = False
        self.hShape = None
        self.hVertex = None
        self._painter = QPainter()
        self._cursor = CURSOR_DEFAULT
        # Menus:
        self.menus = (QMenu(), QMenu())
        # Set widget options.
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.WheelFocus)
        self.verified = False
        self.moving = False
        self.globalP = None
        self._trackCenter = None
        self._trackRadius = 10
        self._trackThickness = 3
        self._showRangeCursor = False
        self._mousePressed = False
        # self.currentBrush = None
        self._prevPosition = None
        self._brushPainter = QPainter()
        self._brushRadius = 10
        self._erasing = False
        self._brushEraseCursor = None
        self._brushDrawCursor = None
        self._updateBrushCursors()

    def showRangeCursor(self):
        return self._showRangeCursor

    def setShowRangeCursor(self, val):
        self._showRangeCursor = val

    def brushRadius(self):
        return self._brushRadius

    def trackThickness(self):
        return self._trackThickness

    def setBrushRadius(self, radius):
        self._brushRadius = radius
        self._updateBrushCursors()

    def trackRadius(self):
        return self._trackRadius

    def setTrackRadius(self, trackRadius):
        self._trackRadius = trackRadius

    def erasing(self):
        return self._erasing

    def setErasing(self, val):
        self._erasing = val

    def scale(self):
        return self._scale

    def setScale(self, scale):
        self._scale = scale
        self._updateBrushCursors()
        self.adjustSize()
        self.update()

    def _updateBrushCursors(self):
        radius = self.brushRadius() * self.scale()
        drawPixmap = QPixmap(radius * 2, radius * 2)
        drawPixmap.fill(Qt.transparent)
        erasePixmap = QPixmap(radius * 2, radius * 2)
        erasePixmap.fill(Qt.transparent)
        p = self._brushPainter
        for pixmap, color in [(drawPixmap, QColor(0, 220, 0, 128)), (erasePixmap, QColor(255, 255, 255, 128))]:
            p.begin(pixmap)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.HighQualityAntialiasing)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawEllipse(0, 0, radius * 2, radius * 2)
            p.end()
        self._brushDrawCursor = QCursor(drawPixmap)
        self._brushEraseCursor = QCursor(erasePixmap)
        # import ipdb;
        # ipdb.set_trace()

    def enterEvent(self, ev):
        self.overrideCursor(self._cursor)

    def leaveEvent(self, ev):
        self.restoreCursor()

    def focusOutEvent(self, ev):
        self.restoreCursor()

    def isVisible(self, shape):
        return self.visible.get(shape, True)

    def drawingRect(self):
        return self.mode == self.CREATE

    def drawingPolygon(self):
        return self.mode == self.CREATE_POLYGON

    def drawingBrush(self):
        return self.mode in [self.CREATE_BRUSH, self.EDIT_BRUSH]

    def editing(self):
        return self.mode == self.EDIT

    def setMode(self, mode):
        self.mode = mode
        if mode in [self.CREATE, self.CREATE_POLYGON, self.CREATE_BRUSH, self.EDIT_BRUSH]:
            self.mousePressed = False
            self.prevPosition = None
            self.line = Shape(line_color=self.lineColor)
            if self.mode != self.EDIT_BRUSH:
                self.unHighlight()
                self.deSelectShape()

    def unHighlight(self):
        if self.hShape:
            self.hShape.highlightClear()
        self.hVertex = self.hShape = None

    def selectedVertex(self):
        return self.hVertex is not None

    def mouseMoveEvent(self, ev):
        """Update line with last point and current coordinates."""
        # print(ev.pos())

        if self.showRangeCursor():
            updateRadius = self.trackRadius() + self.trackThickness()
            if self._trackCenter is not None:
                self.update(self._trackCenter.x() - updateRadius, self._trackCenter.y() - updateRadius, updateRadius * 2,
                            updateRadius * 2)
            self._trackCenter = ev.pos()
            self.update(self._trackCenter.x() - updateRadius, self._trackCenter.y() - updateRadius, updateRadius * 2,
                        updateRadius * 2)
        pos = self.transformPos(ev.pos())

        self.restoreCursor()

        # Polygon drawing.
        if self.drawingRect():
            self.overrideCursor(CURSOR_DRAW)
            if self.current:
                color = self.lineColor
                if self.outOfPixmap(pos):
                    # Don't allow the user to draw outside the pixmap.
                    # Project the point to the pixmap's edges.
                    pos = self.intersectionPoint(self.current[-1], pos)
                elif len(self.current) > 1 and self.closeEnough(pos, self.current[0]):
                    # Attract line to starting point and colorise to alert the
                    # user:
                    pos = self.current[0]
                    color = self.current.line_color
                    self.overrideCursor(CURSOR_POINT)
                    self.current.highlightVertex(0, Shape.NEAR_VERTEX)
                self.line[1] = pos
                self.line.line_color = color
                self.repaint()
                self.current.highlightClear()
            return

        if self.drawingPolygon():
            self.overrideCursor(CURSOR_DRAW)
            if self.current:
                color = self.lineColor
                # if self.outOfPixmap(pos):
                #    # Don't allow the user to draw outside the pixmap.
                #    # Project the point to the pixmap's edges.
                #    return
                #    pos = self.intersectionPoint(self.current[-1], pos)
                if len(self.current) > 1 and self.closeEnough(pos, self.current[0]):
                    # Attract line to starting point and colorise to alert the
                    # user:
                    pos = self.current[0]
                    color = self.current.line_color
                    self.overrideCursor(CURSOR_POINT)
                    self.current.highlightVertex(0, Shape.NEAR_VERTEX)
                self.line[1] = pos
                self.line.line_color = color
                self.repaint()
                self.current.highlightClear()
            return

        if self.drawingBrush():
            if self.erasing():
                self.overrideCursor(self._brushEraseCursor)
            else:
                self.overrideCursor(self._brushDrawCursor)
            if self.mousePressed:
                self.handleDrawingBrush(pos)
            return
        else:
            self.prevPosition = None

        # Polygon copy moving.
        if Qt.RightButton & ev.buttons():
            if self.selectedShapeCopy and self.prevPoint:
                self.overrideCursor(CURSOR_MOVE)
                self.boundedMoveShape(self.selectedShapeCopy, pos)
                self.repaint()
            elif self.selectedShape:
                self.selectedShapeCopy = self.selectedShape.copy()
                self.repaint()
            return

        # Polygon/Vertex moving.
        if Qt.LeftButton & ev.buttons():
            if self.selectedVertex():
                self.boundedMoveVertex(pos)
                self.shapeMoved.emit()
                self.repaint()
            elif self.selectedShape and self.prevPoint:
                self.overrideCursor(CURSOR_MOVE)
                self.boundedMoveShape(self.selectedShape, pos)
                self.shapeMoved.emit()
                self.repaint()
            elif self.moving:
                globalP = ev.globalPos()
                if self.globalP:
                    v_delta = globalP.y() - self.globalP.y()
                    h_delta = globalP.x() - self.globalP.x()
                    v_delta and self.dragRequest.emit(v_delta, Qt.Vertical)
                    h_delta and self.dragRequest.emit(h_delta, Qt.Horizontal)
                self.globalP = globalP
                self.overrideCursor(CURSOR_MOVE)
            return

        # Just hovering over the canvas, 2 posibilities:
        # - Highlight shapes
        # - Highlight vertex
        # Update shape/vertex fill and tooltip value accordingly.
        self.setToolTip("Image")

        for shape in [self.hShape] + [s for s in self.sortedShapes if self.isVisible(s)]:
            if shape is not None and not isinstance(shape, Brush):
                index = shape.nearestVertex(pos, self.epsilon / self.scale())
                if index is not None:
                    if self.selectedVertex():
                        self.hShape.highlightClear()
                    self.hVertex, self.hShape = index, shape
                    shape.highlightVertex(index, shape.MOVE_VERTEX)
                    self.overrideCursor(CURSOR_POINT)
                    self.setToolTip("Click & drag to move point")
                    self.setStatusTip(self.toolTip())
                    self.update()
                    break
        else:
            for shape in [s for s in self.sortedShapes if self.isVisible(s)]:
                # Look for a nearby vertex to highlight. If that fails,
                # check if we happen to be inside a shape.
                if shape.containsPoint(pos):
                    if self.selectedVertex():
                        self.hShape.highlightClear()
                    self.hVertex, self.hShape = None, shape
                    self.setToolTip(
                        "Click & drag to move shape '%s'" % shape.label)
                    self.setStatusTip(self.toolTip())
                    self.overrideCursor(CURSOR_GRAB)
                    self.update()
                    break
            else:  # Nothing found, clear highlights, reset state.

                if self.hShape:
                    self.hShape.highlightClear()
                    self.update()
                self.hVertex, self.hShape = None, None

    def mousePressEvent(self, ev):
        self.mousePressed = True
        pos = self.transformPos(ev.pos())

        if ev.button() == Qt.LeftButton:
            if self.drawingRect():
                self.handleDrawing(pos)
            elif self.drawingPolygon():
                self.handleDrawingPolygon(pos)
            elif self.drawingBrush():
                self.handleDrawingBrush(pos)
            else:
                self.selectShapePoint(pos)
                if self.selectedShape is None:
                    self.moving = True
                    self.globalP = ev.globalPos()
                self.prevPoint = pos
                self.repaint()
        elif ev.button() == Qt.RightButton and self.editing():
            self.selectShapePoint(pos)
            self.prevPoint = pos
            self.repaint()

    def mouseReleaseEvent(self, ev):
        self.mousePressed = False
        self.prevPosition = None
        if ev.button() == Qt.RightButton:
            menu = self.menus[bool(self.selectedShapeCopy)]
            self.restoreCursor()
            if not menu.exec_(self.mapToGlobal(ev.pos())) \
                    and self.selectedShapeCopy:
                # Cancel the move by deleting the shadow copy.
                self.selectedShapeCopy = None
                self.repaint()
        elif ev.button() == Qt.LeftButton and self.selectedShape:
            self.overrideCursor(CURSOR_GRAB)
        elif ev.button() == Qt.LeftButton:
            pos = self.transformPos(ev.pos())
            if self.drawingRect():
                self.handleDrawing(pos)
            if self.drawingPolygon():
                self.handleDrawingPolygon(pos)
                if self.moving:
                    self.moving = False

    def endMove(self, copy=False):
        assert self.selectedShape and self.selectedShapeCopy
        shape = self.selectedShapeCopy
        # de        # del shape.line_color
        if copy:
            self.currentShapes.append(shape)
            self.selectedShape.selected = False
            self.selectedShape = shape
            self.repaint()
        else:
            self.selectedShape.points = [p for p in shape.points]
        self.selectedShapeCopy = None

    def hideBackroundShapes(self, value):
        self.hideBackround = value
        if self.selectedShape:
            # Only hide other shapes if there is a current selection.
            # Otherwise the user will not be able to select a shape.
            self.setHiding(True)
            self.repaint()

    def handleDrawing(self, pos):
        if self.current and self.current.reachMaxPoints() is False:
            initPos = self.current[0]
            minX = initPos.x()
            minY = initPos.y()
            targetPos = self.line[1]
            maxX = targetPos.x()
            maxY = targetPos.y()
            self.current.addPoint(QPointF(maxX, minY))
            self.current.addPoint(targetPos)
            self.current.addPoint(QPointF(minX, maxY))
            self.current.addPoint(initPos)
            self.line[0] = self.current[-1]
            if self.current.isClosed():
                self.finalize()
        elif not self.outOfPixmap(pos):
            self.current = Shape()
            self.current.addPoint(pos)
            self.line.points = [pos, pos]
            self.setHiding()
            self.drawingShape.emit(True)
            self.update()

    def handleDrawingPolygon(self, pos):
        # if self.current is not None:
        #     print(self.current.points)
        if self.current:  # and self.current.reachMaxPoints() is False:
            if self.closeEnough(pos, self.current[0]):
                if len(self.current) <= 2:
                    pass
                else:
                    self.current.addPoint(self.current[0])
            else:
                if not self.closeEnough(self.current[-1], pos):
                    self.current.addPoint(pos)
            # initPos = self.current[0]
            # minX = initPos.x()
            # minY = initPos.y()
            # targetPos = self.line[1]
            # maxX = targetPos.x()
            # maxY = targetPos.y()
            # # self.current.addPoint(QPointF(maxX, minY))
            # self.current.addPoint(targetPos)
            # # self.current.addPoint(QPointF(minX, maxY))
            # # self.current.addPoint(initPos)
            self.line[0] = self.current[-1]
            self.update()
            if self.current.isClosed():
                self.finalize()
        elif not self.outOfPixmap(pos):
            self.current = Polygon()  # Shape()
            self.current.addPoint(pos)
            self.line.points = [pos, pos]
            self.setHiding()
            self.drawingShape.emit(True)
            self.update()

    def handleDrawingBrush(self, pos):
        if self.outOfPixmap(pos):
            return
        if self.pixmap is None:
            return
        if self.mode == Canvas.EDIT_BRUSH:
            assert self.selectedShape is not None
            target = self.selectedShape
        elif self.mode == Canvas.CREATE_BRUSH:
            if self.current is None:
                self.current = Brush(self.pixmap.size())
            target = self.current
        else:
            raise NotImplementedError
        if self.prevPosition is None:
            target.addPoint(pos - target.offset, self.brushRadius(), self.erasing())
        else:
            target.addLine(self.prevPosition - target.offset, pos - target.offset, self.brushRadius(), self.erasing())
        self.update()
        self.prevPosition = pos

    def setHiding(self, enable=True):
        self._hideBackround = self.hideBackround if enable else False

    def canCloseShape(self):
        if self.drawingRect():
            return self.current and len(self.current) > 2
        elif self.drawingPolygon():
            return self.current and len(self.current) > 2
        elif self.drawingBrush():
            return self.current and len(self.current.history) > 1
        else:
            return False

    def mouseDoubleClickEvent(self, ev):
        # We need at least 4 points here, since the mousePress handler
        # adds an extra one before this handler is called.
        if self.canCloseShape() and len(self.current) > 3:
            self.current.popPoint()
            self.finalize()

    def selectShape(self, shape):
        self.deSelectShape()
        shape.selected = True
        self.selectedShape = shape
        self.setHiding()
        self.selectionChanged.emit(True)
        self.update()

    def selectShapePoint(self, point):
        """Select the first shape created which contains this point."""
        self.deSelectShape()
        if self.selectedVertex():  # A vertex is marked for selection.
            index, shape = self.hVertex, self.hShape
            shape.highlightVertex(index, shape.MOVE_VERTEX)
            return
        for shape in self.sortedShapes:
            if self.isVisible(shape) and shape.containsPoint(point):
                shape.selected = True
                self.selectedShape = shape
                self.calculateOffsets(shape, point)
                self.setHiding()
                self.selectionChanged.emit(True)
                return

    def calculateOffsets(self, shape, point):
        rect = shape.boundingRect()
        x1 = rect.x() - point.x()
        y1 = rect.y() - point.y()
        x2 = (rect.x() + rect.width()) - point.x()
        y2 = (rect.y() + rect.height()) - point.y()
        self.offsets = QPointF(x1, y1), QPointF(x2, y2)

    def boundedMoveVertex(self, pos):
        index, shape = self.hVertex, self.hShape
        point = shape[index]
        # if self.outOfPixmap(pos):
        #    pos = self.intersectionPoint(point, pos)

        shiftPos = pos - point
        shape.moveVertexBy(index, shiftPos)

        if isinstance(shape, Shape):
            lindex = (index + 1) % 4
            rindex = (index + 3) % 4
            lshift = None
            rshift = None
            if index % 2 == 0:
                rshift = QPointF(shiftPos.x(), 0)
                lshift = QPointF(0, shiftPos.y())
            else:
                lshift = QPointF(shiftPos.x(), 0)
                rshift = QPointF(0, shiftPos.y())
            shape.moveVertexBy(rindex, rshift)
            shape.moveVertexBy(lindex, lshift)

    def boundedMoveShape(self, shape, pos):
        # if self.outOfPixmap(pos):
        #    return False  # No need to move
        o1 = pos + self.offsets[0]
        # if self.outOfPixmap(o1):
        #    pos -= QPointF(min(0, o1.x()), min(0, o1.y()))
        o2 = pos + self.offsets[1]
        # if self.outOfPixmap(o2):
        #    pos += QPointF(min(0, self.pixmap.width() - o2.x()),
        #                   min(0, self.pixmap.height() - o2.y()))
        # The next line tracks the new position of the cursor
        # relative to the shape, but also results in making it
        # a bit "shaky" when nearing the border and allows it to
        # go outside of the shape's area for some reason. XXX
        # self.calculateOffsets(self.selectedShape, pos)
        dp = pos - self.prevPoint
        if dp:
            shape.moveBy(dp)
            self.prevPoint = pos
            return True
        return False

    def deSelectShape(self):
        if self.selectedShape:
            self.selectedShape.selected = False
            self.selectedShape = None
            self.setHiding(False)
            self.selectionChanged.emit(False)
            self.update()

    def deleteSelected(self):
        if self.selectedShape:
            shape = self.selectedShape
            self.currentShapes.remove(self.selectedShape)
            self.selectedShape = None
            self.selectionChanged.emit(False)
            self.update()
            return shape

    def copySelectedShape(self):
        if self.selectedShape:
            shape = self.selectedShape.copy()
            self.deSelectShape()
            self.currentShapes.append(shape)
            shape.selected = True
            self.selectedShape = shape
            self.boundedShiftShape(shape)
            return shape

    def boundedShiftShape(self, shape):
        # Try to move in one direction, and if it fails in another.
        # Give up if both fail.
        point = shape[0]
        offset = QPointF(2.0, 2.0)
        self.calculateOffsets(shape, point)
        self.prevPoint = point
        if not self.boundedMoveShape(shape, point - offset):
            self.boundedMoveShape(shape, point + offset)

    @property
    def windowWidget(self):
        return self.parentWidget().parentWidget().parentWidget()

    @property
    def currentShapes(self):
        return self.shapes[self.windowWidget.currentCategoryId]

    def getSortedShapes(self, categoryId):
        labelList = self.windowWidget.labelLists[categoryId]
        items = [labelList.item(i) for i in range(labelList.count())]
        sortedShapes = [self.windowWidget.itemsToShapes[categoryId][item] for item in items]
        return sortedShapes

    @property
    def sortedShapes(self):
        return self.getSortedShapes(self.windowWidget.currentCategoryId)

    def paintEvent(self, event):
        if not self.pixmap:
            return super(Canvas, self).paintEvent(event)

        p = self._painter
        p.begin(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.HighQualityAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        p.scale(self.scale(), self.scale())
        p.translate(self.offsetToCenter())

        p.drawPixmap(0, 0, self.pixmap)

        Shape.scale = self.scale()

        # if len(self.shapes) > 0:
        sortedShapes = self.sortedShapes

        for idx, shape in enumerate(sortedShapes):
            if (shape.selected or not self._hideBackround) and self.isVisible(shape):
                shape.fill = shape.selected or shape == self.hShape
                shape.paint(p, prev_shapes=sortedShapes[:idx], scale=self.scale())
        if self.current:
            self.current.fill = True
            self.current.paint(p, scale=self.scale())
            self.line.paint(p)
        # if self.selectedShapeCopy:
        #     self.selectedShapeCopy.paint(p)

        # Paint rect
        if self.drawingRect():
            if self.current is not None and len(self.line) == 2:
                leftTop = self.line[0]
                rightBottom = self.line[1]
                rectWidth = rightBottom.x() - leftTop.x()
                rectHeight = rightBottom.y() - leftTop.y()
                color = QColor(0, 220, 0)
                p.setPen(color)
                brush = QBrush(Qt.BDiagPattern)
                p.setBrush(brush)
                p.drawRect(leftTop.x(), leftTop.y(), rectWidth, rectHeight)
        elif self.drawingPolygon():
            if self.current is not None and len(self.current) >= 2:
                color = QColor(0, 220, 0)
                pen = QPen(color)
                pen.setWidth(min(3.0 / self.scale(), max(1, int(round(5.0 / self.scale())))))
                p.setPen(pen)
                brush = QBrush(Qt.BDiagPattern)
                p.setBrush(brush)
                p.drawPolygon(*self.current.points, self.line[1])
        # elif self.drawingBrush():
        #     if self.current is not None:
        #         color = QColor(0, 220, 0)
        #         pen = QPen(color)
        #         p.setPen(pen)
        #         bgMode = p.backgroundMode()
        #         p.setOpacity(0.5)
        #         p.setBackgroundMode(Qt.TransparentMode)
        #         p.drawPixmap(0, 0, self.current)
        #         p.setBackgroundMode(bgMode)

        self.setAutoFillBackground(True)
        if self.verified:
            pal = self.palette()
            pal.setColor(self.backgroundRole(), QColor(184, 239, 38, 128))
            self.setPalette(pal)
        else:
            pal = self.palette()
            pal.setColor(self.backgroundRole(), QColor(232, 232, 232, 255))
            self.setPalette(pal)

        p.end()

        if self.showRangeCursor() and self._trackCenter is not None:
            p.begin(self)
            p.scale(self.scale(), self.scale())
            # p.translate(self.offsetToCenter())
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.HighQualityAntialiasing)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            pen = QPen(QColor(255, 0, 0))
            pen.setWidth(self.trackThickness())
            p.setPen(pen)
            p.drawEllipse(QPointF(self._trackCenter.x() / self.scale(), self._trackCenter.y() / self.scale()),
                          self.trackRadius(), self.trackRadius())
            p.end()

    def transformPos(self, point):
        """Convert from widget-logical coordinates to painter-logical coordinates."""
        return point / self.scale() - self.offsetToCenter()

    def offsetToCenter(self):
        s = self.scale()
        area = super(Canvas, self).size()
        w, h = self.pixmap.width() * s, self.pixmap.height() * s
        aw, ah = area.width(), area.height()
        x = (aw - w) / (2 * s) if aw > w else 0
        y = (ah - h) / (2 * s) if ah > h else 0
        return QPointF(x, y)

    def outOfPixmap(self, p):
        w, h = self.pixmap.width(), self.pixmap.height()
        return not (0 <= p.x() <= w and 0 <= p.y() <= h)

    def finalize(self):
        assert self.current
        self.current.close()
        self.currentShapes.append(self.current)
        self.current = None
        self.setHiding(False)
        self.newShape.emit()
        self.update()

    def closeEnough(self, p1, p2):
        # d = distance(p1 - p2)
        # m = (p1-p2).manhattanLength()
        # print "d %.2f, m %d, %.2f" % (d, m, d - m)
        return distance(p1 - p2) * self.scale() < self.epsilon

    def intersectionPoint(self, p1, p2):
        # Cycle through each image edge in clockwise fashion,
        # and find the one intersecting the current line segment.
        # http://paulbourke.net/geometry/lineline2d/
        size = self.pixmap.size()
        points = [(0, 0),
                  (size.width(), 0),
                  (size.width(), size.height()),
                  (0, size.height())]
        x1, y1 = p1.x(), p1.y()
        x2, y2 = p2.x(), p2.y()
        d, i, (x, y) = min(self.intersectingEdges((x1, y1), (x2, y2), points))
        x3, y3 = points[i]
        x4, y4 = points[(i + 1) % 4]
        if (x, y) == (x1, y1):
            # Handle cases where previous point is on one of the edges.
            if x3 == x4:
                return QPointF(x3, min(max(0, y2), max(y3, y4)))
            else:  # y3 == y4
                return QPointF(min(max(0, x2), max(x3, x4)), y3)
        return QPointF(x, y)

    def intersectingEdges(self, x1y1, x2y2, points):
        """For each edge formed by `points', yield the intersection
        with the line segment `(x1,y1) - (x2,y2)`, if it exists.
        Also return the distance of `(x2,y2)' to the middle of the
        edge along with its index, so that the one closest can be chosen."""
        x1, y1 = x1y1
        x2, y2 = x2y2
        for i in range(4):
            x3, y3 = points[i]
            x4, y4 = points[(i + 1) % 4]
            denom = (y4 - y3) * (x2 - x1) - (x4 - x3) * (y2 - y1)
            nua = (x4 - x3) * (y1 - y3) - (y4 - y3) * (x1 - x3)
            nub = (x2 - x1) * (y1 - y3) - (y2 - y1) * (x1 - x3)
            if denom == 0:
                # This covers two cases:
                #   nua == nub == 0: Coincident
                #   otherwise: Parallel
                continue
            ua, ub = nua / denom, nub / denom
            if 0 <= ua <= 1 and 0 <= ub <= 1:
                x = x1 + ua * (x2 - x1)
                y = y1 + ua * (y2 - y1)
                m = QPointF((x3 + x4) / 2, (y3 + y4) / 2)
                d = distance(m - QPointF(x2, y2))
                yield d, i, (x, y)

    # These two, along with a call to adjustSize are required for the
    # scroll area.
    def sizeHint(self):
        return self.minimumSizeHint()

    def minimumSizeHint(self):
        if self.pixmap:
            return self.scale() * self.pixmap.size()
        return super(Canvas, self).minimumSizeHint()

    def wheelEvent(self, ev):
        qt_version = 4 if hasattr(ev, "delta") else 5
        if qt_version == 4:
            if ev.orientation() == Qt.Vertical:
                v_delta = ev.delta()
                h_delta = 0
            else:
                h_delta = ev.delta()
                v_delta = 0
        else:
            delta = ev.angleDelta()
            h_delta = delta.x()
            v_delta = delta.y()

        mods = ev.modifiers()
        if Qt.ControlModifier == int(mods) and v_delta:
            self.zoomRequest.emit(v_delta)
        else:
            v_delta and self.scrollRequest.emit(v_delta, Qt.Vertical)
            h_delta and self.scrollRequest.emit(h_delta, Qt.Horizontal)
        ev.accept()

    def keyPressEvent(self, ev):
        key = ev.key()
        if key in [Qt.Key_Escape, Qt.Key_Delete, Qt.Key_Backspace] and self.current is not None:
            # print('ESC press')
            if self.drawingRect():
                self.current = None
                self.setMode(Canvas.EDIT)
                self.drawingShape.emit(False)
                self.update()
            elif self.drawingPolygon():
                if self.current and len(self.current.points) >= 1:
                    self.current.popPoint()
                    if len(self.current.points) > 0:
                        self.line[0] = self.current.points[-1]
                else:
                    self.current = None
                    self.setMode(Canvas.EDIT)
                    self.drawingShape.emit(False)
                if self.current:
                    print(self.current.points)
                self.update()
            elif self.drawingBrush():
                self.drawingShape.emit(False)
                self.update()
        elif key == Qt.Key_Return and self.canCloseShape():
            self.finalize()
        elif key == Qt.Key_Left and self.selectedShape:
            self.moveOnePixel('Left')
        elif key == Qt.Key_Right and self.selectedShape:
            self.moveOnePixel('Right')
        elif key == Qt.Key_Up and self.selectedShape:
            self.moveOnePixel('Up')
        elif key == Qt.Key_Down and self.selectedShape:
            self.moveOnePixel('Down')
            # elif key in [Qt.Key_Delete, Qt.Key_Backspace] and self.selectedShape and self.selectedVertex():
            #     if isinstance(self.selectedShape, Polygon):
            #         if len(self.selectedShape.points) >= 4:
            #             self.selectedShape.points.pop(self.selectedVertex())
            #             self.update()

    def moveOnePixel(self, direction):
        # print(self.selectedShape.points)
        if direction == 'Left' and not self.moveOutOfBound(QPointF(-1.0, 0)):
            # print("move Left one pixel")
            self.selectedShape.points[0] += QPointF(-1.0, 0)
            self.selectedShape.points[1] += QPointF(-1.0, 0)
            self.selectedShape.points[2] += QPointF(-1.0, 0)
            self.selectedShape.points[3] += QPointF(-1.0, 0)
        elif direction == 'Right' and not self.moveOutOfBound(QPointF(1.0, 0)):
            # print("move Right one pixel")
            self.selectedShape.points[0] += QPointF(1.0, 0)
            self.selectedShape.points[1] += QPointF(1.0, 0)
            self.selectedShape.points[2] += QPointF(1.0, 0)
            self.selectedShape.points[3] += QPointF(1.0, 0)
        elif direction == 'Up' and not self.moveOutOfBound(QPointF(0, -1.0)):
            # print("move Up one pixel")
            self.selectedShape.points[0] += QPointF(0, -1.0)
            self.selectedShape.points[1] += QPointF(0, -1.0)
            self.selectedShape.points[2] += QPointF(0, -1.0)
            self.selectedShape.points[3] += QPointF(0, -1.0)
        elif direction == 'Down' and not self.moveOutOfBound(QPointF(0, 1.0)):
            # print("move Down one pixel")
            self.selectedShape.points[0] += QPointF(0, 1.0)
            self.selectedShape.points[1] += QPointF(0, 1.0)
            self.selectedShape.points[2] += QPointF(0, 1.0)
            self.selectedShape.points[3] += QPointF(0, 1.0)
        self.shapeMoved.emit()
        self.repaint()

    def moveOutOfBound(self, step):
        points = [p1 + p2 for p1, p2 in zip(self.selectedShape.points, [step] * 4)]
        return True in map(self.outOfPixmap, points)

    def setLastLabel(self, text):
        assert text
        self.currentShapes[-1].label = text
        return self.currentShapes[-1]

    def undoLastLine(self):
        assert self.currentShapes
        # if self.drawingRect():
        self.current = self.currentShapes.pop()
        self.current.setOpen()
        self.line.points = [self.current[-1], self.current[0]]
        self.drawingShape.emit(True)
        # elif self.drawingPolygon():

    def undoNewBrush(self):
        assert self.currentShapes
        self.current = self.currentShapes.pop()
        self.drawingShape.emit(True)

    def resetAllLines(self):
        assert self.currentShapes
        self.current = self.currentShapes.pop()
        self.current.setOpen()
        self.line.points = [self.current[-1], self.current[0]]
        self.drawingShape.emit(True)
        self.current = None
        self.drawingShape.emit(False)
        self.update()

    def loadPixmap(self, pixmap):
        self.pixmap = pixmap
        self.shapes = defaultdict(list)
        self.repaint()

    def loadShapes(self, shapes):
        self.shapes = shapes  # list(shapes)
        self.current = None
        self.repaint()

    def setShapeVisible(self, shape, value):
        self.visible[shape] = value
        self.repaint()

    def overrideCursor(self, cursor):
        self.restoreCursor()
        self._cursor = cursor
        QApplication.setOverrideCursor(cursor)

    def restoreCursor(self):
        QApplication.restoreOverrideCursor()

    def resetState(self):
        self.restoreCursor()
        self.pixmap = None
        self.update()
