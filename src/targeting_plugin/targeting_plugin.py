from src import utils
from src.targeting_plugin.n5_converter import OnTheFlyOverviewN5Converter
import os

class TargetingPlugin:
    N5_CONVERSION_MSG = "CONVERT OV TO N5"

    def __init__(self, main_controls):
        self._ui = main_controls
        self._acq = main_controls.acq
        self._ui.checkBox_n5Conversion.setChecked(False)
        self.update_ov()
        self._n5_converter = OnTheFlyOverviewN5Converter(self._acq, main_controls.ovm, self.selected_ov())

    def update_ov(self):
        ov_combobox = self._ui.comboBox_ovId
        ovm = self._ui.ovm
        current_index = ov_combobox.currentIndex()
        if current_index == -1:
            current_index = 0

        ov_combobox.blockSignals(True)
        ov_combobox.clear()
        ov_list_str = [str(r) for r in range(0, ovm.number_ov)]
        ov_combobox.addItems(ov_list_str)
        if current_index > len(ov_list_str) - 1:
            current_index = 0
        ov_combobox.setCurrentIndex(current_index)
        ov_combobox.blockSignals(False)

    def selected_ov(self):
        return self._ui.comboBox_ovId.currentIndex()

    def is_convert_to_n5_active(self):
        return self._ui.checkBox_n5Conversion.isChecked()

    def restrict_gui(self, b):
        self._ui.comboBox_ovId.setEnabled(b)
        self._ui.checkBox_n5Conversion.setEnabled(b)

    def update_n5_converter_settings(self):
        if self._acq.base_dir != self._n5_converter.base_dir or self._acq.stack_name != self._n5_converter.stack_name \
                or self.selected_ov() != self._n5_converter.ov_index:
            self._n5_converter = OnTheFlyOverviewN5Converter(self._acq.base_dir, self._acq.stack_name,
                                                             self.selected_ov())

    def handle_message(self, msg):
        ov_index = int(msg[len(self.N5_CONVERSION_MSG):])
        if ov_index == self._n5_converter.ov_index and self.is_convert_to_n5_active():
            self._write_ov_to_n5()

    def _write_ov_to_n5(self):
        relative_ov_path = utils.ov_relative_save_path(self._acq.stack_name, self._n5_converter.ov_index,
                                                       self._acq.slice_counter)
        path_to_tiff_slice = os.path.join(self._acq.base_dir, relative_ov_path)
        self._n5_converter.write_slice(path_to_tiff_slice)


