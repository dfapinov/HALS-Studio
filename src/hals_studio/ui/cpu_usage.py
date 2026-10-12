"""Nonblocking system CPU utilisation for the persistent status bar."""
import os
from PySide6 import QtCore as C, QtWidgets as W


class CpuSampler:
    def __init__(self):
        self.previous = None
        self.api = None
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            self.filetime = wintypes.FILETIME
            self.api = ctypes.WinDLL('kernel32', use_last_error=True).GetSystemTimes
            self.api.argtypes = [ctypes.POINTER(wintypes.FILETIME)]*3
            self.api.restype = wintypes.BOOL

    def counters(self):
        if self.api is not None:
            import ctypes
            idle, kernel, user = self.filetime(), self.filetime(), self.filetime()
            if not self.api(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                raise OSError('CPU counters unavailable')
            value = lambda item: (item.dwHighDateTime << 32) | item.dwLowDateTime
            return value(idle), value(kernel)+value(user)
        with open('/proc/stat') as source:
            values = [int(n) for n in source.readline().split()[1:]]
        return sum(values[3:5]), sum(values[:8])

    def sample(self):
        current = self.counters()
        previous, self.previous = self.previous, current
        if previous is None or current[1] <= previous[1]: return None
        return max(0., min(100., 100*(1-(current[0]-previous[0])/(current[1]-previous[1]))))


class CpuMeter(W.QLabel):
    def __init__(self, parent):
        super().__init__('CPU —', parent)
        self.setMinimumWidth(75)
        self.setToolTip('System CPU utilisation across all logical processors; updated every second.')
        self.sampler = CpuSampler()
        self.timer = C.QTimer(self);self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_usage)
        self.update_usage();self.timer.start()

    def update_usage(self):
        try:
            value = self.sampler.sample()
            if value is not None:self.setText(f'CPU {value:.0f}%')
        except OSError:
            self.setText('CPU n/a')


def add_cpu_meter(window):
    window.cpu_meter = CpuMeter(window)
    window.statusBar().addPermanentWidget(window.cpu_meter)
