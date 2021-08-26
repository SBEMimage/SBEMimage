
class TargetingPlugin:

    def __init__(self, main_controls):
        self._ui = main_controls
        self._ui.checkBox_n5Conversion.setChecked(False)
        self.update_ov()

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