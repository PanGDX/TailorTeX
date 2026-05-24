import sys
import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QPlainTextEdit, QSplitter, QDialog,
    QListWidget, QListWidgetItem, QMessageBox, QAbstractItemView,
    QStackedWidget, QInputDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtPdfWidgets import QPdfView

from compiler import compile_latex_to_pdf
from snapshot_manager import save_snapshot, load_index as snap_load_index, \
    load_snapshot_content, delete_snapshot
from template_manager import seed_default_templates, save_template, \
    load_index as tmpl_load_index, load_template_content, delete_template

GEN_PDF_DIR = "generated-pdfs"
LATEX_CODE_DIR = "latex-files"
TEMP_PNG_DIR = ".temp"


def make_timestamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")


# ==========================================
# Background Thread for Compilation
# ==========================================
class CompileThread(QThread):
    finished_signal = pyqtSignal(bool, str, str)  # success, message, pdf_filepath
    status_signal = pyqtSignal(str)

    def __init__(self, latex_code, pdf_filepath):
        super().__init__()
        self.latex_code = latex_code
        self.pdf_filepath = pdf_filepath

    def run(self):
        self.status_signal.emit("Status: Compiling (Please wait...)")
        success, message = compile_latex_to_pdf(self.latex_code, output_pdf_path=self.pdf_filepath)
        self.finished_signal.emit(success, message, self.pdf_filepath)


# ==========================================
# Error Modal Dialog
# ==========================================
class ErrorDialog(QDialog):
    def __init__(self, error_message, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Compilation Error")
        self.resize(600, 400)
        self.setModal(True)

        layout = QVBoxLayout(self)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlainText(error_message)
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Courier", 10))
        layout.addWidget(self.text_edit)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


# ==========================================
# Shared PDF-preview panel
# (reused identically in both dialogs)
# ==========================================
class PdfPreviewPanel(QWidget):
    """
    A QStackedWidget wrapper that shows either:
      - a centred placeholder label  (index 0)
      - a live QPdfView              (index 1)
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self._lbl = QLabel()
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setStyleSheet("color: gray; font-size: 14px;")
        self.stack.addWidget(self._lbl)          # index 0

        self._doc = QPdfDocument(self)
        self._view = QPdfView(self)
        self._view.setDocument(self._doc)
        self._view.setPageMode(QPdfView.PageMode.MultiPage)
        self._view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.stack.addWidget(self._view)         # index 1

        self.show_placeholder("Select an entry to preview")

    def show_placeholder(self, text: str):
        self._lbl.setText(text)
        self.stack.setCurrentIndex(0)

    def show_pdf(self, pdf_filepath: str):
        self._doc.close()
        result = self._doc.load(pdf_filepath)
        if result == QPdfDocument.Error.None_:
            self.stack.setCurrentIndex(1)
        else:
            self.show_placeholder("PDF-NOT-FOUND")


# ==========================================
# Snapshots Dialog
# ==========================================
class SnapshotsDialog(QDialog):
    load_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Snapshots")
        self.resize(960, 560)
        self.setModal(True)
        self._entries: list[dict] = []

        outer = QHBoxLayout(self)

        # Left column
        left = QWidget()
        left.setFixedWidth(300)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)

        ll.addWidget(QLabel("<b>Saved snapshots</b>"))

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        ll.addWidget(self.list_widget)

        self.btn_load = QPushButton("Load into Editor")
        self.btn_load.setEnabled(False)
        self.btn_load.clicked.connect(self._on_load_clicked)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setEnabled(False)
        self.btn_delete.setStyleSheet("color: red;")
        self.btn_delete.clicked.connect(self._on_delete_clicked)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)

        btns = QHBoxLayout()
        btns.addWidget(self.btn_load)
        btns.addWidget(self.btn_delete)
        btns.addWidget(btn_close)
        ll.addLayout(btns)

        outer.addWidget(left)

        # Right column — PDF preview
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("<b>Preview</b>"))
        self.preview = PdfPreviewPanel()
        rl.addWidget(self.preview)
        outer.addWidget(right, stretch=1)

        self._populate()

    def _populate(self):
        self.list_widget.clear()
        self.preview.show_placeholder("Select a snapshot to preview")
        self.btn_load.setEnabled(False)
        self.btn_delete.setEnabled(False)
        self._entries = snap_load_index()

        if not self._entries:
            item = QListWidgetItem("No snapshots yet.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(item)
            return
        for e in self._entries:
            self.list_widget.addItem(QListWidgetItem(f"  {e['timestamp']}"))

    def _selected(self) -> dict | None:
        row = self.list_widget.currentRow()
        return self._entries[row] if 0 <= row < len(self._entries) else None

    def _on_row_changed(self, _row):
        e = self._selected()
        if e is None:
            self.preview.show_placeholder("Select a snapshot to preview")
            self.btn_load.setEnabled(False)
            self.btn_delete.setEnabled(False)
            return
        self.btn_load.setEnabled(True)
        self.btn_delete.setEnabled(True)
        pdf = e.get("pdf_filepath", "")
        if pdf and Path(pdf).exists():
            self.preview.show_pdf(pdf)
        else:
            self.preview.show_placeholder("PDF-NOT-FOUND")

    def _on_load_clicked(self):
        e = self._selected()
        if e is None:
            return
        try:
            content = load_snapshot_content(e["tex_filepath"])
        except FileNotFoundError:
            QMessageBox.warning(self, "File Missing",
                                f"The .tex file could not be found:\n{e['tex_filepath']}. Proceeding to delete erroneous snapshot.")
            delete_snapshot(e["tex_filepath"])
            self.accept()
            return
        if QMessageBox.question(
            self, "Load Snapshot",
            f"Replace the current editor content with the snapshot from {e['timestamp']}?\n\n"
            "Unsaved work in the editor will be overwritten.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        ) == QMessageBox.StandardButton.Yes:
            self.load_requested.emit(content)
            self.accept()

    def _on_delete_clicked(self):
        e = self._selected()
        if e is None:
            return
        if QMessageBox.question(
            self, "Delete Snapshot",
            f"Permanently delete the snapshot from {e['timestamp']}?\n\n"
            "The associated PDF in generated-pdfs/ will not be removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        ) == QMessageBox.StandardButton.Yes:
            delete_snapshot(e["tex_filepath"])
            self._populate()


# ==========================================
# Templates Dialog
# ==========================================
class TemplatesDialog(QDialog):
    load_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Templates")
        self.resize(960, 560)
        self.setModal(True)
        self._entries: list[dict] = []

        outer = QHBoxLayout(self)

        # Left column
        left = QWidget()
        left.setFixedWidth(300)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)

        ll.addWidget(QLabel("<b>Available templates</b>"))

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        ll.addWidget(self.list_widget)

        self.btn_load = QPushButton("Load into Editor")
        self.btn_load.setEnabled(False)
        self.btn_load.clicked.connect(self._on_load_clicked)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setEnabled(False)
        self.btn_delete.setStyleSheet("color: red;")
        self.btn_delete.clicked.connect(self._on_delete_clicked)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)

        btns = QHBoxLayout()
        btns.addWidget(self.btn_load)
        btns.addWidget(self.btn_delete)
        btns.addWidget(btn_close)
        ll.addLayout(btns)

        outer.addWidget(left)

        # Right column — PDF preview
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("<b>Preview</b>"))
        self.preview = PdfPreviewPanel()
        rl.addWidget(self.preview)
        outer.addWidget(right, stretch=1)

        self._populate()

    def _populate(self):
        self.list_widget.clear()
        self.preview.show_placeholder("Select a template to preview")
        self.btn_load.setEnabled(False)
        self.btn_delete.setEnabled(False)
        self._entries = tmpl_load_index()

        if not self._entries:
            item = QListWidgetItem("No templates yet.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(item)
            return
        for e in self._entries:
            self.list_widget.addItem(QListWidgetItem(f"  {e['name']}"))

    def _selected(self) -> dict | None:
        row = self.list_widget.currentRow()
        return self._entries[row] if 0 <= row < len(self._entries) else None

    def _on_row_changed(self, _row):
        e = self._selected()
        if e is None:
            self.preview.show_placeholder("Select a template to preview")
            self.btn_load.setEnabled(False)
            self.btn_delete.setEnabled(False)
            return
        self.btn_load.setEnabled(True)
        self.btn_delete.setEnabled(True)
        pdf = e.get("pdf_filepath", "")
        if pdf and Path(pdf).exists():
            self.preview.show_pdf(pdf)
        else:
            self.preview.show_placeholder("PDF-NOT-FOUND")

    def _on_load_clicked(self):
        e = self._selected()
        if e is None:
            return
        try:
            content = load_template_content(e["tex_filepath"])
        except FileNotFoundError:
            QMessageBox.warning(self, "File Missing",
                                f"The .tex file could not be found:\n{e['tex_filepath']}. Proceeding to delete erroneous template.")
            delete_template(e["tex_filepath"])
            self.accept()
            return
        if QMessageBox.question(
            self, "Load Template",
            f"Replace the current editor content with \"{e['name']}\"?\n\n"
            "Unsaved work in the editor will be overwritten.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        ) == QMessageBox.StandardButton.Yes:
            self.load_requested.emit(content)
            self.accept()

    def _on_delete_clicked(self):
        e = self._selected()
        if e is None:
            return
        if QMessageBox.question(
            self, "Delete Template",
            f"Permanently delete the template \"{e['name']}\"?\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        ) == QMessageBox.StandardButton.Yes:
            delete_template(e["tex_filepath"])
            self._populate()


# ==========================================
# Main Application Window
# ==========================================
class TailorTeXApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TailorTeX - Resume Tailoring Tool")
        self.resize(1280, 720)

        for directory in [GEN_PDF_DIR, LATEX_CODE_DIR, TEMP_PNG_DIR]:
            Path(f"./{directory}").mkdir(parents=True, exist_ok=True)

        # Seed default templates on every launch (no-ops if already present)
        seed_default_templates()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Toolbar ---
        toolbar_widget = QWidget()
        toolbar_widget.setFixedHeight(44)
        toolbar_layout = QHBoxLayout(toolbar_widget)
        toolbar_layout.setContentsMargins(6, 4, 6, 4)
        toolbar_layout.setSpacing(6)

        self.btn_compile = QPushButton("⚙ Compile")
        self.btn_compile.clicked.connect(self.on_compile_clicked)

        self.btn_templates = QPushButton("📄 Templates")
        self.btn_templates.clicked.connect(self.on_templates_clicked)

        self.btn_snapshots = QPushButton("🕒 Snapshots")
        self.btn_snapshots.clicked.connect(self.on_snapshots_clicked)

        self.btn_make_template = QPushButton("⭐ Make Template")
        self.btn_make_template.clicked.connect(self.on_make_template_clicked)

        self.btn_ai = QPushButton("✨ AI Tailor")
        self.btn_ai.clicked.connect(lambda: print("Action: Open AI Tailor"))

        self.lbl_status = QLabel("Status: Ready")
        self.lbl_status.setStyleSheet("color: gray; font-weight: bold; margin-left: 15px;")

        for btn in [self.btn_compile, self.btn_templates, self.btn_snapshots,
                    self.btn_make_template, self.btn_ai]:
            toolbar_layout.addWidget(btn)
        toolbar_layout.addWidget(self.lbl_status)
        toolbar_layout.addStretch()

        main_layout.addWidget(toolbar_widget, 0)

        # --- Split Screen ---
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter, 1)

        self.editor = QPlainTextEdit()
        self.editor.setPlainText(
            "% Write your LaTeX here...\n\\documentclass{article}\n\\begin{document}\n\n"
            "Hello World!\n\n\\end{document}"
        )
        font = QFont("Courier New", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(font)
        self.splitter.addWidget(self.editor)

        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(0, 0, 0, 0)

        zoom_layout = QHBoxLayout()
        lbl_pdf = QLabel("PDF Viewer")
        lbl_pdf.setStyleSheet("color: gray; font-weight: bold;")
        btn_zoom_in = QPushButton("🔍 Zoom In")
        btn_zoom_in.clicked.connect(self.zoom_in)
        btn_zoom_out = QPushButton("🔍 Zoom Out")
        btn_zoom_out.clicked.connect(self.zoom_out)
        zoom_layout.addWidget(lbl_pdf)
        zoom_layout.addWidget(btn_zoom_in)
        zoom_layout.addWidget(btn_zoom_out)
        zoom_layout.addStretch()
        right_layout.addLayout(zoom_layout)

        self.pdf_document = QPdfDocument(self)
        self.pdf_view = QPdfView(self)
        self.pdf_view.setDocument(self.pdf_document)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.current_zoom = 1.0
        right_layout.addWidget(self.pdf_view)

        self.splitter.addWidget(right_pane)
        self.splitter.setSizes([640, 640])

        # Pending compile state
        # _compile_mode is either "snapshot" or "template"
        self._pending_latex: str = ""
        self._pending_timestamp: str = ""
        self._compile_mode: str = "snapshot"
        self._pending_template_name: str = ""

    # --- Zoom ---

    def zoom_in(self):
        self.current_zoom += 0.2
        self.pdf_view.setZoomFactor(self.current_zoom)

    def zoom_out(self):
        self.current_zoom = max(0.2, self.current_zoom - 0.2)
        self.pdf_view.setZoomFactor(self.current_zoom)

    # --- Compile (normal) ---

    def on_compile_clicked(self):
        self._start_compile(mode="snapshot")

    # --- Make This A Template ---

    def on_make_template_clicked(self):
        name, ok = QInputDialog.getText(
            self, "Save as Template", "Template name:"
        )
        if not ok or not name.strip():
            return  # user cancelled or left blank — don't compile

        self._pending_template_name = name.strip()
        self._start_compile(mode="template")

    # --- Shared compile entry point ---

    def _start_compile(self, mode: str):
        self._set_toolbar_enabled(False)
        timestamp = make_timestamp()
        pdf_filepath = f"{GEN_PDF_DIR}/{timestamp}.pdf"

        self._pending_latex = self.editor.toPlainText()
        self._pending_timestamp = timestamp
        self._compile_mode = mode

        self.thread = CompileThread(self._pending_latex, pdf_filepath)
        self.thread.status_signal.connect(self.update_status)
        self.thread.finished_signal.connect(self.on_compile_finished)
        self.thread.start()

    def _set_toolbar_enabled(self, enabled: bool):
        for btn in [self.btn_compile, self.btn_make_template,
                    self.btn_templates, self.btn_snapshots, self.btn_ai]:
            btn.setEnabled(enabled)

    def update_status(self, text: str):
        self.lbl_status.setText(text)

    def on_compile_finished(self, success: bool, message: str, pdf_filepath: str):
        self._set_toolbar_enabled(True)

        if not success:
            self.update_status("Status: Compile Failed!")
            ErrorDialog(message, self).exec()
            return

        # --- Success ---
        self.update_status("Status: Ready (Compile Success!)")
        self.pdf_document.load(pdf_filepath)
        self.pdf_view.setZoomFactor(self.current_zoom)

        if self._compile_mode == "snapshot":
            try:
                save_snapshot(self._pending_latex, self._pending_timestamp)
            except Exception as e:
                self.update_status(f"Status: Compiled OK, but snapshot failed: {e}")

        elif self._compile_mode == "template":
            try:
                save_template(
                    name=self._pending_template_name,
                    latex_code=self._pending_latex,
                    compiled_pdf_filepath=pdf_filepath,
                )
                self.update_status(
                    f"Status: Template \"{self._pending_template_name}\" saved!"
                )
            except Exception as e:
                self.update_status(f"Status: Compiled OK, but template save failed: {e}")

    # --- Dialog launchers ---

    def on_snapshots_clicked(self):
        dialog = SnapshotsDialog(self)
        dialog.load_requested.connect(self._load_source_into_editor)
        dialog.exec()

    def on_templates_clicked(self):
        dialog = TemplatesDialog(self)
        dialog.load_requested.connect(self._load_source_into_editor)
        dialog.exec()

    def _load_source_into_editor(self, latex_source: str):
        self.editor.setPlainText(latex_source)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TailorTeXApp()
    window.show()
    sys.exit(app.exec())
