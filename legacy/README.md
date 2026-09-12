# Legacy and prototype code

This folder preserves the earlier generations of the toolkit. The project was built
incrementally while requirements were still being discovered, so several modules were
written, used, and then superseded by a cleaner design. They are kept here on purpose:

- to document the real evolution of the system,
- to show what was tried and why it changed,
- so that the final architecture can be read as a sequence of decisions rather than a
  single big-bang design.

Nothing in this folder is required to run the current pipeline. Treat it as an archive.

| File | What it was | Why it was superseded |
| --- | --- | --- |
| new.py | First working prototype: a FreeSimpleGUI console-cable collector that talked to switches over serial and captured Wave 1 / Wave 2 logs. | Replaced by main_app.py once the metadata model, location structure and logging conventions stabilised. |
| new1.py | Second prototype: threaded, multi-instance collector with ntc-templates parsing and a more complete UI. | Same reason; it proved the collection model but was not maintainable enough to be the product. |
| organize_data.py | Original "scan logs, group by location, build LLM input packages" utility. | Superseded by unified_processor.py, which resolves paths from metadata and standardises package assembly. |
| extract_macs.py | Experiment: parse MAC address tables with TextFSM / ntc-templates instead of an LLM. | Superseded by Stage 2 of the LLM pipeline, which handled vendor variation far better. |
| extract_arps.py | Experiment: standalone ARP table parser. | Superseded by the LLM pipeline and the arp_table loader. |
| build1.bat | PyInstaller build script for the new1.py prototype. | Replaced by build.bat / main_app.spec. |
| new1.spec | PyInstaller spec for the new1.py prototype (local Python path removed). | Replaced by main_app.spec. |
| 1zip.bat | Helper that bundled data + outputs into a zip for transfer. | Superseded by normal repository and artefact handling. |
| export_lab_area_to_excel.TRUNCATED.py | A half-written twin of export_all_devices_by_site.py, cut off mid-SQL. It never parsed or ran. | Archived for completeness; the working exporter is netsurvey/reporting/export_all_devices_by_site.py. |

Note on packaging: new1.spec originally contained a machine-specific Python path. That
path has been replaced with a placeholder, and no personal or employer data remains.

Note on imports: these prototypes import config, utils and data_manager by their old
root-level names, because they predate the netsurvey package refactor. They are archived
evidence and are not part of the build; the current equivalents live under netsurvey/.
