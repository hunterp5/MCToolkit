# This file is part of MolManager.
# Copyright (C) 2026 Hunter Picard
#
# MolManager is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MolManager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""One-off helper: split chemistry_mixin.py into sub-mixin modules."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "molmanager" / "ui" / "main_window" / "chemistry_mixin.py"
OUT_DIR = SRC.parent

HEADER_END = 65  # line before `class ChemistryMixin`
RANGES: list[tuple[str, str, int, int]] = [
    ("plot_tools_mixin.py", "PlotToolsMixin", 69, 365),
    ("ingest_render_mixin.py", "IngestRenderMixin", 367, 900),
    ("prepare_structures_mixin.py", "PrepareStructuresMixin", 902, 1683),
    ("conformers_descriptors_mixin.py", "ConformersDescriptorsMixin", 1685, 2060),
    ("fragment_tools_mixin.py", "FragmentToolsMixin", 2062, 2379),
    ("tools_sql_predict_mixin.py", "ToolsSqlPredictMixin", 2381, 10_000),
]

lines = SRC.read_text(encoding="utf-8").splitlines()
preamble = "\n".join(lines[:HEADER_END]) + "\n\n"
body_lines = lines[HEADER_END:]
for i, line in enumerate(body_lines):
    if line.startswith("class ChemistryMixin"):
        body_lines = body_lines[i + 1 :]
        break


CLASS_LINE_NO = 68  # ``class ChemistryMixin`` in the monolithic file


def slice_methods(start: int, end: int) -> str:
    """Extract method lines (1-based inclusive line numbers in the monolithic file)."""
    i0 = start - CLASS_LINE_NO - 1
    i1 = end - CLASS_LINE_NO
    chunk = body_lines[i0:i1]
    return "\n".join(chunk)


for filename, class_name, start, end in RANGES:
    methods = slice_methods(start, end)
    doc = {
        "plot_tools_mixin.py": "Plot docking, plot↔table sync, and plot panel UI.",
        "ingest_render_mixin.py": "File ingest, SQLite rebuild, and 2D structure rendering.",
        "prepare_structures_mixin.py": "Fast prepare, disconnect/neutralize, and render-2D batch tools.",
        "conformers_descriptors_mixin.py": "Conformers, superposition, and descriptor calculation.",
        "fragment_tools_mixin.py": "BRICS/RECAP/R-group fragment tools.",
        "tools_sql_predict_mixin.py": "Calculator, SQL load, external DB, and prediction dialogs.",
    }[filename]
    text = f'"""{doc}"""\n\n{preamble}class {class_name}:\n{methods}\n'
    (OUT_DIR / filename).write_text(text, encoding="utf-8")
    print(f"wrote {filename} ({len(text)} bytes)")

composite = '''"""Chemistry tools, ingest, rendering, and prediction entry points for the main window."""

from __future__ import annotations

from .conformers_descriptors_mixin import ConformersDescriptorsMixin
from .fragment_tools_mixin import FragmentToolsMixin
from .ingest_render_mixin import IngestRenderMixin
from .plot_tools_mixin import PlotToolsMixin
from .prepare_structures_mixin import PrepareStructuresMixin
from .tools_sql_predict_mixin import ToolsSqlPredictMixin


class ChemistryMixin(
    PlotToolsMixin,
    IngestRenderMixin,
    PrepareStructuresMixin,
    ConformersDescriptorsMixin,
    FragmentToolsMixin,
    ToolsSqlPredictMixin,
):
    """Composite mixin: plot UI, ingest/render, structure prep, conformers, fragments, SQL/predictions."""
'''
(SRC.parent / "chemistry_mixin.py").write_text(composite, encoding="utf-8")
print("wrote chemistry_mixin.py (composite)")
