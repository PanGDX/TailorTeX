import json
import shutil
from pathlib import Path

TEMPLATES_DIR = "templates"
TEMPLATES_PREVIEW_DIR = "templates/previews"
TEMPLATES_INDEX_FILE = "templates/index.json"

# -----------------------------------------------------------------------
# Default template source — written to disk once on first run by
# seed_default_templates().  Defined here so the file stays self-contained.
# -----------------------------------------------------------------------

_CLASSIC_RESUME = r"""\documentclass[11pt,a4paper]{article}
\usepackage[margin=2.5cm]{geometry}
\usepackage{enumitem}
\usepackage{titlesec}
\usepackage{hyperref}
\usepackage{parskip}

\titleformat{\section}{\large\bfseries}{}{0em}{}[\titlerule]
\titlespacing{\section}{0pt}{10pt}{4pt}

\begin{document}

% ---- Header ----
\begin{center}
    {\LARGE \textbf{Jane Doe}} \\[4pt]
    jane.doe@email.com \quad | \quad +1 (555) 000-0000 \quad | \quad
    \href{https://linkedin.com/in/janedoe}{linkedin.com/in/janedoe}
\end{center}

% ---- Summary ----
\section{Summary}
Results-driven software engineer with 5 years of experience building
scalable web applications. Strong communicator and collaborative team member.

% ---- Experience ----
\section{Experience}

\textbf{Senior Software Engineer} \hfill Jan 2021 -- Present \\
\textit{Acme Corp, San Francisco, CA}
\begin{itemize}[nosep, left=0pt]
    \item Led migration of monolithic service to microservices, reducing
          deploy time by 40\%.
    \item Mentored three junior engineers and ran bi-weekly code reviews.
\end{itemize}

\textbf{Software Engineer} \hfill Jun 2019 -- Dec 2020 \\
\textit{Startup Inc, Remote}
\begin{itemize}[nosep, left=0pt]
    \item Built REST APIs consumed by 50k daily active users.
    \item Implemented CI/CD pipeline using GitHub Actions and Docker.
\end{itemize}

% ---- Education ----
\section{Education}
\textbf{B.Sc. Computer Science} \hfill 2015 -- 2019 \\
University of Example, Example City

% ---- Skills ----
\section{Skills}
Python, Go, TypeScript, PostgreSQL, Docker, Kubernetes, AWS, Git

\end{document}
"""

_MODERN_RESUME = r"""\documentclass[10pt,a4paper]{article}
\usepackage[top=1.5cm, bottom=1.5cm, left=2cm, right=2cm]{geometry}
\usepackage{array}
\usepackage{xcolor}
\usepackage{titlesec}
\usepackage{enumitem}
\usepackage{hyperref}
\usepackage{tabularx}
\usepackage{parskip}

\definecolor{accent}{HTML}{2E4057}
\titleformat{\section}{\bfseries\color{accent}\large}{}{0em}{}[{\color{accent}\titlerule}]
\titlespacing{\section}{0pt}{8pt}{4pt}

\begin{document}
\pagestyle{empty}

% ---- Header ----
\begin{center}
    {\Huge \textbf{\color{accent}Alex Rivera}} \\[6pt]
    \small
    alex.rivera@email.com \quad $\bullet$ \quad +44 7700 000000 \quad $\bullet$ \quad
    \href{https://github.com/alexrivera}{github.com/alexrivera}
\end{center}

\vspace{4pt}

% ---- Profile ----
\section{Profile}
Creative product designer with 7 years of experience crafting user-centred
digital products. Proficient in end-to-end design processes from research
to high-fidelity prototyping and developer hand-off.

% ---- Experience ----
\section{Experience}

\noindent
\begin{tabularx}{\textwidth}{@{}X r@{}}
    \textbf{Lead Product Designer} --- \textit{DesignCo Ltd} & \textit{Mar 2020 -- Present}
\end{tabularx}
\begin{itemize}[nosep, left=12pt, topsep=2pt]
    \item Redesigned core onboarding flow, lifting 30-day retention by 18\%.
    \item Established a component library adopted across four product teams.
\end{itemize}

\vspace{4pt}

\noindent
\begin{tabularx}{\textwidth}{@{}X r@{}}
    \textbf{UX Designer} --- \textit{Agency XYZ} & \textit{Aug 2017 -- Feb 2020}
\end{tabularx}
\begin{itemize}[nosep, left=12pt, topsep=2pt]
    \item Delivered 20+ client projects spanning SaaS, e-commerce, and fintech.
    \item Ran user interviews and usability sessions with 200+ participants.
\end{itemize}

% ---- Education ----
\section{Education}

\noindent
\begin{tabularx}{\textwidth}{@{}X r@{}}
    \textbf{M.A. Interaction Design} --- University of Arts London & \textit{2015 -- 2017}
\end{tabularx}

% ---- Skills ----
\section{Skills}
Figma \quad Sketch \quad Adobe XD \quad HTML/CSS \quad User Research \quad
Prototyping \quad Design Systems \quad Accessibility (WCAG 2.1)

\end{document}
"""

_DEFAULTS = [
    {"name": "Classic Resume",  "source": _CLASSIC_RESUME},
    {"name": "Modern Resume",   "source": _MODERN_RESUME},
]

# -----------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------

def _ensure_dirs():
    Path(TEMPLATES_DIR).mkdir(parents=True, exist_ok=True)
    Path(TEMPLATES_PREVIEW_DIR).mkdir(parents=True, exist_ok=True)


def seed_default_templates() -> None:
    """
    Called once at app startup.  Writes default .tex files and index entries
    only if the index does not already contain an entry with that name —
    so re-running the app never duplicates them.
    """
    _ensure_dirs()
    index = load_index()
    existing_names = {e["name"] for e in index}
    changed = False

    for default in _DEFAULTS:
        if default["name"] in existing_names:
            continue

        slug = _name_to_slug(default["name"])
        tex_filepath = f"{TEMPLATES_DIR}/{slug}.tex"

        with open(tex_filepath, "w", encoding="utf-8") as f:
            f.write(default["source"])

        entry = {
            "name": default["name"],
            "tex_filepath": tex_filepath,
            # No preview PDF until the user compiles — handled gracefully by the dialog
            "pdf_filepath": f"{TEMPLATES_PREVIEW_DIR}/{slug}.pdf",
        }
        index.append(entry)
        changed = True

    if changed:
        _write_index(index)


def save_template(name: str, latex_code: str, compiled_pdf_filepath: str) -> dict:
    """
    Saves a new template from the editor.
    - Writes the .tex to templates/<slug>.tex
    - Copies the already-compiled PDF to templates/previews/<slug>.pdf
    - Appends (or updates) the index entry

    Raises ValueError if name is empty.
    Raises FileNotFoundError if compiled_pdf_filepath does not exist.
    """
    name = name.strip()
    if not name:
        raise ValueError("Template name must not be empty.")

    _ensure_dirs()

    compiled_pdf = Path(compiled_pdf_filepath)
    if not compiled_pdf.exists():
        raise FileNotFoundError(f"Compiled PDF not found: {compiled_pdf_filepath}")

    slug = _name_to_slug(name)
    tex_filepath = f"{TEMPLATES_DIR}/{slug}.tex"
    pdf_filepath = f"{TEMPLATES_PREVIEW_DIR}/{slug}.pdf"

    with open(tex_filepath, "w", encoding="utf-8") as f:
        f.write(latex_code)

    shutil.copy(compiled_pdf_filepath, pdf_filepath)

    index = load_index()
    # If a template with the same slug already exists, update it in-place
    for i, entry in enumerate(index):
        if entry.get("tex_filepath") == tex_filepath:
            index[i] = {"name": name, "tex_filepath": tex_filepath, "pdf_filepath": pdf_filepath}
            _write_index(index)
            return index[i]

    new_entry = {"name": name, "tex_filepath": tex_filepath, "pdf_filepath": pdf_filepath}
    index.append(new_entry)
    _write_index(index)
    return new_entry


def load_index() -> list[dict]:
    path = Path(TEMPLATES_INDEX_FILE)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def load_template_content(tex_filepath: str) -> str:
    with open(tex_filepath, "r", encoding="utf-8") as f:
        return f.read()


def delete_template(tex_filepath: str) -> None:
    """
    Removes the .tex, its preview PDF, and the index entry.
    Default templates can be deleted just like user-created ones.
    """
    tex_path = Path(tex_filepath)
    if tex_path.exists():
        tex_path.unlink()

    # Derive preview PDF path from index entry
    index = load_index()
    for entry in index:
        if entry["tex_filepath"] == tex_filepath:
            pdf_path = Path(entry.get("pdf_filepath", ""))
            if pdf_path.exists():
                pdf_path.unlink()
            break

    index = [e for e in index if e["tex_filepath"] != tex_filepath]
    _write_index(index)


# ---- Internal helpers ----

def _name_to_slug(name: str) -> str:
    """Converts a display name to a safe filename slug."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name).strip("_").lower()


def _write_index(index: list[dict]) -> None:
    _ensure_dirs()
    with open(TEMPLATES_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
