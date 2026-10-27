"""Pinned OCR dependencies stay importable on current tooling."""

from __future__ import annotations

import sys

import pytest

from src.utils.compat import ensure_pkg_resources

pytestmark = pytest.mark.unit


def test_a_missing_pkg_resources_is_replaced_by_a_working_shim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gdown 4.4 (pinned by VietOCR) reads its version through pkg_resources."""
    from src.utils import compat

    real_import = compat.import_module

    def without_pkg_resources(name: str) -> object:
        if name == "pkg_resources":
            raise ImportError("removed in setuptools 81")
        return real_import(name)

    monkeypatch.delitem(sys.modules, "pkg_resources", raising=False)
    monkeypatch.setattr(compat, "import_module", without_pkg_resources)

    ensure_pkg_resources()

    shim = sys.modules["pkg_resources"]
    assert shim.get_distribution("pytest").version == pytest.__version__
    assert shim.get_distribution("no-such-package-xyz").version == "0"


def test_macos_without_trusted_roots_gets_the_certifi_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """python.org builds on macOS ship no CA roots; model downloads failed."""
    from types import SimpleNamespace

    from src.utils import compat

    monkeypatch.setattr(compat.sys, "platform", "darwin")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(
        compat.ssl,
        "get_default_verify_paths",
        lambda: SimpleNamespace(cafile=None, capath=None),
    )
    monkeypatch.setattr(
        compat,
        "import_module",
        lambda name: SimpleNamespace(where=lambda: "/certifi/cacert.pem"),
    )

    assert compat.ensure_ca_certificates() == "/certifi/cacert.pem"
    assert compat.os.environ["SSL_CERT_FILE"] == "/certifi/cacert.pem"


def test_other_platforms_and_configured_stores_are_left_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.utils import compat

    monkeypatch.setattr(compat.sys, "platform", "win32")
    assert compat.ensure_ca_certificates() is None

    monkeypatch.setattr(compat.sys, "platform", "darwin")
    monkeypatch.setenv("SSL_CERT_FILE", "/company/roots.pem")
    assert compat.ensure_ca_certificates() is None
