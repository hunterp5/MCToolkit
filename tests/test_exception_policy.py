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

"""Tests for intentional exception-swallow helpers."""

from __future__ import annotations

import logging

from molmanager.platform_support.exception_policy import log_swallowed_exception


def test_log_swallowed_exception_records_exc_info(caplog):
    log = logging.getLogger("molmanager.platform_support.exception_policy.test")
    with caplog.at_level(logging.DEBUG, logger=log.name):
        try:
            raise ValueError("boom")
        except ValueError:
            log_swallowed_exception(log, "swallowed for test")
    assert any("swallowed for test" in r.message for r in caplog.records)
