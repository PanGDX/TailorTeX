import os
import platform
import subprocess
import tempfile
import shutil

def check_and_install_tectonic() -> tuple[bool, str]:
    """
    Checks if `./tectonic` exists. If not, attempts to install it on Linux.
    Returns: (is_ready: bool, message: str)
    """
    executable_path = "./tectonic"
    
    # Check if Windows uses .exe
    if platform.system() == "Windows" and os.path.exists("tectonic.exe"):
        executable_path = "tectonic.exe"

    if os.path.exists(executable_path):
        return True, "Tectonic is ready."

    # If not found, check the OS
    if platform.system() == "Linux":
        print("Tectonic not detected. Attempting to download via drop-sh...")
        try:
            # Using shell=True here to support the pipe (|) operator in the curl command
            install_cmd = "curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net | sh"
            subprocess.run(
                install_cmd, 
                shell=True, 
                check=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE
            )
            
            # Verify it actually downloaded
            if os.path.exists("./tectonic"):
                return True, "Tectonic installed successfully."
            else:
                return False, "Installation script ran, but ./tectonic was not found."
                
        except subprocess.CalledProcessError as e:
            return False, f"Failed to install tectonic:\n{e.stderr.decode('utf-8', errors='ignore')}"
    else:
        return False, "Tectonic is not detected. Please install tectonic manually from https://tectonic-typesetting.github.io/ and place it in the project root."


def compile_latex_to_pdf(latex_code: str, output_pdf_path: str = "build.pdf") -> tuple[bool, str]:
    """
    Writes LaTeX code to a temporary file, compiles it, and copies the resulting PDF.
    Returns: (success: bool, message_or_error: str)
    """
    # 1. Ensure the compiler exists
    is_ready, msg = check_and_install_tectonic()
    if not is_ready:
        return False, msg

    # Resolve executable path
    executable = "tectonic.exe" if platform.system() == "Windows" and os.path.exists("tectonic.exe") else "./tectonic"

    # 2. Use a temporary directory to keep the workspace clean 
    # (Tectonic creates auxiliary files sometimes, this prevents clutter)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_tex_path = os.path.join(temp_dir, "document.tex")
        
        # Write editor content to a temporary .tex file
        try:
            with open(temp_tex_path, "w", encoding="utf-8") as f:
                f.write(latex_code)
        except Exception as e:
            return False, f"Failed to write temporary LaTeX file: {str(e)}"

        # 3. Call tectonic compiler via subprocess
        try:
            result = subprocess.run(
                [executable, temp_tex_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True # Decodes output to strings instead of bytes
            )

            # 4. Handle Results
            if result.returncode == 0:
                # Tectonic generates the PDF in the same directory as the input file
                temp_pdf_path = os.path.join(temp_dir, "document.pdf")
                
                if os.path.exists(temp_pdf_path):
                    shutil.copy(temp_pdf_path, output_pdf_path)
                    return True, f"Success! PDF saved to {output_pdf_path}"
                else:
                    return False, "Compilation succeeded, but the PDF could not be found."
            else:
                # Compilation failed: Catch standard output/errors
                error_msg = f"LaTeX Compilation Failed!\n\n--- Standard Output ---\n{result.stdout}\n\n--- Standard Error ---\n{result.stderr}"
                return False, error_msg

        except Exception as e:
            return False, f"An unexpected error occurred while executing Tectonic: {str(e)}"
