import dearpygui.dearpygui as dpg

# ==========================================
# 1. Dummy Callbacks (To be implemented later)
# ==========================================
def callback_compile(sender, app_data):
    print("Action: Trigger Compilation Thread")
    # Hint: We will implement Issue #2 (Threading/Compile) here

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
    dpg.create_context()

    # --- Setup Placeholder Texture for PDF ---
    # We create a simple light-gray blank image (800x1000) to act as our PDF placeholder
    tex_width, tex_height = 800, 1000
    # RGBA format: Light gray background
    texture_data = [0.9, 0.9, 0.9, 1.0] * (tex_width * tex_height) 

    with dpg.texture_registry(show=False):
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
                with dpg.child_window(border=False):
                    dpg.add_text("PDF Viewer", color=[150, 150, 150])
                    # To allow scrolling if the PDF is larger than the window, 
                    # we wrap the image in a child_window that allows scrolling.
                    with dpg.child_window(horizontal_scrollbar=True, width=-1, height=-1):
                        dpg.add_image("pdf_texture_tag", tag="pdf_image_viewer")

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
