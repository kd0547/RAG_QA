import hashlib
import json
import random

import pytest

from tests.score_ocr_cer import Counts, align, markdown_text, normalize, total_counts, validate_run


@pytest.mark.parametrize("ref,hyp,expected", [
    ("가나다", "가X다", (1, 0, 0)),
    ("가나다", "가다", (0, 1, 0)),
    ("가나다", "가나X다", (0, 0, 1)),
    ("", "", (0, 0, 0)),
    ("", "abc", (0, 0, 3)),
    ("abc", "", (0, 3, 0)),
])
def test_edit_counts(ref, hyp, expected):
    count, edits = align(ref, hyp)
    assert (count.substitutions, count.deletions, count.insertions) == expected
    assert len(edits) == sum(expected)


def test_exact_distance_against_scalar_oracle():
    rng = random.Random(190)
    for _ in range(100):
        a = "".join(rng.choice("ab가나") for _ in range(rng.randrange(20)))
        b = "".join(rng.choice("ab가나") for _ in range(rng.randrange(20)))
        previous = list(range(len(b)+1))
        for i, char in enumerate(a, 1):
            current = [i]
            for j, other in enumerate(b, 1):
                current.append(min(current[-1]+1, previous[j]+1, previous[j-1]+(char != other)))
            previous = current
        counts, _ = align(a, b)
        assert counts.errors == previous[-1]


def test_weighted_aggregate_and_negative_accuracy():
    assert total_counts([Counts(100), Counts(1, deletions=1)]).metrics()["cer"] == 1/101
    assert Counts(1, insertions=3).metrics()["accuracy_pct"] == -200
    assert Counts(insertions=1).metrics()["cer"] is None


def test_normalization_retains_ocr_errors():
    assert normalize("가 나\n㎟ 5ᵗʰ ☐ – “A”") == '가나mm25th□-"A"'
    assert normalize("Aa,1.") == "Aa,1."
    assert normalize("가\n\t나", keep_spaces=True) == "가 나"
    assert normalize("가") == "가"


def test_markup_preserves_caption_cells_and_math():
    text = '# 제목\n| A | B |\n| --- | --- |\n| **가** | ~~나~~<br>다 |\n<성적서 번호 12>\n$ mm^{2} $ $ 5^{\\text{th}} $ $ \\rightarrow $'
    assert normalize(markdown_text(text)) == "제목AB가나다<성적서번호12>mm25th→"


def test_figure_retains_text_and_does_not_deduplicate():
    text = '<figure type="image">\n- 내용: 설명입니다.\n- 표기: 실제 문구\n</figure>\n실제 문구\n[로고: ktl] [이미지] [도장]\n[판독불가]'
    assert normalize(markdown_text(text)) == "실제문구실제문구ktl[판독불가]"


def test_run_validation_rejects_missing_and_modified_pages(tmp_path):
    path = tmp_path / "page_001.txt"
    path.write_text("가", encoding="utf-8")
    summary = {"source_sha256": "test", "pages": [{"page": 1, "error": None,
        "output_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]}
    (tmp_path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    manifest = {"source_sha256": "test", "pages": [{"page": 1}]}
    validate_run(tmp_path, manifest)
    with pytest.raises(ValueError, match="누락"):
        validate_run(tmp_path, {**manifest, "pages": [{"page": 1}, {"page": 2}]})
    path.write_text("변경", encoding="utf-8")
    with pytest.raises(ValueError, match="변경"):
        validate_run(tmp_path, manifest)
