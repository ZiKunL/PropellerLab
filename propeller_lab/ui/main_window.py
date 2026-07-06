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
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from propeller_lab.core.bemt import calculate_propeller
from propeller_lab.core.design import DesignInput, DesignResult, clone_geometry, design_twist_with_target
from propeller_lab.core.export import (
    export_design_station_csv,
    export_optimization_history_csv,
    export_optimization_summary_csv,
    export_scan_csv,
    export_station_csv,
    export_summary_csv,
)
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
from propeller_lab.core.optimizer import (
    CandidateEvaluation,
    OptimizationHistoryRow,
    TargetOptimizationInput,
    TargetOptimizationResult,
    estimate_optimization_reynolds_range,
)
from propeller_lab.core.polar import AirfoilPolar, MultiAirfoilPolar, MultiRePolar, TablePolar, normalize_airfoil_id
from propeller_lab.core.xfoil_runner import XfoilPolarPoint, XfoilRunResult, XfoilRunner
from propeller_lab.ui.app_state import AppState
from propeller_lab.ui.optimization_worker import (
    AirfoilComparisonWorker,
    OptimizationWorker,
    TargetAirfoilComparisonResult,
    TargetAirfoilXfoilItem,
    TargetAirfoilXfoilResult,
    TargetAirfoilXfoilWorker,
)
from propeller_lab.ui.plot_widgets import (
    AeroPlotWidget,
    DesignPlotWidget,
    LoadPlotWidget,
    OptimizedGeometryPlotWidget,
    OptimizationHistoryPlotWidget,
    PolarPlotWidget,
    ScanPlotWidget,
)
from propeller_lab.ui.xfoil_worker import XfoilWorker


class MainWindow(QMainWindow):
    """Desktop window that connects UI controls to the core package."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PropellerLab - Propeller Thrust and Torque Calculator")
        self.resize(1280, 820)

        self.app_state = AppState(prop_input=PropellerInput())
        self.current_result = None
        self.current_geometry = None
        self.current_polar = None
        self.xfoil_points: list[XfoilPolarPoint] = []
        self.xfoil_reynolds_tables: dict[float, list[XfoilPolarPoint]] = {}
        self.xfoil_display_reynolds: float | None = None
        self.scan_rows: list[dict[str, float | int]] = []
        self.xfoil_thread: QThread | None = None
        self.xfoil_worker: XfoilWorker | None = None
        self.optimization_thread: QThread | None = None
        self.optimization_worker: OptimizationWorker | AirfoilComparisonWorker | None = None
        self.target_xfoil_thread: QThread | None = None
        self.target_xfoil_worker: TargetAirfoilXfoilWorker | None = None
        self.target_airfoil_polar: MultiAirfoilPolar | None = None
        self.target_airfoil_comparison_result: TargetAirfoilComparisonResult | None = None
        self.target_progress_history: list[OptimizationHistoryRow] = []
        self._target_plot_warning_shown = False
        self._target_detail_refresh_generation = -1
        self._pitch_syncing = False

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(6, 6, 6, 6)
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Workspace:"))
        self.workspace_combo = QComboBox()
        self.workspace_combo.addItem("Base Calculate")
        self.workspace_combo.addItem("Optimization Design")
        self.workspace_combo.addItem("Target Optimization")
        top_bar.addWidget(self.workspace_combo)
        top_bar.addStretch(1)
        central_layout.addLayout(top_bar)

        self.workspace_stack = QStackedWidget()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_input_panel())
        splitter.addWidget(self._build_tabs())
        splitter.setSizes([360, 920])
        self.workspace_stack.addWidget(splitter)
        self.workspace_stack.addWidget(self._build_design_workspace())
        self.workspace_stack.addWidget(self._build_target_optimization_workspace())
        central_layout.addWidget(self.workspace_stack, 1)
        self.workspace_combo.currentIndexChanged.connect(self.workspace_stack.setCurrentIndex)
        self.setCentralWidget(central)
        self._update_design_control_state()
        self._connect_re_range_inputs()
        self._update_re_range_from_inputs(log=False, show_errors=False)

    @property
    def current_result(self) -> PropellerResult | None:
        """Return the last Base Calculate result."""

        return self.app_state.last_analysis_result

    @current_result.setter
    def current_result(self, value: PropellerResult | None) -> None:
        self.app_state.last_analysis_result = value

    @property
    def current_geometry(self) -> list[GeometryStation] | None:
        """Return the active shared geometry."""

        return self.app_state.current_geometry

    @current_geometry.setter
    def current_geometry(self, value: list[GeometryStation] | None) -> None:
        self.app_state.current_geometry = value

    @property
    def current_polar(self) -> AirfoilPolar | None:
        """Return the active shared polar."""

        return self.app_state.current_polar

    @current_polar.setter
    def current_polar(self, value: AirfoilPolar | None) -> None:
        self.app_state.current_polar = value

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
        layout.addRow("Solver mode", self.calc_mode_combo)
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
        self.xfoil_path_edit = QLineEdit(_default_xfoil_path())
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
        self.airfoil_source_combo.currentIndexChanged.connect(self._update_airfoil_source_controls)
        self.run_xfoil_button.clicked.connect(self.run_xfoil)
        self.save_xfoil_button.clicked.connect(self.save_xfoil_csv)
        self.use_xfoil_button.clicked.connect(self.use_xfoil_polar)
        self._update_airfoil_source_controls()
        return widget

    def _build_design_workspace(self) -> QWidget:
        """Build the Optimization Design workspace."""

        widget = QWidget()
        layout = QVBoxLayout(widget)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.addWidget(self._design_method_group())
        controls_layout.addWidget(self._design_objective_group())
        controls_layout.addWidget(self._design_constraints_group())
        controls_layout.addWidget(self._design_button_group())
        controls_layout.addStretch(1)
        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setWidget(controls)
        splitter.addWidget(controls_scroll)
        splitter.addWidget(self._design_output_tabs())
        splitter.setSizes([380, 900])
        layout.addWidget(splitter)
        return widget

    def _design_method_group(self) -> QGroupBox:
        """Build design method and condition controls."""

        group = QGroupBox("Design method")
        layout = QFormLayout(group)
        self.design_method_combo = QComboBox()
        self.design_method_combo.addItem("Max Cl/Cd Twist Design", "none")
        self.design_method_combo.addItem("Target Thrust Twist Design", "thrust")
        self.design_method_combo.addItem("Target Power Twist Design", "power")
        self.design_rpm_spin = _spin_float(0.0, 200000.0, self.rpm_spin.value(), 1, 100.0)
        self.design_vinf_spin = _spin_float(0.0, 400.0, self.vinf_spin.value(), 3, 0.1)
        self.design_target_type_combo = QComboBox()
        self.design_target_type_combo.addItem("None", "none")
        self.design_target_type_combo.addItem("Target thrust", "thrust")
        self.design_target_type_combo.addItem("Target power", "power")
        self.design_target_value_spin = _spin_float(0.0, 1000000.0, 0.0, 3, 1.0)
        layout.addRow("Design method", self.design_method_combo)
        layout.addRow("Design RPM", self.design_rpm_spin)
        layout.addRow("Design V_inf, m/s", self.design_vinf_spin)
        layout.addRow("Target type", self.design_target_type_combo)
        layout.addRow("Target value", self.design_target_value_spin)
        self.design_method_combo.currentIndexChanged.connect(self._sync_design_method_target)
        self.design_target_type_combo.currentIndexChanged.connect(self._update_design_control_state)
        return group

    def _design_objective_group(self) -> QGroupBox:
        """Build alpha objective controls."""

        group = QGroupBox("Alpha objective")
        layout = QFormLayout(group)
        self.design_alpha_objective_combo = QComboBox()
        self.design_alpha_objective_combo.addItem("Max Cl/Cd", "max_ld")
        self.design_alpha_objective_combo.addItem("Max local thrust/torque ratio", "max_local_efficiency")
        self.design_alpha_objective_combo.addItem("Fixed alpha", "fixed_alpha")
        self.design_fixed_alpha_spin = _spin_float(-20.0, 30.0, 5.0, 2, 0.25)
        self.design_alpha_min_spin = _spin_float(-30.0, 30.0, -4.0, 2, 0.25)
        self.design_alpha_max_spin = _spin_float(-30.0, 40.0, 12.0, 2, 0.25)
        self.design_alpha_step_spin = _spin_float(0.05, 5.0, 0.25, 2, 0.05)
        self.design_stall_margin_spin = _spin_float(0.0, 10.0, 2.0, 2, 0.25)
        self.design_max_cl_fraction_spin = _spin_float(0.1, 1.0, 0.85, 3, 0.05)
        layout.addRow("Alpha objective", self.design_alpha_objective_combo)
        layout.addRow("Fixed alpha, deg", self.design_fixed_alpha_spin)
        layout.addRow("Alpha min, deg", self.design_alpha_min_spin)
        layout.addRow("Alpha max, deg", self.design_alpha_max_spin)
        layout.addRow("Alpha step, deg", self.design_alpha_step_spin)
        layout.addRow("Stall margin, deg", self.design_stall_margin_spin)
        layout.addRow("Max Cl fraction", self.design_max_cl_fraction_spin)
        self.design_alpha_objective_combo.currentIndexChanged.connect(self._update_design_control_state)
        return group

    def _design_constraints_group(self) -> QGroupBox:
        """Build design constraints controls."""

        group = QGroupBox("Constraints")
        layout = QFormLayout(group)
        self.design_beta_min_spin = _spin_float(-20.0, 80.0, 0.0, 2, 0.5)
        self.design_beta_max_spin = _spin_float(-20.0, 90.0, 60.0, 2, 0.5)
        self.design_max_tip_mach_spin = _spin_float(0.1, 2.0, 0.75, 3, 0.05)
        self.design_chord_mode_combo = QComboBox()
        self.design_chord_mode_combo.addItem("Keep current chord", "keep_current")
        self.design_chord_mode_combo.addItem("Linear chord", "linear")
        self.design_allow_beta_offset_check = QCheckBox("Allow beta offset")
        self.design_allow_beta_offset_check.setChecked(True)
        layout.addRow("Beta min, deg", self.design_beta_min_spin)
        layout.addRow("Beta max, deg", self.design_beta_max_spin)
        layout.addRow("Max tip Mach", self.design_max_tip_mach_spin)
        layout.addRow("Chord mode", self.design_chord_mode_combo)
        layout.addRow(self.design_allow_beta_offset_check)
        return group

    def _design_button_group(self) -> QGroupBox:
        """Build design action buttons."""

        group = QGroupBox("Actions")
        layout = QGridLayout(group)
        self.generate_design_button = QPushButton("Generate design")
        self.analyze_design_button = QPushButton("Analyze generated design")
        self.apply_design_button = QPushButton("Apply to Base Calculate")
        self.export_design_geometry_button = QPushButton("Export designed geometry CSV")
        self.export_design_station_button = QPushButton("Export design station CSV")
        buttons = [
            self.generate_design_button,
            self.analyze_design_button,
            self.apply_design_button,
            self.export_design_geometry_button,
            self.export_design_station_button,
        ]
        for idx, button in enumerate(buttons):
            layout.addWidget(button, idx, 0)
        self.generate_design_button.clicked.connect(self.generate_design)
        self.analyze_design_button.clicked.connect(self.analyze_generated_design)
        self.apply_design_button.clicked.connect(self.apply_design_to_base)
        self.export_design_geometry_button.clicked.connect(self.export_design_geometry)
        self.export_design_station_button.clicked.connect(self.export_design_station_csv)
        return group

    def _design_output_tabs(self) -> QTabWidget:
        """Build design result tabs."""

        tabs = QTabWidget()
        tabs.addTab(self._design_summary_tab(), "Design summary")
        tabs.addTab(self._design_station_table_tab(), "Design station table")
        self.design_plot = DesignPlotWidget()
        tabs.addTab(self.design_plot, "Design plots")
        return tabs

    def _design_summary_tab(self) -> QWidget:
        """Build design summary tab."""

        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        self.design_summary_labels: dict[str, QLabel] = {}
        for key, label in DESIGN_SUMMARY_ROWS:
            value_label = QLabel("-")
            self.design_summary_labels[key] = value_label
            form.addRow(label, value_label)
        layout.addLayout(form)
        self.design_warning_text = QTextEdit()
        self.design_warning_text.setReadOnly(True)
        self.design_warning_text.setPlaceholderText("Design warnings")
        layout.addWidget(self.design_warning_text, 1)
        return widget

    def _design_station_table_tab(self) -> QWidget:
        """Build design station table tab."""

        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.design_station_table = QTableWidget(0, len(DESIGN_COLUMNS))
        self.design_station_table.setHorizontalHeaderLabels([label for label, _attr in DESIGN_COLUMNS])
        self.design_station_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.design_station_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.design_station_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.design_station_table)
        return widget

    def _build_target_optimization_workspace(self) -> QWidget:
        """Build the Target Optimization workspace."""

        widget = QWidget()
        layout = QVBoxLayout(widget)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.addWidget(self._target_conditions_group())
        controls_layout.addWidget(self._target_airfoil_group())
        controls_layout.addWidget(self._target_bounds_group())
        controls_layout.addWidget(self._target_algorithm_group())
        controls_layout.addWidget(self._target_button_group())
        controls_layout.addStretch(1)
        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setWidget(controls)
        splitter.addWidget(controls_scroll)
        splitter.addWidget(self._target_output_tabs())
        splitter.setSizes([420, 860])
        layout.addWidget(splitter)
        self._sync_target_from_base()
        self._update_target_mode_controls()
        return widget

    def _target_conditions_group(self) -> QGroupBox:
        """Build target and operating condition controls."""

        group = QGroupBox("Target and operating point")
        layout = QFormLayout(group)
        self.target_mode_combo = QComboBox()
        self.target_mode_combo.addItem("Target thrust, minimize power", "target_thrust_min_power")
        self.target_mode_combo.addItem("Target thrust with torque limit", "target_thrust_torque_limited")
        self.target_mode_combo.addItem("Target torque, maximize thrust", "target_torque_max_thrust")
        self.target_mode_combo.addItem("Match thrust", "match_thrust")
        self.target_mode_combo.addItem("Match torque", "match_torque")
        self.target_thrust_spin = _spin_float(0.0, 1000000.0, 1.0, 4, 0.1)
        self.target_torque_spin = _spin_float(0.0, 1000000.0, 0.05, 5, 0.01)
        self.target_torque_limit_spin = _spin_float(0.0, 1000000.0, 0.08, 5, 0.01)
        self.target_power_limit_spin = _spin_float(0.0, 100000000.0, 0.0, 3, 1.0)
        self.target_blades_spin = _spin_int(1, 12, 2)
        self.target_diameter_mode_combo = QComboBox()
        self.target_diameter_mode_combo.addItem("Fixed diameter", "fixed")
        self.target_diameter_mode_combo.addItem("Optimize diameter range", "range")
        self.target_diameter_spin = _spin_float(0.001, 10.0, 0.254, 4, 0.001)
        self.target_diameter_min_spin = _spin_float(0.001, 10.0, 0.254, 4, 0.001)
        self.target_diameter_max_spin = _spin_float(0.001, 10.0, 0.254, 4, 0.001)
        self.target_diameter_label = QLabel("Diameter D, m")
        self.target_diameter_min_label = QLabel("Diameter min D, m")
        self.target_diameter_max_label = QLabel("Diameter max D, m")
        self.target_hub_spin = _spin_float(0.0, 9.0, 0.035, 4, 0.001)
        self.target_rpm_spin = _spin_float(0.0, 200000.0, 8000.0, 1, 100.0)
        self.target_vinf_spin = _spin_float(0.0, 400.0, 0.0, 3, 0.1)
        self.target_rho_spin = _spin_float(0.001, 50.0, 1.225, 4, 0.001)
        self.target_mu_spin = _spin_float(0.00000001, 0.1, 1.81e-5, 8, 0.000001)
        self.target_sound_speed_spin = _spin_float(1.0, 2000.0, 343.0, 3, 1.0)
        self.target_elements_spin = _spin_int(3, 500, 40)
        self.sync_target_base_button = QPushButton("Use Base Calculate inputs")
        self.target_polar_label = QLabel("Polar: Generic airfoil")
        self.target_polar_label.setWordWrap(True)
        self.use_target_polar_button = QPushButton("Use current Base polar")

        layout.addRow("Target mode", self.target_mode_combo)
        layout.addRow("Target thrust, N", self.target_thrust_spin)
        layout.addRow("Target torque, N*m", self.target_torque_spin)
        layout.addRow("Torque limit, N*m", self.target_torque_limit_spin)
        layout.addRow("Power limit, W", self.target_power_limit_spin)
        layout.addRow("Blades B", self.target_blades_spin)
        layout.addRow("Diameter mode", self.target_diameter_mode_combo)
        layout.addRow(self.target_diameter_label, self.target_diameter_spin)
        layout.addRow(self.target_diameter_min_label, self.target_diameter_min_spin)
        layout.addRow(self.target_diameter_max_label, self.target_diameter_max_spin)
        layout.addRow("Hub diameter, m", self.target_hub_spin)
        layout.addRow("RPM", self.target_rpm_spin)
        layout.addRow("V_inf, m/s", self.target_vinf_spin)
        layout.addRow("Density rho", self.target_rho_spin)
        layout.addRow("Dynamic viscosity mu", self.target_mu_spin)
        layout.addRow("Sound speed a", self.target_sound_speed_spin)
        layout.addRow("Elements", self.target_elements_spin)
        layout.addRow(self.target_polar_label)
        layout.addRow(self.sync_target_base_button, self.use_target_polar_button)

        self.target_mode_combo.currentIndexChanged.connect(self._update_target_mode_controls)
        self.target_diameter_mode_combo.currentIndexChanged.connect(self._update_target_diameter_mode_controls)
        self.sync_target_base_button.clicked.connect(self._sync_target_from_base)
        self.use_target_polar_button.clicked.connect(self._refresh_target_polar_label)
        self._update_target_diameter_mode_controls()
        return group

    def _target_airfoil_group(self) -> QGroupBox:
        """Build target multi-airfoil preprocessing controls."""

        group = QGroupBox("Airfoils and XFOIL preprocessing")
        layout = QFormLayout(group)
        self.target_airfoil_mode_combo = QComboBox()
        self.target_airfoil_mode_combo.addItem("Hybrid root-to-tip", "hybrid")
        self.target_airfoil_mode_combo.addItem("Compare uniform airfoils", "compare_uniform")
        self.target_airfoil_source_combo = QComboBox()
        self.target_airfoil_source_combo.addItem("NACA list", "naca")
        self.target_airfoil_source_combo.addItem("DAT files", "dat")
        self.target_airfoil_source_combo.addItem("NACA + DAT candidates", "mixed")
        self.target_airfoil_codes_edit = QLineEdit("4412")
        self.target_airfoil_codes_edit.setPlaceholderText("4412, 2412, 0012")
        self.target_dat_paths_edit = QTextEdit()
        self.target_dat_paths_edit.setPlaceholderText("One DAT file path per line")
        self.target_dat_paths_edit.setFixedHeight(70)
        self.target_dat_browse_button = QPushButton("Browse DAT files")
        self.target_re_min_spin = _spin_float(1000.0, 50000000.0, 50000.0, 0, 1000.0)
        self.target_re_max_spin = _spin_float(1000.0, 50000000.0, 300000.0, 0, 1000.0)
        self.target_re_count_spin = _spin_int(1, 7, 3)
        self.target_estimate_re_button = QPushButton("Estimate optimization Re")
        self.target_build_xfoil_button = QPushButton("Build target XFOIL polars")
        self.target_airfoil_status_label = QLabel("Target airfoil polar: not built")
        self.target_airfoil_status_label.setWordWrap(True)

        layout.addRow("Airfoil optimization mode", self.target_airfoil_mode_combo)
        layout.addRow("Airfoil source", self.target_airfoil_source_combo)
        layout.addRow("NACA airfoils", self.target_airfoil_codes_edit)
        layout.addRow("DAT files", self.target_dat_paths_edit)
        layout.addRow(self.target_dat_browse_button)
        layout.addRow("Target Re min", self.target_re_min_spin)
        layout.addRow("Target Re max", self.target_re_max_spin)
        layout.addRow("Target Re count", self.target_re_count_spin)
        layout.addRow(self.target_estimate_re_button)
        layout.addRow(self.target_build_xfoil_button)
        layout.addRow(self.target_airfoil_status_label)

        self.target_airfoil_mode_combo.currentIndexChanged.connect(self._update_target_airfoil_mode_controls)
        self.target_airfoil_source_combo.currentIndexChanged.connect(self._update_target_airfoil_source_controls)
        self.target_airfoil_codes_edit.textChanged.connect(self._clear_target_airfoil_polar)
        self.target_dat_paths_edit.textChanged.connect(self._clear_target_airfoil_polar)
        self.target_dat_browse_button.clicked.connect(self.browse_target_dat_files)
        self.target_estimate_re_button.clicked.connect(self.estimate_target_optimization_re_range)
        self.target_build_xfoil_button.clicked.connect(self.build_target_xfoil_polars)
        self._update_target_airfoil_mode_controls()
        self._update_target_airfoil_source_controls()
        return group

    def _target_bounds_group(self) -> QGroupBox:
        """Build target optimization geometry and diagnostic bounds."""

        group = QGroupBox("Geometry bounds and diagnostics")
        layout = QFormLayout(group)
        self.target_control_points_spin = _spin_int(2, 20, 6)
        self.target_chord_min_spin = _spin_float(0.001, 1.0, 0.03, 4, 0.001)
        self.target_chord_max_spin = _spin_float(0.001, 1.0, 0.18, 4, 0.001)
        self.target_beta_min_spin = _spin_float(-20.0, 90.0, 2.0, 2, 0.5)
        self.target_beta_max_spin = _spin_float(-20.0, 90.0, 45.0, 2, 0.5)
        self.target_max_tip_mach_spin = _spin_float(0.1, 2.0, 0.75, 3, 0.05)
        self.target_max_alpha_spin = _spin_float(0.1, 90.0, 18.0, 2, 0.5)
        self.target_max_stall_fraction_spin = _spin_float(0.0, 1.0, 0.35, 3, 0.05)
        self.target_max_low_re_fraction_spin = _spin_float(0.0, 1.0, 0.50, 3, 0.05)
        layout.addRow("Control points", self.target_control_points_spin)
        layout.addRow("Chord min c/R", self.target_chord_min_spin)
        layout.addRow("Chord max c/R", self.target_chord_max_spin)
        layout.addRow("Beta min, deg", self.target_beta_min_spin)
        layout.addRow("Beta max, deg", self.target_beta_max_spin)
        layout.addRow("Max tip Mach", self.target_max_tip_mach_spin)
        layout.addRow("Max alpha, deg", self.target_max_alpha_spin)
        layout.addRow("Max stall fraction", self.target_max_stall_fraction_spin)
        layout.addRow("Max low Re fraction", self.target_max_low_re_fraction_spin)
        return group

    def _target_algorithm_group(self) -> QGroupBox:
        """Build target optimization algorithm controls."""

        group = QGroupBox("Optimizer")
        layout = QFormLayout(group)
        self.target_method_combo = QComboBox()
        self.target_method_combo.addItem("Genetic algorithm", "genetic_algorithm")
        self.target_method_combo.addItem("Random search", "random_search")
        self.target_method_combo.addItem("GA + local refine", "ga_local_refine")
        self.target_population_spin = _spin_int(2, 500, 40)
        self.target_generations_spin = _spin_int(1, 500, 40)
        self.target_mutation_spin = _spin_float(0.0, 1.0, 0.15, 3, 0.01)
        self.target_crossover_spin = _spin_float(0.0, 1.0, 0.75, 3, 0.01)
        self.target_elitism_spin = _spin_int(0, 50, 2)
        self.target_tournament_spin = _spin_int(1, 20, 3)
        self.target_seed_spin = _spin_int(0, 1000000000, 1)
        self.target_smoothness_weight_spin = _spin_float(0.0, 100.0, 0.05, 4, 0.01)
        self.target_power_weight_spin = _spin_float(0.0, 100.0, 0.10, 4, 0.01)
        self.target_torque_weight_spin = _spin_float(0.0, 100.0, 2.0, 4, 0.1)
        self.target_constraint_weight_spin = _spin_float(0.0, 100.0, 5.0, 4, 0.1)
        layout.addRow("Method", self.target_method_combo)
        layout.addRow("Population size", self.target_population_spin)
        layout.addRow("Generations", self.target_generations_spin)
        layout.addRow("Mutation rate", self.target_mutation_spin)
        layout.addRow("Crossover rate", self.target_crossover_spin)
        layout.addRow("Elitism count", self.target_elitism_spin)
        layout.addRow("Tournament size", self.target_tournament_spin)
        layout.addRow("Random seed", self.target_seed_spin)
        layout.addRow("Smoothness weight", self.target_smoothness_weight_spin)
        layout.addRow("Power weight", self.target_power_weight_spin)
        layout.addRow("Torque weight", self.target_torque_weight_spin)
        layout.addRow("Constraint weight", self.target_constraint_weight_spin)
        return group

    def _target_button_group(self) -> QGroupBox:
        """Build target optimization action buttons."""

        group = QGroupBox("Actions")
        layout = QGridLayout(group)
        self.start_target_button = QPushButton("Start optimization")
        self.stop_target_button = QPushButton("Stop")
        self.apply_target_button = QPushButton("Apply best to Base Calculate")
        self.export_target_geometry_button = QPushButton("Export best geometry CSV")
        self.export_target_history_button = QPushButton("Export history CSV")
        self.export_target_summary_button = QPushButton("Export summary CSV")
        buttons = [
            self.start_target_button,
            self.stop_target_button,
            self.apply_target_button,
            self.export_target_geometry_button,
            self.export_target_history_button,
            self.export_target_summary_button,
        ]
        for idx, button in enumerate(buttons):
            layout.addWidget(button, idx // 2, idx % 2)
        self.stop_target_button.setEnabled(False)
        self.apply_target_button.setEnabled(False)
        self.export_target_geometry_button.setEnabled(False)
        self.export_target_history_button.setEnabled(False)
        self.export_target_summary_button.setEnabled(False)
        self.start_target_button.clicked.connect(self.start_target_optimization)
        self.stop_target_button.clicked.connect(self.stop_target_optimization)
        self.apply_target_button.clicked.connect(self.apply_target_optimization_to_base)
        self.export_target_geometry_button.clicked.connect(self.export_target_geometry)
        self.export_target_history_button.clicked.connect(self.export_target_history)
        self.export_target_summary_button.clicked.connect(self.export_target_summary)
        return group

    def _target_output_tabs(self) -> QTabWidget:
        """Build target optimization output tabs."""

        tabs = QTabWidget()
        tabs.addTab(self._target_summary_tab(), "Optimization summary")
        tabs.addTab(self._target_airfoil_comparison_tab(), "Airfoil comparison")
        tabs.addTab(self._target_history_table_tab(), "History")
        tabs.addTab(self._target_geometry_table_tab(), "Best geometry")
        self.target_history_plot = OptimizationHistoryPlotWidget()
        tabs.addTab(self.target_history_plot, "Convergence")
        self.target_geometry_plot = OptimizedGeometryPlotWidget()
        tabs.addTab(self.target_geometry_plot, "Geometry plots")
        return tabs

    def _target_summary_tab(self) -> QWidget:
        """Build target optimization summary tab."""

        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        self.target_summary_labels: dict[str, QLabel] = {}
        for key, label in TARGET_SUMMARY_ROWS:
            value_label = QLabel("-")
            self.target_summary_labels[key] = value_label
            form.addRow(label, value_label)
        layout.addLayout(form)
        self.target_warning_text = QTextEdit()
        self.target_warning_text.setReadOnly(True)
        self.target_warning_text.setPlaceholderText("Optimization log and warnings")
        layout.addWidget(self.target_warning_text, 1)
        return widget

    def _target_airfoil_comparison_tab(self) -> QWidget:
        """Build target optimization uniform-airfoil comparison table."""

        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.target_airfoil_comparison_table = QTableWidget(0, len(TARGET_COMPARISON_COLUMNS))
        self.target_airfoil_comparison_table.setHorizontalHeaderLabels(TARGET_COMPARISON_COLUMNS)
        self.target_airfoil_comparison_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.target_airfoil_comparison_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.target_airfoil_comparison_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.target_airfoil_comparison_table)
        return widget

    def _target_history_table_tab(self) -> QWidget:
        """Build target optimization history table tab."""

        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.target_history_table = QTableWidget(0, len(TARGET_HISTORY_COLUMNS))
        self.target_history_table.setHorizontalHeaderLabels([label for label, _attr in TARGET_HISTORY_COLUMNS])
        self.target_history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.target_history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.target_history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.target_history_table)
        return widget

    def _target_geometry_table_tab(self) -> QWidget:
        """Build target optimization best geometry table tab."""

        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.target_geometry_table = QTableWidget(0, len(TARGET_GEOMETRY_COLUMNS))
        self.target_geometry_table.setHorizontalHeaderLabels([label for label, _attr in TARGET_GEOMETRY_COLUMNS])
        self.target_geometry_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.target_geometry_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.target_geometry_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.target_geometry_table)
        return widget

    def _input(self) -> PropellerInput:
        """Read PropellerInput from controls."""

        inp = PropellerInput(
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
        self.app_state.prop_input = inp
        return inp

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

    def _design_polar(self) -> AirfoilPolar | None:
        """Return the active polar for design, or None for GenericPolar."""

        return self._selected_polar()

    def _design_input(self) -> DesignInput:
        """Read DesignInput from design controls."""

        target_type = str(self.design_target_type_combo.currentData())
        target_value = self.design_target_value_spin.value() if target_type != "none" else 0.0
        return DesignInput(
            rpm=self.design_rpm_spin.value(),
            v_inf=self.design_vinf_spin.value(),
            rho=self.rho_spin.value(),
            mu=self.mu_spin.value(),
            sound_speed=self.sound_speed_spin.value(),
            target_type=target_type,
            target_value=target_value,
            objective=str(self.design_alpha_objective_combo.currentData()),
            chord_mode=str(self.design_chord_mode_combo.currentData()),
            alpha_min_deg=self.design_alpha_min_spin.value(),
            alpha_max_deg=self.design_alpha_max_spin.value(),
            alpha_step_deg=self.design_alpha_step_spin.value(),
            stall_margin_deg=self.design_stall_margin_spin.value(),
            max_cl_fraction=self.design_max_cl_fraction_spin.value(),
            fixed_alpha_deg=self.design_fixed_alpha_spin.value(),
            beta_min_deg=self.design_beta_min_spin.value(),
            beta_max_deg=self.design_beta_max_spin.value(),
            max_tip_mach=self.design_max_tip_mach_spin.value(),
            allow_beta_offset=self.design_allow_beta_offset_check.isChecked(),
        )

    def _sync_design_method_target(self) -> None:
        """Keep the target selector aligned with the selected design method."""

        target_type = str(self.design_method_combo.currentData())
        index = self.design_target_type_combo.findData(target_type)
        if index >= 0:
            self.design_target_type_combo.setCurrentIndex(index)
        self._update_design_control_state()

    def _update_design_control_state(self, *_args: object) -> None:
        """Enable only controls relevant to the current design choices."""

        target_type = str(self.design_target_type_combo.currentData())
        has_target = target_type in ("thrust", "power")
        self.design_target_type_combo.setEnabled(False)
        self.design_target_value_spin.setEnabled(has_target)
        self.design_allow_beta_offset_check.setEnabled(has_target)
        if not has_target:
            self.design_allow_beta_offset_check.setChecked(False)
        elif not self.design_allow_beta_offset_check.isChecked():
            self.design_allow_beta_offset_check.setChecked(True)

        objective = str(self.design_alpha_objective_combo.currentData())
        is_fixed_alpha = objective == "fixed_alpha"
        is_max_ld = objective == "max_ld"
        uses_scan = not is_fixed_alpha
        self.design_fixed_alpha_spin.setEnabled(is_fixed_alpha)
        self.design_alpha_min_spin.setEnabled(uses_scan)
        self.design_alpha_max_spin.setEnabled(uses_scan)
        self.design_alpha_step_spin.setEnabled(uses_scan)
        self.design_stall_margin_spin.setEnabled(is_max_ld)
        self.design_max_cl_fraction_spin.setEnabled(is_max_ld)

    def _sync_target_from_base(self) -> None:
        """Copy Base Calculate inputs into the target optimization workspace."""

        pairs: list[tuple[QDoubleSpinBox | QSpinBox, float]] = [
            (self.target_blades_spin, self.blades_spin.value()),
            (self.target_diameter_spin, self.diameter_spin.value()),
            (self.target_diameter_min_spin, self.diameter_spin.value()),
            (self.target_diameter_max_spin, self.diameter_spin.value()),
            (self.target_hub_spin, self.hub_spin.value()),
            (self.target_rpm_spin, self.rpm_spin.value()),
            (self.target_vinf_spin, self.vinf_spin.value()),
            (self.target_rho_spin, self.rho_spin.value()),
            (self.target_mu_spin, self.mu_spin.value()),
            (self.target_sound_speed_spin, self.sound_speed_spin.value()),
            (self.target_elements_spin, self.elements_spin.value()),
        ]
        for spin, value in pairs:
            _set_spin_value_silently(spin, value)
        chord_min = max(min(self.root_chord_spin.value(), self.tip_chord_spin.value()) * 0.5, 0.001)
        chord_max = min(max(self.root_chord_spin.value(), self.tip_chord_spin.value()) * 1.5, 1.0)
        if chord_min < chord_max:
            _set_spin_value_silently(self.target_chord_min_spin, chord_min)
            _set_spin_value_silently(self.target_chord_max_spin, chord_max)
        if self.current_result is not None:
            _set_spin_value_silently(self.target_thrust_spin, max(self.current_result.thrust_N, 0.0))
            _set_spin_value_silently(self.target_torque_spin, max(self.current_result.torque_Nm, 0.0))
            _set_spin_value_silently(self.target_torque_limit_spin, max(self.current_result.torque_Nm * 1.1, 0.0))
            _set_spin_value_silently(self.target_power_limit_spin, max(self.current_result.power_W * 1.25, 0.0))
        self.target_diameter_mode_combo.setCurrentIndex(0)
        self._update_target_diameter_mode_controls()
        self._refresh_target_polar_label()

    def _refresh_target_polar_label(self) -> None:
        """Refresh the target optimization polar status label."""

        if self.target_airfoil_polar is not None:
            text = f"Polar: target XFOIL multi-airfoil ({len(self.target_airfoil_polar.airfoils)} airfoil(s))"
        else:
            mode = str(self.polar_mode_combo.currentData())
            if mode == "generic":
                text = "Polar: Generic airfoil"
            elif self.current_polar is None:
                text = "Polar: missing; optimizer will use Generic airfoil"
            elif isinstance(self.current_polar, MultiAirfoilPolar):
                text = f"Polar: current multi-airfoil ({len(self.current_polar.airfoils)} airfoil(s))"
            elif isinstance(self.current_polar, MultiRePolar):
                text = "Polar: current Multi-Re table"
            elif isinstance(self.current_polar, TablePolar):
                text = f"Polar: current table with {len(self.current_polar.points)} point(s)"
            else:
                text = "Polar: current imported polar"
        self.target_polar_label.setText(text)
        if self.target_airfoil_polar is None:
            return
        self.target_airfoil_status_label.setText(
            f"Target airfoil polar: {len(self.target_airfoil_polar.airfoils)} airfoil(s) ready"
        )

    def _update_target_mode_controls(self, *_args: object) -> None:
        """Enable only target fields relevant to the selected objective."""

        mode = str(self.target_mode_combo.currentData())
        uses_thrust = mode in ("target_thrust_min_power", "target_thrust_torque_limited", "match_thrust")
        uses_torque = mode in ("target_torque_max_thrust", "match_torque")
        uses_torque_limit = mode in ("target_thrust_torque_limited", "target_torque_max_thrust")
        self.target_thrust_spin.setEnabled(uses_thrust)
        self.target_torque_spin.setEnabled(uses_torque)
        self.target_torque_limit_spin.setEnabled(uses_torque_limit)

    def _target_diameter_mode(self) -> str:
        """Return the selected target diameter handling mode."""

        return str(self.target_diameter_mode_combo.currentData())

    def _update_target_diameter_mode_controls(self, *_args: object) -> None:
        """Show only the diameter inputs needed by the selected mode."""

        range_mode = self._target_diameter_mode() == "range"
        fixed_widgets = (self.target_diameter_label, self.target_diameter_spin)
        range_widgets = (
            self.target_diameter_min_label,
            self.target_diameter_min_spin,
            self.target_diameter_max_label,
            self.target_diameter_max_spin,
        )
        for widget in fixed_widgets:
            widget.setVisible(not range_mode)
        for widget in range_widgets:
            widget.setVisible(range_mode)
        self.target_diameter_spin.setEnabled(not range_mode)
        self.target_diameter_min_spin.setEnabled(range_mode)
        self.target_diameter_max_spin.setEnabled(range_mode)

    def _target_airfoil_source(self) -> str:
        """Return the selected target airfoil source type."""

        return str(self.target_airfoil_source_combo.currentData())

    def _target_airfoil_mode(self) -> str:
        """Return how selected target airfoils are used."""

        return str(self.target_airfoil_mode_combo.currentData())

    def _update_target_airfoil_mode_controls(self, *_args: object) -> None:
        """Update target airfoil entry hints for the selected mode."""

        if self._target_airfoil_mode() == "compare_uniform":
            mixed_index = self.target_airfoil_source_combo.findData("mixed")
            if mixed_index >= 0 and self._target_airfoil_source() != "mixed":
                self.target_airfoil_source_combo.setCurrentIndex(mixed_index)
            self.target_airfoil_codes_edit.setPlaceholderText("4412, 4612, 0012")
            self.target_dat_paths_edit.setPlaceholderText("One DAT candidate file path per line")
        else:
            if self._target_airfoil_source() == "mixed":
                self.target_airfoil_source_combo.setCurrentIndex(0)
            self.target_airfoil_codes_edit.setPlaceholderText("4412, 2412, 0012")
            self.target_dat_paths_edit.setPlaceholderText("One DAT file path per line, root-to-tip")
        self._update_target_airfoil_source_controls()

    def _update_target_airfoil_source_controls(self, *_args: object) -> None:
        """Enable target airfoil controls for the selected source."""

        compare_mode = self._target_airfoil_mode() == "compare_uniform"
        if not compare_mode and self._target_airfoil_source() == "mixed":
            self.target_airfoil_source_combo.setCurrentIndex(0)
            return
        use_dat = self._target_airfoil_source() == "dat"
        use_mixed = compare_mode
        self.target_airfoil_source_combo.setEnabled(not compare_mode)
        self.target_airfoil_codes_edit.setEnabled(use_mixed or not use_dat)
        self.target_dat_paths_edit.setEnabled(use_mixed or use_dat)
        self.target_dat_browse_button.setEnabled(use_mixed or use_dat)
        self._clear_target_airfoil_polar()

    def browse_target_dat_files(self) -> None:
        """Browse for target DAT airfoil files."""

        paths, _filter = QFileDialog.getOpenFileNames(self, "Select target DAT files", "", "DAT files (*.dat);;All files (*)")
        if paths:
            self.target_dat_paths_edit.setPlainText("\n".join(paths))

    def _target_airfoil_ids(self) -> list[str]:
        """Return selected target airfoils."""

        if self._target_airfoil_mode() == "compare_uniform":
            return _unique_strings(self._target_naca_airfoil_ids(default_to_4412=False) + self._target_dat_airfoil_ids())
        if self._target_airfoil_source() == "dat":
            return self._target_dat_airfoil_ids()
        return self._target_naca_airfoil_ids(default_to_4412=True)

    def _target_airfoil_items(self) -> list[TargetAirfoilXfoilItem]:
        """Return target XFOIL preprocessing items with explicit source type."""

        if self._target_airfoil_mode() == "compare_uniform":
            items = [TargetAirfoilXfoilItem("naca", airfoil_id) for airfoil_id in self._target_naca_airfoil_ids(default_to_4412=False)]
            items.extend(TargetAirfoilXfoilItem("dat", path) for path in self._target_dat_paths())
            return _unique_xfoil_items(items)
        if self._target_airfoil_source() == "dat":
            return [TargetAirfoilXfoilItem("dat", path) for path in self._target_dat_paths()]
        return [TargetAirfoilXfoilItem("naca", airfoil_id) for airfoil_id in self._target_naca_airfoil_ids(default_to_4412=True)]

    def _target_naca_airfoil_ids(self, default_to_4412: bool) -> list[str]:
        """Return NACA target airfoil ids from the NACA input."""

        text = self.target_airfoil_codes_edit.text()
        raw_items = [item.strip() for item in text.replace(";", ",").split(",")]
        airfoils = [normalize_airfoil_id(item) for item in raw_items if normalize_airfoil_id(item)]
        if not airfoils and default_to_4412:
            return ["naca4412"]
        return _unique_strings(airfoils)

    def _target_dat_airfoil_ids(self) -> list[str]:
        """Return DAT target airfoil ids from DAT filenames."""

        airfoils = [normalize_airfoil_id(Path(path).stem) for path in self._target_dat_paths() if normalize_airfoil_id(Path(path).stem)]
        return _unique_strings(airfoils)

    def _target_dat_paths(self) -> list[str]:
        """Return selected DAT paths."""

        paths: list[str] = []
        for line in self.target_dat_paths_edit.toPlainText().splitlines():
            text = line.strip().strip('"')
            if text:
                paths.append(text)
        return paths

    def _clear_target_airfoil_polar(self, *_args: object) -> None:
        """Clear cached target airfoil polar after airfoil list edits."""

        self.target_airfoil_polar = None
        self.target_airfoil_status_label.setText("Target airfoil polar: not built")

    def estimate_target_optimization_re_range(self) -> None:
        """Estimate target optimization Reynolds bounds from search ranges."""

        try:
            estimate = estimate_optimization_reynolds_range(self._target_optimization_input())
            re_min = estimate["re_min"]
            re_max = estimate["re_max"]
            _set_spin_value_silently(self.target_re_min_spin, re_min)
            _set_spin_value_silently(self.target_re_max_spin, re_max)
            values = representative_reynolds_values(re_min, re_max, self.target_re_count_spin.value())
            self._append_target_log(
                "Estimated target optimization Re range: "
                f"{re_min:.6g} to {re_max:.6g}; values: "
                + ", ".join(f"{value:.6g}" for value in values)
            )
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Target Re estimate failed", str(exc))

    def build_target_xfoil_polars(self) -> None:
        """Build target multi-airfoil XFOIL polar tables."""

        if self.target_xfoil_thread is not None:
            QMessageBox.information(self, "Target XFOIL", "Target XFOIL preprocessing is already running.")
            return
        try:
            estimate = estimate_optimization_reynolds_range(self._target_optimization_input())
            re_min = estimate["re_min"]
            re_max = estimate["re_max"]
            _set_spin_value_silently(self.target_re_min_spin, re_min)
            _set_spin_value_silently(self.target_re_max_spin, re_max)
            reynolds_values = representative_reynolds_values(re_min, re_max, self.target_re_count_spin.value())
            airfoil_items = self._target_airfoil_items()
            airfoil_ids = self._target_airfoil_ids()
            if not airfoil_items:
                raise ValueError("Please select at least one target airfoil.")
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Target XFOIL setup failed", str(exc))
            return
        self.target_airfoil_polar = None
        self.target_airfoil_status_label.setText("Target airfoil polar: building")
        self._append_target_log(
            "Starting target XFOIL preprocessing for "
            + ", ".join(airfoil_ids)
            + " at Re values "
            + ", ".join(f"{value:.6g}" for value in reynolds_values)
        )
        self.target_build_xfoil_button.setEnabled(False)
        self.target_xfoil_thread = QThread(self)
        self.target_xfoil_worker = TargetAirfoilXfoilWorker(
            self.xfoil_path_edit.text() or "xfoil",
            airfoil_items,
            reynolds_values,
            self.xfoil_mach_spin.value(),
            self.alpha_start_spin.value(),
            self.alpha_end_spin.value(),
            self.alpha_step_spin.value(),
            self.iter_spin.value(),
            self.panels_spin.value(),
            self.timeout_spin.value(),
            source_type=self._target_airfoil_source(),
        )
        self.target_xfoil_worker.moveToThread(self.target_xfoil_thread)
        self.target_xfoil_thread.started.connect(self.target_xfoil_worker.run)
        self.target_xfoil_worker.log.connect(self._append_target_log)
        self.target_xfoil_worker.finished.connect(self._target_xfoil_finished)
        self.target_xfoil_worker.failed.connect(self._target_xfoil_failed)
        self.target_xfoil_worker.finished.connect(self.target_xfoil_thread.quit)
        self.target_xfoil_worker.failed.connect(self.target_xfoil_thread.quit)
        self.target_xfoil_thread.finished.connect(self._target_xfoil_cleanup)
        self.target_xfoil_thread.start()

    def _target_xfoil_finished(self, result: TargetAirfoilXfoilResult) -> None:
        """Handle completed target XFOIL preprocessing."""

        self.target_airfoil_polar = result.polar
        self.target_airfoil_status_label.setText(
            "Target airfoil polar: "
            f"{len(result.airfoil_ids)} airfoil(s), {len(result.reynolds_values)} Re value(s)"
        )
        self._refresh_target_polar_label()
        if result.warnings:
            self._append_target_log("Target XFOIL warnings:")
            self._append_target_log("\n".join(result.warnings))

    def _target_xfoil_failed(self, message: str) -> None:
        """Handle failed target XFOIL preprocessing."""

        self.target_airfoil_status_label.setText("Target airfoil polar: failed")
        self._append_target_log(f"Target XFOIL failed: {message}")
        QMessageBox.warning(self, "Target XFOIL failed", message)

    def _target_xfoil_cleanup(self) -> None:
        """Release target XFOIL worker thread references."""

        self.target_build_xfoil_button.setEnabled(True)
        if self.target_xfoil_worker is not None:
            self.target_xfoil_worker.deleteLater()
        if self.target_xfoil_thread is not None:
            self.target_xfoil_thread.deleteLater()
        self.target_xfoil_worker = None
        self.target_xfoil_thread = None

    def _target_optimization_input(self) -> TargetOptimizationInput:
        """Read TargetOptimizationInput from controls."""

        if self._target_diameter_mode() == "range":
            diameter_min_m = self.target_diameter_min_spin.value()
            diameter_max_m = self.target_diameter_max_spin.value()
            if diameter_min_m > diameter_max_m:
                raise ValueError("Diameter min must be smaller than or equal to diameter max.")
            if diameter_min_m <= self.target_hub_spin.value():
                raise ValueError("Diameter min must be greater than hub diameter.")
            diameter_m = 0.5 * (diameter_min_m + diameter_max_m)
        else:
            diameter_m = self.target_diameter_spin.value()
            if diameter_m <= self.target_hub_spin.value():
                raise ValueError("Diameter must be greater than hub diameter.")
            diameter_min_m = diameter_m
            diameter_max_m = diameter_m
        if self.target_chord_min_spin.value() >= self.target_chord_max_spin.value():
            raise ValueError("Chord min must be smaller than chord max.")
        if self.target_beta_min_spin.value() >= self.target_beta_max_spin.value():
            raise ValueError("Beta min must be smaller than beta max.")
        constraint_weight = self.target_constraint_weight_spin.value()
        seed_value = self.target_seed_spin.value()
        return TargetOptimizationInput(
            target_mode=str(self.target_mode_combo.currentData()),
            target_thrust_N=self.target_thrust_spin.value(),
            target_torque_Nm=self.target_torque_spin.value(),
            torque_limit_Nm=self.target_torque_limit_spin.value(),
            power_limit_W=self.target_power_limit_spin.value(),
            blades=self.target_blades_spin.value(),
            diameter_m=diameter_m,
            diameter_min_m=diameter_min_m,
            diameter_max_m=diameter_max_m,
            hub_diameter_m=self.target_hub_spin.value(),
            rpm=self.target_rpm_spin.value(),
            v_inf=self.target_vinf_spin.value(),
            rho=self.target_rho_spin.value(),
            mu=self.target_mu_spin.value(),
            sound_speed=self.target_sound_speed_spin.value(),
            elements=self.target_elements_spin.value(),
            control_points=self.target_control_points_spin.value(),
            chord_min_ratio=self.target_chord_min_spin.value(),
            chord_max_ratio=self.target_chord_max_spin.value(),
            beta_min_deg=self.target_beta_min_spin.value(),
            beta_max_deg=self.target_beta_max_spin.value(),
            airfoil_ids=tuple(self._target_airfoil_ids()),
            max_tip_mach=self.target_max_tip_mach_spin.value(),
            max_alpha_deg=self.target_max_alpha_spin.value(),
            max_stall_fraction=self.target_max_stall_fraction_spin.value(),
            max_low_re_fraction=self.target_max_low_re_fraction_spin.value(),
            optimizer_method=str(self.target_method_combo.currentData()),
            population_size=self.target_population_spin.value(),
            generations=self.target_generations_spin.value(),
            mutation_rate=self.target_mutation_spin.value(),
            crossover_rate=self.target_crossover_spin.value(),
            elitism_count=self.target_elitism_spin.value(),
            tournament_size=self.target_tournament_spin.value(),
            random_seed=None if seed_value == 0 else seed_value,
            smoothness_weight=self.target_smoothness_weight_spin.value(),
            power_weight=self.target_power_weight_spin.value(),
            torque_weight=self.target_torque_weight_spin.value(),
            mach_weight=constraint_weight,
            stall_weight=constraint_weight,
            low_re_weight=0.1 * constraint_weight,
            geometry_weight=0.1 * constraint_weight,
        )

    def _target_optimization_polar(self) -> AirfoilPolar | None:
        """Return the polar for target optimization, falling back to GenericPolar."""

        if self.target_airfoil_polar is not None:
            self._append_target_log("Using target XFOIL multi-airfoil polar.")
            return self.target_airfoil_polar
        if len(self._target_airfoil_ids()) > 1 and not isinstance(self.current_polar, MultiAirfoilPolar):
            if self._target_airfoil_mode() == "compare_uniform":
                raise ValueError("Airfoil comparison requires Build target XFOIL polars before optimization.")
            raise ValueError("Hybrid multi-airfoil optimization requires Build target XFOIL polars before optimization.")
        mode = str(self.polar_mode_combo.currentData())
        if mode == "generic":
            return None
        if self.current_polar is None:
            self._append_target_log("No imported or XFOIL polar is available; using Generic airfoil.")
            return None
        return self.current_polar

    def start_target_optimization(self) -> None:
        """Start target optimization in a worker thread."""

        if self.optimization_thread is not None:
            QMessageBox.information(self, "Target optimization", "Target optimization is already running.")
            return
        try:
            opt_input = self._target_optimization_input()
            self.target_warning_text.clear()
            polar = self._target_optimization_polar()
            compare_airfoils = self._target_airfoil_ids()
            compare_mode = self._target_airfoil_mode() == "compare_uniform"
            if compare_mode:
                if len(compare_airfoils) < 2:
                    raise ValueError("Airfoil comparison requires at least two target airfoils.")
                if not isinstance(polar, MultiAirfoilPolar):
                    raise ValueError("Airfoil comparison requires target XFOIL multi-airfoil polar data.")
                missing = [airfoil_id for airfoil_id in compare_airfoils if airfoil_id not in polar.airfoils]
                if missing:
                    raise ValueError("Missing polar data for airfoil(s): " + ", ".join(missing))
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Target optimization setup failed", str(exc))
            return
        if compare_mode:
            self._append_target_log("Starting uniform-airfoil comparison: " + ", ".join(compare_airfoils))
        else:
            self._append_target_log("Starting target optimization.")
        self._append_target_log("Model-based optimizer only; not CFD, structural, noise, or guaranteed global optimum.")
        self.target_airfoil_comparison_result = None
        self._target_plot_warning_shown = False
        self._target_detail_refresh_generation = -1
        self.target_progress_history = []
        self._fill_target_history_table([])
        self._fill_target_geometry_table([])
        self._fill_target_airfoil_comparison_table([])
        self.start_target_button.setText("Start optimization")
        self.stop_target_button.setText("Stop")
        self.start_target_button.setEnabled(False)
        self.stop_target_button.setEnabled(True)
        self.optimization_thread = QThread(self)
        base_geometry = clone_geometry(self.current_geometry) if self.current_geometry is not None else None
        if compare_mode:
            self.optimization_worker = AirfoilComparisonWorker(opt_input, polar, base_geometry, compare_airfoils)
        else:
            self.optimization_worker = OptimizationWorker(opt_input, polar, base_geometry)
        self.optimization_worker.moveToThread(self.optimization_thread)
        self.optimization_thread.started.connect(self.optimization_worker.run)
        self.optimization_worker.log.connect(self._append_target_log)
        self.optimization_worker.progress.connect(self._target_optimization_progress)
        if compare_mode:
            self.optimization_worker.finished.connect(self._target_airfoil_comparison_finished)
        else:
            self.optimization_worker.finished.connect(self._target_optimization_finished)
        self.optimization_worker.failed.connect(self._target_optimization_failed)
        self.optimization_worker.finished.connect(self.optimization_thread.quit)
        self.optimization_worker.failed.connect(self.optimization_thread.quit)
        self.optimization_thread.finished.connect(self._target_optimization_cleanup)
        self.optimization_thread.start()

    def stop_target_optimization(self) -> None:
        """Request target optimization stop."""

        if self.optimization_worker is None:
            return
        self.optimization_worker.request_stop()
        self._append_target_log("Stop requested. Waiting for the current station/candidate to stop safely.")
        self.stop_target_button.setText("Stopping...")
        self.stop_target_button.setEnabled(False)

    def _target_optimization_progress(self, generation: int, total: int, best: object) -> None:
        """Update target optimization progress summary."""

        try:
            self.target_summary_labels["progress"].setText(f"{generation}/{total}")
            if isinstance(best, CandidateEvaluation):
                self.target_summary_labels["best_fitness"].setText(_fmt(best.fitness))
                self.target_summary_labels["target_error"].setText(_fmt(best.target_error_fraction))
                if best.analysis is not None:
                    self.target_summary_labels["T"].setText(_fmt(best.analysis.thrust_N))
                    self.target_summary_labels["Q"].setText(_fmt(best.analysis.torque_Nm))
                    self.target_summary_labels["P"].setText(_fmt(best.analysis.power_W))
                    row = OptimizationHistoryRow(
                        generation=max(generation - 1, 0),
                        evaluations=generation * self.target_population_spin.value(),
                        best_diameter_m=float(best.diagnostics.get("diameter_m", self.target_diameter_spin.value())),
                        best_fitness=best.fitness,
                        best_thrust_N=best.analysis.thrust_N,
                        best_torque_Nm=best.analysis.torque_Nm,
                        best_power_W=best.analysis.power_W,
                        best_eta=best.analysis.eta,
                        best_ct=best.analysis.ct,
                        best_cq=best.analysis.cq,
                        best_cp=best.analysis.cp,
                        target_error_fraction=best.target_error_fraction,
                        stall_fraction=float(best.diagnostics.get("stall_fraction", 0.0)),
                        low_re_fraction=float(best.diagnostics.get("low_re_fraction", 0.0)),
                        max_mach=float(best.diagnostics.get("max_mach", 0.0)),
                    )
                    self.target_progress_history.append(row)
                    if self._should_refresh_target_details(generation, total):
                        self._fill_target_history_table(self.target_progress_history)
                        self._fill_target_geometry_table(best.geometry)
                        self._safe_update_target_plots(self.target_progress_history, best.geometry, best.analysis)
        except Exception as exc:  # noqa: BLE001 - GUI updates must not terminate the app.
            try:
                self._append_target_log(f"Target progress update skipped: {exc}")
            except Exception:
                pass

    def _should_refresh_target_details(self, generation: int, total: int) -> bool:
        """Throttle expensive target tables and plots during optimization."""

        if generation <= 1 or generation >= total:
            self._target_detail_refresh_generation = generation
            return True
        if generation - self._target_detail_refresh_generation >= 5:
            self._target_detail_refresh_generation = generation
            return True
        return False

    def _target_optimization_finished(self, result: TargetOptimizationResult) -> None:
        """Handle completed target optimization."""

        try:
            self.target_airfoil_comparison_result = None
            self.app_state.last_target_optimization_result = result
            self._show_target_optimization_result(result)
            self._fill_target_airfoil_comparison_table([])
            self.apply_target_button.setEnabled(True)
            self.export_target_geometry_button.setEnabled(True)
            self.export_target_history_button.setEnabled(True)
            self.export_target_summary_button.setEnabled(True)
            self._append_target_log("Target optimization result is ready.")
        except Exception as exc:  # noqa: BLE001 - GUI updates must not terminate the app.
            self.app_state.last_target_optimization_result = result
            self._append_target_log(f"Target result display skipped: {exc}")

    def _target_airfoil_comparison_finished(self, result: TargetAirfoilComparisonResult) -> None:
        """Handle completed uniform-airfoil comparison optimization."""

        try:
            self.target_airfoil_comparison_result = result
            self._fill_target_airfoil_comparison_table(result.entries)
            best_entry = result.entries[0]
            self.app_state.last_target_optimization_result = best_entry.result
            self._show_target_optimization_result(best_entry.result)
            self._fill_target_airfoil_comparison_table(result.entries)
            self.apply_target_button.setEnabled(True)
            self.export_target_geometry_button.setEnabled(True)
            self.export_target_history_button.setEnabled(True)
            self.export_target_summary_button.setEnabled(True)
            self._append_target_log(
                f"Airfoil comparison result is ready. Best uniform airfoil: {best_entry.airfoil_id}."
            )
            if result.warnings:
                self._append_target_log("Airfoil comparison warnings:")
                self._append_target_log("\n".join(result.warnings))
        except Exception as exc:  # noqa: BLE001 - GUI updates must not terminate the app.
            if result.entries:
                self.app_state.last_target_optimization_result = result.entries[0].result
            self._append_target_log(f"Airfoil comparison display skipped: {exc}")

    def _target_optimization_failed(self, message: str) -> None:
        """Handle failed target optimization."""

        self._append_target_log(f"Target optimization failed: {message}")
        QMessageBox.warning(self, "Target optimization failed", message)

    def _target_optimization_cleanup(self) -> None:
        """Release target optimization worker references."""

        self.start_target_button.setEnabled(True)
        self.start_target_button.setText("Start optimization")
        self.stop_target_button.setText("Stop")
        self.stop_target_button.setEnabled(False)
        if self.optimization_worker is not None:
            self.optimization_worker.deleteLater()
        if self.optimization_thread is not None:
            self.optimization_thread.deleteLater()
        self.optimization_worker = None
        self.optimization_thread = None

    def apply_target_optimization_to_base(self) -> None:
        """Apply the optimized geometry and operating point to Base Calculate."""

        result = self.app_state.last_target_optimization_result
        if result is None:
            QMessageBox.information(self, "No target optimization", "Please run target optimization first.")
            return
        opt_input = result.input
        self.current_geometry = clone_geometry(result.best_geometry)
        _set_spin_value_silently(self.blades_spin, opt_input.blades)
        _set_spin_value_silently(self.diameter_spin, result.best_diameter_m)
        _set_spin_value_silently(self.hub_spin, opt_input.hub_diameter_m)
        _set_spin_value_silently(self.rpm_spin, opt_input.rpm)
        _set_spin_value_silently(self.vinf_spin, opt_input.v_inf)
        _set_spin_value_silently(self.rho_spin, opt_input.rho)
        _set_spin_value_silently(self.mu_spin, opt_input.mu)
        _set_spin_value_silently(self.sound_speed_spin, opt_input.sound_speed)
        _set_spin_value_silently(self.elements_spin, len(result.best_geometry))
        if self.current_polar is None:
            self.polar_mode_combo.setCurrentIndex(0)
        self._auto_estimate_re_range()
        self.workspace_combo.setCurrentIndex(0)
        self.calculate()

    def export_target_geometry(self) -> None:
        """Export the best target optimization geometry."""

        result = self.app_state.last_target_optimization_result
        if result is None:
            QMessageBox.information(self, "No target optimization", "Please run target optimization first.")
            return
        path, _filter = QFileDialog.getSaveFileName(self, "Export optimized geometry CSV", "optimized_geometry.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            save_geometry_csv(result.best_geometry, path)
            QMessageBox.information(self, "Geometry exported", "Optimized geometry CSV was written.")
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Optimized geometry export failed", str(exc))

    def export_target_history(self) -> None:
        """Export target optimization history."""

        result = self.app_state.last_target_optimization_result
        if result is None:
            QMessageBox.information(self, "No target optimization", "Please run target optimization first.")
            return
        path, _filter = QFileDialog.getSaveFileName(self, "Export optimization history CSV", "optimization_history.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            export_optimization_history_csv(result, path)
            QMessageBox.information(self, "History exported", "Optimization history CSV was written.")
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Optimization history export failed", str(exc))

    def export_target_summary(self) -> None:
        """Export target optimization summary."""

        result = self.app_state.last_target_optimization_result
        if result is None:
            QMessageBox.information(self, "No target optimization", "Please run target optimization first.")
            return
        path, _filter = QFileDialog.getSaveFileName(self, "Export optimization summary CSV", "optimization_summary.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            export_optimization_summary_csv(result, path)
            QMessageBox.information(self, "Summary exported", "Optimization summary CSV was written.")
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Optimization summary export failed", str(exc))

    def _show_target_optimization_result(self, result: TargetOptimizationResult) -> None:
        """Refresh target optimization summary, tables, and plots."""

        analysis = result.best_analysis
        values: dict[str, object] = {
            "progress": f"{len(result.history)}/{result.input.generations}",
            "T": analysis.thrust_N,
            "Q": analysis.torque_Nm,
            "P": analysis.power_W,
            "eta": analysis.eta,
            "CT": analysis.ct,
            "CQ": analysis.cq,
            "CP": analysis.cp,
            "best_diameter_m": result.best_diameter_m,
            "best_fitness": result.best_fitness,
            "target_error": result.target_error_fraction,
            "evaluations": result.evaluations,
            "target_mode": result.input.target_mode,
            "optimizer_method": result.input.optimizer_method,
        }
        for key, label in self.target_summary_labels.items():
            label.setText(_fmt(values.get(key, result.diagnostics.get(key, "-"))))
        warning_lines = ["Model-based optimizer only; not CFD, structural, noise, or guaranteed global optimum."]
        warning_lines.extend(result.warnings)
        if result.diagnostics:
            warning_lines.append("")
            warning_lines.extend(f"{key}: {value}" for key, value in result.diagnostics.items())
        self.target_warning_text.setPlainText("\n".join(warning_lines))
        self._fill_target_history_table(result.history)
        self._fill_target_geometry_table(result.best_geometry)
        self._safe_update_target_plots(result.history, result.best_geometry, result.best_analysis)

    def _safe_update_target_plots(
        self,
        history: list[OptimizationHistoryRow],
        geometry: list[GeometryStation],
        analysis: PropellerResult | None,
    ) -> None:
        """Update target plots without letting plotting errors close the UI."""

        try:
            self.target_history_plot.update_plot(history)
            self.target_geometry_plot.update_plot(geometry, analysis)
        except Exception as exc:  # noqa: BLE001 - plotting is secondary to optimization results.
            if not self._target_plot_warning_shown:
                self._target_plot_warning_shown = True
                self._append_target_log(f"Target plot update skipped: {exc}")

    def _fill_target_history_table(self, rows: list[Any]) -> None:
        """Populate the target optimization history table."""

        self.target_history_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col, (_label, attr) in enumerate(TARGET_HISTORY_COLUMNS):
                value = getattr(row, attr)
                self.target_history_table.setItem(row_index, col, QTableWidgetItem(_fmt(value) if isinstance(value, float) else str(value)))

    def _fill_target_airfoil_comparison_table(self, entries: list[Any]) -> None:
        """Populate the uniform-airfoil comparison table."""

        sorted_entries = sorted(entries, key=lambda entry: entry.result.best_fitness)
        self.target_airfoil_comparison_table.setRowCount(len(sorted_entries))
        for row_index, entry in enumerate(sorted_entries):
            result = entry.result
            analysis = result.best_analysis
            values: list[object] = [
                row_index + 1,
                entry.airfoil_id,
                result.best_diameter_m,
                result.best_fitness,
                result.target_error_fraction,
                analysis.thrust_N,
                analysis.torque_Nm,
                analysis.power_W,
                analysis.eta,
                analysis.ct,
                analysis.cq,
                analysis.cp,
                result.evaluations,
                len(result.warnings),
            ]
            for col, value in enumerate(values):
                self.target_airfoil_comparison_table.setItem(
                    row_index,
                    col,
                    QTableWidgetItem(_fmt(value) if isinstance(value, float) else str(value)),
                )

    def _fill_target_geometry_table(self, geometry: list[GeometryStation]) -> None:
        """Populate the target optimization best geometry table."""

        self.target_geometry_table.setRowCount(len(geometry))
        for row_index, station in enumerate(geometry):
            for col, (_label, attr) in enumerate(TARGET_GEOMETRY_COLUMNS):
                value = getattr(station, attr)
                self.target_geometry_table.setItem(row_index, col, QTableWidgetItem(_fmt(value) if isinstance(value, float) else str(value)))

    def _append_target_log(self, message: str) -> None:
        """Append one line to the target optimization log."""

        self.target_warning_text.append(message)

    def generate_design(self) -> None:
        """Generate a twist design from the current inputs."""

        try:
            result = design_twist_with_target(
                self._input(),
                self._design_input(),
                polar=self._design_polar(),
                base_geometry=self.current_geometry,
            )
            self.app_state.last_design_result = result
            self._show_design_result(result)
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Design failed", str(exc))

    def analyze_generated_design(self) -> None:
        """Re-analyze the current generated design geometry."""

        result = self.app_state.last_design_result
        if result is None:
            QMessageBox.information(self, "No design", "Please generate a design first.")
            return
        try:
            design_input = self._design_input()
            analysis_input = replace(
                self._input(),
                rpm=design_input.rpm,
                v_inf=design_input.v_inf,
                rho=design_input.rho,
                mu=design_input.mu,
                sound_speed=design_input.sound_speed,
                calculation_mode="auto",
            )
            analysis_result = calculate_propeller(analysis_input, polar=self._design_polar(), geometry=result.geometry)
            updated = replace(result, design_input=design_input, analysis_result=analysis_result)
            self.app_state.last_design_result = updated
            self._show_design_result(updated)
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Design analysis failed", str(exc))

    def apply_design_to_base(self) -> None:
        """Apply the generated design geometry to Base Calculate."""

        result = self.app_state.last_design_result
        if result is None:
            QMessageBox.information(self, "No design", "Please generate a design first.")
            return
        self.current_geometry = clone_geometry(result.geometry)
        self.elements_spin.setValue(len(result.geometry))
        self._auto_estimate_re_range()
        self.workspace_combo.setCurrentIndex(0)
        self.calculate()

    def export_design_geometry(self) -> None:
        """Export the generated design geometry."""

        result = self.app_state.last_design_result
        if result is None:
            QMessageBox.information(self, "No design", "Please generate a design first.")
            return
        path, _filter = QFileDialog.getSaveFileName(self, "Export designed geometry CSV", "designed_geometry.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            save_geometry_csv(result.geometry, path)
            QMessageBox.information(self, "Geometry exported", "Designed geometry CSV was written.")
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Design geometry export failed", str(exc))

    def export_design_station_csv(self) -> None:
        """Export the generated design station table."""

        result = self.app_state.last_design_result
        if result is None:
            QMessageBox.information(self, "No design", "Please generate a design first.")
            return
        path, _filter = QFileDialog.getSaveFileName(self, "Export design station CSV", "design_stations.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            export_design_station_csv(result, path)
            QMessageBox.information(self, "Design exported", "Design station CSV was written.")
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Design station export failed", str(exc))

    def _show_design_result(self, result: DesignResult) -> None:
        """Refresh design summary, table, and plots."""

        analysis = result.analysis_result
        target_error = result.diagnostics.get("target_error_fraction", 0.0)
        values: dict[str, object] = {
            "T": analysis.thrust_N if analysis is not None else 0.0,
            "Q": analysis.torque_Nm if analysis is not None else 0.0,
            "P": analysis.power_W if analysis is not None else 0.0,
            "eta": analysis.eta if analysis is not None else 0.0,
            "CT": analysis.ct if analysis is not None else 0.0,
            "CP": analysis.cp if analysis is not None else 0.0,
            "target_error": target_error,
            "objective": result.design_input.objective,
            "target_type": result.design_input.target_type,
        }
        for key, label in self.design_summary_labels.items():
            label.setText(_fmt(values.get(key, result.diagnostics.get(key, "-"))))
        self.design_warning_text.setPlainText("\n".join(result.warnings))
        self._fill_design_station_table(result.stations)
        self.design_plot.update_plot(result.stations)

    def _fill_design_station_table(self, stations: list[Any]) -> None:
        """Populate the design station table."""

        self.design_station_table.setRowCount(len(stations))
        for row, station in enumerate(stations):
            for col, (_label, attr) in enumerate(DESIGN_COLUMNS):
                value = getattr(station, attr)
                self.design_station_table.setItem(row, col, QTableWidgetItem(_fmt(value) if isinstance(value, float) else str(value)))

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

    def _update_airfoil_source_controls(self) -> None:
        """Enable controls relevant to the selected airfoil source."""

        use_dat_file = self.airfoil_source_combo.currentText() == "DAT file"
        self.naca_edit.setEnabled(not use_dat_file)
        self.dat_path_edit.setEnabled(use_dat_file)
        self.dat_browse_button.setEnabled(use_dat_file)

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
        self.xfoil_display_reynolds = _find_reynolds_for_points(result.points, result.reynolds_tables)
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
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Save polar CSV",
            self._default_xfoil_polar_filename(),
            "CSV files (*.csv)",
        )
        if not path:
            return
        try:
            XfoilRunner.export_xfoil_points_to_csv(self.xfoil_points, path)
            QMessageBox.information(self, "Polar saved", "Polar CSV was written.")
        except Exception as exc:  # noqa: BLE001
            _show_error(self, "Polar save failed", str(exc))

    def _default_xfoil_polar_filename(self) -> str:
        """Return an airfoil-and-Re based default polar file name."""

        airfoil_name = _safe_filename_token(self._xfoil_airfoil_name())
        reynolds = self.xfoil_display_reynolds
        if reynolds is None:
            reynolds = self.xfoil_re_spin.value()
        return f"{airfoil_name}_{_reynolds_filename_token(reynolds)}.csv"

    def _xfoil_airfoil_name(self) -> str:
        """Return the selected XFOIL airfoil name."""

        if self.airfoil_source_combo.currentText() == "DAT file":
            dat_path = self.dat_path_edit.text().strip()
            if dat_path:
                return Path(dat_path).stem
            return "dat_airfoil"
        return f"naca{self.naca_edit.text().strip() or '4412'}"

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
            self.app_state.xfoil_cached_polar = multi
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
        self.app_state.xfoil_cached_polar = self.current_polar
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


def _unique_strings(items: list[str]) -> list[str]:
    """Return strings without duplicates."""

    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _unique_xfoil_items(items: list[TargetAirfoilXfoilItem]) -> list[TargetAirfoilXfoilItem]:
    """Return XFOIL target items without duplicate final airfoil ids."""

    seen: set[str] = set()
    out: list[TargetAirfoilXfoilItem] = []
    for item in items:
        airfoil_id = normalize_airfoil_id(Path(item.value).stem) if item.source_type == "dat" else normalize_airfoil_id(item.value)
        if airfoil_id and airfoil_id not in seen:
            seen.add(airfoil_id)
            out.append(item)
    return out


def _show_error(parent: QWidget, title: str, message: str) -> None:
    """Show an error dialog."""

    QMessageBox.critical(parent, title, message)


def _short_log(name: str, text: str, max_chars: int = 3000) -> str:
    """Return a bounded log block for display."""

    if not text:
        return f"{name}:"
    trimmed = text[-max_chars:]
    return f"{name}:\n{trimmed}"


def _default_xfoil_path() -> str:
    """Return the bundled local XFOIL path when it exists."""

    local_xfoil = Path(__file__).resolve().parents[2] / "tools" / "xfoil" / "xfoil-6.99" / "xfoil.exe"
    if local_xfoil.exists():
        return str(local_xfoil)
    return "xfoil"


def _find_reynolds_for_points(
    points: list[XfoilPolarPoint],
    reynolds_tables: dict[float, list[XfoilPolarPoint]],
) -> float | None:
    """Return the Reynolds table associated with displayed XFOIL points."""

    if not points:
        return None
    for reynolds, table_points in reynolds_tables.items():
        if table_points is points or table_points == points:
            return float(reynolds)
    if len(reynolds_tables) == 1:
        return float(next(iter(reynolds_tables)))
    return None


def _reynolds_filename_token(reynolds: float) -> str:
    """Return a Reynolds number token for file names."""

    value = max(float(reynolds), 0.0)
    if value >= 1000.0:
        text = f"{value:.0f}"
    else:
        text = f"{value:.3g}"
    return "Re" + _safe_filename_token(text)


def _safe_filename_token(text: str) -> str:
    """Return an ASCII-safe token for generated file names."""

    cleaned: list[str] = []
    previous_underscore = False
    for char in text.strip().lower():
        if char.isascii() and (char.isalnum() or char in ("-", ".")):
            cleaned.append(char)
            previous_underscore = False
        elif not previous_underscore:
            cleaned.append("_")
            previous_underscore = True
    token = "".join(cleaned).strip("._-")
    return token or "airfoil"


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
DESIGN_SUMMARY_ROWS = [
    ("T", "predicted T, N"),
    ("Q", "predicted Q, N*m"),
    ("P", "predicted P, W"),
    ("eta", "predicted eta"),
    ("CT", "CT"),
    ("CP", "CP"),
    ("target_error", "target error"),
    ("objective", "objective"),
    ("target_type", "target_type"),
    ("max_beta_deg", "max_beta_deg"),
    ("min_beta_deg", "min_beta_deg"),
    ("max_alpha_design_deg", "max_alpha_design_deg"),
    ("min_alpha_design_deg", "min_alpha_design_deg"),
    ("max_mach", "max_mach"),
    ("max_reynolds", "max_reynolds"),
    ("min_reynolds", "min_reynolds"),
    ("stations_with_warnings", "stations_with_warnings"),
]
DESIGN_COLUMNS = [
    ("r/R", "r_over_R"),
    ("chord/R", "chord_over_R"),
    ("phi_deg", "phi_deg"),
    ("alpha_design_deg", "alpha_design_deg"),
    ("beta_deg", "beta_deg"),
    ("Re", "reynolds"),
    ("Mach", "mach"),
    ("Cl", "cl"),
    ("Cd", "cd"),
    ("Cl/Cd", "ld"),
    ("objective_value", "objective_value"),
    ("warning", "warning"),
]
TARGET_SUMMARY_ROWS = [
    ("progress", "progress"),
    ("T", "best T, N"),
    ("Q", "best Q, N*m"),
    ("P", "best P, W"),
    ("eta", "best eta"),
    ("CT", "CT"),
    ("CQ", "CQ"),
    ("CP", "CP"),
    ("best_diameter_m", "best diameter D, m"),
    ("best_fitness", "best fitness"),
    ("target_error", "target error"),
    ("evaluations", "evaluations"),
    ("target_mode", "target mode"),
    ("optimizer_method", "optimizer method"),
    ("max_alpha_deg", "max_alpha_deg"),
    ("stall_fraction", "stall_fraction"),
    ("low_re_fraction", "low_re_fraction"),
    ("max_mach", "max_mach"),
    ("geometry_smoothness", "geometry_smoothness"),
]
TARGET_HISTORY_COLUMNS = [
    ("generation", "generation"),
    ("evaluations", "evaluations"),
    ("D", "best_diameter_m"),
    ("fitness", "best_fitness"),
    ("T", "best_thrust_N"),
    ("Q", "best_torque_Nm"),
    ("P", "best_power_W"),
    ("eta", "best_eta"),
    ("CT", "best_ct"),
    ("CQ", "best_cq"),
    ("CP", "best_cp"),
    ("target_error", "target_error_fraction"),
    ("stall_fraction", "stall_fraction"),
    ("low_re_fraction", "low_re_fraction"),
    ("max_mach", "max_mach"),
]
TARGET_COMPARISON_COLUMNS = [
    "rank",
    "airfoil_id",
    "D",
    "fitness",
    "target_error",
    "T",
    "Q",
    "P",
    "eta",
    "CT",
    "CQ",
    "CP",
    "evaluations",
    "warnings_count",
]
TARGET_GEOMETRY_COLUMNS = [
    ("r/R", "r_over_R"),
    ("chord/R", "chord_over_R"),
    ("beta_deg", "beta_deg"),
    ("airfoil_id", "airfoil_id"),
]
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
