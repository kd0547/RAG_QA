"""저장된 전체 페이지 전사본으로 문자 오류율(CER)을 재현한다. 모델 호출 없음."""
import argparse
from dataclasses import asdict, dataclass
import hashlib
import html
import json
from pathlib import Path
import re
import unicodedata

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def markdown_text(text: str) -> str:
    """서식/그림 설명만 제거한다. OCR 철자와 반복, 본문에 덧붙인 문장은 유지한다."""
    def figure(match):
        # 기존 프롬프트의 구조화된 사진 설명에서 OCR 필드만 보존한다.
        fields = re.findall(r"^\s*-\s*(캡션|표기|구성)\s*:\s*(.*?)(?=^\s*-\s*[^\n:]+:|\Z)",
                            match[1], flags=re.M | re.S)
        return "\n".join(value.strip() for _, value in fields
                         if value.strip() not in {"없음", "(없음)"})

    text = re.sub(r"<figure\b[^>]*>(.*?)</figure>", figure, text, flags=re.S | re.I)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"\[로고\s*:\s*([^\]]+)\]", r"\1", text)
    text = re.sub(r"\[(?:이미지|로고|도장|서명|2D코드|빈 사각형 기호)(?::[^\]]*)?\]", "", text)
    # 한국어 캡션 <성적서 번호 ...>을 HTML로 오인하여 삭제하지 않는다.
    tags = r"(?:div|span|p|br|table|thead|tbody|tr|td|th|strong|b|em|i|sup|sub|del|s|h[1-6])"
    text = re.sub(rf"</?{tags}(?:\s[^<>]*|\s*/)?\s*>", " ", text, flags=re.I)
    text = html.unescape(text)

    def math(match):
        body = match[1].replace(r"\rightarrow", "→")
        body = body.replace(r"\times", "×").replace(r"\circ", "°")
        for _ in range(3):
            body = re.sub(r"\\(?:text|mathrm|mathbf)\{([^{}]*)\}", r"\1", body)
            body = re.sub(r"[\^_]\{([^{}]*)\}", r"\1", body)
        return body

    text = re.sub(r"\$([^$\n]+)\$", math, text)
    text = re.sub(r"(?m)^\s*#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*```[^\n]*$", "", text)
    text = re.sub(r"(?m)^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", "", text)
    for pattern in (r"\*\*(.+?)\*\*", r"__(.+?)__", r"~~(.+?)~~", r"\*([^*\n]+)\*"):
        text = re.sub(pattern, r"\1", text)
    lines = []
    for line in text.splitlines():
        if line.strip().startswith("|"):
            cells = line.strip().strip("|").split("|")
            if all(re.fullmatch(r"\s*:?-{3,}:?\s*", cell) for cell in cells):
                continue
            line = "\t".join(cells)
        lines.append(line)
    return "\n".join(lines).strip()


def normalize(text: str, *, keep_spaces: bool = False) -> str:
    """대소문자/문장부호 유지. 호환 글꼴과 인쇄상의 대시/따옴표만 통일."""
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(str.maketrans({
        "–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-",
        "“": '"', "”": '"', "‘": "'", "’": "'", "☐": "□",
    }))
    return re.sub(r"\s+", " " if keep_spaces else "", text).strip()


@dataclass
class Counts:
    n: int = 0
    substitutions: int = 0
    deletions: int = 0
    insertions: int = 0

    @property
    def errors(self):
        return self.substitutions + self.deletions + self.insertions

    def metrics(self):
        # 빈 정답+삽입은 분모 0이므로 점수를 꾸미지 않고 정의 불가로 남긴다.
        cer = self.errors / self.n if self.n else (0.0 if not self.errors else None)
        return {**asdict(self), "errors": self.errors, "cer": cer,
                "accuracy_pct": 100 * (1 - cer) if cer is not None else None}


def align(reference: str, hypothesis: str) -> tuple[Counts, list[dict]]:
    """정확한 Levenshtein DP. 같은 비용이면 일치→치환→삭제→삽입 우선."""
    n, m = len(reference), len(hypothesis)
    if (n + 1) * (m + 1) > 64_000_000:
        raise ValueError("페이지가 너무 큽니다. 페이지 단위로 나누어 평가하세요.")
    distance = np.empty((n + 1, m + 1), dtype=np.int32)
    distance[0] = np.arange(m + 1)
    distance[:, 0] = np.arange(n + 1)
    target = np.array(list(hypothesis))
    columns = np.arange(1, m + 1, dtype=np.int32)
    for i, char in enumerate(reference, 1):
        candidate = np.minimum(distance[i-1, 1:] + 1,
                               distance[i-1, :-1] + (target != char))
        # row[j] = min(candidate[j], row[j-1]+1), vectorized prefix minimum.
        distance[i, 1:] = np.minimum.accumulate(np.minimum(candidate - columns, i)) + columns
    counts, edits = Counts(n=n), []
    i, j = n, m
    while i or j:
        if i and j and reference[i-1] == hypothesis[j-1] and distance[i,j] == distance[i-1,j-1]:
            i -= 1
            j -= 1
            continue
        if i and j and distance[i,j] == distance[i-1,j-1]+1:
            counts.substitutions += 1
            i -= 1
            j -= 1
            op, a, b = "S", reference[i], hypothesis[j]
        elif i and distance[i,j] == distance[i-1,j]+1:
            counts.deletions += 1
            i -= 1
            op, a, b = "D", reference[i], ""
        else:
            counts.insertions += 1
            j -= 1
            op, a, b = "I", "", hypothesis[j]
        edits.append({"op": op, "ref_index": i, "hyp_index": j, "reference": a, "hypothesis": b})
    assert counts.errors == int(distance[n,m])
    edits.reverse()
    return counts, edits


def total_counts(items):
    return Counts(**{key: sum(getattr(item, key) for item in items) for key in asdict(Counts())})


def validate_run(folder: Path, manifest: dict):
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    if summary["source_sha256"] != manifest["source_sha256"]:
        raise ValueError(f"{folder.name}: 원본 SHA-256 불일치")
    pages = summary["pages"]
    expected = [p["page"] for p in manifest["pages"]]
    if [p["page"] for p in pages] != expected:
        raise ValueError(f"{folder.name}: 누락 또는 중복 페이지")
    for page in pages:
        if page["error"]:
            raise ValueError(f"{folder.name}: OCR 실패 페이지 {page['page']}")
        path = folder / f"page_{page['page']:03d}.txt"
        if hashlib.sha256(path.read_bytes()).hexdigest() != page["output_sha256"]:
            raise ValueError(f"{folder.name}: 저장 후 변경된 OCR 결과 {path.name}")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=ROOT / "tests/ocr_reference/kc_n5800")
    parser.add_argument("--runs", type=Path, default=ROOT / "markdown/ocr_cer")
    parser.add_argument("--out", type=Path, default=ROOT / "markdown/ocr_cer/evaluation")
    args = parser.parse_args()
    manifest = json.loads((args.reference / "manifest.json").read_text(encoding="utf-8"))
    if manifest["status"] != "visually_reviewed_ai_assisted":
        raise ValueError("검토하지 않은 전사본은 평가에 사용할 수 없습니다")
    source = ROOT / "tests/data" / manifest["source"]
    if hashlib.sha256(source.read_bytes()).hexdigest() != manifest["source_sha256"]:
        raise ValueError("현재 원본 PDF가 참조 전사본과 다릅니다")
    args.out.mkdir(parents=True, exist_ok=True)
    labels = {"vlm": "PaddleOCR-VL", "llm": "기존 LLM", "llm_text": "LLM 문자 전사 전용"}
    results, input_hashes = {}, None
    for name, label in labels.items():
        folder = args.runs / name
        summary = validate_run(folder, manifest)
        hashes = [p["input_sha256"] for p in summary["pages"]]
        if input_hashes is not None and hashes != input_hashes:
            raise ValueError("백엔드 간 입력 이미지 불일치")
        input_hashes = hashes
        scores, counts, spaced_counts = [], [], []
        normalized = args.out / name
        normalized.mkdir(exist_ok=True)
        for record in manifest["pages"]:
            number = record["page"]
            source_file = args.reference / f"page_{number:03d}.txt"
            if hashlib.sha256(source_file.read_bytes()).hexdigest() != record["sha256"]:
                raise ValueError(f"전사본 해시 변경: {source_file}")
            ref = source_file.read_text(encoding="utf-8")
            raw = (folder / source_file.name).read_text(encoding="utf-8")
            hyp = markdown_text(raw)
            reference, hypothesis = normalize(ref), normalize(hyp)
            count, edits = align(reference, hypothesis)
            spaced, _ = align(normalize(ref, keep_spaces=True), normalize(hyp, keep_spaces=True))
            counts.append(count)
            spaced_counts.append(spaced)
            page_score = {"page": number, **count.metrics(), "with_spaces": spaced.metrics()}
            scores.append(page_score)
            (normalized / source_file.name).write_text(hyp + "\n", encoding="utf-8")
            (normalized / f"page_{number:03d}_alignment.json").write_text(json.dumps({
                "reference_normalized": reference, "hypothesis_normalized": hypothesis,
                "metrics": count.metrics(), "edits": edits,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        results[name] = {"label": label, "aggregate": total_counts(counts).metrics(),
                         "with_spaces": total_counts(spaced_counts).metrics(), "pages": scores,
                         "source_run": str(folder), "model": summary["model"]}
    payload = {"formula": "CER=(S+D+I)/N; accuracy_pct=100*(1-CER)",
               "reference_manifest": manifest, "results": results}
    (args.out / "scores.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 전체 문자 OCR 평가", "", "범위: 21쪽 본문·표·머리글·바닥글·캡션. 사진 내부 제외(동일한 마스킹 입력).", "",
             "정답은 OCR 초안을 원본 이미지와 대조하여 수정한 AI 보조 전사본입니다. 독립적인 사람 검수는 받지 않았습니다.", "",
             "주 지표는 공백 제외, NFKC/인쇄 기호 정규화 후 CER입니다. 대소문자·숫자·문장부호를 유지합니다.", "",
             "| 방식 | 정답 문자 N | 치환 S | 누락 D | 삽입 I | CER | 문자 정확도 |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for result in results.values():
        s = result["aggregate"]
        lines.append(f"| {result['label']} | {s['n']:,} | {s['substitutions']:,} | {s['deletions']:,} | {s['insertions']:,} | {s['cer']:.4%} | {s['accuracy_pct']:.4f}% |")
    lines += ["", "전체 점수는 페이지별 오류 합계 ÷ 전체 정답 문자 수입니다. 페이지 점수의 단순평균이 아닙니다.", "",
              "| PDF 쪽 | 정답 문자 | PaddleOCR-VL 정확도 | 기존 LLM 정확도 | LLM 전사 전용 정확도 |",
              "| ---: | ---: | ---: | ---: | ---: |"]
    for index, record in enumerate(manifest["pages"]):
        row = [results[n]["pages"][index] for n in labels]
        lines.append(f"| {record['page']} | {row[0]['n']:,} | " + " | ".join(f"{r['accuracy_pct']:.4f}%" for r in row) + " |")
    lines += ["", "공백 포함 보조지표(연속 공백·탭·줄바꿈을 한 칸으로 통일):", ""]
    lines += [f"- {r['label']}: {r['with_spaces']['accuracy_pct']:.4f}%" for r in results.values()]
    lines += ["", "서식 제거 후 텍스트와 모든 문자 정렬 오류는 각 방식의 하위 폴더에 저장했습니다.", ""]
    (args.out / "evaluation.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({name: value["aggregate"] for name, value in results.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
