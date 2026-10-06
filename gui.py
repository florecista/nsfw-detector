import sys
import os
import html
from collections import Counter, deque
from datetime import datetime
from importlib import metadata
from pathlib import Path
from time import monotonic

# ONNX Runtime and Qt ship overlapping Windows runtime DLLs. Loading ONNX
# Runtime first avoids a process-level DLL collision when NudeNet is selected.
import onnxruntime  # noqa: F401
from PIL import Image
from PySide6.QtCore import QObject, QSettings, QSize, Qt, QThread, QTimer, Signal, Slot
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
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from nsfw_detector.model_adapters import (
    DEFAULT_MODEL_ID,
    available_model_types,
    create_model_adapter,
)
from nsfw_detector.result_cache import ResultCache


APP_DIR = Path(__file__).resolve().parent
APP_ICON_PATH = APP_DIR / "hacker-icon.png"
ORGANIZATION_NAME = "florecista"
APPLICATION_NAME = "NSFW Detector"
APPLICATION_VERSION = "Development build"
APPLICATION_COPYRIGHT = "Copyright © 2026 florecista. All rights reserved."

THIRD_PARTY_COMPONENTS = (
    (
        "PySide6 / Qt for Python",
        "PySide6",
        "LGPL-3.0 / GPL-3.0 or commercial",
        "https://doc.qt.io/qtforpython-6/",
        "https://doc.qt.io/qtforpython-6/licenses.html",
    ),
    (
        "TensorFlow",
        "tensorflow",
        "Apache-2.0",
        "https://github.com/tensorflow/tensorflow",
        "https://github.com/tensorflow/tensorflow/blob/master/LICENSE",
    ),
    (
        "TensorFlow Hub",
        "tensorflow-hub",
        "Apache-2.0",
        "https://github.com/tensorflow/hub",
        "https://github.com/tensorflow/hub/blob/master/LICENSE",
    ),
    (
        "TF-Keras",
        "tf-keras",
        "Apache-2.0",
        "https://github.com/keras-team/tf-keras",
        "https://github.com/keras-team/tf-keras/blob/master/LICENSE",
    ),
    (
        "Pillow",
        "Pillow",
        "HPND",
        "https://python-pillow.github.io/",
        "https://github.com/python-pillow/Pillow/blob/main/LICENSE",
    ),
    (
        "NumPy",
        "numpy",
        "BSD-3-Clause; bundled components have additional notices",
        "https://numpy.org/",
        "https://github.com/numpy/numpy/blob/main/LICENSE.txt",
    ),
    (
        "ONNX Runtime",
        "onnxruntime",
        "MIT",
        "https://onnxruntime.ai/",
        "https://github.com/microsoft/onnxruntime/blob/main/LICENSE",
    ),
    (
        "OpenNSFW2",
        "opennsfw2",
        "MIT",
        "https://github.com/bhky/opennsfw2",
        "https://github.com/bhky/opennsfw2/blob/main/LICENSE",
    ),
    (
        "OpenCV Python",
        "opencv-python",
        "Apache-2.0",
        "https://opencv.org/",
        "https://github.com/opencv/opencv-python/blob/4.x/LICENSE.txt",
    ),
)

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _installed_version(distribution_name):
    try:
        return metadata.version(distribution_name)
    except metadata.PackageNotFoundError:
        return "Not installed"


def _text_browser(html_text, parent):
    browser = QTextBrowser(parent)
    browser.setOpenExternalLinks(True)
    browser.setHtml(html_text)
    return browser


class AboutDialog(QDialog):
    def __init__(self, active_model, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {APPLICATION_NAME}")
        self.setMinimumSize(680, 520)

        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)
        tabs.setObjectName("aboutTabs")
        tabs.addTab(self._about_tab(), "About")
        tabs.addTab(self._models_tab(active_model), "Models")
        tabs.addTab(self._third_party_tab(), "Third-party licenses")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _about_tab(self):
        return _text_browser(
            f"""
            <h1>{APPLICATION_NAME}</h1>
            <p><b>{APPLICATION_VERSION}</b></p>
            <p>Scans directories for potentially not-safe-for-work images using
            a selectable local classification model. Images and classification
            results remain on this computer.</p>
            <h2>Application license</h2>
            <p>{APPLICATION_COPYRIGHT}</p>
            <p>This development build does not yet include a separate application
            license file. No permission to copy, modify, redistribute, sublicense,
            or commercially use the application is granted unless the copyright
            owner provides those rights in a distributed license.</p>
            <p>Third-party libraries and model assets remain subject to their own
            licenses, shown on the other tabs.</p>
            """,
            self,
        )

    def _models_tab(self, active_model):
        sections = []
        for adapter_type in available_model_types():
            active_text = (
                " <b>(active)</b>" if adapter_type.id == active_model.id else ""
            )
            asset = getattr(adapter_type, "asset", None)
            checksum = getattr(asset, "sha256", None) or getattr(
                adapter_type, "asset_sha256", "Not specified"
            )
            sections.append(
                f"<h2>{html.escape(adapter_type.display_name)}{active_text}</h2>"
                f"<p>{html.escape(adapter_type.description)}</p>"
                f"<p><b>Model ID:</b> {html.escape(adapter_type.id)}<br>"
                f"<b>Version:</b> {html.escape(adapter_type.version)}<br>"
                f"<b>License:</b> {html.escape(adapter_type.license_name)}<br>"
                f"<b>SHA-256:</b> <code>{html.escape(checksum)}</code><br>"
                f'<b>Source:</b> <a href="{html.escape(adapter_type.source_url)}">'
                f"{html.escape(adapter_type.source_url)}</a></p>"
            )
        return _text_browser(
            "<p>Model weights are separate works from the application and its "
            "Python libraries. Review their terms before redistribution.</p>"
            + "".join(sections),
            self,
        )

    def _third_party_tab(self):
        rows = []
        for (
            name,
            distribution,
            license_name,
            source_url,
            license_url,
        ) in THIRD_PARTY_COMPONENTS:
            rows.append(
                "<tr>"
                f"<td><b>{html.escape(name)}</b></td>"
                f"<td>{html.escape(_installed_version(distribution))}</td>"
                f"<td>{html.escape(license_name)}</td>"
                f'<td><a href="{html.escape(source_url)}">Project</a> | '
                f'<a href="{html.escape(license_url)}">License</a></td>'
                "</tr>"
            )
        return _text_browser(
            "<p>This list covers the application's direct Python dependencies. "
            "Packaged distributions should also include the complete applicable "
            "license texts, copyright notices, and notices for transitive or "
            "bundled components.</p>"
            "<table cellspacing='0' cellpadding='6' border='1'>"
            "<tr><th>Component</th><th>Installed version</th>"
            "<th>License</th><th>Information</th></tr>"
            + "".join(rows)
            + "</table><p><b>Important:</b> This screen is an attribution aid; "
            "it is not a substitute for including the required license and "
            "notice files with a distributed build.</p>",
            self,
        )


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
            self.model_thresholds.get(
                selected_model_id,
                self._adapter_type(selected_model_id).default_nsfw_threshold,
            )
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
            self.model_thresholds.get(
                self.current_model_id,
                self._adapter_type(self.current_model_id).default_nsfw_threshold,
            )
        )
        self._update_model_description()

    def _adapter_type(self, model_id):
        return next(
            model_type
            for model_type in available_model_types()
            if model_type.id == model_id
        )

    def _update_model_description(self):
        adapter_type = self._adapter_type(self.model_combo.currentData())
        region_text = "Yes" if adapter_type.supports_regions else "No"
        self.model_description.setText(
            f"{adapter_type.description}<br><br>"
            f"Version: {adapter_type.version}<br>"
            f"Region detection: {region_text}<br>"
            f"License: {adapter_type.license_name}<br>"
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
    image_scanned = Signal(str, dict, bool)
    image_skipped = Signal(str, str)
    discovery_progress = Signal(str, int)
    discovery_finished = Signal(int)
    progress = Signal(int, int, str)
    finished = Signal(bool, int, int)

    def __init__(
        self,
        model_adapter,
        selected_directory,
        recursive,
        supported_extensions,
    ):
        super().__init__()
        self.model_adapter = model_adapter
        self.selected_directory = Path(selected_directory)
        self.recursive = recursive
        self.supported_extensions = set(supported_extensions)
        self._cancel_requested = False

    def request_cancel(self):
        self._cancel_requested = True

    def _directory_error(self, error):
        filename = getattr(error, "filename", None) or str(self.selected_directory)
        self.image_skipped.emit(str(filename), str(error))

    def _discover_images(self):
        image_paths = []
        if self.recursive:
            for directory, directory_names, filenames in os.walk(
                self.selected_directory,
                topdown=True,
                followlinks=False,
                onerror=self._directory_error,
            ):
                if self._cancel_requested:
                    break
                directory_names.sort(key=str.casefold)
                filenames.sort(key=str.casefold)
                for filename in filenames:
                    if self._cancel_requested:
                        break
                    path = Path(directory) / filename
                    if path.suffix.lower() not in self.supported_extensions:
                        continue
                    try:
                        resolved = path.resolve()
                    except OSError as error:
                        self.image_skipped.emit(str(path), str(error))
                        continue
                    image_paths.append(resolved)
                    self.discovery_progress.emit(str(resolved), len(image_paths))
        else:
            try:
                entries = sorted(
                    self.selected_directory.iterdir(),
                    key=lambda path: str(path).casefold(),
                )
            except OSError as error:
                self._directory_error(error)
                return image_paths
            for path in entries:
                if self._cancel_requested:
                    break
                try:
                    supported = (
                        path.is_file()
                        and path.suffix.lower() in self.supported_extensions
                    )
                except OSError as error:
                    self.image_skipped.emit(str(path), str(error))
                    continue
                if supported:
                    try:
                        resolved = path.resolve()
                    except OSError as error:
                        self.image_skipped.emit(str(path), str(error))
                        continue
                    image_paths.append(resolved)
                    self.discovery_progress.emit(str(resolved), len(image_paths))
        return image_paths

    def _classify_missing(self, paths):
        valid_paths = []
        errors = {}
        for path in paths:
            try:
                with Image.open(path) as image:
                    image.load()
                valid_paths.append(path)
            except Exception as error:
                errors[str(path)] = str(error)

        results = {}
        if valid_paths:
            try:
                results.update(self.model_adapter.classify_batch(valid_paths))
            except Exception:
                # Fall back to individual inference so one troublesome image does
                # not cause an otherwise valid batch to be skipped.
                for path in valid_paths:
                    try:
                        results[str(path)] = self.model_adapter.classify(str(path))
                    except Exception as error:
                        errors[str(path)] = str(error)
        return results, errors

    @Slot()
    def run(self):
        cache_hits = 0
        newly_classified = 0
        image_paths = self._discover_images()
        total = len(image_paths)
        self.discovery_finished.emit(total)
        if self._cancel_requested:
            self.finished.emit(True, cache_hits, newly_classified)
            return

        with ResultCache() as cache:
            batch_size = max(1, int(self.model_adapter.batch_size))
            for batch_start in range(0, total, batch_size):
                if self._cancel_requested:
                    self.finished.emit(True, cache_hits, newly_classified)
                    return

                batch = image_paths[batch_start : batch_start + batch_size]
                batch_results = {}
                cached_paths = set()
                missing = []
                errors = {}
                for image_path in batch:
                    path_text = str(image_path)
                    try:
                        cached = cache.get(
                            image_path,
                            self.model_adapter.id,
                            self.model_adapter.version,
                        )
                    except Exception:
                        cached = None
                    if cached is None:
                        missing.append(image_path)
                    else:
                        batch_results[path_text] = self.model_adapter.apply_threshold(cached)
                        cached_paths.add(path_text)

                classified_results, classification_errors = self._classify_missing(
                    missing
                )
                batch_results.update(classified_results)
                errors.update(classification_errors)

                for path_text, result in classified_results.items():
                    try:
                        cache.put(
                            path_text,
                            self.model_adapter.id,
                            self.model_adapter.version,
                            result,
                        )
                    except Exception:
                        # A cache failure must not turn a successful classification
                        # into a skipped image.
                        pass
                try:
                    cache.commit()
                except Exception:
                    pass

                for batch_index, image_path in enumerate(batch, start=1):
                    path_text = str(image_path)
                    index = batch_start + batch_index
                    if path_text in batch_results:
                        from_cache = path_text in cached_paths
                        if from_cache:
                            cache_hits += 1
                        else:
                            newly_classified += 1
                        self.image_scanned.emit(
                            path_text,
                            batch_results[path_text],
                            from_cache,
                        )
                    else:
                        self.image_skipped.emit(
                            path_text,
                            errors.get(path_text, "The model returned no result."),
                        )
                    self.progress.emit(index, total, path_text)

            if self._cancel_requested:
                self.finished.emit(True, cache_hits, newly_classified)
                return

        self.finished.emit(self._cancel_requested, cache_hits, newly_classified)


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
        self.cache_hits = 0
        self.newly_classified = 0
        self.scan_recursive = False
        self.scan_thread = None
        self.scan_worker = None
        self.progress_dialog = None
        self._close_when_scan_finishes = False
        self._thumbnail_queue = deque()
        self._thumbnail_generation = 0
        self._filters_ready = False
        self._scan_started_at = None

        self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.setGeometry(100, 100, 1100, 700)
        self.set_title()

        self._build_results_view()
        self._build_actions()
        self._build_filter_panel()
        self._build_details_panel()
        self._build_status_bar()
        self._filters_ready = True

        self.show()
        self._load_model_adapter(self.model_adapter)

    def _build_results_view(self):
        central_widget = QWidget(self)
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(6, 6, 6, 6)

        scan_status_widget = QWidget(central_widget)
        scan_status_layout = QHBoxLayout(scan_status_widget)
        scan_status_layout.setContentsMargins(6, 4, 6, 4)

        self.scan_state_label = QLabel(
            "Ready — select and scan a directory.", scan_status_widget
        )
        self.scan_state_label.setWordWrap(True)
        self.scan_state_label.setStyleSheet("font-weight: 600;")
        scan_status_layout.addWidget(self.scan_state_label, 1)

        self.scan_progress_bar = QProgressBar(scan_status_widget)
        self.scan_progress_bar.setMinimumWidth(190)
        self.scan_progress_bar.setTextVisible(True)
        self.scan_progress_bar.hide()
        scan_status_layout.addWidget(self.scan_progress_bar)

        self.cancel_scan_button = QPushButton("Cancel scan", scan_status_widget)
        self.cancel_scan_button.clicked.connect(self.cancel_scan)
        self.cancel_scan_button.hide()
        scan_status_layout.addWidget(self.cancel_scan_button)

        central_layout.addWidget(scan_status_widget)

        self.image_list = QListWidget(central_widget)
        self.image_list.setViewMode(QListView.ViewMode.IconMode)
        self.image_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.image_list.setMovement(QListView.Movement.Static)
        self.image_list.setWrapping(True)
        self.image_list.setWordWrap(True)
        self.image_list.setIconSize(QSize(144, 144))
        self.image_list.setGridSize(QSize(190, 205))
        self.image_list.setSpacing(8)
        self.image_list.currentItemChanged.connect(self._show_item_details)
        central_layout.addWidget(self.image_list, 1)
        self.setCentralWidget(central_widget)

    def _build_actions(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        settings_menu = menu_bar.addMenu("&Settings")
        help_menu = menu_bar.addMenu("&Help")

        self.open_action = QAction("&Select and scan directory...", self)
        self.open_action.triggered.connect(self.open_folder)
        self.open_action.setStatusTip("Choose a directory and start scanning it")
        self.open_action.setShortcut("Ctrl+O")
        file_menu.addAction(self.open_action)

        self.rescan_action = QAction("&Rescan selected directory", self)
        self.rescan_action.triggered.connect(self.start_scan)
        self.rescan_action.setStatusTip(
            "Scan the selected directory again with the current scope"
        )
        self.rescan_action.setShortcut("Ctrl+R")
        self.rescan_action.setEnabled(False)
        file_menu.addAction(self.rescan_action)

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

        about_action = QAction("&About...", self)
        about_action.setShortcut("F1")
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        toolbar = QToolBar("Main toolbar", self)
        toolbar.setIconSize(QSize(16, 16))
        toolbar.addAction(self.open_action)
        toolbar.addAction(self.rescan_action)
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

        filter_explanation = QLabel(
            "Filter changes update these results only. They do not rescan or "
            "run the model.",
            filter_form,
        )
        filter_explanation.setWordWrap(True)
        layout.addRow(filter_explanation)

        self.clear_results_button = QPushButton(
            "Clear displayed scan results", clicked=self.clear_results
        )
        layout.addRow(self.clear_results_button)

        layout.addRow(QLabel("Scan options:", filter_form))
        self.checkboxRecursive = QCheckBox("Include subdirectories", self)
        self.checkboxRecursive.setChecked(
            self.settings.value("scan/recursive", False, type=bool)
        )
        self.checkboxRecursive.setToolTip(
            "Applies the next time a directory is selected or rescanned"
        )
        layout.addRow(self.checkboxRecursive)

        self.rescan_button = QPushButton(
            "Rescan selected directory", clicked=self.start_scan
        )
        self.rescan_button.setEnabled(False)
        layout.addRow(self.rescan_button)

        formats = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        format_label = QLabel(f"Formats: {formats}", filter_form)
        format_label.setWordWrap(True)
        layout.addRow(format_label)

        self.filter_dock.setWidget(filter_form)
        self.filter_checkboxes = {}
        self._rebuild_model_category_filters()
        self._restore_filter_settings()
        self.checkboxAllResults.stateChanged.connect(self._filter_selection_changed)
        self.checkboxNsfw.stateChanged.connect(self._filter_selection_changed)
        self.checkboxSfw.stateChanged.connect(self._filter_selection_changed)

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
        adapter_type = next(
            (
                model_type
                for model_type in available_model_types()
                if model_type.id == model_id
            ),
            None,
        )
        default_threshold = (
            adapter_type.default_nsfw_threshold
            if adapter_type is not None
            else create_model_adapter(DEFAULT_MODEL_ID).default_nsfw_threshold
        )
        value = self.settings.value(
            f"models/{model_id}/nsfw_threshold", default_threshold
        )
        try:
            return float(value)
        except (TypeError, ValueError):
            return default_threshold

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
            checkbox.stateChanged.connect(self._filter_selection_changed)
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
            self.cache_hits = 0
            self.newly_classified = 0
            self.image_list.clear()
            self.skipped_text.clear()
            self.selected_path_label.setText("None")
            self.selected_scores_label.clear()
            self._filters_ready = False
            self._rebuild_model_category_filters()
            self._restore_filter_settings()
            self._filters_ready = True
        else:
            self.model_adapter.nsfw_threshold = selected_threshold
            self.scan_results = {
                path: self.model_adapter.apply_threshold(scores)
                for path, scores in self.scan_results.items()
            }
            self._update_nsfw_filter_label()

        self.checkboxRecursive.setChecked(configuration["recursive_scan"])
        self.settings.setValue("scan/recursive", configuration["recursive_scan"])
        for model_id, threshold in configuration["model_thresholds"].items():
            self.settings.setValue(f"models/{model_id}/nsfw_threshold", threshold)
        self.settings.setValue("models/default", self.model_adapter.id)
        self.settings.sync()
        self.render_cached_results()
        self._update_rescan_enabled()
        self.status_bar.showMessage("Configuration saved", 5000)

    def _load_model_adapter(self, model_adapter):
        self.scan_state_label.setText(f"Loading {model_adapter.display_name}...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.status_bar.showMessage(f"Loading {model_adapter.display_name}...")
        QApplication.processEvents()
        try:
            model_adapter.load()
        except Exception as error:
            current_model_available = self.model_adapter.loaded
            if not current_model_available:
                self.open_action.setEnabled(False)
            QMessageBox.critical(
                self,
                "Model load failed",
                f"{model_adapter.display_name} could not be loaded:\n\n{error}",
            )
            self.status_bar.showMessage("Model load failed")
            if current_model_available:
                self.scan_state_label.setText(
                    f"Could not load {model_adapter.display_name}. The current "
                    "model remains ready."
                )
            else:
                self.scan_state_label.setText(
                    "Model unavailable — open Settings > Configuration to choose "
                    "or retry a model."
                )
            self._update_rescan_enabled()
            return False
        finally:
            QApplication.restoreOverrideCursor()

        self.open_action.setEnabled(True)
        self.status_bar.showMessage(f"{model_adapter.display_name} ready", 5000)
        if self.selected_directory:
            self.scan_state_label.setText(
                "Ready — choose Rescan selected directory to start a new scan."
            )
        else:
            self.scan_state_label.setText("Ready — select and scan a directory.")
        self._update_rescan_enabled()
        return True

    def _update_rescan_enabled(self):
        enabled = bool(
            self.selected_directory
            and self.model_adapter.loaded
            and not self._scan_is_running()
        )
        if hasattr(self, "rescan_action"):
            self.rescan_action.setEnabled(enabled)
        if hasattr(self, "rescan_button"):
            self.rescan_button.setEnabled(enabled)

    def _set_scan_controls_enabled(self, enabled):
        self.open_action.setEnabled(enabled and self.model_adapter.loaded)
        self.configuration_action.setEnabled(enabled)
        self.checkboxRecursive.setEnabled(enabled)
        self.checkboxAllResults.setEnabled(enabled)
        self.checkboxNsfw.setEnabled(enabled)
        self.checkboxSfw.setEnabled(enabled)
        self.category_filter_widget.setEnabled(enabled)
        self.clear_results_button.setEnabled(enabled)
        if enabled:
            self._update_rescan_enabled()
        else:
            self.rescan_action.setEnabled(False)
            self.rescan_button.setEnabled(False)

    @Slot()
    def cancel_scan(self):
        if self.scan_worker is None or not self._scan_is_running():
            return
        self.scan_worker.request_cancel()
        self.cancel_scan_button.setEnabled(False)
        self.scan_state_label.setText("Cancelling scan...")
        self.status_bar.showMessage("Cancelling scan...")

    @Slot()
    def _show_progress_dialog_if_scanning(self):
        if self.progress_dialog is not None and self._scan_is_running():
            self.progress_dialog.show()

    def set_title(self, filename=None):
        name = filename if filename else "No directory"
        self.setWindowTitle(f"{name} - {self.title}")

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
        if self._scan_is_running():
            return
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

        self.scan_recursive = self.checkboxRecursive.isChecked()
        self.scan_results.clear()
        self.skipped_files.clear()
        self.image_list.clear()
        self.skipped_text.clear()
        self.total_discovered = 0
        self.cache_hits = 0
        self.newly_classified = 0
        self._scan_started_at = monotonic()
        self._update_summary()

        self._set_scan_controls_enabled(False)
        self.scan_state_label.setText("Discovering supported images...")
        self.scan_progress_bar.setRange(0, 0)
        self.scan_progress_bar.setFormat("Discovering images…")
        self.scan_progress_bar.show()
        self.cancel_scan_button.setEnabled(True)
        self.cancel_scan_button.show()
        self.progress_dialog = QProgressDialog(
            "Discovering supported images...", "Cancel", 0, 0, self
        )
        self.progress_dialog.setWindowTitle("Scanning images")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(750)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.setAutoReset(False)

        self.scan_thread = QThread(self)
        self.scan_worker = ScanWorker(
            self.model_adapter,
            self.selected_directory,
            self.scan_recursive,
            SUPPORTED_EXTENSIONS,
        )
        self.scan_worker.moveToThread(self.scan_thread)

        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_worker.image_scanned.connect(self._cache_scan_result)
        self.scan_worker.image_skipped.connect(self._cache_skipped_file)
        self.scan_worker.discovery_progress.connect(self._update_discovery_progress)
        self.scan_worker.discovery_finished.connect(self._finish_discovery)
        self.scan_worker.progress.connect(self._update_scan_progress)
        self.scan_worker.finished.connect(self._finish_scan)
        self.scan_worker.finished.connect(self.scan_thread.quit)
        self.scan_worker.finished.connect(self.scan_worker.deleteLater)
        self.scan_thread.finished.connect(self._release_scan_thread)
        self.scan_thread.finished.connect(self.scan_thread.deleteLater)
        # A direct Python callback updates the worker's cancellation flag even
        # while its thread is busy inside the scan loop.
        self.progress_dialog.canceled.connect(self.cancel_scan)

        recursive_text = " recursively" if self.scan_recursive else ""
        self.status_bar.showMessage(f"Discovering images{recursive_text}...")
        self.scan_thread.start()
        QTimer.singleShot(750, self._show_progress_dialog_if_scanning)

    @Slot(str, int)
    def _update_discovery_progress(self, image_path, count):
        filename = Path(image_path).name
        if self.progress_dialog is not None:
            self.progress_dialog.setLabelText(
                f"Discovering images ({count} found):\n{filename}"
            )
        self.scan_state_label.setText(
            f"Discovering images — {count} found. Current file: {filename}"
        )
        self.scan_progress_bar.setFormat(f"{count} found")
        self.status_bar.showMessage(f"Discovering images: {count} found")

    @Slot(int)
    def _finish_discovery(self, total):
        self.total_discovered = total
        if self.progress_dialog is not None:
            self.progress_dialog.setRange(0, max(total, 1))
            self.progress_dialog.setValue(0)
            if total:
                self.progress_dialog.setLabelText(
                    f"Discovered {total} image(s). Starting classification..."
                )
            else:
                self.progress_dialog.setLabelText("No supported images found.")
        self.scan_progress_bar.setRange(0, max(total, 1))
        self.scan_progress_bar.setValue(0)
        if total:
            self.scan_progress_bar.setFormat(f"0 of {total}")
            self.scan_state_label.setText(
                f"Discovered {total} image(s). Starting classification..."
            )
        else:
            self.scan_progress_bar.setValue(1)
            self.scan_progress_bar.setFormat("No supported images")
            self.scan_state_label.setText("No supported images found.")
        self._update_summary()

    @Slot(str, dict, bool)
    def _cache_scan_result(self, image_path, scores, from_cache):
        self.scan_results[image_path] = scores
        if from_cache:
            self.cache_hits += 1
        else:
            self.newly_classified += 1

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
        self.scan_progress_bar.setMaximum(total)
        self.scan_progress_bar.setValue(current)
        self.scan_progress_bar.setFormat(f"{current} of {total}")
        self.scan_state_label.setText(
            f"Processing image {current} of {total}: {Path(image_path).name}"
        )
        self.status_bar.showMessage(
            f"Processing {current}/{total}: {Path(image_path).name}"
        )

    @Slot(bool, int, int)
    def _finish_scan(self, cancelled, cache_hits, newly_classified):
        self.cache_hits = cache_hits
        self.newly_classified = newly_classified
        if self.progress_dialog is not None:
            self.progress_dialog.close()
            self.progress_dialog.deleteLater()
            self.progress_dialog = None

        self.scan_progress_bar.hide()
        self.cancel_scan_button.hide()
        self._set_scan_controls_enabled(True)
        self._update_skipped_text()
        self.render_cached_results()

        elapsed = (
            monotonic() - self._scan_started_at
            if self._scan_started_at is not None
            else 0.0
        )
        self._scan_started_at = None
        completed_at = datetime.now().strftime("%H:%M:%S")

        if not cancelled and self.total_discovered == 0:
            completion = (
                f"Scan complete at {completed_at} — no supported images found "
                f"({elapsed:.1f}s)."
            )
            self.scan_state_label.setText(completion)
            self.status_bar.showMessage(completion)
            QMessageBox.information(
                self,
                "No images found",
                "No supported images were found in the selected scan scope.",
            )
            return

        status = "cancelled" if cancelled else "complete"
        completion = (
            f"Scan {status} at {completed_at} — "
            f"{len(self.scan_results)} classified, "
            f"{len(self.skipped_files)} skipped, {cache_hits} from cache, "
            f"{newly_classified} newly classified ({elapsed:.1f}s)."
        )
        self.scan_state_label.setText(completion)
        self.status_bar.showMessage(completion)

    @Slot()
    def _release_scan_thread(self):
        self.scan_worker = None
        self.scan_thread = None
        self._update_rescan_enabled()
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

    @Slot()
    def _filter_selection_changed(self):
        if not self._filters_ready:
            return
        self._save_filter_settings()
        self.settings.sync()
        if self.selected_directory:
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
        self._thumbnail_generation += 1
        generation = self._thumbnail_generation
        self.image_list.clear()
        self._thumbnail_queue = deque(
            (image_path, scores)
            for image_path, scores in sorted(
                self.scan_results.items(), key=lambda item: item[0].casefold()
            )
            if self._matches_selected_filters(scores)
        )
        self.display_count_label.setText("Displayed: 0")
        self._update_summary()
        QTimer.singleShot(0, lambda: self._render_thumbnail_batch(generation))

    def _render_thumbnail_batch(self, generation):
        if generation != self._thumbnail_generation:
            return

        for _ in range(min(12, len(self._thumbnail_queue))):
            image_path, scores = self._thumbnail_queue.popleft()
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
                confidence = self.model_adapter.score_for(scores, category.id)
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
        if self._thumbnail_queue:
            QTimer.singleShot(0, lambda: self._render_thumbnail_batch(generation))

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
                f"Primary category: {category.label} "
                f"({self.model_adapter.score_for(scores, category.id):.2f}%)"
            )
        lines.append(
            f"NSFW: {'Yes' if scores['is_nsfw'] else 'No'} "
            f"({scores['nsfw_score']:.2f}%, threshold "
            f"{self.model_adapter.nsfw_threshold:.1f}%)"
        )
        lines.extend(
            f"{category.label}: "
            f"{self.model_adapter.score_for(scores, category.id):.2f}%"
            for category in self.model_adapter.categories
        )
        detections = scores.get("detections", [])
        if detections:
            lines.append("")
            lines.append(f"Detected regions: {len(detections)}")
            lines.extend(
                f"{detection['category_id']}: {detection['score']:.2f}% "
                f"at {detection.get('box', [])}"
                for detection in detections
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
            f"From cache: {self.cache_hits}",
            f"Newly classified: {self.newly_classified}",
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
            self.cancel_scan()
            return

        self.scan_results.clear()
        self.skipped_files.clear()
        self.total_discovered = 0
        self.cache_hits = 0
        self.newly_classified = 0
        self._thumbnail_generation += 1
        self._thumbnail_queue.clear()
        self.image_list.clear()
        self.skipped_text.clear()
        self.selected_path_label.setText("None")
        self.selected_scores_label.clear()
        self.display_count_label.setText("Displayed: 0")
        self._update_summary()
        message = (
            "Results cleared — choose Rescan selected directory to process the "
            "directory again."
        )
        self.scan_state_label.setText(message)
        self.status_bar.showMessage(message)
        self._update_rescan_enabled()

    def show_about(self):
        AboutDialog(self.model_adapter, self).exec()

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


def main():
    try:
        import ctypes

        myappid = "matthewryan.analysistools.nsfwdetective.01"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    finally:
        app = QApplication(sys.argv)
        window = MainWindow()
        return app.exec()


if __name__ == "__main__":
    sys.exit(main())
