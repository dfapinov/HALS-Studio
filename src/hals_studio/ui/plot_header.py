"""Shared single-row header for Analysis and Export response panes."""
from PySide6 import QtCore as C, QtWidgets as W


def plot_settings_button(callback):
    button = W.QToolButton(); button.setText('\u2699'); button.setFixedHeight(32)
    button.setToolTip('Plot settings'); button.setAccessibleName('Plot settings')
    button.clicked.connect(callback)
    return button


class PlotHeader(W.QWidget):
    def __init__(self, choose, reset, settings):
        super().__init__()
        outer = W.QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(2)
        row = W.QHBoxLayout(); self.controls = row; row.setSpacing(4); outer.addLayout(row)
        self.expanded_readout = False
        self.title = W.QPushButton()
        from hals_studio.ui.viewer_theme import stylesheet_colours
        title_style = 'text-align:left; color:#54d9e8; border-radius:4px; padding:8px;'
        self.title.setProperty('theme_original_style', title_style)
        self.title.setStyleSheet(stylesheet_colours(title_style))
        self.title.setSizePolicy(W.QSizePolicy.Fixed, W.QSizePolicy.Fixed)
        self.title.setFixedHeight(32); self.title.clicked.connect(choose)
        row.addWidget(self.title)
        row.addStretch(1)
        self.readout = W.QLabel(); self.readout.setStyleSheet('font-size:11px; padding:0 5px;')
        self.readout.setSizePolicy(W.QSizePolicy.Minimum, W.QSizePolicy.Preferred)
        self.readout.setAlignment(C.Qt.AlignRight | C.Qt.AlignVCenter)
        row.addWidget(self.readout)
        self.reset = W.QPushButton('Reset axes'); self.reset.setFixedHeight(32)
        self.reset.clicked.connect(reset); row.addWidget(self.reset)
        self.gear = plot_settings_button(settings); row.addWidget(self.gear)

    def set_readout_expanded(self, expanded):
        """Give long directivity readouts their own wrapping row."""
        if expanded == self.expanded_readout: return
        self.expanded_readout = expanded
        if expanded:
            self.controls.removeWidget(self.readout)
            self.readout.setMinimumWidth(0); self.readout.setMaximumWidth(16777215)
            self.readout.setSizePolicy(W.QSizePolicy.Ignored, W.QSizePolicy.Preferred)
            self.readout.setWordWrap(True)
            self.readout.setAlignment(C.Qt.AlignLeft | C.Qt.AlignVCenter)
            self.layout().addWidget(self.readout)
        else:
            self.layout().removeWidget(self.readout)
            self.readout.setWordWrap(False); self.readout.setFixedWidth(220)
            self.readout.setSizePolicy(W.QSizePolicy.Fixed, W.QSizePolicy.Preferred)
            self.readout.setAlignment(C.Qt.AlignRight | C.Qt.AlignVCenter)
            self.controls.insertWidget(self.controls.indexOf(self.reset), self.readout)
