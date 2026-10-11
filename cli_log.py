"""CLI text views that follow output only while the reader is near the end."""
from contextlib import contextmanager
from weakref import WeakSet

from PySide6 import QtGui as G, QtWidgets as W
from shiboken6 import isValid


class CliLog(W.QPlainTextEdit):
    _views = WeakSet()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self._views.add(self)

    @contextmanager
    def output_update(self):
        # Export panels can share one document while reading different places.
        snapshots = []
        for view in list(self._views):
            if not isValid(view) or view.document() != self.document():
                continue
            bar = view.verticalScrollBar()
            anchor = G.QTextCursor(view.firstVisibleBlock())
            snapshots.append((view, bar.maximum()-bar.value() <= 3,
                              bar.value(), anchor, view.cursorRect(anchor).top(),
                              view.horizontalScrollBar().value()))
        try:
            yield
        finally:
            for view, follow, position, anchor, top, horizontal in snapshots:
                if not isValid(view):
                    continue
                bar = view.verticalScrollBar()
                if follow:
                    bar.setValue(bar.maximum())
                else:
                    bar.setValue(position)
                    # A maximum-block limit can trim old lines. Keep the same
                    # surviving text in view rather than the same line number.
                    line_height = max(1, view.fontMetrics().lineSpacing())
                    displacement = view.cursorRect(anchor).top()-top
                    bar.setValue(bar.value()+round(displacement/line_height))
                view.horizontalScrollBar().setValue(horizontal)

    def appendPlainText(self, text):
        with self.output_update():
            # Edit the shared document directly so every Export CLI view gets
            # its layout/scroll range updated, not only the writing widget.
            cursor = G.QTextCursor(self.document())
            cursor.movePosition(G.QTextCursor.End)
            if not self.document().isEmpty():
                cursor.insertBlock()
            cursor.insertText(text)
