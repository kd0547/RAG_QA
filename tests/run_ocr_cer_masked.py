"""기존 1~16쪽 결과를 재사용하고 사진 내부를 가린 17~21쪽을 실측한다.

원본 파일과 기존 결과를 변경하지 않는다. 실행에는 LLM 서버/로컬 Paddle가 필요하다.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 원본 150 DPI 렌더(1241x1755)에서 직접 확인한 사진 사각형. 캡션은 남긴다.
PHOTO_BOXES = {
    17: [(210, 179, 1024, 744), (210, 800, 1025, 1342)],
    18: [(212, 214, 1025, 719), (212, 845, 1025, 1308)],
    19: [(227, 237, 974, 800), (227, 844, 975, 1412)],
    20: [(224, 217, 971, 780), (224, 824, 973, 1392)],
    21: [(210, 176, 1021, 740)],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["vlm", "llm", "llm_text"], required=True)
    args = parser.parse_args()
    from PIL import Image, ImageDraw
    import config
    from ocr.ocr_pdf import pdf_to_pages, _get_cli_llm
    from ocr.llm_ocr import OCR_PROMPT, ocr_image_with_meta
    from ocr.provider import get_ocr_backend, close_ocr_backends
    from run_ocr_transcription import TRANSCRIPTION_PROMPT

    source = next((ROOT / "tests/data").glob("KC*.pdf"))
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    stem = f"{source.stem}_pdf"
    previous = {
        "vlm": ROOT / "markdown/ocr_comparison/vlm_pdf_final" / stem,
        "llm": ROOT / "markdown/ocr_comparison/llm_pdf" / stem,
        "llm_text": ROOT / "markdown/ocr_cer/llm_transcription" / stem,
    }[args.backend]
    prior = json.loads((previous / "summary.json").read_text(encoding="utf-8"))
    if prior["source_sha256"] != source_hash or len(prior["pages"]) != 21:
        raise ValueError("원본 SHA-256 또는 페이지 수 불일치")
    out = ROOT / "markdown/ocr_cer" / args.backend
    inputs = ROOT / "markdown/ocr_cer/masked_inputs"
    out.mkdir(parents=True, exist_ok=True)
    inputs.mkdir(parents=True, exist_ok=True)
    prompt = TRANSCRIPTION_PROMPT if args.backend == "llm_text" else OCR_PROMPT
    llm = _get_cli_llm() if args.backend != "vlm" else None
    backend = get_ocr_backend("vlm") if args.backend == "vlm" else None
    records, combined = [], []
    try:
        for number, page in enumerate(pdf_to_pages(source, dpi=200), 1):
            record = dict(prior["pages"][number - 1])
            if number < 17:
                if record["error"]:
                    raise ValueError(f"재사용할 {number}쪽에 오류가 있습니다")
                text = (previous / f"page_{number:03d}.txt").read_text(encoding="utf-8")
                record["reused_from"] = str(previous.relative_to(ROOT))
                data = page["image"]
                # 파일이 같은 PDF라도 렌더 조건이 다르면 재사용하지 않는다.
                if hashlib.sha256(data).digest() != hashlib.sha256((previous / f"page_{number:03d}.png").read_bytes()).digest():
                    raise ValueError(f"{number}쪽 입력 렌더 불일치")
            else:
                im = Image.open(io.BytesIO(page["image"])).convert("RGB")
                draw = ImageDraw.Draw(im)
                sx, sy = im.width / 1241, im.height / 1755
                for x0, y0, x1, y1 in PHOTO_BOXES[number]:
                    draw.rectangle((round(x0*sx), round(y0*sy), round(x1*sx), round(y1*sy)), fill="white")
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                data = buf.getvalue()
                input_file = inputs / f"page_{number:03d}.png"
                if input_file.exists() and input_file.read_bytes() != data:
                    raise ValueError("백엔드별 마스킹 입력이 달라졌습니다")
                input_file.write_bytes(data)
                start = time.perf_counter()
                if backend is not None:
                    text, usage = backend.ocr_image(data), {}
                else:
                    text, usage = ocr_image_with_meta(data, prompt=prompt, llm=llm)
                record.update(elapsed_sec=round(time.perf_counter()-start, 2), chars=len(text), usage=usage, error=None)
                record["photo_boxes_150dpi"] = PHOTO_BOXES[number]
                print(f"{args.backend} page {number}: {record['elapsed_sec']}s, {len(text)} chars", flush=True)
            record["input_sha256"] = hashlib.sha256(data).hexdigest()
            output_file = out / f"page_{number:03d}.txt"
            output_file.write_text(text, encoding="utf-8")
            record["output_sha256"] = hashlib.sha256(output_file.read_bytes()).hexdigest()
            records.append(record)
            combined.append(f"<!-- page {number} -->\n{text}")
    finally:
        close_ocr_backends()
    (out / "result.md").write_text("\n\n".join(combined), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps({
        "source": source.name, "source_sha256": source_hash, "dpi": 200,
        "scope": "All document text; photograph interiors masked on pages 17-21",
        "backend": args.backend, "model": "PaddleOCR-VL-1.6" if backend else config.LLM_MODEL,
        "prompt": prompt if llm else None, "pages": records,
        "total_sec": round(sum(r["elapsed_sec"] for r in records), 2),
        "timing_note": "Pages 1-16 reused; pages 17-21 freshly measured on masked images",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
