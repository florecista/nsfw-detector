import hashlib
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

from gui import SUPPORTED_EXTENSIONS, ScanWorker
from nsfw_detector.model_adapters import ModelAdapter, ModelCategory
from nsfw_detector.model_store import ModelAsset, ensure_model_asset
from nsfw_detector.result_cache import ResultCache


class FakeAdapter(ModelAdapter):
    id = "fake"
    display_name = "Fake"
    version = "1"
    categories = (ModelCategory("example", "Example", 50.0, True),)
    batch_size = 2

    def load(self):
        self.model = object()
        return self

    def classify(self, image_path):
        return self.build_result({"example": 75.0}, 75.0)

    def classify_batch(self, image_paths):
        return {str(path): self.classify(path) for path in image_paths}


class TemporaryModelStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.previous_data_directory = os.environ.get("NSFW_DETECTOR_DATA_DIR")
        os.environ["NSFW_DETECTOR_DATA_DIR"] = self.temporary_directory.name

    def tearDown(self):
        if self.previous_data_directory is None:
            os.environ.pop("NSFW_DETECTOR_DATA_DIR", None)
        else:
            os.environ["NSFW_DETECTOR_DATA_DIR"] = self.previous_data_directory
        self.temporary_directory.cleanup()


class ModelAssetTests(TemporaryModelStoreTestCase):
    def test_bundled_asset_is_copied_and_corruption_is_repaired(self):
        source = Path(self.temporary_directory.name) / "source.bin"
        source.write_bytes(b"validated model")
        expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        asset = ModelAsset(
            model_id="test-model",
            version="1",
            filename="model.bin",
            sha256=expected_hash,
            bundled_path=source,
        )

        installed = ensure_model_asset(asset)
        self.assertEqual(installed.read_bytes(), b"validated model")

        installed.write_bytes(b"corrupt")
        repaired = ensure_model_asset(asset)
        self.assertEqual(repaired.read_bytes(), b"validated model")

    def test_archive_member_is_downloaded_extracted_and_validated(self):
        archive_path = Path(self.temporary_directory.name) / "model.whl"
        model_data = b"model inside archive"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("package/model.onnx", model_data)
        asset = ModelAsset(
            model_id="archive-model",
            version="1",
            filename="model.onnx",
            sha256=hashlib.sha256(model_data).hexdigest(),
            url=archive_path.as_uri(),
            download_sha256=hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            archive_member="package/model.onnx",
        )

        installed = ensure_model_asset(asset)
        self.assertEqual(installed.read_bytes(), model_data)


class ResultCacheTests(TemporaryModelStoreTestCase):
    def test_cache_key_changes_when_file_changes(self):
        image_path = Path(self.temporary_directory.name) / "image.jpg"
        image_path.write_bytes(b"first")
        result = FakeAdapter().classify(image_path)

        with ResultCache() as cache:
            cache.put(image_path, "fake", "1", result)
            cache.commit()
            self.assertEqual(cache.get(image_path, "fake", "1"), result)

            image_path.write_bytes(b"different size")
            self.assertIsNone(cache.get(image_path, "fake", "1"))


class ScanWorkerTests(TemporaryModelStoreTestCase):
    def _make_image(self, path, colour):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (12, 12), colour).save(path)

    def _run_worker(self, root):
        state = {
            "found": None,
            "results": [],
            "skipped": [],
            "finished": None,
        }
        worker = ScanWorker(
            FakeAdapter().load(),
            root,
            True,
            SUPPORTED_EXTENSIONS,
        )
        worker.discovery_finished.connect(
            lambda count: state.update(found=count)
        )
        worker.image_scanned.connect(
            lambda path, result, cached: state["results"].append(
                (path, result, cached)
            )
        )
        worker.image_skipped.connect(
            lambda path, error: state["skipped"].append((path, error))
        )
        worker.finished.connect(
            lambda cancelled, hits, classified: state.update(
                finished=(cancelled, hits, classified)
            )
        )
        worker.run()
        return state

    def test_recursive_scan_batches_and_reuses_persistent_cache(self):
        root = Path(self.temporary_directory.name) / "scan"
        self._make_image(root / "one.jpg", "red")
        self._make_image(root / "nested" / "two.png", "blue")
        (root / "nested" / "ignored.txt").write_text("ignored")

        first = self._run_worker(root)
        self.assertEqual(first["found"], 2)
        self.assertEqual(len(first["results"]), 2)
        self.assertEqual(first["skipped"], [])
        self.assertEqual(first["finished"], (False, 0, 2))

        second = self._run_worker(root)
        self.assertEqual(second["found"], 2)
        self.assertEqual(len(second["results"]), 2)
        self.assertTrue(all(cached for _, _, cached in second["results"]))
        self.assertEqual(second["finished"], (False, 2, 0))


if __name__ == "__main__":
    unittest.main()
