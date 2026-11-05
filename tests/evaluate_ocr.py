"""tests/data의 OCR/본문 추출 결과 및 평가용 근거를 저장하는 수동 실행 도구.

python -m tests.evaluate_ocr --backend vlm --out markdown/ocr_evaluation
PDF/이미지는 공통 OCR CLI로 전체 페이지를 인식하고, DOCX/HWP는 실제
parse_file 경로를 사용한다. DOCX/HWP의 결과를 OCR 정확도로 계산하지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["llm", "vlm"], required=True)
    parser.add_argument("--data", type=Path, default=PROJECT_ROOT / "tests/data")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "markdown/ocr_evaluation")
    parser.add_argument("--native-only", action="store_true", help="DOCX/HWP 등 기존 본문 파서만 실행")
    args = parser.parse_args()
    import config
    config.OCR_BACKEND = args.backend
    from ocr.ocr_pdf import run_ocr, SUPPORTED_EXTS
    from ocr.provider import close_ocr_backends
    from parser.file_parser import parse_file, SUPPORTED_EXTENSIONS

    output = args.out / args.backend
    output.mkdir(parents=True, exist_ok=True)
    records = []
    try:
        for path in sorted(args.data.iterdir()):
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            is_ocr = path.suffix.lower() in SUPPORTED_EXTS
            if args.native_only and is_ocr:
                continue
            start = time.perf_counter()
            record = {"source": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      "backend": args.backend, "ocr_used": is_ocr,
                      "method": "full_page_ocr" if is_ocr else "native_parser"}
            try:
                if is_ocr:
                    pages = run_ocr(path, out_dir=output)
                    record.update(pages=len(pages), errors=sum(bool(p["error"]) for p in pages),
                                  chars=sum(p["chars"] for p in pages))
                else:
                    pages = parse_file(path)
                    text = "\n\n".join(p.text for p in pages)
                    result_path = output / (path.stem + ".md")
                    result_path.write_text(text, encoding="utf-8")
                    record.update(pages=len(pages), errors=0, chars=len(text), output=str(result_path))
                record["status"] = "success" if record["errors"] == 0 else "failed"
            except Exception as exc:
                record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            record["elapsed_sec"] = round(time.perf_counter() - start, 3)
            records.append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
            (output / "evaluation.json").write_text(json.dumps({
                "run_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
                "files": records,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        close_ocr_backends()
    return int(any(r["status"] != "success" for r in records))


if __name__ == "__main__":
    raise SystemExit(main())
