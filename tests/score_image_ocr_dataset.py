"""동일 이미지로 수행한 LLM/PaddleOCR 결과의 완전성·차이와 검증 가능한 CER을 계산."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

import markdown
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.score_ocr_cer import align, markdown_text, normalize, total_counts


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def malformed_tables(text: str) -> int:
    """파이프 표의 열 수가 헤더와 다른 블록 수. 이스케이프된 파이프는 제외."""
    blocks, current = [], []
    for line in text.splitlines() + [""]:
        if line.strip().startswith("|") and line.strip().endswith("|"):
            current.append(line.strip())
        elif current:
            blocks.append(current)
            current = []
    bad = 0
    for block in blocks:
        widths = [len(re.split(r"(?<!\\)\|", line)) - 2 for line in block]
        if len(set(widths)) != 1:
            bad += 1
    return bad


def main():
    base = ROOT / "markdown/ocr_dataset_eval_2026-11-05"
    source_dir = ROOT / "tests/data"
    data = []
    manifest = json.loads((ROOT / "tests/ocr_reference/kc_n5800/manifest.json").read_text(encoding="utf-8"))
    checkpoint_set = json.loads((ROOT / "tests/ocr_dataset_checkpoints_2026-11-05.json").read_text(encoding="utf-8"))
    kc_counts = {"llm": [], "vlm": []}
    check_results = []
    for llm_dir in sorted((base / "llm").iterdir()):
        if not llm_dir.is_dir() or not (llm_dir / "summary.json").exists():
            continue
        llm = json.loads((llm_dir / "summary.json").read_text(encoding="utf-8"))
        vlm_dir = base / "vlm" / llm_dir.name
        vlm = json.loads((vlm_dir / "summary.json").read_text(encoding="utf-8"))
        source = source_dir / llm["source"]
        if llm["source"] != vlm["source"] or not source.exists():
            raise ValueError(f"짝이 맞지 않는 원본: {llm_dir.name}")
        if llm["source_sha256"] != vlm["source_sha256"] or sha(source.read_bytes()) != llm["source_sha256"]:
            raise ValueError(f"원본 해시 불일치: {source.name}")
        if llm["prompt_sha256"] != vlm["prompt_sha256"] or llm["dpi"] != vlm["dpi"]:
            raise ValueError(f"실행 설정 불일치: {source.name}")
        if len(llm["pages"]) != len(vlm["pages"]):
            raise ValueError(f"페이지 누락: {source.name}")
        pages = []
        for left, right in zip(llm["pages"], vlm["pages"]):
            number = left["page"]
            if number != right["page"] or left["input_sha256"] != right["input_sha256"]:
                raise ValueError(f"입력 이미지 불일치: {source.name} p{number}")
            if left["error"] or right["error"]:
                raise ValueError(f"OCR 실패: {source.name} p{number}: {left['error']} {right['error']}")
            texts = {}
            for backend, folder, record in (("llm", llm_dir, left), ("vlm", vlm_dir, right)):
                image_file = folder / f"page_{number:03d}.png"
                text_file = folder / f"page_{number:03d}.txt"
                if sha(image_file.read_bytes()) != record["input_sha256"]:
                    raise ValueError(f"이미지 변경: {image_file}")
                if sha(text_file.read_bytes()) != record["output_sha256"]:
                    raise ValueError(f"결과 변경: {text_file}")
                texts[backend] = normalize(markdown_text(text_file.read_text(encoding="utf-8")))
            counts, _ = align(texts["llm"], texts["vlm"])
            difference = counts.errors / max(len(texts["llm"]), len(texts["vlm"]), 1)
            pages.append({"page": number, "input_sha256": left["input_sha256"],
                          "llm_chars": left["chars"], "vlm_chars": right["chars"],
                          "llm_sec": left["elapsed_sec"], "vlm_sec": right["elapsed_sec"],
                          "normalized_disagreement": round(difference, 6),
                          "edit_distance": counts.errors})
            for check in checkpoint_set["checks"]:
                if check["source"] == source.name and check["page"] == number:
                    check_results.append({**check, "llm": normalize(check["expected"]) in texts["llm"],
                                          "vlm": normalize(check["expected"]) in texts["vlm"]})
            if llm["source"] == manifest["source"] and number <= 16:
                reference = ROOT / "tests/ocr_reference/kc_n5800" / f"page_{number:03d}.txt"
                if sha(reference.read_bytes()) != manifest["pages"][number-1]["sha256"]:
                    raise ValueError("KC 참조 전사본 해시 불일치")
                ref = normalize(reference.read_text(encoding="utf-8"))
                for backend in kc_counts:
                    score, _ = align(ref, texts[backend])
                    kc_counts[backend].append(score)
        document_quality = {}
        for backend, folder in (("llm", llm_dir), ("vlm", vlm_dir)):
            result = (folder / "result.md").read_text(encoding="utf-8")
            soup = BeautifulSoup(markdown.markdown(result, extensions=["tables", "fenced_code"]), "html.parser")
            document_quality[backend] = {"markdown_tables": len(soup.find_all("table")),
                                         "malformed_pipe_tables": malformed_tables(result),
                                         "replacement_chars": result.count("\ufffd"),
                                         "empty_pages": sum(not normalize(markdown_text((folder / f'page_{p["page"]:03d}.txt').read_text(encoding="utf-8")))
                                                            for p in pages)}
        data.append({"source": source.name, "source_sha256": llm["source_sha256"],
                     "pages": len(pages), "llm_sec": llm["total_sec"], "vlm_sec": vlm["total_sec"],
                     "llm_chars": sum(p["llm_chars"] for p in pages),
                     "vlm_chars": sum(p["vlm_chars"] for p in pages),
                     "quality": document_quality,
                     "mean_page_disagreement": round(sum(p["normalized_disagreement"] for p in pages)/len(pages), 6),
                     "output_llm": str(llm_dir / "result.md"), "output_vlm": str(vlm_dir / "result.md"),
                     "page_metrics": pages})
    if len(data) != 7 or sum(f["pages"] for f in data) != 80:
        raise ValueError("평가 대상 PDF/JPG 7개, 80페이지가 완성되지 않았습니다")
    if len(check_results) != len(checkpoint_set["checks"]):
        raise ValueError("시각 검토 체크포인트가 일부 평가되지 않았습니다")
    payload = {"method": "Full-page image input, same PNG SHA-256 per backend. Disagreement is not accuracy.",
               "files": data, "total_files": len(data), "total_pages": sum(f["pages"] for f in data),
               "spot_checks": {"method": checkpoint_set["method"], "results": check_results},
               "kc_pages_1_16_cer": {b: total_counts(c).metrics() for b,c in kc_counts.items()}}
    (base / "comparison.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 추가 이미지 데이터셋 OCR 비교", "",
             "PDF 전체 페이지를 200 DPI PNG로 렌더링하고 JPG도 이미지 그대로 사용했습니다. 같은 PNG의 SHA-256을 두 결과에서 확인했습니다.",
             "PDF 텍스트 레이어나 일반 문서 파서의 결과를 모델 입력으로 사용하지 않았습니다.", "",
             "| 파일 | 페이지 | PaddleOCR-VL 시간 | LLM 시간 | PaddleOCR-VL 출력 글자 | LLM 출력 글자 | Markdown 표 VLM/LLM | 열 수 불일치 표 VLM/LLM | 페이지별 평균 출력 차이* |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for f in data:
        q=f["quality"]
        lines.append(f"| {f['source']} | {f['pages']} | {f['vlm_sec']:.2f}초 | {f['llm_sec']:.2f}초 | {f['vlm_chars']:,} | {f['llm_chars']:,} | {q['vlm']['markdown_tables']}/{q['llm']['markdown_tables']} | {q['vlm']['malformed_pipe_tables']}/{q['llm']['malformed_pipe_tables']} | {f['mean_page_disagreement']:.2%} |")
    lines += ["", "*출력 차이는 서식·공백을 정규화한 두 결과의 Levenshtein 거리 ÷ 더 긴 출력 길이입니다. **정확도가 아닙니다.**", "",
              "## 원문 이미지에서 확인한 문구", "",
              "| 파일 | 확인 문구 수 | PaddleOCR-VL 일치 | LLM 일치 |",
              "| --- | ---: | ---: | ---: |"]
    for f in data:
        checked = [r for r in check_results if r["source"] == f["source"]]
        if checked:
            lines.append(f"| {f['source']} | {len(checked)} | {sum(r['vlm'] for r in checked)} | {sum(r['llm'] for r in checked)} |")
    lines += ["", f"체크포인트는 새 6개 파일의 대표 이미지에서 눈으로 확인한 {len(check_results)}개 문자열입니다. 전체 문자 정확도가 아닙니다.", "",
              "| 방식 | KC 인증서 본문 1~16쪽 정답 문자 | 치환 | 누락 | 삽입 | CER | 문자 정확도 |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for backend, name in (("vlm", "PaddleOCR-VL"), ("llm", "LLM")):
        s = payload["kc_pages_1_16_cer"][backend]
        lines.append(f"| {name} | {s['n']:,} | {s['substitutions']:,} | {s['deletions']:,} | {s['insertions']:,} | {s['cer']:.4%} | {s['accuracy_pct']:.4f}% |")
    lines += ["", "KC 문서의 정답은 이전 평가에서 만든 AI 보조 시각 대조 전사본입니다. 사진을 제외한 본문 1~16쪽만 이번 새 실행과 직접 비교했습니다.",
              "새 6개 자료에는 검수된 전체 문자 정답이 없으므로 문자 정확도를 산출하지 않았습니다. 두 모델 출력의 일치율도 정답률로 쓰지 않습니다.", ""]
    (base / "comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"files": len(data), "pages": sum(f["pages"] for f in data),
                      "kc_cer": payload["kc_pages_1_16_cer"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
