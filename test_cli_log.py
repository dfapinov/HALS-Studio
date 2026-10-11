import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import bootstrap
import pytest
from PySide6 import QtGui as G, QtWidgets as W
from cli_log import CliLog


@pytest.fixture
def logs():
    app = W.QApplication.instance() or W.QApplication([])
    views = [CliLog(), CliLog()]
    views[1].setDocument(views[0].document())
    for view in views:
        view.resize(450, 200);view.show()
    views[0].appendPlainText('\n'.join(f'Line {i}' for i in range(150)))
    app.processEvents()
    yield app, views
    for view in views:view.close();view.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('distance', [0, 3, 4, 40])
def test_follow_only_within_three_lines(logs, distance):
    app, (log, _) = logs
    bar = log.verticalScrollBar();bar.setValue(bar.maximum()-distance)
    before = bar.value()
    log.appendPlainText('\n'.join(['New output']*20));app.processEvents()
    assert bar.value() == (bar.maximum() if distance <= 3 else before)


def test_shared_views_follow_independently_and_resume(logs):
    app, (writer, reader) = logs
    bar = reader.verticalScrollBar();bar.setValue(30)
    writer.appendPlainText('New output');app.processEvents()
    assert bar.value() == 30
    assert writer.verticalScrollBar().value() == writer.verticalScrollBar().maximum()
    bar.setValue(bar.maximum()-3)
    writer.appendPlainText('Follow again');app.processEvents()
    assert bar.value() == bar.maximum()


def test_trimming_keeps_surviving_text_in_view(logs):
    app, (log, reader) = logs
    log.setMaximumBlockCount(150)
    for view in (log, reader):view.verticalScrollBar().setValue(40)
    before = [view.firstVisibleBlock().text() for view in (log, reader)]
    log.appendPlainText('\n'.join(['More output']*10));app.processEvents()
    assert [view.firstVisibleBlock().text() for view in (log, reader)] == before


def test_process_progress_updates_preserve_scroll_and_selection(logs):
    from types import SimpleNamespace
    from process_workspace import ProcessWorkspace
    app, (log, _) = logs
    cursor = G.QTextCursor(log.document().findBlockByNumber(30))
    cursor.movePosition(G.QTextCursor.EndOfBlock, G.QTextCursor.KeepAnchor)
    log.setTextCursor(cursor)
    log.verticalScrollBar().setValue(25)
    selected = log.textCursor().selectedText()
    owner = SimpleNamespace(log=log, _cli_line='')
    ProcessWorkspace.append_output(owner, '\rProgress 10%\rProgress 20%\nDone\n')
    app.processEvents()
    assert log.verticalScrollBar().value() == 25
    assert log.textCursor().selectedText() == selected
    assert log.toPlainText().endswith('Progress 20%\nDone\n')
    log.verticalScrollBar().setValue(log.verticalScrollBar().maximum()-2)
    ProcessWorkspace.append_output(owner, 'Following\n')
    app.processEvents()
    assert log.verticalScrollBar().value() == log.verticalScrollBar().maximum()
