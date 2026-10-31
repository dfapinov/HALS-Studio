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


def test_markdown_navigation_and_image_width(monkeypatch):
    app = W.QApplication.instance() or W.QApplication([])
    viewer = DocumentationViewer()
    viewer.show()
    app.processEvents()
    assert viewer.browser.font().styleStrategy() & G.QFont.PreferAntialias
    assert viewer.files.font().styleStrategy() & G.QFont.PreferAntialias
    assert viewer.browser.document().defaultFont().styleStrategy() & G.QFont.PreferAntialias
    groups = [viewer.files.topLevelItem(i) for i in range(viewer.files.topLevelItemCount())]
    assert [group.text(0) for group in groups] == [
        "Process", "Analysis", "Export", "PDFs", "Miscellaneous",
    ]
    assert groups[1].childCount() == 1
    assert groups[1].child(0).text(0) == "No files yet"
    assert groups[1].child(0).data(0, C.Qt.UserRole) is None
    assert [groups[0].child(i).data(0, C.Qt.UserRole) for i in range(groups[0].childCount())] == [
        "stage1_fdw_gui_help.md", "stage2_origin_help.md", "stage3_help.md",
        "stage4_she_solver_help.md",
    ]
    assert "stage5_export_help.md" in [groups[2].child(i).data(0, C.Qt.UserRole)
                                        for i in range(groups[2].childCount())]
    assert [groups[3].child(i).data(0, C.Qt.UserRole) for i in range(groups[3].childCount())] == [
        "HALS_IR_Validation.pdf", "HALS_Stage5_Geometric_Phase_Validation.pdf",
    ]
    assert "grid_gen_help.md" in [groups[4].child(i).data(0, C.Qt.UserRole)
                                  for i in range(groups[4].childCount())]
    assert all(group.child(i).data(0, C.Qt.UserRole) != "architecture.md"
               for group in groups for i in range(group.childCount()))
    assert viewer.open_document("stage2_origin_help.md", "upper-frequency")
    app.processEvents()
    assert viewer.browser.verticalScrollBar().value() > 0
    assert viewer.browser.document().size().width() <= viewer.browser.viewport().width() + 1
    viewer.resize(850, 650)
    app.processEvents()
    assert viewer.browser.document().size().width() <= viewer.browser.viewport().width() + 1
    viewer._follow_link(C.QUrl("stage3_help.md#upper-test-range"))
    assert "Stage 3 Help" in viewer.browser.toPlainText()
    assert not viewer.open_document("../README.md")

    opened = []
    monkeypatch.setattr(G.QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    assert viewer.open_document("HALS_IR_Validation.pdf")
    assert opened[0].isLocalFile()
    assert opened[0].toLocalFile().endswith("HALS_IR_Validation.pdf")
    viewer.close()
