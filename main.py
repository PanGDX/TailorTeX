import sys
import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QPlainTextEdit, QSplitter, QDialog, QMessageBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QFont

# Import the PDF modules (Included in PyQt6-WebEngine)
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtPdfWidgets import QPdfView

# Import your existing compiler module
from compiler import compile_latex_to_pdf

GEN_PDF_DIR = "generated-pdfs"
LATEX_CODE_DIR = "latex-files"
TEMP_PNG_DIR = ".temp"

def get_filepath():
    now = datetime.datetime.now()
    return f"{GEN_PDF_DIR}/{now.strftime('%Y-%m-%d %H-%M-%S')}.pdf"

# ==========================================
# Background Thread for Compilation
# ==========================================
class CompileThread(QThread):
    # Signals to communicate back to the Main GUI thread safely
    finished_signal = pyqtSignal(bool, str, str)  # success, message, filepath
    status_signal = pyqtSignal(str)

    def __init__(self, latex_code, filepath):
        super().__init__()
        self.latex_code = latex_code
        self.filepath = filepath

    def run(self):
        self.status_signal.emit("Status: Compiling (Please wait...)")
        # Call your existing tectonic compiler function
        success, message = compile_latex_to_pdf(self.latex_code, output_pdf_path=self.filepath)
        self.finished_signal.emit(success, message, self.filepath)


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

        # Read-only text box for the error
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlainText(error_message)
        self.text_edit.setReadOnly(True)
        # Use a monospaced font for errors
        self.text_edit.setFont(QFont("Courier", 10))
        layout.addWidget(self.text_edit)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


# ==========================================
# Main Application Window
# ==========================================
class TailorTeXApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TailorTeX - Resume Tailoring Tool")
        self.resize(1280, 720)

        # Setup Directories
        for directory in [GEN_PDF_DIR, LATEX_CODE_DIR, TEMP_PNG_DIR]:
            Path(f"./{directory}").mkdir(parents=True, exist_ok=True)

        # Central Widget & Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Toolbar Setup ---
        toolbar_layout = QHBoxLayout()
        
        self.btn_compile = QPushButton("⚙ Compile")
        self.btn_compile.clicked.connect(self.on_compile_clicked)
        
        self.btn_templates = QPushButton("📄 Templates")
        self.btn_templates.clicked.connect(lambda: print("Action: Open Templates"))
        
        self.btn_snapshots = QPushButton("🕒 Snapshots")
        self.btn_snapshots.clicked.connect(lambda: print("Action: Open Snapshots"))
        
        self.btn_ai = QPushButton("✨ AI Tailor")
        self.btn_ai.clicked.connect(lambda: print("Action: Open AI Tailor"))

        self.lbl_status = QLabel("Status: Ready")
        self.lbl_status.setStyleSheet("color: gray; font-weight: bold; margin-left: 15px;")

        for btn in [self.btn_compile, self.btn_templates, self.btn_snapshots, self.btn_ai]:
            toolbar_layout.addWidget(btn)
        toolbar_layout.addWidget(self.lbl_status)
        toolbar_layout.addStretch() # Pushes everything to the left

        main_layout.addLayout(toolbar_layout)

        # --- Split Screen Setup ---
        # QSplitter automatically provides a draggable divider
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter)

        # 1. LEFT PANE (Editor)
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(
            "% Write your LaTeX here...\n\\documentclass{article}\n\\begin{document}\n\nHello World!\n\n\\end{document}"
        )
        # Standardize a monospaced font for code
        font = QFont("Courier New", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(font)
        self.splitter.addWidget(self.editor)

        # 2. RIGHT PANE (PDF Viewer & Zoom Controls)
        right_pane = QWidget()
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Zoom Controls
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

        # Native Qt PDF Widgets
        self.pdf_document = QPdfDocument(self)
        self.pdf_view = QPdfView(self)
        self.pdf_view.setDocument(self.pdf_document)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.current_zoom = 1.0 # Base zoom
        
        right_layout.addWidget(self.pdf_view)
        self.splitter.addWidget(right_pane)

        # Set initial split sizes (50/50)
        self.splitter.setSizes([640, 640])

    # --- Callbacks and Methods ---

    def zoom_in(self):
        self.current_zoom += 0.2
        self.pdf_view.setZoomFactor(self.current_zoom)

    def zoom_out(self):
        self.current_zoom = max(0.2, self.current_zoom - 0.2)
        self.pdf_view.setZoomFactor(self.current_zoom)

    def on_compile_clicked(self):
        # Disable the compile button while compiling
        self.btn_compile.setEnabled(False)
        
        latex_code = self.editor.toPlainText()
        filepath = get_filepath()

        # Spin up QThread
        self.thread = CompileThread(latex_code, filepath)
        self.thread.status_signal.connect(self.update_status)
        self.thread.finished_signal.connect(self.on_compile_finished)
        self.thread.start()

    def update_status(self, text):
        self.lbl_status.setText(text)

    def on_compile_finished(self, success, message, filepath):
        self.btn_compile.setEnabled(True)

        if success:
            self.update_status("Status: Ready (Compile Success!)")
            # Natively load the PDF document into the viewer
            self.pdf_document.load(filepath)
            self.pdf_view.setZoomFactor(self.current_zoom)
        else:
            self.update_status("Status: Compile Failed!")
            # Show the error modal
            dialog = ErrorDialog(message, self)
            dialog.exec()


if __name__ == "__main__":
    # Initialize the Qt Application
    app = QApplication(sys.argv)
    
    # Create and show the main window
    window = TailorTeXApp()
    window.show()
    
    # Start the event loop
    sys.exit(app.exec())
