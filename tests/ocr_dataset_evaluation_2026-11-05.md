# 추가 데이터셋 이미지 OCR 재평가

2026-11-05 기준으로 `tests/data`의 **새 PDF 5개·JPG 1개(59페이지)**와 기존 KC 인증서 PDF(21페이지)를 다시 평가했습니다. PDF는 모든 페이지를 200 DPI PNG로 렌더링했고 JPG는 원본 이미지(1140×1484)를 사용했습니다. **LLM과 PaddleOCR-VL에 같은 이미지 바이트를 입력**했으며, 80페이지 모두 양쪽에서 처리 성공했습니다. PDF의 텍스트 레이어와 앱의 일반 문서 파서는 모델 입력에 사용하지 않았습니다.

기존 앱의 OCR·파싱 코드는 수정하지 않았습니다. 비교용 실행기와 채점기만 `tests/`에 추가했으며, 기존 LLM `OCR_PROMPT`와 설치된 `PaddleOCR-VL-1.6`을 그대로 사용했습니다. LLM 모델은 `qwen3.8-flash-next`이며 사용자가 승인한 설정 서버로 이미지가 전송됐습니다.

## 파일별 평가표

| 이미지 원본 | 페이지 | VLM 시간 | LLM 시간 | 확인 문구 VLM/LLM | Markdown 표 열 수 오류 VLM/LLM |
| --- | ---: | ---: | ---: | ---: | ---: |
| AI 제품·서비스 확인제 가이드라인 | 30 | 192.39초 | 202.02초 | 4/3 (4개) | 0/0 |
| KC N5800 안전확인신고 증명서 | 21 | 235.64초 | 311.97초 | 별도 CER 평가 | 0/0 |
| N5800 14세대 Sales Guide | 12 | 45.14초 | 93.61초 | 3/6 (6개) | 0/0 |
| TG AI Board 확인신청서 | 9 | 138.89초 | 155.19초 | 4/4 (4개) | 0/2 |
| 노트북 입찰 사양 JPG | 1 | 11.78초 | 9.89초 | 5/3 (6개) | 0/1 |
| 시험성적서 LME186-A701 | 5 | 38.27초 | 64.27초 | 4/4 (4개) | 0/1 |
| 여행 영수증 | 2 | 7.74초 | 9.08초 | 3/4 (4개) | 0/0 |
| **합계** | **80** | **669.85초** | **846.03초** | **23/24 (28개)** | **0/4** |

시간은 OCR 호출의 페이지별 합계로 이미지 렌더링과 파일 저장은 제외합니다. 첫 VLM 호출의 모델 로딩과 LLM 네트워크 왕복은 포함됩니다. 각 방식의 파일별 출력 글자 수·Markdown 표 수·페이지별 실행 시간·원본/입출력 SHA-256은 [전체 비교표](../markdown/ocr_dataset_eval_2026-11-05/comparison.md)와 [기계 판독 결과](../markdown/ocr_dataset_eval_2026-11-05/comparison.json)에 있습니다. 출력 글자 수나 두 출력의 일치율은 정확도로 해석하지 않았습니다.

## 원문 이미지 대조에서 확인한 차이

| 원본 위치 | PaddleOCR-VL | LLM | 평가 |
| --- | --- | --- | --- |
| 가이드라인 2쪽, 별첨 표제 `인정` | 유지 | `인증`으로 변경 | VLM 정확 |
| Sales Guide 1쪽 표지 | 제목·관리번호를 놓치고 `[이미지]`만 출력 | 제목·관리번호 포함 | LLM 우세 |
| Sales Guide 5쪽 포트 그림 | `오른쪽 면` 누락, 나머지 포트 명칭 대부분 포함 | 오른쪽·왼쪽 면과 포트 설명 포함 | LLM 우세 |
| TG AI Board 신청서 1쪽 | 빨간 보강 문구와 체크 상태 포함 | 같은 내용 포함 | 양쪽 주요 내용 보존. LLM 결과에는 전체 2개 표의 열 수 불일치 |
| 입찰 사양 JPG, OS·무선 LAN 조건 | `기능 제거` 3곳 보존 | 세 곳 모두 `기능 제공`으로 변경 | **LLM의 의미 반전 오류**. 입찰 조건에 사용하면 위험 |
| 입찰 사양 JPG, 항목명 | `주기억장치`를 `주기악장치`, `무게`를 `무개`로 오인식 | `주기억장치`, `무게` 유지 | LLM 우세 |
| 시험성적서 2쪽 표제 | `시험결과`를 `시 협 결 파`로 오인식 | `시험결과` 유지 | LLM 우세. LLM의 결과 표 1개는 열 수 불일치 |
| 여행 영수증 1쪽 객실 유형 | `스탠다드`를 `스텐다드`로 오인식 | `스탠다드` 유지 | LLM 정확 |

입찰 사양의 LLM 출력에는 위 세 곳 외에도 `초기화 방안`을 `초기화 방지`로 바꾼 문장이 있습니다. 원문 의미가 중요한 계약·사양 문서는 검색용 OCR 결과를 그대로 확정값으로 쓰기 전에 해당 문구를 검수해야 합니다. 사진·도식의 시각적 설명은 LLM이 더 많이 출력하며, PaddleOCR은 그림 위치를 `[이미지]`로 표시하는 경우가 많습니다.

## 전체 문자 정확도와 평가 한계

검토된 참조 전사본이 있는 KC 인증서의 **본문·표 1~16쪽 28,783자**에 한해 이번 새 실행의 전체 문자 오류율을 다시 계산했습니다. 사진 안 글자는 제외했습니다.

| 방식 | 치환 | 누락 | 삽입 | CER | 문자 정확도 |
| --- | ---: | ---: | ---: | ---: | ---: |
| PaddleOCR-VL | 71 | 917 | 48 | 3.5993% | 96.4007% |
| LLM | 12 | 17 | 119 | 0.5142% | 99.4858% |

`CER=(치환+누락+삽입)/정답 문자 수`, `문자 정확도=100×(1-CER)`입니다. 이 KC 참조본은 이전 평가에서 LLM 초안을 AI가 원문 이미지와 대조해 수정했으며, 독립적인 사람 검수는 없었습니다. 따라서 초안 편향이나 남은 전사 오류 가능성이 있습니다. 앞서 보고한 KC 21쪽 점수는 사진을 가린 이미지로 평가했으므로 이번 **무가림 1~16쪽** 점수와 범위가 다릅니다.

새 6개 자료에는 전체 문자에 대한 검수된 정답 전사본이 없습니다. 28개 원문 문구 검사는 이미지에서 눈으로 확인한 대표 문자열의 존재 검사이며 **전체 문자 정확도가 아닙니다**. PDF 내부 텍스트를 임의로 정답으로 삼지 않았습니다. 두 결과의 출력 차이도 [비교표](../markdown/ocr_dataset_eval_2026-11-05/comparison.md)에 참고값으로만 기록했습니다.

이번 이미지 비교는 PDF 6개와 JPG 1개를 대상으로 합니다. 기존 DOCX·HWP 2개는 추가된 파일이 아니고 원본 페이지의 시각적 형태를 재현할 변환 도구가 확인되지 않아 포함하지 않았습니다. 기존 DOCX·HWP의 일반 파싱 결과를 이미지 OCR 점수에 섞지 않았습니다.

## Markdown 결과물과 재현

모든 PDF/JPG의 페이지별 실제 입력 PNG, 원본 OCR 텍스트, 합본 `result.md`, `summary.json`은 `markdown/ocr_dataset_eval_2026-11-05/{vlm,llm}/<파일명>_<확장자>/`에 저장했습니다. 아래는 새 자료의 합본 Markdown입니다.

| 자료 | PaddleOCR-VL | LLM |
| --- | --- | --- |
| 가이드라인 | [result.md](<../markdown/ocr_dataset_eval_2026-11-05/vlm/AI 제품 및 서비스 확인제 가이드라인(기업용)_통합본(260721)_pdf/result.md>) | [result.md](<../markdown/ocr_dataset_eval_2026-11-05/llm/AI 제품 및 서비스 확인제 가이드라인(기업용)_통합본(260721)_pdf/result.md>) |
| Sales Guide | [result.md](../markdown/ocr_dataset_eval_2026-11-05/vlm/N5800_14세대__Sales_Guide_V1.1_20260922_pdf/result.md) | [result.md](../markdown/ocr_dataset_eval_2026-11-05/llm/N5800_14세대__Sales_Guide_V1.1_20260922_pdf/result.md) |
| TG AI Board 신청서 | [result.md](<../markdown/ocr_dataset_eval_2026-11-05/vlm/TG_AI_Board_확인신청서_검토(빨강 보강)_pdf/result.md>) | [result.md](<../markdown/ocr_dataset_eval_2026-11-05/llm/TG_AI_Board_확인신청서_검토(빨강 보강)_pdf/result.md>) |
| 입찰 사양 JPG | [result.md](<../markdown/ocr_dataset_eval_2026-11-05/vlm/노트북 입찰 사양_jpg/result.md>) | [result.md](<../markdown/ocr_dataset_eval_2026-11-05/llm/노트북 입찰 사양_jpg/result.md>) |
| 시험성적서 | [result.md](<../markdown/ocr_dataset_eval_2026-11-05/vlm/시험성적서(LME186-A701)_pdf/result.md>) | [result.md](<../markdown/ocr_dataset_eval_2026-11-05/llm/시험성적서(LME186-A701)_pdf/result.md>) |
| 여행 영수증 | [result.md](<../markdown/ocr_dataset_eval_2026-11-05/vlm/진에어 - 2026-10-28_pdf/result.md>) | [result.md](<../markdown/ocr_dataset_eval_2026-11-05/llm/진에어 - 2026-10-28_pdf/result.md>) |

깨진 문자(U+FFFD)는 양쪽 모두 0개였습니다. Markdown 표 열 수 불일치 블록은 PaddleOCR 0개, LLM 4개입니다. 이것은 표 구조 검사이며 표의 내용 정확도를 보증하지 않습니다.

```powershell
# 프로젝트 루트에서, PDF/JPG 전체 페이지를 이미지로 입력
.\.venv\Scripts\python.exe tests/evaluate_image_ocr_dataset.py --backend vlm
.\.venv\Scripts\python.exe tests/evaluate_image_ocr_dataset.py --backend llm

# 저장된 실행 결과 재채점: 모델 호출 없음
.\.venv\Scripts\python.exe tests/score_image_ocr_dataset.py
```

두 실행 결과의 원본/페이지별 PNG/텍스트 해시와 페이지 수를 검증했습니다. 기존 OCR·CER·연동 테스트 **42개가 통과**했습니다. 평가 문구의 목록은 [28개 체크포인트](ocr_dataset_checkpoints_2026-11-05.json)에 있습니다.
