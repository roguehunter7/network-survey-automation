# ui_components.py
import datetime
import ipaddress  # For IP validation in handle_laptop_ip_pasted
import logging
import os  # Imported for os.path.abspath in handle_save_wave1_metadata
import tkinter as tk
from tkinter import font, messagebox, ttk

from netsurvey import config  # Assuming config.py contains constants
from netsurvey import utils  # Assuming utils.py contains helper functions

# --- Location Setup Section ---


def create_location_widgets(parent, vars_dict, callbacks_dict, data_manager):
    """Creates and grids the location setup widgets."""
    widgets = {}
    parent.columnconfigure(1, weight=1)
    parent.columnconfigure(3, weight=1)
    parent.columnconfigure(5, weight=1)

    ttk.Label(parent, text="Site:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
    widgets["site_combo"] = ttk.Combobox(
        parent, textvariable=vars_dict["site"], state="readonly", width=20
    )
    widgets["site_combo"].grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)
    widgets["site_combo"].bind(
        "<<ComboboxSelected>>",
        lambda event: handle_site_selected(
            vars_dict, widgets, callbacks_dict, data_manager
        ),
    )

    ttk.Label(parent, text="Wing:").grid(
        row=0, column=4, padx=(15, 5), pady=5, sticky=tk.W
    )
    widgets["wing_combo"] = ttk.Combobox(
        parent, textvariable=vars_dict["wing"], state="disabled", width=15
    )
    widgets["wing_combo"].grid(row=0, column=5, padx=5, pady=5, sticky=tk.EW)
    widgets["wing_combo"].bind(
        "<<ComboboxSelected>>",
        lambda event: handle_wing_selected(
            vars_dict, widgets, callbacks_dict, data_manager
        ),
    )

    ttk.Label(parent, text="Building:").grid(
        row=1, column=0, padx=5, pady=5, sticky=tk.W
    )
    widgets["building_combo"] = ttk.Combobox(
        parent, textvariable=vars_dict["building"], state="disabled", width=20
    )
    widgets["building_combo"].grid(row=1, column=1, padx=5, pady=5, sticky=tk.EW)
    widgets["building_combo"].bind(
        "<<ComboboxSelected>>",
        lambda event: handle_building_selected(
            vars_dict, widgets, callbacks_dict, data_manager
        ),
    )

    ttk.Label(parent, text="Area Name:").grid(
        row=1, column=4, padx=(15, 5), pady=5, sticky=tk.W
    )
    widgets["area_combo"] = ttk.Combobox(
        parent, textvariable=vars_dict["area"], state="disabled", width=30
    )
    widgets["area_combo"].grid(row=1, column=5, padx=5, pady=5, sticky=tk.EW)
    widgets["area_combo"].bind(
        "<<ComboboxSelected>>", lambda event: handle_area_selected(vars_dict, widgets)
    )

    ttk.Label(parent, text="Floor:").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
    widgets["floor_combo"] = ttk.Combobox(
        parent, textvariable=vars_dict["floor"], state="disabled", width=20
    )
    widgets["floor_combo"].grid(row=2, column=1, padx=5, pady=5, sticky=tk.EW)
    widgets["floor_combo"].bind(
        "<<ComboboxSelected>>",
        lambda event: handle_floor_selected(
            vars_dict, widgets, callbacks_dict, data_manager
        ),
    )

    widgets["confirm_button"] = ttk.Button(
        parent,
        text="Confirm Location & Start Session",
        command=lambda: handle_confirm_location(vars_dict, widgets, callbacks_dict),
        state=tk.DISABLED,
    )
    widgets["confirm_button"].grid(row=3, column=0, columnspan=6, pady=10)

    bold_font = font.Font(weight="bold")
    widgets["display_label"] = ttk.Label(
        parent, textvariable=vars_dict["location_display"], font=bold_font
    )
    widgets["display_label"].grid(
        row=4, column=0, columnspan=6, pady=(5, 0), sticky=tk.W
    )

    # Initial population
    sites = data_manager.get_sites()
    site_combo = widgets.get("site_combo")
    if site_combo and site_combo.winfo_exists():
        if sites:
            site_combo["values"] = sites
            site_combo.config(state="readonly")
        else:
            site_combo.set("[No Sites]")
            site_combo.config(state="disabled")
            messagebox.showerror("Config Error", "No Sites found in data file.")

    return widgets


def _reset_combobox(combobox_widget, string_var, state="disabled"):
    """Helper to reset location comboboxes."""
    string_var.set("")
    if combobox_widget and combobox_widget.winfo_exists():
        combobox_widget["values"] = []
        combobox_widget.config(state=state)


def handle_site_selected(vars_dict, widgets_dict, callbacks_dict, data_manager):
    site = vars_dict["site"].get()
    _reset_combobox(widgets_dict.get("building_combo"), vars_dict["building"])
    _reset_combobox(widgets_dict.get("floor_combo"), vars_dict["floor"])
    _reset_combobox(widgets_dict.get("wing_combo"), vars_dict["wing"])
    _reset_combobox(widgets_dict.get("area_combo"), vars_dict["area"])
    confirm_button = widgets_dict.get("confirm_button")
    if confirm_button and confirm_button.winfo_exists():
        confirm_button.config(state=tk.DISABLED)

    if site:
        buildings = data_manager.get_buildings(site)
        combo = widgets_dict.get("building_combo")
        if combo and combo.winfo_exists():
            if len(buildings) == 1:
                combo["values"] = buildings
                combo.current(0)
                combo.config(state="readonly")
                handle_building_selected(
                    vars_dict, widgets_dict, callbacks_dict, data_manager
                )
            elif len(buildings) > 1:
                combo["values"] = buildings
                combo.config(state="readonly")
            else:
                combo.set("[No Buildings]")
                combo.config(state="disabled")


def handle_building_selected(vars_dict, widgets_dict, callbacks_dict, data_manager):
    site = vars_dict["site"].get()
    building = vars_dict["building"].get()
    _reset_combobox(widgets_dict.get("floor_combo"), vars_dict["floor"])
    _reset_combobox(widgets_dict.get("wing_combo"), vars_dict["wing"])
    _reset_combobox(widgets_dict.get("area_combo"), vars_dict["area"])
    confirm_button = widgets_dict.get("confirm_button")
    if confirm_button and confirm_button.winfo_exists():
        confirm_button.config(state=tk.DISABLED)

    if site and building:
        floors = data_manager.get_floors(site, building)
        combo = widgets_dict.get("floor_combo")
        if combo and combo.winfo_exists():
            if len(floors) == 1:
                combo["values"] = floors
                combo.current(0)
                combo.config(state="readonly")
                handle_floor_selected(
                    vars_dict, widgets_dict, callbacks_dict, data_manager
                )
            elif len(floors) > 1:
                combo["values"] = floors
                combo.config(state="readonly")
            else:
                combo.set("[No Floors]")
                combo.config(state="disabled")


def handle_floor_selected(vars_dict, widgets_dict, callbacks_dict, data_manager):
    site = vars_dict["site"].get()
    building = vars_dict["building"].get()
    floor = vars_dict["floor"].get()
    _reset_combobox(widgets_dict.get("wing_combo"), vars_dict["wing"])
    _reset_combobox(widgets_dict.get("area_combo"), vars_dict["area"])
    confirm_button = widgets_dict.get("confirm_button")
    if confirm_button and confirm_button.winfo_exists():
        confirm_button.config(state=tk.DISABLED)

    if site and building and floor:
        wings = data_manager.get_wings(site, building, floor)
        combo = widgets_dict.get("wing_combo")
        if combo and combo.winfo_exists():
            if len(wings) == 1:
                combo["values"] = wings
                combo.current(0)
                combo.config(state="readonly")
                handle_wing_selected(
                    vars_dict, widgets_dict, callbacks_dict, data_manager
                )
            elif len(wings) > 1:
                combo["values"] = wings
                combo.config(state="readonly")
            else:  # No specific wings, but area exists for this S/B/F
                combo.set("N/A")  # Default to N/A if no specific wings found
                combo.config(state="readonly")  # Allow selection of N/A
                handle_wing_selected(
                    vars_dict, widgets_dict, callbacks_dict, data_manager
                )


def handle_wing_selected(vars_dict, widgets_dict, callbacks_dict, data_manager):
    site = vars_dict["site"].get()
    building = vars_dict["building"].get()
    floor = vars_dict["floor"].get()
    wing = vars_dict["wing"].get()  # This is the display value ("N/A" or actual)
    _reset_combobox(widgets_dict.get("area_combo"), vars_dict["area"])
    confirm_button = widgets_dict.get("confirm_button")
    if confirm_button and confirm_button.winfo_exists():
        confirm_button.config(state=tk.DISABLED)

    if site and building and floor:  # Wing is now set (could be "N/A")
        areas = data_manager.get_areas(site, building, floor, wing)
        combo = widgets_dict.get("area_combo")
        if combo and combo.winfo_exists():
            if len(areas) == 1:
                combo["values"] = areas
                combo.current(0)
                combo.config(state="readonly")
                handle_area_selected(vars_dict, widgets_dict)
            elif len(areas) > 1:
                combo["values"] = areas
                combo.config(state="readonly")
            else:
                combo.set("[No Areas]")
                combo.config(state="disabled")


def handle_area_selected(vars_dict, widgets_dict):
    area = vars_dict["area"].get()
    confirm_button = widgets_dict.get("confirm_button")
    if confirm_button and confirm_button.winfo_exists():
        is_enabled = area and area != "[No Areas]"
        confirm_button.config(state=tk.NORMAL if is_enabled else tk.DISABLED)


def handle_confirm_location(vars_dict, widgets_dict, callbacks_dict):
    site = vars_dict["site"].get()
    building = vars_dict["building"].get()
    floor = vars_dict["floor"].get()
    wing = vars_dict[
        "wing"
    ].get()  # This is the display value ("N/A" or actual wing name)
    area = vars_dict["area"].get()

    if not all([site, building, floor, area]) or area == "[No Areas]":
        messagebox.showerror(
            "Input Error", "Select valid Site, Building, Floor, and Area."
        )
        return

    # For internal data storage, "N/A" wing should be an empty string or consistent null placeholder
    actual_wing_for_data = "" if wing == "N/A" else wing

    location_data = {
        "site": site,
        "building": building,
        "floor": floor,
        "wing": actual_wing_for_data,  # Stored wing value
        "area_name": area,
    }

    logging.info(f"Location confirmed: {location_data}")
    display_wing_text = wing if wing else "N/A"  # For display label, use what user saw
    display_text = (
        f"Location Set: {site} | {building} | {floor} | {display_wing_text} | {area}"
    )
    vars_dict["location_display"].set(display_text)

    if "confirm_location_callback" in callbacks_dict:
        callbacks_dict["confirm_location_callback"](location_data)

    for widget_key in widgets_dict:
        widget = widgets_dict.get(widget_key)
        try:
            if widget and widget.winfo_exists():
                if widget.winfo_class() in ("TCombobox", "TButton"):
                    widget.config(state=tk.DISABLED)
        except tk.TclError:
            pass


# --- Log Other Device Section ---


def handle_rack_type_selected(vars_dict, widgets_dict, frame_key_prefix=""):
    rack_type_var_key = "rack_type"
    rack_type_other_var_key = "rack_type_other"

    selected_type = vars_dict[rack_type_var_key].get()
    other_label = widgets_dict.get(f"{frame_key_prefix}rack_other_label")
    other_entry = widgets_dict.get(f"{frame_key_prefix}rack_other_entry")

    is_other = selected_type == "Other"

    if other_label and other_label.winfo_exists():
        other_label.grid() if is_other else other_label.grid_remove()
    if other_entry and other_entry.winfo_exists():
        other_entry.grid() if is_other else other_entry.grid_remove()
        if is_other:
            other_entry.focus_set()

    if not is_other:
        if rack_type_other_var_key in vars_dict:
            vars_dict[rack_type_other_var_key].set("")


def create_log_other_device_widgets(
    parent_frame, vars_dict, callbacks_dict, data_manager
):
    widgets = {}
    parent_frame.columnconfigure(1, weight=1)
    parent_frame.columnconfigure(3, weight=1)
    current_row = 0

    ttk.Label(parent_frame, text="Device Type/Status:").grid(
        row=current_row, column=0, padx=5, pady=5, sticky=tk.W
    )
    status_options = [
        "Access Point (Observed)",
        "Unmanaged (No CLI)",
        "Hub (Observed)",
        "Failed Access (No Response)",
        "Failed Access (Creds Unknown)",
        "Failed Access (Port Damaged)",
        "Failed Access (Garbled Text)",
        "Other (See Notes)",
    ]
    widgets["status_combo"] = ttk.Combobox(
        parent_frame,
        textvariable=vars_dict["status_reason"],
        values=status_options,
        state="readonly",
        width=35,
    )
    widgets["status_combo"].grid(
        row=current_row, column=1, columnspan=3, padx=5, pady=5, sticky=tk.W
    )
    try:
        widgets["status_combo"].set(config.DEFAULT_STATUS_REASON)
    except tk.TclError:  # Fallback if value not in list, though it should be
        widgets["status_combo"].current(0)
    widgets["status_combo"].bind(
        "<<ComboboxSelected>>",
        lambda event: handle_log_other_status_changed(vars_dict, widgets),
    )
    current_row += 1

    ttk.Label(parent_frame, text="Specific Location Notes:").grid(
        row=current_row, column=0, padx=5, pady=5, sticky=tk.W
    )
    widgets["notes_entry"] = ttk.Entry(
        parent_frame, textvariable=vars_dict["notes"], width=60
    )
    widgets["notes_entry"].grid(
        row=current_row, column=1, columnspan=3, padx=5, pady=5, sticky=tk.EW
    )
    current_row += 1

    ttk.Label(parent_frame, text="Rack Type:").grid(
        row=current_row, column=0, padx=5, pady=5, sticky=tk.W
    )
    rack_options = [
        "",
        "Network",
        "Server",
        "Mini",
        "Ceiling",
        "Floor",
        "Wall",
        "Door",
        "Other",
    ]
    widgets["log_other_rack_type_combo"] = ttk.Combobox(
        parent_frame,
        textvariable=vars_dict["rack_type"],
        values=rack_options,
        state="readonly",
        width=15,
    )
    widgets["log_other_rack_type_combo"].grid(
        row=current_row, column=1, padx=5, pady=5, sticky=tk.W
    )
    widgets["log_other_rack_type_combo"].bind(
        "<<ComboboxSelected>>",
        lambda event: handle_rack_type_selected(
            vars_dict, widgets, frame_key_prefix="log_other_"
        ),
    )

    widgets["log_other_rack_other_label"] = ttk.Label(
        parent_frame, text="Other Rack Detail:"
    )
    widgets["log_other_rack_other_label"].grid(
        row=current_row, column=2, padx=(10, 5), pady=5, sticky=tk.W
    )
    widgets["log_other_rack_other_entry"] = ttk.Entry(
        parent_frame, textvariable=vars_dict["rack_type_other"], width=30
    )
    widgets["log_other_rack_other_entry"].grid(
        row=current_row, column=3, padx=5, pady=5, sticky=tk.W
    )
    current_row += 1

    ttk.Label(
        parent_frame, text="--- Reported Details ---", style="Header.TLabel"
    ).grid(row=current_row, column=0, columnspan=4, padx=5, pady=(10, 5), sticky=tk.W)
    current_row += 1

    ttk.Label(parent_frame, text="Make/Vendor:").grid(
        row=current_row, column=0, padx=5, pady=5, sticky=tk.W
    )
    widgets["make_entry"] = ttk.Entry(
        parent_frame, textvariable=vars_dict["make"], width=30
    )
    widgets["make_entry"].grid(row=current_row, column=1, padx=5, pady=5, sticky=tk.W)
    ttk.Label(parent_frame, text="Model:").grid(
        row=current_row, column=2, padx=5, pady=5, sticky=tk.W
    )
    widgets["model_entry"] = ttk.Entry(
        parent_frame, textvariable=vars_dict["model"], width=30
    )
    widgets["model_entry"].grid(row=current_row, column=3, padx=5, pady=5, sticky=tk.W)
    current_row += 1

    ttk.Label(parent_frame, text="Serial Number:").grid(
        row=current_row, column=0, padx=5, pady=5, sticky=tk.W
    )
    widgets["sn_entry"] = ttk.Entry(
        parent_frame, textvariable=vars_dict["sn"], width=30
    )
    widgets["sn_entry"].grid(row=current_row, column=1, padx=5, pady=5, sticky=tk.W)
    ttk.Label(parent_frame, text="Asset Tag:").grid(
        row=current_row, column=2, padx=5, pady=5, sticky=tk.W
    )
    widgets["asset_entry"] = ttk.Entry(
        parent_frame, textvariable=vars_dict["asset"], width=30
    )
    widgets["asset_entry"].grid(row=current_row, column=3, padx=5, pady=5, sticky=tk.W)
    current_row += 1

    ttk.Label(parent_frame, text="Observed Laptop IP:").grid(
        row=current_row, column=0, padx=5, pady=5, sticky=tk.W
    )
    widgets["laptop_ip_entry"] = ttk.Entry(
        parent_frame, textvariable=vars_dict["observed_laptop_ip"], width=30
    )
    widgets["laptop_ip_entry"].grid(
        row=current_row, column=1, padx=5, pady=5, sticky=tk.W
    )

    def _laptop_ip_lookup_wrapper(event=None):
        handle_laptop_ip_pasted(
            vars_dict, widgets, callbacks_dict, data_manager, parent_frame
        )

    widgets["laptop_ip_entry"].bind("<FocusOut>", _laptop_ip_lookup_wrapper)
    widgets["laptop_ip_entry"].bind("<Return>", _laptop_ip_lookup_wrapper)

    ttk.Label(parent_frame, text="Reported MOONID:").grid(
        row=current_row, column=2, padx=5, pady=5, sticky=tk.W
    )
    widgets["moonid_entry"] = ttk.Entry(
        parent_frame, textvariable=vars_dict["reported_moonid"], width=30
    )
    widgets["moonid_entry"].grid(row=current_row, column=3, padx=5, pady=5, sticky=tk.W)

    def _moonid_lookup_wrapper(event=None):
        handle_lookup_moonid_ip_range(vars_dict, data_manager)

    widgets["moonid_entry"].bind("<FocusOut>", _moonid_lookup_wrapper)
    widgets["moonid_entry"].bind("<Return>", _moonid_lookup_wrapper)
    current_row += 1

    ttk.Label(parent_frame, text="Data IP Range (for MOONID):").grid(
        row=current_row, column=0, padx=5, pady=2, sticky=tk.W
    )
    widgets["autofill_ip_label"] = ttk.Label(
        parent_frame,
        textvariable=vars_dict["autofilled_ip_range"],
        style="ReadOnly.TLabel",
        width=50,
        anchor=tk.W,
    )
    widgets["autofill_ip_label"].grid(
        row=current_row, column=1, columnspan=3, padx=5, pady=2, sticky=tk.EW
    )
    current_row += 1

    conditional_row = current_row
    widgets["ssid_label"] = ttk.Label(parent_frame, text="Observed SSID:")
    widgets["ssid_entry"] = ttk.Entry(
        parent_frame, textvariable=vars_dict["observed_ssid"], width=30
    )
    widgets["mac_label"] = ttk.Label(parent_frame, text="MAC Address:")
    widgets["mac_entry"] = ttk.Entry(
        parent_frame, textvariable=vars_dict["mac_address"], width=30
    )
    widgets["failure_label"] = ttk.Label(parent_frame, text="Failure Reason Detail:")
    widgets["failure_entry"] = ttk.Entry(
        parent_frame, textvariable=vars_dict["failure_reason_detail"], width=60
    )
    widgets["ssid_label"].grid(
        row=conditional_row, column=0, padx=5, pady=5, sticky=tk.W
    )
    widgets["ssid_entry"].grid(
        row=conditional_row, column=1, padx=5, pady=5, sticky=tk.W
    )
    widgets["mac_label"].grid(
        row=conditional_row, column=2, padx=5, pady=5, sticky=tk.W
    )
    widgets["mac_entry"].grid(
        row=conditional_row, column=3, padx=5, pady=5, sticky=tk.W
    )
    widgets["failure_label"].grid(
        row=conditional_row + 1, column=0, padx=5, pady=5, sticky=tk.W
    )
    widgets["failure_entry"].grid(
        row=conditional_row + 1, column=1, columnspan=3, padx=5, pady=5, sticky=tk.EW
    )
    current_row += 2

    ttk.Label(parent_frame, text="--- Port Counts ---", style="Header.TLabel").grid(
        row=current_row, column=0, columnspan=4, padx=5, pady=(15, 5), sticky=tk.W
    )
    current_row += 1

    vcmd_int = parent_frame.register(utils.validate_int_input)
    ttk.Label(parent_frame, text="Total Ports:").grid(
        row=current_row, column=0, padx=5, pady=5, sticky=tk.W
    )
    widgets["total_ports_entry"] = ttk.Entry(
        parent_frame,
        textvariable=vars_dict["total_ports"],
        width=10,
        validate="key",
        validatecommand=(vcmd_int, "%P"),
    )
    widgets["total_ports_entry"].grid(
        row=current_row, column=1, padx=5, pady=5, sticky=tk.W
    )
    ttk.Label(parent_frame, text="Used Ports:").grid(
        row=current_row, column=2, padx=5, pady=5, sticky=tk.W
    )
    widgets["used_ports_entry"] = ttk.Entry(
        parent_frame,
        textvariable=vars_dict["used_ports"],
        width=10,
        validate="key",
        validatecommand=(vcmd_int, "%P"),
    )
    widgets["used_ports_entry"].grid(
        row=current_row, column=3, padx=5, pady=5, sticky=tk.W
    )
    current_row += 1

    widgets["save_button"] = ttk.Button(
        parent_frame,
        text="Save Device Log Entry",
        command=lambda: handle_save_log_other_device(
            vars_dict, callbacks_dict, data_manager, widgets
        ),
    )
    widgets["save_button"].grid(row=current_row, column=0, columnspan=4, pady=15)

    parent_frame.update_idletasks()
    handle_log_other_status_changed(vars_dict, widgets)
    handle_rack_type_selected(vars_dict, widgets, frame_key_prefix="log_other_")

    return widgets


def handle_log_other_status_changed(vars_dict, widgets_dict):
    status = vars_dict["status_reason"].get()
    is_ap = status == "Access Point (Observed)"
    is_failed_access = "Failed Access" in status

    for key in ["ssid_label", "ssid_entry", "mac_label", "mac_entry"]:
        w = widgets_dict.get(key)
        if w and w.winfo_exists():
            w.grid() if is_ap else w.grid_remove()
            if not is_ap:
                if key == "ssid_entry" and "observed_ssid" in vars_dict:
                    vars_dict["observed_ssid"].set("")
                if key == "mac_entry" and "mac_address" in vars_dict:
                    vars_dict["mac_address"].set("")

    for key in ["failure_label", "failure_entry"]:
        w = widgets_dict.get(key)
        if w and w.winfo_exists():
            w.grid() if is_failed_access else w.grid_remove()
            if (
                not is_failed_access
                and key == "failure_entry"
                and "failure_reason_detail" in vars_dict
            ):
                vars_dict["failure_reason_detail"].set("")


def handle_lookup_moonid_ip_range(vars_dict, data_manager):
    moonid = vars_dict["reported_moonid"].get().strip().upper()
    ip_range = data_manager.lookup_moonid_ip_range(moonid)
    vars_dict["autofilled_ip_range"].set(ip_range)


def handle_laptop_ip_pasted(
    vars_dict, widgets_dict, callbacks_dict, data_manager, parent_frame
):
    """Handles autofilling MOONID based on the Observed Laptop IP."""
    laptop_ip_str = vars_dict["observed_laptop_ip"].get().strip()
    update_status_cb = callbacks_dict.get("update_status")

    if not laptop_ip_str:
        return

    try:
        ipaddress.ip_address(laptop_ip_str)  # Validate IP format
    except ValueError:
        if update_status_cb:
            update_status_cb(f"Invalid IP Address format: {laptop_ip_str}")
        messagebox.showwarning(
            "Invalid IP",
            f"The entered IP address '{laptop_ip_str}' is not valid.",
            parent=parent_frame.winfo_toplevel(),
        )
        vars_dict["autofilled_ip_range"].set(
            "Invalid IP for MOONID lookup"
        )  # Update range text
        return

    matching_moonids_info = data_manager.lookup_moonids_by_ip(laptop_ip_str)

    if not matching_moonids_info:
        vars_dict["autofilled_ip_range"].set("No MOONID match for this IP")
        if update_status_cb:
            update_status_cb(f"No MOONID found for IP {laptop_ip_str}")
    elif len(matching_moonids_info) == 1:
        moonid_info = matching_moonids_info[0]
        vars_dict["reported_moonid"].set(moonid_info["moonid"])
        handle_lookup_moonid_ip_range(
            vars_dict, data_manager
        )  # This updates autofilled_ip_range
        if update_status_cb:
            update_status_cb(
                f"Autofilled MOONID {moonid_info['moonid']} for IP {laptop_ip_str}"
            )
    else:  # Multiple matches
        first_moonid = matching_moonids_info[0]["moonid"]
        vars_dict["reported_moonid"].set(first_moonid)
        handle_lookup_moonid_ip_range(vars_dict, data_manager)
        current_range_text = vars_dict["autofilled_ip_range"].get()
        vars_dict["autofilled_ip_range"].set(
            f"{current_range_text} (Multiple MOONIDs match IP)"
        )

        dialog_title = "Multiple MOONIDs Found"
        dialog_message = (
            f"The IP address {laptop_ip_str} falls into ranges defined for multiple MOONIDs.\n"
            f"The first match ({first_moonid}) has been auto-filled. Review the list and update if needed:"
        )

        utils.show_multiple_moonid_matches_dialog(
            parent_frame.winfo_toplevel(),
            dialog_title,
            dialog_message,
            matching_moonids_info,
        )
        if update_status_cb:
            update_status_cb(
                f"Multiple MOONIDs found for IP {laptop_ip_str}. '{first_moonid}' autofilled. See details."
            )


def handle_save_log_other_device(vars_dict, callbacks_dict, data_manager, widgets_dict):
    update_status = callbacks_dict.get("update_status")
    get_current_location = callbacks_dict.get("get_current_location")

    if not get_current_location:
        messagebox.showerror("Error", "Cannot get current location.")
        return
    current_location = get_current_location()
    if not current_location:
        messagebox.showerror("Error", "Location not set.")
        return
    status_reason = vars_dict["status_reason"].get()
    if not status_reason:
        messagebox.showerror("Input Error", "Status/Reason is required.")
        return

    notes = vars_dict["notes"].get().strip()
    make = vars_dict["make"].get().strip()
    model = vars_dict["model"].get().strip()
    sn = vars_dict["sn"].get().strip()
    asset = vars_dict["asset"].get().strip()
    total_ports_str = vars_dict["total_ports"].get().strip()
    used_ports_str = vars_dict["used_ports"].get().strip()
    reported_moonid = vars_dict["reported_moonid"].get().strip().upper()
    observed_laptop_ip = vars_dict["observed_laptop_ip"].get().strip()
    rack_type = vars_dict["rack_type"].get()
    rack_other = vars_dict["rack_type_other"].get().strip()
    final_rack_detail = ""
    if rack_type == "Other":
        final_rack_detail = rack_other if rack_other else "Other - Not Specified"
    elif rack_type:
        final_rack_detail = rack_type

    failure_reason = (
        vars_dict["failure_reason_detail"].get().strip()
        if "Failed Access" in status_reason
        else ""
    )
    observed_ssid = (
        vars_dict["observed_ssid"].get().strip()
        if status_reason == "Access Point (Observed)"
        else ""
    )
    mac_address = (
        vars_dict["mac_address"].get().strip().upper()
        if status_reason == "Access Point (Observed)"
        else ""
    )

    total_ports, used_ports = None, None
    try:
        if total_ports_str:
            total_ports = int(total_ports_str)
        if used_ports_str:
            used_ports = int(used_ports_str)
        if (
            total_ports is not None
            and used_ports is not None
            and used_ports > total_ports
        ):
            messagebox.showerror(
                "Input Error", "Used Ports cannot be greater than Total Ports."
            )
            return
    except ValueError:
        messagebox.showerror("Input Error", "Port counts must be numbers.")
        return

    timestamp = datetime.datetime.now().isoformat(sep=" ", timespec="seconds")
    log_entry = {
        "Timestamp": timestamp,
        "StatusReason": status_reason,
        "Site": current_location.get("site", ""),
        "Building": current_location.get("building", ""),
        "Floor": current_location.get("floor", ""),
        "Wing": current_location.get(
            "wing", ""
        ),  # Stored wing value (empty string for N/A)
        "AreaName": current_location.get("area_name", ""),
        "SpecificLocationNotes": notes or "N/A",
        "RackTypeDetail": final_rack_detail or "N/A",
        "ReportedMake": make or "Unknown",
        "ReportedModel": model or "Unknown",
        "ReportedSerialNumber": sn or "Unknown",
        "ReportedAssetTag": asset or "Unknown",
        "ReportedMOONID": reported_moonid or "",
        "ObservedLaptopIP": observed_laptop_ip or "",
        "FailureReason": failure_reason or "N/A",
        "ObservedSSID": observed_ssid or "",
        "MACAddress": mac_address or "",
        "ReportedTotalPorts": total_ports_str or "",
        "ReportedUsedPorts": used_ports_str or "",
    }

    loc = current_location
    safe_fname_base = utils.generate_safe_filename(
        loc.get("site"), loc.get("building"), loc.get("floor"), loc.get("area_name")
    )
    target_filename = f"{safe_fname_base}_other_devices.json"
    success, message = data_manager.save_other_device_log_entry(
        log_entry, target_filename
    )

    if success:
        messagebox.showinfo("Success", message)
        if update_status:
            update_status("Device entry saved.")
        for key, var in vars_dict.items():
            if key not in [
                "status_reason",
                "autofilled_ip_range",
                "rack_type",  # Keep rack_type selection
            ]:  # Vars to clear
                var.set("")
        # Explicitly clear rack_type_other if not "Other"
        if vars_dict["rack_type"].get() != "Other":
            vars_dict["rack_type_other"].set("")

        vars_dict["autofilled_ip_range"].set(config.DEFAULT_IP_RANGE_TEXT)
        vars_dict["status_reason"].set(
            config.DEFAULT_STATUS_REASON  # Reset to default after save
        )
        handle_log_other_status_changed(vars_dict, widgets_dict)
        # Rack type visibility update already handled by status_reason change if needed
    else:
        messagebox.showerror("Error", message)
        if update_status:
            update_status("Error saving log.")


# --- Wave 1 (Managed Device) Section ---


def _handle_wave1_op_status_change(vars_dict, widgets_dict):
    op_status = vars_dict["lldp_cdp_operational_status"].get()
    detail_frame = widgets_dict.get("wave1_detailed_neighbor_frame")
    yes_radio = widgets_dict.get("wave1_detailed_neighbor_data_captured_yes_radio")
    no_radio = widgets_dict.get("wave1_detailed_neighbor_data_captured_no_radio")

    if op_status == "Operational":
        if detail_frame and detail_frame.winfo_exists():
            detail_frame.grid()
        if yes_radio and yes_radio.winfo_exists():
            yes_radio.config(state=tk.NORMAL)
        if no_radio and no_radio.winfo_exists():
            no_radio.config(state=tk.NORMAL)
    else:
        if detail_frame and detail_frame.winfo_exists():
            detail_frame.grid_remove()
        if yes_radio and yes_radio.winfo_exists():
            yes_radio.config(state=tk.DISABLED)
        if no_radio and no_radio.winfo_exists():
            no_radio.config(state=tk.DISABLED)
        if "wave1_detailed_neighbor_data_captured" in vars_dict:
            vars_dict["wave1_detailed_neighbor_data_captured"].set("No")


def create_wave1_widgets(
    parent_frame_container, vars_dict, widgets_dict, callbacks_dict, data_manager
):  # parent_frame_container is now the direct parent where frames are packed
    content_frame = widgets_dict[
        "content_frame"
    ]  # This is the scrollable frame from main_app

    widgets_dict["frame_connection"] = ttk.LabelFrame(
        content_frame, text="2. Connection & Access", padding="10"
    )
    widgets_dict["frame_cli_checks"] = ttk.LabelFrame(
        content_frame, text="3. Perform CLI Data Point Collection", padding="10"
    )
    widgets_dict["frame_final_id"] = ttk.LabelFrame(
        content_frame, text="4. Final Device ID & Notes", padding="10"
    )
    widgets_dict["frame_neighbor_status"] = ttk.LabelFrame(
        content_frame, text="5. Neighbor Discovery Status & Data Capture", padding="10"
    )
    widgets_dict["frame_actions"] = ttk.Frame(content_frame, padding="10")

    widgets_dict["frame_connection"].pack(fill=tk.X, pady=5, anchor=tk.NW)
    widgets_dict["frame_cli_checks"].pack(fill=tk.X, pady=5, anchor=tk.NW)
    widgets_dict["frame_final_id"].pack(fill=tk.X, pady=5, anchor=tk.NW)
    widgets_dict["frame_neighbor_status"].pack(fill=tk.X, pady=5, anchor=tk.NW)
    widgets_dict["frame_actions"].pack(fill=tk.X, pady=10, anchor=tk.NW)

    f_conn = widgets_dict["frame_connection"]
    f_conn.columnconfigure(1, weight=1)
    f_conn.columnconfigure(3, weight=1)
    update_state_callback = callbacks_dict.get("wave1_update_ui_state_callback")
    ttk.Label(f_conn, text="Could you interact?").grid(
        row=0, column=0, sticky=tk.W, pady=2
    )
    widgets_dict["conn_yes_radio"] = ttk.Radiobutton(
        f_conn,
        text="Yes",
        variable=vars_dict["connection_confirmed"],
        value="True",
        command=update_state_callback,
    )
    widgets_dict["conn_yes_radio"].grid(row=1, column=0, sticky=tk.W, padx=5)
    widgets_dict["conn_no_radio"] = ttk.Radiobutton(
        f_conn,
        text="No (Log Other Device)",
        variable=vars_dict["connection_confirmed"],
        value="False",
        command=update_state_callback,
    )
    widgets_dict["conn_no_radio"].grid(
        row=1, column=1, columnspan=3, sticky=tk.W, padx=5
    )
    ttk.Label(f_conn, text="Access Level:").grid(
        row=2, column=0, sticky=tk.W, pady=(5, 0)
    )
    widgets_dict["access_user_radio"] = ttk.Radiobutton(
        f_conn,
        text="User (>)",
        variable=vars_dict["access_level"],
        value="User",
        command=update_state_callback,
    )
    widgets_dict["access_user_radio"].grid(row=3, column=0, sticky=tk.W, padx=5)
    widgets_dict["access_priv_radio"] = ttk.Radiobutton(
        f_conn,
        text="Privileged (#)",
        variable=vars_dict["access_level"],
        value="Privileged",
        command=update_state_callback,
    )
    widgets_dict["access_priv_radio"].grid(row=3, column=1, sticky=tk.W, padx=5)
    ttk.Label(f_conn, text="Device Type:").grid(
        row=2, column=2, sticky=tk.W, padx=(15, 5), pady=(5, 0)
    )
    widgets_dict["type_switch_radio"] = ttk.Radiobutton(
        f_conn,
        text="Switch",
        variable=vars_dict["device_type"],
        value="Switch",
        command=update_state_callback,
    )
    widgets_dict["type_switch_radio"].grid(row=3, column=2, sticky=tk.W, padx=(15, 5))
    widgets_dict["type_router_radio"] = ttk.Radiobutton(
        f_conn,
        text="Router",
        variable=vars_dict["device_type"],
        value="Router",
        command=update_state_callback,
    )
    widgets_dict["type_router_radio"].grid(row=3, column=3, sticky=tk.W, padx=5)

    f_cli = widgets_dict["frame_cli_checks"]
    instr_text = (
        "Action Required: Switch to terminal emulator and connect to the device console.\n\n"
        "CONSOLE DATA POINT CAPTURE (Perform ALL before proceeding):\n"
        "---------------------------------------------------------\n"
        "1.  Start Console Logging to a temporary file (you will be given the exact filename later).\n"
        "2.  Login to the device (obtain User or Privileged access).\n"
        "3.  Ensure terminal output shows all lines (e.g., equivalent of 'terminal length 0').\n\n"
        "4.  **Capture ESSENTIAL Device Information & State (Do This FIRST):**\n"
        "    Obtain and log the following data points:\n"
        "    -   Device Identification: Version, Hostname, Uptime, **Serial Number**, **Device Base MAC Address**.\n"
        "    -   Interface Status: Physical & Logical interface operational states.\n"
        "    -   VLAN Details: Configured VLAN IDs, names, and their assigned ports.\n"
        "    -   IP Address Configuration: IPs on SVIs/Management interfaces (including masks/prefixes).\n"
        "    -   PoE Status (if applicable): Power usage, capability.\n"
        "    -   **Neighbor Discovery (LLDP/CDP) Operational Status**: Check if protocols are active.\n\n"
        "5.  **If Privileged Access, Capture EXTENDED Details (Do This LAST):**\n"
        "    Obtain and log the following data points if access level permits:\n"
        "    -   Full Running Configuration.\n"
        "    -   MAC Address Table.\n"
        "    -   ARP Table.\n"
        "    -   IP Routing Table (IPv4).\n"
        "    -   IPv6 Routing Table (if IPv6 is active).\n\n"
        "    (Action: If privileged AND neighbor discovery was OFF in Step 4, attempt to enable it. Then, re-check its operational status. If it becomes operational, capture detailed neighbor information - e.g., equivalent of 'show lldp/cdp neighbors detail').\n\n"
        "---------------------------------------------------------\n"
        "--> Return to this GUI AFTER ALL console steps are completed. Set results & flags below. <--"
    )
    ttk.Label(f_cli, text=instr_text, justify=tk.LEFT, style="Instr.TLabel").pack(
        fill=tk.X
    )
    widgets_dict["cli_checks_button"] = ttk.Button(
        f_cli,
        text="Proceed after CLI Data Point Collection",
        command=lambda: handle_wave1_cli_checks_done(callbacks_dict),
    )
    widgets_dict["cli_checks_button"].pack(pady=5)

    f_final = widgets_dict["frame_final_id"]
    f_final.columnconfigure(1, weight=1)
    f_final.columnconfigure(3, weight=1)
    current_row = 0
    ttk.Label(f_final, text="Serial Number (MANDATORY):").grid(
        row=current_row, column=0, sticky=tk.W, padx=5, pady=5
    )
    widgets_dict["entry_sn"] = ttk.Entry(
        f_final, textvariable=vars_dict["final_sn"], width=40
    )
    widgets_dict["entry_sn"].grid(
        row=current_row, column=1, columnspan=3, sticky=tk.EW, padx=5, pady=5
    )
    current_row += 1
    ttk.Label(f_final, text="Hostname (from CLI):").grid(
        row=current_row, column=0, sticky=tk.W, padx=5, pady=5
    )
    widgets_dict["entry_hostname"] = ttk.Entry(
        f_final, textvariable=vars_dict["final_hostname"], width=40
    )
    widgets_dict["entry_hostname"].grid(
        row=current_row, column=1, columnspan=3, sticky=tk.EW, padx=5, pady=5
    )
    current_row += 1
    ttk.Label(f_final, text="Make/Vendor (MANDATORY):").grid(
        row=current_row, column=0, sticky=tk.W, padx=5, pady=5
    )
    widgets_dict["entry_make"] = ttk.Entry(
        f_final, textvariable=vars_dict["final_make"], width=40
    )
    widgets_dict["entry_make"].grid(
        row=current_row, column=1, columnspan=3, sticky=tk.EW, padx=5, pady=5
    )
    current_row += 1
    ttk.Label(f_final, text="Model (MANDATORY):").grid(
        row=current_row, column=0, sticky=tk.W, padx=5, pady=5
    )
    widgets_dict["entry_model"] = ttk.Entry(
        f_final, textvariable=vars_dict["final_model"], width=40
    )
    widgets_dict["entry_model"].grid(
        row=current_row, column=1, columnspan=3, sticky=tk.EW, padx=5, pady=5
    )
    current_row += 1

    ttk.Label(f_final, text="PoE Capable:").grid(
        row=current_row, column=0, sticky=tk.W, padx=5, pady=5
    )
    poe_frame = ttk.Frame(f_final)
    poe_frame.grid(
        row=current_row, column=1, columnspan=3, sticky=tk.EW, padx=5, pady=2
    )
    widgets_dict["poe_yes_radio"] = ttk.Radiobutton(
        poe_frame, text="Yes", variable=vars_dict["is_poe_capable_gui"], value="Yes"
    )
    widgets_dict["poe_yes_radio"].pack(side=tk.LEFT, padx=(0, 10))
    widgets_dict["poe_no_radio"] = ttk.Radiobutton(
        poe_frame, text="No", variable=vars_dict["is_poe_capable_gui"], value="No"
    )
    widgets_dict["poe_no_radio"].pack(side=tk.LEFT)
    current_row += 1

    ttk.Label(f_final, text="Rack Type:").grid(
        row=current_row, column=0, sticky=tk.W, padx=5, pady=5
    )
    rack_options = [
        "",
        "Network",
        "Server",
        "Mini",
        "Ceiling",
        "Floor",
        "Wall",
        "Door",
        "Other",
    ]
    widgets_dict["wave1_rack_type_combo"] = ttk.Combobox(
        f_final,
        textvariable=vars_dict["rack_type"],
        values=rack_options,
        state="readonly",
        width=15,
    )
    widgets_dict["wave1_rack_type_combo"].grid(
        row=current_row, column=1, sticky=tk.W, padx=5, pady=5
    )
    widgets_dict["wave1_rack_type_combo"].bind(
        "<<ComboboxSelected>>",
        lambda event: handle_rack_type_selected(
            vars_dict, widgets_dict, frame_key_prefix="wave1_"
        ),
    )
    widgets_dict["wave1_rack_other_label"] = ttk.Label(
        f_final, text="Other Rack Detail:"
    )
    widgets_dict["wave1_rack_other_label"].grid(
        row=current_row, column=2, sticky=tk.W, padx=(10, 5), pady=5
    )
    widgets_dict["wave1_rack_other_entry"] = ttk.Entry(
        f_final,
        textvariable=vars_dict["rack_type_other"],
        width=30,
    )
    widgets_dict["wave1_rack_other_entry"].grid(
        row=current_row, column=3, sticky=tk.W, padx=5, pady=5
    )
    current_row += 1

    ttk.Label(f_final, text="Specific Notes (in current area):").grid(
        row=current_row, column=0, sticky=tk.W, padx=5, pady=5
    )
    widgets_dict["entry_notes"] = ttk.Entry(
        f_final, textvariable=vars_dict["final_location_notes"], width=40
    )
    widgets_dict["entry_notes"].grid(
        row=current_row, column=1, columnspan=3, sticky=tk.EW, padx=5, pady=5
    )
    current_row += 1

    f_neighbor = widgets_dict["frame_neighbor_status"]
    f_neighbor.columnconfigure(1, weight=1)

    ttk.Label(f_neighbor, text="LLDP/CDP Status (after checks/attempts):").grid(
        row=0, column=0, columnspan=2, sticky=tk.W, padx=5, pady=(5, 2)
    )

    def op_status_callback():
        return _handle_wave1_op_status_change(vars_dict, widgets_dict)

    widgets_dict["op_radio_yes"] = ttk.Radiobutton(
        f_neighbor,
        text="Operational",
        variable=vars_dict["lldp_cdp_operational_status"],
        value="Operational",
        command=op_status_callback,
    )
    widgets_dict["op_radio_yes"].grid(row=1, column=0, sticky=tk.W, padx=10, pady=2)
    widgets_dict["op_radio_no"] = ttk.Radiobutton(
        f_neighbor,
        text="Non_Operational",
        variable=vars_dict["lldp_cdp_operational_status"],
        value="Non_Operational",
        command=op_status_callback,
    )
    widgets_dict["op_radio_no"].grid(row=1, column=1, sticky=tk.W, padx=5, pady=2)

    widgets_dict["wave1_detailed_neighbor_frame"] = ttk.Frame(f_neighbor)
    widgets_dict["wave1_detailed_neighbor_frame"].grid(
        row=2, column=0, columnspan=2, sticky=tk.W, padx=5, pady=(5, 2)
    )

    ttk.Label(
        widgets_dict["wave1_detailed_neighbor_frame"],
        text="Detailed Neighbor Data (Wave 2 Equiv.) Captured in Wave 1 Log?",
    ).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(5, 0))
    widgets_dict["wave1_detailed_neighbor_data_captured_yes_radio"] = ttk.Radiobutton(
        widgets_dict["wave1_detailed_neighbor_frame"],
        text="Yes",
        variable=vars_dict["wave1_detailed_neighbor_data_captured"],
        value="Yes",
        state=tk.DISABLED,
    )
    widgets_dict["wave1_detailed_neighbor_data_captured_yes_radio"].grid(
        row=1, column=0, sticky=tk.W, padx=10
    )
    widgets_dict["wave1_detailed_neighbor_data_captured_no_radio"] = ttk.Radiobutton(
        widgets_dict["wave1_detailed_neighbor_frame"],
        text="No",
        variable=vars_dict["wave1_detailed_neighbor_data_captured"],
        value="No",
        state=tk.DISABLED,
    )
    widgets_dict["wave1_detailed_neighbor_data_captured_no_radio"].grid(
        row=1, column=1, sticky=tk.W, padx=5
    )

    f_actions = widgets_dict["frame_actions"]
    widgets_dict["save_button"] = ttk.Button(
        f_actions,
        text="Save Metadata & Show Log Instructions",
        command=lambda: handle_save_wave1_metadata(
            vars_dict, widgets_dict, callbacks_dict, data_manager
        ),
    )
    widgets_dict["save_button"].pack(side=tk.LEFT, padx=10)
    widgets_dict["reset_button"] = ttk.Button(
        f_actions,
        text="Reset Wave 1 Form",
        command=lambda: handle_wave1_reset_form(
            vars_dict, widgets_dict, callbacks_dict
        ),
    )
    widgets_dict["reset_button"].pack(side=tk.RIGHT, padx=10)

    content_frame.update_idletasks()  # Ensure frame has dimensions
    # Initialize visibility based on default values
    handle_rack_type_selected(vars_dict, widgets_dict, frame_key_prefix="wave1_")
    _handle_wave1_op_status_change(vars_dict, widgets_dict)


def handle_wave1_cli_checks_done(callbacks_dict):
    if "wave1_set_ui_state_callback" in callbacks_dict:
        callbacks_dict["wave1_set_ui_state_callback"]("cli_checks_done")


def handle_wave1_reset_form(vars_dict, widgets_dict, callbacks_dict):
    for key, var in vars_dict.items():
        if isinstance(var, tk.Variable):
            if key == "device_type":
                var.set(config.DEFAULT_DEVICE_TYPE)
            elif key == "wave1_detailed_neighbor_data_captured":
                var.set("No")
            elif key == "is_poe_capable_gui":
                var.set("")
            elif key in [
                "connection_confirmed",
                "access_level",
                "lldp_cdp_operational_status",
            ]:
                var.set("")
            elif key == "rack_type":  # Specifically for combobox
                var.set("")
            elif key == "rack_type_other":  # Clear this too
                var.set("")
            else:  # Clears most other StringVars like final_sn, final_hostname etc.
                var.set("")

    # Explicitly call these handlers after reset to ensure UI consistency
    handle_rack_type_selected(vars_dict, widgets_dict, frame_key_prefix="wave1_")
    _handle_wave1_op_status_change(vars_dict, widgets_dict)

    if "wave1_set_ui_state_callback" in callbacks_dict:
        callbacks_dict["wave1_set_ui_state_callback"]("initial")
    if "update_status" in callbacks_dict:
        callbacks_dict["update_status"]("Wave 1: Form reset.")


def handle_save_wave1_metadata(vars_dict, widgets_dict, callbacks_dict, data_manager):
    update_status = callbacks_dict.get("update_status")
    get_current_location = callbacks_dict.get("get_current_location")
    show_copyable_msg = callbacks_dict.get("show_copyable_message_callback")

    if not get_current_location or not show_copyable_msg:
        messagebox.showerror("Error", "Internal application error (missing callbacks).")
        return
    current_location = get_current_location()
    if not current_location:
        messagebox.showerror("Error", "Location not set.")
        return

    required_fields = {
        "access_level": "Access Level",
        "device_type": "Device Type",
        "final_sn": "Serial Number",
        "final_hostname": "Hostname",
        "final_make": "Make/Vendor",
        "final_model": "Model",
        "lldp_cdp_operational_status": "LLDP/CDP Status",
    }
    if vars_dict["lldp_cdp_operational_status"].get() == "Operational":
        required_fields["wave1_detailed_neighbor_data_captured"] = (
            "Detailed Neighbor Data Captured?"
        )

    # Check PoE selection
    if not vars_dict["is_poe_capable_gui"].get():  # If PoE selection is empty
        required_fields["is_poe_capable_gui_selection"] = "PoE Capable (Yes/No)"

    missing = [
        label
        for key, label in required_fields.items()
        if not vars_dict.get(key) or not vars_dict[key].get()
    ]
    # Special check for PoE if it was added to required_fields
    if (
        "is_poe_capable_gui_selection" in required_fields
        and not vars_dict["is_poe_capable_gui"].get()
    ):
        # It's already included in the missing list if it's empty, this is a bit redundant
        # but ensures the logic if other required fields were met but PoE was missed.
        pass

    if missing:
        messagebox.showerror(
            "Input Error", "Missing required fields:\n- " + "\n- ".join(missing)
        )
        return

    sn = vars_dict["final_sn"].get().strip().upper()
    op_status = vars_dict["lldp_cdp_operational_status"].get()
    detailed_capture_in_w1 = (
        vars_dict["wave1_detailed_neighbor_data_captured"].get() == "Yes"
        if op_status == "Operational"
        else False
    )

    rack_type = vars_dict["rack_type"].get()
    rack_other = vars_dict["rack_type_other"].get().strip()
    final_rack_detail = ""
    if rack_type == "Other":
        final_rack_detail = rack_other if rack_other else "Other - Not Specified"
    elif rack_type:
        final_rack_detail = rack_type

    poe_gui_value = vars_dict["is_poe_capable_gui"].get()
    is_poe_capable_metadata_value = 1 if poe_gui_value == "Yes" else 0

    metadata = {
        "helper_script_version": config.APP_VERSION,
        "metadata_capture_timestamp": datetime.datetime.now().isoformat(
            sep=" ", timespec="seconds"
        ),
        "access_level": vars_dict["access_level"].get(),
        "device_type": vars_dict["device_type"].get(),
        "final_hostname": vars_dict["final_hostname"].get().strip(),
        "final_serial_number": sn,
        "final_make": vars_dict["final_make"].get().strip(),
        "final_model": vars_dict["final_model"].get().strip(),
        "is_poe_capable": is_poe_capable_metadata_value,
        "final_rack_type_detail": final_rack_detail or "N/A",
        "final_site": current_location.get("site"),
        "final_building": current_location.get("building"),
        "final_floor": current_location.get("floor"),
        "final_wing": current_location.get("wing"),
        "final_area_name": current_location.get("area_name"),
        "final_location_notes": vars_dict["final_location_notes"].get().strip()
        or "N/A",
        "lldp_cdp_operational_status": op_status,
        "wave2_data_captured_in_wave1_log": detailed_capture_in_w1,
    }

    loc_site_sanitized = utils.sanitize_foldername_part(
        current_location.get("site"), "NoSite_Fallback"
    )
    loc_folder_segment = utils.format_location_log_folder_segment(
        building=current_location.get("building"),
        floor=current_location.get("floor"),
        wing=current_location.get("wing"),
        area_name=current_location.get("area_name"),
        wing_placeholder=utils.PATH_PLACEHOLDER_WING_DEFAULT,
        area_placeholder=utils.PATH_PLACEHOLDER_AREA_DEFAULT,
    )
    absolute_target_log_dir = os.path.abspath(
        os.path.join(config.LOGS_DIR, loc_site_sanitized, loc_folder_segment)
    )

    base_filename = utils.generate_safe_filename(sn)
    if not base_filename or base_filename == "unknown_filename":
        base_filename = f"UNKNOWN_SN_{datetime.datetime.now():%Y%m%d_%H%M%S}"

    metadata_filename = f"{base_filename}-WAVE1.meta.json"
    log_filename_txt_w1 = f"{base_filename}-WAVE1.txt"
    log_filename_txt_w2 = f"{base_filename}-WAVE2.txt"

    success, message_or_filepath = data_manager.save_wave1_metadata(
        metadata, metadata_filename
    )

    if success:
        metadata_filepath = message_or_filepath
        final_msg_prefix = f"Metadata saved to:\n{metadata_filepath}\n\n{'-' * 50}\nCRITICAL FINAL STEP(S):\n{'-' * 50}\n"

        final_msg_step1 = (
            f"1. Stop terminal logging for Wave 1.\n"
            f"2. Manually save your session log file using EXACTLY the name:\n"
            f"   >>> {log_filename_txt_w1} <<<\n\n"
            f"3. Place this file INSIDE the following PRE-CREATED directory:\n"
            f"   (This directory should exist if 'create_log_folders.py' was run)\n"
            f"   >>> {absolute_target_log_dir} <<<"
        )

        critical_note_w1 = ""
        if detailed_capture_in_w1:
            critical_note_w1 = (
                f"\n\n   **IMPORTANT**: Since 'Detailed Neighbor Data Captured = YES',\n"
                f"   ensure '{log_filename_txt_w1}' (in the directory above) CONTAINS the full output\n"
                "   of commands like 'show lldp neighbors detail' / 'show cdp neighbors detail'."
            )

        final_msg_suffix = (
            f"\n\n   Form will reset after clicking OK on this message.\n{'-' * 50}"
        )
        final_msg_step2 = ""
        if op_status == "Operational" and not detailed_capture_in_w1:
            final_msg_step2 = (
                f"\n\n{'-' * 50}\nACTION FOR WAVE 2 (Separate Log):\n{'-' * 50}\n"
                f"1. Go to Wave 2 tab, Verify SN (or use list).\n"
                f"2. Perform console check for detailed neighbors.\n"
                f"3. **ONLY IF** neighbors seen, save NEW log as:\n"
                f"   >>> {log_filename_txt_w2} <<<\n"
                f"   (Save this file also in the SAME directory: {absolute_target_log_dir})\n"
                f"4. Return to Wave 2 tab & click 'Mark Completed'."
            )

        full_message = f"{final_msg_prefix}{final_msg_step1}{critical_note_w1}{final_msg_step2}{final_msg_suffix}"

        show_copyable_msg(
            title="Success & Next Steps",
            message=full_message,
            copyable_text_label="Wave 1 Log Filename (for easy copy):",
            copyable_text=log_filename_txt_w1,
        )
        handle_wave1_reset_form(vars_dict, widgets_dict, callbacks_dict)
        if update_status:
            update_status(
                "Wave 1 metadata saved. Follow instructions for console log file."
            )
    else:
        error_message = message_or_filepath
        logging.error(f"Error saving Wave 1 metadata: {error_message}")
        messagebox.showerror(
            "Save Error", f"Could not save Wave 1 metadata:\n{error_message}"
        )
        if update_status:
            update_status("Error saving Wave 1 metadata.")


# --- Wave 2 (Checklist) Section ---


def create_wave2_checklist_widgets(
    parent_frame, vars_dict, widgets_dict, callbacks_dict, data_manager
):
    parent_frame.columnconfigure(0, weight=1)
    parent_frame.rowconfigure(2, weight=1)  # Row 2 (checklist_frame) will expand

    sn_entry_frame = ttk.LabelFrame(
        parent_frame, text="Verify SN for Wave 2 Completion", padding="5"
    )
    sn_entry_frame.grid(row=0, column=0, sticky=tk.EW, padx=5, pady=5)
    sn_entry_frame.columnconfigure(1, weight=1)

    ttk.Label(sn_entry_frame, text="Enter Serial Number:").grid(
        row=0, column=0, padx=5, pady=5, sticky=tk.W
    )
    widgets_dict["wave2_sn_entry_field"] = ttk.Entry(
        sn_entry_frame, textvariable=vars_dict["wave2_sn_entry"], width=30
    )
    widgets_dict["wave2_sn_entry_field"].grid(
        row=0, column=1, padx=5, pady=5, sticky=tk.EW
    )
    widgets_dict["wave2_verify_button"] = ttk.Button(
        sn_entry_frame,
        text="Verify & Prepare for Completion",
        command=lambda: handle_wave2_verify_sn(
            vars_dict, widgets_dict, callbacks_dict, data_manager, parent_frame
        ),
    )
    widgets_dict["wave2_verify_button"].grid(
        row=0, column=2, padx=5, pady=5, sticky=tk.E
    )

    widgets_dict["wave2_detail_frame"] = ttk.LabelFrame(
        parent_frame, text="Verified Device Details", padding="5"
    )
    widgets_dict["wave2_detail_frame"].columnconfigure(1, weight=1)
    ttk.Label(widgets_dict["wave2_detail_frame"], text="Verified SN:").grid(
        row=0, column=0, sticky=tk.W, padx=5
    )
    widgets_dict["wave2_verified_sn_label"] = ttk.Label(
        widgets_dict["wave2_detail_frame"],
        textvariable=vars_dict["wave2_verified_sn"],
        style="ReadOnly.TLabel",
    )
    widgets_dict["wave2_verified_sn_label"].grid(row=0, column=1, sticky=tk.W, padx=5)

    ttk.Label(widgets_dict["wave2_detail_frame"], text="Hostname:").grid(
        row=1, column=0, sticky=tk.W, padx=5
    )
    widgets_dict["wave2_verified_hostname_label"] = ttk.Label(
        widgets_dict["wave2_detail_frame"],
        textvariable=vars_dict["wave2_verified_hostname"],
        style="ReadOnly.TLabel",
    )
    widgets_dict["wave2_verified_hostname_label"].grid(
        row=1, column=1, sticky=tk.W, padx=5
    )

    ttk.Label(widgets_dict["wave2_detail_frame"], text="Make/Model:").grid(
        row=2, column=0, sticky=tk.W, padx=5
    )
    widgets_dict["wave2_verified_make_model_label"] = ttk.Label(
        widgets_dict["wave2_detail_frame"],
        textvariable=vars_dict["wave2_verified_make_model"],
        style="ReadOnly.TLabel",
    )
    widgets_dict["wave2_verified_make_model_label"].grid(
        row=2, column=1, sticky=tk.W, padx=5
    )

    ttk.Label(widgets_dict["wave2_detail_frame"], text="Required Log Filename:").grid(
        row=3, column=0, sticky=tk.W, padx=5, pady=(5, 0)
    )
    widgets_dict["wave2_required_filename_entry"] = ttk.Entry(
        widgets_dict["wave2_detail_frame"],
        textvariable=vars_dict["wave2_required_filename"],
        state="readonly",
        width=40,
    )
    widgets_dict["wave2_required_filename_entry"].grid(
        row=3, column=1, sticky=tk.EW, padx=5, pady=(5, 0)
    )

    def _copy_wave2_filename():
        clipboard_root = parent_frame.winfo_toplevel()
        if clipboard_root and clipboard_root.winfo_exists():
            clipboard_root.clipboard_clear()
            clipboard_root.clipboard_append(vars_dict["wave2_required_filename"].get())
            if callbacks_dict.get("update_status"):
                callbacks_dict["update_status"]("Wave 2 Filename copied to clipboard.")
        else:
            logging.warning("Could not access clipboard root for Wave 2 filename copy.")

    widgets_dict["wave2_copy_filename_button"] = ttk.Button(
        widgets_dict["wave2_detail_frame"],
        text="Copy",
        command=_copy_wave2_filename,
        state=tk.DISABLED,
    )
    widgets_dict["wave2_copy_filename_button"].grid(
        row=3, column=2, padx=5, pady=(5, 0), sticky=tk.W
    )

    widgets_dict["wave2_mark_complete_button"] = ttk.Button(
        widgets_dict["wave2_detail_frame"],
        text="Mark Completed (if log saved)",
        state=tk.DISABLED,
        command=lambda: handle_mark_wave2_complete(
            vars_dict, widgets_dict, callbacks_dict, data_manager
        ),
    )
    widgets_dict["wave2_mark_complete_button"].grid(
        row=4, column=0, columnspan=3, pady=10
    )
    widgets_dict["wave2_detail_frame"].grid(
        row=1, column=0, sticky=tk.EW, padx=5, pady=5
    )
    widgets_dict["wave2_detail_frame"].grid_remove()

    checklist_frame = ttk.LabelFrame(
        parent_frame, text="Pending Wave 2 Checklist (Optional Lookup)", padding="5"
    )
    checklist_frame.grid(row=2, column=0, sticky=tk.NSEW, padx=5, pady=5)
    checklist_frame.columnconfigure(0, weight=1)  # Treeview column
    checklist_frame.columnconfigure(1, weight=0)  # Search label (no weight)
    checklist_frame.columnconfigure(2, weight=0)  # Search entry (no weight)
    checklist_frame.rowconfigure(1, weight=1)  # Treeview row

    widgets_dict["refresh_button"] = ttk.Button(
        checklist_frame,
        text="Refresh Checklist",
        command=lambda: handle_refresh_wave2_checklist(
            vars_dict, widgets_dict, callbacks_dict, data_manager
        ),
    )
    widgets_dict["refresh_button"].grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
    ttk.Label(checklist_frame, text="Search List:").grid(
        row=0, column=1, padx=(10, 0), pady=5, sticky=tk.E
    )
    widgets_dict["wave2_tree_search_entry"] = ttk.Entry(
        checklist_frame, textvariable=vars_dict["wave2_tree_search_term"], width=25
    )
    widgets_dict["wave2_tree_search_entry"].grid(
        row=0, column=2, padx=5, pady=5, sticky=tk.E
    )
    widgets_dict["wave2_tree_search_entry"].bind(
        "<KeyRelease>",
        lambda event: handle_refresh_wave2_checklist(
            vars_dict, widgets_dict, callbacks_dict, data_manager
        ),
    )

    columns = ("hostname", "make", "model", "location_notes")
    widgets_dict["tree"] = ttk.Treeview(
        checklist_frame, columns=columns, show="headings", height=10
    )
    widgets_dict["tree"].heading("hostname", text="Hostname")
    widgets_dict["tree"].column("hostname", width=180, anchor=tk.W)
    widgets_dict["tree"].heading("make", text="Make")
    widgets_dict["tree"].column("make", width=100, anchor=tk.W)
    widgets_dict["tree"].heading("model", text="Model")
    widgets_dict["tree"].column("model", width=120, anchor=tk.W)
    widgets_dict["tree"].heading("location_notes", text="Location Notes")
    widgets_dict["tree"].column("location_notes", width=250, anchor=tk.W)
    tree_scrollbar = ttk.Scrollbar(
        checklist_frame, orient="vertical", command=widgets_dict["tree"].yview
    )
    widgets_dict["tree"].configure(yscrollcommand=tree_scrollbar.set)
    widgets_dict["tree"].grid(
        row=1, column=0, columnspan=3, sticky=tk.NSEW
    )  # Span all 3 cols for tree
    tree_scrollbar.grid(
        row=1, column=3, sticky=tk.NS
    )  # Put scrollbar in a 4th conceptual col
    widgets_dict["tree"].bind(
        "<<TreeviewSelect>>",
        lambda event: handle_wave2_tree_item_select(vars_dict, widgets_dict),
    )

    widgets_dict["wave2_treeview_map"] = {}
    return widgets_dict


def handle_refresh_wave2_checklist(
    vars_dict, widgets_dict, callbacks_dict, data_manager
):
    update_status = callbacks_dict.get("update_status")
    get_current_location = callbacks_dict.get("get_current_location")
    tree = widgets_dict.get("tree")
    tree_map = widgets_dict.get("wave2_treeview_map")
    search_term = vars_dict.get("wave2_tree_search_term", tk.StringVar()).get().lower()

    if not get_current_location or not tree or tree_map is None:
        return
    current_location = get_current_location()
    if not current_location:
        messagebox.showerror("Location Error", "Current location is not set.")
        return

    for item in tree.get_children():
        tree.delete(item)
    tree_map.clear()
    pending_items = data_manager.get_wave1_metadata_files_info(current_location)

    filtered_items = []
    if search_term:
        for item_data in pending_items:
            if (
                search_term in item_data.get("sn", "").lower()
                or search_term in item_data.get("hostname", "").lower()
                or search_term in item_data.get("make", "").lower()
                or search_term in item_data.get("model", "").lower()
                or search_term in item_data.get("location_notes", "").lower()
            ):
                filtered_items.append(item_data)
    else:
        filtered_items = pending_items

    for item_data in filtered_items:
        sn_val = item_data.get("sn")
        if sn_val:
            values = (
                item_data.get("hostname", "N/A"),
                item_data.get("make", "N/A"),
                item_data.get("model", "N/A"),
                item_data.get("location_notes", ""),
            )
            iid = tree.insert(
                "", tk.END, values=values, tags=(sn_val,)
            )  # Use SN as a tag for identification
            tree_map[iid] = item_data  # Map IID to full data

    found_count = len(filtered_items)
    if update_status:
        update_status(
            f"Wave 2 Checklist: Found {found_count} pending item(s) matching search."
        )


def _generate_wave2_filename(sn_value):
    if sn_value:
        base = utils.generate_safe_filename(sn_value)
        return f"{base}-WAVE2.txt" if base and base != "unknown_filename" else None
    return None


def handle_wave2_tree_item_select(vars_dict, widgets_dict):
    tree = widgets_dict.get("tree")
    tree_map = widgets_dict.get("wave2_treeview_map")
    sn_entry_var = vars_dict.get("wave2_sn_entry")

    if not tree or not tree_map or not sn_entry_var:
        return

    selected_iids = tree.selection()
    if selected_iids:
        iid = selected_iids[0]
        item_data = tree_map.get(iid)
        if item_data and item_data.get("sn"):
            sn_entry_var.set(item_data.get("sn"))


def handle_wave2_verify_sn(
    vars_dict, widgets_dict, callbacks_dict, data_manager, parent_frame_for_clipboard
):
    sn_to_verify = vars_dict["wave2_sn_entry"].get().strip().upper()
    update_status = callbacks_dict.get("update_status")
    get_current_location = callbacks_dict.get("get_current_location")

    detail_frame = widgets_dict.get("wave2_detail_frame")
    mark_complete_btn = widgets_dict.get("wave2_mark_complete_button")
    copy_filename_btn = widgets_dict.get("wave2_copy_filename_button")

    vars_dict["wave2_verified_sn"].set("N/A")
    vars_dict["wave2_verified_hostname"].set("N/A")
    vars_dict["wave2_verified_make_model"].set("N/A")
    vars_dict["wave2_required_filename"].set("N/A")

    if detail_frame and detail_frame.winfo_exists():
        detail_frame.grid_remove()
    if mark_complete_btn and mark_complete_btn.winfo_exists():
        mark_complete_btn.config(state=tk.DISABLED)
    if copy_filename_btn and copy_filename_btn.winfo_exists():
        copy_filename_btn.config(state=tk.DISABLED)

    if not sn_to_verify:
        messagebox.showerror("Input Error", "Please enter a Serial Number to verify.")
        return
    if not get_current_location:
        return
    current_location = get_current_location()
    if not current_location:
        messagebox.showerror("Location Error", "Current location is not set.")
        return

    is_valid_for_wave2, device_info_or_error = data_manager.verify_sn_for_wave2(
        sn_to_verify, current_location
    )

    if is_valid_for_wave2 and isinstance(device_info_or_error, dict):
        vars_dict["wave2_verified_sn"].set(device_info_or_error.get("sn", "Error"))
        vars_dict["wave2_verified_hostname"].set(
            device_info_or_error.get("hostname", "N/A")
        )
        make_model = f"{device_info_or_error.get('make', 'N/A')} / {device_info_or_error.get('model', 'N/A')}"
        vars_dict["wave2_verified_make_model"].set(make_model)

        filename = _generate_wave2_filename(device_info_or_error.get("sn"))
        vars_dict["wave2_required_filename"].set(
            filename if filename else "Error generating filename"
        )

        if detail_frame and detail_frame.winfo_exists():
            detail_frame.grid()
        if mark_complete_btn and mark_complete_btn.winfo_exists():
            mark_complete_btn.config(state=tk.NORMAL)
        if copy_filename_btn and copy_filename_btn.winfo_exists():
            copy_filename_btn.config(state=tk.NORMAL if filename else tk.DISABLED)
        if update_status:
            update_status(f"SN {sn_to_verify} verified. Prepare log and mark complete.")
    else:
        messagebox.showerror("Verification Failed", device_info_or_error)
        if update_status:
            update_status(
                f"SN {sn_to_verify} verification failed: {device_info_or_error}"
            )


def handle_mark_wave2_complete(vars_dict, widgets_dict, callbacks_dict, data_manager):
    sn_to_complete = vars_dict["wave2_verified_sn"].get()
    update_status = callbacks_dict.get("update_status")
    detail_frame = widgets_dict.get("wave2_detail_frame")
    mark_complete_btn = widgets_dict.get("wave2_mark_complete_button")
    copy_filename_btn = widgets_dict.get("wave2_copy_filename_button")

    if not sn_to_complete or sn_to_complete == "N/A":
        messagebox.showerror("Error", "No verified Serial Number to mark complete.")
        return

    filename = vars_dict["wave2_required_filename"].get()
    if not filename or "Error" in filename or filename == "N/A":
        messagebox.showerror(
            "Error", "Cannot confirm completion due to filename error."
        )
        return

    msg = f"Confirm Completion for SN: {sn_to_complete}\n\nDid you see neighbor output AND save the log as '{filename}'?\n\n(Click 'Yes' only if BOTH conditions are true.)"
    if messagebox.askyesno("Confirm Wave 2 Log Saved", msg):
        timestamp = datetime.datetime.now().isoformat(sep=" ", timespec="seconds")
        success, message = data_manager.add_wave2_completed_sn(
            sn_to_complete, timestamp
        )

        if success:
            vars_dict["wave2_verified_sn"].set("N/A")
            vars_dict["wave2_verified_hostname"].set("N/A")
            vars_dict["wave2_verified_make_model"].set("N/A")
            vars_dict["wave2_required_filename"].set("N/A")
            vars_dict["wave2_sn_entry"].set("")
            if detail_frame and detail_frame.winfo_exists():
                detail_frame.grid_remove()
            if mark_complete_btn and mark_complete_btn.winfo_exists():
                mark_complete_btn.config(state=tk.DISABLED)
            if copy_filename_btn and copy_filename_btn.winfo_exists():
                copy_filename_btn.config(state=tk.DISABLED)

            if update_status:
                update_status(f"Marked {sn_to_complete} as Wave 2 complete.")
            logging.info(f"User marked SN {sn_to_complete} W2 complete via SN entry.")
            handle_refresh_wave2_checklist(
                vars_dict, widgets_dict, callbacks_dict, data_manager
            )
        else:
            messagebox.showerror(
                "Save Error", f"Failed to save completion status:\n{message}"
            )
            if update_status:
                update_status("Error marking W2 complete.")
    else:
        logging.info(f"User cancelled W2 completion for SN {sn_to_complete}.")


# All Deferred Switches (Cable Missing) Section functions have been removed:
# create_deferred_widgets, handle_log_deferred_switch,
# handle_refresh_deferred_checklist, handle_deferred_checklist_select,
# handle_copy_deferred_notes, handle_mark_deferred_surveyed
