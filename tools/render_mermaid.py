import argparse
import json
import os
import shutil
import subprocess
import sys

# --- Configuration ---
DEFAULT_PNG_SCALE_FACTOR = "8"
MERMAID_CONFIG_FILENAME = "mermaid_render_config.json"
DEFAULT_MAX_TEXT_SIZE = 100000000
# --- End Configuration ---

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mermaid Diagram Viewer</title>
    <style>
        body {{ margin: 0; padding: 20px; display: flex; justify-content: center; align-items: center; background-color: #f0f0f0; }}
        .mermaid-container {{ max-width: 95%; max-height: 95vh; overflow: auto; background-color: white; padding: 10px; border: 1px solid #ccc; }}
        /* You can add more specific styling for the SVG container if needed */
    </style>
</head>
<body>
    <div class="mermaid-container">
        <pre class="mermaid">
{mermaid_code}
        </pre>
    </div>
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@latest/dist/mermaid.esm.min.mjs'
        try {{
            mermaid.initialize({{
                startOnLoad: true,
                maxTextSize: {max_text_size_js}, // Use a large value
                // You can add other Mermaid JS configurations here if needed
                // flowchart: {{
                // defaultRenderer: 'dagre'
                // }},
                // theme: "default",
            }});
        }} catch (e) {{
            console.error("Mermaid initialization error:", e);
            const mermaidContainer = document.querySelector('.mermaid');
            if (mermaidContainer) {{
                mermaidContainer.textContent = `Error initializing Mermaid: ${{e.message}}\\n\\nOriginal Mermaid Code:\\n{mermaid_code_escaped_for_js_error}`;
            }}
        }}
    </script>
</body>
</html>
"""


def find_mmdc():
    return shutil.which("mmdc")


def ensure_mermaid_config_exists(config_path, max_text_size):
    if not os.path.exists(config_path):
        print(
            f"Creating default Mermaid config file: {config_path} with maxTextSize: {max_text_size}"
        )
        config_data = {"maxTextSize": int(max_text_size)}
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=4)
            print(f"Successfully created {config_path}")
        except IOError as e:
            print(
                f"WARNING: Could not create Mermaid config file at {config_path}: {e}"
            )
            return False
    return True


def generate_html_viewer(
    input_mmd_path, output_html_path, max_text_size_for_js=20000000
):
    """
    Generates an HTML file that renders the given .mmd file using Mermaid.js.
    """
    if not os.path.exists(input_mmd_path):
        print(f"ERROR: Input .mmd file not found: {input_mmd_path}")
        sys.exit(1)

    try:
        with open(input_mmd_path, "r", encoding="utf-8") as f:
            mermaid_code = f.read()
    except IOError as e:
        print(f"ERROR: Could not read input .mmd file {input_mmd_path}: {e}")
        sys.exit(1)

    # For displaying code in JS error message, escape backticks and backslashes
    mermaid_code_escaped = mermaid_code.replace("\\", "\\\\").replace("`", "\\`")

    html_content = HTML_TEMPLATE.format(
        mermaid_code=mermaid_code,
        max_text_size_js=max_text_size_for_js,
        mermaid_code_escaped_for_js_error=mermaid_code_escaped,
    )

    try:
        with open(output_html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"HTML viewer file generated: {os.path.abspath(output_html_path)}")
        print(
            "Open this HTML file in your web browser to view the diagram and save it as SVG."
        )
    except IOError as e:
        print(f"ERROR: Could not write HTML file {output_html_path}: {e}")
        sys.exit(1)


def render_mermaid_cli(
    input_path, output_path, png_scale_factor, mmdc_config_path=None
):
    """
    Renders using mmdc (original function).
    """
    mmdc_executable = find_mmdc()
    if not mmdc_executable:
        print("ERROR: Mermaid CLI ('mmdc') not found. Cannot render using CLI.")
        # Don't exit if HTML generation is also an option, but indicate failure for mmdc
        return False  # Indicate mmdc rendering failed

    if not os.path.exists(input_path):
        print(f"ERROR: Input file not found: {input_path}")
        return False

    _, output_ext = os.path.splitext(output_path)
    output_ext = output_ext.lower()

    print(f"Found mmdc at: {mmdc_executable}")
    print(f"Attempting to render '{input_path}' to '{output_path}' using mmdc...")

    command = [mmdc_executable, "-i", input_path, "-o", output_path]

    if mmdc_config_path and os.path.exists(mmdc_config_path):
        print(f"--> Using mmdc config file: {mmdc_config_path}")
        command.extend(["-C", mmdc_config_path])
    elif mmdc_config_path:
        print(
            f"WARNING: Specified mmdc config file not found: {mmdc_config_path}. Proceeding without it."
        )

    if output_ext == ".png":
        print(f"--> Detected PNG output, applying scale factor: {png_scale_factor}")
        command.extend(["-s", str(png_scale_factor)])

    print(f"DEBUG: Executing mmdc command: {' '.join(command)}")
    try:
        result = subprocess.run(
            command, check=True, capture_output=True, text=True, encoding="utf-8"
        )
        print("mmdc rendering successful!")
        if result.stdout:
            print("mmdc output:", result.stdout)
        if result.stderr:
            print("mmdc errors/warnings (stderr):", result.stderr)
        # Check output file content for mmdc's "Max text size" error in SVG
        if output_ext == ".svg":
            try:
                with open(output_path, "r", encoding="utf-8") as f_svg:
                    svg_content = f_svg.read(500)  # Read first 500 chars
                    if "Maximum text size in diagram exceeded" in svg_content:
                        print(
                            "WARNING: mmdc seems to have written 'Maximum text size' error into the SVG."
                        )
                        print(
                            "         The HTML viewer might be a better option for this large diagram."
                        )
            except Exception:
                pass  # Ignore if we can't read it back
        return True  # Indicate mmdc rendering was attempted successfully by the process

    except FileNotFoundError:
        print(
            f"ERROR: Could not execute '{mmdc_executable}'. Make sure it's installed and in PATH."
        )
    except subprocess.CalledProcessError as e:
        print(f"ERROR: 'mmdc' command failed with exit code {e.returncode}")
        print("Command:", " ".join(e.cmd))
        print("stdout:", e.stdout)
        print("stderr:", e.stderr)
    except Exception as e:
        print(f"An unexpected error occurred during mmdc rendering: {e}")
    return False  # Indicate mmdc rendering failed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Render a Mermaid .mmd file to an image using mmdc or generate an HTML viewer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Example Usage:
  Render to SVG using mmdc:
    python {sys.argv[0]} diagram.mmd diagram.svg

  Generate an HTML viewer (then open diagram.html in browser to save SVG):
    python {sys.argv[0]} diagram.mmd diagram.html --html

  Render to PNG using mmdc:
    python {sys.argv[0]} diagram.mmd diagram.png

Options for mmdc:
  --png_scale <factor>          Scale factor for PNG output (default: {DEFAULT_PNG_SCALE_FACTOR})
  --mmdc_config <path>          Path to a custom mmdc JSON config file.
  --create_default_config       Creates a default '{MERMAID_CONFIG_FILENAME}' for mmdc and exits.
  --max_text_size_for_default_config <size> Set maxTextSize for default mmdc config.
""",
    )
    parser.add_argument(
        "input_file", help="Path to the input Mermaid diagram file (.mmd)"
    )
    parser.add_argument(
        "output_file",
        help="Path for the output file. For --html, this will be the .html file. Otherwise, extension determines mmdc format (e.g., .svg, .png, .pdf)",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="Generate an HTML viewer file instead of using mmdc directly. Output file should be .html.",
    )
    parser.add_argument(
        "--png_scale",
        default=DEFAULT_PNG_SCALE_FACTOR,
        help=f"Scale factor for PNG output with mmdc (default: {DEFAULT_PNG_SCALE_FACTOR})",
    )
    parser.add_argument(
        "--mmdc_config",
        help=f"Path to a custom mmdc JSON config file. If not provided, tries to use '{MERMAID_CONFIG_FILENAME}' in the script's directory for mmdc.",
        default=None,
    )
    parser.add_argument(
        "--create_default_config",
        action="store_true",
        help=f"If specified, creates a default '{MERMAID_CONFIG_FILENAME}' in the script's directory with maxTextSize={DEFAULT_MAX_TEXT_SIZE} for mmdc and then exits.",
    )
    parser.add_argument(
        "--max_text_size_for_default_config",
        default=DEFAULT_MAX_TEXT_SIZE,
        type=int,
        help=f"Set the maxTextSize when creating the default mmdc config with --create_default_config (default: {DEFAULT_MAX_TEXT_SIZE})",
    )
    parser.add_argument(
        "--js_max_text_size",
        default=200000000,  # Large default for JS library
        type=int,
        help="maxTextSize to use in the HTML viewer's Mermaid.js initialization (default: 200000000).",
    )

    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.realpath(__file__))
    default_config_path_in_script_dir = os.path.join(
        script_dir, MERMAID_CONFIG_FILENAME
    )

    if args.create_default_config:
        ensure_mermaid_config_exists(
            default_config_path_in_script_dir, args.max_text_size_for_default_config
        )
        print(
            f"Exiting after ensuring default mmdc config is present at: {default_config_path_in_script_dir}"
        )
        sys.exit(0)

    if args.html:
        if not args.output_file.lower().endswith(".html"):
            print(
                "WARNING: --html flag is set, but output file does not end with .html. Proceeding to generate HTML."
            )
            # Consider forcing .html or appending if not present
            # if not args.output_file.lower().endswith(".html"):
            # args.output_file += ".html" # Example: auto-append
        generate_html_viewer(args.input_file, args.output_file, args.js_max_text_size)
    else:
        # Determine which mmdc config file to use
        config_to_use_for_mmdc = None
        if args.mmdc_config:
            config_to_use_for_mmdc = args.mmdc_config
            if not os.path.exists(config_to_use_for_mmdc):
                print(
                    f"WARNING: Explicitly specified mmdc_config '{config_to_use_for_mmdc}' not found. Will proceed without it."
                )
                config_to_use_for_mmdc = None
        elif os.path.exists(default_config_path_in_script_dir):
            print(
                f"Found default mmdc config in script directory: {default_config_path_in_script_dir}"
            )
            config_to_use_for_mmdc = default_config_path_in_script_dir
        else:
            print(
                f"No custom mmdc config specified and '{default_config_path_in_script_dir}' not found for mmdc."
            )

        if not find_mmdc():
            print(
                "mmdc not found. Cannot render directly. Consider using the --html flag."
            )
            sys.exit(1)

        render_mermaid_cli(
            args.input_file, args.output_file, args.png_scale, config_to_use_for_mmdc
        )
