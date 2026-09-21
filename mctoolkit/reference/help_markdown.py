# This file is part of MCToolkit.
# Copyright (C) 2026 Hunter Picard
#
# MCToolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MCToolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit.  If not, see <https://www.gnu.org/licenses/>.

"""Load and render bundled Markdown help topics for the in-app User Manual."""

from __future__ import annotations

import html
import re
from pathlib import Path

from ..platform_support.bundled_paths import resources_dir

_GUIDE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def help_dir() -> Path:
    return resources_dir() / "help"


def help_markdown_path(guide_id: str) -> Path:
    gid = (guide_id or "").strip()
    if not _GUIDE_ID_RE.match(gid):
        raise ValueError(f"Invalid guide id: {guide_id!r}")
    return help_dir() / f"{gid}.md"


def load_help_markdown(guide_id: str) -> str | None:
    """Return Markdown body for ``guide_id``, or ``None`` if the file is missing."""
    path = help_markdown_path(guide_id)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def _inline_md(text: str) -> str:
    """Escape HTML then apply a small set of inline Markdown transforms."""
    s = html.escape(text, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def markdown_to_html_fragment(md: str) -> str:
    """
    Convert a constrained Markdown subset to an HTML fragment.

    Supports: AT1–H3, paragraphs, unordered/ordered lists, blockquotes (tips),
    fenced code blocks, horizontal rules, and simple pipe tables.
    """
    lines = (md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i = 0
    in_ul = False
    in_ol = False
    in_p = False
    in_code = False
    code_lines: list[str] = []

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def close_p() -> None:
        nonlocal in_p
        if in_p:
            out.append("</p>")
            in_p = False

    def start_p() -> None:
        nonlocal in_p
        if not in_p:
            out.append("<p>")
            in_p = True

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()

        if in_code:
            if line.startswith("```"):
                body = html.escape("\n".join(code_lines), quote=False)
                out.append(f"<pre><code>{body}</code></pre>")
                code_lines = []
                in_code = False
            else:
                code_lines.append(raw)
            i += 1
            continue

        if line.startswith("```"):
            close_p()
            close_lists()
            in_code = True
            code_lines = []
            i += 1
            continue

        if not line.strip():
            close_p()
            close_lists()
            i += 1
            continue

        if line.strip() in ("---", "***", "___"):
            close_p()
            close_lists()
            out.append("<hr/>")
            i += 1
            continue

        # Pipe table: header | --- | rows
        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+:?\s*\|", lines[i + 1]):
            close_p()
            close_lists()
            table_rows: list[str] = []
            while i < len(lines) and "|" in lines[i]:
                row = lines[i].strip()
                if re.match(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$", row):
                    i += 1
                    continue
                cells = [c.strip() for c in row.strip("|").split("|")]
                table_rows.append(cells)
                i += 1
            if table_rows:
                out.append("<table>")
                for ridx, cells in enumerate(table_rows):
                    tag = "th" if ridx == 0 else "td"
                    out.append("<tr>")
                    for c in cells:
                        out.append(f"<{tag}>{_inline_md(c)}</{tag}>")
                    out.append("</tr>")
                out.append("</table>")
            continue

        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            close_p()
            close_lists()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline_md(m.group(2).strip())}</h{level}>")
            i += 1
            continue

        if line.startswith("> "):
            close_p()
            close_lists()
            tip_bits = [line[2:]]
            i += 1
            while i < len(lines) and lines[i].startswith("> "):
                tip_bits.append(lines[i][2:])
                i += 1
            tip_html = " ".join(_inline_md(t.strip()) for t in tip_bits if t.strip())
            out.append(f'<div class="tip">{tip_html}</div>')
            continue

        m = re.match(r"^[-*]\s+(.*)$", line)
        if m:
            close_p()
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline_md(m.group(1))}</li>")
            i += 1
            continue

        m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m:
            close_p()
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_inline_md(m.group(2))}</li>")
            i += 1
            continue

        close_lists()
        start_p()
        out.append(_inline_md(line.strip()) + " ")
        i += 1

    close_p()
    close_lists()
    if in_code:
        body = html.escape("\n".join(code_lines), quote=False)
        out.append(f"<pre><code>{body}</code></pre>")
    return "".join(out)


def missing_topic_html(guide_id: str) -> str:
    safe = html.escape(guide_id or "(none)")
    return (
        f"<h2>Topic unavailable</h2>"
        f"<p>The help topic <code>{safe}</code> could not be loaded. "
        f"The Markdown file may be missing from the installation.</p>"
    )
