from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class TableGrid:
    title: Optional[str]
    covered:set
    table_cells: list[TableCell]


@dataclass
class TableCell:
    row: int
    col: int
    text: str
    rowspan: int
    colspan: int
