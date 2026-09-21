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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MCToolkit. If not, see <https://www.gnu.org/licenses/>.

"""Install ``menu_spec.MenuItem`` trees onto a ``QMenuBar`` / ``QMenu``."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QMenuBar

from .menu_spec import (
    KIND_ACTION,
    KIND_REDO,
    KIND_SEPARATOR,
    KIND_SETTINGS,
    KIND_SUBMENU,
    KIND_UNDO,
    MenuItem,
)


def install_menu_specs(window: Any, menubar: QMenuBar, specs: Sequence[MenuItem]) -> None:
    """Create menus and actions on *menubar* from *specs*, binding slots on *window*."""
    for item in specs:
        if item.kind == KIND_SETTINGS:
            window._init_settings_menu(menubar)
            continue
        if item.kind != KIND_SUBMENU:
            raise ValueError(f"top-level menu item must be a submenu or settings, got {item.kind}")
        menu = menubar.addMenu(item.title)
        _install_into_menu(window, menu, item)
    # PySide6 drops QAction wrappers from addMenu unless Python holds them;
    # collecting the wrapper deletes the C++ QMenu (including window._help_menu).
    window._qt_kept_menubar_actions = list(menubar.actions())


def _install_into_menu(window: Any, menu: QMenu, spec: MenuItem) -> None:
    if spec.tooltips_visible:
        menu.setToolTipsVisible(True)
    if spec.attr:
        setattr(window, spec.attr, menu)
    if spec.about_to_show:
        menu.aboutToShow.connect(getattr(window, spec.about_to_show))
    for item in spec.items:
        if item.kind == KIND_SEPARATOR:
            menu.addSeparator()
        elif item.kind == KIND_SUBMENU:
            child = menu.addMenu(item.title)
            acts = menu.actions()
            if acts:
                kept = getattr(window, "_qt_kept_menu_actions", None)
                if kept is None:
                    kept = []
                    window._qt_kept_menu_actions = kept
                kept.append(acts[-1])
            _install_into_menu(window, child, item)
        elif item.kind == KIND_UNDO:
            act = window._bind_hotkey(item.hotkey, window._undo_stack.createUndoAction(window))
            menu.addAction(act)
            if item.add_to_window:
                window.addAction(act)
        elif item.kind == KIND_REDO:
            act = window._bind_hotkey(item.hotkey, window._undo_stack.createRedoAction(window))
            menu.addAction(act)
            if item.add_to_window:
                window.addAction(act)
        elif item.kind == KIND_ACTION:
            menu.addAction(_make_action(window, item))
        else:
            raise ValueError(f"unsupported menu item kind {item.kind!r}")


def _slot_callable(window: Any, item: MenuItem) -> Callable[..., None] | None:
    if item.call_with_window == "user_guide":
        from ..user_guides import open_user_guide_dialog

        return lambda *_checked, w=window: open_user_guide_dialog(w)
    if item.call_with_window == "citations":
        from ..citations_dialog import open_citations_dialog

        return lambda *_checked, w=window: open_citations_dialog(w)
    if not item.slot:
        return None
    method = getattr(window, item.slot)
    args = item.args
    return lambda *_checked, m=method, a=args: m(*a)


def _make_action(window: Any, item: MenuItem) -> QAction:
    act = QAction(item.title, window)
    if item.tooltip:
        act.setToolTip(item.tooltip)
    if not item.enabled:
        act.setEnabled(False)
    fn = _slot_callable(window, item)
    if fn is not None:
        act.triggered.connect(fn)
    if item.hotkey:
        window._bind_hotkey(item.hotkey, act)
    if item.attr:
        setattr(window, item.attr, act)
    if item.add_to_window:
        window.addAction(act)
    return act
