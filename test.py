# Source - https://stackoverflow.com/a/77284710
# Posted by Atlas, modified by community. See post 'Timeline' for change history
# Retrieved 2026-05-19, License - CC BY-SA 4.0

import time
import inspect
import dearpygui.dearpygui as dpg
dpg.create_context()

dpg_callback_queue = []


def msgbox():

    def on_msgbox_btn_click(sender, data, user_data):
        nonlocal resp
        resp = dpg.get_item_label(sender)
        dpg.hide_item(popup)
        # dpg.delete_item(popup)

    with dpg.popup(parent=dpg.last_item(), modal=True) as popup:
        dpg.add_text('goto step 2?')
        with dpg.group(horizontal=True):
            dpg.add_button(label='Yes', callback=on_msgbox_btn_click)
            dpg.add_button(label='No', callback=on_msgbox_btn_click)
    dpg.show_item(popup)

    resp = None
    while not resp:
        # print('waiting for response ...')
        # time.sleep(0.01)  # NOT needed
        handle_callbacks_and_render_one_frame()  # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<
    return resp


def on_btn_click(sender, data, user_data):
    print('do sth step 1 ...')
    resp = msgbox()
    if resp == 'Yes':
        print('do sth step 2 ...')
    print('done!')


def main():
    with dpg.window(tag='prim'):
        dpg.add_button(label='Submit', callback=on_btn_click)
    dpg.create_viewport(title='test msgbox', width=600, height=300)

    # start_dpg()
    dpg.setup_dearpygui()
    dpg.set_primary_window('prim', True)
    dpg.show_viewport()
    dpg.configure_app(manual_callback_management=True)
    while dpg.is_dearpygui_running():
        handle_callbacks_and_render_one_frame()
    dpg.destroy_context()


def run_callbacks():
    global dpg_callback_queue
    while dpg_callback_queue:
        job = dpg_callback_queue.pop(0)
        if job[0] is None:
            continue
        sig = inspect.signature(job[0])
        args = []
        for i in range(len(sig.parameters)):
            args.append(job[i+1])
        result = job[0](*args)


def handle_callbacks_and_render_one_frame():
    global dpg_callback_queue
    dpg_callback_queue += dpg.get_callback_queue() or []  # retrieves and clears queue
    # print(f'jobs: {jobs}')
    run_callbacks()
    dpg.render_dearpygui_frame()


if __name__ == '__main__':
    main()
