"""Documentation navigation and PDF handoff."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore as C, QtGui as G, QtWidgets as W

from hals_studio.ui.documentation_viewer import DocumentationViewer, help_group


def test_footer_tag_controls_markdown_group(tmp_path):
    path = tmp_path / "new_topic.md"
    path.write_text("# New topic\n\n<!-- help-group: analysis -->\n", encoding="utf-8")
    assert help_group(path) == "Analysis"
    path.write_text("# New topic\n", encoding="utf-8")
    assert help_group(path) == "Miscellaneous"
    path.write_text("# New topic\n\n<!-- help-group: hidden -->\n", encoding="utf-8")
    assert help_group(path) == "Hidden"
    assert help_group(tmp_path / "reference.pdf") == "PDFs"


def test_markdown_navigation_images_and_pdf_handoff(tmp_path, monkeypatch):
    app = W.QApplication.instance() or W.QApplication([])
    directory = tmp_path / 'docs'
    directory.mkdir()
    (tmp_path / 'outside.md').write_text('# Outside the help directory', encoding='utf-8')
    image = G.QImage(2400, 200, G.QImage.Format_RGB32)
    image.fill(G.QColor('blue'))
    assert image.save(str(directory / 'wide.png'))
    (directory / 'guide.md').write_text(
        '# Guide\n\n![Wide image](wide.png)\n\n' +
        ('A paragraph before the target heading.\n\n' * 100) +
        '## Details\n\n[Next topic](next.md#target)\n\n<!-- help-group: process -->\n',
        encoding='utf-8')
    (directory / 'next.md').write_text(
        '# Next topic\n\n## Target\n\nLinked content.\n\n<!-- help-group: analysis -->\n',
        encoding='utf-8')
    (directory / 'hidden.md').write_text('# Hidden\n\n<!-- help-group: hidden -->\n',
                                      encoding='utf-8')
    # The system app owns PDF rendering; this test checks only the handoff.
    (directory / 'reference.pdf').touch()
    viewer = DocumentationViewer(directory=directory)
    try:
        viewer.show()
        app.processEvents()
        def listed_files():
            return {group.child(i).data(0, C.Qt.UserRole): group.text(0)
                    for group in (viewer.files.topLevelItem(j)
                                  for j in range(viewer.files.topLevelItemCount()))
                    for i in range(group.childCount())
                    if group.child(i).data(0, C.Qt.UserRole)}
        assert listed_files() == {'guide.md': 'Process', 'next.md': 'Analysis',
                                  'reference.pdf': 'PDFs'}
        assert viewer.open_document('guide.md', 'details')
        app.processEvents()
        assert viewer.browser.verticalScrollBar().value() > 0
        for width in (850, 650):
            viewer.resize(width, 650)
            app.processEvents()
            assert viewer.browser.document().size().width() <= viewer.browser.viewport().width() + 1
        viewer.browser.anchorClicked.emit(C.QUrl('next.md#target'))
        assert 'Linked content.' in viewer.browser.toPlainText()
        assert not viewer.open_document('../outside.md')
        assert not viewer.open_document('missing.md')
        opened = []
        monkeypatch.setattr(G.QDesktopServices, 'openUrl', lambda url: opened.append(url) or True)
        assert viewer.open_document('reference.pdf')
        assert opened == [C.QUrl.fromLocalFile(str(directory / 'reference.pdf'))]
        # Adding a guide must populate navigation without changing this test.
        (directory / 'extra.md').write_text('# Extra topic', encoding='utf-8')
        viewer.refresh_files()
        assert listed_files()['extra.md'] == 'Miscellaneous'
    finally:
        viewer.close()
