from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from nsfw_detector import predict


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_ID = "gantman-mobilenet"
DEFAULT_NSFW_THRESHOLD = 70.0


@dataclass(frozen=True)
class ModelCategory:
    id: str
    label: str
    threshold: float
    contributes_to_nsfw: bool = False


class ModelAdapter(ABC):
    id = ""
    display_name = ""
    version = ""
    description = ""
    source_url = ""
    categories = ()
    supports_regions = False

    def __init__(self, nsfw_threshold=DEFAULT_NSFW_THRESHOLD):
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

    def normalize_scores(self, raw_scores):
        scores = {
            category.id: float(raw_scores.get(category.id, 0.0))
            for category in self.categories
        }
        nsfw_score = sum(scores[category_id] for category_id in self.nsfw_category_ids)
        scores["nsfw_score"] = nsfw_score
        scores["is_nsfw"] = nsfw_score >= self.nsfw_threshold
        scores["model_id"] = self.id
        scores["model_version"] = self.version
        return scores

    def apply_threshold(self, scores):
        updated = dict(scores)
        updated["is_nsfw"] = updated["nsfw_score"] >= self.nsfw_threshold
        return updated

    def category_matches(self, scores, category_id):
        category = self.get_category(category_id)
        return scores[category_id] >= category.threshold

    def get_category(self, category_id):
        for category in self.categories:
            if category.id == category_id:
                return category
        raise KeyError(f"Unknown category for {self.id}: {category_id}")

    def primary_category(self, scores):
        if not self.categories:
            return None
        return max(self.categories, key=lambda category: scores[category.id])


class GantManMobileNetAdapter(ModelAdapter):
    id = DEFAULT_MODEL_ID
    display_name = "GantMan MobileNet (five categories)"
    version = "bundled"
    description = (
        "Fast local 224x224 classifier with Drawings, Hentai, Neutral, Porn, "
        "and Sexy categories. The NSFW score is the combined Hentai, Porn, "
        "and Sexy probability."
    )
    source_url = "https://github.com/GantMan/nsfw_model"
    model_path = PROJECT_DIR / "nsfw_detector" / "nsfw_model.h5"
    categories = (
        ModelCategory("drawings", "Drawings", 40.0),
        ModelCategory("hentai", "Hentai", 70.0, contributes_to_nsfw=True),
        ModelCategory("neutral", "Neutral", 25.0),
        ModelCategory("porn", "Porn", 70.0, contributes_to_nsfw=True),
        ModelCategory("sexy", "Sexy", 70.0, contributes_to_nsfw=True),
    )

    def load(self):
        self.model = predict.load_model(str(self.model_path))
        return self

    def classify(self, image_path):
        if not self.loaded:
            raise RuntimeError(f"{self.display_name} has not been loaded.")
        result = predict.classify(self.model, str(image_path))
        raw_scores = result.get("data")
        if not isinstance(raw_scores, dict):
            raise ValueError("The model did not return scores for this image.")
        return self.normalize_scores(raw_scores)


MODEL_REGISTRY = {
    GantManMobileNetAdapter.id: GantManMobileNetAdapter,
}


def available_model_types():
    return tuple(MODEL_REGISTRY.values())


def create_model_adapter(model_id, nsfw_threshold=DEFAULT_NSFW_THRESHOLD):
    adapter_type = MODEL_REGISTRY.get(model_id)
    if adapter_type is None:
        adapter_type = MODEL_REGISTRY[DEFAULT_MODEL_ID]
    return adapter_type(nsfw_threshold=nsfw_threshold)
