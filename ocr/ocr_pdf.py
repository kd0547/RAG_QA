import argparse
import hashlib
import io
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pymupdf  # pip install pymupdf
from PIL import Image, ImageOps, ImageSequence  # pip install pillow
from langchain_openai import ChatOpenAI

import config
from agent.llm_provider import get_llm_model, set_local_model

from ocr.llm_ocr import OCR_PROMPT, ocr_image_with_meta as llm_ocr_with_meta
from ocr.provider import get_ocr_backend


# 지원하는 입력 형식
PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
SUPPORTED_EXTS = PDF_EXTS | IMAGE_EXTS

# 작은 이미지 확대 설정 (이미지 파일에만 적용, PDF는 DPI로 조절)
# 긴 변이 UPSCALE_BELOW px 미만이면 UPSCALE_FACTOR배로 키운다. FACTOR=1이면 확대 안 함.
UPSCALE_BELOW = 1000
UPSCALE_FACTOR = 2.0

def ocr_image(image_bytes: bytes, prompt: str = OCR_PROMPT, llm=None) -> str:
    text, _ = ocr_image_with_meta(image_bytes, prompt, llm)
    return text


def ocr_image_with_meta(image_bytes: bytes, prompt: str = OCR_PROMPT, llm=None) -> tuple[str, dict]:
    # 명시적으로 전달한 LLM은 기존 호출과 호환한다.
    backend = get_ocr_backend("llm" if llm is not None else None)
    if backend.name == "llm":
        if llm is None:
            llm = _get_cli_llm()
        return llm_ocr_with_meta(image_bytes, prompt, llm)
    return backend.ocr_image(image_bytes), {}


def _get_cli_llm():
    try:
        return get_llm_model(mode="local")
    except RuntimeError:
        llm = ChatOpenAI(model=config.LLM_MODEL, base_url=config.LLM_BASE_URL,
                         api_key=config.VLLM_API_KEY, timeout=300, max_retries=0)
        set_local_model(llm)
        return llm


# ---------------------------------------------------------------------------
# 입력 파일 → 페이지 목록
# 각 페이지: {"image": PNG 바이트, "original_size": (w, h), "size": (w, h)}
# ---------------------------------------------------------------------------

def pdf_to_pages(pdf_path: str | Path, dpi: int = 200) -> list[dict]:
    """PDF 각 페이지를 PNG로 렌더링한다."""
    pages = []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            size = (pix.width, pix.height)
            pages.append({"image": pix.tobytes("png"), "original_size": size, "size": size})
    return pages


def _normalize_image(
    img: Image.Image,
    upscale_below: int = UPSCALE_BELOW,
    upscale_factor: float = UPSCALE_FACTOR,
) -> dict:
    """모델 입력용으로 이미지를 정리해 PNG로 반환한다.

    - 휴대폰 사진의 EXIF 회전 정보를 실제 픽셀에 반영 (안 하면 옆으로 누운 채 들어감)
    - 투명 배경은 흰색으로 채움 (그냥 RGB로 바꾸면 검은 배경이 되어 글자가 안 보일 수 있음)
    - 작은 이미지는 확대 (가는 글씨를 다른 단어로 잘못 읽는 오류 완화)
    """
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.getchannel("A"))
        img = background
    else:
        img = img.convert("RGB")

    original_size = img.size
    if upscale_factor > 1 and max(img.size) < upscale_below:
        new_size = (round(img.width * upscale_factor), round(img.height * upscale_factor))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"image": buf.getvalue(), "original_size": original_size, "size": img.size}


def image_to_pages(image_path: str | Path, **upscale) -> list[dict]:
    """이미지 파일을 페이지 목록으로 변환한다. 다중 페이지 TIFF는 프레임마다 한 페이지."""
    image_path = Path(image_path)
    with Image.open(image_path) as img:
        if image_path.suffix.lower() in (".tif", ".tiff"):
            return [_normalize_image(frame.copy(), **upscale) for frame in ImageSequence.Iterator(img)]
        return [_normalize_image(img, **upscale)]  # GIF 등은 첫 프레임만 사용


def load_pages(
    path: str | Path,
    dpi: int = 200,
    upscale_below: int = UPSCALE_BELOW,
    upscale_factor: float = UPSCALE_FACTOR,
) -> list[dict]:
    """확장자에 따라 PDF 또는 이미지 파일을 페이지 목록으로 변환한다."""
    suffix = Path(path).suffix.lower()
    if suffix in PDF_EXTS:
        return pdf_to_pages(path, dpi=dpi)
    if suffix in IMAGE_EXTS:
        return image_to_pages(path, upscale_below=upscale_below, upscale_factor=upscale_factor)
    raise ValueError(f"지원하지 않는 형식입니다: {suffix} (지원: {', '.join(sorted(SUPPORTED_EXTS))})")


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def run_ocr(
    file_path: str | Path,
    dpi: int = 200,
    upscale_below: int = UPSCALE_BELOW,
    upscale_factor: float = UPSCALE_FACTOR,
    prompt: str = OCR_PROMPT,
    out_dir: str | Path = "ocr_results",
    llm=None,
) -> list[dict]:
    """PDF 또는 이미지 파일 하나를 페이지 단위로 OCR하고, 결과와 처리 시간을 파일로 남긴다.

    출력 구조:
        ocr_results/<파일 이름>_<확장자>/
            page_001.png   # 모델에 실제로 넣은 이미지 (확대된 경우 확대본)
            page_001.txt   # 페이지별 OCR 결과
            result.md      # 전체 페이지 합본
            summary.json   # 실행 설정, 페이지별 크기·소요 시간·글자 수·토큰·에러
    """
    file_path = Path(file_path)
    # 이름이 같고 확장자만 다른 파일(a.pdf, a.jpg)이 서로 덮어쓰지 않도록 확장자를 폴더명에 포함
    out = Path(out_dir) / f"{file_path.stem}_{file_path.suffix.lstrip('.').lower()}"
    out.mkdir(parents=True, exist_ok=True)

    pages = load_pages(file_path, dpi=dpi, upscale_below=upscale_below, upscale_factor=upscale_factor)
    kind = "PDF" if file_path.suffix.lower() in PDF_EXTS else "이미지"
    print(f"[{file_path.name}] {kind}, {len(pages)}페이지" + (f", DPI {dpi}" if kind == "PDF" else ""))

    results, texts = [], []
    for i, page in enumerate(pages, start=1):
        name = f"page_{i:03d}"
        image_bytes = page["image"]
        (out / f"{name}.png").write_bytes(image_bytes)
        upscaled = page["size"] != page["original_size"]

        start = time.perf_counter()
        try:
            text, usage = ocr_image_with_meta(image_bytes, prompt, llm)
            error = None
        except Exception as e:  # 한 페이지 실패해도 나머지는 계속 진행
            text, usage, error = "", {}, f"{type(e).__name__}: {e}"
        elapsed = time.perf_counter() - start

        (out / f"{name}.txt").write_text(text, encoding="utf-8")
        texts.append(f"<!-- page {i} -->\n{text}")
        results.append({
            "page": i,
            "original_size": list(page["original_size"]),
            "size": list(page["size"]),
            "upscaled": upscaled,
            "elapsed_sec": round(elapsed, 2),
            "chars": len(text),
            "usage": usage,
            "error": error,
        })

        w0, h0 = page["original_size"]
        w, h = page["size"]
        size_info = f"{w0}x{h0} → {w}x{h}" if upscaled else f"{w}x{h}"
        status = f"오류: {error}" if error else f"{len(text)}자"
        print(f"  page {i}: {size_info}, {elapsed:.1f}s, {status}")

    (out / "result.md").write_text("\n\n".join(texts), encoding="utf-8")
    summary = {
        "source": file_path.name,
        "source_sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
        "backend": "llm" if llm is not None else get_ocr_backend().name,
        "type": kind,
        "dpi": dpi if kind == "PDF" else None,
        "upscale": None if kind == "PDF" else {"below": upscale_below, "factor": upscale_factor},
        "prompt": prompt if llm is not None or get_ocr_backend().name == "llm" else None,
        "model": config.LLM_MODEL if llm is not None or get_ocr_backend().name == "llm" else "PaddleOCR-VL-1.6",
        "run_at": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
        "total_sec": round(sum(r["elapsed_sec"] for r in results), 2),
        "pages": results,
    }
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"완료: 총 {summary['total_sec']}s → {out}")
    return results


def run_ocr_path(path: str | Path, out_dir: str | Path = "ocr_results", **options) -> bool:
    """파일이면 그 파일만, 폴더면 안의 PDF·이미지 파일을 모두 OCR한다."""
    path = Path(path)
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix.lower() in SUPPORTED_EXTS)
        if not files:
            print(f"OCR할 파일이 없습니다: {path}")
            return False
        print(f"{len(files)}개 파일 처리 시작")
        success = True
        for f in files:
            try:
                results = run_ocr(f, out_dir=out_dir, **options)
                success = bool(results) and all(r["error"] is None for r in results) and success
            except Exception as e:  # 파일 하나가 깨져 있어도 나머지는 계속
                success = False
                print(f"[{f.name}] 건너뜀: {type(e).__name__}: {e}")
        return success
    else:
        results = run_ocr(path, out_dir=out_dir, **options)
        return bool(results) and all(r["error"] is None for r in results)


if __name__ == "__main__":
    # 사용 예:
    #   python ocr_pdf.py 시험성적서.pdf                     → PDF
    #   python ocr_pdf.py 사진.jpg                           → 이미지 (작으면 2배 확대)
    #   python ocr_pdf.py samples                            → 폴더 안의 PDF·이미지 전부
    #   python ocr_pdf.py samples --upscale-factor 1 --out ocr_results_x1   → 확대 없이 (비교용)
    parser = argparse.ArgumentParser(description="PDF·이미지 OCR")
    parser.add_argument("path", nargs="?", default="시험성적서(LME186-A701).pdf",
                        help="PDF·이미지 파일 또는 폴더")
    parser.add_argument("--dpi", type=int, default=200, help="PDF 렌더링 DPI (기본 200)")
    parser.add_argument("--upscale-below", type=int, default=UPSCALE_BELOW,
                        help=f"긴 변이 이 값(px) 미만인 이미지를 확대 (기본 {UPSCALE_BELOW})")
    parser.add_argument("--upscale-factor", type=float, default=UPSCALE_FACTOR,
                        help=f"확대 배율, 1이면 확대 안 함 (기본 {UPSCALE_FACTOR})")
    parser.add_argument("--out", default="ocr_results", help="결과 폴더 (기본 ocr_results)")
    args = parser.parse_args()

    success = run_ocr_path(
        args.path,
        out_dir=args.out,
        dpi=args.dpi,
        upscale_below=args.upscale_below,
        upscale_factor=args.upscale_factor,
    )
    raise SystemExit(0 if success else 1)
