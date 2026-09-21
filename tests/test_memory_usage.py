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

from __future__ import annotations

from mctoolkit.platform_support.memory_usage import (
    current_process_rss_bytes,
    format_memory_bytes,
    format_process_memory_status,
)


def test_format_memory_bytes() -> None:
    assert format_memory_bytes(0) == "0 B"
    assert format_memory_bytes(512) == "512 B"
    assert format_memory_bytes(1024) == "1 KiB"
    assert format_memory_bytes(1536) == "2 KiB"
    assert format_memory_bytes(5 * 1024 * 1024) == "5.0 MiB"
    assert format_memory_bytes(3 * 1024 * 1024 * 1024) == "3.0 GiB"


def test_current_process_rss_bytes_positive() -> None:
    rss = current_process_rss_bytes()
    assert rss is None or rss > 0


def test_format_process_memory_status() -> None:
    text = format_process_memory_status()
    assert text is None or text.startswith("Mem: ")
