import utils
from n5_converter import OnTheFlyOverviewN5Converter
import os


class TargetingPlugin:

    def __init__(self, acq):
        self._acq = acq
        self._selected_ov = None
        self._convert_to_n5 = False
        self._n5_converter = None

    @property
    def selected_ov(self):
        return self._selected_ov

    @property
    def convert_to_n5(self):
        return self._convert_to_n5

    def update_targeting_plugin_settings(self, selected_ov, convert_to_n5):
        self._selected_ov = selected_ov
        self._convert_to_n5 = convert_to_n5

        # update n5 converter settings
        if self._convert_to_n5:
            if self._n5_converter is None:
                self._n5_converter = OnTheFlyOverviewN5Converter(self._acq, self._acq.ovm,
                                                                 self._selected_ov)
            elif self._acq.base_dir != self._n5_converter.base_dir or \
                    self._acq.stack_name != self._n5_converter.stack_name or \
                    self._selected_ov != self._n5_converter.ov_index:
                self._n5_converter = OnTheFlyOverviewN5Converter(self._acq, self._acq.ovm,
                                                                 self._selected_ov)
            else:
                self._n5_converter.update_ov_settings()

    def write_ov_to_n5(self):
        if self._n5_converter is not None and self._convert_to_n5:
            relative_ov_path = utils.ov_relative_save_path(self._acq.stack_name, self._n5_converter.ov_index,
                                                           self._acq.slice_counter)
            path_to_tiff_slice = os.path.join(self._acq.base_dir, relative_ov_path)
            self._n5_converter.write_slice(path_to_tiff_slice)


