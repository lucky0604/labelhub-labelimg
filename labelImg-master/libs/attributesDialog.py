try:
    from PyQt5.QtGui import *
    from PyQt5.QtCore import *
    from PyQt5.QtWidgets import *
except ImportError:
    from PyQt4.QtGui import *
    from PyQt4.QtCore import *

from libs.lib import newIcon, labelValidator

BB = QDialogButtonBox


class AttributesDialog(QDialog):
    def __init__(self, text="Select attributes", parent=None, attributes=None, labelLists=None):
        super(AttributesDialog, self).__init__(parent)
        self.parent = parent
        # self.edit = QLineEdit()
        # self.edit.setText(text)
        # self.edit.setValidator(labelValidator())
        # self.edit.editingFinished.connect(self.postProcess)
        layout = QVBoxLayout()
        # layout.addWidget(self.edit)
        self.buttonBox = bb = BB(BB.Ok | BB.Cancel, Qt.Horizontal, self)
        bb.button(BB.Ok).setIcon(newIcon('done'))
        bb.button(BB.Cancel).setIcon(newIcon('undo'))
        bb.accepted.connect(self.validate)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

        self.labelLists = labelLists
        self.attributes = attributes
        self.listWidget = QListWidget(self)

        for idx, attr in enumerate(attributes):
            item = QListWidgetItem(attr)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Unchecked)
            self.listWidget.addItem(item)

        layout.addWidget(self.listWidget)

        self.setLayout(layout)

    def validate(self):
        self.accept()

    def popUp(self, currentAttributes=(), move=True):
        items = [self.listWidget.item(idx) for idx in range(self.listWidget.count())]
        for item in items:
            attr = item.text()
            if attr in currentAttributes:
                item.setCheckState(Qt.Checked)
            else:
                item.setCheckState(Qt.Unchecked)
        if move:
            self.move(QCursor.pos())
        if self.exec_():
            return tuple([item.text() for item in items if item.checkState()])
        else:
            return None
        # return self.edit.text() if self.exec_() else None
