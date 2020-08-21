try:
    from PyQt5.QtGui import *
    from PyQt5.QtCore import *
    from PyQt5.QtWidgets import *
except ImportError:
    from PyQt4.QtGui import *
    from PyQt4.QtCore import *

from libs.lib import newIcon, labelValidator

BB = QDialogButtonBox


class LabelDialog(QDialog):
    def __init__(self, text="Enter label", parent=None, listItem=None, labelLists=None, predefinedClasses=None):
        super(LabelDialog, self).__init__(parent)
        self.parent = parent
        self.edit = QLineEdit()
        self.edit.setText(text)
        self.edit.setValidator(labelValidator())
        self.edit.editingFinished.connect(self.postProcess)
        layout = QVBoxLayout()
        layout.addWidget(self.edit)
        self.buttonBox = bb = BB(BB.Ok | BB.Cancel, Qt.Horizontal, self)
        bb.button(BB.Ok).setIcon(newIcon('done'))
        bb.button(BB.Cancel).setIcon(newIcon('undo'))
        bb.accepted.connect(self.validate)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

        self.labelLists = labelLists
        self.predefinedClasses = predefinedClasses
        if labelLists is not None:
            self.newListWidget = QListWidget(self)
            layout.addWidget(self.newListWidget)
            self.newListWidget.itemDoubleClicked.connect(self.newListItemClick)

        if listItem is not None and len(listItem) > 0:
            self.listWidget = QListWidget(self)
            for item in listItem:
                self.listWidget.addItem(item)
            self.listWidget.itemDoubleClicked.connect(self.listItemClick)
            layout.addWidget(self.listWidget)

        self.setLayout(layout)

    def validate(self):
        try:
            if self.edit.text().trimmed():
                self.accept()
        except AttributeError:
            # PyQt5: AttributeError: 'str' object has no attribute 'trimmed'
            if self.edit.text().strip():
                self.accept()

    def postProcess(self):
        try:
            self.edit.setText(self.edit.text().trimmed())
        except AttributeError:
            # PyQt5: AttributeError: 'str' object has no attribute 'trimmed'
            self.edit.setText(self.edit.text())

    def popUp(self, text='', move=True):
        labelList = self.parent.currentLabelList
        current_labels = [labelList.item(idx).text() for idx in range(labelList.count())]

        self.newListWidget.clear()
        def scan_for_max(prefixes):
            maxids = [0] * len(prefixes)
            for x in current_labels:
                for idx, p in enumerate(prefixes):
                    if x.startswith(p):
                        try:
                            maxids[idx] = max(maxids[idx], int(x[len(p):]))
                        except ValueError:
                            pass
            for idx, p in enumerate(prefixes):
                self.newListWidget.addItem(QListWidgetItem(f'{p}{maxids[idx]+1}'))

        if self.parent.currentCategoryId == 'object':
            scan_for_max(['box', 'o', 'pad'])
        elif self.parent.currentCategoryId == 'suction_region':
            scan_for_max(['PorousRegion', 'UnevenRegion'])
        if self.predefinedClasses is not None:
            for cls in self.predefinedClasses:
                self.newListWidget.addItem(QListWidgetItem(cls))

        self.edit.setText(text)
        self.edit.setSelection(0, len(text))
        self.edit.setFocus(Qt.PopupFocusReason)
        if move:
            self.move(QCursor.pos())
        return self.edit.text() if self.exec_() else None

    def newListItemClick(self, tQListWidgetItem):
        try:
            text = tQListWidgetItem.text().trimmed()
        except AttributeError:
            # PyQt5: AttributeError: 'str' object has no attribute 'trimmed'
            text = tQListWidgetItem.text().strip()
        self.edit.setText(text)
        self.validate()

    def listItemClick(self, tQListWidgetItem):
        try:
            text = tQListWidgetItem.text().trimmed()
        except AttributeError:
            # PyQt5: AttributeError: 'str' object has no attribute 'trimmed'
            text = tQListWidgetItem.text().strip()
        self.edit.setText(text)
        self.validate()
