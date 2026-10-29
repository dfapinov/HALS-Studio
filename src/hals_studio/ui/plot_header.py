"""Shared single-row header for Analysis and Export response panes."""
from PySide6 import QtCore as C, QtWidgets as W


class PlotHeader(W.QWidget):
    def __init__(self, choose, reset, settings):
        super().__init__()
        row = W.QHBoxLayout(self); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(4)
        self.title = W.QPushButton()
        self.title.setStyleSheet('text-align:left; color:#54d9e8; border-radius:4px; padding:8px;')
        self.title.setSizePolicy(W.QSizePolicy.Ignored, W.QSizePolicy.Fixed)
        self.title.setFixedHeight(32); self.title.clicked.connect(choose)
        row.addWidget(self.title, 1)
        self.readout = W.QLabel(); self.readout.setStyleSheet('font-size:11px; padding:0 5px;')
        self.readout.setFixedWidth(220); self.readout.setAlignment(C.Qt.AlignRight | C.Qt.AlignVCenter)
        row.addWidget(self.readout)
        self.reset = W.QPushButton('Reset axes'); self.reset.setFixedHeight(32)
        self.reset.clicked.connect(reset); row.addWidget(self.reset)
        self.gear = W.QToolButton(); self.gear.setText('\u2699'); self.gear.setFixedHeight(32)
        self.gear.setToolTip('Plot settings'); self.gear.setAccessibleName('Plot settings')
        self.gear.clicked.connect(settings); row.addWidget(self.gear)
