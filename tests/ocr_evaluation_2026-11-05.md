# OCR 연동 및 결과 평가

추가 평가: [전체 문자 CER 평가표](ocr_character_evaluation_2026-11-05.md).
아래의 30개 체크포인트 결과는 최초 평가 기록이며 전체 문자 정확도와 구분합니다.

평가일: 2026-11-05 (Asia/Seoul). 입력 폴더는 `tests/data`이며 PDF, DOCX, HWP 각 1개입니다.

## 결과 요약

환경변수 `OCR_BACKEND=llm|vlm` 선택, `OCRBackend` 공통 계약, 기존 파서·이미지 표 가져오기 연동을 구현했습니다.
PaddleOCR는 `C:/TG_AI_DEV/paddleocr_vl_test`의 설치 환경과 모델을 별도 프로세스로 재사용합니다.
자동 테스트 30개가 통과했고 두 OCR 모두 PDF 21페이지를 오류 없이 처리했습니다.

| 평가 항목 | PaddleOCR-VL 1.6 | 기존 LLM (qwen3.8-flash-next) |
| --- | ---: | ---: |
| PDF 처리 성공 | 21/21 페이지 | 21/21 페이지 |
| 전체 OCR 소요 시간 | 237.51초 | 303.54초 |
| 본문·표 페이지 1–16 소요 시간 | 232.36초 | 255.98초 |
| 사진 페이지 17–21 소요 시간 | 5.15초 | 47.56초 |
| 페이지 출력 글자 합계 | 41,171자 | 43,342자 |
| 원본 대조 체크포인트 | 27/30 (90.0%) | 29/30 (96.7%) |
| Markdown 렌더러가 인식한 표 | 18개 | 17개 |
| 인식한 표 내부 열 개수 불일치 | 0개 | 0개 |
| 깨진 문자 U+FFFD / 저장되지 않은 이미지 링크 | 0 / 0 | 0 / 0 |
| 사진 의미·내부 라벨 | `[이미지]`로 표시, 설명 없음 | 사진 설명·라벨 추출 포함 |

시간은 200 DPI의 동일한 PNG 입력으로 한 번씩 실행한 페이지별 시간의 합이며, PNG 렌더링·파일 저장 시간은 제외했습니다.
PaddleOCR의 첫 페이지는 모델 초기화를 포함하고, LLM 시간은 네트워크 요청을 포함합니다.
로컬 GPU는 RTX 5090이며 LLM은 사용자가 승인한 `http://14.38.199.190:9090/v1` 서버를 사용했습니다.
두 실행은 로컬/원격에서 동시에 진행했으며, 서버 부하·반복 실험을 통제한 벤치마크는 아닙니다.
사진 페이지의 처리 범위가 다르므로 전체 시간만으로 순수 OCR 속도를 비교하면 안 됩니다.

체크포인트는 원본 이미지에서 확인한 1·4·13·17페이지의 30개 문자열/표 행입니다.
공백·대소문자·구분기호를 정규화한 존재 검사이며, 무작위 표본이나 전체 문자 정확도(CER/WER)가 아닙니다.
문자 수와 표 수는 내용 정확도를 보증하지 않습니다. 최초 평가 당시 정답 전문이 없어 전체 정확도를 산출하지 않았으며,
후속 전체 전사본 기반 결과는 위 링크에서 확인할 수 있습니다.

## 실제 내용 대조

| 위치 | 원본/확인 기준 | PaddleOCR 결과 | LLM 결과 | 판단 |
| --- | --- | --- | --- | --- |
| PDF 1p | 제조업자명: 주식회사 삼보컴퓨터 | `상보컴퓨터`로 오인식 | `삼보컴퓨터` 유지 | PaddleOCR 고유명사 검수 필요 |
| PDF 1p | 다수 공장의 명: “이면기재” | `이면기재` 유지 | `이연기재`, 뒤 문구도 오인식 | LLM도 한글 오인식 존재 |
| PDF 1p | ZH10003-20001N, DC19 V/2.1 A, KC62368-1(2025-10), 발급일 | 선택 항목 보존 | 선택 항목 보존 | 핵심 번호·수치 표본 통과 |
| PDF 3p | 다수 공장 3열 병합 표 | 병합 셀을 빈 칸으로 펼친 유효한 표 | 헤더 구분선 누락·헤더 2열/본문 3열 | LLM 출력은 Markdown 표로 렌더링되지 않음 |
| PDF 4p | 부품명·제조사·모델·정격·인증 5열 표 | 16개 데이터 행 및 선택 모델명 유지 | 16개 데이터 행 및 선택 모델명 유지 | 본문·표 추출 양호, 기호·공백 표현은 차이 |
| PDF 11p | 1차·2차 변경 문구/번호 | `20-034796-01-1` 등 표 앞 변경 이력 누락 | 해당 번호와 문구 존재 | 30개 검사 밖에서 발견한 PaddleOCR 누락 |
| PDF 13p | 두 사양표의 CPU/MEM/HDD/SSD/OS와 선택 4개 행 | 선택 행 모두 일치 | 선택 행 모두 일치 | 표본의 값/열 관계 유지 |
| PDF 13p | 변경발급 내용/Contents of Certificate Revisions 제목 | 누락 | 유지 | PaddleOCR 레이아웃 누락 주의 |
| PDF 17p | 사진 아래 NL40BAT-3, Getac Technology 캡션 | 사진 영역에 포함되어 누락 | 캡션 포함 | 사진 중심 검색 자료는 LLM이 더 많은 정보 제공 |
| PDF 17–21p | 제품·배터리·메인보드 사진 | 위치 표시, 사진 설명 없음 | 부품 설명 및 일부 라벨 포함 | 출력 범위 차이; LLM의 작은 라벨은 별도 검수 필요 |
| DOCX | 개발비 17,005,528, RTX5070, 원문의 개발기간 | 양쪽 설정 결과 동일 | 양쪽 설정 결과 동일 | 본문 파서 결과이며 OCR 성능 비교 대상 아님 |
| HWP | 전문·계약 개요·제1조~제18조·서명란 | 양쪽 설정 결과 동일 | 양쪽 설정 결과 동일 | 본문 파서 결과이며 OCR 성능 비교 대상 아님 |

PDF는 21페이지 모두 텍스트 레이어가 없는 스캔본입니다. 전체 페이지 개요 이미지와 페이지별 Markdown을 점검하고,
1·4·13·17페이지는 확대 원본과 상세 대조했습니다. 11페이지 누락은 PaddleOCR의 정규화 전 원문에서도 확인되어
HTML 표 변환 과정에서 발생한 누락은 아닙니다. 모든 글자를 수작업 전사하여 대조한 것은 아닙니다.

DOCX 원본 XML에는 `2025/05/12 ~ 2024/08/14`라는 개발기간이 실제로 있습니다.
출력에서 이 날짜를 임의로 교정하지 않았습니다. DOCX/HWP의 표 병합·페이지 구분은 기존 파서의 표현을 따릅니다.

## 파일별 실행 결과

| 파일 | 경로 | PaddleOCR 설정 | LLM 설정 | 검증 범위 |
| --- | --- | --- | --- | --- |
| KC 인증서 PDF | 전체 페이지 이미지 OCR | 21페이지, 237.51초 | 21페이지, 303.54초 | 전체 출력 생성·구조 검사 + 표본 원본 대조 |
| A650 제품제안서 DOCX | `parse_file` 본문·표 파서 | 3,670자, 0.066초 | 3,670자, 0.054초 | 원본 XML 주요 값 확인, 두 결과 동일 |
| SW종사자 표준근로계약서 HWP | `parse_file` 본문·표 파서 | 6,135자, 0.213초 | 6,135자, 0.199초 | 주요 조항·서명란 확인, 두 결과 동일 |

DOCX/HWP는 문서 전체를 논리적 1페이지로 반환합니다. 원본의 인쇄 페이지 수를 뜻하지 않습니다.
이 두 파서에는 기존에 삽입 이미지 OCR이 없으므로 백엔드를 변경해도 본문 추출 결과는 같습니다.

## 연동/회귀 검증

- `pytest tests/test_ocr_backend.py tests/test_spec_import.py -q`: **30 passed**.
- 백엔드 선택·인스턴스 재사용, 잘못된 설정/빈 입력, LLM 응답 정규화, 이미지/PDF 파서 전달, LLM 없는 VLM CLI를 검증했습니다.
- 작업 프로세스 오류·종료·시간 초과·임시 파일 정리·재시작 및 표 rowspan/colspan 변환을 검증했습니다.
- 기존 사양표 가져오기 API 회귀 테스트도 통과했습니다.
- 실제 `parse_file`에 원본 PDF의 1·4·17페이지를 넣어 VLM 호출 **3회**, 결과 **3페이지**, **33.383초**를 확인했습니다.
  이 실측은 전체 PDF OCR 평가와 별개의 연결 점검입니다.
- 원본 모델/설치 폴더를 수정하지 않았으며, 로컬 `.env`의 기본 선택을 강제로 변경하지 않았습니다.

## 초기 품질 문제와 적용 설정

초기 실험에서 `use_ocr_for_image_block=True`를 켜면 2D 코드가 반복 꽃 이모지나
`The quick brown fox jumps over the lazy dog.` 같은 원문에 없는 내용으로 변환됐습니다.
이를 확인한 뒤 해당 옵션을 끄고 **21페이지 전체를 새로 실행**했습니다.
이 보고서는 `vlm_pdf_final` 결과만 평가합니다. `vlm_pdf`는 중단된 초기 실험 자료이며 최종 결과가 아닙니다.

최종 VLM은 이미지 위치만 표시하고, HTML 표를 Markdown 표로 변환합니다.
외부 crop 링크와 base64 이미지 데이터는 검색용 텍스트에 넣지 않습니다.
본문/표만 필요한 로컬 처리에는 사용할 수 있으나, 인증서의 정확한 법인명·변경 이력이나 사진 캡션이 필요한 경우 원본 대조가 필요합니다.
이번 자료의 작은 표본에서는 LLM의 정보 보존 범위가 더 넓었지만, LLM 역시 오인식과 잘못된 Markdown 표를 생성했습니다.

## 결과물과 재현

- [설정 및 실행 안내](../ocr/README.md)
- [PaddleOCR 최종 Markdown](../markdown/ocr_comparison/vlm_pdf_final/KC인증서_안전확인_신고증명서_노트북_컴퓨터_N5800_20260107_pdf/result.md)
- [기존 LLM Markdown](../markdown/ocr_comparison/llm_pdf/KC인증서_안전확인_신고증명서_노트북_컴퓨터_N5800_20260107_pdf/result.md)
- [DOCX Markdown](../markdown/ocr_comparison/native/vlm/_TG_NPC_제품제안서_A650_16인치_Jirisan_AMD_Kracken_RTX5070__Ver_1.0_20250415.md)
- [HWP Markdown](../markdown/ocr_comparison/native/vlm/붙임1_SW종사자_표준근로계약서.md)
- [체크포인트별 통과/불일치 표](../markdown/ocr_comparison/review/checkpoints.md)
- [점수 원자료](../markdown/ocr_comparison/review/scores.json)
- [페이지별 Markdown 구조 검사](../markdown/ocr_comparison/review/markdown_qa.json)
- [실제 PDF 파서 연결 결과](../markdown/ocr_comparison/parser_smoke/result.md)

프로젝트 루트에서 전체 재실행:

```powershell
.\.venv\Scripts\python.exe tests/evaluate_ocr.py --backend vlm --out markdown/ocr_evaluation
.\.venv\Scripts\python.exe tests/evaluate_ocr.py --backend llm --out markdown/ocr_evaluation
```

점수는 `tests/score_ocr.py --vlm <VLM summary.json 폴더> --llm <LLM summary.json 폴더> --out <평가 폴더>`로
재계산합니다. 기준은 [ocr_checkpoints.json](ocr_checkpoints.json)에 저장했고 원본 SHA-256도 검사합니다.
각 결과 폴더에 페이지별 PNG/텍스트, `result.md`, 시간·오류·원본 해시를 포함한 `summary.json`을 보관했습니다.
`markdown/`은 저장소의 기존 `.gitignore` 대상이므로 실제 산출물은 로컬에 보관되고 평가 문서/실행 도구는 코드와 함께 관리할 수 있습니다.

이번 실행 환경에서는 앱 가상환경의 기본 Python 경로가 접근되지 않아 같은 Python 3.12인
`C:/TG_AI/Python312/python.exe`에 앱 `.venv/Lib/site-packages`를 지정하여 실행했습니다.
PaddleOCR 작업 프로세스는 요청받은 별도 가상환경의 Python을 그대로 사용했습니다.
공식 API와 설치 소스를 확인한 기준: [PaddleOCR-VL 공식 구현](https://github.com/PaddlePaddle/PaddleOCR/blob/main/paddleocr/_pipelines/paddleocr_vl.py).
