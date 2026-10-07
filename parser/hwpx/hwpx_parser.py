from pathlib import Path

from hwpx.tools.markdown_export import export_markdown



def parser_hwpx_md(
        hwpx_path:Path):
    return export_markdown(hwpx_path)



