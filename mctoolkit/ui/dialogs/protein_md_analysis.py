# This file is part of mctoolkit.
# Copyright (C) 2026 Hunter Picard
#
# mctoolkit is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# mctoolkit is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with mctoolkit. If not, see <https://www.gnu.org/licenses/>.

"""Protein Viewer trajectory analysis dialog (RMSD / RMSF / energy, not a DCD player)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)
from plotly import graph_objects as go

from ...md.analysis import TrajectoryAnalysis, extract_frame_pdb, read_run_sidecar
from ...reference.method_citations import md_analysis_dialog_footer_html
from ...workers.protein_md_analysis import (
    ProteinMDAnalysisRequest,
    ProteinMDAnalysisSignals,
    ProteinMDAnalysisWorker,
)
from ..plotly_interactive_view import PlotlyInteractiveView
from ..qt_widget_utils import append_viewer_log, make_window_minimizable
from .conformer_output import citation_footer_label
from .protein_source_picker import _browse_path_row


class ProteinMDAnalysisDialog(QDialog):
    """Options for Protein Viewer → Tools → Simulate → Analyze Trajectory."""

    overlay_frame = Signal(str)

    def __init__(self, viewer, parent=None) -> None:
        super().__init__(parent or viewer)
        self._viewer = viewer
        self.setWindowTitle("Analyze Trajectory")
        self.setMinimumWidth(560)
        self.resize(620, 720)
        self._analysis: TrajectoryAnalysis | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        io_gb = QGroupBox("Run files")
        io_form = QFormLayout(io_gb)
        io_form.setContentsMargins(8, 6, 8, 6)
        io_form.setSpacing(4)
        self.edit_dcd = QLineEdit()
        self.edit_dcd.setPlaceholderText("complex_md.dcd")
        io_form.addRow("DCD:", _browse_path_row(self.edit_dcd, self._browse_dcd))
        self.edit_sidecar = QLineEdit()
        self.edit_sidecar.setPlaceholderText("complex_md.dcd.json")
        io_form.addRow("Sidecar:", _browse_path_row(self.edit_sidecar, self._browse_sidecar))
        self.edit_topology = QLineEdit()
        self.edit_topology.setPlaceholderText("complex_md_top.pdb")
        io_form.addRow("Topology PDB:", _browse_path_row(self.edit_topology, self._browse_topology))
        self.edit_energy = QLineEdit()
        self.edit_energy.setPlaceholderText("complex_md_energy.csv")
        io_form.addRow("Energy CSV:", _browse_path_row(self.edit_energy, self._browse_energy))
        self.edit_mmgbsa = QLineEdit()
        self.edit_mmgbsa.setPlaceholderText("complex_md_mmgbsa.csv")
        io_form.addRow("MM-GBSA CSV:", _browse_path_row(self.edit_mmgbsa, self._browse_mmgbsa))
        self.edit_csv = QLineEdit()
        self.edit_csv.setPlaceholderText("complex_md_analysis.csv")
        io_form.addRow("Export CSV:", _browse_path_row(self.edit_csv, self._browse_csv))
        root.addWidget(io_gb)

        plot_gb = QGroupBox("Plots")
        plot_lay = QVBoxLayout(plot_gb)
        plot_lay.setContentsMargins(8, 6, 8, 6)
        plot_lay.setSpacing(4)
        self.combo_plot = QComboBox()
        self.combo_plot.addItem("RMSD vs time", "rmsd")
        self.combo_plot.addItem("Energy vs time", "energy")
        self.combo_plot.addItem("MM-GBSA ΔG vs time", "dg")
        self.combo_plot.addItem("Cα RMSF vs residue", "rmsf")
        self.combo_plot.currentIndexChanged.connect(self._refresh_plot)
        plot_lay.addWidget(self.combo_plot)
        self.plot = PlotlyInteractiveView(parent_app=None, parent=self)
        self.plot.setMinimumHeight(220)
        self.plot.set_hover_options(columns=[], show_structure=False, persist=False)
        plot_lay.addWidget(self.plot)
        root.addWidget(plot_gb)

        self.results = QPlainTextEdit()
        self.results.setReadOnly(True)
        self.results.setPlaceholderText("Summary appears here after Analyze.")
        self.results.setMinimumHeight(90)
        root.addWidget(self.results)
        root.addWidget(citation_footer_label(md_analysis_dialog_footer_html(), self))

        frame_row = QHBoxLayout()
        self.spin_frame = QSpinBox()
        self.spin_frame.setRange(0, 0)
        self.spin_frame.setEnabled(False)
        frame_row.addWidget(self.spin_frame)
        self.btn_overlay = QPushButton("Overlay selected frame")
        self.btn_overlay.setEnabled(False)
        self.btn_overlay.setToolTip("Write one solute frame and overlay it. This is not playback.")
        self.btn_overlay.clicked.connect(self._on_overlay)
        frame_row.addWidget(self.btn_overlay)
        frame_row.addStretch()
        root.addLayout(frame_row)

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("Analyze")
        self.btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self.btn_run)
        btn_row.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)
        root.addLayout(btn_row)

        self._signals = ProteinMDAnalysisSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._signals.progress.connect(self._append_log)
        make_window_minimizable(self)
        self.edit_sidecar.editingFinished.connect(self._on_sidecar_edited)

    def _on_sidecar_edited(self) -> None:
        path = self.edit_sidecar.text().strip()
        if path and Path(path).is_file():
            self._apply_sidecar(path)

    def prefill_from_md_result(self, result) -> None:
        """Fill paths from a finished Molecular Dynamics job."""
        dcd = getattr(result, "dcd_path", "") or ""
        sidecar = getattr(result, "sidecar_path", "") or ""
        if dcd:
            self.edit_dcd.setText(dcd)
        if sidecar:
            self.edit_sidecar.setText(sidecar)
            self._apply_sidecar(sidecar)
        else:
            self.edit_topology.setText(getattr(result, "topology_path", "") or "")
            self.edit_energy.setText(getattr(result, "energy_csv_path", "") or "")
            self.edit_mmgbsa.setText(getattr(result, "csv_path", "") or "")
        if dcd:
            rec = Path(dcd)
            self.edit_csv.setText(str(rec.with_name(f"{rec.stem}_analysis.csv")))

    def _apply_sidecar(self, path: str) -> None:
        meta = read_run_sidecar(path)
        if not meta:
            return
        if meta.get("dcd") and not self.edit_dcd.text().strip():
            self.edit_dcd.setText(str(meta["dcd"]))
        if meta.get("topology"):
            self.edit_topology.setText(str(meta["topology"]))
        if meta.get("energy_csv"):
            self.edit_energy.setText(str(meta["energy_csv"]))
        if meta.get("mmgbsa_csv"):
            self.edit_mmgbsa.setText(str(meta["mmgbsa_csv"]))
        dcd = self.edit_dcd.text().strip()
        if dcd and not self.edit_csv.text().strip():
            rec = Path(dcd)
            self.edit_csv.setText(str(rec.with_name(f"{rec.stem}_analysis.csv")))

    def _browse_dcd(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Trajectory DCD", self.edit_dcd.text().strip(), "DCD (*.dcd);;All files (*.*)"
        )
        if not path:
            return
        self.edit_dcd.setText(path)
        sidecar = str(Path(path)) + ".json"
        if Path(sidecar).is_file():
            self.edit_sidecar.setText(sidecar)
            self._apply_sidecar(sidecar)
        rec = Path(path)
        if not self.edit_csv.text().strip():
            self.edit_csv.setText(str(rec.with_name(f"{rec.stem}_analysis.csv")))

    def _browse_sidecar(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "MD sidecar JSON",
            self.edit_sidecar.text().strip(),
            "JSON (*.json);;All files (*.*)",
        )
        if path:
            self.edit_sidecar.setText(path)
            self._apply_sidecar(path)

    def _browse_topology(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Topology PDB",
            self.edit_topology.text().strip(),
            "PDB (*.pdb);;All files (*.*)",
        )
        if path:
            self.edit_topology.setText(path)

    def _browse_energy(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Energy CSV", self.edit_energy.text().strip(), "CSV (*.csv);;All files (*.*)"
        )
        if path:
            self.edit_energy.setText(path)

    def _browse_mmgbsa(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "MM-GBSA CSV", self.edit_mmgbsa.text().strip(), "CSV (*.csv);;All files (*.*)"
        )
        if path:
            self.edit_mmgbsa.setText(path)

    def _browse_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Analysis CSV", self.edit_csv.text().strip(), "CSV (*.csv);;All files (*.*)"
        )
        if path:
            self.edit_csv.setText(path)

    def _append_log(self, text: str) -> None:
        append_viewer_log(self._viewer, text)

    def _process_host(self):
        parent = self._viewer
        while parent is not None:
            if hasattr(parent, "process_queue"):
                return parent
            parent = parent.parent()
        return None

    def _on_run(self) -> None:
        dcd = self.edit_dcd.text().strip()
        if not dcd:
            QMessageBox.information(self, "Analyze Trajectory", "Set a DCD path.")
            return
        if not Path(dcd).is_file():
            QMessageBox.warning(self, "Analyze Trajectory", f"DCD not found:\n{dcd}")
            return
        csv_path = self.edit_csv.text().strip()
        rmsf_csv = ""
        if csv_path:
            rec = Path(csv_path)
            rmsf_csv = str(rec.with_name(f"{rec.stem}_rmsf.csv"))
        req = ProteinMDAnalysisRequest(
            dcd_path=dcd,
            topology_path=self.edit_topology.text().strip(),
            sidecar_path=self.edit_sidecar.text().strip(),
            energy_csv=self.edit_energy.text().strip(),
            mmgbsa_csv=self.edit_mmgbsa.text().strip(),
            output_csv=csv_path,
            rmsf_csv=rmsf_csv,
        )
        self.btn_run.setEnabled(False)
        self._append_log("Analyzing trajectory…")
        host = self._process_host()
        if host is not None:
            host.process_queue.enqueue(
                "Analyze Trajectory",
                lambda ev, r=req, sig=self._signals: ProteinMDAnalysisWorker(
                    r, signals=sig, cancel_event=ev
                ),
            )
            return
        from PySide6.QtCore import QThreadPool

        QThreadPool.globalInstance().start(ProteinMDAnalysisWorker(req, signals=self._signals))

    def _on_finished(self, result) -> None:
        self.btn_run.setEnabled(True)
        self._analysis = getattr(result, "analysis", None)
        summary = getattr(result, "summary", "") or ""
        if summary:
            self.results.setPlainText(summary)
        n = int(getattr(result, "n_frames", 0) or 0)
        self.spin_frame.setEnabled(n > 0)
        self.btn_overlay.setEnabled(n > 0)
        if n > 0:
            self.spin_frame.setRange(0, n - 1)
        self._refresh_plot()
        csv_path = getattr(result, "csv_path", "") or ""
        if csv_path:
            self._append_log(f"Analysis CSV: {csv_path}")

    def _on_failed(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        self._append_log(msg or "Trajectory analysis failed.")
        QMessageBox.warning(self, "Analyze Trajectory", msg or "Trajectory analysis failed.")

    def _refresh_plot(self) -> None:
        analysis = self._analysis
        if analysis is None:
            return
        kind = self.combo_plot.currentData() or "rmsd"
        fig = go.Figure()
        n = max(1, int(analysis.n_frames))
        if kind == "rmsd":
            fig.add_scatter(
                x=list(analysis.time_ps),
                y=list(analysis.protein_ca_rmsd),
                name="Protein Cα",
                mode="lines",
            )
            fig.add_scatter(
                x=list(analysis.time_ps),
                y=list(analysis.ligand_rmsd),
                name="Ligand",
                mode="lines",
            )
            fig.update_layout(xaxis_title="Time (ps)", yaxis_title="RMSD (Å)")
        elif kind == "energy":
            fig.add_scatter(
                x=list(analysis.time_ps),
                y=list(analysis.e_pot),
                name="E_pot",
                mode="lines",
            )
            fig.update_layout(xaxis_title="Time (ps)", yaxis_title="kcal/mol")
        elif kind == "dg":
            fig.add_scatter(
                x=list(analysis.time_ps),
                y=list(analysis.dg),
                name="ΔG",
                mode="lines",
            )
            fig.update_layout(xaxis_title="Time (ps)", yaxis_title="kcal/mol")
        else:
            xs = list(range(len(analysis.rmsf)))
            ys = [row.rmsf for row in analysis.rmsf]
            labels = [f"{row.resn}{row.resi}" for row in analysis.rmsf]
            fig.add_scatter(x=xs, y=ys, name="RMSF", mode="lines", text=labels)
            fig.update_layout(xaxis_title="Residue index", yaxis_title="RMSF (Å)")
            n = max(1, len(ys))
        fig.update_layout(
            template="plotly_white",
            margin={"l": 48, "r": 16, "t": 24, "b": 40},
            legend={"orientation": "h"},
            height=260,
        )
        if kind != "rmsf":
            n = max(1, int(analysis.n_frames))
        self.plot.push_figure(fig, list(range(n)))

    def _on_overlay(self) -> None:
        dcd = self.edit_dcd.text().strip()
        top = self.edit_topology.text().strip()
        if not dcd or not top:
            QMessageBox.information(
                self, "Analyze Trajectory", "DCD and topology PDB are required to overlay a frame."
            )
            return
        idx = int(self.spin_frame.value())
        dest = Path(dcd).with_name(f"{Path(dcd).stem}_frame{idx}.pdb")
        try:
            out = extract_frame_pdb(
                dcd_path=dcd,
                topology_path=top,
                frame=idx,
                dest=dest,
                sidecar_path=self.edit_sidecar.text().strip(),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Analyze Trajectory", str(exc) or "Could not write frame.")
            return
        self._append_log(f"Overlay frame {idx} → {out.name}")
        self.overlay_frame.emit(str(out))
