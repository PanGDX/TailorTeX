import sys
import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QPlainTextEdit, QSplitter, QDialog,
    QListWidget, QListWidgetItem, QMessageBox, QAbstractItemView,
    QStackedWidget, QInputDialog, QComboBox, QLineEdit, QFormLayout,
    QGroupBox, QSizePolicy, QProgressBar, QFrame
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
from ai_manager import (
    load_api_key, save_api_key, load_provider, save_provider,
    build_initial_messages, build_retry_messages,
    request_latex, session_log_dir, AI_LOGS_DIR,
)

AI_PROVIDERS = ["OpenAI", "Claude", "Google Gemini"]
MAX_AI_RETRIES = 3

GEN_PDF_DIR = "generated-pdfs"
BATCH_PDF_DIR = "generated-pdfs/batch"

BATCH_JOB_TEMPLATE = """\
## Job 1
Company: 
Job Role: 
Job Scope:
(Copy From Website)

---

## Job 2
Company: 
Job Role: 
Job Scope:
(Copy From Website)
"""


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
# Background Thread for AI Requests + Retry Loop
# ==========================================
class AIThread(QThread):
    """
    Runs the full AI request + compile-retry loop off the main thread.

    Signals:
        status_signal(str)           -- status bar text updates
        finished_signal(bool, str, str, str)
            success, result_latex_or_error, pdf_filepath, session_log_dir
    """
    status_signal    = pyqtSignal(str)
    finished_signal  = pyqtSignal(bool, str, str, str)

    def __init__(self, provider: str, api_key: str,
                 latex: str, job_description: str,
                 session_id: str, pdf_dir: str):
        super().__init__()
        self.provider        = provider
        self.api_key         = api_key
        self.latex           = latex
        self.job_description = job_description
        self.session_id      = session_id
        self.pdf_dir         = pdf_dir

    def run(self):
        import tempfile, shutil, os

        log_dir  = session_log_dir(self.session_id)
        messages = build_initial_messages(self.latex, self.job_description)
        last_latex   = ""
        last_error   = ""

        for attempt in range(1, MAX_AI_RETRIES + 1):
            self.status_signal.emit(
                f"Status: AI attempt {attempt}/{MAX_AI_RETRIES} — waiting for response…"
            )

            # ── Call the AI provider ───────────────────────────────────────
            try:
                new_latex, _raw = request_latex(
                    provider=self.provider,
                    api_key=self.api_key,
                    messages=messages,
                    session_id=self.session_id,
                    attempt=attempt,
                )
            except Exception as exc:
                self.finished_signal.emit(False, f"AI request failed: {exc}", "", log_dir)
                return

            last_latex = new_latex

            # ── Try to compile ─────────────────────────────────────────────
            self.status_signal.emit(
                f"Status: AI attempt {attempt}/{MAX_AI_RETRIES} — compiling…"
            )
            pdf_path = os.path.join(
                self.pdf_dir, f"ai_{self.session_id}_attempt{attempt}.pdf"
            )
            success, compile_msg = compile_latex_to_pdf(new_latex, pdf_path)

            if success:
                self.finished_signal.emit(True, new_latex, pdf_path, log_dir)
                return

            # ── Compile failed — prepare retry messages ────────────────────
            last_error = compile_msg
            if attempt < MAX_AI_RETRIES:
                self.status_signal.emit(
                    f"Status: Compile failed (attempt {attempt}), asking AI to fix…"
                )
                messages = build_retry_messages(messages, new_latex, compile_msg)

        # All retries exhausted
        err_msg = (
            f"AI Error: LaTeX is not compiling after {MAX_AI_RETRIES} attempts.\n"
            f"Previous runs saved at: {log_dir}\n\n"
            f"Last compiler error:\n{last_error}"
        )
        self.finished_signal.emit(False, err_msg, "", log_dir)


# ==========================================
# AI Provider Settings Dialog
# ==========================================
class AISettingsDialog(QDialog):
    """Small dialog to select the AI provider and enter / save the API key."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Provider Settings")
        self.setFixedWidth(420)
        self.setModal(True)

        layout = QVBoxLayout(self)

        group = QGroupBox("API Configuration")
        form  = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.combo_provider = QComboBox()
        self.combo_provider.addItems(AI_PROVIDERS)
        self.combo_provider.currentTextChanged.connect(self._on_provider_changed)
        form.addRow("Provider:", self.combo_provider)

        self.edit_key = QLineEdit()
        self.edit_key.setPlaceholderText("Paste your API key here")
        self.edit_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API Key:", self.edit_key)

        lbl_note = QLabel(
            "Keys are saved locally in .env in the project root.\n"
            "They are never transmitted anywhere except the chosen provider."
        )
        lbl_note.setWordWrap(True)
        lbl_note.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow(lbl_note)

        layout.addWidget(group)

        btn_row = QHBoxLayout()
        btn_save   = QPushButton("Save")
        btn_save.clicked.connect(self._on_save)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        # Populate from .env
        saved_provider = load_provider()
        if saved_provider in AI_PROVIDERS:
            self.combo_provider.setCurrentText(saved_provider)
        self._on_provider_changed(self.combo_provider.currentText())

    def _on_provider_changed(self, provider: str):
        key = load_api_key(provider)
        self.edit_key.setText(key)

    def _on_save(self):
        provider = self.combo_provider.currentText()
        key      = self.edit_key.text().strip()
        if not key:
            QMessageBox.warning(self, "Missing Key", "Please enter an API key.")
            return
        save_provider(provider)
        save_api_key(provider, key)
        self.accept()

    def selected_provider(self) -> str:
        return self.combo_provider.currentText()


# ==========================================
# AI Tailor Dialog
# ==========================================
class AITailorDialog(QDialog):
    """
    Popup for pasting a job description and triggering the AI tailoring flow.
    Emits latex_ready(str, str) with (new_latex, pdf_path) on success.
    """
    latex_ready = pyqtSignal(str, str)   # (new_latex, pdf_filepath)

    def __init__(self, current_latex: str, provider: str, api_key: str,
                 pdf_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Tailor — Job Description")
        self.resize(660, 520)
        self.setModal(True)

        self._current_latex = current_latex
        self._provider      = provider
        self._api_key       = api_key
        self._pdf_dir       = pdf_dir
        self._ai_thread: AIThread | None = None

        layout = QVBoxLayout(self)

        # Provider badge
        badge = QLabel(f"Provider: <b>{provider}</b>")
        badge.setStyleSheet("color: gray; font-size: 12px;")
        layout.addWidget(badge)

        # Job description input
        lbl = QLabel("Paste the job description below, then click <b>Apply AI</b>:")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.text_jd = QPlainTextEdit()
        self.text_jd.setPlaceholderText(
            "Job Description:\n\n"
            "Company: \n"
            "Role: \n"
            "Key Requirements:\n"
            "  - \n"
            "  - \n"
            "\nAbout the role:\n"
        )
        self.text_jd.setFont(QFont("Courier New", 10))
        layout.addWidget(self.text_jd, stretch=1)

        # Status label
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #555; font-size: 11px;")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_apply  = QPushButton("✨ Apply AI")
        self.btn_apply.setDefault(True)
        self.btn_apply.clicked.connect(self._on_apply_clicked)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)

        btn_row.addStretch()
        btn_row.addWidget(self.btn_apply)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

    # ── Apply button ──────────────────────────────────────────────────────────

    def _on_apply_clicked(self):
        jd = self.text_jd.toPlainText().strip()
        if not jd:
            QMessageBox.warning(self, "Empty Input",
                                "Please paste a job description before applying.")
            return

        import datetime
        session_id = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        self.btn_apply.setEnabled(False)
        self.btn_cancel.setText("Close")
        self.lbl_status.setText("Status: Sending request to AI provider…")

        self._ai_thread = AIThread(
            provider=self._provider,
            api_key=self._api_key,
            latex=self._current_latex,
            job_description=jd,
            session_id=session_id,
            pdf_dir=self._pdf_dir,
        )
        self._ai_thread.status_signal.connect(self._on_thread_status)
        self._ai_thread.finished_signal.connect(self._on_thread_finished)
        self._ai_thread.start()

    def _on_cancel_clicked(self):
        if self._ai_thread and self._ai_thread.isRunning():
            # Don't kill the thread mid-flight; just close after it finishes
            self.reject()
            return
        self.reject()

    # ── Thread callbacks ──────────────────────────────────────────────────────

    def _on_thread_status(self, text: str):
        self.lbl_status.setText(text)

    def _on_thread_finished(self, success: bool, result: str, pdf_path: str, log_dir: str):
        self.btn_apply.setEnabled(True)

        if success:
            self.lbl_status.setText("Status: Done! Editor updated.")
            self.latex_ready.emit(result, pdf_path)
            self.accept()
        else:
            self.lbl_status.setText("Status: Failed — see error dialog.")
            QMessageBox.critical(
                self, "AI Tailor Error",
                result,
                QMessageBox.StandardButton.Ok,
            )


# ==========================================
# Batch Make — helpers
# ==========================================

def _parse_batch_jobs(text: str) -> list[str]:
    """
    Split the batch input text on '---' separators.
    Each chunk is stripped; empty chunks are discarded.
    Returns a list of job description strings.
    """
    chunks = text.split("---")
    jobs = [c.strip() for c in chunks if c.strip()]
    return jobs


def _slugify(text: str, max_len: int = 40) -> str:
    """Turn 'Acme Corp / Senior Engineer' into 'acme-corp-senior-engineer'."""
    import re
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s/\\]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len]


def _extract_job_label(job_text: str) -> str:
    """
    Try to extract a human-readable label from a job block.
    Looks for 'Company:' and 'Job Role:' lines; falls back to first line.
    """
    company = ""
    role    = ""
    for line in job_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("company:"):
            company = stripped.split(":", 1)[1].strip()
        elif stripped.lower().startswith("job role:"):
            role = stripped.split(":", 1)[1].strip()
        if company and role:
            break
    if company or role:
        parts = [p for p in [company, role] if p]
        return " / ".join(parts)
    # Fallback: first non-empty, non-header line
    for line in job_text.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:60]
    return "Untitled Job"


# ==========================================
# Batch Make — background thread
# ==========================================
class BatchThread(QThread):
    """
    Processes a list of job descriptions sequentially against the same base LaTeX.

    Signals:
        job_started(int, str)           index, label
        job_status(int, str)            index, status text
        job_done(int, bool, str, str)   index, success, latex_or_error, pdf_path
        all_done()
    """
    job_started = pyqtSignal(int, str)
    job_status  = pyqtSignal(int, str)
    job_done    = pyqtSignal(int, bool, str, str)
    all_done    = pyqtSignal()

    def __init__(self, provider: str, api_key: str,
                 base_latex: str, jobs: list[str],
                 batch_id: str, pdf_dir: str):
        super().__init__()
        self.provider    = provider
        self.api_key     = api_key
        self.base_latex  = base_latex
        self.jobs        = jobs
        self.batch_id    = batch_id
        self.pdf_dir     = pdf_dir
        self._stop       = False

    def stop(self):
        self._stop = True

    def run(self):
        import os
        os.makedirs(self.pdf_dir, exist_ok=True)

        for idx, job_desc in enumerate(self.jobs):
            if self._stop:
                break

            label = _extract_job_label(job_desc)
            self.job_started.emit(idx, label)

            session_id = f"{self.batch_id}_job{idx}"
            messages   = build_initial_messages(self.base_latex, job_desc)
            last_latex = ""
            last_error = ""
            success    = False

            for attempt in range(1, MAX_AI_RETRIES + 1):
                if self._stop:
                    break

                self.job_status.emit(
                    idx,
                    f"Attempt {attempt}/{MAX_AI_RETRIES} — waiting for AI…"
                )
                try:
                    new_latex, _ = request_latex(
                        provider=self.provider,
                        api_key=self.api_key,
                        messages=messages,
                        session_id=session_id,
                        attempt=attempt,
                    )
                except Exception as exc:
                    self.job_done.emit(idx, False, f"AI request failed: {exc}", "")
                    break

                last_latex = new_latex
                self.job_status.emit(idx, f"Attempt {attempt}/{MAX_AI_RETRIES} — compiling…")

                slug     = _slugify(label) or f"job{idx}"
                pdf_name = f"{slug}_attempt{attempt}.pdf"
                pdf_path = os.path.join(self.pdf_dir, pdf_name)

                ok, compile_msg = compile_latex_to_pdf(new_latex, pdf_path)

                if ok:
                    success = True
                    self.job_done.emit(idx, True, new_latex, pdf_path)
                    break

                last_error = compile_msg
                if attempt < MAX_AI_RETRIES:
                    self.job_status.emit(
                        idx, f"Compile failed (attempt {attempt}), retrying…"
                    )
                    messages = build_retry_messages(messages, new_latex, compile_msg)

            if not success and not self._stop:
                err = (
                    f"LaTeX did not compile after {MAX_AI_RETRIES} attempts.\n"
                    f"Last error:\n{last_error}"
                )
                self.job_done.emit(idx, False, err, "")

        self.all_done.emit()


# ==========================================
# Batch Make — dialog
# ==========================================

# Status icons shown in the job list
_ICON_WAITING  = "⬜"
_ICON_RUNNING  = "🔄"
_ICON_OK       = "✅"
_ICON_FAIL     = "❌"


class BatchMakeDialog(QDialog):
    """
    Two-phase dialog:
      Phase 1 — user edits the markdown job list, then clicks Run.
      Phase 2 — progress view; each job row shows live status.

    On completion the user can load any successful result into the editor.
    """
    load_into_editor = pyqtSignal(str, str)   # (latex, pdf_path)

    def __init__(self, base_latex: str, provider: str, api_key: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Batch Make — AI Resume Tailoring")
        self.resize(780, 620)
        self.setModal(True)

        self._base_latex  = base_latex
        self._provider    = provider
        self._api_key     = api_key
        self._thread: BatchThread | None = None

        # Per-job result storage: index → (success, latex, pdf_path)
        self._results: dict[int, tuple[bool, str, str]] = {}

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self._outer = QVBoxLayout(self)
        self._outer.setSpacing(8)

        # Provider badge
        badge = QLabel(f"Provider: <b>{self._provider}</b>  |  Base document: current editor content")
        badge.setStyleSheet("color: gray; font-size: 11px;")
        self._outer.addWidget(badge)

        # ── Stacked pages ─────────────────────────────────────────────────────
        self._stack = QStackedWidget()
        self._outer.addWidget(self._stack, stretch=1)

        self._stack.addWidget(self._build_input_page())   # index 0
        self._stack.addWidget(self._build_progress_page()) # index 1

        # ── Bottom button row ─────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #ccc;")
        self._outer.addWidget(sep)

        btn_row = QHBoxLayout()

        self.btn_run = QPushButton("▶  Run Batch")
        self.btn_run.setDefault(True)
        self.btn_run.clicked.connect(self._on_run_clicked)

        self.btn_stop = QPushButton("⏹  Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop_clicked)

        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self._on_close_clicked)

        btn_row.addWidget(self.btn_run)
        btn_row.addWidget(self.btn_stop)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_close)
        self._outer.addLayout(btn_row)

    def _build_input_page(self) -> QWidget:
        page   = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(
            "Define one job per section, separated by <b>---</b>. "
            "Fill in Company, Job Role, and paste the Job Scope from the website."
        )
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.text_jobs = QPlainTextEdit()
        self.text_jobs.setPlainText(BATCH_JOB_TEMPLATE)   # pre-filled, not placeholder
        self.text_jobs.setFont(QFont("Courier New", 10))
        layout.addWidget(self.text_jobs, stretch=1)

        return page

    def _build_progress_page(self) -> QWidget:
        page   = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        hdr = QLabel("<b>Batch progress</b>")
        layout.addWidget(hdr)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        # Job list: each item shows icon + label + status
        self.job_list = QListWidget()
        self.job_list.setAlternatingRowColors(True)
        self.job_list.setFont(QFont("Courier New", 10))
        layout.addWidget(self.job_list, stretch=1)

        # Load-into-editor button (enabled only when a successful job is selected)
        self.btn_load_result = QPushButton("📂  Load Selected into Editor")
        self.btn_load_result.setEnabled(False)
        self.btn_load_result.clicked.connect(self._on_load_result_clicked)
        layout.addWidget(self.btn_load_result)

        self.job_list.currentRowChanged.connect(self._on_job_row_changed)

        return page

    # ── Phase 1 → 2 transition ────────────────────────────────────────────────

    def _on_run_clicked(self):
        raw_text = self.text_jobs.toPlainText()
        jobs     = _parse_batch_jobs(raw_text)

        if not jobs:
            QMessageBox.warning(
                self, "No Jobs",
                "No job blocks were found. Make sure sections are separated by ---."
            )
            return

        # Warn if any job still has unfilled placeholder text
        placeholder_warn = any(
            "(Copy From Website)" in j or j.strip() == BATCH_JOB_TEMPLATE.strip()
            for j in jobs
        )
        if placeholder_warn:
            if QMessageBox.question(
                self, "Unfilled Template",
                "Some job sections still contain placeholder text.\n"
                "Continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            ) != QMessageBox.StandardButton.Yes:
                return

        self._start_batch(jobs)

    def _start_batch(self, jobs: list[str]):
        import datetime, os
        batch_id  = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        pdf_dir   = os.path.join(BATCH_PDF_DIR, batch_id)

        # Populate job list rows
        self.job_list.clear()
        self._results.clear()
        for idx, job in enumerate(jobs):
            label = _extract_job_label(job)
            item  = QListWidgetItem(f"  {_ICON_WAITING}  {label}")
            self.job_list.addItem(item)

        self.progress_bar.setMaximum(len(jobs))
        self.progress_bar.setValue(0)

        # Switch to progress page
        self._stack.setCurrentIndex(1)
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self._thread = BatchThread(
            provider=self._provider,
            api_key=self._api_key,
            base_latex=self._base_latex,
            jobs=jobs,
            batch_id=batch_id,
            pdf_dir=pdf_dir,
        )
        self._thread.job_started.connect(self._on_job_started)
        self._thread.job_status.connect(self._on_job_status)
        self._thread.job_done.connect(self._on_job_done)
        self._thread.all_done.connect(self._on_all_done)
        self._thread.start()

    # ── BatchThread signal handlers ───────────────────────────────────────────

    def _on_job_started(self, idx: int, label: str):
        item = self.job_list.item(idx)
        if item:
            item.setText(f"  {_ICON_RUNNING}  {label}  —  starting…")

    def _on_job_status(self, idx: int, status: str):
        item = self.job_list.item(idx)
        if item:
            # Keep the label, update the trailing status
            parts = item.text().split("  —  ", 1)
            base  = parts[0] if parts else item.text()
            item.setText(f"{base}  —  {status}")

    def _on_job_done(self, idx: int, success: bool, latex_or_error: str, pdf_path: str):
        self._results[idx] = (success, latex_or_error, pdf_path)

        item = self.job_list.item(idx)
        if item:
            parts  = item.text().split("  —  ", 1)
            # Strip the running icon, replace with result icon
            raw    = parts[0].strip()
            for icon in (_ICON_WAITING, _ICON_RUNNING, _ICON_OK, _ICON_FAIL):
                raw = raw.replace(icon, "").strip()
            icon   = _ICON_OK if success else _ICON_FAIL
            status = "Done ✓" if success else "Failed"
            item.setText(f"  {icon}  {raw}  —  {status}")

        done = sum(1 for (s, _, __) in self._results.values() if True)
        self.progress_bar.setValue(len(self._results))

    def _on_all_done(self):
        self.btn_stop.setEnabled(False)
        self.btn_run.setEnabled(True)

        total   = self.job_list.count()
        success = sum(1 for (s, _, __) in self._results.values() if s)
        failed  = total - success

        self.progress_bar.setFormat(f"Complete — {success}/{total} succeeded")
        if failed:
            self.progress_bar.setStyleSheet("QProgressBar::chunk { background: #e07b39; }")
        else:
            self.progress_bar.setStyleSheet("QProgressBar::chunk { background: #4caf50; }")

    def _on_job_row_changed(self, row: int):
        if row < 0 or row not in self._results:
            self.btn_load_result.setEnabled(False)
            return
        success, _, pdf_path = self._results[row]
        self.btn_load_result.setEnabled(success and bool(pdf_path))

    def _on_load_result_clicked(self):
        row = self.job_list.currentRow()
        if row < 0 or row not in self._results:
            return
        success, latex, pdf_path = self._results[row]
        if not success:
            return
        label = _extract_job_label(self._thread.jobs[row] if self._thread else "")
        if QMessageBox.question(
            self, "Load into Editor",
            f"Replace the current editor content with the result for:\n\n"
            f"{label}\n\n"
            "Unsaved changes will be overwritten.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        ) == QMessageBox.StandardButton.Yes:
            self.load_into_editor.emit(latex, pdf_path)
            self.accept()

    # ── Close / stop ──────────────────────────────────────────────────────────

    def _on_stop_clicked(self):
        if self._thread and self._thread.isRunning():
            self._thread.stop()
            self.btn_stop.setEnabled(False)
            self.progress_bar.setFormat("Stopping after current job…")

    def _on_close_clicked(self):
        if self._thread and self._thread.isRunning():
            if QMessageBox.question(
                self, "Batch Running",
                "A batch is still running. Stop it and close?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            ) != QMessageBox.StandardButton.Yes:
                return
            self._thread.stop()
        self.reject()

    def closeEvent(self, event):
        if self._thread and self._thread.isRunning():
            self._thread.stop()
        event.accept()


# ==========================================
# Main Application Window
# ==========================================
class TailorTeXApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TailorTeX - Resume Tailoring Tool")
        self.resize(1280, 720)

        Path(f"./{GEN_PDF_DIR}").mkdir(parents=True, exist_ok=True)

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
        self.btn_ai.clicked.connect(self.on_ai_clicked)

        self.btn_batch = QPushButton("📋 Batch Make")
        self.btn_batch.clicked.connect(self.on_batch_clicked)

        self.lbl_status = QLabel("Status: Ready")
        self.lbl_status.setStyleSheet("color: gray; font-weight: bold; margin-left: 15px;")

        for btn in [self.btn_compile, self.btn_templates, self.btn_snapshots,
                    self.btn_make_template, self.btn_ai, self.btn_batch]:
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
                    self.btn_templates, self.btn_snapshots,
                    self.btn_ai, self.btn_batch]:
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

    # --- AI Tailor ---

    def on_ai_clicked(self):
        """
        1. If no provider/key is configured, open settings first.
        2. Open the AI Tailor dialog.
        """
        provider = load_provider()
        api_key  = load_api_key(provider) if provider else ""

        if not provider or not api_key:
            settings = AISettingsDialog(self)
            if settings.exec() != QDialog.DialogCode.Accepted:
                return
            provider = settings.selected_provider()
            api_key  = load_api_key(provider)

        current_latex = self.editor.toPlainText()
        if not current_latex.strip():
            QMessageBox.warning(self, "Empty Editor",
                                "There is no LaTeX in the editor to tailor.")
            return

        dialog = AITailorDialog(
            current_latex=current_latex,
            provider=provider,
            api_key=api_key,
            pdf_dir=GEN_PDF_DIR,
            parent=self,
        )
        dialog.latex_ready.connect(self._on_ai_result)
        dialog.exec()

    def _on_ai_result(self, new_latex: str, pdf_filepath: str):
        """Called when the AI thread produced valid, compiled LaTeX."""
        self.editor.setPlainText(new_latex)
        self.update_status("Status: AI tailoring applied successfully!")

        # Save a snapshot of the AI-generated version
        timestamp = make_timestamp()
        try:
            save_snapshot(new_latex, timestamp)
        except Exception as e:
            self.update_status(f"Status: AI applied, but snapshot failed: {e}")

        # Show the compiled PDF in the right pane
        if pdf_filepath and Path(pdf_filepath).exists():
            self.pdf_document.load(pdf_filepath)
            self.pdf_view.setZoomFactor(self.current_zoom)

    def on_ai_settings_clicked(self):
        """Standalone settings entry — can be hooked to a menu item later."""
        AISettingsDialog(self).exec()

    # --- Batch Make ---

    def on_batch_clicked(self):
        """Open the Batch Make dialog."""
        provider = load_provider()
        api_key  = load_api_key(provider) if provider else ""

        if not provider or not api_key:
            settings = AISettingsDialog(self)
            if settings.exec() != QDialog.DialogCode.Accepted:
                return
            provider = settings.selected_provider()
            api_key  = load_api_key(provider)

        current_latex = self.editor.toPlainText()
        if not current_latex.strip():
            QMessageBox.warning(self, "Empty Editor",
                                "There is no LaTeX in the editor to use as the base document.")
            return

        dialog = BatchMakeDialog(
            base_latex=current_latex,
            provider=provider,
            api_key=api_key,
            parent=self,
        )
        dialog.load_into_editor.connect(self._on_batch_load_result)
        dialog.exec()

    def _on_batch_load_result(self, latex: str, pdf_path: str):
        """Load a batch result into the editor and PDF viewer."""
        self.editor.setPlainText(latex)
        self.update_status("Status: Batch result loaded into editor.")

        timestamp = make_timestamp()
        try:
            save_snapshot(latex, timestamp)
        except Exception as e:
            self.update_status(f"Status: Loaded, but snapshot failed: {e}")

        if pdf_path and Path(pdf_path).exists():
            self.pdf_document.load(pdf_path)
            self.pdf_view.setZoomFactor(self.current_zoom)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TailorTeXApp()
    window.show()
    sys.exit(app.exec())
