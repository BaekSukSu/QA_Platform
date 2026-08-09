import sys
from types import ModuleType

import pytest


def test_importing_windows_engine_on_macos_does_not_require_win32com() -> None:
    import qa_platform.extraction.windows_hwp_com_engine as module

    assert hasattr(module, "extract_hwp_content_with_pages")


def test_windows_engine_rejects_missing_file(tmp_path) -> None:
    from qa_platform.extraction.windows_hwp_com_engine import (
        extract_hwp_content_with_pages,
    )

    with pytest.raises(FileNotFoundError):
        extract_hwp_content_with_pages(tmp_path / "missing.hwp", tmp_path / "images")


def test_windows_engine_lazily_imports_win32com(monkeypatch, tmp_path) -> None:
    from qa_platform.extraction import windows_hwp_com_engine

    hwp_file = tmp_path / "sample.hwp"
    hwp_file.write_bytes(b"hwp")
    image_dir = tmp_path / "images"

    fake_win32 = ModuleType("win32com")
    fake_client = ModuleType("win32com.client")
    fake_win32.client = fake_client
    monkeypatch.setitem(sys.modules, "win32com", fake_win32)
    monkeypatch.setitem(sys.modules, "win32com.client", fake_client)

    class FakeDocumentInfo:
        CurrentPrintPage = 1

    class FakeDocuments:
        def Item(self, index):
            return type("Doc", (), {"XHwpDocumentInfo": FakeDocumentInfo()})()

    class FakeWindows:
        def Item(self, index):
            return type("Window", (), {"Visible": True})()

    class FakeHwp:
        XHwpWindows = FakeWindows()
        XHwpDocuments = FakeDocuments()
        HeadCtrl = None

        def RegisterModule(self, module_name, security_module_name):
            assert module_name == "FilePathCheckDLL"
            assert security_module_name == "SecurityModule"
            return True

        def Open(self, path, fmt, option):
            assert fmt == "HWP"
            assert option == "forceopen:true"

        def MovePos(self, pos):
            pass

        def InitScan(self):
            pass

        def GetText(self):
            if not hasattr(self, "_called"):
                self._called = True
                return 2, "hello"
            return 1, ""

        def ReleaseScan(self):
            pass

        def Quit(self):
            pass

    fake_client.gencache = type(
        "Cache",
        (),
        {"EnsureDispatch": staticmethod(lambda name: FakeHwp())},
    )()

    result = windows_hwp_com_engine.extract_hwp_content_with_pages(
        hwp_file,
        image_dir,
    )

    assert "[page : 1]" in result.text_data
    assert "hello" in result.text_data
    assert result.image_paths == []
