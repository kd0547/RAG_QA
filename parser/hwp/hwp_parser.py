import io
from pathlib import Path
from contextlib import closing
from hwp5.hwp5txt import TextTransform
from hwp5.xmlmodel import Hwp5File

def parser_hwp_md(hwp_path):
    out = io.BytesIO()
    with closing(Hwp5File(str(hwp_path))) as f:
        TextTransform().transform_hwp5_to_text(f, out)
    return out.getvalue().decode("utf-8")


