#!/usr/bin/env python
# -*- coding: utf8 -*-
import sys
from collections import defaultdict
from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement
from lxml import etree
import codecs

XML_EXT = '.xml'
ENCODE_METHOD = 'utf-8'


class PascalVocWriter:
    def __init__(self, foldername, filename, imgSize, labelCategories, databaseSrc='Unknown', localImgPath=None):
        self.foldername = foldername
        self.filename = filename
        self.databaseSrc = databaseSrc
        self.imgSize = imgSize
        self.objlist = defaultdict(list)
        # self.boxlist = defaultdict(list)
        # self.polygonlist = defaultdict(list)
        self.localImgPath = localImgPath
        self.labelCategories = labelCategories
        self.verified = False

    def prettify(self, elem):
        """
            Return a pretty-printed XML string for the Element.
        """
        rough_string = ElementTree.tostring(elem, 'utf8')
        root = etree.fromstring(rough_string)
        return etree.tostring(root, pretty_print=True, encoding=ENCODE_METHOD).replace("  ".encode(), "\t".encode())

    def genXML(self):
        """
            Return XML root
        """
        # Check conditions
        if self.filename is None or \
                        self.foldername is None or \
                        self.imgSize is None:
            return None

        top = Element('annotation')
        if self.verified:
            top.set('verified', 'yes')

        folder = SubElement(top, 'folder')
        folder.text = self.foldername

        filename = SubElement(top, 'filename')
        filename.text = self.filename

        if self.localImgPath is not None:
            localImgPath = SubElement(top, 'path')
            localImgPath.text = self.localImgPath

        source = SubElement(top, 'source')
        database = SubElement(source, 'database')
        database.text = self.databaseSrc

        size_part = SubElement(top, 'size')
        width = SubElement(size_part, 'width')
        height = SubElement(size_part, 'height')
        depth = SubElement(size_part, 'depth')
        width.text = str(self.imgSize[1])
        height.text = str(self.imgSize[0])
        if len(self.imgSize) == 3:
            depth.text = str(self.imgSize[2])
        else:
            depth.text = '1'

        segmented = SubElement(top, 'segmented')
        segmented.text = '0'
        return top

    def addBndBox(self, categoryId, xmin, ymin, xmax, ymax, name, attributes):
        bndbox = {'xmin': xmin, 'ymin': ymin, 'xmax': xmax, 'ymax': ymax}
        bndbox['name'] = name
        bndbox['attributes'] = attributes
        self.objlist[categoryId].append(('bndbox', bndbox))

    def addPolygon(self, categoryId, points, name, attributes):
        polygon = {'points': points}
        polygon['name'] = name
        polygon['attributes'] = attributes
        self.objlist[categoryId].append(('polygon', polygon))

    def addBrush(self, categoryId, size, offset, history, name, attributes):
        brush = {'size': size, 'name': name, 'offset': offset, 'history': history, 'attributes': attributes}
        self.objlist[categoryId].append(('brush', brush))

    def appendObjects(self, top):

        def _addXY(elem, field, pos):
            pt = SubElement(elem, field)
            ptx = SubElement(pt, "x")
            pty = SubElement(pt, "y")
            ptx.text = str(int(pos[0]))
            pty.text = str(int(pos[1]))

        def _addWH(elem, field, pos):
            pt = SubElement(elem, field)
            ptx = SubElement(pt, "width")
            pty = SubElement(pt, "height")
            ptx.text = str(int(pos[0]))
            pty.text = str(int(pos[1]))

        def _addInt(elem, field, val):
            fe = SubElement(elem, field)
            fe.text = str(int(val))

        def _addBool(elem, field, val):
            fe = SubElement(elem, field)
            fe.text = str(bool(val))

        for _, categoryId in self.labelCategories:
            for typ, each_object in self.objlist[categoryId]:
                if typ == 'bndbox':
                    object_item = SubElement(top, categoryId)
                    name = SubElement(object_item, 'name')
                    name.text = each_object['name']
                    for attr in each_object['attributes']:
                        attrElem = SubElement((object_item, 'attribute'))
                        attrElem.text = attr
                    bndbox = SubElement(object_item, 'bndbox')
                    xmin = SubElement(bndbox, 'xmin')
                    xmin.text = str(each_object['xmin'])
                    ymin = SubElement(bndbox, 'ymin')
                    ymin.text = str(each_object['ymin'])
                    xmax = SubElement(bndbox, 'xmax')
                    xmax.text = str(each_object['xmax'])
                    ymax = SubElement(bndbox, 'ymax')
                    ymax.text = str(each_object['ymax'])
                elif typ == 'polygon':
                    object_item = SubElement(top, categoryId)
                    name = SubElement(object_item, 'name')
                    name.text = each_object['name']
                    for attr in each_object['attributes']:
                        attrElem = SubElement(object_item, 'attribute')
                        attrElem.text = attr
                    polygon = SubElement(object_item, "polygon")
                    for point in each_object['points']:
                        _addXY(polygon, "point", point)
                elif typ == 'brush':
                    object_item = SubElement(top, categoryId)
                    name = SubElement(object_item, 'name')
                    name.text = each_object['name']
                    for attr in each_object['attributes']:
                        attrElem = SubElement(object_item, 'attribute')
                        attrElem.text = attr
                    brush = SubElement(object_item, "brush")
                    _addWH(brush, "size", each_object['size'])
                    _addXY(brush, "offset", each_object['offset'])

                    history = SubElement(brush, "history")
                    for hist_type, hist_data in each_object['history']:
                        if hist_type == 'addPoint':
                            point, radius, erasing = hist_data
                            addPoint = SubElement(history, 'addPoint')
                            _addXY(addPoint, "point", point)
                            _addInt(addPoint, "radius", radius)
                            _addBool(addPoint, "erasing", erasing)
                        elif hist_type == 'addLine':
                            pos1, pos2, radius, erasing = hist_data
                            addLine = SubElement(history, 'addLine')
                            _addXY(addLine, "pos1", pos1)
                            _addXY(addLine, "pos2", pos2)
                            _addInt(addLine, "radius", radius)
                            _addBool(addLine, "erasing", erasing)

    def save(self, targetFile=None):
        root = self.genXML()
        self.appendObjects(root)
        out_file = None
        if targetFile is None:
            out_file = codecs.open(
                self.filename + XML_EXT, 'w', encoding=ENCODE_METHOD)
        else:
            out_file = codecs.open(targetFile, 'w', encoding=ENCODE_METHOD)

        prettifyResult = self.prettify(root)
        out_file.write(prettifyResult.decode('utf8'))
        out_file.close()


def _str_to_bool(s):
    return {'True': True, 'true': True, 'False': False, 'false': False}[s]


class PascalVocReader:
    def __init__(self, filepath, labelCategories):
        self.shapes = defaultdict(list)
        self.filepath = filepath
        self.labelCategories = labelCategories
        self.verified = False
        self.parseXML()

    def getShapes(self):
        return self.shapes

    def addShape(self, category, label, attributes, bndbox):
        xmin = int(bndbox.find('xmin').text)
        ymin = int(bndbox.find('ymin').text)
        xmax = int(bndbox.find('xmax').text)
        ymax = int(bndbox.find('ymax').text)
        points = [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)]
        self.shapes[category].append((label, attributes, points, 'rect'))

    def addPolygon(self, category, label, attributes, polygon):
        points = polygon.findall("point")
        xs = [int(p.find("x").text) for p in points]
        ys = [int(p.find("y").text) for p in points]
        points = list(zip(xs, ys))
        self.shapes[category].append((label, attributes, points, 'polygon'))

    def addBrush(self, category, label, attributes, brush):
        size = (int(brush.find("size").find("width").text), int(brush.find("size").find("height").text))
        offset = (int(brush.find("offset").find("x").text), int(brush.find("offset").find("y").text))
        history = []
        for hist in brush.find("history"):
            if hist.tag == 'addPoint':
                history.append(
                    (
                        'addPoint',
                        (
                            (int(hist.find("point").find("x").text), int(hist.find("point").find("y").text)),
                            int(hist.find("radius").text),
                            _str_to_bool(hist.find("erasing").text),
                        )
                    )
                )
            if hist.tag == 'addLine':
                history.append(
                    (
                        'addLine',
                        (
                            (int(hist.find("pos1").find("x").text), int(hist.find("pos1").find("y").text)),
                            (int(hist.find("pos2").find("x").text), int(hist.find("pos2").find("y").text)),
                            int(hist.find("radius").text),
                            _str_to_bool(hist.find("erasing").text),
                        )
                    )
                )
        self.shapes[category].append((label, attributes, (size, offset, history), 'brush'))

    def parseXML(self):
        assert self.filepath.endswith(XML_EXT), "Unsupport file format"
        parser = etree.XMLParser(encoding=ENCODE_METHOD)
        if len(open(self.filepath, 'rb').read().strip()) == 0:
            return True
        xmltree = ElementTree.parse(self.filepath, parser=parser).getroot()
        try:
            verified = xmltree.attrib['verified']
            if verified == 'yes':
                self.verified = True
        except KeyError:
            self.verified = False

        for _, cat_id in self.labelCategories:
            for object_iter in xmltree.findall(cat_id):
                bndbox = object_iter.find("bndbox")
                label = object_iter.find('name').text
                polygon = object_iter.find("polygon")
                brush = object_iter.find("brush")
                attributes = []
                for attr in object_iter.findall('attribute'):
                    attributes.append(attr.text.strip())
                if bndbox is not None:
                    self.addShape(cat_id, label, attributes, bndbox)
                elif polygon is not None:
                    self.addPolygon(cat_id, label, attributes, polygon)
                elif brush is not None:
                    self.addBrush(cat_id, label, attributes, brush)
                else:
                    raise NotImplementedError
        return True
