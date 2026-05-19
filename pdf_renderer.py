import pymupdf  # PyMuPDF
import numpy as np
import dearpygui.dearpygui as dpg
import traceback
# with tempfile.TemporaryDirectory() as temp_dir:
# Global state to track scaling
pdf_dimensions = {"width": 0, "height": 0}
current_zoom = 0.35  # Default zoom (so a massive 300DPI image fits on screen)

def render_pdf_to_texture(pdf_path: str) -> tuple[bool, str]:
    """Renders the compiled PDF to a DPG texture at 300 DPI."""
    try:
        doc = pymupdf.open(pdf_path)
        page = doc[0] # Grab the first page
        
        # Render PDF to a pixmap at 300 DPI with Alpha (RGBA)
        pix = page.get_pixmap(dpi=300, alpha=True)
        
        pdf_dimensions["width"] = pix.width
        pdf_dimensions["height"] = pix.height
        
        # SUPER FAST CONVERSION: bytearray -> numpy uint8 -> float32 -> normalize 0.0 to 1.0
        texture_data = np.frombuffer(pix.samples, dtype=np.uint8).astype(np.float32) / 255.0
        
        if dpg.does_item_exist("pdf_image_viewer"):
            dpg.delete_item("pdf_image_viewer")
        # DPG UI UPDATE: Textures with changing dimensions must be deleted and recreated
        if dpg.does_item_exist("pdf_texture_tag"):
            dpg.delete_item("pdf_texture_tag")
            
        if dpg.does_alias_exist("pdf_texture_tag"):
            dpg.remove_alias("pdf_texture_tag")

        
        dpg.add_dynamic_texture(
                width=pdf_dimensions["width"], 
                height=pdf_dimensions["height"], 
                default_value=texture_data, 
                tag="pdf_texture_tag",
                parent="tex_registry"
            )
            
        # Redraw the image on the screen
        update_image_viewer()
        return True, "PDF rendered successfully."
        
    except Exception as e:
        print(traceback.format_exception(e))
        return False, f"Failed to render PDF: {str(e)}"

def update_image_viewer():
    """Redraws the image widget based on the current zoom level."""
    if dpg.does_item_exist("pdf_image_viewer"):
        dpg.delete_item("pdf_image_viewer")
        
    scaled_width = int(pdf_dimensions["width"] * current_zoom)
    scaled_height = int(pdf_dimensions["height"] * current_zoom)
    
    # Re-add image to our container
    dpg.add_image(
        "pdf_texture_tag", 
        width=scaled_width, 
        height=scaled_height, 
        tag="pdf_image_viewer", 
        parent="pdf_viewer_container" # Requires a container tag in the GUI!
    )

def zoom_in(sender, app_data):
    global current_zoom
    current_zoom += 0.1
    update_image_viewer()

def zoom_out(sender, app_data):
    global current_zoom
    current_zoom = max(0.1, current_zoom - 0.1) # Prevent zooming to 0 or negative
    update_image_viewer()
