"""tests/data의 PDF/이미지를 동일한 이미지 입력으로 LLM/PaddleOCR-VL 평가한다.

기존 애플리케이션 파서와 PDF 텍스트 레이어는 사용하지 않는다. 같은 파일과 설정으로
재실행하면 완료된 페이지의 입력/출력 해시를 검증하고 이어서 처리한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True, choices=("llm", "vlm"))
    parser.add_argument("--data", type=Path, default=ROOT / "tests/data")
    parser.add_argument("--out", type=Path, default=ROOT / "markdown/ocr_dataset_eval_2026-11-05")
    parser.add_argument("--dpi", type=int, default=200)
    args = parser.parse_args()

    import config
    from ocr.ocr_pdf import SUPPORTED_EXTS, load_pages, _get_cli_llm
    from ocr.llm_ocr import OCR_PROMPT, ocr_image_with_meta
    from ocr.provider import get_ocr_backend, close_ocr_backends

    paths = sorted(p for p in args.data.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS)
    if not paths:
        raise SystemExit("PDF/이미지 파일이 없습니다")
    output = args.out / args.backend
    output.mkdir(parents=True, exist_ok=True)
    llm = _get_cli_llm() if args.backend == "llm" else None
    backend = get_ocr_backend("vlm") if args.backend == "vlm" else None
    failures = 0
    try:
        for path in paths:
            source_sha = sha(path.read_bytes())
            folder = output / f"{path.stem}_{path.suffix[1:].lower()}"
            folder.mkdir(parents=True, exist_ok=True)
            summary_file = folder / "summary.json"
            if summary_file.exists():
                existing = json.loads(summary_file.read_text(encoding="utf-8"))
                if (existing["source_sha256"] != source_sha or existing["backend"] != args.backend
                    or existing["dpi"] != args.dpi or existing["prompt_sha256"] != sha(OCR_PROMPT.encode("utf-8"))):
                    raise ValueError(f"기존 실행 설정과 다릅니다: {path.name}")
                records = existing["pages"]
            else:
                records = []
            pages = load_pages(path, dpi=args.dpi)
            print(f"[{args.backend}] {path.name}: {len(pages)} pages", flush=True)
            if len(records) > len(pages):
                raise ValueError(f"저장된 페이지 수가 원본보다 많습니다: {path.name}")
            for number, page in enumerate(pages, 1):
                image = page["image"]
                image_sha = sha(image)
                name = f"page_{number:03d}"
                image_file, text_file = folder / f"{name}.png", folder / f"{name}.txt"
                if number <= len(records) and not records[number-1].get("error"):
                    old = records[number-1]
                    if old["input_sha256"] != image_sha or not text_file.exists() or old["output_sha256"] != sha(text_file.read_bytes()):
                        raise ValueError(f"저장된 페이지가 달라졌습니다: {path.name} p{number}")
                    if not image_file.exists() or sha(image_file.read_bytes()) != image_sha:
                        raise ValueError(f"저장된 입력 이미지가 달라졌습니다: {path.name} p{number}")
                    print(f"  p{number}: verified existing", flush=True)
                    continue
                image_file.write_bytes(image)
                start = time.perf_counter()
                try:
                    if backend:
                        text, usage = backend.ocr_image(image), {}
                    else:
                        text, usage = ocr_image_with_meta(image, prompt=OCR_PROMPT, llm=llm)
                    error = None
                except Exception as exc:
                    text, usage, error = "", {}, f"{type(exc).__name__}: {exc}"
                    failures += 1
                elapsed = round(time.perf_counter() - start, 2)
                text_file.write_text(text, encoding="utf-8")
                record = {"page": number, "input_sha256": image_sha,
                          "output_sha256": sha(text_file.read_bytes()), "image_size": list(page["size"]),
                          "elapsed_sec": elapsed, "chars": len(text), "usage": usage, "error": error}
                if number <= len(records):
                    records[number-1] = record
                else:
                    records.append(record)
                summary = {"source": path.name, "source_sha256": source_sha, "backend": args.backend,
                           "model": config.LLM_MODEL if llm else "PaddleOCR-VL-1.6",
                           "method": "full_page_image_ocr", "dpi": args.dpi,
                           "prompt_sha256": sha(OCR_PROMPT.encode("utf-8")),
                           "pages": records, "total_sec": round(sum(r["elapsed_sec"] for r in records), 2)}
                summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  p{number}: {elapsed}s, {len(text)} chars, error={error}", flush=True)
            (folder / "result.md").write_text("\n\n".join(
                f"<!-- page {n} -->\n{(folder / f'page_{n:03d}.txt').read_text(encoding='utf-8')}"
                for n in range(1, len(pages)+1)), encoding="utf-8")
    finally:
        close_ocr_backends()
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
