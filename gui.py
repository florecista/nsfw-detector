import sys
from collections import Counter
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, QSettings, QSize, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from nsfw_detector.model_adapters import (
    DEFAULT_MODEL_ID,
    DEFAULT_NSFW_THRESHOLD,
    available_model_types,
    create_model_adapter,
)


APP_DIR = Path(__file__).resolve().parent
APP_ICON_PATH = APP_DIR / "hacker-icon.png"
ORGANIZATION_NAME = "florecista"
APPLICATION_NAME = "NSFW Detector"

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class ConfigurationDialog(QDialog):
    def __init__(
        self,
        selected_model_id,
        model_thresholds,
        recursive_scan,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Configuration")
        self.setMinimumWidth(520)
        self.model_thresholds = dict(model_thresholds)
        self.current_model_id = selected_model_id

        layout = QFormLayout(self)

        self.model_combo = QComboBox(self)
        for adapter_type in available_model_types():
            self.model_combo.addItem(adapter_type.display_name, adapter_type.id)
        selected_index = self.model_combo.findData(selected_model_id)
        self.model_combo.setCurrentIndex(max(selected_index, 0))
        layout.addRow("Default model:", self.model_combo)

        self.model_description = QLabel(self)
        self.model_description.setWordWrap(True)
        self.model_description.setOpenExternalLinks(True)
        layout.addRow("Model information:", self.model_description)

        self.threshold_spin = QDoubleSpinBox(self)
        self.threshold_spin.setRange(0.0, 100.0)
        self.threshold_spin.setDecimals(1)
        self.threshold_spin.setSingleStep(1.0)
        self.threshold_spin.setSuffix("%")
        self.threshold_spin.setValue(
            self.model_thresholds.get(selected_model_id, DEFAULT_NSFW_THRESHOLD)
        )
        layout.addRow("NSFW threshold:", self.threshold_spin)

        self.recursive_checkbox = QCheckBox("Include subdirectories by default", self)
        self.recursive_checkbox.setChecked(recursive_scan)
        layout.addRow("Directory scans:", self.recursive_checkbox)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self.model_combo.currentIndexChanged.connect(self._model_changed)
        self._update_model_description()

    def _model_changed(self):
        self.model_thresholds[self.current_model_id] = self.threshold_spin.value()
        self.current_model_id = self.model_combo.currentData()
        self.threshold_spin.setValue(
            self.model_thresholds.get(self.current_model_id, DEFAULT_NSFW_THRESHOLD)
        )
        self._update_model_description()

    def _update_model_description(self):
        adapter_type = next(
            model_type
            for model_type in available_model_types()
            if model_type.id == self.model_combo.currentData()
        )
        self.model_description.setText(
            f"{adapter_type.description}<br><br>"
            f"Version: {adapter_type.version}<br>"
            f'<a href="{adapter_type.source_url}">Model source</a>'
        )

    def configuration(self):
        self.model_thresholds[self.model_combo.currentData()] = (
            self.threshold_spin.value()
        )
        return {
            "model_id": self.model_combo.currentData(),
            "model_thresholds": self.model_thresholds,
            "recursive_scan": self.recursive_checkbox.isChecked(),
        }


class ScanWorker(QObject):
    image_scanned = Signal(str, dict)
    image_skipped = Signal(str, str)
    progress = Signal(int, int, str)
    finished = Signal(bool)

    def __init__(self, model_adapter, image_paths):
        super().__init__()
        self.model_adapter = model_adapter
        self.image_paths = image_paths
        self._cancel_requested = False

    def request_cancel(self):
        self._cancel_requested = True

    @Slot()
    def run(self):
        total = len(self.image_paths)
        for index, image_path in enumerate(self.image_paths, start=1):
            if self._cancel_requested:
                self.finished.emit(True)
                return

            path_text = str(image_path)
            try:
                # Fully decode first so corrupt files are reported rather than
                # reaching TensorFlow as an empty batch.
                with Image.open(image_path) as image:
                    image.load()

                scores = self.model_adapter.classify(path_text)
                self.image_scanned.emit(path_text, scores)
            except Exception as error:
                self.image_skipped.emit(path_text, str(error))

            self.progress.emit(index, total, path_text)

        self.finished.emit(self._cancel_requested)


class MainWindow(QMainWindow):
    def __init__(self, *args, settings=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.settings = settings or QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        self.selected_model_id = self.settings.value(
            "models/default", DEFAULT_MODEL_ID, type=str
        )
        self.model_adapter = create_model_adapter(
            self.selected_model_id,
            nsfw_threshold=self._model_threshold(self.selected_model_id),
        )
        self.selected_model_id = self.model_adapter.id
        self.title = "NSFW Detector"
        self.selected_directory = ""
        self.scan_results = {}
        self.skipped_files = {}
        self.total_discovered = 0
        self.scan_recursive = False
        self.scan_thread = None
        self.scan_worker = None
        self.progress_dialog = None
        self._close_when_scan_finishes = False

        self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.setGeometry(100, 100, 1100, 700)
        self.set_title()

        self._build_results_view()
        self._build_actions()
        self._build_filter_panel()
        self._build_details_panel()
        self._build_status_bar()

        self.show()
        self._load_model_adapter(self.model_adapter)

    def _build_results_view(self):
        self.image_list = QListWidget(self)
        self.image_list.setViewMode(QListView.ViewMode.IconMode)
        self.image_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.image_list.setMovement(QListView.Movement.Static)
        self.image_list.setWrapping(True)
        self.image_list.setWordWrap(True)
        self.image_list.setIconSize(QSize(144, 144))
        self.image_list.setGridSize(QSize(190, 205))
        self.image_list.setSpacing(8)
        self.image_list.currentItemChanged.connect(self._show_item_details)
        self.setCentralWidget(self.image_list)

    def _build_actions(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        settings_menu = menu_bar.addMenu("&Settings")
        help_menu = menu_bar.addMenu("&Help")

        self.open_action = QAction("&Open directory...", self)
        self.open_action.triggered.connect(self.open_folder)
        self.open_action.setStatusTip("Choose a directory to scan")
        self.open_action.setShortcut("Ctrl+O")
        file_menu.addAction(self.open_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setStatusTip("Exit")
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        self.configuration_action = QAction("&Configuration...", self)
        self.configuration_action.setShortcut("Ctrl+,")
        self.configuration_action.setStatusTip(
            "Choose the default model and scan settings"
        )
        self.configuration_action.triggered.connect(self.open_configuration)
        settings_menu.addAction(self.configuration_action)

        about_action = QAction("&About", self)
        about_action.setShortcut("F1")
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        toolbar = QToolBar("Main toolbar", self)
        toolbar.setIconSize(QSize(16, 16))
        toolbar.addAction(self.open_action)
        toolbar.addSeparator()
        toolbar.addAction(exit_action)
        self.addToolBar(toolbar)

    def _build_filter_panel(self):
        self.filter_dock = QDockWidget("Filters", self)
        self.filter_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.filter_dock)

        filter_form = QWidget(self.filter_dock)
        layout = QFormLayout(filter_form)

        layout.addRow(QLabel("Common filters:", filter_form))

        self.checkboxAllResults = QCheckBox("All classified images", self)
        layout.addRow(self.checkboxAllResults)

        self.checkboxNsfw = QCheckBox(self)
        layout.addRow(self.checkboxNsfw)

        self.checkboxSfw = QCheckBox("SFW", self)
        layout.addRow(self.checkboxSfw)

        self.model_categories_heading = QLabel(filter_form)
        self.model_categories_heading.setWordWrap(True)
        layout.addRow(self.model_categories_heading)

        self.category_filter_widget = QWidget(filter_form)
        self.category_filter_layout = QVBoxLayout(self.category_filter_widget)
        self.category_filter_layout.setContentsMargins(0, 0, 0, 0)
        layout.addRow(self.category_filter_widget)

        layout.addRow(QPushButton("Apply filters", clicked=self.filter))
        layout.addRow(QPushButton("Clear results", clicked=self.clear_results))

        layout.addRow(QLabel("Scan options:", filter_form))
        self.checkboxRecursive = QCheckBox("Include subdirectories", self)
        self.checkboxRecursive.setChecked(
            self.settings.value("scan/recursive", False, type=bool)
        )
        self.checkboxRecursive.setToolTip("Applies the next time a directory is opened")
        layout.addRow(self.checkboxRecursive)

        formats = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        format_label = QLabel(f"Formats: {formats}", filter_form)
        format_label.setWordWrap(True)
        layout.addRow(format_label)

        self.filter_dock.setWidget(filter_form)
        self.filter_checkboxes = {}
        self._rebuild_model_category_filters()
        self._restore_filter_settings()

    def _build_details_panel(self):
        self.details_dock = QDockWidget("Scan details", self)
        self.details_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.details_dock)

        panel = QWidget(self.details_dock)
        layout = QVBoxLayout(panel)

        self.summary_label = QLabel("No directory has been scanned.", panel)
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.summary_label)

        layout.addWidget(QLabel("Selected image:", panel))
        self.selected_path_label = QLabel("None", panel)
        self.selected_path_label.setWordWrap(True)
        self.selected_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.selected_path_label)

        self.selected_scores_label = QLabel("", panel)
        self.selected_scores_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.selected_scores_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.selected_scores_label)

        layout.addWidget(QLabel("Skipped files:", panel))
        self.skipped_text = QPlainTextEdit(panel)
        self.skipped_text.setReadOnly(True)
        self.skipped_text.setPlaceholderText("None")
        layout.addWidget(self.skipped_text)

        self.details_dock.setWidget(panel)

    def _build_status_bar(self):
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Ready")
        self.display_count_label = QLabel("Displayed: 0", self)
        self.status_bar.addPermanentWidget(self.display_count_label)

    def _model_threshold(self, model_id):
        value = self.settings.value(
            f"models/{model_id}/nsfw_threshold", DEFAULT_NSFW_THRESHOLD
        )
        try:
            return float(value)
        except (TypeError, ValueError):
            return DEFAULT_NSFW_THRESHOLD

    def _all_model_thresholds(self):
        return {
            adapter_type.id: self._model_threshold(adapter_type.id)
            for adapter_type in available_model_types()
        }

    def _rebuild_model_category_filters(self):
        while self.category_filter_layout.count():
            item = self.category_filter_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        self.filter_checkboxes = {}
        self.model_categories_heading.setText(
            f"{self.model_adapter.display_name} categories:"
        )
        for category in self.model_adapter.categories:
            checkbox = QCheckBox(category.label, self.category_filter_widget)
            self.category_filter_layout.addWidget(checkbox)
            self.filter_checkboxes[category.id] = checkbox

        if not self.model_adapter.categories:
            no_categories = QLabel(
                "This model does not provide category-specific scores.",
                self.category_filter_widget,
            )
            no_categories.setWordWrap(True)
            self.category_filter_layout.addWidget(no_categories)

        self._update_nsfw_filter_label()

    def _update_nsfw_filter_label(self):
        self.checkboxNsfw.setText(
            f"NSFW (score ≥ {self.model_adapter.nsfw_threshold:.1f}%)"
        )

    def _filter_settings_prefix(self, model_id=None):
        return f"filters/{model_id or self.model_adapter.id}"

    def _restore_filter_settings(self):
        prefix = self._filter_settings_prefix()
        default_all_results = not bool(self.model_adapter.categories)
        self.checkboxAllResults.setChecked(
            self.settings.value(
                f"{prefix}/all_results", default_all_results, type=bool
            )
        )
        self.checkboxNsfw.setChecked(
            self.settings.value(f"{prefix}/nsfw", False, type=bool)
        )
        self.checkboxSfw.setChecked(
            self.settings.value(f"{prefix}/sfw", False, type=bool)
        )

        saved_categories = self.settings.value(f"{prefix}/categories")
        if saved_categories is None:
            selected_categories = set(self.filter_checkboxes)
        elif isinstance(saved_categories, str):
            selected_categories = {saved_categories}
        else:
            selected_categories = set(saved_categories)
        selected_categories.discard("__none__")

        for category_id, checkbox in self.filter_checkboxes.items():
            checkbox.setChecked(category_id in selected_categories)

    def _save_filter_settings(self):
        prefix = self._filter_settings_prefix()
        self.settings.setValue(
            f"{prefix}/all_results", self.checkboxAllResults.isChecked()
        )
        self.settings.setValue(f"{prefix}/nsfw", self.checkboxNsfw.isChecked())
        self.settings.setValue(f"{prefix}/sfw", self.checkboxSfw.isChecked())
        selected_categories = [
            category_id
            for category_id, checkbox in self.filter_checkboxes.items()
            if checkbox.isChecked()
        ]
        self.settings.setValue(
            f"{prefix}/categories", selected_categories or ["__none__"]
        )

    def open_configuration(self):
        if self._scan_is_running():
            QMessageBox.information(
                self,
                "Scan in progress",
                "Cancel or wait for the current scan before changing models.",
            )
            return

        dialog = ConfigurationDialog(
            selected_model_id=self.model_adapter.id,
            model_thresholds=self._all_model_thresholds(),
            recursive_scan=self.checkboxRecursive.isChecked(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        configuration = dialog.configuration()
        selected_model_id = configuration["model_id"]
        selected_threshold = configuration["model_thresholds"][selected_model_id]

        self._save_filter_settings()
        self.settings.setValue("scan/recursive", configuration["recursive_scan"])
        self.checkboxRecursive.setChecked(configuration["recursive_scan"])
        for model_id, threshold in configuration["model_thresholds"].items():
            self.settings.setValue(f"models/{model_id}/nsfw_threshold", threshold)

        if selected_model_id != self.model_adapter.id:
            candidate = create_model_adapter(
                selected_model_id, nsfw_threshold=selected_threshold
            )
            if not self._load_model_adapter(candidate):
                return
            self.model_adapter = candidate
            self.selected_model_id = candidate.id
            self.settings.setValue("models/default", candidate.id)
            self.scan_results.clear()
            self.skipped_files.clear()
            self.total_discovered = 0
            self.image_list.clear()
            self.skipped_text.clear()
            self.selected_path_label.setText("None")
            self.selected_scores_label.clear()
            self._rebuild_model_category_filters()
            self._restore_filter_settings()
        else:
            self.model_adapter.nsfw_threshold = selected_threshold
            self.scan_results = {
                path: self.model_adapter.apply_threshold(scores)
                for path, scores in self.scan_results.items()
            }
            self._update_nsfw_filter_label()

        self.settings.setValue("models/default", self.model_adapter.id)
        self.settings.sync()
        self.render_cached_results()
        self.status_bar.showMessage("Configuration saved", 5000)

    def _load_model_adapter(self, model_adapter):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.status_bar.showMessage(f"Loading {model_adapter.display_name}...")
        QApplication.processEvents()
        try:
            model_adapter.load()
        except Exception as error:
            if not self.model_adapter.loaded:
                self.open_action.setEnabled(False)
            QMessageBox.critical(
                self,
                "Model load failed",
                f"{model_adapter.display_name} could not be loaded:\n\n{error}",
            )
            self.status_bar.showMessage("Model load failed")
            return False
        finally:
            QApplication.restoreOverrideCursor()

        self.open_action.setEnabled(True)
        self.status_bar.showMessage(f"{model_adapter.display_name} ready", 5000)
        return True

    def set_title(self, filename=None):
        name = filename if filename else "No directory"
        self.setWindowTitle(f"{name} - {self.title}")

    def discover_images(self, selected_directory, recursive=None):
        directory = Path(selected_directory)
        if recursive is None:
            recursive = self.checkboxRecursive.isChecked()

        candidates = directory.rglob("*") if recursive else directory.iterdir()
        return sorted(
            (
                path.resolve()
                for path in candidates
                if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
            ),
            key=lambda path: str(path).casefold(),
        )

    def open_folder(self):
        if self._scan_is_running():
            QMessageBox.information(
                self,
                "Scan in progress",
                "Cancel or wait for the current scan before opening another directory.",
            )
            return

        selected_directory = QFileDialog.getExistingDirectory(
            self, "Choose a directory to scan", self.selected_directory
        )
        if not selected_directory:
            return

        self.selected_directory = str(Path(selected_directory).resolve())
        self.set_title(self.selected_directory)
        self.start_scan()

    def start_scan(self):
        if not self.model_adapter.loaded:
            QMessageBox.critical(self, "Model unavailable", "The model is not loaded.")
            return
        if not self.selected_directory:
            QMessageBox.information(
                self,
                "No directory selected",
                "Choose a directory before starting a scan.",
            )
            return

        try:
            self.scan_recursive = self.checkboxRecursive.isChecked()
            image_paths = self.discover_images(
                self.selected_directory, recursive=self.scan_recursive
            )
        except OSError as error:
            QMessageBox.critical(self, "Directory error", str(error))
            return

        self.scan_results.clear()
        self.skipped_files.clear()
        self.image_list.clear()
        self.skipped_text.clear()
        self.total_discovered = len(image_paths)
        self._update_summary()

        if not image_paths:
            self.status_bar.showMessage("No supported images found", 5000)
            QMessageBox.information(
                self,
                "No images found",
                "No supported images were found in the selected scan scope.",
            )
            return

        self.open_action.setEnabled(False)
        self.configuration_action.setEnabled(False)
        self.progress_dialog = QProgressDialog(
            "Preparing scan...", "Cancel", 0, len(image_paths), self
        )
        self.progress_dialog.setWindowTitle("Scanning images")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.setAutoReset(False)

        self.scan_thread = QThread(self)
        self.scan_worker = ScanWorker(self.model_adapter, image_paths)
        self.scan_worker.moveToThread(self.scan_thread)

        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_worker.image_scanned.connect(self._cache_scan_result)
        self.scan_worker.image_skipped.connect(self._cache_skipped_file)
        self.scan_worker.progress.connect(self._update_scan_progress)
        self.scan_worker.finished.connect(self._finish_scan)
        self.scan_worker.finished.connect(self.scan_thread.quit)
        self.scan_worker.finished.connect(self.scan_worker.deleteLater)
        self.scan_thread.finished.connect(self._release_scan_thread)
        self.scan_thread.finished.connect(self.scan_thread.deleteLater)
        # A direct Python callback updates the worker's cancellation flag even
        # while its thread is busy inside the scan loop.
        self.progress_dialog.canceled.connect(
            lambda: self.scan_worker and self.scan_worker.request_cancel()
        )

        recursive_text = " recursively" if self.checkboxRecursive.isChecked() else ""
        self.status_bar.showMessage(
            f"Scanning {len(image_paths)} image(s){recursive_text}..."
        )
        self.progress_dialog.show()
        self.scan_thread.start()

    @Slot(str, dict)
    def _cache_scan_result(self, image_path, scores):
        self.scan_results[image_path] = scores

    @Slot(str, str)
    def _cache_skipped_file(self, image_path, error):
        self.skipped_files[image_path] = error

    @Slot(int, int, str)
    def _update_scan_progress(self, current, total, image_path):
        progress_dialog = self.progress_dialog
        if progress_dialog is None:
            return
        progress_dialog.setLabelText(
            f"Scanning {current} of {total}:\n{Path(image_path).name}"
        )
        progress_dialog.setMaximum(total)
        progress_dialog.setValue(current)
        self.status_bar.showMessage(
            f"Scanning {current}/{total}: {Path(image_path).name}"
        )

    @Slot(bool)
    def _finish_scan(self, cancelled):
        if self.progress_dialog is not None:
            self.progress_dialog.close()
            self.progress_dialog.deleteLater()
            self.progress_dialog = None

        self.open_action.setEnabled(True)
        self.configuration_action.setEnabled(True)
        self._update_skipped_text()
        self.render_cached_results()

        status = "cancelled" if cancelled else "complete"
        self.status_bar.showMessage(
            f"Scan {status}: {len(self.scan_results)} classified, "
            f"{len(self.skipped_files)} skipped",
            8000,
        )

    @Slot()
    def _release_scan_thread(self):
        self.scan_worker = None
        self.scan_thread = None
        if self._close_when_scan_finishes:
            self._close_when_scan_finishes = False
            self.close()

    def _scan_is_running(self):
        return self.scan_thread is not None and self.scan_thread.isRunning()

    def filter(self):
        if not self.selected_directory:
            QMessageBox.information(
                self,
                "No directory selected",
                "Choose a directory before applying filters.",
            )
            return
        self._save_filter_settings()
        self.settings.sync()
        self.render_cached_results()

    def _matches_selected_filters(self, scores):
        if self.checkboxAllResults.isChecked():
            return True
        if self.checkboxNsfw.isChecked() and scores["is_nsfw"]:
            return True
        if self.checkboxSfw.isChecked() and not scores["is_nsfw"]:
            return True

        return any(
            checkbox.isChecked()
            and self.model_adapter.category_matches(scores, category_id)
            for category_id, checkbox in self.filter_checkboxes.items()
        )

    def render_cached_results(self):
        self.image_list.clear()

        for image_path, scores in sorted(
            self.scan_results.items(), key=lambda item: item[0].casefold()
        ):
            if not self._matches_selected_filters(scores):
                continue

            pixmap = QPixmap(image_path)
            if pixmap.isNull():
                continue
            pixmap = pixmap.scaled(
                self.image_list.iconSize(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

            category = self.model_adapter.primary_category(scores)
            label = Path(image_path).name
            if category is not None:
                confidence = scores[category.id]
                label += f"\n{category.label} {confidence:.1f}%"
            if scores["is_nsfw"]:
                label += f"\nNSFW {scores['nsfw_score']:.1f}%"

            item = QListWidgetItem(QIcon(pixmap), label)
            item.setData(Qt.ItemDataRole.UserRole, image_path)
            item.setData(Qt.ItemDataRole.UserRole + 1, scores)
            item.setToolTip(self._format_item_details(image_path, scores))
            self.image_list.addItem(item)

        self.display_count_label.setText(f"Displayed: {self.image_list.count()}")
        self._update_summary()

    def _format_item_details(self, image_path, scores):
        category = self.model_adapter.primary_category(scores)
        lines = []
        if image_path:
            lines.append(image_path)
        lines.append(
            f"Model: {self.model_adapter.display_name} ({self.model_adapter.version})"
        )
        if category is not None:
            lines.append(
                f"Primary category: {category.label} ({scores[category.id]:.2f}%)"
            )
        lines.append(
            f"NSFW: {'Yes' if scores['is_nsfw'] else 'No'} "
            f"({scores['nsfw_score']:.2f}%, threshold "
            f"{self.model_adapter.nsfw_threshold:.1f}%)"
        )
        lines.extend(
            f"{category.label}: {scores[category.id]:.2f}%"
            for category in self.model_adapter.categories
        )
        return "\n".join(lines)

    @Slot(QListWidgetItem, QListWidgetItem)
    def _show_item_details(self, current, _previous):
        if current is None:
            self.selected_path_label.setText("None")
            self.selected_scores_label.clear()
            return

        image_path = current.data(Qt.ItemDataRole.UserRole)
        scores = current.data(Qt.ItemDataRole.UserRole + 1)
        self.selected_path_label.setText(image_path)
        self.selected_scores_label.setText(self._format_item_details("", scores))

    def _update_summary(self):
        counts = Counter()
        for scores in self.scan_results.values():
            category = self.model_adapter.primary_category(scores)
            if category is not None:
                counts[category.id] += 1
        nsfw_count = sum(
            1 for scores in self.scan_results.values() if scores["is_nsfw"]
        )
        scope = (
            "Including subdirectories"
            if self.scan_recursive
            else "Selected directory only"
        )
        lines = [
            f"Model: {self.model_adapter.display_name}",
            f"NSFW threshold: {self.model_adapter.nsfw_threshold:.1f}%",
            f"Directory: {self.selected_directory or 'None'}",
            f"Scope: {scope}",
            f"Found: {self.total_discovered}",
            f"Classified: {len(self.scan_results)}",
            f"Skipped: {len(self.skipped_files)}",
            f"Displayed: {self.image_list.count()}",
            f"NSFW: {nsfw_count}",
            "",
            "Primary categories:",
        ]
        if self.model_adapter.categories:
            lines.extend(
                f"{category.label}: {counts[category.id]}"
                for category in self.model_adapter.categories
            )
        else:
            lines.append("Not supplied by this model")
        self.summary_label.setText("\n".join(lines))

    def _update_skipped_text(self):
        if not self.skipped_files:
            self.skipped_text.clear()
            return
        self.skipped_text.setPlainText(
            "\n\n".join(
                f"{path}\n{error}" for path, error in self.skipped_files.items()
            )
        )

    def clear_results(self):
        if self._scan_is_running():
            self.scan_worker.request_cancel()
            self.status_bar.showMessage("Cancelling scan...")
            return

        self.scan_results.clear()
        self.skipped_files.clear()
        self.total_discovered = 0
        self.image_list.clear()
        self.skipped_text.clear()
        self.selected_path_label.setText("None")
        self.selected_scores_label.clear()
        self.display_count_label.setText("Displayed: 0")
        self._update_summary()
        self.status_bar.showMessage("Results cleared", 3000)

    def show_about(self):
        QMessageBox.about(
            self,
            "About NSFW Detector",
            "NSFW Detector scans supported images locally and displays results "
            "using model-aware filters.\n\n"
            f"Active model: {self.model_adapter.display_name}\n"
            f"NSFW threshold: {self.model_adapter.nsfw_threshold:.1f}%\n\n"
            "Open Settings > Configuration to choose the default model and "
            "scan options.",
        )

    def closeEvent(self, event):
        if self._scan_is_running():
            self._close_when_scan_finishes = True
            self.scan_worker.request_cancel()
            self.status_bar.showMessage("Cancelling scan before closing...")
            event.ignore()
            return
        self._save_filter_settings()
        self.settings.setValue("models/default", self.model_adapter.id)
        self.settings.setValue(
            f"models/{self.model_adapter.id}/nsfw_threshold",
            self.model_adapter.nsfw_threshold,
        )
        self.settings.setValue("scan/recursive", self.checkboxRecursive.isChecked())
        self.settings.sync()
        event.accept()


if __name__ == "__main__":
    try:
        import ctypes

        myappid = "matthewryan.analysistools.nsfwdetective.01"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    finally:
        app = QApplication(sys.argv)
        window = MainWindow()
        sys.exit(app.exec())
