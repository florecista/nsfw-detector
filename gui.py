import sys
from collections import Counter
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDockWidget,
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

from nsfw_detector import predict


APP_DIR = Path(__file__).resolve().parent
MODEL_PATH = APP_DIR / "nsfw_detector" / "nsfw_model.h5"
APP_ICON_PATH = APP_DIR / "hacker-icon.png"

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
NSFW_CATEGORIES = ("hentai", "porn", "sexy")
NSFW_THRESHOLD = 70.0
CATEGORY_THRESHOLDS = {
    "drawings": 40.0,
    "hentai": 70.0,
    "neutral": 25.0,
    "porn": 70.0,
    "sexy": 70.0,
}
CATEGORY_LABELS = {
    "drawings": "Drawings",
    "hentai": "Hentai",
    "neutral": "Neutral",
    "porn": "Porn",
    "sexy": "Sexy",
}


def evaluate_scores(raw_scores):
    """Return normalized scores and the single NSFW decision used by the UI."""
    scores = {
        category: float(raw_scores.get(category, 0.0))
        for category in CATEGORY_THRESHOLDS
    }
    nsfw_score = sum(scores[category] for category in NSFW_CATEGORIES)
    scores["nsfw_score"] = nsfw_score
    scores["is_nsfw"] = nsfw_score >= NSFW_THRESHOLD
    return scores


def primary_category(scores):
    return max(CATEGORY_THRESHOLDS, key=lambda category: scores[category])


class ScanWorker(QObject):
    image_scanned = Signal(str, dict)
    image_skipped = Signal(str, str)
    progress = Signal(int, int, str)
    finished = Signal(bool)

    def __init__(self, model, image_paths):
        super().__init__()
        self.model = model
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

                result = predict.classify(self.model, path_text)
                raw_scores = result.get("data")
                if not isinstance(raw_scores, dict):
                    raise ValueError("The model did not return scores for this image.")
                self.image_scanned.emit(path_text, evaluate_scores(raw_scores))
            except Exception as error:
                self.image_skipped.emit(path_text, str(error))

            self.progress.emit(index, total, path_text)

        self.finished.emit(self._cancel_requested)


class MainWindow(QMainWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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
        self.model = self._load_model_once()

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

        layout.addRow(QLabel("Display results matching:", filter_form))

        self.checkboxAllNsfw = QCheckBox(
            f"All NSFW (combined score ≥ {NSFW_THRESHOLD:.0f}%)", self
        )
        self.checkboxAllNsfw.setChecked(False)
        layout.addRow(self.checkboxAllNsfw)

        self.checkboxHentai = QCheckBox("Hentai", self)
        self.checkboxHentai.setChecked(True)
        layout.addRow(self.checkboxHentai)

        self.checkboxSexy = QCheckBox("Sexy", self)
        self.checkboxSexy.setChecked(True)
        layout.addRow(self.checkboxSexy)

        self.checkboxPorn = QCheckBox("Porn", self)
        self.checkboxPorn.setChecked(True)
        layout.addRow(self.checkboxPorn)

        self.checkboxDrawings = QCheckBox("Drawings", self)
        self.checkboxDrawings.setChecked(True)
        layout.addRow(self.checkboxDrawings)

        self.checkboxNeutral = QCheckBox("Neutral", self)
        self.checkboxNeutral.setChecked(True)
        layout.addRow(self.checkboxNeutral)

        layout.addRow(QPushButton("Apply filters", clicked=self.filter))
        layout.addRow(QPushButton("Clear results", clicked=self.clear_results))

        layout.addRow(QLabel("Scan options:", filter_form))
        self.checkboxRecursive = QCheckBox("Include subdirectories", self)
        self.checkboxRecursive.setChecked(False)
        self.checkboxRecursive.setToolTip("Applies the next time a directory is opened")
        layout.addRow(self.checkboxRecursive)

        formats = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        format_label = QLabel(f"Formats: {formats}", filter_form)
        format_label.setWordWrap(True)
        layout.addRow(format_label)

        self.filter_dock.setWidget(filter_form)
        self.filter_checkboxes = {
            "hentai": self.checkboxHentai,
            "sexy": self.checkboxSexy,
            "porn": self.checkboxPorn,
            "drawings": self.checkboxDrawings,
            "neutral": self.checkboxNeutral,
        }

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

    def _load_model_once(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.status_bar.showMessage("Loading model...")
        QApplication.processEvents()
        try:
            model = predict.load_model(str(MODEL_PATH))
        except Exception as error:
            self.open_action.setEnabled(False)
            QMessageBox.critical(
                self,
                "Model load failed",
                f"The NSFW model could not be loaded:\n\n{error}",
            )
            self.status_bar.showMessage("Model load failed")
            return None
        finally:
            QApplication.restoreOverrideCursor()

        self.status_bar.showMessage("Model ready", 5000)
        return model

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
        if self.model is None:
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
        self.progress_dialog = QProgressDialog(
            "Preparing scan...", "Cancel", 0, len(image_paths), self
        )
        self.progress_dialog.setWindowTitle("Scanning images")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setAutoClose(False)
        self.progress_dialog.setAutoReset(False)

        self.scan_thread = QThread(self)
        self.scan_worker = ScanWorker(self.model, image_paths)
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
        if progress_dialog is not None:
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
        self.render_cached_results()

    def _matches_selected_filters(self, scores):
        if self.checkboxAllNsfw.isChecked() and scores["is_nsfw"]:
            return True

        return any(
            checkbox.isChecked()
            and scores[category] >= CATEGORY_THRESHOLDS[category]
            for category, checkbox in self.filter_checkboxes.items()
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

            category = primary_category(scores)
            confidence = scores[category]
            label = f"{Path(image_path).name}\n{CATEGORY_LABELS[category]} {confidence:.1f}%"
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
        category = primary_category(scores)
        lines = []
        if image_path:
            lines.append(image_path)
        lines.extend(
            [
                f"Primary category: {CATEGORY_LABELS[category]} ({scores[category]:.2f}%)",
                f"NSFW: {'Yes' if scores['is_nsfw'] else 'No'} "
                f"({scores['nsfw_score']:.2f}%)",
            ]
        )
        lines.extend(
            f"{CATEGORY_LABELS[name]}: {scores[name]:.2f}%"
            for name in CATEGORY_THRESHOLDS
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
        counts = Counter(
            primary_category(scores) for scores in self.scan_results.values()
        )
        nsfw_count = sum(
            1 for scores in self.scan_results.values() if scores["is_nsfw"]
        )
        scope = (
            "Including subdirectories"
            if self.scan_recursive
            else "Selected directory only"
        )
        lines = [
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
        lines.extend(
            f"{CATEGORY_LABELS[category]}: {counts[category]}"
            for category in CATEGORY_THRESHOLDS
        )
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
            "using configurable category filters.\n\n"
            f"All NSFW means {', '.join(NSFW_CATEGORIES)} combined ≥ "
            f"{NSFW_THRESHOLD:.0f}%.",
        )

    def closeEvent(self, event):
        if self._scan_is_running():
            self._close_when_scan_finishes = True
            self.scan_worker.request_cancel()
            self.status_bar.showMessage("Cancelling scan before closing...")
            event.ignore()
            return
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
