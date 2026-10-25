"""Settings apply weights storage, execution device, and processing options."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from src.config import ConfigManager, Preferences
from src.core.exceptions import WeightsError
from src.gui.components.settings_dock import SettingsDock
from src.gui.dialogs.settings_dialog import SettingsDialog
from src.services import device_service
from src.services.device_service import detect_devices, resolve_device
from src.services.weights_manager import ModelWeightsManager, migrate_weights

pytestmark = pytest.mark.gui


@pytest.fixture
def weights_dir(tmp_path: Path) -> Path:
    source = tmp_path / "models"
    (source / "vietocr").mkdir(parents=True)
    (source / "vietocr" / "transformer.pth").write_bytes(b"trong so mo hinh" * 64)
    (source / "paddle").mkdir()
    (source / "paddle" / "det.bin").write_bytes(b"paddle" * 32)
    return source


@pytest.fixture
def config(tmp_path: Path) -> ConfigManager:
    return ConfigManager(tmp_path / "config", use_qsettings=False)


@pytest.fixture
def dialog(qtbot, config: ConfigManager, weights_dir: Path) -> SettingsDialog:
    config.save(Preferences(weights_dir=str(weights_dir)))
    widget = SettingsDialog(config=config)
    qtbot.addWidget(widget)
    return widget


# -- device discovery -------------------------------------------------------


def test_cpu_is_always_offered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device_service, "_load_torch", lambda: None)

    identifiers = {device.identifier for device in detect_devices()}

    assert {"auto", "cpu"} <= identifiers


def test_cuda_is_reported_unavailable_without_torch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(device_service, "_load_torch", lambda: None)

    cuda = next(item for item in detect_devices() if item.identifier == "cuda")

    assert cuda.available is False
    assert resolve_device("auto") == "cpu"


def test_cuda_reports_its_name_and_memory_when_present(
    monkeypatch: pytest.MonkeyPatch, fake_torch: object
) -> None:
    monkeypatch.setattr(device_service, "_load_torch", lambda: fake_torch)

    cuda = next(item for item in detect_devices() if item.identifier == "cuda")

    assert cuda.available is True
    assert cuda.name == "NVIDIA RTX 4090"
    assert cuda.total_memory_gb == pytest.approx(24.0, rel=1e-3)
    assert resolve_device("auto") == "cuda"


def test_an_explicit_choice_is_never_overridden(
    monkeypatch: pytest.MonkeyPatch, fake_torch: object
) -> None:
    monkeypatch.setattr(device_service, "_load_torch", lambda: fake_torch)

    assert resolve_device("cpu") == "cpu"


def test_a_broken_accelerator_library_degrades_to_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Exploding:
        @property
        def cuda(self) -> object:
            raise RuntimeError("driver mismatch")

    monkeypatch.setattr(device_service, "_load_torch", Exploding)

    assert resolve_device("auto") == "cpu"


@pytest.fixture
def fake_torch() -> object:
    class Properties:
        name = "NVIDIA RTX 4090"
        total_memory = 24 * 1024**3

    class Cuda:
        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def get_device_properties(index: int) -> Properties:
            return Properties()

    class Torch:
        cuda = Cuda()

    return Torch()


# -- weights migration ------------------------------------------------------


def test_migration_copies_every_weight_file(weights_dir: Path, tmp_path: Path) -> None:
    destination = tmp_path / "ổ ngoài" / "models"

    migrate_weights(weights_dir, destination)

    assert (destination / "vietocr" / "transformer.pth").read_bytes() == (
        b"trong so mo hinh" * 64
    )
    assert (destination / "paddle" / "det.bin").is_file()


def test_migration_reports_progress_up_to_completion(
    weights_dir: Path, tmp_path: Path
) -> None:
    reported: list[int] = []

    migrate_weights(weights_dir, tmp_path / "đích", on_progress=reported.append)

    assert reported[-1] == 100
    assert reported == sorted(reported)


def test_migration_removes_the_source_only_after_a_full_copy(
    weights_dir: Path, tmp_path: Path
) -> None:
    migrate_weights(weights_dir, tmp_path / "đích")

    assert list(weights_dir.rglob("*.pth")) == []


def test_cancelled_migration_leaves_the_original_weights_untouched(
    weights_dir: Path, tmp_path: Path
) -> None:
    destination = tmp_path / "đích"

    with pytest.raises(WeightsError, match="hủy"):
        migrate_weights(weights_dir, destination, should_cancel=lambda: True)

    assert (weights_dir / "vietocr" / "transformer.pth").is_file()
    assert not destination.exists()


def test_migration_into_the_source_itself_is_refused(weights_dir: Path) -> None:
    with pytest.raises(WeightsError):
        migrate_weights(weights_dir, weights_dir / "bên trong")


def test_migration_refuses_a_destination_without_room(
    weights_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.services.weights_manager as weights_manager

    class Usage:
        free = 1

    monkeypatch.setattr(weights_manager.shutil, "disk_usage", lambda _p: Usage())

    with pytest.raises(WeightsError, match="dung lượng"):
        migrate_weights(weights_dir, tmp_path / "đích")


# -- settings dialog --------------------------------------------------------


def test_dialog_opens_on_the_saved_preferences(
    dialog: SettingsDialog, weights_dir: Path
) -> None:
    assert dialog.weights_edit.text() == str(weights_dir)
    assert dialog.device_combo.currentData() == "auto"


def test_dialog_shows_free_space_for_the_chosen_folder(
    dialog: SettingsDialog,
) -> None:
    assert "GB" in dialog.free_space_label.text()


def test_browsing_updates_the_weights_folder(
    dialog: SettingsDialog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chosen = tmp_path / "thư mục mới"
    chosen.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **k: str(chosen)
    )

    dialog.browse_weights_dir()

    assert dialog.weights_edit.text() == str(chosen)


def test_a_traversing_path_is_refused_before_saving(
    dialog: SettingsDialog, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda _p, _t, text, *a, **k: shown.append(text)
    )
    dialog.weights_edit.setText("../../etc")

    dialog.accept()

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert shown


def test_accepting_persists_every_choice(
    dialog: SettingsDialog, config: ConfigManager, tmp_path: Path
) -> None:
    output = tmp_path / "ket qua"
    output.mkdir()
    dialog.output_edit.setText(str(output))
    dialog.device_combo.setCurrentIndex(dialog.device_combo.findData("cpu"))

    dialog.accept()

    stored = config.load()
    assert stored.device == "cpu"
    assert stored.output_dir == str(output)


def test_accepting_applies_the_weights_folder_to_the_manager(
    dialog: SettingsDialog, tmp_path: Path, qtbot
) -> None:
    chosen = tmp_path / "kho weights"
    chosen.mkdir()
    dialog.weights_edit.setText(str(chosen))

    with qtbot.waitSignal(dialog.weights_directory_changed) as blocker:
        dialog.accept()

    assert blocker.args == [str(chosen)]
    assert ModelWeightsManager(chosen).base_path == chosen.resolve()


def test_moving_weights_runs_off_the_gui_thread_and_finishes(
    dialog: SettingsDialog, qtbot, tmp_path: Path
) -> None:
    destination = tmp_path / "kho mới"
    dialog.weights_edit.setText(str(destination))

    with qtbot.waitSignal(dialog.migration_finished, timeout=15000) as blocker:
        dialog.start_weights_migration()

    assert blocker.args == [str(destination)]
    assert dialog.progress_bar.value() == 100
    assert (destination / "vietocr" / "transformer.pth").is_file()


def test_a_failed_move_is_reported_without_technical_detail(
    dialog: SettingsDialog, qtbot, weights_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    dialog.weights_edit.setText(str(weights_dir / "bên trong"))

    with qtbot.waitSignal(dialog.migration_failed, timeout=15000) as blocker:
        dialog.start_weights_migration()

    assert "Traceback" not in blocker.args[0]


def test_dialog_exposes_six_comprehensive_configuration_categories(
    dialog: SettingsDialog,
) -> None:
    assert dialog.category_tabs.count() == 6
    titles = [
        dialog.category_tabs.tabText(i) for i in range(dialog.category_tabs.count())
    ]
    assert titles == [
        "Chung và Giao diện",
        "Xem PDF",
        "OCR và Tiền xử lý",
        "Từ điển và Chính tả",
        "Xuất tệp và PDF",
        "Hiệu năng và AI",
    ]


def test_dialog_persists_all_six_category_options(
    dialog: SettingsDialog, config: ConfigManager
) -> None:
    dialog.restore_session_check.setChecked(False)
    dialog.confirm_delete_check.setChecked(False)
    dialog.zoom_mode_combo.setCurrentIndex(dialog.zoom_mode_combo.findData("fit_width"))
    dialog.color_mode_combo.setCurrentIndex(dialog.color_mode_combo.findData("sepia"))
    dialog.thumbnails_check.setChecked(False)
    dialog.cache_pages_spin.setValue(6)
    dialog.default_dpi_spin.setValue(400)
    dialog.auto_ocr_check.setChecked(True)
    dialog.deskew_check.setChecked(False)
    dialog.spell_correction_check.setChecked(False)
    dialog.confidence_spin.setValue(0.75)
    dialog.custom_dict_edit.setPlainText("UBND, Bộ Tài chính")
    dialog.export_format_combo.setCurrentIndex(
        dialog.export_format_combo.findData("pdf")
    )
    dialog.compression_combo.setCurrentIndex(dialog.compression_combo.findData("max"))
    dialog.worker_threads_spin.setValue(8)

    dialog.accept()

    saved = config.load()
    assert saved.restore_session is False
    assert saved.confirm_page_delete is False
    assert saved.default_zoom_mode == "fit_width"
    assert saved.page_color_mode == "sepia"
    assert saved.show_thumbnails is False
    assert saved.cache_size_pages == 6
    assert saved.default_dpi == 400
    assert saved.auto_ocr_on_open is True
    assert saved.default_deskew is False
    assert saved.auto_spell_correction is False
    assert saved.confidence_threshold == pytest.approx(0.75)
    assert saved.custom_dictionary == "UBND, Bộ Tài chính"
    assert saved.default_export_format == "pdf"
    assert saved.pdf_compression_level == "max"
    assert saved.max_worker_threads == 8


def test_dialog_exports_and_imports_profile_json(
    dialog: SettingsDialog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_file = tmp_path / "profile.json"
    dialog.color_mode_combo.setCurrentIndex(dialog.color_mode_combo.findData("night"))
    dialog.default_dpi_spin.setValue(450)
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(profile_file), "JSON")
    )
    dialog.export_profile_to_file()
    assert profile_file.is_file()

    # Reset UI controls then import profile back
    dialog.color_mode_combo.setCurrentIndex(dialog.color_mode_combo.findData("normal"))
    dialog.default_dpi_spin.setValue(200)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *a, **k: (str(profile_file), "JSON")
    )
    dialog.import_profile_from_file()

    assert dialog.color_mode_combo.currentData() == "night"
    assert dialog.default_dpi_spin.value() == 450


# -- settings dock ----------------------------------------------------------


@pytest.fixture
def dock(qtbot) -> SettingsDock:
    widget = SettingsDock()
    qtbot.addWidget(widget)
    return widget


def test_dock_lists_the_registered_ocr_engines(dock: SettingsDock) -> None:
    engines = {dock.engine_combo.itemData(i) for i in range(dock.engine_combo.count())}

    assert "vietocr" in engines


def test_dock_publishes_the_current_processing_options(
    dock: SettingsDock, qtbot
) -> None:
    with qtbot.waitSignal(dock.options_changed) as blocker:
        dock.dpi_spin.setValue(400)

    options = blocker.args[0]
    assert options["dpi"] == 400
    assert options["engine_id"] == dock.engine_combo.currentData()


def test_dock_exposes_the_tunable_parameters_of_the_chosen_model(
    dock: SettingsDock, qtbot
) -> None:
    dock.engine_combo.setCurrentIndex(dock.engine_combo.findData("paddle"))
    threshold = dock.param_widgets["paddle"]["det_db_thresh"]

    with qtbot.waitSignal(dock.options_changed) as blocker:
        threshold.setValue(0.5)

    assert blocker.args[0]["engine_params"] == {"lang": "vi", "det_db_thresh": 0.5}
    assert threshold.isVisibleTo(dock) is True
    assert dock.param_widgets["surya"]["langs"].isVisibleTo(dock) is False


def test_dock_resets_model_parameters_to_their_defaults(dock: SettingsDock) -> None:
    dock.engine_combo.setCurrentIndex(dock.engine_combo.findData("paddle"))
    dock.param_widgets["paddle"]["det_db_thresh"].setValue(0.7)

    dock.param_reset_button.click()

    assert dock.engine_params()["det_db_thresh"] == pytest.approx(0.3)


def test_every_exposed_parameter_is_accepted_by_its_engine() -> None:
    from src.engines.engine_registry import EngineRegistry
    from src.gui.components.settings_dock import ENGINE_PARAMETERS

    for engine_id, parameters in ENGINE_PARAMETERS.items():
        engine = EngineRegistry.get(
            engine_id, config={p.key: p.default for p in parameters}
        )
        assert engine is not None


def test_dock_toggles_each_preprocessing_stage(dock: SettingsDock, qtbot) -> None:
    with qtbot.waitSignal(dock.options_changed) as blocker:
        dock.preprocessing_boxes["deskew"].setChecked(False)

    assert blocker.args[0]["preprocessing"]["deskew"] is False
    assert blocker.args[0]["preprocessing"]["enhance"] is True


def test_dock_rejects_a_dpi_outside_the_supported_range(dock: SettingsDock) -> None:
    dock.dpi_spin.setValue(10_000)

    assert dock.dpi_spin.value() <= dock.dpi_spin.maximum()
    assert dock.options()["dpi"] == dock.dpi_spin.maximum()


def test_preferences_apply_live_to_settings_dock_and_main_window(
    qtbot, tmp_path: Path
) -> None:
    from PySide6.QtCore import QSettings

    from src.gui.main_window import MainWindow
    from src.gui.window_helpers import apply_preferences_to_window

    store = QSettings(str(tmp_path / "live_prefs.ini"), QSettings.Format.IniFormat)
    store.setFallbacksEnabled(False)
    window = MainWindow(settings=store)
    qtbot.addWidget(window)

    prefs = Preferences(
        default_engine="paddle",
        default_dpi=450,
        device="cpu",
        default_deskew=False,
        default_denoise=False,
        default_binarize=False,
        auto_spell_correction=False,
        page_color_mode="sepia",
        show_thumbnails=False,
        cache_size_pages=6,
        default_zoom_mode="fit_width",
    )
    apply_preferences_to_window(window, prefs)

    opts = window.ocr_options()
    assert opts["engine_id"] == "paddle"
    assert opts["dpi"] == 450
    assert opts["device"] == "cpu"
    assert opts["preprocessing"]["deskew"] is False
    assert opts["preprocessing"]["enhance"] is False
    assert opts["spell_check"] is False
    assert window.navigation_dock.reading_mode_combo.currentData() == "sepia"
    assert window.navigation_dock._show_thumbnails is False


def test_dock_drop_downs_follow_the_panel_width(dock: SettingsDock) -> None:
    """Long model names must not push the options past the panel's right edge."""
    from PySide6.QtWidgets import QComboBox, QSizePolicy

    combos = dock.findChildren(QComboBox)
    assert combos
    for combo in combos:
        assert (
            combo.sizeAdjustPolicy()
            == QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        assert combo.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
        if combo.count():
            popup = combo.view()
            assert popup.minimumWidth() >= popup.sizeHintForColumn(0)
