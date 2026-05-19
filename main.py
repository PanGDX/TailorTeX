import dearpygui.dearpygui as dpg
import threading
from compiler import compile_latex_to_pdf  # Import your new module
import datetime, os
from pathlib import Path
import pdf_renderer

GEN_PDF_DIR = "generated-pdfs"
LATEX_CODE_DIR = "latex-files"
TEMP_PNG_DIR = ".temp"

def get_filepath():
    now = datetime.datetime.now()
    filepath = f"{GEN_PDF_DIR}/{now.strftime('%Y-%m-%d %H-%M-%S')}"+".pdf"
    return filepath


def compile_thread(latex_code):
    dpg.set_value("status_text", " Status: Compiling (Please wait...)")
    
    pdf_filepath = get_filepath()
    success, message = compile_latex_to_pdf(latex_code, output_pdf_path=pdf_filepath)
    
    if success:
        dpg.set_value("status_text", " Status: Rendering PDF...")
        
        render_success, render_msg = pdf_renderer.render_pdf_to_texture(pdf_filepath)
        
        if render_success:
            dpg.set_value("status_text", " Status: Ready (Compile Success!)")
            dpg.configure_item("error_modal", show=False) 
        else:
            dpg.set_value("status_text", " Status: Render Failed!")
            # Show error modal for rendering failure
            print(render_msg) 
            dpg.set_value("error_modal_text", render_msg)
            dpg.configure_item("error_modal", show=True)

    else:
        print(message) 

        dpg.set_value("status_text", " Status: Compile Failed!")
        dpg.set_value("error_modal_text", message)
        dpg.configure_item("error_modal", show=True)
        # Pop up an error window or print to console so the user sees the LaTeX error

        

def callback_compile(sender, app_data):
    # Grab the current code from the DearPyGui text editor
    current_code = dpg.get_value("editor_text")
    
    # Spin up a background thread so the GUI does not freeze
    t = threading.Thread(target=compile_thread, args=(current_code,))
    t.start()

def callback_templates(sender, app_data):
    print("Action: Open Templates Modal")

def callback_snapshots(sender, app_data):
    print("Action: Open Snapshots Modal")

def callback_ai_tailor(sender, app_data):
    print("Action: Open AI Tailor Modal")

# ==========================================
# 2. Main GUI Setup
# ==========================================
def setup_gui():
    for dir in [GEN_PDF_DIR, LATEX_CODE_DIR, TEMP_PNG_DIR]:
        path = Path(f"./{dir}")
        path.mkdir(parents=True, exist_ok=True)

    dpg.create_context()

    # --- Setup Placeholder Texture for PDF ---
    # We create a simple light-gray blank image (800x1000) to act as our PDF placeholder
    tex_width, tex_height = 800, 1000
    # RGBA format: Light gray background
    texture_data = [0.9, 0.9, 0.9, 1.0] * (tex_width * tex_height) 

    with dpg.texture_registry(show=False, tag="tex_registry"):
        dpg.add_dynamic_texture(width=tex_width, height=tex_height, 
                                default_value=texture_data, tag="pdf_texture_tag")

    # --- Main Window ---
    with dpg.window(tag="PrimaryWindow"):
        
        # --- Toolbar ---
        with dpg.group(horizontal=True):
            dpg.add_button(label="⚙ Compile", callback=callback_compile, width=100, height=30)
            dpg.add_button(label="📄 Templates", callback=callback_templates, width=100, height=30)
            dpg.add_button(label="🕒 Snapshots", callback=callback_snapshots, width=100, height=30)
            dpg.add_button(label="✨ AI Tailor", callback=callback_ai_tailor, width=100, height=30)
            
            # Optional: A status text label to show what the app is doing
            dpg.add_text(" Status: Ready", tag="status_text")

        dpg.add_separator()

        # --- Split Screen Layout ---
        # Using a resizable table gives us a draggable divider between the two panes!
        with dpg.table(header_row=False, resizable=True, borders_innerV=True, height=-1):
            
            # Define 2 columns of equal initial width (50% / 50%)
            dpg.add_table_column(init_width_or_weight=0.5)
            dpg.add_table_column(init_width_or_weight=0.5)

            with dpg.table_row():
                
                # --- LEFT PANE: LaTeX Editor ---
                with dpg.child_window(border=False):
                    dpg.add_text("LaTeX Editor", color=[150, 150, 150])
                    # width=-1 and height=-1 forces the input to fill the parent child_window
                    dpg.add_input_text(
                        multiline=True, 
                        width=-1, 
                        height=-1, 
                        tag="editor_text",
                        default_value="% Write your LaTeX here...\n\\documentclass{article}\n\\begin{document}\n\nHello World!\n\n\\end{document}"
                    )

                # --- RIGHT PANE: PDF Viewer ---
                # --- RIGHT PANE: PDF Viewer ---
                with dpg.child_window(border=False):
                    
                    # Viewer Toolbar (Zooming)
                    with dpg.group(horizontal=True):
                        dpg.add_text("PDF Viewer", color=[150, 150, 150])
                        dpg.add_button(label="🔍 Zoom In", callback=lambda: pdf_renderer.zoom_in(None, None))
                        dpg.add_button(label="🔍 Zoom Out", callback=lambda: pdf_renderer.zoom_out(None, None))

                    # The container that allows scrolling (added tag="pdf_viewer_container")
                    with dpg.child_window(horizontal_scrollbar=True, width=-1, height=-1, tag="pdf_viewer_container"):
                        dpg.add_image("pdf_texture_tag", tag="pdf_image_viewer")


    with dpg.window(label="Compilation Error", modal=True, show=False, tag="error_modal", 
                    width=600, height=400, no_move=False):
        
        # We use a readonly multiline input_text instead of a standard text element.
        # This allows the user to scroll through long LaTeX errors and copy/paste them to Google/AI!
        dpg.add_input_text(multiline=True, readonly=True, tag="error_modal_text", 
                           width=-1, height=-40)
        
        # A button to close the popup
        dpg.add_button(label="Close", width=-1, 
                       callback=lambda: dpg.configure_item("error_modal", show=False))

    # ==========================================
    # 3. Viewport and OS Window Execution
    # ==========================================
    dpg.create_viewport(title='TailorTeX - Resume Tailoring Tool', width=1280, height=720)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    
    # Set the window we created as the primary full-screen window
    dpg.set_primary_window("PrimaryWindow", True)
    
    dpg.start_dearpygui()
    dpg.destroy_context()

if __name__ == "__main__":
    setup_gui()
