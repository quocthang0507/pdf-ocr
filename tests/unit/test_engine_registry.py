"""OCR providers are discoverable, lazy, validated, and safely released."""

from pathlib import Path

import pytest

from src.core.exceptions import OCREngineError
from src.core.models import OCRPage
from src.engines.base_engine import BaseOCREngine, ConfigField
from src.engines.engine_registry import EngineRegistry, engine_session
from src.services.weights_manager import ModelWeightsManager

pytestmark = pytest.mark.unit


class DemoEngine(BaseOCREngine):
    CONFIG_SCHEMA = {
        "device": ConfigField("cpu", lambda value: value in {"cpu", "cuda"}),
        "beam_width": ConfigField(
            1, lambda value: type(value) is int and 1 <= value <= 10
        ),
    }

    def __init__(
        self, *args: object, fail_load: bool = False, **kwargs: object
    ) -> None:
        self.load_count = 0
        self.unload_count = 0
        self.fail_load = fail_load
        super().__init__(*args, **kwargs)

    def _load_model(self) -> None:
        self.load_count += 1
        if self.fail_load:
            raise RuntimeError("secret backend detail")

    def _recognize(self, image: object, page_number: int) -> OCRPage:
        return OCRPage(page_number=page_number, width=20, height=10)

    def _unload_model(self) -> None:
        self.unload_count += 1


@pytest.fixture(autouse=True)
def preserve_registry() -> None:
    snapshot = EngineRegistry.snapshot()
    yield
    EngineRegistry.restore(snapshot)


def test_decorator_registration_supports_future_provider_without_core_edits() -> None:
    EngineRegistry.unregister("future_test", missing_ok=True)

    @EngineRegistry.register(
        engine_id="future_test",
        name="Future OCR",
        description="A test provider",
        supports_handwriting=True,
        supports_tables=False,
    )
    class FutureEngine(DemoEngine):
        pass

    metadata = EngineRegistry.describe("future_test")
    assert metadata.name == "Future OCR"
    assert metadata.supports_handwriting
    assert EngineRegistry.get_class("future_test") is FutureEngine


def test_engine_creation_is_lazy_and_configuration_is_validated(tmp_path: Path) -> None:
    EngineRegistry.unregister("lazy_test", missing_ok=True)
    EngineRegistry.register("lazy_test", "Lazy", "Lazy engine")(DemoEngine)
    manager = ModelWeightsManager(tmp_path)

    engine = EngineRegistry.get(
        "lazy_test", weights_manager=manager, config={"beam_width": 4}
    )
    assert engine.load_count == 0
    assert engine.config == {"device": "cpu", "beam_width": 4}
    assert engine.weights_dir == tmp_path / "lazy_test"

    with pytest.raises(OCREngineError, match="beam_width"):
        EngineRegistry.get(
            "lazy_test", weights_manager=manager, config={"beam_width": 0}
        )
    with pytest.raises(OCREngineError, match="không hỗ trợ"):
        EngineRegistry.get("lazy_test", config={"unknown": True})


def test_engine_wraps_load_failures_without_leaking_backend_details() -> None:
    engine = DemoEngine(fail_load=True)
    with pytest.raises(OCREngineError) as caught:
        engine.load_model()
    assert "secret backend detail" not in str(caught.value)
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert not engine.is_loaded


def test_engine_session_unloads_after_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    EngineRegistry.unregister("session_test", missing_ok=True)
    EngineRegistry.register("session_test", "Session", "Lifecycle")(DemoEngine)
    released: list[str] = []
    monkeypatch.setattr(
        "src.engines.engine_registry.release_accelerator_memory",
        lambda device: released.append(device),
    )

    with engine_session("session_test", device="cuda") as engine:
        assert engine.is_loaded
        assert engine.recognize(object()).page_number == 1
    assert engine.unload_count == 1
    assert not engine.is_loaded
    assert released == ["cuda"]

    with pytest.raises(RuntimeError, match="caller failure"):
        with engine_session("session_test", device="cuda") as failed_engine:
            raise RuntimeError("caller failure")
    assert failed_engine.unload_count == 1
    assert released == ["cuda", "cuda"]


def test_unloaded_engine_rejects_recognition() -> None:
    with pytest.raises(OCREngineError, match="chưa được nạp"):
        DemoEngine().recognize(object())
