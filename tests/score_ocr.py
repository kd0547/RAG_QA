"""저장된 두 OCR 실행을 체크포인트로 비교한다. 네트워크/모델 호출 없음."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import unicodedata


def normalize(text):
    text = re.sub(r"<[^>]*>", "", text)
    text = unicodedata.normalize("NFKC", text).casefold()
    return "".join(c for c in text if c.isalnum())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vlm", type=Path, required=True, help="summary.json이 있는 폴더")
    parser.add_argument("--llm", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    checkpoints = json.loads(Path(__file__).with_name("ocr_checkpoints.json").read_text(encoding="utf-8"))
    scores, summaries = {}, {}
    for backend, folder in (("vlm", args.vlm), ("llm", args.llm)):
        summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        if summary["source"] != checkpoints["source"]:
            raise ValueError("체크포인트와 실행 대상 파일이 다릅니다.")
        if summary.get("source_sha256") != checkpoints["source_sha256"]:
            raise ValueError("체크포인트 원본과 실행 파일의 SHA-256이 다릅니다.")
        for p in summary["pages"]:
            if p["error"]:
                raise ValueError(f"{backend} page {p['page']} 실행 오류: {p['error']}")
        scores[backend] = []
        for page, label, expected in checkpoints["checks"]:
            text = (folder / f"page_{page:03d}.txt").read_text(encoding="utf-8")
            scores[backend].append({"page": page, "label": label, "expected": expected,
                                    "passed": normalize(expected) in normalize(text)})
        summaries[backend] = {
            "pages": len(summary["pages"]), "total_sec": summary["total_sec"],
            "chars": sum(p["chars"] for p in summary["pages"]),
            "checkpoint_passed": sum(c["passed"] for c in scores[backend]),
            "checkpoint_total": len(scores[backend]),
            "result_sha256": hashlib.sha256((folder / "result.md").read_bytes()).hexdigest(),
        }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "scores.json").write_text(json.dumps({
        "method": checkpoints["method"], "summary": summaries, "checks": scores,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# OCR 체크포인트 평가", "", checkpoints["method"], "",
             "| 페이지 | 항목 | 기대값 | PaddleOCR | LLM |", "| --- | --- | --- | --- | --- |"]
    for i, (page, label, expected) in enumerate(checkpoints["checks"]):
        flags = ["통과" if scores[b][i]["passed"] else "불일치" for b in ("vlm", "llm")]
        lines.append(f"| {page} | {label} | {expected} | {flags[0]} | {flags[1]} |")
    (args.out / "checkpoints.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
