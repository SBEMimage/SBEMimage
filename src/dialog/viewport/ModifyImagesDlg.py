from qtpy.QtCore import Qt
from qtpy.QtWidgets import QDialog, QListWidgetItem, QMessageBox
from qtpy.uic import loadUi

from dialog.viewport.ImportImageDlg import ImportImageDlg
from dialog.viewport.ModifyImageDlg import ModifyImageDlg
import utils


class ModifyImagesDlg(QDialog):
    """Modify imported images from the viewport."""

    def __init__(self, imported_images, grid_manager, stage, viewport_trigger):
        self.imported = imported_images
        self.gm = grid_manager
        self.stage = stage
        self.viewport_trigger = viewport_trigger
        super().__init__()
        loadUi('gui/modify_images_dlg.ui', self)
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowIcon(utils.get_window_icon())
        self.setFixedSize(self.size())
        self.pushButton_import.clicked.connect(self.import_image)
        self.pushButton_delete.clicked.connect(self.delete_imported)
        self.pushButton_modify.clicked.connect(self.modify_imported)
        self.pushButton_move_up.clicked.connect(self.move_up)
        self.pushButton_move_down.clicked.connect(self.move_down)
        self.populate_image_list()

    def populate_image_list(self):
        # Populate the list widget with existing imported images:
        #self.listWidget_imagelist.itemChanged.disconnect()
        self.listWidget_imagelist.clear()
        for index, imported_image in enumerate(self.imported):
            item = QListWidgetItem(str(index) + ' - ' + imported_image.description)
            if imported_image.enabled:
                state = Qt.CheckState.Checked
            else:
                state = Qt.CheckState.Unchecked
            item.setCheckState(state)
            self.listWidget_imagelist.addItem(item)
        self.listWidget_imagelist.itemChanged.connect(self.item_changed)

    def item_changed(self, item):
        index = self.listWidget_imagelist.row(item)
        checked = (item.checkState() == Qt.CheckState.Checked)
        self.imported[index].enabled = checked
        self.viewport_trigger.transmit('DRAW VP')

    def import_image(self):
        dialog = ImportImageDlg(self.imported, self.viewport_trigger, self.stage)
        if dialog.exec():
            self.populate_image_list()
            self.viewport_trigger.transmit('DRAW VP')

    def delete_imported(self):
        index = self.listWidget_imagelist.currentRow()
        if index >= 0:
            imported = self.imported[index]
            response = QMessageBox.question(
                self, 'Delete imported image',
                f'Are you sure you want to delete imported image?\n{imported.description}',
                QMessageBox.Ok | QMessageBox.Cancel)
            if response == QMessageBox.Ok:
                if self.imported[index].is_array:
                    self.viewport_trigger.transmit('ARRAY REMOVE IMAGE')
                self.imported.delete_image(index)
                self.populate_image_list()
                self.viewport_trigger.transmit('DRAW VP')

    def modify_imported(self):
        index = self.listWidget_imagelist.currentRow()
        if index >= 0:
            selected_image = self.imported[index]
            dialog = ModifyImageDlg(selected_image, self.gm,
                                    self.viewport_trigger)
            dialog.exec()

    def move_up(self):
        index = self.listWidget_imagelist.currentRow()
        if index > 0:
            self.imported[index], self.imported[index - 1] = self.imported[index - 1], self.imported[index]
            self.populate_image_list()
            self.viewport_trigger.transmit('DRAW VP')

    def move_down(self):
        index = self.listWidget_imagelist.currentRow()
        if 0 <= index < len(self.imported) - 1:
            self.imported[index], self.imported[index + 1] = self.imported[index + 1], self.imported[index]
            self.populate_image_list()
            self.viewport_trigger.transmit('DRAW VP')
