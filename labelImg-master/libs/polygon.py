#!/usr/bin/python
# -*- coding: utf-8 -*-
from functools import lru_cache
import builtins

from libs.brush import Brush

try:
    from PyQt5.QtGui import *
    from PyQt5.QtCore import *
except ImportError:
    from PyQt4.QtGui import *
    from PyQt4.QtCore import *

from libs.lib import distance
import shapely.geometry
import shapely.errors
import numpy as np

DEFAULT_LINE_COLOR = QColor(0, 255, 0, 128)
DEFAULT_FILL_COLOR = QColor(255, 0, 0, 0)
DEFAULT_SELECT_LINE_COLOR = QColor(255, 255, 255)
DEFAULT_SELECT_FILL_COLOR = QColor(0, 128, 255, 155)
DEFAULT_VERTEX_FILL_COLOR = QColor(0, 255, 0, 255)
DEFAULT_HVERTEX_FILL_COLOR = QColor(255, 0, 0)

if not hasattr(builtins, 'profile'):
    builtins.profile = lambda x: x


class Polygon(object):
    P_SQUARE, P_ROUND = range(2)

    MOVE_VERTEX, NEAR_VERTEX = range(2)

    # The following class variables influence the drawing
    # of _all_ shape objects.
    line_color = DEFAULT_LINE_COLOR
    fill_color = DEFAULT_FILL_COLOR
    select_line_color = DEFAULT_SELECT_LINE_COLOR
    select_fill_color = DEFAULT_SELECT_FILL_COLOR
    vertex_fill_color = DEFAULT_VERTEX_FILL_COLOR
    hvertex_fill_color = DEFAULT_HVERTEX_FILL_COLOR
    point_type = P_ROUND
    point_size = 8
    scale = 1.0

    def __init__(self, label=None, attributes=(), line_color=None, difficult=False):
        self.label = label
        self.attributes = attributes
        self.points = []
        self.points_tuple = ()
        self.points_dirty = False
        self.fill = False
        self.selected = False
        self.difficult = difficult

        self._highlightIndex = None
        self._highlightMode = self.NEAR_VERTEX
        self._highlightSettings = {
            self.NEAR_VERTEX: (2, self.P_ROUND),
            self.MOVE_VERTEX: (2, self.P_SQUARE),
        }

        self._closed = False
        self._mask = None

        if line_color is not None:
            # Override the class line_color attribute
            # with an object attribute. Currently this
            # is used for drawing the pending line a different color.
            self.line_color = line_color

    def close(self):
        self._closed = True

    @property
    def labelWithAttributes(self):
        if len(self.attributes) > 0:
            return f"{self.label} ({', '.join(self.attributes)})"
        else:
            return self.label

    def reachMaxPoints(self):
        if len(self.points) >= 4:
            return True
        return False

    def addPoint(self, point):
        self.points_dirty = True
        if self.points and point == self.points[0]:
            self.close()
        else:
            self.points.append(point)

    def popPoint(self):
        self.points_dirty = True
        if self.points:
            return self.points.pop()
        return None

    def get_points_tuple(self):
        if self.points_dirty:
            self.points_tuple = tuple([(p.x(), p.y()) for p in self.points])
            self.points_dirty = False
        return self.points_tuple

    def isClosed(self):
        return self._closed

    def setOpen(self):
        self._closed = False

    @staticmethod
    @lru_cache(maxsize=1000)
    def get_shapely_polygon(points):
        if len(points) >= 3:
            return shapely.geometry.Polygon(points)
        elif len(points) == 2:
            return shapely.geometry.LineString(points)
        elif len(points) == 1:
            return shapely.geometry.Point(*points[0])
        else:
            raise NotImplementedError


    @staticmethod
    @lru_cache(maxsize=1000)
    @profile
    def compute_self_poly(points, prev_shape_points):
        poly = Polygon.get_shapely_polygon(points)
        min_xy = np.min(points, axis=0)
        max_xy = np.max(points, axis=0)

        if prev_shape_points:
            for prev_shape_pts in prev_shape_points:
                prev_shape_pts_np = np.asarray(prev_shape_pts)
                prev_min_xy = np.min(prev_shape_pts_np, axis=0)
                if np.any(max_xy < prev_min_xy):
                    continue
                prev_max_xy = np.max(prev_shape_pts_np, axis=0)
                if np.any(min_xy > prev_max_xy):
                    continue
                prev_poly = Polygon.get_shapely_polygon(prev_shape_pts)
                try:
                    poly = poly.difference(prev_poly)
                except shapely.errors.TopologicalError:
                    poly = poly.buffer(0).difference(prev_poly.buffer(0))
        return poly

    @staticmethod
    @lru_cache(maxsize=1000)
    @profile
    def self_poly_geom_points(points, prev_shape_points):
        self_poly = Polygon.compute_self_poly(points=points, prev_shape_points=prev_shape_points)
        if isinstance(self_poly, shapely.geometry.MultiPolygon):
            geoms = self_poly.geoms
        else:
            geoms = [self_poly]
        geom_points = []
        for geom in geoms:
            if isinstance(geom, shapely.geometry.Point):
                pts = [QPointF(geom.x, geom.y)]
            elif isinstance(geom, shapely.geometry.LineString):
                pts = [QPointF(x, y) for x, y in zip(*geom.xy)]
            elif isinstance(geom, shapely.geometry.GeometryCollection):
                if len(geom.geoms) == 0:
                    continue
                import ipdb;
                ipdb.set_trace()
            else:
                pts = [QPointF(x, y) for x, y in geom.exterior.coords]
            geom_points.append((geom, pts))
        return geom_points

    @profile
    def paint(self, painter, prev_shapes=None, scale=None):
        drawAllVertices = True
        if scale is None:
            scale = self.scale

        if self.points:
            def is_original(p):
                dists = [abs(p.x() - q.x()) + abs(p.y() - q.y()) for q in self.points]
                return min(dists) < 1e-5

            if prev_shapes is None:
                prev_shape_points = None
            else:
                prev_shape_points = []
                for shape in prev_shapes:
                    if isinstance(shape, Brush):
                        continue
                    if isinstance(shape, Polygon):
                        prev_shape_points.append(shape.get_points_tuple())
                prev_shape_points = tuple(prev_shape_points)

            for geom, points in self.self_poly_geom_points(
                    points=self.get_points_tuple(),  # tuple([(p.x(), p.y()) for p in self.points]),
                    prev_shape_points=prev_shape_points,
            ):
                color = self.select_line_color if self.selected else self.line_color
                pen = QPen(color)
                # Try using integer sizes for smoother drawing(?)
                pen.setWidth(min(5, max(1, int(round(5.0 / scale)))))
                painter.setPen(pen)

                line_path = QPainterPath()

                line_path.moveTo(points[0])

                if not drawAllVertices:
                    vrtx_path = QPainterPath()

                # Uncommenting the following line will draw 2 paths
                # for the 1st vertex, and make it non-filled, which
                # may be desirable.
                # self.drawVertex(vrtx_path, 0)

                for i, p in enumerate(points):
                    line_path.lineTo(p)
                    if not drawAllVertices:
                        if is_original(p):
                            self.drawVertex(vrtx_path, i, point=p, scale=scale)

                if self.isClosed():
                    line_path.lineTo(points[0])

                painter.drawPath(line_path)

                if self.fill:
                    if hasattr(geom, 'interiors') and len(geom.interiors) > 0:
                        ipath = QPainterPath()
                        for interior in geom.interiors:
                            start_point = None
                            for x, y in zip(*interior.xy):
                                if start_point is None:
                                    start_point = (x, y)
                                    ipath.moveTo(QPointF(x, y))
                                else:
                                    ipath.lineTo(QPointF(x, y))
                            ipath.lineTo(QPointF(*start_point))
                            line_path.addPath(ipath)
                    if not drawAllVertices:
                        painter.fillPath(vrtx_path, self.vertex_fill_color)

                    color = self.select_fill_color if self.selected else self.fill_color
                    painter.fillPath(line_path, color)

            if self.fill:
                if drawAllVertices:
                    vrtx_path = QPainterPath()
                    for i, p in enumerate(self.points):
                        self.drawVertex(vrtx_path, i, point=p, scale=scale)
                        painter.drawPath(vrtx_path)
                    painter.fillPath(vrtx_path, self.vertex_fill_color)

    def drawVertex(self, path, i, point=None, scale=None):
        if scale is not None:
            d = self.point_size / scale
        else:
            d = self.point_size / self.scale
        shape = self.point_type
        if point is None:
            point = self.points[i]
        size, shape = self._highlightSettings[self._highlightMode]
        d *= size
        if i == self._highlightIndex:
            d *= 2
        # if self._highlightIndex is not None:
        self.vertex_fill_color = self.hvertex_fill_color
        # else:
        #     self.vertex_fill_color = Polygon.vertex_fill_color
        if shape == self.P_SQUARE:
            path.addRect(point.x() - d / 2, point.y() - d / 2, d, d)
        elif shape == self.P_ROUND:
            path.addEllipse(point, d / 2.0, d / 2.0)
        else:
            assert False, "unsupported vertex shape"

    def nearestVertex(self, point, epsilon):
        for i, p in enumerate(self.points):
            if distance(p - point) <= epsilon:
                return i
        return None

    def containsPoint(self, point):
        return self.makePath().contains(point)

    def makePath(self):
        path = QPainterPath(self.points[0])
        for p in self.points[1:]:
            path.lineTo(p)
        return path

    def boundingRect(self):
        return self.makePath().boundingRect()

    def moveBy(self, offset):
        self.points_dirty = True
        self.points = [p + offset for p in self.points]

    def moveVertexBy(self, i, offset):
        self.points_dirty = True
        self.points[i] = self.points[i] + offset

    def highlightVertex(self, i, action):
        self._highlightIndex = i
        self._highlightMode = action

    def highlightClear(self):
        self._highlightIndex = None

    def copy(self):
        shape = Polygon("%s" % self.label)
        shape.points = [p for p in self.points]
        shape.fill = self.fill
        shape.selected = self.selected
        shape._closed = self._closed
        if self.line_color != Polygon.line_color:
            shape.line_color = self.line_color
        if self.fill_color != Polygon.fill_color:
            shape.fill_color = self.fill_color
        shape.difficult = self.difficult
        return shape

    def __len__(self):
        return len(self.points)

    def __getitem__(self, key):
        return self.points[key]

    def __setitem__(self, key, value):
        self.points[key] = value

    def get_unoccluded_mask(self, size):
        import numpy as np
        assert self._closed
        bitmap = QBitmap(size)
        bitmap.clear()
        p = QPainter()
        p.begin(bitmap)
        p.setPen(Qt.color1)
        p.setBrush(Qt.color1)
        line_path = QPainterPath()
        line_path.moveTo(self.points[0])
        for point in self.points:
            line_path.lineTo(point)
        line_path.lineTo(self.points[0])
        p.drawPath(line_path)
        p.end()

        image = bitmap.toImage().convertToFormat(QImage.Format_Indexed8)
        ptr = image.constBits()
        ptr.setsize(image.byteCount())
        mask = np.frombuffer(ptr, count=image.byteCount(), dtype=np.uint8).reshape(
            image.height(), image.bytesPerLine())[:image.height(), :image.width()]

        return mask
