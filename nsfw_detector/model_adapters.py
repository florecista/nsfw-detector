import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from nsfw_detector.model_store import (
    ModelAsset,
    ensure_model_asset,
    remove_invalid_tensorflow_hub_entries,
    tensorflow_hub_cache_directory,
)


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_ID = "gantman-mobilenet"
DEFAULT_NSFW_THRESHOLD = 70.0
RESULT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ModelCategory:
    id: str
    label: str
    threshold: float | None = None
    contributes_to_nsfw: bool = False


class ModelAdapter(ABC):
    id = ""
    display_name = ""
    version = ""
    description = ""
    source_url = ""
    license_name = ""
    categories = ()
    supports_regions = False
    default_nsfw_threshold = DEFAULT_NSFW_THRESHOLD
    batch_size = 8

    def __init__(self, nsfw_threshold=None):
        if nsfw_threshold is None:
            nsfw_threshold = self.default_nsfw_threshold
        self.nsfw_threshold = float(nsfw_threshold)
        self.model = None

    @property
    def category_ids(self):
        return tuple(category.id for category in self.categories)

    @property
    def nsfw_category_ids(self):
        return tuple(
            category.id
            for category in self.categories
            if category.contributes_to_nsfw
        )

    @property
    def loaded(self):
        return self.model is not None

    @abstractmethod
    def load(self):
        raise NotImplementedError

    @abstractmethod
    def classify(self, image_path):
        raise NotImplementedError

    def classify_batch(self, image_paths):
        return {str(path): self.classify(str(path)) for path in image_paths}

    def build_result(
        self,
        category_scores,
        nsfw_score,
        *,
        nudity_score=None,
        detections=None,
    ):
        result = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "model_id": self.id,
            "model_version": self.version,
            "category_scores": {
                category.id: float(category_scores.get(category.id, 0.0))
                for category in self.categories
            },
            "nsfw_score": float(nsfw_score),
            "nudity_score": None if nudity_score is None else float(nudity_score),
            "detections": list(detections or []),
        }
        return self.apply_threshold(result)

    def normalize_category_scores(self, raw_scores):
        category_scores = {
            category.id: float(raw_scores.get(category.id, 0.0))
            for category in self.categories
        }
        nsfw_score = sum(
            category_scores[category_id]
            for category_id in self.nsfw_category_ids
        )
        return self.build_result(category_scores, nsfw_score)

    def apply_threshold(self, result):
        updated = dict(result)
        updated["is_nsfw"] = updated["nsfw_score"] >= self.nsfw_threshold
        nudity_score = updated.get("nudity_score")
        updated["is_nudity"] = (
            None if nudity_score is None else nudity_score >= self.nsfw_threshold
        )
        return updated

    def score_for(self, result, category_id):
        return float(result.get("category_scores", {}).get(category_id, 0.0))

    def category_matches(self, result, category_id):
        category = self.get_category(category_id)
        threshold = self.nsfw_threshold if category.threshold is None else category.threshold
        return self.score_for(result, category_id) >= threshold

    def get_category(self, category_id):
        for category in self.categories:
            if category.id == category_id:
                return category
        raise KeyError(f"Unknown category for {self.id}: {category_id}")

    def primary_category(self, result):
        if not self.categories:
            return None
        category = max(
            self.categories,
            key=lambda category: self.score_for(result, category.id),
        )
        if self.score_for(result, category.id) <= 0.0:
            return None
        return category


class GantManMobileNetAdapter(ModelAdapter):
    id = DEFAULT_MODEL_ID
    display_name = "GantMan MobileNet (legacy five categories)"
    version = "1.1.0-mobilenet-v2-140-224"
    description = (
        "Fast legacy 224x224 classifier with Drawings, Hentai, Neutral, Porn, "
        "and Sexy categories. The NSFW score is the combined Hentai, Porn, "
        "and Sexy probability. Its TensorFlow Hub dependency is stored in the "
        "application's versioned model directory."
    )
    source_url = "https://github.com/GantMan/nsfw_model"
    license_name = "MIT"
    default_nsfw_threshold = 70.0
    batch_size = 16
    categories = (
        ModelCategory("drawings", "Drawings", 40.0),
        ModelCategory("hentai", "Hentai", 70.0, contributes_to_nsfw=True),
        ModelCategory("neutral", "Neutral", 25.0),
        ModelCategory("porn", "Porn", 70.0, contributes_to_nsfw=True),
        ModelCategory("sexy", "Sexy", 70.0, contributes_to_nsfw=True),
    )
    asset = ModelAsset(
        model_id=id,
        version=version,
        filename="nsfw_mobilenet_v2_140_224.h5",
        sha256="a36f12fc283559d3071a04f7674f200096f045b0a1d1811e0dc8e834153dd328",
        bundled_path=PROJECT_DIR / "nsfw_detector" / "nsfw_model.h5",
    )

    def load(self):
        from nsfw_detector import predict

        model_path = ensure_model_asset(self.asset)
        hub_cache = tensorflow_hub_cache_directory(self.id, self.version)
        os.environ["TFHUB_CACHE_DIR"] = str(hub_cache)
        try:
            self.model = predict.load_model(str(model_path))
        except Exception:
            remove_invalid_tensorflow_hub_entries(hub_cache)
            self.model = predict.load_model(str(model_path))
        return self

    def classify(self, image_path):
        return self.classify_batch([image_path])[str(image_path)]

    def classify_batch(self, image_paths):
        if not self.loaded:
            raise RuntimeError(f"{self.display_name} has not been loaded.")

        from nsfw_detector import predict

        path_texts = [str(path) for path in image_paths]
        images, loaded_paths = predict.load_images(
            path_texts,
            (predict.IMAGE_DIM, predict.IMAGE_DIM),
            verbose=False,
        )
        if len(loaded_paths) != len(path_texts):
            missing = sorted(set(path_texts) - set(loaded_paths))
            raise ValueError(f"Unable to load image(s): {', '.join(missing)}")

        predictions = predict.classify_nd(self.model, images)
        return {
            path: self.normalize_category_scores(raw_scores)
            for path, raw_scores in zip(loaded_paths, predictions)
        }


class NudeNet320Adapter(ModelAdapter):
    id = "nudenet-320n"
    display_name = "NudeNet 320n (explicit nudity)"
    version = "3.4.2-320n"
    description = (
        "Local YOLOv8/ONNX detector for exposed anatomical regions. This is "
        "the recommended fast model when the task is specifically finding "
        "nudity rather than broader NSFW content."
    )
    source_url = "https://github.com/notAI-tech/NudeNet"
    license_name = "Review NudeNet package and repository terms before distribution"
    supports_regions = True
    default_nsfw_threshold = 35.0
    batch_size = 4
    categories = (
        ModelCategory("female_breast_exposed", "Female breast exposed", None, True),
        ModelCategory("female_genitalia_exposed", "Female genitalia exposed", None, True),
        ModelCategory("male_genitalia_exposed", "Male genitalia exposed", None, True),
        ModelCategory("buttocks_exposed", "Buttocks exposed", None, True),
        ModelCategory("anus_exposed", "Anus exposed", None, True),
    )
    asset_sha256 = "c15d8273adad2d0a92f014cc69ab2d6c311a06777a55545f2c4eb46f51911f0f"
    detection_labels = (
        "female_genitalia_covered",
        "face_female",
        "buttocks_exposed",
        "female_breast_exposed",
        "female_genitalia_exposed",
        "male_breast_exposed",
        "anus_exposed",
        "feet_exposed",
        "belly_covered",
        "feet_covered",
        "armpits_covered",
        "armpits_exposed",
        "face_male",
        "belly_exposed",
        "male_genitalia_exposed",
        "anus_covered",
        "female_breast_covered",
        "buttocks_covered",
    )

    def load(self):
        try:
            import onnxruntime
        except ImportError as error:
            raise RuntimeError(
                "ONNX Runtime is not installed. Install the pinned requirements first."
            ) from error

        asset = ModelAsset(
            model_id=self.id,
            version=self.version,
            filename="320n.onnx",
            sha256=self.asset_sha256,
            url=(
                "https://files.pythonhosted.org/packages/1c/ee/"
                "1aa02d44ba958cc77e16ff1e41a0aac5e721037db7bf62b9c9d124917f87/"
                "nudenet-3.4.2-py3-none-any.whl"
            ),
            download_sha256=(
                "5937dbd84e5d8e5de038f08ffea5a1bb50a08475776bf2b4795914ce0eaf0331"
            ),
            archive_member="nudenet/320n.onnx",
        )
        model_path = ensure_model_asset(asset)
        self.model = onnxruntime.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        self._input_name = self.model.get_inputs()[0].name
        return self

    @staticmethod
    def _intersection_over_union(box, boxes):
        import numpy as np

        x1 = np.maximum(box[0], boxes[:, 0])
        y1 = np.maximum(box[1], boxes[:, 1])
        x2 = np.minimum(box[0] + box[2], boxes[:, 0] + boxes[:, 2])
        y2 = np.minimum(box[1] + box[3], boxes[:, 1] + boxes[:, 3])
        intersection = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
        box_area = max(0.0, box[2]) * max(0.0, box[3])
        areas = np.maximum(0.0, boxes[:, 2]) * np.maximum(0.0, boxes[:, 3])
        union = box_area + areas - intersection
        return np.divide(
            intersection,
            union,
            out=np.zeros_like(intersection),
            where=union > 0,
        )

    @classmethod
    def _non_maximum_suppression(cls, boxes, scores, threshold=0.45):
        import numpy as np

        if not len(boxes):
            return []
        boxes_array = np.asarray(boxes, dtype=np.float32)
        order = np.asarray(scores).argsort()[::-1]
        keep = []
        while order.size:
            selected = int(order[0])
            keep.append(selected)
            if order.size == 1:
                break
            remaining = order[1:]
            overlaps = cls._intersection_over_union(
                boxes_array[selected], boxes_array[remaining]
            )
            order = remaining[overlaps <= threshold]
        return keep

    @staticmethod
    def _prepare_image(image_path):
        import numpy as np
        from PIL import Image

        with Image.open(image_path) as source:
            image = source.convert("RGB")
            original_width, original_height = image.size
            padded_size = max(original_width, original_height)
            padded = Image.new("RGB", (padded_size, padded_size))
            padded.paste(image, (0, 0))
            resized = padded.resize((320, 320), Image.Resampling.BILINEAR)
            array = np.asarray(resized, dtype=np.float32) / 255.0
        return (
            np.transpose(array, (2, 0, 1)),
            original_width,
            original_height,
            padded_size,
        )

    def _postprocess(self, output, metadata):
        import numpy as np

        original_width, original_height, padded_size = metadata
        rows = np.squeeze(output)
        if rows.ndim != 2:
            return []
        if rows.shape[0] < rows.shape[1]:
            rows = rows.T

        boxes = []
        scores = []
        class_ids = []
        scale = padded_size / 320.0
        for row in rows:
            class_scores = row[4:]
            class_id = int(np.argmax(class_scores))
            score = float(class_scores[class_id])
            if score < 0.05:
                continue
            centre_x, centre_y, width, height = row[:4]
            x = max(0.0, min((centre_x - width / 2.0) * scale, original_width))
            y = max(0.0, min((centre_y - height / 2.0) * scale, original_height))
            width = max(0.0, min(width * scale, original_width - x))
            height = max(0.0, min(height * scale, original_height - y))
            boxes.append([x, y, width, height])
            scores.append(score)
            class_ids.append(class_id)

        keep = self._non_maximum_suppression(boxes, scores)
        return [
            {
                "class": self.detection_labels[class_ids[index]].upper(),
                "score": scores[index],
                "box": [int(value) for value in boxes[index]],
            }
            for index in keep
        ]

    def _normalize_detections(self, raw_detections):
        category_scores = {category.id: 0.0 for category in self.categories}
        detections = []
        for detection in raw_detections:
            category_id = str(detection.get("class", "")).lower()
            score = float(detection.get("score", 0.0)) * 100.0
            box = [int(value) for value in detection.get("box", [])]
            detections.append(
                {"category_id": category_id, "score": score, "box": box}
            )
            if category_id in category_scores:
                category_scores[category_id] = max(category_scores[category_id], score)

        nudity_score = max(category_scores.values(), default=0.0)
        return self.build_result(
            category_scores,
            nudity_score,
            nudity_score=nudity_score,
            detections=detections,
        )

    def classify(self, image_path):
        return self.classify_batch([image_path])[str(image_path)]

    def classify_batch(self, image_paths):
        if not self.loaded:
            raise RuntimeError(f"{self.display_name} has not been loaded.")
        import numpy as np

        path_texts = [str(path) for path in image_paths]
        prepared = [self._prepare_image(path) for path in path_texts]
        batch = np.stack([item[0] for item in prepared], axis=0)
        raw_output = self.model.run(None, {self._input_name: batch})[0]
        raw_results = [
            self._postprocess(raw_output[index : index + 1], item[1:])
            for index, item in enumerate(prepared)
        ]
        return {
            path: self._normalize_detections(raw_detections)
            for path, raw_detections in zip(path_texts, raw_results)
        }


class OpenNsfw2Adapter(ModelAdapter):
    id = "opennsfw2"
    display_name = "OpenNSFW2 (broad pornographic content)"
    version = "0.19.0-yahoo-weights-0.1.0"
    description = (
        "Maintained MIT-licensed Keras implementation of Yahoo Open-NSFW. It "
        "returns a broad pornographic-content probability rather than exposed "
        "body-part detections."
    )
    source_url = "https://github.com/bhky/opennsfw2"
    license_name = "MIT"
    default_nsfw_threshold = 50.0
    batch_size = 8
    asset = ModelAsset(
        model_id=id,
        version=version,
        filename="open_nsfw_weights.h5",
        sha256="14ca261f48bdd88c1eecba96a761bd1579b523adae1b749b0a4ffd8b7ed8babe",
        url=(
            "https://github.com/bhky/opennsfw2/releases/download/v0.1.0/"
            "open_nsfw_weights.h5"
        ),
    )

    def load(self):
        os.environ.setdefault("OPENNSFW2_KERAS", "tf-keras")
        try:
            import opennsfw2 as n2
        except ImportError as error:
            raise RuntimeError(
                "OpenNSFW2 is not installed. Install the pinned requirements first."
            ) from error

        weights_path = ensure_model_asset(self.asset)
        self._n2 = n2
        self.model = n2.make_open_nsfw_model(weights_path=str(weights_path))
        return self

    def classify(self, image_path):
        return self.classify_batch([image_path])[str(image_path)]

    def classify_batch(self, image_paths):
        if not self.loaded:
            raise RuntimeError(f"{self.display_name} has not been loaded.")

        import numpy as np
        from PIL import Image

        path_texts = [str(path) for path in image_paths]
        prepared = []
        for path in path_texts:
            with Image.open(path) as image:
                prepared.append(self._n2.preprocess_image(image.convert("RGB")))

        predictions = self.model(np.asarray(prepared), training=False)
        if hasattr(predictions, "numpy"):
            predictions = predictions.numpy()
        return {
            path: self.build_result({}, float(prediction[1]) * 100.0)
            for path, prediction in zip(path_texts, predictions)
        }


MODEL_REGISTRY = {
    adapter.id: adapter
    for adapter in (
        GantManMobileNetAdapter,
        NudeNet320Adapter,
        OpenNsfw2Adapter,
    )
}


def available_model_types():
    return tuple(MODEL_REGISTRY.values())


def create_model_adapter(model_id, nsfw_threshold=None):
    adapter_type = MODEL_REGISTRY.get(model_id)
    if adapter_type is None:
        adapter_type = MODEL_REGISTRY[DEFAULT_MODEL_ID]
    return adapter_type(nsfw_threshold=nsfw_threshold)
