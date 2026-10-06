import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui import AboutDialog, MainWindow
from PySide6.QtCore import QEventLoop, QSettings, QTimer
from PySide6.QtWidgets import QApplication, QTabWidget


class GuiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_about_dialog_has_about_models_and_license_tabs(self):
        from nsfw_detector.model_adapters import create_model_adapter

        dialog = AboutDialog(create_model_adapter("gantman-mobilenet"))
        tabs = dialog.findChild(QTabWidget, "aboutTabs")

        self.assertIsNotNone(tabs)
        self.assertEqual(
            [tabs.tabText(index) for index in range(tabs.count())],
            ["About", "Models", "Third-party licenses"],
        )
        dialog.close()

    def test_saved_nudenet_configuration_and_recursive_scan(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            previous_data_directory = os.environ.get("NSFW_DETECTOR_DATA_DIR")
            os.environ["NSFW_DETECTOR_DATA_DIR"] = temporary_directory
            try:
                settings = QSettings(
                    str(Path(temporary_directory) / "settings.ini"),
                    QSettings.Format.IniFormat,
                )
                settings.setValue("models/default", "nudenet-320n")
                settings.setValue("models/nudenet-320n/nsfw_threshold", 35.0)
                settings.setValue("scan/recursive", True)

                window = MainWindow(settings=settings)
                self.assertEqual(window.model_adapter.id, "nudenet-320n")
                self.assertTrue(window.model_adapter.loaded)
                self.assertTrue(window.checkboxRecursive.isChecked())

                window.selected_directory = str(
                    (Path(__file__).resolve().parents[1] / "images").resolve()
                )
                window.start_scan()
                loop = QEventLoop()
                window.scan_thread.finished.connect(loop.quit)
                QTimer.singleShot(15_000, loop.quit)
                loop.exec()

                for _ in range(20):
                    self.application.processEvents()
                    if not window._thumbnail_queue:
                        break

                self.assertFalse(window._scan_is_running())
                self.assertEqual(window.total_discovered, 4)
                self.assertEqual(len(window.scan_results), 4)
                self.assertEqual(window.skipped_files, {})
                self.assertIn("Scan complete", window.scan_state_label.text())
                self.assertTrue(window.rescan_action.isEnabled())
                self.assertFalse(window.scan_progress_bar.isVisible())
                self.assertGreaterEqual(
                    sum(
                        1
                        for result in window.scan_results.values()
                        if result["is_nsfw"]
                    ),
                    1,
                )

                classified_before_filtering = window.newly_classified
                cache_hits_before_filtering = window.cache_hits
                window.checkboxAllResults.setChecked(True)
                for _ in range(20):
                    self.application.processEvents()
                    if not window._thumbnail_queue:
                        break
                self.assertEqual(window.image_list.count(), 4)
                self.assertEqual(window.newly_classified, classified_before_filtering)
                self.assertEqual(window.cache_hits, cache_hits_before_filtering)

                window.start_scan()
                rescan_loop = QEventLoop()
                window.scan_thread.finished.connect(rescan_loop.quit)
                QTimer.singleShot(15_000, rescan_loop.quit)
                rescan_loop.exec()
                self.assertFalse(window._scan_is_running())
                self.assertEqual(window.cache_hits, 4)
                self.assertEqual(window.newly_classified, 0)
                self.assertIn("4 from cache", window.scan_state_label.text())
                window.close()
            finally:
                if previous_data_directory is None:
                    os.environ.pop("NSFW_DETECTOR_DATA_DIR", None)
                else:
                    os.environ["NSFW_DETECTOR_DATA_DIR"] = previous_data_directory


if __name__ == "__main__":
    unittest.main()
