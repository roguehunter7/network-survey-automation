# main_app.py
import logging
import sys
import tkinter as tk
from tkinter import messagebox, ttk

# Local imports
from netsurvey import config
from netsurvey.gui import data_manager
from netsurvey.gui import ui_components
from netsurvey import utils

# --- Logging Setup ---
log_format = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)


class ConsolidatedSurveyApp:
    def __init__(self, root_window):
        self.root = root_window
        self.root.title(config.APP_TITLE)  # Gets title from config
        self.root.minsize(config.WINDOW_MIN_WIDTH, config.WINDOW_MIN_HEIGHT)

        # --- Initialize Core Components ---
        # Add basic error handling for DataManager init
        try:
            self.data_manager = data_manager.DataManager()
        except Exception as e:
            logging.exception("FATAL: Failed to initialize DataManager.")
            messagebox.showerror(
                "Initialization Error",
                f"Failed to initialize data manager: {e}\n\nCheck data files and permissions. Application cannot continue.",
            )
            self.root.destroy()
            return  # Stop initialization

        # --- State Variables ---
        self.current_location_data = None
        self.wave1_state = {"current": "initial"}

        # --- Tkinter Variables (Grouped Logically) ---
        self.location_vars = {
            "site": tk.StringVar(),
            "building": tk.StringVar(),
            "floor": tk.StringVar(),
            "wing": tk.StringVar(),
            "area": tk.StringVar(),
            "location_display": tk.StringVar(value="Location not set."),
        }
        self.log_other_device_vars = {
            "status_reason": tk.StringVar(value=config.DEFAULT_STATUS_REASON),
            "notes": tk.StringVar(),
            "rack_type": tk.StringVar(),
            "rack_type_other": tk.StringVar(),
            "make": tk.StringVar(),
            "model": tk.StringVar(),
            "sn": tk.StringVar(),
            "asset": tk.StringVar(),
            "total_ports": tk.StringVar(),
            "used_ports": tk.StringVar(),
            "failure_reason_detail": tk.StringVar(),
            "observed_ssid": tk.StringVar(),
            "mac_address": tk.StringVar(),
            "reported_moonid": tk.StringVar(),
            "observed_laptop_ip": tk.StringVar(),
            "autofilled_ip_range": tk.StringVar(value=config.DEFAULT_IP_RANGE_TEXT),
        }
        self.wave1_vars = {
            "connection_confirmed": tk.StringVar(value=""),
            "access_level": tk.StringVar(),
            "device_type": tk.StringVar(value=config.DEFAULT_DEVICE_TYPE),
            "final_sn": tk.StringVar(),
            "final_hostname": tk.StringVar(),
            "final_make": tk.StringVar(),
            "final_model": tk.StringVar(),
            "final_location_notes": tk.StringVar(),
            "rack_type": tk.StringVar(),
            "rack_type_other": tk.StringVar(),
            "is_poe_capable_gui": tk.StringVar(value=""),
            "lldp_cdp_operational_status": tk.StringVar(value=""),
            "wave1_detailed_neighbor_data_captured": tk.StringVar(value="No"),
        }
        self.wave2_vars = {
            "wave2_sn_entry": tk.StringVar(),
            "wave2_verified_sn": tk.StringVar(value="N/A"),
            "wave2_verified_hostname": tk.StringVar(value="N/A"),
            "wave2_verified_make_model": tk.StringVar(value="N/A"),
            "wave2_required_filename": tk.StringVar(value="N/A"),
            "wave2_tree_search_term": tk.StringVar(),
            "selected_sn": tk.StringVar(value="N/A"),
        }
        self.status_var = tk.StringVar(value="Initializing...")

        # --- Widget Dictionaries ---
        self.location_widgets = {}
        self.log_other_device_widgets = {}
        self.wave1_widgets = {}
        self.wave2_widgets = {}

        # --- Callback Dictionary ---
        self.callbacks = {
            "confirm_location_callback": self.handle_location_confirmed,
            "get_current_location": self.get_current_location,
            "update_status": self.update_status_bar,
            "show_copyable_message_callback": self._show_copyable_message_proxy,
            "wave1_update_ui_state_callback": self._wave1_update_state,
            "wave1_set_ui_state_callback": self._wave1_set_ui_state,
        }

        # --- Styling ---
        self.style = ttk.Style()
        try:
            if sys.platform == "win32":
                self.style.theme_use("vista")
            elif sys.platform == "darwin":
                self.style.theme_use("aqua")
            else:
                self.style.theme_use("clam")
        except tk.TclError:
            pass
        self._configure_styles()

        # --- Main Layout ---
        self.location_frame = ttk.LabelFrame(
            self.root, text="1. Set Current Survey Location", padding="10"
        )
        self.location_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(10, 5))
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(expand=True, fill="both", padx=10, pady=(0, 5))
        self.notebook = ttk.Notebook(self.main_frame)
        self.notebook.pack(expand=1, fill="both")

        self.tab_log_other_device = ttk.Frame(self.notebook, padding="10")
        self.tab_wave1 = ttk.Frame(self.notebook)
        self.tab_wave2 = ttk.Frame(self.notebook, padding="10")

        self.notebook.add(
            self.tab_log_other_device, text="Log Other Device", state=tk.DISABLED
        )
        self.notebook.add(self.tab_wave1, text="Wave 1 (Managed)", state=tk.DISABLED)
        self.notebook.add(
            self.tab_wave2, text="Wave 2 (Verify/Complete)", state=tk.DISABLED
        )

        status_bar = ttk.Label(
            self.root, textvariable=self.status_var, style="Status.TLabel"
        )
        status_bar.pack(side=tk.BOTTOM, fill=tk.X, padx=0, pady=0)

        # --- Create Widgets using ui_components ---
        self.location_widgets = ui_components.create_location_widgets(
            self.location_frame, self.location_vars, self.callbacks, self.data_manager
        )
        self.log_other_device_widgets = ui_components.create_log_other_device_widgets(
            self.tab_log_other_device,
            self.log_other_device_vars,
            self.callbacks,
            self.data_manager,
        )
        self._create_wave1_widgets_with_scrolling(self.tab_wave1)
        ui_components.create_wave1_widgets(
            self.wave1_widgets["content_frame"],  # Pass the scrollable content frame
            self.wave1_vars,
            self.wave1_widgets,
            self.callbacks,
            self.data_manager,
        )
        self.wave2_widgets = ui_components.create_wave2_checklist_widgets(
            self.tab_wave2,
            self.wave2_vars,
            self.wave2_widgets,
            self.callbacks,
            self.data_manager,
        )

        # --- Initial State & Bindings ---
        self._check_initial_data()
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)  # For Windows/Linux
        self.root.bind_all("<Button-4>", self._on_mousewheel)  # For Linux scroll up
        self.root.bind_all("<Button-5>", self._on_mousewheel)  # For Linux scroll down
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self._wave1_set_ui_state("initial")
        self.status_var.set("Set location to begin.")

    def _configure_styles(self):
        self.style.configure("Header.TLabel", font=("Helvetica", 11, "bold"))
        self.style.configure("Status.TLabel", relief=tk.__TK_MOONKEN__, anchor=tk.W, padding=3)
        self.style.configure("TButton", padding=5)
        self.style.configure("TLabelframe.Label", font=("Helvetica", 10, "bold"))
        self.style.configure("Instr.TLabel", foreground="blue", font=("Helvetica", 9))
        self.style.configure(
            "Accent.TLabel", foreground="darkred", font=("Helvetica", 9, "italic")
        )
        self.style.configure(
            "ReadOnly.TLabel", foreground="grey", font=("Helvetica", 9)
        )
        self.style.configure("Treeview.Heading", font=("Helvetica", 10, "bold"))

    def _check_initial_data(self):
        if not self.data_manager.lab_areas_data:
            self.status_var.set(
                f"FATAL: Lab areas data ('{config.LAB_AREAS_FILENAME}') missing or invalid."
            )
            messagebox.showerror(
                "Data Error",
                f"Could not load essential location data:\n{config.LAB_AREAS_FILENAME}\nApplication may not function correctly.",
            )
            if self.location_widgets.get("confirm_button"):
                self.location_widgets["confirm_button"].config(state=tk.DISABLED)
            site_combo = self.location_widgets.get("site_combo")
            if site_combo and site_combo.winfo_exists():
                site_combo.config(state="disabled")

    def _create_wave1_widgets_with_scrolling(self, parent_frame):
        # Create a canvas and a scrollbar for the Wave 1 tab
        self.wave1_widgets["canvas"] = tk.Canvas(
            parent_frame, borderwidth=0, highlightthickness=0
        )
        self.wave1_widgets["scrollbar"] = ttk.Scrollbar(
            parent_frame, orient="vertical", command=self.wave1_widgets["canvas"].yview
        )
        self.wave1_widgets["canvas"].configure(
            yscrollcommand=self.wave1_widgets["scrollbar"].set
        )

        self.wave1_widgets["scrollbar"].pack(side="right", fill="y")
        self.wave1_widgets["canvas"].pack(side="left", fill="both", expand=True)

        # This frame will contain all the Wave 1 widgets and will be scrolled
        self.wave1_widgets["content_frame"] = ttk.Frame(
            self.wave1_widgets["canvas"], padding="10"
        )
        self.wave1_widgets["canvas_window"] = self.wave1_widgets[
            "canvas"
        ].create_window((0, 0), window=self.wave1_widgets["content_frame"], anchor="nw")

        # Bind configure events
        self.wave1_widgets["content_frame"].bind(
            "<Configure>", self._on_wave1_frame_configure
        )
        self.wave1_widgets["canvas"].bind(
            "<Configure>", self._on_wave1_canvas_configure
        )

    def _on_wave1_frame_configure(self, event=None):
        # Update scroll region of canvas whenever the content_frame size changes
        canvas = self.wave1_widgets.get("canvas")
        if canvas and canvas.winfo_exists():  # Check if widget exists
            canvas.configure(scrollregion=canvas.bbox("all"))

    def _on_wave1_canvas_configure(self, event=None):
        # Update the width of the canvas window to match the canvas width
        canvas = self.wave1_widgets.get("canvas")
        canvas_window = self.wave1_widgets.get("canvas_window")
        if (
            canvas and canvas_window and event and canvas.winfo_exists()
        ):  # Check if widgets exist and event is valid
            canvas.itemconfig(canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        # Determine which canvas to scroll (currently only Wave 1 has its own canvas)
        target_canvas = None
        widget_under_cursor = self.root.winfo_containing(event.x_root, event.y_root)

        # Check if the scroll event is over the Wave 1 tab's canvas or its content
        wave1_canvas = self.wave1_widgets.get("canvas")
        if wave1_canvas and widget_under_cursor:
            current_widget = widget_under_cursor
            while current_widget is not None:
                if current_widget == wave1_canvas:
                    target_canvas = wave1_canvas
                    break
                # Check if the widget is a child of the Wave 1 content_frame
                if hasattr(
                    current_widget, "master"
                ) and current_widget.master == self.wave1_widgets.get("content_frame"):
                    target_canvas = wave1_canvas
                    break
                try:
                    if hasattr(current_widget, "master"):
                        current_widget = current_widget.master
                    else:
                        break  # Reached the top-level window or a non-master widget
                except tk.TclError:  # Widget might have been destroyed
                    break

        if not target_canvas:
            return  # Scroll event not over a relevant canvas

        delta = 0
        if sys.platform == "win32":  # Windows
            delta = -1 * int(event.delta / 120)
        elif event.num == 4:  # Linux scroll up
            delta = -1
        elif event.num == 5:  # Linux scroll down
            delta = 1
        elif sys.platform == "darwin":  # macOS
            delta = -1 * int(event.delta)  # macOS uses event.delta directly

        if delta != 0 and target_canvas.winfo_exists():
            target_canvas.yview_scroll(delta, "units")

    def _on_tab_changed(self, event):
        try:
            selected_tab_index = self.notebook.index(self.notebook.select())
            # Tab indices: 0=Log Other, 1=Wave 1, 2=Wave 2
            if selected_tab_index == 2:  # Wave 2 tab
                ui_components.handle_refresh_wave2_checklist(
                    self.wave2_vars,
                    self.wave2_widgets,
                    self.callbacks,
                    self.data_manager,
                )
        except tk.TclError:
            # This can happen if the notebook is being destroyed or tab doesn't exist
            logging.warning(
                "Error getting selected tab index, possibly during shutdown."
            )
        except Exception as e:
            logging.exception(f"Unexpected error during tab change: {e}")

    def handle_location_confirmed(self, location_data):
        self.current_location_data = location_data
        self.update_status_bar("Location set. Select tab to begin survey.")
        try:
            for i in range(self.notebook.index("end")):
                if self.notebook.tabs()[i]:  # Check if tab exists
                    self.notebook.tab(i, state=tk.NORMAL)
        except tk.TclError as e:
            logging.error(f"Error enabling notebook tabs: {e}")
        except Exception as e:
            logging.exception(f"Unexpected error enabling tabs: {e}")

    def update_status_bar(self, message):
        self.status_var.set(str(message))
        self.root.update_idletasks()

    def get_current_location(self):
        return self.current_location_data

    def _show_copyable_message_proxy(
        self, title, message, copyable_text_label, copyable_text
    ):
        if self.root and self.root.winfo_exists():
            utils.show_copyable_message(
                self.root, title, message, copyable_text_label, copyable_text
            )
        else:
            logging.error("Cannot show copyable message: Root window destroyed.")

    def _wave1_set_frame_state(self, frame_key, state=tk.NORMAL):
        frame = self.wave1_widgets.get(frame_key)
        if not frame or not frame.winfo_exists():
            return

        interactive_classes = (
            "TButton",
            "TEntry",
            "TCombobox",
            "TRadiobutton",
            "Button",  # Standard Tkinter widgets
            "Entry",
            "Combobox",
            "Radiobutton",
            "Checkbutton",
            "TCheckbutton",
        )
        for widget in frame.winfo_children():
            try:
                descendants = [widget]
                # If the widget is a frame itself, also iterate its children
                if isinstance(widget, (ttk.Frame, ttk.LabelFrame)):
                    descendants.extend(widget.winfo_children())

                for descendant in descendants:
                    if not descendant.winfo_exists():
                        continue
                    widget_class = descendant.winfo_class()
                    if widget_class in interactive_classes:
                        try:
                            descendant.configure(state=state)
                        except tk.TclError:
                            # Some widgets might not support state or might be misconfigured
                            pass
            except tk.TclError:
                # Widget might have been destroyed
                continue

    def _wave1_set_ui_state(self, state_name):
        self.wave1_state["current"] = state_name
        logging.debug(f"Setting Wave 1 UI state to: {state_name}")

        # Default states
        conn_state = tk.DISABLED
        cli_state = tk.DISABLED
        final_id_state = tk.DISABLED
        neighbor_state = tk.DISABLED
        save_btn_state = tk.DISABLED
        status_message = ""

        if state_name == "initial":
            conn_state = tk.NORMAL
            status_message = "Wave 1: Confirm connection status."
        elif state_name == "connection_confirmed_yes":
            conn_state = (
                tk.NORMAL
            )  # Connection frame remains active to select access/type
            status_message = "Wave 1: Select Access Level & Device Type."
        elif state_name == "connection_confirmed_no":
            # All Wave 1 input frames remain disabled
            status_message = "Connection failed. Use 'Log Other Device' tab."
        elif state_name == "access_selected":
            conn_state = tk.DISABLED  # Lock connection frame once access/type selected
            cli_state = tk.NORMAL
            status_message = (
                "Wave 1: Perform CLI Data Point Collection (then click button below)."
            )
        elif state_name == "cli_checks_done":
            conn_state = tk.DISABLED
            cli_state = tk.DISABLED  # Lock CLI checks frame
            final_id_state = tk.NORMAL
            neighbor_state = tk.NORMAL
            save_btn_state = tk.NORMAL
            status_message = "Wave 1: Enter final details & neighbor status, then Save."

        # Apply states to frames
        self._wave1_set_frame_state("frame_connection", conn_state)
        self._wave1_set_frame_state("frame_cli_checks", cli_state)
        self._wave1_set_frame_state("frame_final_id", final_id_state)
        self._wave1_set_frame_state(
            "frame_neighbor_status", neighbor_state
        )  # Neighbor status frame

        # Special handling for the save button (not in a sub-frame of its own)
        save_button = self.wave1_widgets.get("save_button")
        if save_button and save_button.winfo_exists():
            try:
                save_button.config(state=save_btn_state)
            except tk.TclError:
                pass

        # Ensure detailed neighbor UI is updated correctly based on its parent frame state
        detailed_neighbor_frame = self.wave1_widgets.get(
            "wave1_detailed_neighbor_frame"
        )
        if detailed_neighbor_frame and detailed_neighbor_frame.winfo_exists():
            # This frame's widgets' states are controlled by _handle_wave1_op_status_change,
            # but the frame itself should follow `neighbor_state`.
            # If neighbor_state is DISABLED, _handle_wave1_op_status_change will also disable its contents.
            ui_components._handle_wave1_op_status_change(  # Call to ensure consistency
                self.wave1_vars, self.wave1_widgets
            )

        self.update_status_bar(status_message)

    def _wave1_update_state(self, *args):
        conn_status = self.wave1_vars["connection_confirmed"].get()
        access_level = self.wave1_vars["access_level"].get()
        device_type = self.wave1_vars["device_type"].get()
        current_state = self.wave1_state.get("current")

        if conn_status == "True":
            if (
                access_level and device_type
            ):  # Both access level and device type are selected
                if current_state not in ("access_selected", "cli_checks_done"):
                    self._wave1_set_ui_state("access_selected")
            else:  # Connection confirmed, but access/type not yet fully selected
                if current_state != "connection_confirmed_yes":
                    self._wave1_set_ui_state("connection_confirmed_yes")
        elif conn_status == "False":
            if current_state != "connection_confirmed_no":
                messagebox.showwarning(
                    "Action Required",
                    "Connection failed.\nUse 'Log Other Device' tab (if unmanaged/AP/Hub).",
                )
                # Reset the Wave 1 form when connection is 'No'
                ui_components.handle_wave1_reset_form(
                    self.wave1_vars, self.wave1_widgets, self.callbacks
                )  # This will also set state to 'initial' via callback
                self._wave1_set_ui_state(
                    "connection_confirmed_no"
                )  # Explicitly set this for status bar
        else:  # Connection status is empty (initial state)
            if current_state != "initial":
                self._wave1_set_ui_state("initial")

    def on_close(self):
        if messagebox.askokcancel("Quit", "Quit survey helper application?"):
            logging.info("Application closing.")
            try:
                self.data_manager.save_wave2_completion_status()
                # self.data_manager.save_deferred_switches_status() # Removed
                logging.info("Saved Wave 2 statuses.")
            except Exception as e:
                logging.error(f"Error saving state on exit: {e}")
            self.root.destroy()

    def run(self):
        # Check if DataManager initialized successfully
        if not hasattr(self, "data_manager"):
            logging.error("Application initialization failed. Exiting.")
            return  # Prevent mainloop if DataManager failed

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.mainloop()


def main():
    """Launch the survey GUI."""
    logging.info(f"Starting {config.APP_TITLE}...")
    main_root = tk.Tk()
    app = ConsolidatedSurveyApp(main_root)
    app.run()
    logging.info("Application closed.")


if __name__ == "__main__":
    main()
