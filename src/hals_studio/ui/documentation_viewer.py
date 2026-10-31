"""Small local documentation browser for bundled Markdown and PDFs."""

from pathlib import Path
import re

from PySide6 import QtCore as C, QtGui as G, QtWidgets as W

from hals_studio import bootstrap


DOCUMENTATION = bootstrap.HERE / "documentation"
GROUPS = ("Process", "Analysis", "Export", "PDFs", "Miscellaneous")
GROUP_TAG = re.compile(r"<!--\s*help-group:\s*(process|analysis|export|miscellaneous|hidden)\s*-->", re.I)


def help_group(path):
    """Use the Markdown footer; place every PDF in its own group."""
    if path.suffix.lower() == ".pdf":
        return "PDFs"
    lines = path.read_text(encoding="utf-8").rstrip().splitlines()
    match = GROUP_TAG.fullmatch(lines[-1].strip()) if lines else None
    return match.group(1).casefold().capitalize() if match else "Miscellaneous"


class MarkdownBrowser(W.QTextBrowser):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self._markdown = ""
        self._directory = DOCUMENTATION

    def show_file(self, path):
        self._directory = path.parent
        self._markdown = path.read_text(encoding="utf-8")
        self._render_markdown()

    def _render_markdown(self):
        document = G.QTextDocument(self)
        document.setDefaultFont(self.font())
        document.setBaseUrl(C.QUrl.fromLocalFile(str(self._directory) + "/"))
        self.setDocument(document)
        self.setMarkdown(self._markdown)

    def loadResource(self, resource_type, url):
        if resource_type == G.QTextDocument.ImageResource and url.isLocalFile():
            image = G.QImage(url.toLocalFile())
            if not image.isNull():
                width = max(100, self.viewport().width() - 24)
                return image.scaledToWidth(width, C.Qt.SmoothTransformation) if image.width() > width else image
        return super().loadResource(resource_type, url)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._markdown:
            position = self.verticalScrollBar().value()
            self._render_markdown()
            self.verticalScrollBar().setValue(position)

    def show_heading(self, heading):
        wanted = heading.replace("-", " ").casefold()
        block = self.document().begin()
        while block.isValid():
            text = re.sub(r"[^\w\s]", "", block.text()).strip().casefold()
            if text == wanted:
                y = self.document().documentLayout().blockBoundingRect(block).top()
                self.verticalScrollBar().setValue(max(0, int(y) - 20))
                return
            block = block.next()


class DocumentationViewer(W.QDialog):
    def __init__(self, parent=None, directory=DOCUMENTATION):
        super().__init__(parent)
        self.directory = Path(directory)
        self.setObjectName("documentationViewer")
        self.setWindowTitle("HALS Studio Help")
        self.resize(1200, 800)
        help_font = G.QFont("Segoe UI", 10)
        help_font.setStyleStrategy(G.QFont.PreferAntialias)
        self.setFont(help_font)
        self.setStyleSheet("""
            QDialog#documentationViewer, QDialog#documentationViewer QWidget {
                background: #ffffff;
                color: #111111;
                font-family: 'Segoe UI';
                font-size: 10pt;
            }
            QDialog#documentationViewer QTreeWidget {
                border: 1px solid #d4dce3;
            }
            QDialog#documentationViewer QTreeWidget::item:selected {
                background: #dcecff;
                color: #111111;
            }
            QDialog#documentationViewer QTextBrowser {
                border: 1px solid #d4dce3;
            }
        """)
        layout = W.QHBoxLayout(self)
        self.files = W.QTreeWidget()
        self.files.setFont(help_font)
        self.files.setHeaderHidden(True)
        self.files.setMinimumWidth(280)
        self.files.setMaximumWidth(350)
        self.browser = MarkdownBrowser()
        self.browser.setFont(help_font)
        layout.addWidget(self.files)
        layout.addWidget(self.browser, 1)
        self.files.itemActivated.connect(lambda item, _: self._selected(item))
        self.files.currentItemChanged.connect(lambda current, _: self._selected(current))
        self.browser.anchorClicked.connect(self._follow_link)
        self.refresh_files()

    def refresh_files(self):
        self.files.clear()
        if not self.directory.is_dir():
            self.browser.setPlainText("Documentation folder was not found.")
            return
        groups = {name: W.QTreeWidgetItem(self.files, [name]) for name in GROUPS}
        for group in groups.values():
            group.setFlags(group.flags() & ~C.Qt.ItemIsSelectable)
            group.setExpanded(True)
            font = group.font(0)
            font.setBold(True)
            group.setFont(0, font)
        for path in sorted(self.directory.iterdir(), key=lambda p: p.name.casefold()):
            if path.is_file() and path.suffix.lower() in (".md", ".pdf"):
                group_name = help_group(path)
                if group_name == "Hidden":
                    continue
                group = groups[group_name]
                title = path.stem.replace("_", " ")
                item = W.QTreeWidgetItem(group, [title + (" (PDF)" if path.suffix.lower() == ".pdf" else "")])
                item.setData(0, C.Qt.UserRole, path.name)
        if not groups["Analysis"].childCount():
            placeholder = W.QTreeWidgetItem(groups["Analysis"], ["No files yet"])
            placeholder.setFlags(placeholder.flags() & ~C.Qt.ItemIsSelectable)
            placeholder.setForeground(0, G.QColor("#6b7280"))
        if any(group.childCount() for group in groups.values()):
            first = next(group.child(0) for group in groups.values() if group.childCount())
            self.files.setCurrentItem(first)
        else:
            self.browser.setPlainText("No Markdown or PDF files were found.")

    def _selected(self, item):
        if item is not None and item.data(0, C.Qt.UserRole):
            self.open_document(item.data(0, C.Qt.UserRole))

    def open_document(self, filename, heading=""):
        path = (self.directory / filename).resolve()
        if path.parent != self.directory.resolve() or path.suffix.lower() not in (".md", ".pdf") or not path.is_file():
            return False
        if path.suffix.lower() == ".pdf":
            return G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(str(path)))
        self.browser.show_file(path)
        if heading:
            self.browser.show_heading(heading)
        for index in range(self.files.topLevelItemCount()):
            group = self.files.topLevelItem(index)
            for child_index in range(group.childCount()):
                item = group.child(child_index)
                if item.data(0, C.Qt.UserRole) == filename:
                    self.files.blockSignals(True)
                    self.files.setCurrentItem(item)
                    self.files.blockSignals(False)
                    return True
        return True

    def _follow_link(self, url):
        if url.isRelative() and not url.path() and url.hasFragment():
            self.browser.show_heading(url.fragment())
            return
        if url.isRelative():
            path = (self.browser._directory / url.path()).resolve()
        elif url.isLocalFile():
            path = Path(url.toLocalFile()).resolve()
        else:
            G.QDesktopServices.openUrl(url)
            return
        if path.parent == self.directory.resolve() and path.suffix.lower() in (".md", ".pdf"):
            self.open_document(path.name, url.fragment())
