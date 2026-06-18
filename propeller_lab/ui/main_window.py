"""Main PySide6 window for PropellerLab."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from propeller_lab.core.bemt import calculate_propeller
from propeller_lab.core.export import export_scan_csv, export_station_csv, export_summary_csv
from propeller_lab.core.geometry import (
    estimate_reynolds_range,
    generate_pitch_geometry,
    load_geometry_csv,
    pitch_angle_from_pitch,
    pitch_from_pitch_angle,
    representative_reynolds_values,
    save_geometry_csv,
)
from propeller_lab.core.models import GeometryStation, PolarPoint, PropellerInput, PropellerResult
from propeller_lab.core.polar import AirfoilPolar, MultiRePolar, TablePolar
from propeller_lab.core.xfoil_runner import XfoilPolarPoint, XfoilRunResult, XfoilRunner
from propeller_lab.ui.plot_widgets import AeroPlotWidget, LoadPlotWidget, PolarPlotWidget, ScanPlotWidget
from propeller_lab.ui.xfoil_worker import XfoilWorker


class MainWindow(QMainWindow):
    """Desktop window that connects UI controls to the core package."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PropellerLab - Propeller Thrust and Torque Calculator")
        self.resize(1280, 820)

        self.current_result: PropellerResult | None = None
        self.current_geometry: list[GeometryStation] | None = None
        self.current_polar: AirfoilPolar | None = None
        self.xfoil_points: list[XfoilPolarPoint] = []
        self.xfoil_reynolds_tables: dict[float, list[XfoilPolarPoint]] = {}
        self.scan_rows: list[dict[str, float | int]] = []
        self.xfoil_thread: QThread | None = None
        self.xfoil_worker: XfoilWorker | None = None
        self._pitch_syncing = False

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_input_panel())
        splitter.addWidget(self._build_tabs())
        splitter.setSizes([360, 920])
        self.setCentralWidget(splitter)
        self._connect_re_range_inputs()
        self._update_re_range_from_inputs(log=False, show_errors=False)

    def _build_input_panel(self) -> QWidget:
        """Build the left input panel."""

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(8, 8, 8, 8)

        form = QWidget()
        form_layout = QVBoxLayout(form)
        form_layout.addWidget(self._geometry_group())
        form_layout.addWidget(self._operating_group())
        form_layout.addWidget(self._model_group())
        form_layout.addWidget(self._button_group())
        form_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form)
        panel_layout.addWidget(scroll)
        return panel

    def _geometry_group(self) -> QGroupBox:
        """Build geometry controls."""

        group = QGroupBox("Geometry")
        layout = QFormLayout(group)
        self.blades_spin = _spin_int(1, 12, 2)
        self.diameter_spin = _spin_float(0.001, 10.0, 0.254, 4, 0.001)
        self.hub_spin = _spin_float(0.0, 9.0, 0.035, 4, 0.001)
        self.pitch_input_combo = QComboBox()
        self.pitch_input_combo.addItem("Pitch P, m", "pitch")
        self.pitch_input_combo.addItem("Pitch angle at 70%R, deg", "pitch_angle")
        self.pitch_spin = _spin_float(0.0, 10.0, 0.1143, 4, 0.001)
        self.pitch_angle_spin = _spin_float(0.0, 89.0, 11.568, 3, 0.1)
        self.root_chord_spin = _spin_float(0.001, 1.0, 0.16, 4, 0.001)
        self.tip_chord_spin = _spin_float(0.001, 1.0, 0.06, 4, 0.001)
        self.elements_spin = _spin_int(3, 500, 50)
        layout.addRow("Blades B", self.blades_spin)
        layout.addRow("Diameter D, m", self.diameter_spin)
        layout.addRow("Hub diameter, m", self.hub_spin)
        layout.addRow("Pitch input", self.pitch_input_combo)
        layout.addRow("Pitch P, m", self.pitch_spin)
        layout.addRow("Pitch angle at 70%R, deg", self.pitch_angle_spin)
        layout.addRow("Root chord c_root/R", self.root_chord_spin)
        layout.addRow("Tip chord c_tip/R", self.tip_chord_spin)
        layout.addRow("Elements", self.elements_spin)
        self.pitch_input_combo.currentIndexChanged.connect(self._update_pitch_input_state)
        self.pitch_spin.valueChanged.connect(self._sync_pitch_angle_from_pitch)
        self.pitch_angle_spin.valueChanged.connect(self._sync_pitch_from_angle)
        self.diameter_spin.valueChanged.connect(self._sync_pitch_dependent_input)
        self._sync_pitch_angle_from_pitch()
        self._update_pitch_input_state()
        return group

    def _operating_group(self) -> QGroupBox:
        """Build operating-point controls."""

        group = QGroupBox("Operating point")
        layout = QFormLayout(group)
        self.rpm_spin = _spin_float(0.0, 200000.0, 8000.0, 1, 100.0)
        self.vinf_spin = _spin_float(0.0, 400.0, 0.0, 3, 0.1)
        self.rho_spin = _spin_float(0.001, 50.0, 1.225, 4, 0.001)
        self.mu_spin = _spin_float(0.00000001, 0.1, 1.81e-5, 8, 0.000001)
        self.sound_speed_spin = _spin_float(1.0, 2000.0, 343.0, 3, 1.0)
        layout.addRow("RPM", self.rpm_spin)
        layout.addRow("Freestream velocity V_inf, m/s", self.vinf_spin)
        layout.addRow("Density rho", self.rho_spin)
        layout.addRow("Dynamic viscosity mu", self.mu_spin)
        layout.addRow("Sound speed a", self.sound_speed_spin)
        return group

    def _model_group(self) -> QGroupBox:
        """Build model selection controls."""

        group = QGroupBox("Model")
        layout = QFormLayout(group)
        self.calc_mode_combo = QComboBox()
        self.calc_mode_combo.addItem("Auto solver", "auto")
        self.calc_mode_combo.addItem("Simple blade element", "simple")
        self.calc_mode_combo.addItem("Simple blade element + axial induction", "simple_induced")
        self.calc_mode_combo.addItem("Forward-flight phi-BEMT", "bemt_phi_forward")
        self.calc_mode_combo.addItem("Dimensional low-speed BEMT", "bemt_hover_dimensional")
        self.calc_mode_combo.setCurrentIndex(0)
        self.polar_mode_combo = QComboBox()
        self.polar_mode_combo.addItem("Generic airfoil", "generic")
        self.polar_mode_combo.addItem("Imported polar CSV", "table")
        self.polar_mode_combo.addItem("XFOIL cached polar", "xfoil_cached")
        self.tip_loss_check = QCheckBox("Use tip loss")
        self.tip_loss_check.setChecked(True)
        self.hub_loss_check = QCheckBox("Use hub loss")
        self.hub_loss_check.setChecked(True)
        layout.addRow("Calculation mode", self.calc_mode_combo)
        layout.addRow("Polar mode", self.polar_mode_combo)
        layout.addRow(self.tip_loss_check)
        layout.addRow(self.hub_loss_check)
        return group

    def _button_group(self) -> QGroupBox:
        """Build action buttons."""

        group = QGroupBox("Actions")
        layout = QGridLayout(group)
        self.calculate_button = QPushButton("Calculate")
        self.import_geometry_button = QPushButton("Import geometry CSV")
        self.export_geometry_button = QPushButton("Export geometry CSV")
        self.import_polar_button = QPushButton("Import polar CSV")
        self.export_station_button = QPushButton("Export station CSV")
        self.export_summary_button = QPushButton("Export summary CSV")

        buttons = [
            self.calculate_button,
            self.import_geometry_button,
            self.export_geometry_button,
            self.import_polar_button,
            self.export_station_button,
            self.export_summary_button,
        ]
        for idx, button in enumerate(buttons):
            layout.addWidget(button, idx // 2, idx % 2)

        self.calculate_button.clicked.connect(self.calculate)
        self.import_geometry_button.clicked.connect(self.import_geometry)
        self.export_geometry_button.clicked.connect(self.export_geometry)
        self.import_polar_button.clicked.connect(self.import_polar)
        self.export_station_button.clicked.connect(self.export_station_csv)
        self.export_summary_button.clicked.connect(self.export_summary_csv)
        return group

    def _build_tabs(self) -> QTabWidget:
        """Build right-side output tabs."""

        tabs = QTabWidget()
        tabs.addTab(self._summary_tab(), "Summary")
        self.load_plot = LoadPlotWidget()
        tabs.addTab(self.load_plot, "Radial loads")
        self.aero_plot = AeroPlotWidget()
        tabs.addTab(self.aero_plot, "Aero state")
        tabs.addTab(self._station_table_tab(), "Station table")
        tabs.addTab(self._scan_tab(), "RPM sweep")
        tabs.addTab(self._xfoil_tab(), "XFOIL polar generator")
        return tabs

    def _summary_tab(self) -> QWidget:
        """Build summary tab."""

        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        self.summary_labels: dict[str, QLabel] = {}
        for key, label in [
            ("T", "T, N"),
            ("Q", "Q, N*m"),
            ("P", "P, W"),
            ("eta", "eta"),
            ("CT", "CT"),
            ("CQ", "CQ"),
            ("CP", "CP"),
            ("requested_mode", "requested_mode"),
            ("actual_mode", "actual_mode"),
            ("J", "J"),
            ("mu_adv", "mu_adv"),
            ("max_alpha_deg", "max_alpha_deg"),
            ("stall_station_fraction", "stall_station_fraction"),
            ("low_re_station_fraction", "low_re_station_fraction"),
            ("negative_thrust_station_fraction", "negative_thrust_station_fraction"),
            ("max_vi_mps", "max_vi_mps"),
            ("solver_fallback_fraction", "solver_fallback_fraction"),
        ]:
            value_label = QLabel("-")
            self.summary_labels[key] = value_label
            form.addRow(label, value_label)
        layout.addLayout(form)
        self.warning_text = QTextEdit()
        self.warning_text.setReadOnly(True)
        self.warning_text.setPlaceholderText("Warnings")
        layout.addWidget(self.warning_text, 1)
        return widget

    def _station_table_tab(self) -> QWidget:
        """Build station table tab."""

        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.station_table = QTableWidget(0, len(STATION_COLUMNS))
        self.station_table.setHorizontalHeaderLabels([label for label, _attr in STATION_COLUMNS])
        self.station_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.station_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.station_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.station_table)
        return widget

    def _scan_tab(self) -> QWidget:
        """Build RPM sweep tab."""

        widget = QWidget()
        layout = QVBoxLayout(widget)
        controls = QHBoxLayout()
        self.rpm_start_spin = _spin_float(0.0, 200000.0, 4000.0, 1, 100.0)
        self.rpm_end_spin = _spin_float(0.0, 200000.0, 12000.0, 1, 100.0)
        self.rpm_step_spin = _spin_float(1.0, 100000.0, 1000.0, 1, 100.0)
        self.scan_button = QPushButton("Start sweep")
        self.export_scan_button = QPushButton("Export sweep CSV")
        controls.addWidget(QLabel("rpm_start"))
        controls.addWidget(self.rpm_start_spin)
        controls.addWidget(QLabel("rpm_end"))
        controls.addWidget(self.rpm_end_spin)
        controls.addWidget(QLabel("rpm_step"))
        controls.addWidget(self.rpm_step_spin)
        controls.addWidget(self.scan_button)
        controls.addWidget(self.export_scan_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.scan_table = QTableWidget(0, len(SCAN_COLUMNS))
        self.scan_table.setHorizontalHeaderLabels(SCAN_COLUMNS)
        self.scan_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.scan_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.scan_plot = ScanPlotWidget()
        layout.addWidget(self.scan_table, 1)
        layout.addWidget(self.scan_plot, 2)

        self.scan_button.clicked.connect(self.run_scan)
        self.export_scan_button.clicked.connect(self.export_scan)
        return widget

    def _xfoil_tab(self) -> QWidget:
        """Build XFOIL tab."""

        widget = QWidget()
        layout = QVBoxLayout(widget)
        top = QGridLayout()
        self.xfoil_path_edit = QLineEdit("xfoil")
        self.xfoil_browse_button = QPushButton("Browse")
        self.xfoil_check_button = QPushButton("Check XFOIL")
        self.airfoil_source_combo = QComboBox()
        self.airfoil_source_combo.addItem("NACA")
        self.airfoil_source_combo.addItem("DAT file")
        self.naca_edit = QLineEdit("4412")
        self.dat_path_edit = QLineEdit()
        self.dat_browse_button = QPushButton("Browse")
        self.xfoil_re_spin = _spin_float(1000.0, 50000000.0, 100000.0, 0, 1000.0)
        self.auto_re_range_check = QCheckBox("Auto estimate Re range")
        self.auto_re_range_check.setChecked(True)
        self.use_multi_re_check = QCheckBox("Use multi-Re sweep")
        self.re_min_spin = _spin_float(1000.0, 50000000.0, 50000.0, 0, 1000.0)
        self.re_max_spin = _spin_float(1000.0, 50000000.0, 300000.0, 0, 1000.0)
        self.re_count_spin = _spin_int(1, 7, 3)
        self.estimate_re_button = QPushButton("Estimate Re range")
        self.xfoil_mach_spin = _spin_float(0.0, 2.0, 0.0, 3, 0.01)
        self.alpha_start_spin = _spin_float(-90.0, 90.0, -10.0, 2, 0.5)
        self.alpha_end_spin = _spin_float(-90.0, 90.0, 15.0, 2, 0.5)
        self.alpha_step_spin = _spin_float(0.01, 20.0, 0.5, 2, 0.1)
        self.iter_spin = _spin_int(1, 1000, 100)
        self.panels_spin = _spin_int(20, 500, 160)
        self.timeout_spin = _spin_float(1.0, 600.0, 60.0, 1, 1.0)
        self.run_xfoil_button = QPushButton("Run XFOIL")
        self.save_xfoil_button = QPushButton("Save polar CSV")
        self.use_xfoil_button = QPushButton("Use as current polar")

        rows = [
            ("XFOIL executable path", self.xfoil_path_edit, self.xfoil_browse_button),
            ("Airfoil source", self.airfoil_source_combo, None),
            ("NACA code", self.naca_edit, None),
            ("DAT file path", self.dat_path_edit, self.dat_browse_button),
            ("Reynolds", self.xfoil_re_spin, None),
            ("Auto Re range", self.auto_re_range_check, self.estimate_re_button),
            ("Use multi-Re sweep", self.use_multi_re_check, None),
            ("Re min", self.re_min_spin, None),
            ("Re max", self.re_max_spin, None),
            ("Re count", self.re_count_spin, None),
            ("Mach", self.xfoil_mach_spin, None),
            ("alpha_start", self.alpha_start_spin, None),
            ("alpha_end", self.alpha_end_spin, None),
            ("alpha_step", self.alpha_step_spin, None),
            ("ITER", self.iter_spin, None),
            ("panels", self.panels_spin, None),
            ("timeout", self.timeout_spin, None),
        ]
        for row, (label, control, extra) in enumerate(rows):
            top.addWidget(QLabel(label), row, 0)
            top.addWidget(control, row, 1)
            if extra is not None:
                top.addWidget(extra, row, 2)
        top.addWidget(self.xfoil_check_button, 0, 3)
        top.addWidget(self.run_xfoil_button, 1, 3)
        top.addWidget(self.save_xfoil_button, 2, 3)
        top.addWidget(self.use_xfoil_button, 3, 3)
        layout.addLayout(top)

        middle = QSplitter(Qt.Orientation.Horizontal)
        self.xfoil_table = QTableWidget(0, len(XFOIL_COLUMNS))
        self.xfoil_table.setHorizontalHeaderLabels(XFOIL_COLUMNS)
        self.xfoil_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.xfoil_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.polar_plot = PolarPlotWidget()
        middle.addWidget(self.xfoil_table)
        middle.addWidget(self.polar_plot)
        middle.setSizes([420, 620])
        layout.addWidget(middle, 2)

        self.xfoil_log = QTextEdit()
        self.xfoil_log.setReadOnly(True)
        self.xfoil_log.setPlaceholderText("XFOIL log")
        layout.addWidget(self.xfoil_log, 1)

        self.xfoil_browse_button.clicked.connect(self.browse_xfoil)
        self.dat_browse_button.clicked.connect(self.browse_dat)
        self.xfoil_check_button.clicked.connect(self.check_xfoil)
        self.estimate_re_button.clicked.connect(self.estimate_re_range)
        self.auto_re_range_check.toggled.connect(self._auto_estimate_re_range)
        self.run_xfoil_button.clicked.connect(self.run_xfoil)
        self.save_xfoil_button.clicked.connect(self.save_xfoil_csv)
        self.use_xfoil_button.clicked.connect(self.use_xfoil_polar)
        return widget

    def _input(self) -> PropellerInput:
        """Read PropellerInput from controls."""

        return PropellerInput(
            blades=self.blades_spin.value(),
            diameter_m=self.diameter_spin.value(),
            hub_diameter_m=self.hub_spin.value(),
            pitch_m=self._current_pitch_m(),
            pitch_input_mode=str(self.pitch_input_combo.currentData()),
            pitch_angle_deg=self.pitch_angle_spin.value(),
            root_chord_ratio=self.root_chord_spin.value(),
            tip_chord_ratio=self.tip_chord_spin.value(),
            rpm=self.rpm_spin.value(),
            v_inf=self.vinf_spin.value(),
            rho=self.rho_spin.value(),
            mu=self.mu_spin.value(),
            sound_speed=self.sound_speed_spin.value(),
            elements=self.elements_spin.value(),
            calculation_mode=str(self.calc_mode_combo.currentData()),
            polar_mode=str(self.polar_mode_combo.currentData()),
            use_tip_loss=self.tip_loss_check.isChecked(),
            use_hub_loss=self.hub_loss_check.isChecked(),
        )

    def _current_pitch_m(self) -> float:
        """Return the current pitch in meters from the active pitch input."""

        if str(self.pitch_input_combo.currentData()) == "pitch_angle":
            return pitch_from_pitch_angle(self.diameter_spin.value(), self.pitch_angle_spin.value())
        return self.pitch_spin.value()

    def _update_pitch_input_state(self) -> None:
        """Enable only the selected pitch input and synchronize the other value."""

        use_angle = str(self.pitch_input_combo.currentData()) == "pitch_angle"
        self.pitch_spin.setEnabled(not use_angle)
        self.pitch_angle_spin.setEnabled(use_angle)
        if use_angle:
            self._sync_pitch_from_angle()
        else:
            self._sync_pitch_angle_from_pitch()

    def _sync_pitch_angle_from_pitch(self) -> None:
        """Update the 70 percent radius pitch angle from pitch in meters."""

        if self._pitch_syncing:
            return
        self._pitch_syncing = True
        try:
            value = pitch_angle_from_pitch(self.diameter_spin.value(), self.pitch_spin.value())
            self.pitch_angle_spin.blockSignals(True)
            self.pitch_angle_spin.setValue(value)
            self.pitch_angle_spin.blockSignals(False)
        finally:
            self.pitch_angle_spin.blockSignals(False)
            self._pitch_syncing = False

    def _sync_pitch_from_angle(self) -> None:
        """Update pitch in meters from the 70 percent radius pitch angle."""

        if self._pitch_syncing:
            return
        self._pitch_syncing = True
        try:
            value = pitch_from_pitch_angle(self.diameter_spin.value(), self.pitch_angle_spin.value())
            self.pitch_spin.blockSignals(True)
            self.pitch_spin.setValue(value)
            self.pitch_spin.blockSignals(False)
        finally:
            self.pitch_spin.blockSignals(False)
            self._pitch_syncing = False

    def _sync_pitch_dependent_input(self) -> None:
        """Synchronize pitch inputs after a diameter change."""

        if str(self.pitch_input_combo.currentData()) == "pitch_angle":
            self._sync_pitch_from_angle()
        else:
            self._sync_pitch_angle_from_pitch()

    def _selected_polar(self) -> AirfoilPolar | None:
        """Return current polar for non-generic modes."""

        mode = str(self.polar_mode_combo.currentData())
        if mode == "generic":
            return None
        if self.current_polar is None:
            raise ValueError("No imported or XFOIL polar is available.")
        return self.current_polar

    def calculate(self) -> None:
        """Run one propeller calculation."""

        try:
            inp = self._input()
            polar = self._selected_polar()
            result = calculate_propeller(inp, polar=polar, geometry=self.current_geometry)
            self.current_result = result
            self._show_result(result)
        except Exception as exc:  # noqa: BLE001 - GUI reports all errors.
            _show_error(self, "Calculation failed", str(exc))

    def _show_result(self, result: PropellerResult) -> None:
        """Refresh summary, plots, and station table."""

        self.summary_labels["T"].setText(_fmt(result.thrust_N))
        self.summary_labels["Q"].setText(_fmt(result.torque_Nm))
        self.summary_labels["P"].setText(_fmt(result.power_W))
        self.summary_labels["eta"].setText(_fmt(result.eta))
        self.summary_labels["CT"].setText(_fmt(result.ct))
        self.summary_labels["CQ"].setText(_fmt(result.cq))
        self.summary_labels["CP"].setText(_fmt(result.cp))
        for key in DIAGNOSTIC_KEYS:
            self.summary_labels[key].setText(_fmt(result.diagnostics.get(key, "-")))
        self.warning_text.setPlainText("\n".join(result.warnings))
        self.load_plot.update_plot(result.stations)
        self.aero_plot.update_plot(result.stations)
        self._fill_station_table(result.stations)

    def _fill_station_table(self, stations: list[Any]) -> None:
        """Populate a QTableWidget from StationResult objects."""

        self.station_table.setRowCount(len(stations))
        for row, station in enumerate(stations):
            for col, (_label, attr) in enumerate(STATION_COLUMNS):
                value = getattr(station, attr)
                self.station_table.setItem(row, col, QTableWidgetItem(_fmt(value) if isinstance(value, float) else str(value)))

    def import_geometry(self) -> None:
        """Import blade geometry CSV."""

        path, _filter = QFileDialog.getOpenFileName(self, "Import geometry CSV", "", "CSV files (*.csv);;All files (*)")
        if not path:
            return
        try:
            self.current_geometry = load_geometry_csv(path)
            self.elements_spin.setValue(len(self.current_geometry))
            self._auto_estimate_re_range()
            QMessageBox.information(self, "Geometry imported", f"Imported {len(self.current_geometry)} station(s).")
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Geometry import failed", str(exc))

    def export_geometry(self) -> None:
        """Export current or generated blade geometry."""

        path, _filter = QFileDialog.getSaveFileName(self, "Export geometry CSV", "geometry.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            stations = self.current_geometry or generate_pitch_geometry(self._input())
            save_geometry_csv(stations, path)
            QMessageBox.information(self, "Geometry exported", "Geometry CSV was written.")
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Geometry export failed", str(exc))

    def import_polar(self) -> None:
        """Import TablePolar CSV."""

        path, _filter = QFileDialog.getOpenFileName(self, "Import polar CSV", "", "CSV files (*.csv);;All files (*)")
        if not path:
            return
        try:
            self.current_polar = TablePolar.from_csv(path)
            self.polar_mode_combo.setCurrentIndex(1)
            QMessageBox.information(self, "Polar imported", f"Imported {len(self.current_polar.points)} point(s).")
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Polar import failed", str(exc))

    def export_station_csv(self) -> None:
        """Export station results."""

        if self.current_result is None:
            QMessageBox.information(self, "No result", "Please calculate first.")
            return
        path, _filter = QFileDialog.getSaveFileName(self, "Export station CSV", "stations.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            export_station_csv(self.current_result, path)
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Station export failed", str(exc))

    def export_summary_csv(self) -> None:
        """Export summary results."""

        if self.current_result is None:
            QMessageBox.information(self, "No result", "Please calculate first.")
            return
        path, _filter = QFileDialog.getSaveFileName(self, "Export summary CSV", "summary.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            export_summary_csv(self.current_result, path)
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Summary export failed", str(exc))

    def run_scan(self) -> None:
        """Run RPM sweep with current inputs."""

        try:
            start = self.rpm_start_spin.value()
            end = self.rpm_end_spin.value()
            step = self.rpm_step_spin.value()
            if end < start:
                raise ValueError("rpm_end must be greater than or equal to rpm_start.")
            if step <= 0.0:
                raise ValueError("rpm_step must be positive.")
            base = self._input()
            polar = self._selected_polar()
            rows: list[dict[str, float | int]] = []
            rpm = start
            guard = 0
            while rpm <= end + 1e-9 and guard < 10000:
                result = calculate_propeller(replace(base, rpm=rpm), polar=polar, geometry=self.current_geometry)
                rows.append(
                    {
                        "RPM": rpm,
                        "T": result.thrust_N,
                        "Q": result.torque_Nm,
                        "P": result.power_W,
                        "eta": result.eta,
                        "CT": result.ct,
                        "CQ": result.cq,
                        "CP": result.cp,
                        "warnings_count": len(result.warnings),
                    }
                )
                rpm += step
                guard += 1
            self.scan_rows = rows
            self._fill_scan_table(rows)
            self.scan_plot.update_plot(rows)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "RPM sweep failed", str(exc))

    def _fill_scan_table(self, rows: list[dict[str, float | int]]) -> None:
        """Populate RPM sweep table."""

        self.scan_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col, name in enumerate(SCAN_COLUMNS):
                value = row.get(name, "")
                self.scan_table.setItem(row_index, col, QTableWidgetItem(_fmt(value) if isinstance(value, float) else str(value)))

    def export_scan(self) -> None:
        """Export RPM sweep rows."""

        if not self.scan_rows:
            QMessageBox.information(self, "No scan", "Please run a sweep first.")
            return
        path, _filter = QFileDialog.getSaveFileName(self, "Export sweep CSV", "rpm_sweep.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            export_scan_csv(self.scan_rows, path)
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Sweep export failed", str(exc))

    def browse_xfoil(self) -> None:
        """Browse for XFOIL executable."""

        path, _filter = QFileDialog.getOpenFileName(self, "Select XFOIL executable", "", "All files (*)")
        if path:
            self.xfoil_path_edit.setText(path)

    def browse_dat(self) -> None:
        """Browse for DAT airfoil coordinates."""

        path, _filter = QFileDialog.getOpenFileName(self, "Select DAT file", "", "DAT files (*.dat);;All files (*)")
        if path:
            self.dat_path_edit.setText(path)

    def check_xfoil(self) -> None:
        """Check whether XFOIL can be started."""

        runner = XfoilRunner(self.xfoil_path_edit.text() or "xfoil", self.timeout_spin.value())
        if runner.check_available():
            QMessageBox.information(self, "XFOIL", "XFOIL is available.")
        else:
            QMessageBox.warning(self, "XFOIL", "XFOIL executable was not found or did not start.")

    def _connect_re_range_inputs(self) -> None:
        """Connect propeller inputs that affect the estimated Reynolds range."""

        for spin in (
            self.diameter_spin,
            self.hub_spin,
            self.pitch_spin,
            self.pitch_angle_spin,
            self.root_chord_spin,
            self.tip_chord_spin,
            self.elements_spin,
            self.rpm_spin,
            self.vinf_spin,
            self.rho_spin,
            self.mu_spin,
            self.re_count_spin,
        ):
            spin.valueChanged.connect(self._auto_estimate_re_range)
        self.pitch_input_combo.currentIndexChanged.connect(self._auto_estimate_re_range)

    def _auto_estimate_re_range(self, *_args: object) -> None:
        """Silently refresh the Reynolds range when auto-estimation is enabled."""

        if not self.auto_re_range_check.isChecked():
            return
        self._update_re_range_from_inputs(log=False, show_errors=False)

    def estimate_re_range(self) -> None:
        """Estimate Reynolds range for XFOIL from current propeller inputs."""

        self._update_re_range_from_inputs(log=True, show_errors=True, enable_multi=True)

    def _update_re_range_from_inputs(
        self,
        log: bool,
        show_errors: bool,
        enable_multi: bool = False,
    ) -> bool:
        """Update XFOIL Reynolds controls from current propeller inputs."""

        try:
            estimate = estimate_reynolds_range(self._input(), self.current_geometry)
            re_min = estimate["re_min"]
            re_max = estimate["re_max"]
            values = representative_reynolds_values(re_min, re_max, self.re_count_spin.value())
            _set_spin_value_silently(self.re_min_spin, re_min)
            _set_spin_value_silently(self.re_max_spin, re_max)
            if values:
                _set_spin_value_silently(self.xfoil_re_spin, values[len(values) // 2])
            if enable_multi:
                self.use_multi_re_check.setChecked(True)
            if log:
                self.xfoil_log.append(
                    f"Estimated Re range: {re_min:.6g} to {re_max:.6g}; values: "
                    + ", ".join(f"{value:.6g}" for value in values)
                )
            return True
        except Exception as exc:  # noqa: BLE001
            if show_errors:
                _show_error(self, "Reynolds estimate failed", str(exc))
            elif log:
                self.xfoil_log.append(f"Reynolds estimate failed: {exc}")
            return False

    def run_xfoil(self) -> None:
        """Start XFOIL worker thread."""

        if self.xfoil_thread is not None:
            QMessageBox.information(self, "XFOIL", "XFOIL is already running.")
            return
        source_type = self.airfoil_source_combo.currentText()
        if source_type == "DAT file" and not self.dat_path_edit.text().strip():
            QMessageBox.warning(self, "XFOIL", "Please select a DAT file.")
            return

        self.run_xfoil_button.setEnabled(False)
        self.xfoil_log.append("Starting worker thread.")
        reynolds_values = self._xfoil_reynolds_values()
        self.xfoil_thread = QThread(self)
        self.xfoil_worker = XfoilWorker(
            self.xfoil_path_edit.text() or "xfoil",
            source_type,
            self.naca_edit.text() or "4412",
            self.dat_path_edit.text(),
            self.xfoil_re_spin.value(),
            reynolds_values,
            self.xfoil_mach_spin.value(),
            self.alpha_start_spin.value(),
            self.alpha_end_spin.value(),
            self.alpha_step_spin.value(),
            self.iter_spin.value(),
            self.panels_spin.value(),
            self.timeout_spin.value(),
        )
        self.xfoil_worker.moveToThread(self.xfoil_thread)
        self.xfoil_thread.started.connect(self.xfoil_worker.run)
        self.xfoil_worker.log.connect(self.xfoil_log.append)
        self.xfoil_worker.finished.connect(self._xfoil_finished)
        self.xfoil_worker.failed.connect(self._xfoil_failed)
        self.xfoil_worker.finished.connect(self.xfoil_thread.quit)
        self.xfoil_worker.failed.connect(self.xfoil_thread.quit)
        self.xfoil_thread.finished.connect(self._xfoil_cleanup)
        self.xfoil_thread.start()

    def _xfoil_finished(self, result: XfoilRunResult) -> None:
        """Handle completed XFOIL run."""

        self.xfoil_points = result.points
        self.xfoil_reynolds_tables = result.reynolds_tables
        self._fill_xfoil_table(result.points)
        self.polar_plot.update_plot(result.points)
        if result.reynolds_tables:
            self.xfoil_log.append(
                "Reynolds tables: " + ", ".join(f"{value:.6g}" for value in sorted(result.reynolds_tables))
            )
        self.xfoil_log.append(_short_log("stdout", result.stdout))
        self.xfoil_log.append(_short_log("stderr", result.stderr))
        if result.warnings:
            self.xfoil_log.append("Warnings:")
            self.xfoil_log.append("\n".join(result.warnings))
        if len(result.points) < 5:
            self.xfoil_log.append("Fewer than 5 points; this polar cannot be used directly.")

    def _xfoil_reynolds_values(self) -> list[float]:
        """Return one or more Reynolds values requested for XFOIL."""

        if not self.use_multi_re_check.isChecked():
            return [self.xfoil_re_spin.value()]
        return representative_reynolds_values(
            self.re_min_spin.value(),
            self.re_max_spin.value(),
            self.re_count_spin.value(),
        )

    def _xfoil_failed(self, message: str) -> None:
        """Handle failed XFOIL worker."""

        self.xfoil_log.append(f"XFOIL failed: {message}")
        QMessageBox.warning(self, "XFOIL failed", message)

    def _xfoil_cleanup(self) -> None:
        """Release worker thread references."""

        self.run_xfoil_button.setEnabled(True)
        if self.xfoil_worker is not None:
            self.xfoil_worker.deleteLater()
        if self.xfoil_thread is not None:
            self.xfoil_thread.deleteLater()
        self.xfoil_worker = None
        self.xfoil_thread = None

    def _fill_xfoil_table(self, points: list[XfoilPolarPoint]) -> None:
        """Populate XFOIL polar table."""

        self.xfoil_table.setRowCount(len(points))
        for row, point in enumerate(points):
            values = [
                point.alpha_deg,
                point.cl,
                point.cd,
                point.cdp,
                point.cm,
                "" if point.xtr_top is None else point.xtr_top,
                "" if point.xtr_bottom is None else point.xtr_bottom,
            ]
            for col, value in enumerate(values):
                self.xfoil_table.setItem(row, col, QTableWidgetItem(_fmt(value) if isinstance(value, float) else str(value)))

    def save_xfoil_csv(self) -> None:
        """Save generated XFOIL polar points."""

        if not self.xfoil_points:
            QMessageBox.information(self, "No polar", "Please run XFOIL first.")
            return
        path, _filter = QFileDialog.getSaveFileName(self, "Save polar CSV", "xfoil_polar.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            XfoilRunner.export_xfoil_points_to_csv(self.xfoil_points, path)
            QMessageBox.information(self, "Polar saved", "Polar CSV was written.")
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Polar save failed", str(exc))

    def use_xfoil_polar(self) -> None:
        """Use generated XFOIL points as the active TablePolar."""

        if len(self.xfoil_points) < 5:
            QMessageBox.warning(self, "Polar unavailable", "At least 5 XFOIL points are required.")
            return
        if len(self.xfoil_reynolds_tables) > 1:
            multi = MultiRePolar()
            usable = 0
            for reynolds, table_points in sorted(self.xfoil_reynolds_tables.items()):
                if len(table_points) < 5:
                    continue
                points = [
                    PolarPoint(
                        alpha_deg=p.alpha_deg,
                        cl=p.cl,
                        cd=p.cd,
                        cm=p.cm,
                        cdp=p.cdp,
                        xtr_top=p.xtr_top,
                        xtr_bottom=p.xtr_bottom,
                    )
                    for p in table_points
                ]
                multi.add_table(reynolds, TablePolar(points))
                usable += 1
            if usable < 2:
                QMessageBox.warning(self, "Polar unavailable", "At least 2 Reynolds tables with 5 points each are required.")
                return
            self.current_polar = multi
            self.polar_mode_combo.setCurrentIndex(2)
            QMessageBox.information(self, "Polar active", "Multi-Re XFOIL polar is now the current polar.")
            return
        points = [
            PolarPoint(
                alpha_deg=p.alpha_deg,
                cl=p.cl,
                cd=p.cd,
                cm=p.cm,
                cdp=p.cdp,
                xtr_top=p.xtr_top,
                xtr_bottom=p.xtr_bottom,
            )
            for p in self.xfoil_points
        ]
        self.current_polar = TablePolar(points)
        self.polar_mode_combo.setCurrentIndex(2)
        QMessageBox.information(self, "Polar active", "XFOIL polar is now the current polar.")


def _spin_int(minimum: int, maximum: int, value: int) -> QSpinBox:
    """Create a configured integer spin box."""

    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    return spin


def _spin_float(minimum: float, maximum: float, value: float, decimals: int, step: float) -> QDoubleSpinBox:
    """Create a configured double spin box."""

    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(decimals)
    spin.setSingleStep(step)
    spin.setValue(value)
    return spin


def _set_spin_value_silently(spin: QDoubleSpinBox | QSpinBox, value: float) -> None:
    """Set a spin-box value without emitting valueChanged."""

    spin.blockSignals(True)
    try:
        spin.setValue(value)
    finally:
        spin.blockSignals(False)


def _fmt(value: object) -> str:
    """Format table and label values without NaN strings."""

    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return "0"
        return f"{value:.6g}"
    return str(value)


def _show_error(parent: QWidget, title: str, message: str) -> None:
    """Show an error dialog."""

    QMessageBox.critical(parent, title, message)


def _short_log(name: str, text: str, max_chars: int = 3000) -> str:
    """Return a bounded log block for display."""

    if not text:
        return f"{name}:"
    trimmed = text[-max_chars:]
    return f"{name}:\n{trimmed}"


STATION_COLUMNS = [
    ("r/R", "r_over_R"),
    ("r_m", "r_m"),
    ("dr_m", "dr_m"),
    ("chord_m", "chord_m"),
    ("beta_deg", "beta_deg"),
    ("phi_deg", "phi_deg"),
    ("alpha_deg", "alpha_deg"),
    ("Re", "reynolds"),
    ("Mach", "mach"),
    ("Cl", "cl"),
    ("Cd", "cd"),
    ("Cm", "cm"),
    ("vi_mps", "vi_mps"),
    ("vt_mps", "vt_mps"),
    ("F", "tip_loss_F"),
    ("dT/dr", "dT_dr"),
    ("dQ/dr", "dQ_dr"),
    ("warning", "warning"),
]

SCAN_COLUMNS = ["RPM", "T", "Q", "P", "eta", "CT", "CQ", "CP", "warnings_count"]
XFOIL_COLUMNS = ["alpha", "Cl", "Cd", "CDp", "Cm", "Xtr_top", "Xtr_bottom"]
DIAGNOSTIC_KEYS = [
    "requested_mode",
    "actual_mode",
    "J",
    "mu_adv",
    "max_alpha_deg",
    "stall_station_fraction",
    "low_re_station_fraction",
    "negative_thrust_station_fraction",
    "max_vi_mps",
    "solver_fallback_fraction",
]


def run_app() -> int:
    """Run the Qt application."""

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()
