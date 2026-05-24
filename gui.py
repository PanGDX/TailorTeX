import sys
import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QPlainTextEdit, QSplitter, QDialog,
    QListWidget, QListWidgetItem, QMessageBox, QAbstractItemView, QStackedWidget
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtPdfWidgets import QPdfView

from compiler import compile_latex_to_pdf
from snapshot_manager import save_snapshot, load_index, load_snapshot_content, delete_snapshot

GEN_PDF_DIR = "generated-pdfs"
LATEX_CODE_DIR = "latex-files"
TEMP_PNG_DIR = ".temp"


def make_timestamp() -> str:
    """Single source of truth for the timestamp format used across PDF, .tex, and index."""
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
# Snapshots Modal Dialog
# ==========================================
class SnapshotsDialog(QDialog):
    # Emitted when the user confirms loading; carries the LaTeX source string
    load_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Snapshots")
        self.resize(960, 560)
        self.setModal(True)

        self._entries: list[dict] = []

        # Outer layout: list on the left, preview on the right
        outer_layout = QHBoxLayout(self)

        # ---- Left column: list + action buttons ----
        left_widget = QWidget()
        left_widget.setFixedWidth(320)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)

        header = QLabel("Saved snapshots")
        header.setStyleSheet("font-weight: bold; margin-bottom: 4px;")
        left_layout.addWidget(header)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        left_layout.addWidget(self.list_widget)

        btn_layout = QHBoxLayout()

        self.btn_load = QPushButton("Load into Editor")
        self.btn_load.setEnabled(False)
        self.btn_load.clicked.connect(self._on_load_clicked)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setEnabled(False)
        self.btn_delete.setStyleSheet("color: red;")
        self.btn_delete.clicked.connect(self._on_delete_clicked)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)

        btn_layout.addWidget(self.btn_load)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addWidget(btn_close)
        left_layout.addLayout(btn_layout)

        outer_layout.addWidget(left_widget)

        # ---- Right column: PDF preview (or not-found label) ----
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        preview_label = QLabel("Preview:")
        preview_label.setStyleSheet("font-weight: bold; margin-bottom: 4px;")
        right_layout.addWidget(preview_label)

        # QStackedWidget lets us swap between the PDF viewer and the
        # "PDF not found" placeholder without any show/hide juggling
        self.preview_stack = QStackedWidget()
        right_layout.addWidget(self.preview_stack)

        # Page 0 — placeholder shown before any selection or when PDF is missing
        self.lbl_no_pdf = QLabel()
        self.lbl_no_pdf.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_no_pdf.setStyleSheet("color: gray; font-size: 14px;")
        self.lbl_no_pdf.setText("Select a snapshot to preview")
        self.preview_stack.addWidget(self.lbl_no_pdf)   # index 0

        # Page 1 — live QPdfView
        self.preview_pdf_doc = QPdfDocument(self)
        self.preview_pdf_view = QPdfView(self)
        self.preview_pdf_view.setDocument(self.preview_pdf_doc)
        self.preview_pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.preview_pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.preview_stack.addWidget(self.preview_pdf_view)  # index 1

        outer_layout.addWidget(right_widget, stretch=1)

        self._populate()

    # ---- Internal helpers ----

    def _populate(self):
        self.list_widget.clear()
        self._show_placeholder("Select a snapshot to preview")
        self.btn_load.setEnabled(False)
        self.btn_delete.setEnabled(False)

        self._entries = load_index()

        if not self._entries:
            placeholder = QListWidgetItem("No snapshots yet.")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(placeholder)
            return

        for entry in self._entries:
            self.list_widget.addItem(QListWidgetItem(f"  {entry['timestamp']}"))

    def _selected_entry(self) -> dict | None:
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self._entries):
            return None
        return self._entries[row]

    def _show_placeholder(self, text: str):
        self.lbl_no_pdf.setText(text)
        self.preview_stack.setCurrentIndex(0)

    def _show_pdf(self, pdf_filepath: str):
        self.preview_pdf_doc.close()
        result = self.preview_pdf_doc.load(pdf_filepath)
        if result == QPdfDocument.Error.None_:
            self.preview_stack.setCurrentIndex(1)
        else:
            # load() succeeded in opening the file but reported a non-Ready
            # status — treat it the same as missing
            self._show_placeholder("PDF-NOT-FOUND")

    def _on_row_changed(self, row: int):
        entry = self._selected_entry()
        if entry is None:
            self._show_placeholder("Select a snapshot to preview")
            self.btn_load.setEnabled(False)
            self.btn_delete.setEnabled(False)
            return

        self.btn_load.setEnabled(True)
        self.btn_delete.setEnabled(True)

        pdf_path = entry.get("pdf_filepath", "")
        if pdf_path and Path(pdf_path).exists():
            self._show_pdf(pdf_path)
        else:
            self._show_placeholder("PDF-NOT-FOUND")

    def _on_load_clicked(self):
        entry = self._selected_entry()
        
        if entry is None:
            return
        try:
            content = load_snapshot_content(entry["tex_filepath"])
        except FileNotFoundError:
            QMessageBox.warning(self, "File Missing",
                                f"The .tex file could not be found:\n{entry['tex_filepath']}. Proceeding to delete this erroneous entry.")
            delete_snapshot(entry["tex_filepath"])
            self.accept()
            return

        confirm = QMessageBox.question(
            self,
            "Load Snapshot",
            f"Replace the current editor content with the snapshot from {entry['timestamp']}?\n\n"
            "Unsaved work in the editor will be overwritten.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.load_requested.emit(content)
            self.accept()

    def _on_delete_clicked(self):
        entry = self._selected_entry()
        if entry is None:
            return

        confirm = QMessageBox.question(
            self,
            "Delete Snapshot",
            f"Permanently delete the snapshot from {entry['timestamp']}?\n\n"
            "The associated PDF in generated-pdfs/ will not be removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            delete_snapshot(entry["tex_filepath"])
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
        self.btn_templates.clicked.connect(lambda: print("Action: Open Templates"))

        self.btn_snapshots = QPushButton("🕒 Snapshots")
        self.btn_snapshots.clicked.connect(self.on_snapshots_clicked)

        self.btn_ai = QPushButton("✨ AI Tailor")
        self.btn_ai.clicked.connect(lambda: print("Action: Open AI Tailor"))

        self.lbl_status = QLabel("Status: Ready")
        self.lbl_status.setStyleSheet("color: gray; font-weight: bold; margin-left: 15px;")

        for btn in [self.btn_compile, self.btn_templates, self.btn_snapshots, self.btn_ai]:
            toolbar_layout.addWidget(btn)
        toolbar_layout.addWidget(self.lbl_status)
        toolbar_layout.addStretch()

        main_layout.addWidget(toolbar_widget, 0)

        # --- Split Screen ---
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter, 1)

        self.editor = QPlainTextEdit()
        self.editor.setPlainText(
            "% Write your LaTeX here...\n\\documentclass{article}\n\\begin{document}\n\nHello World!\n\n\\end{document}"
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

        self._pending_latex: str = ""
        self._pending_timestamp: str = ""

    # --- Toolbar Callbacks ---

    def zoom_in(self):
        self.current_zoom += 0.2
        self.pdf_view.setZoomFactor(self.current_zoom)

    def zoom_out(self):
        self.current_zoom = max(0.2, self.current_zoom - 0.2)
        self.pdf_view.setZoomFactor(self.current_zoom)

    def on_compile_clicked(self):
        self.btn_compile.setEnabled(False)

        # Generate the timestamp once here — this exact string will be used
        # for the PDF filename, the .tex filename, and the index entry.
        timestamp = make_timestamp()
        pdf_filepath = f"{GEN_PDF_DIR}/{timestamp}.pdf"

        self._pending_latex = self.editor.toPlainText()
        self._pending_timestamp = timestamp

        self.thread = CompileThread(self._pending_latex, pdf_filepath)
        self.thread.status_signal.connect(self.update_status)
        self.thread.finished_signal.connect(self.on_compile_finished)
        self.thread.start()

    def update_status(self, text):
        self.lbl_status.setText(text)

    def on_compile_finished(self, success, message, pdf_filepath):
        self.btn_compile.setEnabled(True)

        if success:
            self.update_status("Status: Ready (Compile Success!)")
            self.pdf_document.load(pdf_filepath)
            self.pdf_view.setZoomFactor(self.current_zoom)

            try:
                save_snapshot(self._pending_latex, self._pending_timestamp)
            except Exception as e:
                self.update_status(f"Status: Compiled OK, but snapshot failed: {e}")
        else:
            self.update_status("Status: Compile Failed!")
            dialog = ErrorDialog(message, self)
            dialog.exec()

    def on_snapshots_clicked(self):
        dialog = SnapshotsDialog(self)
        dialog.load_requested.connect(self.load_snapshot_into_editor)
        dialog.exec()

    def load_snapshot_into_editor(self, latex_source: str):
        self.editor.setPlainText(latex_source)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TailorTeXApp()
    window.show()
    sys.exit(app.exec())
