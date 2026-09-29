import sys
import traceback

sys.path.insert(0, r"d:\GitHub\pdf-ocr")

from src.services.pipeline_service import PipelineService

PATH = r"C:\Users\quoct\Downloads\1039-KH-ĐHĐL- Chào mừng 50 năm Trường ĐHĐL đổi mới và phát triển (1976-2026).pdf"

service = PipelineService()
with service.open_page_session(engine_id="vietocr", device="cpu", dpi=300) as session:
    try:
        pages = session.page_count(PATH)
        print("page_count:", pages)
    except Exception:
        print("FAILED to get page_count")
        traceback.print_exc()
        sys.exit(1)

    for number in range(1, pages + 1):
        print(f"--- page {number} ---")
        try:
            page = session.recognise(PATH, number)
            print("OK, blocks:", len(page.blocks))
        except Exception as error:
            print("ERROR:", type(error).__name__, error)
            traceback.print_exc()
