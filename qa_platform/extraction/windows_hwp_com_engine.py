from __future__ import annotations

from pathlib import Path
import time

from qa_platform.extraction.models import DocumentExtractionResult


def extract_hwp_content_with_pages(
    hwp_path: Path,
    output_img_dir: Path,
    *,
    security_module_name: str = "SecurityModule",
) -> DocumentExtractionResult:
    hwp_path = Path(hwp_path)
    output_img_dir = Path(output_img_dir)
    output_img_dir.mkdir(parents=True, exist_ok=True)

    if not hwp_path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {hwp_path}")

    try:
        import win32com.client as win32
        from PIL import ImageGrab
    except ImportError as exc:
        raise RuntimeError(
            "Windows HWP COM extraction requires pywin32 and Pillow on Windows."
        ) from exc

    hwp = win32.gencache.EnsureDispatch("HWPFrame.HwpObject")
    hwp.XHwpWindows.Item(0).Visible = False
    hwp.RegisterModule("FilePathCheckDLL", security_module_name)
    hwp.Open(str(hwp_path.resolve()), "HWP", "forceopen:true")

    full_text = ""
    image_paths: list[Path] = []

    hwp.MovePos(2)
    hwp.InitScan()
    current_page_tracker = 0

    while True:
        state, text_chunk = hwp.GetText()
        if state <= 1:
            break
        hwp.MovePos(201)
        page = hwp.XHwpDocuments.Item(0).XHwpDocumentInfo.CurrentPrintPage
        if page != current_page_tracker and page > 0:
            current_page_tracker = page
            full_text += f"\n\n[page : {current_page_tracker}]\n"
        full_text += text_chunk

    hwp.ReleaseScan()

    ctrl = hwp.HeadCtrl
    global_image_index = 1
    while ctrl is not None:
        if ctrl.CtrlID == "gso":
            hwp.SetPosBySet(ctrl.GetAnchorPos(0))
            current_page = hwp.XHwpDocuments.Item(0).XHwpDocumentInfo.CurrentPrintPage
            image_path = output_img_dir / f"{global_image_index}_{current_page}.bmp"
            hwp.FindCtrl()
            hwp.Run("Copy")
            time.sleep(0.1)
            image = ImageGrab.grabclipboard()
            if image is not None:
                if image.mode in ("RGBA", "LA", "P"):
                    image = image.convert("RGB")
                image.save(image_path, "BMP")
                image_paths.append(image_path)
                global_image_index += 1
        ctrl = ctrl.Next

    hwp.Quit()
    return DocumentExtractionResult(text_data=full_text, image_paths=image_paths)
