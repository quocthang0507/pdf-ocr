"""Weights and framework caches stay in the chosen writable storage tree."""

import os
import shutil
import sys
from pathlib import Path

import pytest

from src.core.exceptions import WeightsError
from src.services.weights_manager import ModelWeightsManager

pytestmark = pytest.mark.unit

CACHE_PATHS = {
    "TORCH_HOME": "torch",
    "HF_HOME": "huggingface",
    "HF_HUB_CACHE": "huggingface/hub",
    "HUGGINGFACE_HUB_CACHE": "huggingface/hub",
    "TRANSFORMERS_CACHE": "huggingface/hub",
    "HF_XET_CACHE": "huggingface/xet",
    "HF_ASSETS_CACHE": "huggingface/assets",
    "HUGGINGFACE_ASSETS_CACHE": "huggingface/assets",
    "PADDLE_HOME": "paddle",
    "PADDLE_PDX_CACHE_HOME": "paddle/paddlex",
    "EASYOCR_MODULE_PATH": "easyocr",
}


@pytest.fixture(autouse=True)
def isolate_cache_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in CACHE_PATHS:
        monkeypatch.setenv(variable, "previous-cache")


def test_custom_path_creates_storage_and_redirects_all_caches(tmp_path: Path) -> None:
    manager = ModelWeightsManager(tmp_path / "mô hình")
    assert manager.base_path == (tmp_path / "mô hình").resolve()
    for variable, relative in CACHE_PATHS.items():
        target = manager.base_path / relative
        assert Path(os.environ[variable]) == target
        assert target.is_dir()
    for engine in ("vietocr", "paddle", "surya", "trocr", "easyocr"):
        assert manager.get_engine_weights_dir(engine).is_dir()


def test_default_uses_app_root_and_ignores_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.services.weights_manager as weights

    monkeypatch.setattr(weights, "get_app_root", lambda: tmp_path)
    monkeypatch.chdir(tmp_path.parent)
    assert ModelWeightsManager().base_path == tmp_path / "src" / "models"


@pytest.mark.parametrize("bundled_src", [True, False])
def test_portable_build_finds_bundled_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bundled_src: bool
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pdf-ocr.exe"))
    expected = tmp_path / ("src/models" if bundled_src else "models")
    expected.mkdir(parents=True)
    (expected / "offline.weights").write_bytes(b"existing weights")
    manager = ModelWeightsManager()
    assert manager.base_path == expected
    assert (expected / "offline.weights").read_bytes() == b"existing weights"


@pytest.mark.parametrize(
    "engine_id",
    [
        "../escape",
        "..\\escape",
        "/escape",
        "C:\\escape",
        "a/b",
        "",
        ".",
        "CON",
        "NUL",
        "name:stream",
    ],
)
def test_rejects_unsafe_engine_names(tmp_path: Path, engine_id: str) -> None:
    manager = ModelWeightsManager(tmp_path / "weights")
    with pytest.raises(WeightsError):
        manager.get_engine_weights_dir(engine_id)


def test_accepts_future_engine_without_core_changes(tmp_path: Path) -> None:
    manager = ModelWeightsManager(tmp_path)
    assert manager.get_engine_weights_dir("got_ocr-2") == tmp_path / "got_ocr-2"


@pytest.mark.parametrize(
    "path", ["../weights", "safe/../../escape", "safe\\..\\escape", "bad\x00path", ""]
)
def test_rejects_invalid_custom_paths_without_changing_environment(path: str) -> None:
    with pytest.raises(WeightsError):
        ModelWeightsManager(path)
    assert os.environ["TORCH_HOME"] == "previous-cache"


def test_rejects_resolved_subdirectory_outside_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "weights"
    original_resolve = Path.resolve

    def resolve_link(path: Path, strict: bool = False) -> Path:
        if path == base / "torch":
            return tmp_path / "outside"
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve_link)
    with pytest.raises(WeightsError):
        ModelWeightsManager(base)
    assert not (tmp_path / "outside").exists()
    assert os.environ["TORCH_HOME"] == "previous-cache"


def test_disk_space_reports_gib_and_enforces_download_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    usage = shutil.disk_usage(tmp_path)._replace(free=3 * 1024**3)
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage)
    manager = ModelWeightsManager(tmp_path)
    assert manager.get_free_disk_space_gb() == 3.0
    manager.ensure_disk_space(2 * 1024**3)
    with pytest.raises(WeightsError, match="dung lượng"):
        manager.ensure_disk_space(4 * 1024**3)


def test_full_disk_fails_before_environment_redirection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    usage = shutil.disk_usage(tmp_path)._replace(free=0)
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage)
    with pytest.raises(WeightsError, match="dung lượng"):
        ModelWeightsManager(tmp_path)
    assert os.environ["HF_HOME"] == "previous-cache"


def test_unwritable_directory_raises_safe_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.utils.file_utils as files

    def denied(*args: object, **kwargs: object) -> None:
        raise PermissionError("sensitive/path")

    monkeypatch.setattr(files.tempfile, "TemporaryFile", denied)
    with pytest.raises(WeightsError) as caught:
        ModelWeightsManager(tmp_path)
    assert "sensitive/path" not in str(caught.value)
    assert isinstance(caught.value.__cause__, PermissionError)
    assert os.environ["TORCH_HOME"] == "previous-cache"


def test_rejects_existing_file_as_weights_directory(tmp_path: Path) -> None:
    target = tmp_path / "model.bin"
    target.write_bytes(b"keep")
    with pytest.raises(WeightsError):
        ModelWeightsManager(target)
    assert target.read_bytes() == b"keep"


def test_reopening_storage_preserves_existing_weights(tmp_path: Path) -> None:
    manager = ModelWeightsManager(tmp_path)
    checkpoint = manager.get_engine_weights_dir("vietocr") / "model.pth"
    checkpoint.write_bytes(b"local model")
    ModelWeightsManager(tmp_path)
    assert checkpoint.read_bytes() == b"local model"


def test_invalid_disk_budget_is_rejected(tmp_path: Path) -> None:
    manager = ModelWeightsManager(tmp_path)
    with pytest.raises(ValueError):
        manager.ensure_disk_space(-1)
