#!/usr/bin/env python
# -*- coding: utf8 -*-
import copy
import codecs
import os.path
import re
import sys
import subprocess
import requests
import json
import base64

from functools import partial
from collections import defaultdict

# try:
from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
# except ImportError:
#     # needed for py3+qt4
#     # Ref:
#     # http://pyqt.sourceforge.net/Docs/PyQt4/incompatible_apis.html
#     # http://stackoverflow.com/questions/21217399/pyqt4-qtcore-qvariant-object-instead-of-a-string
#     if sys.version_info.major >= 3:
#         import sip
#
#         sip.setapi('QVariant', 2)
#     from PyQt4.QtGui import *
#     from PyQt4.QtCore import *

import resources
# Add internal libs
from libs.brush import Brush
from libs.lib import struct, newAction, newIcon, addActions, fmtShortcut
from libs.polygon import Polygon
from libs.shape import Shape, DEFAULT_LINE_COLOR, DEFAULT_FILL_COLOR
from libs.canvas import Canvas, laterOnTop
from libs.zoomWidget import ZoomWidget
from libs.labelDialog import LabelDialog
from libs.attributesDialog import AttributesDialog
from libs.colorDialog import ColorDialog
from libs.labelFile import LabelFile, LabelFileError
from libs.toolBar import ToolBar
from libs.pascal_voc_io import PascalVocReader
from libs.pascal_voc_io import XML_EXT
from libs.ustr import ustr

__appname__ = 'labelImg'


# Utility functions and classes.




def have_qstring():
    '''p3/qt5 get rid of QString wrapper as py3 has native unicode str type'''
    return not (sys.version_info.major >= 3 or QT_VERSION_STR.startswith('5.'))


def util_qt_strlistclass():
    return QStringList if have_qstring() else list


def natural_sort(l):
    convert = lambda text: int(text) if text.isdigit() else text.lower()
    alphanum_key = lambda key: [convert(c) for c in re.split('([0-9]+)', key)]
    return sorted(l, key=alphanum_key)


class WindowMixin(object):
    def menu(self, title, actions=None):
        menu = self.menuBar().addMenu(title)
        if actions:
            addActions(menu, actions)
        return menu

    def toolbar(self, title, actions=None):
        toolbar = ToolBar(title)
        toolbar.setObjectName(u'%sToolBar' % title)
        # toolbar.setOrientation(Qt.Vertical)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        if actions:
            addActions(toolbar, actions)
        self.addToolBar(Qt.LeftToolBarArea, toolbar)
        return toolbar


# PyQt5: TypeError: unhashable type: 'QListWidgetItem'
class HashableQListWidgetItem(QListWidgetItem):
    def __init__(self, *args):
        super(HashableQListWidgetItem, self).__init__(*args)

    def __hash__(self):
        return hash(id(self))


def loadLabels(shapes, labelCategories):
    for _, cat_id in labelCategories:
        for label, attributes, points, type in shapes[cat_id]:
            if type == 'rect':
                shape = Shape(label=label, attributes=attributes)
                for x, y in points:
                    shape.addPoint(QPointF(x, y))
            elif type == 'polygon':
                shape = Polygon(label=label, attributes=attributes)
                for x, y in points:
                    shape.addPoint(QPointF(x, y))
            elif type == 'brush':
                size, offset, history = points
                shape = Brush(
                    size=QSize(size[0], size[1]), label=label, attributes=attributes, history=history,
                    offset=QPointF(offset[0], offset[1])
                )
            else:
                raise NotImplementedError

            shape.close()
            yield cat_id, shape

class LoginWindow(QWidget):
    show_project_win_signal = pyqtSignal()
    def __init__(self):
        super(LoginWindow, self).__init__()
        self.init_ui()
        # self.name = name
        # self.password = password

    def init_ui(self):
        self.setGeometry(300, 300, 600, 800)
        bt1 = QPushButton('登录', self)
        bt1.move(50, 250)
        bt1.clicked.connect(self.go_main)
        form_layout = QFormLayout()
        nameLabel = QLabel('用户名')
        self.name = QLineEdit('')
        passLabel = QLabel('密码')
        self.password = QLineEdit('')
        form_layout.addRow(nameLabel, self.name)
        form_layout.addRow(passLabel, self.password)
        self.setLayout(form_layout)
        self.show()

    def go_main(self):
        password = self.password.text().encode('utf-8')
        params = {
            'account': (None, self.name.text()),
            'password': (None, base64.b64encode(password)),
            'language': (None, 'en')
        }
        res_data = requests.post('http://labelhub-cookie.awkvector.com/api/login', files=params)
        resp = json.loads(res_data.text)
        print(res_data)
        print(resp)
        print(resp['code'], ' --- resp code ---')
        if resp['code'] == 1:
            self.show_project_win_signal.emit()

    def setInfo(self):
        self.textEdit.setText('Test')


class ProjectListWindow(QWidget):
    show_main_win_signal = pyqtSignal()

    def __init__(self):
        super(ProjectListWindow, self).__init__()
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()
        table = QTableWidget()
        table.setColumnCount(3)
        table.setItem(
            table.rowCount(),
            0,
            'test'
        )
        table.setItem(
            table.rowCount(),
            1,
            'test'
        )
        table.setItem(
            table.rowCount(),
            2,
            'test'
        )
        horizontal_header = (["项目名称", '项目编号', '操作'])
        table.setHorizontalHeaderLabels(horizontal_header)
        layout.addWidget(table)
        self.setLayout(layout)

    def go_main(self):
        self.show_main_win_signal.emit()


class MainWindow(QMainWindow, WindowMixin):
    FIT_WINDOW, FIT_WIDTH, MANUAL_ZOOM = list(range(3))

    def __init__(self, prefdefClassFile, attributesFile, labelCategories=(("Objects", "object"))):
        super(MainWindow, self).__init__()
        self.setWindowTitle(__appname__)
        # Save as Pascal voc xml
        self.defaultSaveDir = None
        self.usingPascalVocFormat = True
        # For loading all image under a directory
        self.mImgList = []
        self.dirname = None
        self.labelHist = []
        self.attributes = []
        self.lastOpenDir = None

        # Whether we need to save or not.
        self.dirty = False

        # clip board for copying / pasting shapes
        self.clipBoardShapes = None

        self._noSelectionSlot = False

        # Main widgets and related state.

        self.itemsToShapes = defaultdict(dict)
        self.shapesToItems = defaultdict(dict)
        self.prevLabelText = ''

        listLayout = QVBoxLayout()
        listLayout.setContentsMargins(0, 0, 0, 0)

        editButtonsContainer = QWidget()
        editButtonsLayout = QHBoxLayout()
        editButtonsContainer.setLayout(editButtonsLayout)

        self.editButton = QToolButton()
        self.editButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        editButtonsLayout.addWidget(self.editButton)

        # Add some of widgets to listLayout
        # listLayout.addWidget(self.editButton)

        self.editAttributesButton = QToolButton()
        self.editAttributesButton.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        # Add some of widgets to listLayout
        editButtonsLayout.addWidget(self.editAttributesButton)

        listLayout.addWidget(editButtonsContainer)

        # Create and add a widget for showing current label items

        def moved(*args, **kwargs):
            self.setDirty()
            self.canvas.update()

        self.labelCategories = labelCategories
        self.labelLists = dict()

        categoryTab = QTabWidget()
        # import ipdb; ipdb.set_trace()
        categoryTab.sizePolicy().setHorizontalPolicy(QSizePolicy.MinimumExpanding)
        self.categoryTab = categoryTab

        for cat_name, cat_id in labelCategories:
            labelList = QListWidget()
            labelList.setDragDropMode(QAbstractItemView.InternalMove)
            self.labelLists[cat_id] = labelList
            categoryTab.addTab(labelList, cat_name)
            labelList.model().rowsMoved.connect(moved)
            labelList.itemActivated.connect(self.labelSelectionChanged)
            labelList.itemSelectionChanged.connect(self.labelSelectionChanged)
            labelList.itemDoubleClicked.connect(self.editLabel)
            # Connect to itemChanged to detect checkbox changes.
            labelList.itemChanged.connect(self.labelItemChanged)
            labelList.setContextMenuPolicy(Qt.CustomContextMenu)
            labelList.customContextMenuRequested.connect(
                self.popLabelListMenu)

        listLayout.addWidget(categoryTab)  # labelList)  # self.labelList)

        labelListContainer = QWidget()
        labelListContainer.setLayout(listLayout)

        self.dock = QDockWidget(u'Labels', self)
        self.dock.setObjectName(u'Labels')
        self.dock.setWidget(labelListContainer)

        # Tzutalin 20160906 : Add file list and dock to move faster
        self.fileListWidget = QListWidget()
        self.fileListWidget.itemDoubleClicked.connect(self.fileitemDoubleClicked)
        filelistLayout = QVBoxLayout()
        filelistLayout.setContentsMargins(0, 0, 0, 0)
        filelistLayout.addWidget(self.fileListWidget)
        fileListContainer = QWidget()
        fileListContainer.setLayout(filelistLayout)
        self.filedock = QDockWidget(u'File List', self)
        #self.filedock.show()
        self.filedock.setObjectName(u'Files')
        self.filedock.setWidget(fileListContainer)
        self.filedock.setFeatures(QDockWidget.DockWidgetFloatable |
                 QDockWidget.DockWidgetMovable)

        self.zoomWidget = ZoomWidget()
        self.colorDialog = ColorDialog(parent=self)

        def categoryTabChanged(*args, **kwargs):
            self.canvas.update()
            self.labelSelectionChanged()
            self.shapeSelectionChanged(self.currentItem() is not None)

        self.canvas = Canvas()
        categoryTab.currentChanged.connect(categoryTabChanged)
        self.canvas.zoomRequest.connect(self.zoomRequest)

        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setWidgetResizable(True)
        self.scrollBars = {
            Qt.Vertical: scroll.verticalScrollBar(),
            Qt.Horizontal: scroll.horizontalScrollBar()
        }
        self.scrollArea = scroll
        self.canvas.scrollRequest.connect(self.scrollRequest)
        self.canvas.dragRequest.connect(self.dragRequest)

        self.canvas.newShape.connect(self.newShape)
        self.canvas.shapeMoved.connect(self.setDirty)
        self.canvas.selectionChanged.connect(self.shapeSelectionChanged)
        self.canvas.drawingShape.connect(self.toggleDrawingSensitive)

        self.setCentralWidget(scroll)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        # Tzutalin 20160906 : Add file list and dock to move faster
        self.addDockWidget(Qt.RightDockWidgetArea, self.filedock)

        self.dockFeatures = QDockWidget.DockWidgetClosable \
                            | QDockWidget.DockWidgetFloatable
        self.dock.setFeatures(self.dock.features() ^ self.dockFeatures)
        self.filedock.setFeatures(self.filedock.features() ^ self.dockFeatures)

        # Actions
        action = partial(newAction, self)
        quit = action('&Quit', self.close,
                      'Ctrl+Q', 'quit', u'Quit application')

        open = action('&Open', self.openFile,
                      'Ctrl+O', 'open', u'Open image or label file')

        opendir = action('&Open Dir', self.openDir,
                         'Ctrl+u', 'open', u'Open Dir')

        changeSavedir = action('&Change Save Dir', self.changeSavedir,
                               'Ctrl+r', 'open', u'Change default saved Annotation dir')

        openAnnotation = action('&Open Annotation', self.openAnnotation,
                                'Ctrl+Shift+O', 'open', u'Open Annotation')

        openNextImg = action('&Next Image', self.openNextImg,
                             'd', 'next', u'Open Next')

        openPrevImg = action('&Prev Image', self.openPrevImg,
                             'a', 'prev', u'Open Prev')

        save = action('&Save', self.saveFile,
                      'Ctrl+S', 'save', u'Save labels to file', enabled=True)
        saveAs = action('&Save As', self.saveFileAs,
                        'Ctrl+Shift+S', 'save-as', u'Save labels to a different file',
                        enabled=False)
        close = action('&Close', self.closeFile,
                       'Ctrl+W', 'close', u'Close current file')

        # createMode = action('Create\nRectBox', self.setCreateMode,
        #                     'Ctrl+N', 'new', u'Start drawing Boxs', enabled=False)
        #
        # editMode = action('&Edit\nRectBox', self.setEditMode,
        #                   'Ctrl+J', 'edit', u'Move and edit Boxs', enabled=False)

        # create = action('Create\nRectBox', self.createShape,
        #                'w', 'new', u'Draw a new Box', enabled=False)
        createPolygon = action('Create Polygon', self.createPolygon,
                               'w', 'new', u'Draw a new Polygon', enabled=False)

        brushRadiusWidget = ZoomWidget(value=self.canvas.brushRadius())
        brushRadiusWidget.setPrefix('Radius: ')
        brushRadiusWidget.setSuffix(' px')
        brushRadiusWidget.setToolTip('Radius of brush')
        brushRadiusWidget.setButtonSymbols(QAbstractSpinBox.UpDownArrows)

        def brushRadiusChanged(*_, **__):
            self.canvas.setBrushRadius(self.brushRadiusWidget.value())

        brushRadiusWidget.valueChanged.connect(brushRadiusChanged)
        self.brushRadiusWidget = brushRadiusWidget

        setBrushRadius = QWidgetAction(self)
        setBrushRadius.setDefaultWidget(brushRadiusWidget)

        createBrush = action('Draw Brush', self.createBrush,
                             'b', 'new', u'Draw a new Brush', enabled=False)

        eraseBrush = action('Start Erasing', self.eraseBrush,
                            'e', 'new', u'Erase regions from Brush', enabled=False)

        copyAllShapes = action('Copy Shapes', self.copyAllShapes,
                               'Ctrl+C', 'copy', u'Copy all annotations to the clipboard', enabled=False)

        pasteAllShapes = action('Paste Shapes', self.pasteAllShapes,
                                'Ctrl+V', 'copy',
                                u'Paste all (and overwrite any existing) annotations in the clipboard',
                                enabled=False)

        delete = action('Delete', self.deleteSelectedShape,
                        'Delete', 'delete', u'Delete', enabled=False)
        # copy = action('&Duplicate\nRectBox', self.copySelectedShape,
        #               'Ctrl+D', 'copy', u'Create a duplicate of the selected Box',
        #               enabled=False)

        # advancedMode = action('&Advanced Mode', self.toggleAdvancedMode,
        #                       'Ctrl+Shift+A', 'expert', u'Switch to advanced mode',
        #                       checkable=True)

        hideAll = action('&Hide\nRectBox', partial(self.togglePolygons, False),
                         'Ctrl+H', 'hide', u'Hide all Boxs',
                         enabled=False)
        showAll = action('&Show\nRectBox', partial(self.togglePolygons, True),
                         'Ctrl+A', 'hide', u'Show all Boxs',
                         enabled=False)

        zoom = QWidgetAction(self)
        zoom.setDefaultWidget(self.zoomWidget)
        self.zoomWidget.setWhatsThis(
            u"Zoom in or out of the image. Also accessible with"
            " %s and %s from the canvas." % (fmtShortcut("Ctrl+[-+]"),
                                             fmtShortcut("Ctrl+Wheel")))
        self.zoomWidget.setEnabled(False)

        zoomIn = action('Zoom &In', partial(self.addZoom, 10),
                        'Ctrl++', 'zoom-in', u'Increase zoom level', enabled=False)
        zoomOut = action('&Zoom Out', partial(self.addZoom, -10),
                         'Ctrl+-', 'zoom-out', u'Decrease zoom level', enabled=False)
        zoomOrg = action('&Original size', partial(self.setZoom, 100),
                         'Ctrl+=', 'zoom', u'Zoom to original size', enabled=False)
        fitWindow = action('&Fit Window', self.setFitWindow,
                           'Ctrl+F', 'fit-window', u'Zoom follows window size',
                           checkable=True, enabled=False)
        fitWidth = action('Fit &Width', self.setFitWidth,
                          'Ctrl+Shift+F', 'fit-width', u'Zoom follows window width',
                          checkable=True, enabled=False)
        toggleRangeIndicator = action('Show &Range Indicator', self.toggleRangeCursor,
                                      None, 'fit-width', u'Toggle appearance of range indicator.',
                                      checkable=True, enabled=True)

        rangeWidget = ZoomWidget(value=self.canvas.trackRadius())
        rangeWidget.setPrefix('Radius: ')
        rangeWidget.setSuffix(' px')
        rangeWidget.setToolTip('Radius of indicated range')
        rangeWidget.setButtonSymbols(QAbstractSpinBox.UpDownArrows)

        def rangeChanged(*_, **__):
            self.canvas.setTrackRadius(self.rangeWidget.value())

        rangeWidget.valueChanged.connect(rangeChanged)
        self.rangeWidget = rangeWidget
        setRange = QWidgetAction(self)
        setRange.setDefaultWidget(rangeWidget)

        self.toggleRangeIndicator = toggleRangeIndicator
        # Group zoom controls into a list for easier toggling.
        zoomActions = (self.zoomWidget, zoomIn, zoomOut,
                       zoomOrg, fitWindow, fitWidth)
        self.zoomMode = self.MANUAL_ZOOM
        self.scalers = {
            self.FIT_WINDOW: self.scaleFitWindow,
            self.FIT_WIDTH: self.scaleFitWidth,
            # Set to one to scale to 100% when loading files.
            self.MANUAL_ZOOM: lambda: 1,
        }

        edit = action('&Edit Label', self.editLabel,
                      'Ctrl+E', 'edit', u'Modify the label of the selected region',
                      enabled=False)
        self.editButton.setDefaultAction(edit)
        editAttributes = action('&Edit Attributes', self.editAttributes,
                                None, 'edit', u'Modify the attributes of the selected region',
                                enabled=False)
        self.editAttributesButton.setDefaultAction(editAttributes)

        shapeLineColor = action('Shape &Line Color', self.chshapeLineColor,
                                icon='color_line', tip=u'Change the line color for this specific shape',
                                enabled=False)
        shapeFillColor = action('Shape &Fill Color', self.chshapeFillColor,
                                icon='color', tip=u'Change the fill color for this specific shape',
                                enabled=False)

        labels = self.dock.toggleViewAction()
        labels.setText('Show/Hide Label Panel')
        labels.setShortcut('Ctrl+Shift+L')

        fileListAction = self.filedock.toggleViewAction()
        fileListAction.setText('Show/Hide File List')
        fileListAction.setShortcut('Ctrl+Shift+F')

        # Lavel list context menu.
        labelMenu = QMenu()
        addActions(labelMenu, (edit, delete))

        # Store actions for further handling.
        self.actions = struct(save=save, saveAs=saveAs, open=open, close=close,
                              delete=delete, edit=edit, editAttributes=editAttributes,
                              createPolygon=createPolygon,
                              createBrush=createBrush,
                              eraseBrush=eraseBrush,
                              copyAllShapes=copyAllShapes,
                              pasteAllShapes=pasteAllShapes,
                              # createMode=createMode, editMode=editMode,
                              # advancedMode=advancedMode,
                              shapeLineColor=shapeLineColor, shapeFillColor=shapeFillColor,
                              zoom=zoom, zoomIn=zoomIn, zoomOut=zoomOut, zoomOrg=zoomOrg,
                              fitWindow=fitWindow, fitWidth=fitWidth,
                              zoomActions=zoomActions,
                              fileMenuActions=(
                                  open, opendir, save, saveAs, close, quit),
                              beginner=(),  # advanced=(),
                              editMenu=(edit,
                                        # copy,
                                        delete,
                                        None),
                              beginnerContext=(createPolygon, copyAllShapes, pasteAllShapes, edit,
                                               # copy,
                                               delete),
                              # advancedContext=(createMode, editMode, edit, copy,
                              #                  delete, shapeLineColor, shapeFillColor),
                              onLoadActive=(
                                  close, createPolygon,
                                  copyAllShapes,
                                  pasteAllShapes,
                                  # createMode, editMode
                              ),
                              onShapesPresent=(saveAs, hideAll, showAll))

        self.menus = struct(
            file=self.menu('&File'),
            edit=self.menu('&Edit'),
            view=self.menu('&View'),
            recentFiles=QMenu('Open &Recent'),
            labelList=labelMenu)

        # Auto saving : Enble auto saving if pressing next
        self.autoSaving = QAction("Auto Saving", self)
        self.autoSaving.setCheckable(True)
        self.autoSaving.setChecked(True)

        # # Sync single class mode from PR#106
        # self.singleClassMode = QAction("Single Class Mode", self)
        # self.singleClassMode.setShortcut("Ctrl+Shift+S")
        # self.singleClassMode.setCheckable(True)
        self.lastLabel = None

        addActions(self.menus.file,
                   (open, opendir, changeSavedir, openAnnotation, self.menus.recentFiles, save, saveAs, close, None,
                    quit))
        addActions(self.menus.view, (
            self.autoSaving,
            # self.singleClassMode,
            labels,
            fileListAction,
            # advancedMode,
            None,
            hideAll, showAll, None,
            zoomIn, zoomOut, zoomOrg, None,
            fitWindow, fitWidth, toggleRangeIndicator))

        fileListAction.setEnabled(True)

        self.menus.file.aboutToShow.connect(self.updateFileMenu)

        # Custom context menu for the canvas widget:
        addActions(self.canvas.menus[0], self.actions.beginnerContext)
        addActions(self.canvas.menus[1], (
            action('&Copy here', self.copyShape),
            action('&Move here', self.moveShape)))

        self.tools = self.toolbar('Tools')
        self.actions.beginner = (
            # open, opendir, changeSavedir,
            openNextImg, openPrevImg,
            # verify,
            save, None, createPolygon,
            setBrushRadius,
            createBrush,
            eraseBrush,
            copyAllShapes,
            pasteAllShapes,
            fileListAction,
            # copy,
            delete, None,
            zoomIn, zoom, zoomOut, fitWindow, fitWidth, setRange, toggleRangeIndicator)

        self.statusBar().showMessage('%s started.' % __appname__)
        self.statusBar().show()

        # Application state.
        self.image = QImage()
        self.filePath = None
        self.recentFiles = []
        self.maxRecent = 7
        self.lineColor = None
        self.fillColor = None
        self.zoom_level = 100
        self.fit_window = False
        # Add Chris
        # self.difficult = False

        # Load predefined classes to the list
        self.loadPredefinedClasses(prefdefClassFile)
        self.loadAttributes(attributesFile)
        self.predefinedClasses = list(self.labelHist)

        self.labelDialog = LabelDialog(parent=self, listItem=self.labelHist, labelLists=self.labelLists,
                                       predefinedClasses=self.predefinedClasses)

        self.attributesDialog = AttributesDialog(parent=self, attributes=self.attributes, labelLists=self.labelLists)

        # XXX: Could be completely declarative.
        # Restore application settings.
        if have_qstring():
            types = {
                'filename': QString,
                'recentFiles': QStringList,
                'window/size': QSize,
                'window/position': QPoint,
                'window/geometry': QByteArray,
                'line/color': QColor,
                'fill/color': QColor,
                # 'advanced': bool,
                # Docks and toolbars:
                'window/state': QByteArray,
                'savedir': QString,
                'lastOpenDir': QString,
            }
        else:
            types = {
                'filename': str,
                'recentFiles': list,
                'window/size': QSize,
                'window/position': QPoint,
                'window/geometry': QByteArray,
                'line/color': QColor,
                'fill/color': QColor,
                # 'advanced': bool,
                # Docks and toolbars:
                'window/state': QByteArray,
                'savedir': str,
                'lastOpenDir': str,
            }

        self.settings = settings = Settings(types)
        self.recentFiles = list(settings.get('recentFiles', []) or [])
        size = settings.get('window/size', QSize(600, 500))
        position = settings.get('window/position', QPoint(0, 0))
        self.resize(size)
        self.move(position)
        saveDir = ustr(settings.get('savedir', None))
        self.lastOpenDir = ustr(settings.get('lastOpenDir', None))
        if saveDir is not None and os.path.exists(saveDir):
            self.defaultSaveDir = saveDir
            self.statusBar().showMessage('%s started. Annotation will be saved to %s' %
                                         (__appname__, self.defaultSaveDir))
            self.statusBar().show()

        # or simply:
        # self.restoreGeometry(settings['window/geometry']
        self.restoreState(settings.get('window/state', QByteArray()))
        self.lineColor = QColor(settings.get('line/color', Shape.line_color))
        self.fillColor = QColor(settings.get('fill/color', Shape.fill_color))
        Shape.line_color = self.lineColor
        Shape.fill_color = self.fillColor

        # Add chris
        # Shape.difficult = self.difficult

        def xbool(x):
            if isinstance(x, QVariant):
                return x.toBool()
            return bool(x)

        # if xbool(settings.get('advanced', False)):
        #     self.actions.advancedMode.setChecked(True)
        #     self.toggleAdvancedMode()

        # Populate the File menu dynamically.
        self.updateFileMenu()
        # Since loading the file may take some time, make sure it runs in the
        # background.
        self.queueEvent(partial(self.loadFile, self.filePath or ""))

        # Callbacks:
        self.zoomWidget.valueChanged.connect(self.paintCanvas)

        self.populateModeActions()

    ## Support Functions ##

    def toggleRangeCursor(self):
        self.canvas.setShowRangeCursor(not self.canvas.showRangeCursor())
        if self.canvas.showRangeCursor():
            self.toggleRangeIndicator.setText("Hide Range Indicator")
        else:
            self.toggleRangeIndicator.setText("Show Range Indicator")
        self.canvas.update()

    @property
    def currentCategoryId(self):
        return self.labelCategories[self.categoryTab.currentIndex()][1]

    @property
    def currentLabelList(self):
        return self.labelLists[self.currentCategoryId]

    def noShapes(self):
        return not self.itemsToShapes[self.currentCategoryId]

    def copyAllShapes(self):
        if len(self.canvas.shapes) > 0:
            self.clipBoardShapes = copy.deepcopy(self.canvas.sortedShapes)
        else:
            self.status('There are no shapes to be copied!')

    def pasteAllShapes(self):
        if self.clipBoardShapes:
            if self.dirty or len(self.canvas.shapes) > 0:
                yes, no = QMessageBox.Yes, QMessageBox.No
                msg = u'Doing this will overwrite any unsaved changes. Proceed anyway?'
                if not (yes == QMessageBox.warning(self, u'Attention', msg, yes | no)):
                    return
            self.canvas.shapes[self.currentCategoryId] = copy.deepcopy(self.clipBoardShapes)
            self.labelHist = []
            self.currentLabelList.clear()
            for shape in self.canvas.currentShapes:
                self.addLabel(self.currentCategoryId, shape)
                if shape.label not in self.labelHist:
                    self.labelHist.append(shape.label)
            self.paintCanvas()
            self.update()
            self.status('Shapes copied!')
            self.setDirty()
        else:
            self.status('There are no shapes in the clipboard!')

    def populateModeActions(self):
        # if self.beginner():
        tool, menu = self.actions.beginner, self.actions.beginnerContext
        # else:
        #     raise NotImplementedError
        # tool, menu = self.actions.advanced, self.actions.advancedContext
        self.tools.clear()
        addActions(self.tools, tool)
        self.canvas.menus[0].clear()
        addActions(self.canvas.menus[0], menu)
        self.menus.edit.clear()
        actions = (
            self.actions.createPolygon, self.actions.copyAllShapes, self.actions.pasteAllShapes)  # if self.beginner() \
        addActions(self.menus.edit, actions + self.actions.editMenu)

    # def setBeginner(self):
    #     self.tools.clear()
    #     addActions(self.tools, self.actions.beginner)
    #
    # def setAdvanced(self):
    #     self.tools.clear()
    #     addActions(self.tools, self.actions.advanced)

    def setDirty(self):
        self.dirty = True
        self.actions.save.setEnabled(True)

    def setClean(self):
        self.dirty = False
        self.actions.save.setEnabled(True)
        # self.actions.create.setEnabled(True)
        self.actions.createPolygon.setEnabled(True)
        self.actions.createBrush.setEnabled(True)
        self.actions.eraseBrush.setEnabled(False)
        self.actions.copyAllShapes.setEnabled(True)
        self.actions.pasteAllShapes.setEnabled(True)

    def toggleActions(self, value=True):
        """Enable/Disable widgets which depend on an opened image."""
        for z in self.actions.zoomActions:
            z.setEnabled(value)
        for action in self.actions.onLoadActive:
            action.setEnabled(value)

    def queueEvent(self, function):
        QTimer.singleShot(0, function)

    def status(self, message, delay=5000):
        self.statusBar().showMessage(message, delay)

    def resetState(self):
        self.itemsToShapes.clear()
        self.shapesToItems.clear()
        for labelList in self.labelLists.values():
            labelList.clear()
        self.filePath = None
        self.imageData = None
        self.labelFile = None
        self.canvas.resetState()

    def currentItem(self):
        items = self.currentLabelList.selectedItems()
        if items:
            return items[0]
        return None

    def addRecentFile(self, filePath):
        if filePath in self.recentFiles:
            self.recentFiles.remove(filePath)
        elif len(self.recentFiles) >= self.maxRecent:
            self.recentFiles.pop()
        self.recentFiles.insert(0, filePath)

    # def beginner(self):
    #     return self._beginner

    # def advanced(self):
    #     return not self.beginner()

    def createShape(self):
        # assert self.beginner()
        self.canvas.setMode(Canvas.CREATE)
        self.actions.createPolygon.setEnabled(False)
        self.actions.createBrush.setEnabled(False)
        self.actions.eraseBrush.setEnabled(False)
        self.actions.copyAllShapes.setEnabled(False)
        self.actions.pasteAllShapes.setEnabled(False)

    def createPolygon(self):
        self.canvas.setMode(Canvas.CREATE_POLYGON)
        self.actions.createPolygon.setEnabled(False)
        self.actions.createBrush.setEnabled(False)
        self.actions.eraseBrush.setEnabled(False)
        self.actions.copyAllShapes.setEnabled(False)
        self.actions.pasteAllShapes.setEnabled(False)
        self.filedock.setEnabled(False)
        self.dock.setEnabled(False)

    def createBrush(self):
        if self.canvas.mode == Canvas.CREATE_BRUSH:
            # finish drawing brush
            self.canvas.setErasing(False)
            if self.canvas.current is not None:
                self.canvas.finalize()
            else:
                self.canvas.setMode(Canvas.EDIT)
                self.actions.createBrush.setText("Draw Brush")
                self.actions.createPolygon.setEnabled(True)
                self.actions.createBrush.setEnabled(True)
                self.actions.eraseBrush.setEnabled(False)
                self.actions.eraseBrush.setText("Start Erasing")
                self.actions.delete.setEnabled(False)
                self.actions.copyAllShapes.setEnabled(True)
                self.actions.pasteAllShapes.setEnabled(True)
            self.filedock.setEnabled(True)
            self.dock.setEnabled(True)
        elif self.canvas.mode == Canvas.EDIT_BRUSH:
            self.canvas.deSelectShape()
            self.canvas.setMode(Canvas.EDIT)
            self.canvas.setErasing(False)
            self.actions.createBrush.setText("Draw Brush")
            self.actions.createPolygon.setEnabled(True)
            self.actions.createBrush.setEnabled(True)
            self.actions.eraseBrush.setEnabled(False)
            self.actions.eraseBrush.setText("Start Erasing")
            self.actions.delete.setEnabled(False)
            self.actions.copyAllShapes.setEnabled(True)
            self.actions.pasteAllShapes.setEnabled(True)
            self.filedock.setEnabled(True)
            self.dock.setEnabled(True)
        elif self.canvas.mode == Canvas.EDIT:
            if self.canvas.selectedShape is not None and isinstance(self.canvas.selectedShape, Brush):
                self.canvas.setMode(Canvas.EDIT_BRUSH)
            else:
                self.canvas.setMode(Canvas.CREATE_BRUSH)
            self.actions.createBrush.setText("Finish Brush")
            self.canvas.setErasing(False)
            self.actions.createPolygon.setEnabled(False)
            self.actions.createBrush.setEnabled(True)
            self.actions.eraseBrush.setEnabled(True)
            self.actions.delete.setEnabled(False)
            self.actions.copyAllShapes.setEnabled(False)
            self.actions.pasteAllShapes.setEnabled(False)
            self.filedock.setEnabled(False)
            self.dock.setEnabled(False)
        else:
            raise NotImplementedError

    def eraseBrush(self):
        # self.canvas.setMode(Canvas.CREATE_BRUSH)
        if self.canvas.mode == Canvas.CREATE_BRUSH:
            self.canvas.setErasing(not self.canvas.erasing())
            self.actions.createPolygon.setEnabled(False)
            self.actions.createBrush.setEnabled(True)
            self.actions.eraseBrush.setEnabled(True)
            self.actions.copyAllShapes.setEnabled(False)
            self.actions.pasteAllShapes.setEnabled(False)
            self.actions.delete.setEnabled(False)
            if self.canvas.erasing():
                self.actions.eraseBrush.setText("Stop Erasing")
            else:
                self.actions.eraseBrush.setText("Start Erasing")
        elif self.canvas.mode == Canvas.EDIT_BRUSH:
            self.canvas.setErasing(not self.canvas.erasing())
            self.actions.delete.setEnabled(False)
            if self.canvas.erasing():
                self.actions.eraseBrush.setText("Stop Erasing")
            else:
                self.actions.eraseBrush.setText("Start Erasing")
        elif self.canvas.mode == Canvas.EDIT:
            assert self.canvas.selectedShape is not None and isinstance(self.canvas.selectedShape, Brush)
            self.canvas.setMode(Canvas.EDIT_BRUSH)
            self.actions.createBrush.setText("Finish Brush")
            assert not self.canvas.erasing()
            self.actions.eraseBrush.setText("Stop Erasing")
            self.canvas.setErasing(True)
            self.actions.delete.setEnabled(False)
            self.actions.createPolygon.setEnabled(False)
            self.actions.createBrush.setEnabled(True)
            self.actions.eraseBrush.setEnabled(True)
            self.actions.copyAllShapes.setEnabled(False)
            self.actions.pasteAllShapes.setEnabled(False)

    def toggleDrawingSensitive(self, drawing=True):
        """In the middle of drawing, toggling between modes should be disabled."""
        if not drawing:
            self.canvas.setMode(Canvas.EDIT)
            self.canvas.restoreCursor()
            self.actions.createPolygon.setEnabled(True)
            self.actions.createBrush.setEnabled(True)
            self.actions.copyAllShapes.setEnabled(True)
            self.actions.pasteAllShapes.setEnabled(True)

    def updateFileMenu(self):
        currFilePath = self.filePath

        def exists(filename):
            return os.path.exists(filename)

        menu = self.menus.recentFiles
        menu.clear()
        files = [f for f in self.recentFiles if f !=
                 currFilePath and exists(f)]
        for i, f in enumerate(files):
            icon = newIcon('labels')
            action = QAction(
                icon, '&%d %s' % (i + 1, QFileInfo(f).fileName()), self)
            action.triggered.connect(partial(self.loadRecent, f))
            menu.addAction(action)

    def popLabelListMenu(self, point):
        self.menus.labelList.exec_(self.currentLabelList.mapToGlobal(point))

    def editLabel(self, item=None):
        if not self.canvas.editing():
            return
        item = item if item else self.currentItem()
        shape = self.itemsToShapes[self.currentCategoryId][item]
        label = self.labelDialog.popUp(shape.label)
        if label is not None:
            shape.label = label
            item.setText(shape.labelWithAttributes)
            self.setDirty()

    def editAttributes(self, item=None):
        if not self.canvas.editing():
            return
        item = item if item else self.currentItem()
        shape = self.itemsToShapes[self.currentCategoryId][item]
        attributes = self.attributesDialog.popUp(shape.attributes)
        if attributes is not None:
            shape.attributes = attributes
            item.setText(shape.labelWithAttributes)
            self.setDirty()

    # Tzutalin 20160906 : Add file list and dock to move faster
    def fileitemDoubleClicked(self, item=None):
        if not self.dirty or self.dirty and self.mayContinue():
            currIndex = self.mImgList.index(ustr(item.text()).replace(' (labeled)', ''))
            if currIndex < len(self.mImgList):
                filename = self.mImgList[currIndex]
                if filename:
                    self.loadFile(filename)

    # Add chris
    def btnstate(self, item=None):
        """ Function to handle difficult examples
        Update on each object """
        if not self.canvas.editing():
            return

        item = self.currentItem()
        if not item:  # If not selected Item, take the first one
            item = self.currentLabelList.item(self.currentLabelList.count() - 1)

        # difficult = self.diffcButton.isChecked()

        try:
            shape = self.itemsToShapes[self.currentCategoryId][item]
        except:
            pass
        # Checked and Update
        try:
            # if difficult != shape.difficult:
            #     shape.difficult = difficult
            #     self.setDirty()
            # else:  # User probably changed item visibility
            self.canvas.setShapeVisible(shape, item.checkState() == Qt.Checked)
        except:
            pass

    # React to canvas signals.
    def shapeSelectionChanged(self, selected=False):
        if self._noSelectionSlot:
            self._noSelectionSlot = False
        else:
            shape = self.canvas.selectedShape
            if shape is not None:
                self.shapesToItems[self.currentCategoryId][shape].setSelected(True)

                if isinstance(shape, Brush) and selected:
                    self.actions.createBrush.setText('Add Brush')
                    self.actions.createBrush.setEnabled(True)
                    self.actions.eraseBrush.setEnabled(True)
            else:
                self.currentLabelList.clearSelection()
        if not selected and self.canvas.mode == Canvas.EDIT:
            self.actions.createBrush.setText('Create Brush')
            self.actions.eraseBrush.setText('Start Erasing')
            self.actions.createBrush.setEnabled(True)
            self.actions.eraseBrush.setEnabled(False)

        self.actions.delete.setEnabled(selected)
        self.actions.edit.setEnabled(selected)
        self.actions.editAttributes.setEnabled(selected)
        self.actions.shapeLineColor.setEnabled(selected)
        self.actions.shapeFillColor.setEnabled(selected)

    def addLabel(self, categoryId, shape, index=None):
        item = HashableQListWidgetItem(shape.labelWithAttributes)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        self.itemsToShapes[categoryId][item] = shape
        self.shapesToItems[categoryId][shape] = item
        if index is None:
            self.labelLists[categoryId].addItem(item)
        else:
            self.labelLists[categoryId].insertItem(index, item)
        for action in self.actions.onShapesPresent:
            action.setEnabled(True)

    def remLabel(self, shape):
        if shape is None:
            # print('rm empty label')
            return
        item = self.shapesToItems[self.currentCategoryId][shape]
        self.currentLabelList.takeItem(self.currentLabelList.row(item))
        del self.shapesToItems[self.currentCategoryId][shape]
        del self.itemsToShapes[self.currentCategoryId][item]

    def loadLabels(self, shapes):
        ss = defaultdict(list)
        for cat_id, shape in loadLabels(shapes, self.labelCategories):
            self.addLabel(cat_id, shape)
            ss[cat_id].append(shape)
        self.canvas.loadShapes(ss)

    def saveLabels(self, annotationFilePath):
        annotationFilePath = ustr(annotationFilePath)
        if self.labelFile is None:
            self.labelFile = LabelFile()
            self.labelFile.verified = self.canvas.verified

        def format_shape(s):
            if isinstance(s, Polygon):
                return dict(
                    type="polygon",
                    label=s.label,
                    attributes=s.attributes,
                    points=[(p.x(), p.y()) for p in s.points],
                )
            elif isinstance(s, Shape):
                return dict(
                    type="rect",
                    label=s.label,
                    attributes=s.attributes,
                    points=[(p.x(), p.y()) for p in s.points],
                )
            elif isinstance(s, Brush):
                return dict(
                    type="brush",
                    label=s.label,
                    attributes=s.attributes,
                    size=(s.size.width(), s.size.height()),
                    history=s.history,
                    offset=(s.offset.x(), s.offset.y()),
                )
            else:
                raise NotImplementedError

        shapes = {
            categoryId: [format_shape(shape) for shape in self.canvas.getSortedShapes(categoryId)]
            for _, categoryId in self.labelCategories
        }

        # Can add differrent annotation formats here
        try:
            if self.usingPascalVocFormat is True:
                self.labelFile.savePascalVocFormat(annotationFilePath, shapes, self.filePath, self.imageData,
                                                   self.labelCategories)
            else:
                raise NotImplementedError
                self.labelFile.save(annotationFilePath, shapes, self.filePath, self.imageData,
                                    self.lineColor.getRgb(), self.fillColor.getRgb())
            return True
        except LabelFileError as e:
            self.errorMessage(u'Error saving label data',
                              u'<b>%s</b>' % e)
            return False

    def copySelectedShape(self):
        self.addLabel(self.canvas.copySelectedShape())
        # fix copy and delete
        self.shapeSelectionChanged(True)

    def labelSelectionChanged(self):
        item = self.currentItem()
        if item and self.canvas.editing() and item in self.itemsToShapes[self.currentCategoryId]:
            self._noSelectionSlot = True
            shape = self.itemsToShapes[self.currentCategoryId][item]
            self.canvas.selectShape(shape)
            if isinstance(shape, Brush):
                self.actions.createBrush.setText('Add Brush')
                self.actions.createBrush.setEnabled(True)
                self.actions.eraseBrush.setEnabled(True)
        else:
            self.canvas.deSelectShape()
            self.canvas.setMode(self.canvas.EDIT)

    def labelItemChanged(self, item):
        shape = self.itemsToShapes[self.currentCategoryId][item]
        # label = item.text()
        # if label != shape.label:
        #     shape.label = item.text()
        # self.setDirty()
        # else:  # User probably changed item visibility
        self.canvas.setShapeVisible(shape, item.checkState() == Qt.Checked)

    # Callback functions:
    def newShape(self):
        """Pop-up and give focus to the label editor.

        position MUST be in global coordinates.
        """
        # if not self.useDefautLabelCheckbox.isChecked() or not self.defaultLabelTextLine.text():
        if len(self.labelHist) > 0:
            self.labelDialog = LabelDialog(
                parent=self, listItem=self.labelHist, labelLists=self.labelLists,
                predefinedClasses=self.predefinedClasses)

        # Sync single class mode from PR#106
        # if self.singleClassMode.isChecked() and self.lastLabel:
        #     text = self.lastLabel
        # else:

        boxIds = [int(x[3:].split(' ')[0]) for x in self.labelHist if x.startswith('box')]
        if len(boxIds) > 0:
            newBoxId = max(boxIds) + 1
        else:
            newBoxId = 1
        text = self.labelDialog.popUp(text=f'box{newBoxId}')
        self.lastLabel = text
        # else:
        #     text = self.defaultLabelTextLine.text()

        # Add Chris
        # self.diffcButton.setChecked(False)
        if text is not None:
            self.prevLabelText = text
            if laterOnTop:
                self.addLabel(self.currentCategoryId, self.canvas.setLastLabel(text), index=0)
            else:
                self.addLabel(self.currentCategoryId, self.canvas.setLastLabel(text))
            # if self.beginner():  # Switch to edit mode.
            self.canvas.setMode(Canvas.EDIT)
            # self.actions.create.setEnabled(True)
            self.actions.createPolygon.setEnabled(True)
            self.actions.copyAllShapes.setEnabled(True)
            self.actions.pasteAllShapes.setEnabled(True)
            self.actions.createBrush.setText("Draw Brush")
            self.actions.createBrush.setEnabled(True)
            self.actions.eraseBrush.setEnabled(False)
            self.actions.eraseBrush.setText("Start Erasing")
            self.filedock.setEnabled(True)
            self.dock.setEnabled(True)
            self.setDirty()

            if text not in self.labelHist:
                if laterOnTop:
                    self.labelHist.insert(0, text)
                else:
                    self.labelHist.append(text)
        else:
            if self.canvas.drawingRect():
                self.canvas.resetAllLines()
            elif self.canvas.drawingPolygon():
                self.canvas.undoLastLine()
            elif self.canvas.drawingBrush():
                self.canvas.undoNewBrush()

    def scrollRequest(self, delta, orientation):
        units = - delta / (8 * 15)
        bar = self.scrollBars[orientation]
        bar.setValue(bar.value() + bar.singleStep() * units)

    def dragRequest(self, delta, orientation):
        bar = self.scrollBars[orientation]
        bar.setValue(bar.value() - delta)

    def setZoom(self, value):
        self.actions.fitWidth.setChecked(False)
        self.actions.fitWindow.setChecked(False)
        self.zoomMode = self.MANUAL_ZOOM
        self.zoomWidget.setValue(value)

    def addZoom(self, increment=10):
        self.setZoom(self.zoomWidget.value() + increment)

    def zoomRequest(self, delta):
        # get the current scrollbar positions
        # calculate the percentages ~ coordinates
        h_bar = self.scrollBars[Qt.Horizontal]
        v_bar = self.scrollBars[Qt.Vertical]

        # get the current maximum, to know the difference after zooming
        h_bar_max = h_bar.maximum()
        v_bar_max = v_bar.maximum()

        # get the cursor position and canvas size
        # calculate the desired movement from 0 to 1
        # where 0 = move left
        #       1 = move right
        # up and down analogous
        cursor = QCursor()
        pos = cursor.pos()

        cursor_x = pos.x()
        cursor_y = pos.y()

        w = self.scrollArea.width()
        h = self.scrollArea.height()

        # the scaling from 0 to 1 has some padding
        # you don't have to hit the very leftmost pixel for a maximum-left movement
        margin = 0.1
        move_x = (cursor_x - margin * w) / (w - 2 * margin * w)
        move_y = (cursor_y - margin * h) / (h - 2 * margin * h)

        # clamp the values form 0 to 1
        move_x = min(max(move_x, 0), 1)
        move_y = min(max(move_y, 0), 1)

        # zoom in
        units = delta / (8 * 15)
        scale = 10
        self.addZoom(scale * units)

        # get the difference in scrollbar values
        # this is how far we can move
        d_h_bar_max = h_bar.maximum() - h_bar_max
        d_v_bar_max = v_bar.maximum() - v_bar_max

        # get the new scrollbar values
        new_h_bar_value = h_bar.value() + move_x * d_h_bar_max
        new_v_bar_value = v_bar.value() + move_y * d_v_bar_max

        h_bar.setValue(new_h_bar_value)
        v_bar.setValue(new_v_bar_value)

    def setFitWindow(self, value=True):
        if value:
            self.actions.fitWidth.setChecked(False)
        self.zoomMode = self.FIT_WINDOW if value else self.MANUAL_ZOOM
        self.adjustScale()

    def setFitWidth(self, value=True):
        if value:
            self.actions.fitWindow.setChecked(False)
        self.zoomMode = self.FIT_WIDTH if value else self.MANUAL_ZOOM
        self.adjustScale()

    def togglePolygons(self, value):
        for item, shape in self.itemsToShapes[self.currentCategoryId].items():
            item.setCheckState(Qt.Checked if value else Qt.Unchecked)

    def loadFile(self, filePath=None):
        """Load the specified file, or the last opened file if None."""
        self.resetState()
        self.canvas.setEnabled(False)
        if filePath is None:
            filePath = self.settings.get('filename')

        unicodeFilePath = ustr(filePath)
        # Tzutalin 20160906 : Add file list and dock to move faster
        # Highlight the file item
        if unicodeFilePath and self.fileListWidget.count() > 0:
            index = self.mImgList.index(unicodeFilePath)
            fileWidgetItem = self.fileListWidget.item(index)
            fileWidgetItem.setSelected(True)

        if unicodeFilePath and os.path.exists(unicodeFilePath):
            if LabelFile.isLabelFile(unicodeFilePath):
                try:
                    self.labelFile = LabelFile(unicodeFilePath)
                except LabelFileError as e:
                    self.errorMessage(u'Error opening file',
                                      (u"<p><b>%s</b></p>"
                                       u"<p>Make sure <i>%s</i> is a valid label file.")
                                      % (e, unicodeFilePath))
                    self.status("Error reading %s" % unicodeFilePath)
                    return False
                self.imageData = self.labelFile.imageData
                self.lineColor = QColor(*self.labelFile.lineColor)
                self.fillColor = QColor(*self.labelFile.fillColor)
            else:
                # Load image:
                # read data first and store for saving into label file.
                self.imageData = read(unicodeFilePath, None)
                self.labelFile = None
            image = QImage.fromData(self.imageData)
            if image.isNull():
                self.errorMessage(u'Error opening file',
                                  u"<p>Make sure <i>%s</i> is a valid image file." % unicodeFilePath)
                self.status("Error reading %s" % unicodeFilePath)
                return False
            self.status("Loaded %s" % os.path.basename(unicodeFilePath))
            self.image = image
            self.filePath = unicodeFilePath
            self.canvas.loadPixmap(QPixmap.fromImage(image))
            if self.labelFile:
                self.loadLabels(self.labelFile.shapes)
            self.setClean()
            self.canvas.setEnabled(True)
            self.adjustScale(initial=True)
            self.paintCanvas()
            self.addRecentFile(self.filePath)
            self.toggleActions(True)

            # Label xml file and show bound box according to its filename
            if self.usingPascalVocFormat is True:
                if self.defaultSaveDir is not None:
                    basename = os.path.basename(
                        os.path.splitext(self.filePath)[0]) + XML_EXT
                    xmlPath = os.path.join(self.defaultSaveDir, basename)
                    import ipdb;
                    ipdb.set_trace()
                    self.loadPascalXMLByFilename(xmlPath, self.labelCategories)
                else:
                    xmlPath = os.path.splitext(filePath)[0] + XML_EXT
                    if os.path.isfile(xmlPath):
                        self.loadPascalXMLByFilename(xmlPath, self.labelCategories)

            self.setWindowTitle(__appname__ + ' ' + filePath)

            self.canvas.setFocus(True)

            self.labelHist = []
            for shapeMap in self.itemsToShapes.values():
                for shape in shapeMap.values():
                    if shape.label not in self.labelHist:
                        self.labelHist.append(shape.label)

            return True
        return False

    def resizeEvent(self, event):
        if self.canvas and not self.image.isNull() \
                and self.zoomMode != self.MANUAL_ZOOM:
            self.adjustScale()
        super(MainWindow, self).resizeEvent(event)

    def paintCanvas(self):
        assert not self.image.isNull(), "cannot paint null image"
        self.canvas.setScale(0.01 * self.zoomWidget.value())

    def adjustScale(self, initial=False):
        if self.canvas is not None and self.canvas.pixmap is not None:
            value = self.scalers[self.FIT_WINDOW if initial else self.zoomMode]()
            self.zoomWidget.setValue(int(100 * value))

    def scaleFitWindow(self):
        """Figure out the size of the pixmap in order to fit the main widget."""
        e = 2.0  # So that no scrollbars are generated.
        w1 = self.centralWidget().width() - e
        h1 = self.centralWidget().height() - e
        a1 = w1 / h1
        # Calculate a new scale value based on the pixmap's aspect ratio.
        w2 = self.canvas.pixmap.width() - 0.0
        h2 = self.canvas.pixmap.height() - 0.0
        a2 = w2 / h2
        return w1 / w2 if a2 >= a1 else h1 / h2

    def scaleFitWidth(self):
        # The epsilon does not seem to work too well here.
        w = self.centralWidget().width() - 2.0
        return w / self.canvas.pixmap.width()

    def closeEvent(self, event):
        if not self.mayContinue():
            event.ignore()
        s = self.settings
        # If it loads images from dir, don't load it at the begining
        if self.dirname is None:
            s['filename'] = self.filePath if self.filePath else ''
        else:
            s['filename'] = ''

        s['window/size'] = self.size()
        s['window/position'] = self.pos()
        s['window/state'] = self.saveState()
        s['line/color'] = self.lineColor
        s['fill/color'] = self.fillColor
        s['recentFiles'] = self.recentFiles
        # s['advanced'] = not self._beginner
        if self.defaultSaveDir is not None and len(self.defaultSaveDir) > 1:
            s['savedir'] = ustr(self.defaultSaveDir)
        else:
            s['savedir'] = ""

        if self.lastOpenDir is not None and len(self.lastOpenDir) > 1:
            s['lastOpenDir'] = self.lastOpenDir
        else:
            s['lastOpenDir'] = ""

    ## User Dialogs ##

    def loadRecent(self, filename):
        if self.mayContinue():
            self.loadFile(filename)

    def scanAllImages(self, folderPath):
        extensions = ['.jpeg', '.jpg', '.png', '.bmp']
        images = []

        for root, dirs, files in os.walk(folderPath):
            for file in files:
                if file.lower().endswith(tuple(extensions)):
                    if not file.split('/')[-1].startswith('.'):
                        relatviePath = os.path.join(root, file)
                        path = ustr(os.path.abspath(relatviePath))
                        images.append(path)
        return natural_sort(images)

    def changeSavedir(self, _value=False):
        if self.defaultSaveDir is not None:
            path = ustr(self.defaultSaveDir)
        else:
            path = '.'

        dirpath = ustr(QFileDialog.getExistingDirectory(self,
                                                        '%s - Save to the directory' % __appname__, path,
                                                        QFileDialog.ShowDirsOnly
                                                        | QFileDialog.DontResolveSymlinks))

        if dirpath is not None and len(dirpath) > 1:
            self.defaultSaveDir = dirpath

        self.statusBar().showMessage('%s . Annotation will be saved to %s' %
                                     ('Change saved folder', self.defaultSaveDir))
        self.statusBar().show()

    def openAnnotation(self, _value=False):
        if self.filePath is None:
            self.statusBar().showMessage('Please select image first')
            self.statusBar().show()
            return

        path = os.path.dirname(ustr(self.filePath)) \
            if self.filePath else '.'
        if self.usingPascalVocFormat:
            filters = "Open Annotation XML file (%s)" % ' '.join(['*.xml'])
            filename = ustr(QFileDialog.getOpenFileName(self, '%s - Choose a xml file' % __appname__, path, filters))
            if filename:
                if isinstance(filename, (tuple, list)):
                    filename = filename[0]
            self.loadPascalXMLByFilename(filename, self.labelCategories)
            self.labelHist = [labelList.item(i).text() for labelList in self.labelLists.values() for i in
                              range(labelList.count())]

    def openDir(self, _value=False, dirpath=None):
        if not self.mayContinue():
            return

        path = os.path.dirname(self.filePath) \
            if self.filePath else '.'

        if self.lastOpenDir is not None and len(self.lastOpenDir) > 1:
            path = self.lastOpenDir

        if dirpath is None:
            dirpath = ustr(QFileDialog.getExistingDirectory(self,
                                                            '%s - Open Directory' % __appname__, path,
                                                            QFileDialog.ShowDirsOnly
                                                            | QFileDialog.DontResolveSymlinks))

        if dirpath is not None and len(dirpath) > 1:
            self.lastOpenDir = dirpath

        self.dirname = dirpath
        self.filePath = None
        self.fileListWidget.clear()
        self.mImgList = self.scanAllImages(dirpath)
        self.openNextImg()
        for imgPath in self.mImgList:
            if os.path.exists(os.path.splitext(imgPath)[0] + '.xml'):
                item = QListWidgetItem(imgPath + ' (labeled)')
            else:
                item = QListWidgetItem(imgPath)
            self.fileListWidget.addItem(item)

            # if len(self.mImgList) > 0:
            #     import ipdb; ipdb.set_trace()
            #     self.loadFile(self.mImgList[0])

    def verifyImg(self, _value=False):
        # Proceding next image without dialog if having any label
        if self.filePath is not None:
            try:
                self.labelFile.toggleVerify()
            except AttributeError:
                # If the labelling file does not exist yet, create if and
                # re-save it with the verified attribute.
                self.saveFile()
                self.labelFile.toggleVerify()

            self.canvas.verified = self.labelFile.verified
            self.paintCanvas()
            self.saveFile()

    def openPrevImg(self, _value=False):
        # Proceding prev image without dialog if having any label
        if self.autoSaving.isChecked() and self.defaultSaveDir is not None:
            if self.dirty is True:
                self.saveFile()

        if not self.mayContinue():
            return

        if len(self.mImgList) <= 0:
            return

        if self.filePath is None:
            return

        currIndex = self.mImgList.index(self.filePath)
        if currIndex - 1 >= 0:
            filename = self.mImgList[currIndex - 1]
            if filename:
                self.loadFile(filename)

    def openNextImg(self, _value=False):
        # Proceding next image without dialog if having any label
        if self.autoSaving.isChecked() and self.defaultSaveDir is not None:
            if self.dirty is True:
                self.saveFile()

        if not self.mayContinue():
            return

        if len(self.mImgList) <= 0:
            return

        filename = None
        if self.filePath is None:
            filename = self.mImgList[0]
        else:
            currIndex = self.mImgList.index(self.filePath)
            if currIndex + 1 < len(self.mImgList):
                filename = self.mImgList[currIndex + 1]

        if filename:
            self.loadFile(filename)

    def openFile(self, _value=False):
        if not self.mayContinue():
            return
        path = os.path.dirname(ustr(self.filePath)) if self.filePath else '.'
        formats = ['*.%s' % fmt.data().decode("ascii").lower() for fmt in QImageReader.supportedImageFormats()]
        formats = formats + [x.upper() for x in formats]
        filters = "Image & Label files (%s)" % ' '.join(formats + ['*%s' % LabelFile.suffix])
        filename = QFileDialog.getOpenFileName(self, '%s - Choose Image or Label file' % __appname__, path, filters)
        if filename:
            if isinstance(filename, (tuple, list)):
                filename = filename[0]
            self.loadFile(filename)

    def saveFile(self, _value=False):
        if self.defaultSaveDir is not None and len(ustr(self.defaultSaveDir)):
            if self.filePath:
                imgFileName = os.path.basename(self.filePath)
                savedFileName = os.path.splitext(imgFileName)[0] + XML_EXT
                savedPath = os.path.join(ustr(self.defaultSaveDir), savedFileName)
                self._saveFile(savedPath)
        else:
            imgFileDir = os.path.dirname(self.filePath)
            imgFileName = os.path.basename(self.filePath)
            savedFileName = os.path.splitext(imgFileName)[0] + XML_EXT
            savedPath = os.path.join(imgFileDir, savedFileName)
            self._saveFile(savedPath if self.labelFile
                           else self.saveFileDialog())

    def saveFileAs(self, _value=False):
        assert not self.image.isNull(), "cannot save empty image"
        self._saveFile(self.saveFileDialog())

    def saveFileDialog(self):
        # caption = '%s - Choose File' % __appname__
        # filters = 'File (*%s)' % LabelFile.suffix
        # openDialogPath = self.currentPath()
        # dlg = QFileDialog(self, caption, openDialogPath, filters)
        # dlg.setDefaultSuffix(LabelFile.suffix[1:])
        # dlg.setAcceptMode(QFileDialog.AcceptSave)
        filenameWithoutExtension = os.path.splitext(self.filePath)[0]
        return filenameWithoutExtension + '.xml'
        # dlg.selectFile(filenameWithoutExtension)
        # dlg.setOption(QFileDialog.DontUseNativeDialog, False)
        # dlg.setOption(QFileDialog.DontConfirmOverwrite, True)
        # if dlg.exec_():
        #    return dlg.selectedFiles()[0]
        # return ''

    def _saveFile(self, annotationFilePath):
        if annotationFilePath and self.saveLabels(annotationFilePath):
            self.setClean()
            self.statusBar().showMessage('Saved to  %s' % annotationFilePath)
            self.statusBar().show()
        index = self.mImgList.index(self.filePath)
        self.fileListWidget.item(index).setText(self.filePath + " (labeled)")

    def closeFile(self, _value=False):
        if not self.mayContinue():
            return
        self.resetState()
        self.setClean()
        self.toggleActions(False)
        self.canvas.setEnabled(False)
        self.actions.saveAs.setEnabled(False)

    def mayContinue(self):
        return not (self.dirty and not self.discardChangesDialog())

    def discardChangesDialog(self):
        yes, no = QMessageBox.Yes, QMessageBox.No
        msg = u'You have unsaved changes, proceed anyway?'
        return yes == QMessageBox.warning(self, u'Attention', msg, yes | no)

    def errorMessage(self, title, message):
        return QMessageBox.critical(self, title,
                                    '<p><b>%s</b></p>%s' % (title, message))

    def currentPath(self):
        return os.path.dirname(self.filePath) if self.filePath else '.'

    def chooseColor1(self):
        color = self.colorDialog.getColor(self.lineColor, u'Choose line color',
                                          default=DEFAULT_LINE_COLOR)
        if color:
            self.lineColor = color
            # Change the color for all shape lines:
            Shape.line_color = self.lineColor
            self.canvas.update()
            self.setDirty()

    def chooseColor2(self):
        color = self.colorDialog.getColor(self.fillColor, u'Choose fill color',
                                          default=DEFAULT_FILL_COLOR)
        if color:
            self.fillColor = color
            Shape.fill_color = self.fillColor
            self.canvas.update()
            self.setDirty()

    def deleteSelectedShape(self):
        # if self.canvas.mode in [self.canvas.CREATE, self.canvas.CREATE_BRUSH, self.canvas.CREATE_POLYGON]:
        #     self.canvas.mode = self.canvas.EDIT
        #     self.canvas.current = None
        #     self.actions.dele(False)
        # else:
        self.remLabel(self.canvas.deleteSelected())
        self.setDirty()
        self.actions.delete.setEnabled(False)
        if self.noShapes():
            for action in self.actions.onShapesPresent:
                action.setEnabled(False)

    def chshapeLineColor(self):
        color = self.colorDialog.getColor(self.lineColor, u'Choose line color',
                                          default=DEFAULT_LINE_COLOR)
        if color:
            self.canvas.selectedShape.line_color = color
            self.canvas.update()
            self.setDirty()

    def chshapeFillColor(self):
        color = self.colorDialog.getColor(self.fillColor, u'Choose fill color',
                                          default=DEFAULT_FILL_COLOR)
        if color:
            self.canvas.selectedShape.fill_color = color
            self.canvas.update()
            self.setDirty()

    def copyShape(self):
        self.canvas.endMove(copy=True)
        self.addLabel(self.canvas.selectedShape)
        self.setDirty()

    def moveShape(self):
        self.canvas.endMove(copy=False)
        self.setDirty()

    def loadPredefinedClasses(self, predefClassesFile):
        if os.path.exists(predefClassesFile) is True:
            with open(predefClassesFile, 'rb') as f:
                for line in f:
                    line = line.strip()
                    try:
                        line = line.decode('utf-8')
                    except UnicodeDecodeError:
                        try:
                            line = line.decode('gb2312')
                        except UnicodeDecodeError:
                            line = line.decode('gbk')
                    if len(line) == 0:
                        continue
                    if self.labelHist is None:
                        self.labelHist = [line]
                    else:
                        self.labelHist.append(line)

    def loadAttributes(self, attributesFile):
        if os.path.exists(attributesFile) is True:
            with open(attributesFile, 'rb') as f:
                for line in f:
                    line = line.strip()
                    try:
                        line = line.decode('utf-8')
                    except UnicodeDecodeError:
                        line = line.decode('gb2312')
                    if len(line) == 0:
                        continue
                    if self.attributes is None:
                        self.attributes = [line]
                    else:
                        self.attributes.append(line)

    def loadPascalXMLByFilename(self, xmlPath, labelCategories):
        if self.filePath is None:
            return
        if os.path.isfile(xmlPath) is False:
            return

        tVocParseReader = PascalVocReader(xmlPath, labelCategories)
        shapes = tVocParseReader.getShapes()
        self.loadLabels(shapes)
        self.canvas.verified = tVocParseReader.verified


class Settings(object):
    """Convenience dict-like wrapper around QSettings."""

    def __init__(self, types=None):
        self.data = QSettings()
        self.types = defaultdict(lambda: QVariant, types if types else {})

    def __setitem__(self, key, value):
        t = self.types[key]
        self.data.setValue(key,
                           t(value) if not isinstance(value, t) else value)

    def __getitem__(self, key):
        return self._cast(key, self.data.value(key))

    def get(self, key, default=None):
        return self._cast(key, self.data.value(key, default))

    def _cast(self, key, value):
        # XXX: Very nasty way of converting types to QVariant methods :P
        t = self.types.get(key)
        if t is not None and t != QVariant:
            if t is str:
                return ustr(value)
            else:
                try:
                    method = getattr(QVariant, re.sub(
                        '^Q', 'to', t.__name__, count=1))
                    return method(value)
                except AttributeError as e:
                    # print(e)
                    return value
        return value


def inverted(color):
    return QColor(*[255 - v for v in color.getRgb()])


def read(filename, default=None):
    try:
        with open(filename, 'rb') as f:
            return f.read()
    except:
        return default


def get_main_app(argv=[]):
    """
    Standard boilerplate Qt application code.
    Do everything but app.exec_() -- so that we can test the application in one thread
    """
    app = QApplication(argv)
    app.setApplicationName(__appname__)
    app.setWindowIcon(newIcon("app"))
    # Tzutalin 201705+: Accept extra agruments to change predefined class file
    # Usage : labelImg.py image predefClassFile
    win = MainWindow(
        os.path.join('predefined_classes.txt'),
        os.path.join('predefined_attributes.txt'),
        labelCategories=(
            ("Objects", "object"),
            ("Suction Regions", "suction_region")
        )
    )
    # win.show()
    #win.queueEvent(partial(win.openDir, dirpath="/nfs1/data/general_object_suction_picking/mrcnn_finetune_05102018/"))
    #win.queueEvent(partial(win.setFitWindow))
    return app, win

def show_main():
    mainWin.show()
    subWin.hide()
    projectWin.hide()

def show_project():
    projectWin.show()
    mainWin.hide()
    subWin.hide()

def main(argv=[]):
    '''construct main app and run it'''
    app, _win = get_main_app(argv)
    return app.exec_()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    mainWin = MainWindow(
        os.path.join('predefined_classes.txt'),
        os.path.join('predefined_attributes.txt'),
        labelCategories=(
            ("Objects", "object"),
            ("Suction Regions", "suction_region")
        )
    )
    subWin = LoginWindow()
    projectWin = ProjectListWindow()
    subWin.show()
    subWin.show_project_win_signal.connect(show_project)
    projectWin.show_main_win_signal.connect(show_main)
    sys.exit(main(sys.argv))
