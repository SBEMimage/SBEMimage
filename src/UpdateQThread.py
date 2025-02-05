from time import sleep

from qtpy.QtCore import QThread, Signal


class UpdateQThread(QThread):
    """Helper for updating QDialogs using QThread"""
    update = Signal()

    def __init__(self, secs):
        self.active = True
        self.secs = secs
        QThread.__init__(self)

    def run(self):
        while self.active:
            self.update.emit()
            sleep(self.secs)

    def stop(self):
        self.active = False
