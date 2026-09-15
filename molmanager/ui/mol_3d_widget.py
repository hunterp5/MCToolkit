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

"""Qt widgets that host the ligand 3Dmol.js viewer."""

from __future__ import annotations

import base64
import json
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt5.QtCore import QEvent, QItemSelectionModel, QTemporaryDir, QTimer, QUrl, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from rdkit import Chem

from .dockable_plot import (
    make_add_to_main_button,
    make_plot_options_button,
    make_plot_options_dialog,
    make_send_window_button,
    show_plot_options_dialog,
    style_plot_footer_text_button,
)
from .mol_3d_html import (
    _BUNDLED_3DMOL,
    _cdn_embed_fallback_html,
    _cdn_fallback_html,
    _cdn_fallback_html_multiconf,
    _mol_block_b64,
    _offline_embed_index_html,
    _offline_index_html,
    _offline_index_html_multiconf,
    _wire_webengine_console_logger,
    bundled_3dmol_available,
    conf_legend_entries,
    distinct_superpose_colors,
)

if TYPE_CHECKING:
    from .mol_3d_dialog import Molecule3DViewerDialog
from .mol_3d_prepare import prepare_mol_3d
from .property_columns_panel import (
    PROPERTY_COLUMN_SLOT_COUNT,
    PROPERTY_COLUMN_SLOT_MAX,
    PropertyColumnsPanel,
)
from .qt_widget_utils import qobject_is_deleted
from .widgets import NumericTableWidgetItem

logger = logging.getLogger(__name__)


def _molecule_3d_viewer_dialog_cls() -> type:
    """Lazy import to avoid a widget↔dialog cycle at module load."""
    from .mol_3d_dialog import Molecule3DViewerDialog

    return Molecule3DViewerDialog


def _multi_conf_block_count(blocks_json_b64: str | None) -> int:
    """Number of packed conformer mol-blocks in a viewer payload."""
    raw = (blocks_json_b64 or "").strip()
    if not raw:
        return 0
    try:
        blocks = json.loads(base64.b64decode(raw.encode("ascii")))
    except Exception:
        return 0
    return len(blocks) if isinstance(blocks, list) else 0


def _layout_visible_min_width(layout) -> int:
    """Sum size hints of visible widgets in a box layout, including spacing and margins."""
    if layout is None:
        return 0
    try:
        margins = layout.contentsMargins()
        total = int(margins.left() + margins.right())
        spacing = int(layout.spacing())
    except Exception:
        total = 0
        spacing = 0
    n_vis = 0
    try:
        count = int(layout.count())
    except Exception:
        return total
    for i in range(count):
        item = layout.itemAt(i)
        if item is None:
            continue
        w = item.widget()
        if w is None or w.isHidden():
            continue
        n_vis += 1
        hint = max(int(w.sizeHint().width()), int(w.minimumSizeHint().width()), 0)
        total += hint
    if n_vis > 1:
        total += spacing * (n_vis - 1)
    return total


class Molecule3DEmbedView(QWidget):
    """
    Sketcher side-panel 3Dmol view: no atom-info boxes or mouse-controls overlay.

    Call ``set_molecule`` to refresh after sketch edits (ETKDG embed + MMFF/UFF).
    The WebEngine page is created lazily on first show so QtWebEngine can preload at app start.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumWidth(420)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._viewer_tmp: QTemporaryDir | None = None
        self._web_ready = False
        self._pending_b64: str | None = None
        self._web = None
        self._bootstrapped = False
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.setInterval(50)
        self._refit_timer.timeout.connect(self.refit_view)
        self._status = QLabel("3D preview", self)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("color: palette(mid); padding: 8px;")

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self._root.addWidget(self._status)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._ensure_web()
        self.schedule_refit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._web_ready:
            self.schedule_refit()

    def schedule_refit(self) -> None:
        """Debounce resize/zoom so the model fills the frame after layout settles."""
        self._refit_timer.start()

    def refit_view(self) -> None:
        """Resize the WebGL canvas and zoom so the whole structure fits with padding."""
        if self._web is None or not self._web_ready:
            return
        try:
            self._web.page().runJavaScript("if (window.molmanagerRefit) window.molmanagerRefit();")
        except Exception:
            logger.debug("3D embed refit failed", exc_info=True)

    def _ensure_web(self) -> None:
        if self._bootstrapped:
            return
        self._bootstrapped = True
        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineSettings, QWebEngineView

            web = QWebEngineView(self)
            web.setContextMenuPolicy(Qt.NoContextMenu)
            _wire_webengine_console_logger(web)
            try:
                s = web.settings()
                s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
                s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
                s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            except Exception:
                pass
            web.loadFinished.connect(self._on_load_finished)
            if bundled_3dmol_available():
                self._viewer_tmp = QTemporaryDir()
                if not self._viewer_tmp.isValid():
                    raise OSError("Could not create a temporary directory for the 3D viewer.")
                tmp = Path(self._viewer_tmp.path())
                shutil.copy2(_BUNDLED_3DMOL, tmp / "3Dmol-min.js")
                index = tmp / "index.html"
                index.write_text(_offline_embed_index_html(""), encoding="utf-8")
                web.load(QUrl.fromLocalFile(str(index.resolve())))
            else:
                web.setHtml(_cdn_embed_fallback_html(""), QUrl("https://3dmol.org/"))
            self._web = web
            self._status.hide()
            self._root.addWidget(web, 1)
        except Exception as e:
            logger.warning("Sketcher 3D embed unavailable: %s", e, exc_info=True)
            self._status.setText(
                "3D preview unavailable.\nInstall matching PyQtWebEngine and restart with "
                "`python -m molmanager`."
            )

    def _on_load_finished(self, ok: bool) -> None:
        self._web_ready = bool(ok)
        if self._web_ready and self._pending_b64 is not None:
            b64 = self._pending_b64
            self._pending_b64 = None
            self._run_set_mol_b64(b64)
        if self._web_ready:
            self.schedule_refit()
            QTimer.singleShot(200, self.refit_view)

    def _run_set_mol_b64(self, b64: str) -> None:
        self._ensure_web()
        if self._web is None:
            return
        if not self._web_ready:
            self._pending_b64 = b64
            return
        js = f"if (window.molmanagerSetMolB64) window.molmanagerSetMolB64({json.dumps(b64)});"
        try:
            self._web.page().runJavaScript(js)
        except Exception:
            logger.debug("3D embed set_mol failed", exc_info=True)

    def clear(self) -> None:
        """Clear the displayed model."""
        self._run_set_mol_b64("")

    def set_molecule(self, mol: Chem.Mol | None, *, rebuild_3d: bool = True) -> None:
        """Embed *mol* in 3D and display it, or clear when *mol* is empty/invalid.

        When *rebuild_3d* is False and *mol* already has a 3D conformer (e.g. a docked
        ligand), that geometry is kept instead of running ETKDG again.
        """
        if mol is None or mol.GetNumAtoms() == 0:
            self.clear()
            return
        m3 = None
        if not rebuild_3d:
            try:
                if mol.GetNumConformers() >= 1 and mol.GetConformer().Is3D():
                    m3 = Chem.Mol(mol)
            except Exception:
                m3 = None
        if m3 is None:
            m3 = prepare_mol_3d(mol)
        if m3 is None:
            self.clear()
            return
        try:
            self._run_set_mol_b64(_mol_block_b64(m3))
            self.schedule_refit()
            QTimer.singleShot(150, self.refit_view)
        except Exception:
            logger.debug("3D embed encode failed", exc_info=True)
            self.clear()


_STRAIN_TABLE_BASE_HEADERS = (
    "Conf",
    "E",
    "ΔE vs ref",
    "ΔE vs min",
    "Pop. %",
    "RMSD",
)
_STRAIN_FF_COLUMN_ORDER = ("MMFF", "MMFF94s", "UFF")


def _fmt_strain_kcal(value) -> str:
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return ""


def populate_strain_energy_table(table: QTableWidget, overlay: dict | None) -> int:
    """Fill a results table with one row per conformer. Returns the row count."""
    table.setSortingEnabled(False)
    table.clearContents()
    table.setRowCount(0)
    if not isinstance(overlay, dict):
        table.setColumnCount(len(_STRAIN_TABLE_BASE_HEADERS))
        table.setHorizontalHeaderLabels(list(_STRAIN_TABLE_BASE_HEADERS))
        return 0
    energies = list(overlay.get("energies") or [])
    n = len(energies)
    deltas = list(overlay.get("deltas") or [])
    deltas_min = list(overlay.get("deltas_min") or [])
    pop_fracs = list(overlay.get("pop_fracs") or [])
    rmsds = list(overlay.get("rmsds") or [])
    primary_ff = str(overlay.get("ff") or "").strip()
    by_ff = overlay.get("energies_by_ff") if isinstance(overlay.get("energies_by_ff"), dict) else {}
    extra_ffs = [
        name
        for name in _STRAIN_FF_COLUMN_ORDER
        if name != primary_ff and isinstance(by_ff.get(name), list) and len(by_ff[name]) == n
    ]
    headers = list(_STRAIN_TABLE_BASE_HEADERS)
    for name in extra_ffs:
        headers.append(f"E ({name})")
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    if n <= 0:
        return 0

    def _at(seq: list, i: int):
        return seq[i] if i < len(seq) else None

    for i in range(n):
        table.insertRow(i)
        conf_item = NumericTableWidgetItem()
        conf_item.setData(Qt.EditRole, float(i + 1))
        conf_item.setText(str(i + 1))
        conf_item.setData(Qt.UserRole, int(i))
        table.setItem(i, 0, conf_item)

        e_item = NumericTableWidgetItem()
        e_item.setData(Qt.EditRole, float(energies[i]))
        e_item.setText(_fmt_strain_kcal(energies[i]))
        table.setItem(i, 1, e_item)

        d_ref = _at(deltas, i)
        d_item = NumericTableWidgetItem()
        if d_ref is None:
            d_item.setText("")
        else:
            d_item.setData(Qt.EditRole, float(d_ref))
            d_item.setText(_fmt_strain_kcal(d_ref))
        table.setItem(i, 2, d_item)

        d_min = _at(deltas_min, i)
        dm_item = NumericTableWidgetItem()
        if d_min is None:
            dm_item.setText("")
        else:
            dm_item.setData(Qt.EditRole, float(d_min))
            dm_item.setText(_fmt_strain_kcal(d_min))
        table.setItem(i, 3, dm_item)

        pop = _at(pop_fracs, i)
        p_item = NumericTableWidgetItem()
        if pop is None:
            p_item.setText("")
        else:
            pct = 100.0 * float(pop)
            p_item.setData(Qt.EditRole, pct)
            p_item.setText(f"{pct:.1f}")
        table.setItem(i, 4, p_item)

        rms = _at(rmsds, i)
        r_item = NumericTableWidgetItem()
        if rms is None:
            r_item.setText("")
        else:
            r_item.setData(Qt.EditRole, float(rms))
            r_item.setText(_fmt_strain_kcal(rms))
        table.setItem(i, 5, r_item)

        for col_i, name in enumerate(extra_ffs, start=6):
            vals = by_ff.get(name) or []
            extra = NumericTableWidgetItem()
            if i < len(vals):
                extra.setData(Qt.EditRole, float(vals[i]))
                extra.setText(_fmt_strain_kcal(vals[i]))
            table.setItem(i, col_i, extra)

    table.setSortingEnabled(True)
    return n


class Molecule3DViewerWidget(QWidget):
    """Interactive 3Dmol structure viewer; float or dock beside the compound table."""

    dockable_in_workspace = True

    def __init__(
        self,
        mol: Chem.Mol,
        parent_app: QWidget | None = None,
        *,
        window_title: str = "View in 3D",
        flat: bool = False,
        multi_conf_blocks_json_b64: str | None = None,
        multi_conf_initial_superpose: bool = False,
        multi_conf_strain_overlay_json_b64: str = "",
        multi_conf_initial_index: int = 0,
        export_parent_oid: int | None = None,
        export_confs_column: str = "confs",
        strain_overlay: dict | None = None,
        source_oid: int | None = None,
    ):
        super().__init__(None)
        self.parent_app = parent_app
        self._window_title = window_title
        self._flat = bool(flat)
        if source_oid is None:
            source_oid = export_parent_oid
        try:
            self._source_oid = int(source_oid) if source_oid is not None else None
        except (TypeError, ValueError):
            self._source_oid = None

        self._multi_conf_blocks_b64 = multi_conf_blocks_json_b64
        self._export_parent_oid = export_parent_oid
        self._export_confs_column = (export_confs_column or "confs").strip() or "confs"
        self._strain_overlay = dict(strain_overlay) if strain_overlay else None
        if self._strain_overlay is None and multi_conf_strain_overlay_json_b64:
            try:
                self._strain_overlay = json.loads(
                    base64.b64decode(multi_conf_strain_overlay_json_b64.encode("ascii"))
                )
            except Exception:
                self._strain_overlay = None
        try:
            self._initial_conf_index = max(0, int(multi_conf_initial_index))
        except (TypeError, ValueError):
            self._initial_conf_index = 0
        self._conf_mode_busy = False
        self._web_refit_size: tuple[int, int] | None = None
        self._web_did_initial_zoom = False

        mol_b64 = _mol_block_b64(mol) if multi_conf_blocks_json_b64 is None else ""
        self._viewer_tmp: QTemporaryDir | None = None
        self._prop_panel: PropertyColumnsPanel | None = None
        self._prop_refresh_wired = False
        self._prop_refresh_timer: QTimer | None = None
        self._prop_refresh_schedule = None
        self._prop_refresh_signals: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        web = None
        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineSettings, QWebEngineView

            web = QWebEngineView(self)
            web.setContextMenuPolicy(Qt.NoContextMenu)
            _wire_webengine_console_logger(web)
            try:
                s = web.settings()
                s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
                s.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
                s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
            except Exception:
                pass
            if bundled_3dmol_available():
                self._viewer_tmp = QTemporaryDir()
                if not self._viewer_tmp.isValid():
                    raise OSError("Could not create a temporary directory for the 3D viewer.")
                tmp = Path(self._viewer_tmp.path())
                shutil.copy2(_BUNDLED_3DMOL, tmp / "3Dmol-min.js")
                index = tmp / "index.html"
                if multi_conf_blocks_json_b64 is not None:
                    index.write_text(
                        _offline_index_html_multiconf(
                            multi_conf_blocks_json_b64,
                            initial_superpose=multi_conf_initial_superpose,
                            initial_conf_index=multi_conf_initial_index,
                        ),
                        encoding="utf-8",
                    )
                else:
                    index.write_text(_offline_index_html(mol_b64, flat=flat), encoding="utf-8")
                web.load(QUrl.fromLocalFile(str(index.resolve())))
            else:
                if multi_conf_blocks_json_b64 is not None:
                    web.setHtml(
                        _cdn_fallback_html_multiconf(
                            multi_conf_blocks_json_b64,
                            initial_superpose=multi_conf_initial_superpose,
                            initial_conf_index=multi_conf_initial_index,
                        ),
                        QUrl("https://3dmol.org/"),
                    )
                else:
                    web.setHtml(_cdn_fallback_html(mol_b64, flat=flat), QUrl("https://3dmol.org/"))
            web.loadFinished.connect(lambda _ok: self._on_standalone_viewer_ready(web))
            web.setMinimumHeight(160)
            web.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            root.addWidget(web, 1)
            self._standalone_web = web
        except Exception as e:
            web = None
            self._standalone_web = None
            err = f"{type(e).__name__}: {e}"
            logger.warning("Embedded 3Dmol viewer unavailable: %s", err, exc_info=True)
            msg = (
                "The embedded viewer could not start.\n\n"
                f"{err}\n\n"
                "Typical fixes:\n"
                "• Install PyQtWebEngine with the same major.minor version as PyQt5 (e.g. both 5.15.x).\n"
                "• Start molmanager with `python -m molmanager` so QtWebEngine loads before the GUI initializes.\n\n"
                "Close this window when you are done."
            )
            root.addWidget(QLabel(msg), 1)

        self._strain_table: QTableWidget | None = None
        self._cb_only_selected_confs: QCheckBox | None = None
        if self._strain_overlay:
            self._strain_table = self._build_strain_energy_table()
            root.addWidget(self._strain_table, 0)

        self._conf_nav_host: QWidget | None = None
        self._conf_count = _multi_conf_block_count(multi_conf_blocks_json_b64)
        self._conf_idx = int(getattr(self, "_initial_conf_index", 0) or 0)
        if self._conf_count > 0:
            self._conf_idx = max(0, min(self._conf_idx, self._conf_count - 1))
        self._conf_superposed = bool(multi_conf_initial_superpose) and self._conf_count >= 2

        self._export_host = None
        self._btn_export_table = None
        self._viewer_status = None
        self._opts_btn = None
        self._opts_dialog = None
        self._cb_hide_options = None
        self._spin_field_count = None
        self._options_visible = True

        self._options_host = QWidget(self)
        options_ly = QVBoxLayout(self._options_host)
        options_ly.setContentsMargins(0, 0, 0, 0)
        options_ly.setSpacing(4)
        self._options_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        # View Conformers is multi-conf; skip table field pickers. Keep them for View 2D/3D.
        if multi_conf_blocks_json_b64 is None:
            self._prop_panel = PropertyColumnsPanel(self._options_host)
            self._prop_panel.bind_app(parent_app)
            self._prop_panel.set_source_oid(self._source_oid)
            options_ly.addWidget(self._prop_panel)
            self._wire_property_column_updates()
            root.addWidget(self._options_host)
        else:
            self._prop_panel = None
            self._options_host.hide()

        footer = QWidget(self)
        footer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._footer_bar = footer
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(4)
        if self._prop_panel is not None:
            self._opts_btn = make_plot_options_button(
                self,
                tooltip="Viewer settings: data fields and options visibility.",
            )
            self._opts_btn.clicked.connect(self._open_viewer_options)
            foot.addWidget(self._opts_btn)
            self._opts_panel = QWidget(self)
            opts_form = QFormLayout(self._opts_panel)
            opts_form.setContentsMargins(0, 0, 0, 0)
            opts_form.setHorizontalSpacing(10)
            opts_form.setVerticalSpacing(8)
            self._cb_hide_options = QCheckBox("Hide Options")
            self._cb_hide_options.setToolTip(
                "Hide column pickers so only the structure view and navigation controls are shown."
            )
            self._cb_hide_options.toggled.connect(self._on_hide_options_toggled)
            opts_form.addRow(self._cb_hide_options)
            self._spin_field_count = QSpinBox()
            self._spin_field_count.setRange(0, PROPERTY_COLUMN_SLOT_MAX)
            self._spin_field_count.setValue(PROPERTY_COLUMN_SLOT_COUNT)
            self._spin_field_count.setToolTip(
                "How many table data fields to show under the structure view."
            )
            self._spin_field_count.valueChanged.connect(self._on_field_count_changed)
            opts_form.addRow("Data fields:", self._spin_field_count)
            self._opts_dialog = make_plot_options_dialog(
                self,
                self._opts_panel,
                title="Viewer Settings",
                min_width=320,
                min_height=140,
            )
        self._add_to_main_btn = make_add_to_main_button(
            self,
            tooltip="Dock this viewer beside the table in the main window (like a plot pane).",
        )
        self._add_to_main_btn.clicked.connect(self._add_to_main_window)
        self._send_window_btn = make_send_window_button(
            self,
            tooltip="Open this docked viewer in a separate floating window.",
        )
        self._send_window_btn.clicked.connect(self._send_to_new_window)
        self._close_viewer_btn = QPushButton("Close")
        self._close_viewer_btn.setToolTip("Close this viewer.")
        self._close_viewer_btn.clicked.connect(self._close_docked_viewer)
        style_plot_footer_text_button(self._close_viewer_btn)
        foot.addStretch(1)
        foot.addWidget(self._add_to_main_btn)
        foot.addWidget(self._send_window_btn)
        foot.addWidget(self._close_viewer_btn)
        self._apply_footer_size_constraints(foot)
        root.insertWidget(0, footer)

        if multi_conf_blocks_json_b64 is not None:
            nav = QWidget(self)
            nav.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            nav_row = QHBoxLayout(nav)
            nav_row.setContentsMargins(0, 0, 0, 0)
            nav_row.setSpacing(4)
            self._add_conf_nav_controls(nav_row)
            self._btn_export_table = QPushButton("Export to Table")
            self._btn_export_table.setAutoDefault(False)
            self._btn_export_table.setDefault(False)
            self._btn_export_table.setToolTip(
                "Add the current conformer (or all when superposed) to the main table. "
                "Writes 2D Structure, optional E / ΔE / RMSD, and packed 3D into confs when present."
            )
            self._btn_export_table.clicked.connect(self._on_export_to_table)
            if web is None:
                self._btn_export_table.setEnabled(False)
            nav_row.addWidget(self._btn_export_table)
            nav_row.addStretch(1)
            self._viewer_status = QLabel("")
            self._viewer_status.setStyleSheet("color: #333;")
            self._viewer_status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            nav_row.addWidget(self._viewer_status)
            self._apply_footer_size_constraints(nav_row)
            root.addWidget(nav)
            self._conf_nav_host = nav
            self._export_host = nav

        self._sync_footer_chrome()
        self._sync_options_chrome()
        self.setMinimumWidth(self.embedded_minimum_width())

    def _wire_property_column_updates(self) -> None:
        """Refresh property values when table cells/headers change."""
        if self._prop_refresh_wired:
            return
        app = self.parent_app
        model = getattr(app, "_table_model", None) if app is not None else None
        if model is None:
            return
        self._prop_refresh_wired = True
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(80)
        self._prop_refresh_timer = timer

        def _refresh() -> None:
            if qobject_is_deleted(self):
                return
            panel = self._prop_panel
            if panel is None:
                return
            panel.refresh_columns()
            panel.update_values()

        timer.timeout.connect(_refresh)

        def _schedule(*_args) -> None:
            if qobject_is_deleted(self):
                return
            t = self._prop_refresh_timer
            if t is None or qobject_is_deleted(t):
                return
            try:
                t.start()
            except RuntimeError:
                return

        self._prop_refresh_schedule = _schedule
        signals = [
            model.dataChanged,
            model.rowsInserted,
            model.rowsRemoved,
            model.modelReset,
            model.layoutChanged,
            model.columnsInserted,
            model.columnsRemoved,
        ]
        try:
            signals.append(model.headerDataChanged)
        except Exception:
            pass
        self._prop_refresh_signals = signals
        for sig in signals:
            sig.connect(_schedule)
        self.destroyed.connect(self._unwire_property_column_updates)

    def _unwire_property_column_updates(self, *_args) -> None:
        """Drop table-model connections so a deleted viewer cannot restart its QTimer."""
        slot = self._prop_refresh_schedule
        for sig in list(self._prop_refresh_signals or []):
            if slot is None:
                break
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._prop_refresh_signals = []
        self._prop_refresh_schedule = None
        self._prop_refresh_timer = None
        self._prop_refresh_wired = False

    def _build_strain_energy_table(self) -> QTableWidget:
        table = QTableWidget(0, len(_STRAIN_TABLE_BASE_HEADERS), self)
        table.setObjectName("StrainEnergyTable")
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setSortingEnabled(True)
        table.setToolTip(
            "One row per conformer. Click a row to show that pose in 3D. "
            "Ctrl+click or Shift+click to select several. With Selected Conformers checked, "
            "the overlay follows the selection. Click a column header to sort."
        )
        table.setMinimumHeight(140)
        table.setMaximumHeight(240)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Stretch)
        hdr.setSectionsClickable(True)
        hdr.setSortIndicatorShown(True)
        populate_strain_energy_table(table, self._strain_overlay)
        start = int(getattr(self, "_initial_conf_index", 0) or 0)
        table.blockSignals(True)
        try:
            self._select_strain_table_conf(table, start)
        finally:
            table.blockSignals(False)
        table.itemSelectionChanged.connect(self._on_strain_table_selection_changed)
        return table

    def _select_strain_table_conf(self, table: QTableWidget, conf_idx: int) -> None:
        want = int(conf_idx)
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            data = item.data(Qt.UserRole)
            try:
                if int(data) == want:
                    table.selectRow(row)
                    table.scrollToItem(item)
                    return
            except (TypeError, ValueError):
                continue

    def _highlight_current_conf_in_table(self, table: QTableWidget, conf_idx: int) -> None:
        """Move the current row marker without clearing a multi-row selection."""
        want = int(conf_idx)
        model = table.model()
        sm = table.selectionModel()
        if model is None or sm is None:
            return
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            data = item.data(Qt.UserRole)
            try:
                if int(data) != want:
                    continue
            except (TypeError, ValueError):
                continue
            index = model.index(row, 0)
            sm.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
            table.scrollTo(index)
            return

    def _only_selected_in_3d(self) -> bool:
        cb = getattr(self, "_cb_only_selected_confs", None)
        return bool(cb is not None and cb.isChecked())

    def _selected_conf_indices(self) -> list[int]:
        table = self._strain_table
        if table is None:
            return []
        sm = table.selectionModel()
        if sm is None:
            return []
        out: list[int] = []
        for idx in sm.selectedRows():
            item = table.item(idx.row(), 0)
            if item is None:
                continue
            try:
                out.append(int(item.data(Qt.UserRole)))
            except (TypeError, ValueError):
                continue
        return sorted(set(out))

    def _visible_conf_indices(self) -> list[int]:
        n = int(self._conf_count)
        if n <= 0:
            return []
        if not self._only_selected_in_3d():
            return list(range(n))
        selected = [i for i in self._selected_conf_indices() if 0 <= i < n]
        return selected

    def _current_table_conf_index(self) -> int | None:
        table = self._strain_table
        if table is None:
            return None
        sm = table.selectionModel()
        if sm is None:
            return None
        cur = sm.currentIndex()
        if cur.isValid():
            item = table.item(cur.row(), 0)
            if item is not None:
                try:
                    return int(item.data(Qt.UserRole))
                except (TypeError, ValueError):
                    pass
        selected = self._selected_conf_indices()
        return selected[0] if selected else None

    def _on_strain_table_selection_changed(self) -> None:
        self._sync_superpose_enabled()
        if self._only_selected_in_3d():
            self._refresh_3d_from_scope()
            return
        self._sync_conf_legend()
        if self._conf_superposed:
            return
        idx = self._current_table_conf_index()
        if idx is not None:
            self._show_conformer(idx, preserve_selection=True)

    def _on_only_selected_confs_toggled(self, _checked: bool = False) -> None:
        self._sync_superpose_enabled()
        self._refresh_3d_from_scope()

    def _sync_superpose_enabled(self) -> None:
        cb = getattr(self, "_cb_superpose", None)
        if cb is None:
            return
        n_vis = len(self._visible_conf_indices())
        can_super = n_vis >= 2
        cb.setEnabled(can_super)
        if can_super:
            cb.setToolTip("Overlay conformers in the 3D view.")
        else:
            cb.setToolTip("Need at least two visible conformers to superpose.")
            if cb.isChecked():
                self._set_superpose_checked(False)
                self._conf_superposed = False

    def _wants_selected_superpose(self, vis: list[int] | None = None) -> bool:
        idxs = self._visible_conf_indices() if vis is None else vis
        return self._only_selected_in_3d() and len(idxs) >= 2

    def _conf_legend_payload(self) -> list[dict[str, str]] | None:
        """Legend entries when Selected Conformers is on and two-plus poses are overlaid."""
        if not self._only_selected_in_3d() or not self._conf_superposed:
            return None
        vis = self._visible_conf_indices()
        if len(vis) < 2:
            return None
        return conf_legend_entries(vis)

    def _sync_conf_legend(self) -> None:
        payload = self._conf_legend_payload()
        arg = "null" if not payload else json.dumps(payload)
        self._run_viewer_js(f"if (window.molmanagerSetConfLegend) molmanagerSetConfLegend({arg});")

    def _refresh_3d_from_scope(self) -> None:
        vis = self._visible_conf_indices()
        if self._wants_selected_superpose(vis) or (self._conf_superposed and len(vis) >= 2):
            self._show_superpose()
            return
        if not vis:
            self._conf_superposed = False
            self._set_superpose_checked(False)
            self._run_viewer_js("if (window.molmanagerShowSuperpose) molmanagerShowSuperpose([]);")
            self._sync_conf_legend()
            return
        if self._conf_idx not in vis:
            self._conf_idx = vis[0]
        self._show_conformer(self._conf_idx, preserve_selection=True)

    def _add_conf_nav_controls(self, row: QHBoxLayout) -> None:
        self._btn_conf_first = QPushButton("<<")
        self._btn_conf_first.setToolTip("First conformer (Home)")
        self._btn_conf_back = QPushButton("←")
        self._btn_conf_back.setToolTip("Previous conformer (←)")
        self._btn_conf_fwd = QPushButton("→")
        self._btn_conf_fwd.setToolTip("Next conformer (→)")
        self._btn_conf_last = QPushButton(">>")
        self._btn_conf_last.setToolTip("Last conformer (End)")
        for btn in (
            self._btn_conf_first,
            self._btn_conf_back,
            self._btn_conf_fwd,
            self._btn_conf_last,
        ):
            btn.setAutoDefault(False)
            btn.setDefault(False)
            row.addWidget(btn)

        self._cb_superpose = QCheckBox("Superpose")
        self._cb_superpose.setToolTip("Overlay conformers in the 3D view.")
        if self._conf_count < 2:
            self._cb_superpose.setEnabled(False)
            self._cb_superpose.setToolTip("Need at least two conformers to superpose.")
        self._cb_superpose.setChecked(
            bool(self._conf_superposed) and self._cb_superpose.isEnabled()
        )
        row.addWidget(self._cb_superpose)

        if self._strain_table is not None:
            self._cb_only_selected_confs = QCheckBox("Selected Conformers")
            self._cb_only_selected_confs.setToolTip(
                "When checked, the 3D view follows the table selection. "
                "Two or more selected rows are superposed, with a color legend on the right."
            )
            self._cb_only_selected_confs.toggled.connect(self._on_only_selected_confs_toggled)
            row.addWidget(self._cb_only_selected_confs)

        self._btn_conf_first.clicked.connect(self._go_first_conf)
        self._btn_conf_back.clicked.connect(lambda: self._step_conf(-1))
        self._btn_conf_fwd.clicked.connect(lambda: self._step_conf(1))
        self._btn_conf_last.clicked.connect(self._go_last_conf)
        self._cb_superpose.toggled.connect(self._on_conf_view_mode_toggled)

        for key, slot in (
            (Qt.Key_Home, self._go_first_conf),
            (Qt.Key_Left, lambda: self._step_conf(-1)),
            (Qt.Key_Right, lambda: self._step_conf(1)),
            (Qt.Key_End, self._go_last_conf),
        ):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

    def _on_conf_view_mode_toggled(self, checked: bool) -> None:
        if getattr(self, "_conf_mode_busy", False):
            return
        self._conf_mode_busy = True
        try:
            if bool(checked):
                self._show_superpose()
            else:
                self._show_conformer(self._conf_idx, preserve_selection=True)
        finally:
            self._conf_mode_busy = False

    def _go_first_conf(self) -> None:
        vis = self._visible_conf_indices()
        if vis:
            self._show_conformer(vis[0], preserve_selection=True)

    def _go_last_conf(self) -> None:
        vis = self._visible_conf_indices()
        if vis:
            self._show_conformer(vis[-1], preserve_selection=True)

    def _step_conf(self, delta: int) -> None:
        vis = self._visible_conf_indices()
        if not vis:
            return
        try:
            pos = vis.index(self._conf_idx)
        except ValueError:
            pos = 0 if int(delta) >= 0 else len(vis) - 1
        else:
            pos = (pos + int(delta)) % len(vis)
        self._show_conformer(vis[pos], preserve_selection=True)

    def _run_viewer_js(self, script: str) -> None:
        web = getattr(self, "_standalone_web", None)
        if web is None:
            return
        try:
            web.page().runJavaScript(script)
        except Exception:
            logger.debug("viewer JS failed", exc_info=True)

    def _show_superpose(self) -> None:
        vis = self._visible_conf_indices()
        if len(vis) < 2:
            if vis:
                self._show_conformer(vis[0], preserve_selection=True)
            else:
                self._conf_superposed = False
                self._set_superpose_checked(False)
                self._run_viewer_js(
                    "if (window.molmanagerShowSuperpose) molmanagerShowSuperpose([]);"
                )
                self._sync_conf_legend()
            return
        was_superposed = bool(self._conf_superposed)
        self._conf_superposed = True
        self._set_superpose_checked(True)
        payload = json.dumps(vis) if self._only_selected_in_3d() else "null"
        zoom_js = "false" if was_superposed else "true"
        colors_js = json.dumps(distinct_superpose_colors(len(vis)))
        self._run_viewer_js(
            "if (window.molmanagerShowSuperpose) "
            f"molmanagerShowSuperpose({payload}, {{zoom: {zoom_js}, colors: {colors_js}}});"
        )
        self._sync_conf_legend()

    def _show_conformer(self, conf_idx: int, *, preserve_selection: bool = True) -> None:
        n = int(self._conf_count)
        if n <= 0:
            return
        vis = self._visible_conf_indices()
        idx = max(0, min(int(conf_idx), n - 1))
        if vis and idx not in vis:
            idx = vis[0]
        self._conf_idx = idx
        self._conf_superposed = False
        self._set_superpose_checked(False)
        table = self._strain_table
        if table is not None:
            table.blockSignals(True)
            try:
                if preserve_selection:
                    self._highlight_current_conf_in_table(table, idx)
                else:
                    self._select_strain_table_conf(table, idx)
            finally:
                table.blockSignals(False)
        self._run_viewer_js(f"if (window.molmanagerLoadConf) molmanagerLoadConf({idx});")
        self._sync_conf_legend()

    def _set_superpose_checked(self, superpose: bool) -> None:
        cb = getattr(self, "_cb_superpose", None)
        if cb is None:
            return
        cb.blockSignals(True)
        try:
            cb.setChecked(bool(superpose) and cb.isEnabled())
        finally:
            cb.blockSignals(False)

    def rebind_parent_app(self, parent_app: QWidget | None) -> None:
        """Update the host app after dock/undock and refresh property columns."""
        self.parent_app = parent_app
        if self._prop_panel is not None:
            self._prop_panel.bind_app(parent_app)
            self._prop_panel.set_source_oid(self._source_oid)
        self._wire_property_column_updates()

    def embedded_minimum_width(self) -> int:
        host = getattr(self, "_conf_nav_host", None)
        if host is None:
            return 420
        row_w = _layout_visible_min_width(host.layout())
        return max(1200, row_w + 32)

    def embedded_preferred_width(self) -> int:
        return max(self.embedded_minimum_width(), 1280)

    def _apply_footer_size_constraints(self, foot: QHBoxLayout) -> None:
        status = getattr(self, "_viewer_status", None)
        for i in range(foot.count()):
            item = foot.itemAt(i)
            w = item.widget() if item is not None else None
            if w is None or w is status:
                continue
            w.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        foot.setSizeConstraint(QLayout.SetMinimumSize)

    def create_floating_dialog(self, parent_app) -> "Molecule3DViewerDialog":
        """Re-open this viewer in a floating window after undocking from the main table."""
        return _molecule_3d_viewer_dialog_cls()(
            None,
            parent_app,
            window_title=self._window_title,
            viewer_widget=self,
        )

    def _add_to_main_window(self) -> None:
        if self.parent_app is None:
            return
        dock = getattr(self.parent_app, "dock_plot_widget", None)
        if not callable(dock):
            return
        dlg = self.window()
        teardown = getattr(dlg, "_scope_sync_disconnect", None)
        if callable(teardown):
            teardown()
        if not dock(self):
            return
        if isinstance(dlg, _molecule_3d_viewer_dialog_cls()):
            dlg._viewer_widget = None
            dlg._force_close = True
            dlg.close()

    def _send_to_new_window(self) -> None:
        if self.parent_app is not None:
            undock = getattr(self.parent_app, "undock_plot_to_window", None)
            if callable(undock):
                undock(self)

    def _close_docked_viewer(self) -> None:
        from .dockable_plot import request_close_plot_widget

        request_close_plot_widget(
            self,
            title="Close Viewer",
            message="Close this viewer?",
        )

    def _is_docked_in_main_window(self) -> bool:
        app = self.parent_app
        if app is None:
            return False
        check = getattr(app, "is_plot_docked", None)
        if callable(check):
            return bool(check(self))
        return getattr(app, "_docked_plot_widget", None) is self

    def _sync_footer_chrome(self) -> None:
        """Floating: opts + Add. Docked: opts + Send + Close (Close moves beside pane ×)."""
        from .dockable_plot import apply_plot_chrome_glyphs, sync_docked_footer_bar

        apply_plot_chrome_glyphs(self)
        floating = isinstance(self.window(), _molecule_3d_viewer_dialog_cls())
        docked = self._is_docked_in_main_window()
        self._add_to_main_btn.setVisible(floating)
        self._send_window_btn.setVisible(docked)
        self._close_viewer_btn.setVisible(docked)
        sync_docked_footer_bar(self, docked=docked)
        if not docked:
            self.setMinimumWidth(self.embedded_minimum_width())

    def _sync_options_chrome(self) -> None:
        """Show or hide property column pickers from Viewer Settings."""
        if getattr(self, "_prop_panel", None) is None:
            return
        visible = bool(getattr(self, "_options_visible", True))
        spin = getattr(self, "_spin_field_count", None)
        count = int(spin.value()) if spin is not None else 1
        host = getattr(self, "_options_host", None)
        if host is not None:
            host.setVisible(visible and count > 0)
        cb = getattr(self, "_cb_hide_options", None)
        if cb is not None and cb.isChecked() == visible:
            cb.blockSignals(True)
            cb.setChecked(not visible)
            cb.blockSignals(False)

    def _on_hide_options_toggled(self, checked: bool) -> None:
        self._options_visible = not bool(checked)
        self._sync_options_chrome()

    def _on_field_count_changed(self, value: int) -> None:
        panel = getattr(self, "_prop_panel", None)
        if panel is not None:
            panel.set_visible_slot_count(int(value))
        self._sync_options_chrome()

    def _open_viewer_options(self) -> None:
        show_plot_options_dialog(getattr(self, "_opts_dialog", None))

    def event(self, event):  # noqa: N802 — Qt API name
        if event.type() == QEvent.ParentChange:
            self._sync_footer_chrome()
        return super().event(event)

    def _host_app(self) -> QWidget | None:
        if self.parent_app is not None:
            return self.parent_app
        parent = self.parent()
        return parent if parent is not None else None

    def _set_viewer_status(self, message: str) -> None:
        msg = (message or "").strip()
        status = getattr(self, "_viewer_status", None)
        if status is not None:
            status.setText(msg)
        app = self._host_app()
        plabel = getattr(app, "status_label", None) if app is not None else None
        if plabel is not None and msg:
            try:
                plabel.setText(msg)
            except Exception:
                pass

    def _on_export_to_table(self) -> None:
        if not self._multi_conf_blocks_b64:
            return
        web = getattr(self, "_standalone_web", None)
        if web is None or self._btn_export_table is None:
            self._set_viewer_status("Export failed: 3D viewer is not available.")
            return
        self._btn_export_table.setEnabled(False)
        self._set_viewer_status("Exporting to table…")

        def _finish(state) -> None:
            try:
                self._export_conformers_to_table(state)
            finally:
                try:
                    self._btn_export_table.setEnabled(True)
                except Exception:
                    pass

        try:
            web.page().runJavaScript(
                "window.molmanagerConfState ? molmanagerConfState() : null",
                _finish,
            )
        except Exception:
            self._btn_export_table.setEnabled(True)
            self._set_viewer_status("Export failed: could not read the current conformer index.")

    def _export_conformers_to_table(self, state) -> None:
        app = self._host_app()
        export_fn = (
            getattr(app, "export_conformer_viewer_to_table", None) if app is not None else None
        )
        if not callable(export_fn):
            self._set_viewer_status(
                "Export failed: open the viewer from the main MolManager window."
            )
            return
        idx = 0
        superposed = False
        n = 0
        if isinstance(state, dict):
            try:
                idx = int(state.get("idx", 0))
            except Exception:
                idx = 0
            superposed = bool(state.get("superposed"))
            try:
                n = int(state.get("n", 0))
            except Exception:
                n = 0
        if superposed or n <= 1:
            if self._only_selected_in_3d():
                selected = self._selected_conf_indices()
                indices = selected if selected else None
            else:
                indices = None
        else:
            indices = [max(0, idx)]
        try:
            n_added = int(
                export_fn(
                    blocks_json_b64=self._multi_conf_blocks_b64,
                    conf_indices=indices,
                    strain_overlay=self._strain_overlay,
                    parent_oid=self._export_parent_oid,
                    confs_column=self._export_confs_column,
                )
            )
        except Exception as exc:
            logger.exception("Export to table failed")
            self._set_viewer_status(f"Export failed: {exc}")
            return
        if n_added <= 0:
            self._set_viewer_status("No conformers were exported.")
            return
        self._set_viewer_status(f"Added {n_added} row(s) to the table.")

    def _on_standalone_viewer_ready(self, web) -> None:
        if self._multi_conf_blocks_b64 and (self._only_selected_in_3d() or self._conf_superposed):
            self._refresh_3d_from_scope()
        else:
            self._sync_conf_legend()
        self._refit_standalone_viewer(web, zoom=True)
        QTimer.singleShot(200, lambda w=web: self._refit_standalone_viewer(w, zoom=True))

    def _refit_standalone_viewer(self, web, *, zoom: bool = False) -> None:
        """Resize the WebGL canvas; zoom only on first load, not on every Qt resize."""
        if web is None:
            return
        js = (
            "if (window.molmanagerRefit) { molmanagerRefit({zoom: "
            + ("true" if zoom else "false")
            + "}); }"
        )
        try:
            web.page().runJavaScript(js)
        except Exception:
            pass
        if zoom and int(web.width()) >= 80 and int(web.height()) >= 80:
            self._web_did_initial_zoom = True

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        web = getattr(self, "_standalone_web", None)
        if web is None:
            return
        size = (int(web.width()), int(web.height()))
        if size == getattr(self, "_web_refit_size", None):
            return
        self._web_refit_size = size
        QTimer.singleShot(80, lambda w=web, s=size: self._refit_after_resize(w, s))

    def _refit_after_resize(self, web, size: tuple[int, int]) -> None:
        if getattr(self, "_web_refit_size", None) != size:
            return
        w, h = size
        first = not getattr(self, "_web_did_initial_zoom", False) and w >= 80 and h >= 80
        if first:
            self._web_did_initial_zoom = True
        self._refit_standalone_viewer(web, zoom=first)
