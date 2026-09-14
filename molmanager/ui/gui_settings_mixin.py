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

"""Settings menu (GUI theme and hotkeys) for the main window."""

from __future__ import annotations

from PyQt5.QtGui import QFont, QPalette
from PyQt5.QtWidgets import QAction, QActionGroup, QApplication, QDialog, QFrame, QMenu

from .hotkeys import apply_hotkey_to_action
from .theme import (
    THEME_DARK,
    THEME_GROOVY,
    THEME_LIGHT,
    apply_application_font_pt,
    apply_application_theme,
    current_theme_name,
    custom_theme_display_name,
    default_app_font_pt,
    default_table_font_pt,
    filter_card_stylesheet,
    filter_panel_stylesheet,
    is_custom_theme_id,
    list_custom_theme_names,
    load_saved_app_font_pt,
    load_saved_table_font_pt,
    load_saved_theme_name,
    load_status_bar_visible,
    make_custom_theme_id,
    save_app_font_pt,
    save_status_bar_visible,
    save_table_font_pt,
    save_theme_name,
)


class GuiSettingsMixin:
    """Settings → GUI: light / dark / groovy / named custom themes."""

    def _init_gui_settings(self) -> None:
        self._hotkey_actions: dict[str, QAction] = {}
        self._app_font_pt = load_saved_app_font_pt()
        apply_application_font_pt(self._app_font_pt)
        self._gui_theme = load_saved_theme_name()
        apply_application_theme(QApplication.instance(), self._gui_theme)
        self._act_theme_light = QAction("Light Mode", self, checkable=True)
        self._act_theme_dark = QAction("Dark Mode", self, checkable=True)
        self._act_theme_groovy = QAction("Groovy Mode", self, checkable=True)
        self._theme_action_group = QActionGroup(self)
        self._theme_action_group.setExclusive(True)
        self._theme_action_group.addAction(self._act_theme_light)
        self._theme_action_group.addAction(self._act_theme_dark)
        self._theme_action_group.addAction(self._act_theme_groovy)
        self._act_theme_light.triggered.connect(lambda: self._set_gui_theme(THEME_LIGHT))
        self._act_theme_dark.triggered.connect(lambda: self._set_gui_theme(THEME_DARK))
        # Always re-apply so choosing Groovy again (after another mode) rolls a new palette.
        self._act_theme_groovy.triggered.connect(lambda: self._set_gui_theme(THEME_GROOVY))
        self._custom_theme_actions: dict[str, QAction] = {}
        self._gui_menu: QMenu | None = None
        self._act_customize_colors = QAction(
            "Custom Colors…", self, triggered=self.open_custom_theme_dialog
        )
        self._act_customize_colors.setToolTip("Create, edit, or delete named custom color schemes.")
        self._sync_theme_menu_checks()
        self._refresh_filter_card_styles()
        self._table_font_pt = load_saved_table_font_pt()
        self._apply_table_font()

    def _bind_hotkey(self, action_id: str, action: QAction) -> QAction:
        """Register *action* for persistence and apply the saved shortcut."""
        self._hotkey_actions[action_id] = action
        apply_hotkey_to_action(action_id, action)
        return action

    def _apply_all_hotkeys(self) -> None:
        for action_id, action in self._hotkey_actions.items():
            apply_hotkey_to_action(action_id, action)

    def open_hotkeys_dialog(self) -> None:
        from .dialogs.hotkeys_dialog import HotkeysDialog

        dlg = HotkeysDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        self._apply_all_hotkeys()
        if hasattr(self, "status_label"):
            self.status_label.setText("Hotkeys updated.")

    def open_structure_settings_dialog(self) -> None:
        from ..display_constants import structure_depiict_height, structure_depiict_width
        from .dialogs.structure_settings import StructureSettingsDialog

        prev_w = structure_depiict_width()
        prev_h = structure_depiict_height()
        dlg = StructureSettingsDialog(prev_w, prev_h, self)
        if hasattr(self, "apply_structure_table_layout"):
            dlg.size_previewed.connect(self._preview_structure_depiict_size)
        if dlg.exec_() == QDialog.Accepted:
            self._apply_structure_depiict_size(
                dlg.selected_width(), dlg.selected_height(), persist=True
            )
        elif hasattr(self, "apply_structure_depiict_size"):
            self._apply_structure_depiict_size(prev_w, prev_h, persist=False)
        if hasattr(self, "status_label"):
            self.status_label.setText(
                f"Structure image size — {structure_depiict_width()}×{structure_depiict_height()} px"
            )

    def _preview_structure_depiict_size(self, width: int, height: int) -> None:
        if hasattr(self, "apply_structure_depiict_size"):
            self.apply_structure_depiict_size(width, height, persist=False)

    def _apply_structure_depiict_size(
        self, width: int, height: int, *, persist: bool = True
    ) -> None:
        if hasattr(self, "apply_structure_depiict_size"):
            self.apply_structure_depiict_size(width, height, persist=persist)

    def open_font_dialog(self) -> None:
        from .dialogs.font_settings import FontSettingsDialog

        prev_app_pt = int(getattr(self, "_app_font_pt", 0) or default_app_font_pt())
        prev_table_pt = int(getattr(self, "_table_font_pt", 0) or default_table_font_pt())
        dlg = FontSettingsDialog(prev_app_pt, prev_table_pt, self)
        dlg.app_font_size_previewed.connect(self._preview_app_font)
        dlg.table_font_size_previewed.connect(self._preview_table_font)
        if dlg.exec_() == QDialog.Accepted:
            self._set_app_font_pt(dlg.selected_app_point_size())
            self._set_table_font_pt(dlg.selected_table_point_size())
        else:
            self._set_app_font_pt(prev_app_pt, persist=False)
            self._set_table_font_pt(prev_table_pt, persist=False)
        if hasattr(self, "status_label"):
            self.status_label.setText(
                f"Font size — application: {self._app_font_pt} pt, table: {self._table_font_pt} pt"
            )

    def _init_settings_menu(self, menubar) -> None:
        settings_menu = menubar.addMenu("&Settings")
        self._gui_menu = settings_menu.addMenu("&GUI")
        self._rebuild_gui_theme_menu()
        settings_menu.addSeparator()
        settings_menu.addAction(
            QAction("&Structure…", self, triggered=self.open_structure_settings_dialog)
        )
        settings_menu.addAction(QAction("&Font…", self, triggered=self.open_font_dialog))
        settings_menu.addAction(QAction("&Hotkeys…", self, triggered=self.open_hotkeys_dialog))
        settings_menu.addSeparator()
        self._act_status_bar = QAction("Status Bar", self, checkable=True)
        self._act_status_bar.setToolTip(
            "Show or hide the status bar at the bottom of the window (messages and memory use)."
        )
        self._act_status_bar.setChecked(load_status_bar_visible())
        self._act_status_bar.toggled.connect(self._on_status_bar_toggled)
        settings_menu.addAction(self._act_status_bar)
        self._apply_status_bar_visible(self._act_status_bar.isChecked(), persist=False)

    def _on_status_bar_toggled(self, checked: bool) -> None:
        self._apply_status_bar_visible(bool(checked), persist=True)

    def _apply_status_bar_visible(self, visible: bool, *, persist: bool = True) -> None:
        overlay = False
        overlay_fn = getattr(self, "_workspace_loading_overlay_visible", None)
        if callable(overlay_fn):
            overlay = bool(overlay_fn())
        show = bool(visible) and not overlay
        host = getattr(self, "_status_host", None)
        if host is not None:
            host.setVisible(show)
        if persist:
            save_status_bar_visible(bool(visible))
        timer = getattr(self, "_memory_status_timer", None)
        if timer is None:
            return
        if show:
            from ..config import load_config

            cfg = load_config()
            if cfg.status_memory_enabled:
                mem_label = getattr(self, "_memory_status_label", None)
                if mem_label is not None:
                    mem_label.show()
                timer.start()
                refresh = getattr(self, "_refresh_status_memory_label", None)
                if callable(refresh):
                    refresh()
        else:
            timer.stop()

    def _rebuild_gui_theme_menu(self) -> None:
        menu = getattr(self, "_gui_menu", None)
        if menu is None:
            return
        menu.clear()
        for act in list(getattr(self, "_custom_theme_actions", {}).values()):
            self._theme_action_group.removeAction(act)
        self._custom_theme_actions = {}

        menu.addAction(self._act_theme_light)
        menu.addAction(self._act_theme_dark)
        menu.addAction(self._act_theme_groovy)

        names = list_custom_theme_names()
        if names:
            menu.addSeparator()
            for name in names:
                act = QAction(name, self, checkable=True)
                theme_id = make_custom_theme_id(name)
                act.triggered.connect(lambda *_a, tid=theme_id: self._set_gui_theme(tid))
                self._theme_action_group.addAction(act)
                self._custom_theme_actions[name] = act
                menu.addAction(act)

        menu.addSeparator()
        menu.addAction(self._act_customize_colors)
        self._sync_theme_menu_checks()

    def _sync_theme_menu_checks(self) -> None:
        name = current_theme_name()
        self._act_theme_light.setChecked(name == THEME_LIGHT)
        self._act_theme_dark.setChecked(name == THEME_DARK)
        self._act_theme_groovy.setChecked(name == THEME_GROOVY)
        custom_name = custom_theme_display_name(name) if is_custom_theme_id(name) else None
        for label, act in getattr(self, "_custom_theme_actions", {}).items():
            act.setChecked(custom_name is not None and label == custom_name)

    def open_custom_theme_dialog(self) -> bool:
        """Edit named custom themes; on Save apply that theme. Returns True if a theme was saved."""
        from .dialogs.custom_theme import CustomThemeDialog

        dlg = CustomThemeDialog(self)
        accepted = dlg.exec_() == QDialog.Accepted
        deleted = dlg.deleted_theme_name()
        saved = dlg.saved_theme_name() if accepted else None

        if deleted:
            cur = current_theme_name()
            if is_custom_theme_id(cur) and custom_theme_display_name(cur) == deleted:
                self._set_gui_theme(THEME_LIGHT)

        if deleted or saved:
            self._rebuild_gui_theme_menu()

        if saved:
            self._set_gui_theme(make_custom_theme_id(saved))
            if hasattr(self, "status_label"):
                self.status_label.setText(f'Saved custom theme "{saved}".')
            return True

        if deleted and hasattr(self, "status_label"):
            self.status_label.setText(f'Deleted custom theme "{deleted}".')
        return False

    def refresh_theme(self) -> None:
        """Hook for ``refresh_open_windows_theme`` — refresh main-window chrome."""
        self._refresh_filter_card_styles()
        self._refresh_structure_delegate_theme()
        self._apply_table_font()
        self._refresh_workspace_pane_theme()
        table = getattr(self, "table", None)
        if table is not None:
            table.viewport().update()

    def _refresh_workspace_pane_theme(self) -> None:
        layout_mgr = getattr(self, "_workspace_layout", None)
        if layout_mgr is None:
            return
        refresh = getattr(layout_mgr, "refresh_theme", None)
        if callable(refresh):
            refresh()

    def _set_gui_theme(self, theme: str) -> None:
        theme = apply_application_theme(QApplication.instance(), theme)
        self._gui_theme = theme
        save_theme_name(theme)
        self._sync_theme_menu_checks()
        # apply_application_theme already refreshes open windows; ensure main chrome is current.
        self.refresh_theme()
        apply_application_font_pt(int(getattr(self, "_app_font_pt", 0) or default_app_font_pt()))

    def _preview_app_font(self, pt: int) -> None:
        self._app_font_pt = int(pt)
        apply_application_font_pt(self._app_font_pt)
        self._apply_table_font()

    def _set_app_font_pt(self, pt: int, *, persist: bool = True) -> None:
        self._app_font_pt = apply_application_font_pt(int(pt))
        if persist:
            save_app_font_pt(self._app_font_pt)
        self._apply_table_font()
        self._refresh_workspace_pane_theme()

    def _apply_table_font(self) -> None:
        """Set the table font point size on the view and its headers (theme-independent)."""
        table = getattr(self, "table", None)
        if table is None:
            return
        pt = int(getattr(self, "_table_font_pt", 0) or default_table_font_pt())
        font = QFont(table.font())
        font.setPointSize(pt)
        table.setFont(font)
        for header in (table.horizontalHeader(), table.verticalHeader()):
            if header is not None:
                header.setFont(font)
        table.viewport().update()

    def _preview_table_font(self, pt: int) -> None:
        self._table_font_pt = int(pt)
        self._apply_table_font()

    def _set_table_font_pt(self, pt: int, *, persist: bool = True) -> None:
        self._table_font_pt = int(pt)
        if persist:
            save_table_font_pt(self._table_font_pt)
        self._apply_table_font()

    def _refresh_filter_card_styles(self) -> None:
        panel = getattr(self, "f_panel", None)
        if panel is not None:
            panel.setStyleSheet(filter_panel_stylesheet())
        qss = filter_card_stylesheet()
        for filt in getattr(self, "filters", []):
            if isinstance(filt, QFrame) and filt.objectName() == "FilterCard":
                filt.setStyleSheet(qss)
                refresh = getattr(filt, "refresh_theme_styles", None)
                if callable(refresh):
                    refresh()

    def _refresh_structure_delegate_theme(self) -> None:
        """Structure column uses theme base for placeholders; rendered cells stay white."""
        if not hasattr(self, "table") or self._table_model is None:
            return
        from .compound_table_model import CompoundTableModel, StructureDelegate

        delg = getattr(self, "_structure_delegate", None)
        if not isinstance(delg, StructureDelegate):
            delg = StructureDelegate(self.table, self._table_model)
            self._structure_delegate = delg
        else:
            delg.set_compound_model(self._table_model)
        delg.set_cell_background(self.palette().color(QPalette.Base))
        self.table.setItemDelegateForColumn(CompoundTableModel.STRUCTURE_COL, delg)
