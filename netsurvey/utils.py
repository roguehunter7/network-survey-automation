# utils.py
"""General utility functions for the Network Survey Helper application."""

import re

try:  # Tk is only needed for the GUI dialogs; allow headless CLI use.
    import tkinter as tk
    from tkinter import StringVar, ttk
except ImportError:  # pragma: no cover - headless environment
    tk = None
    StringVar = None
    ttk = None

# Default placeholders for log folder path segments if wing or area_name are missing/empty.
# These are used by format_location_log_folder_segment and the create_log_folders.py utility.
PATH_PLACEHOLDER_WING_DEFAULT = "__NoWing__"
PATH_PLACEHOLDER_AREA_DEFAULT = "__NoArea__"


def sanitize_foldername_part(name_part: str, placeholder: str = "Unknown") -> str:
    """
    Sanitizes a single component of a path to be filesystem-safe.
    Replaces spaces with underscores, removes most special characters.
    Uses a placeholder if the name_part is None, empty, or becomes empty after sanitization.
    """
    if name_part is None or str(name_part).strip() == "":
        return placeholder

    s_name = str(name_part)

    # Replace common problematic characters that have clear preferred alternatives
    s_name = s_name.replace(" ", "_")
    s_name = s_name.replace("/", "-")  # Common in floor names like "G/F"
    s_name = s_name.replace("\\", "-")
    s_name = s_name.replace(":", "-")

    # Remove characters that are generally unsafe or unwanted in folder names
    s_name = re.sub(r'[<>*?"|]', "", s_name)  # Characters to remove outright

    # Further restrict to a known safe set (alphanumeric, underscore, hyphen, period)
    # This is more restrictive than just removing specific bad chars.
    s_name = re.sub(r"[^\w.\-_]", "", s_name)

    # Collapse multiple consecutive underscores or hyphens that might result from replacements
    s_name = re.sub(r"[_]+", "_", s_name)
    s_name = re.sub(r"[-]+", "-", s_name)

    # Remove leading/trailing underscores, hyphens, or periods
    s_name = s_name.strip("_-.")

    # If after all sanitization the name is empty, return the placeholder
    return s_name if s_name else placeholder


def format_location_log_folder_segment(
    building: str,
    floor: str,
    wing: str,
    area_name: str,
    wing_placeholder: str = PATH_PLACEHOLDER_WING_DEFAULT,
    area_placeholder: str = PATH_PLACEHOLDER_AREA_DEFAULT,
) -> str:
    """
    Formats the <Building>-<Floor>-<Wing>-<LabAreaName> segment for log folder paths.
    Uses specified placeholders for empty/None wing or area_name.
    """
    s_bldg = sanitize_foldername_part(
        building, "NoBuilding_Fallback"
    )  # Building should ideally not be empty
    s_floor = sanitize_foldername_part(
        floor, "NoFloor_Fallback"
    )  # Floor should ideally not be empty

    # Wing and Area can be legitimately empty/None; sanitize_foldername_part handles this by using the provided placeholder
    s_wing = sanitize_foldername_part(wing, wing_placeholder)
    s_area = sanitize_foldername_part(area_name, area_placeholder)

    return f"{s_bldg}-{s_floor}-{s_wing}-{s_area}"


def generate_safe_filename(*args):
    """Generates a filesystem-safe filename from input arguments.

    Converts arguments to strings, joins with underscores, replaces invalid
    characters, and removes characters other than word chars, hyphens, dots.
    This is typically used for SN-based filenames like <SN>-WAVE1.txt.

    Args:
        *args: Variable number of arguments to include in the filename.

    Returns:
        A filesystem-safe string suitable for use as a filename. Returns
        'unknown_filename' if the result would otherwise be empty.
    """
    # Filter out None or empty args before converting to string
    string_args = [str(p) for p in args if p is not None and str(p).strip() != ""]
    if not string_args:
        return "unknown_filename"  # Handle case where all args are empty/None

    base = "_".join(string_args)
    # Replace common problematic characters first
    base = (
        base.replace(" ", "_")
        .replace("/", "-")
        .replace("\\", "-")
        .replace(":", "-")
        .replace("*", "-")
        .replace("?", "")
        .replace('"', "")
        .replace("<", "")
        .replace(">", "")
        .replace("|", "")
    )
    # Remove any remaining characters not explicitly allowed (word chars, hyphen, dot)
    safe_name = re.sub(r"[^\w.\-]", "", base)  # Keep word chars, dot, hyphen
    # Collapse multiple consecutive underscores or hyphens
    safe_name = re.sub(r"[_]+", "_", safe_name)
    safe_name = re.sub(r"[-]+", "-", safe_name)
    # Remove leading/trailing underscores or hyphens
    safe_name = safe_name.strip("_-")

    return safe_name if safe_name else "unknown_filename"  # Ensure not empty


def validate_int_input(p_value):
    """Validation function for Tkinter Entry widgets to allow only integers.

    Intended for use with the 'validatecommand' option.

    Args:
        p_value: The prospective value of the entry widget after the change.

    Returns:
        True if the value is empty or consists only of digits, False otherwise.
    """
    return p_value == "" or p_value.isdigit()


def show_copyable_message(
    root_window, title, message, copyable_text_label, copyable_text
):
    """Displays a Toplevel window with a message and a read-only, copyable text field.

    Args:
        root_window: The parent window (Tk or Toplevel) for the dialog.
        title: The title for the dialog window.
        message: The main message text to display.
        copyable_text_label: The label to display next to the copyable text field.
        copyable_text: The text to display in the read-only entry, ready for copying.
    """
    if (
        not isinstance(root_window, (tk.Tk, tk.Toplevel))
        or not root_window.winfo_exists()
    ):
        # Fallback for headless environments or if root_window is bad
        print("--- show_copyable_message FALLBACK (Invalid root_window) ---")
        print(f"Title: {title}")
        print(f"Message:\n{message}")
        print(f"{copyable_text_label} {copyable_text}")
        print("-----------------------------------------------------------")
        return

    dialog = tk.Toplevel(root_window)
    dialog.title(title)
    dialog.transient(root_window)  # Keep dialog on top of its parent
    dialog.grab_set()  # Make dialog modal
    dialog.resizable(False, False)

    main_frame = ttk.Frame(dialog, padding="15")
    main_frame.pack(expand=True, fill=tk.BOTH)

    # Use a larger wraplength for potentially longer messages
    msg_label = ttk.Label(
        main_frame, text=message, justify=tk.LEFT, wraplength=550
    )  # Increased wraplength
    msg_label.pack(pady=(0, 15), fill=tk.X, expand=True)

    copy_frame = ttk.Frame(main_frame)
    copy_frame.pack(fill=tk.X, pady=5)

    copy_label = ttk.Label(copy_frame, text=copyable_text_label)
    copy_label.pack(side=tk.LEFT, padx=(0, 5))

    copy_var = StringVar(value=copyable_text)
    # Calculate width, ensure a minimum reasonable width, cap at a max
    entry_width = max(
        25, min(70, len(copyable_text) + 5)
    )  # Min 25, Max 70, slight padding
    copy_entry = ttk.Entry(
        copy_frame, textvariable=copy_var, state="readonly", width=entry_width
    )
    copy_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

    # Function to select text for easy copying after a short delay
    def select_entry_text_after_delay():
        # Check if widget still exists before trying to interact
        if dialog.winfo_exists() and copy_entry.winfo_exists():
            copy_entry.focus_set()
            copy_entry.select_range(0, tk.END)
            copy_entry.icursor(tk.END)  # Place cursor at the end

    dialog.after(
        150, select_entry_text_after_delay
    )  # Slightly longer delay for complex UIs

    ok_button = ttk.Button(
        main_frame, text="OK", command=dialog.destroy, width=12
    )  # Slightly wider
    ok_button.pack(pady=(15, 0))

    # Bind Enter key to OK button for convenience
    dialog.bind("<Return>", lambda event: ok_button.invoke())
    dialog.bind("<KP_Enter>", lambda event: ok_button.invoke())  # Numeric keypad Enter

    # Center the dialog relative to the root window
    try:
        # Ensure windows are updated for accurate size/position info
        dialog.update_idletasks()
        if not root_window.winfo_exists():  # Check again after update_idletasks
            dialog.destroy()
            return

        root_window.update_idletasks()
        if not root_window.winfo_exists():  # Check again after update_idletasks
            dialog.destroy()
            return

        root_x = root_window.winfo_rootx()
        root_y = root_window.winfo_rooty()
        root_w = root_window.winfo_width()
        root_h = root_window.winfo_height()

        dialog.update_idletasks()  # Ensure dialog itself has its dimensions calculated
        dialog_w = dialog.winfo_width()
        dialog_h = dialog.winfo_height()

        if all(d > 0 for d in [root_w, root_h, dialog_w, dialog_h]):
            pos_x = root_x + (root_w // 2) - (dialog_w // 2)
            pos_y = root_y + (root_h // 2) - (dialog_h // 2)

            screen_w = root_window.winfo_screenwidth()
            screen_h = root_window.winfo_screenheight()
            pos_x = max(0, min(pos_x, screen_w - dialog_w))  # Ensure it's on screen
            pos_y = max(0, min(pos_y, screen_h - dialog_h))  # Ensure it's on screen

            dialog.geometry(f"+{pos_x}+{pos_y}")
        else:
            # Fallback geometry if sizes are weird (e.g., minimized window)
            dialog.geometry("")  # Let window manager decide
            print(
                "Warning: Could not get valid window dimensions for centering dialog. Using default placement."
            )

    except tk.TclError as e:
        print(f"Warning: Could not center dialog due to TclError: {e}")
        dialog.geometry("")  # Fallback
    except Exception as e:  # Catch any other unexpected error during centering
        print(f"Warning: Unexpected error centering dialog: {e}")
        dialog.geometry("")  # Fallback

    # Wait for the dialog to be closed by the user (modal behavior)
    root_window.wait_window(dialog)


def show_multiple_moonid_matches_dialog(
    root_window, title, message_intro, moonid_matches_list
):
    """Displays a Toplevel window with a list of MOONID matches."""
    if (
        not isinstance(root_window, (tk.Tk, tk.Toplevel))
        or not root_window.winfo_exists()
    ):
        # Fallback for headless environments or if root_window is bad
        print(
            "--- show_multiple_moonid_matches_dialog FALLBACK (Invalid root_window) ---"
        )
        print(f"Title: {title}")
        if message_intro:
            print(f"Message:\n{message_intro}")
        print("Matching MOONIDs:")
        for match in moonid_matches_list:
            print(
                f"  - MOONID: {match.get('moonid', 'N/A')}, Status: {match.get('status', 'N/A')}, Purpose: {match.get('purpose', 'N/A')}"
            )
        print("-----------------------------------------------------------")
        return

    dialog = tk.Toplevel(root_window)
    dialog.title(title)
    dialog.transient(root_window)  # Keep dialog on top of its parent
    dialog.grab_set()  # Make dialog modal
    dialog.resizable(True, True)  # Allow resizing

    main_frame = ttk.Frame(dialog, padding="15")
    main_frame.pack(expand=True, fill=tk.BOTH)

    if message_intro:
        msg_label = ttk.Label(
            main_frame, text=message_intro, justify=tk.LEFT, wraplength=550
        )
        msg_label.pack(
            pady=(0, 10), fill=tk.X, expand=False
        )  # Don't expand message label

    tree_container_frame = ttk.Frame(main_frame)
    tree_container_frame.pack(expand=True, fill=tk.BOTH)

    columns = ("moonid", "status", "purpose")
    tree = ttk.Treeview(
        tree_container_frame,
        columns=columns,
        show="headings",
        height=min(10, len(moonid_matches_list) + 1),
    )

    tree.heading("moonid", text="MOONID")
    tree.column("moonid", width=120, anchor=tk.W, stretch=tk.NO)
    tree.heading("status", text="Status")
    tree.column("status", width=100, anchor=tk.W, stretch=tk.NO)
    tree.heading("purpose", text="Purpose / MOON-Name")
    tree.column("purpose", width=300, anchor=tk.W)  # Allow purpose to stretch

    scrollbar_y = ttk.Scrollbar(
        tree_container_frame, orient="vertical", command=tree.yview
    )
    tree.configure(yscrollcommand=scrollbar_y.set)

    scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
    tree.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)

    for match in moonid_matches_list:
        tree.insert(
            "",
            tk.END,
            values=(
                match.get("moonid", "N/A"),
                match.get("status", "N/A"),
                match.get("purpose", "N/A"),
            ),
        )

    ok_button = ttk.Button(main_frame, text="OK", command=dialog.destroy, width=12)
    ok_button.pack(pady=(15, 0))

    dialog.bind("<Return>", lambda event: ok_button.invoke())
    dialog.bind("<KP_Enter>", lambda event: ok_button.invoke())

    dialog.update_idletasks()
    try:
        root_x = root_window.winfo_rootx()
        root_y = root_window.winfo_rooty()
        root_w = root_window.winfo_width()
        root_h = root_window.winfo_height()
        dialog_w = dialog.winfo_width()
        dialog_h = dialog.winfo_height()
        if dialog_w < 200:
            dialog_w = 580  # ensure min width
        if dialog_h < 100:
            dialog_h = 300  # ensure min height

        pos_x = root_x + (root_w // 2) - (dialog_w // 2)
        pos_y = root_y + (root_h // 2) - (dialog_h // 2)

        screen_w = root_window.winfo_screenwidth()
        screen_h = root_window.winfo_screenheight()
        pos_x = max(0, min(pos_x, screen_w - dialog_w))
        pos_y = max(0, min(pos_y, screen_h - dialog_h))

        dialog.geometry(f"{dialog_w}x{dialog_h}+{pos_x}+{pos_y}")
    except tk.TclError:
        dialog.geometry("580x300")  # Fallback

    root_window.wait_window(dialog)
