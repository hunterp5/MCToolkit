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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Shared Qt WebEngine shell for interactive Plotly (Plotter + PlotlyInteractiveView)."""

from __future__ import annotations

from pathlib import Path

from plotly.offline import get_plotlyjs

_SHELL_HTML_PATH = Path(__file__).with_name("plotly_shell.html")


def sanitized_plotly_js() -> str:
    """Plotly.js safe for embedding in HTML (Qt/Chromium quirks)."""
    return get_plotlyjs().replace(":focus-visible", ":focus").replace("</script>", "<\\/script>")


def interactive_plot_shell_html() -> str:
    """HTML document with Plotly, QWebChannel bridge, selection, and Plotter-specific click handlers."""
    from ..config import load_config

    plotly_js = sanitized_plotly_js()
    overlay_max = int(load_config().plot_selection_overlay_max_points)
    template = _SHELL_HTML_PATH.read_text(encoding="utf-8")
    return template.replace("__PLOTLY_JS__", plotly_js).replace("__OVERLAY_MAX__", str(overlay_max))


def write_interactive_plot_shell(path: Path) -> None:
    path.write_text(interactive_plot_shell_html(), encoding="utf-8")
