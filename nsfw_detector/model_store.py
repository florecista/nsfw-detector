import hashlib
import os
import shutil
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


DATA_DIRECTORY_ENVIRONMENT_VARIABLE = "NSFW_DETECTOR_DATA_DIR"
MODEL_STORE_ENVIRONMENT_VARIABLE = "NSFW_DETECTOR_MODEL_DIR"


def application_data_directory():
    configured = os.environ.get(DATA_DIRECTORY_ENVIRONMENT_VARIABLE)
    if configured:
        return Path(configured).expanduser().resolve()

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "florecista" / "NSFW Detector"

    cache_home = os.environ.get("XDG_CACHE_HOME")
    if cache_home:
        return Path(cache_home) / "nsfw-detector"

    return Path.home() / ".cache" / "nsfw-detector"


def model_store_directory():
    configured = os.environ.get(MODEL_STORE_ENVIRONMENT_VARIABLE)
    if configured:
        return Path(configured).expanduser().resolve()
    return application_data_directory() / "models"


def sha256_file(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ModelAsset:
    model_id: str
    version: str
    filename: str
    sha256: str
    url: str | None = None
    bundled_path: Path | None = None
    download_sha256: str | None = None
    archive_member: str | None = None

    @property
    def directory(self):
        return model_store_directory() / self.model_id / self.version

    @property
    def path(self):
        return self.directory / self.filename


class ModelAssetError(RuntimeError):
    pass


def validate_model_asset(path, expected_sha256):
    path = Path(path)
    return path.is_file() and sha256_file(path).lower() == expected_sha256.lower()


def ensure_model_asset(asset, progress_callback=None):
    asset.directory.mkdir(parents=True, exist_ok=True)
    target = asset.path
    if validate_model_asset(target, asset.sha256):
        return target

    if target.exists():
        target.unlink()

    temporary = target.with_suffix(f"{target.suffix}.part")
    if temporary.exists():
        temporary.unlink()
    download_path = (
        target.with_suffix(f"{target.suffix}.download")
        if asset.archive_member
        else temporary
    )
    if download_path != temporary and download_path.exists():
        download_path.unlink()

    try:
        if asset.bundled_path is not None:
            bundled_path = Path(asset.bundled_path)
            if not validate_model_asset(bundled_path, asset.sha256):
                raise ModelAssetError(
                    f"Bundled model asset failed validation: {bundled_path}"
                )
            shutil.copyfile(bundled_path, temporary)
        elif asset.url:
            request = urllib.request.Request(
                asset.url,
                headers={"User-Agent": "NSFW-Detector/1.0"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                total = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                with download_path.open("wb") as destination:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        destination.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback is not None:
                            progress_callback(downloaded, total)
            expected_download_hash = asset.download_sha256 or asset.sha256
            if not validate_model_asset(download_path, expected_download_hash):
                raise ModelAssetError(
                    f"Downloaded file failed SHA-256 validation: {asset.filename}"
                )
            if asset.archive_member:
                with zipfile.ZipFile(download_path) as archive:
                    try:
                        with archive.open(asset.archive_member) as source:
                            with temporary.open("wb") as destination:
                                shutil.copyfileobj(source, destination)
                    except KeyError as error:
                        raise ModelAssetError(
                            f"Model asset was not found in the downloaded archive: "
                            f"{asset.archive_member}"
                        ) from error
        else:
            raise ModelAssetError(f"No source is configured for {asset.model_id}.")

        if not validate_model_asset(temporary, asset.sha256):
            raise ModelAssetError(
                f"Downloaded model asset failed SHA-256 validation: {asset.filename}"
            )
        temporary.replace(target)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    finally:
        if download_path != temporary and download_path.exists():
            download_path.unlink()

    return target


def tensorflow_hub_cache_directory(model_id, version):
    path = model_store_directory() / model_id / version / "tensorflow-hub"
    path.mkdir(parents=True, exist_ok=True)
    return path


def remove_invalid_tensorflow_hub_entries(cache_directory):
    cache_directory = Path(cache_directory).resolve()
    store_root = model_store_directory().resolve()
    if store_root not in cache_directory.parents:
        raise ModelAssetError("Refusing to clean a TensorFlow Hub cache outside the model store.")

    for entry in cache_directory.iterdir():
        if not entry.is_dir():
            continue
        model_file = entry / "saved_model.pb"
        if not model_file.is_file():
            model_file = entry / "saved_model.pbtxt"
        variables_directory = entry / "variables"
        variable_files = (
            list(variables_directory.glob("variables.*"))
            if variables_directory.is_dir()
            else []
        )
        if (
            model_file.is_file()
            and model_file.stat().st_size > 0
            and variable_files
            and all(path.stat().st_size > 0 for path in variable_files)
        ):
            continue
        shutil.rmtree(entry)
