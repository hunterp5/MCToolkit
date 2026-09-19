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

"""Decisions about what the application should do next, independent of the UI.

A workflow module decides; it never presents. Three rules keep this layer useful:

1. Take plain data or a narrow protocol. Never accept the main window / ``AppKernel``.
2. Return a result object. Never raise a dialog, touch a widget, or import ``PyQt5``.
3. Let the UI adapter read widgets, call the workflow, and render the result.

The distinction from ``molmanager/services/``: a service computes a value from its
inputs, while a workflow branches on what the app should do. If there is no such
branch, the code belongs in ``services/``.
"""
