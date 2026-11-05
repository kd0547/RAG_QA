# OCR 백엔드 선택

프로젝트 루트 `.env`에 다음을 설정한 뒤 앱을 재시작합니다.

```dotenv
OCR_BACKEND=vlm
PADDLEOCR_HOME=C:/TG_AI_DEV/paddleocr_vl_test
PADDLEOCR_DEVICE=gpu:0
PADDLEOCR_TIMEOUT=300
```

`OCR_BACKEND=llm`이면 기존 `LLM_BASE_URL`, `LLM_MODEL`, `VLLM_API_KEY` 및
서버 시작 시 주입한 LLM을 사용합니다. 기본값은 `llm`입니다.
알 수 없는 백엔드 값이나 모델 오류를 다른 백엔드로 자동 우회하지 않습니다.

`vlm`은 `PADDLEOCR_HOME/.venv/Scripts/python.exe`와 그 폴더에 설치된
PaddleOCR 3.6.0 / PaddleX 3.6.1 / PaddleOCR-VL-1.6 및 PP-DocLayoutV3를
재사용합니다. Linux의 기본 Python 경로는 `.venv/bin/python`입니다.
Python 또는 모델 위치가 다르면 `.env.example`의 `PADDLEOCR_PYTHON`,
`PADDLEOCR_VL_MODEL_DIR`, `PADDLEOCR_LAYOUT_MODEL_DIR`를 지정합니다.
Paddle 패키지를 이 앱의 requirements에 중복 설치할 필요가 없습니다.

## 호출과 적용 범위

```python
from ocr.provider import ocr_image
markdown = ocr_image(image_bytes)
```

- `OCRBackend` 추상 클래스 아래 `LLMOCR`, `VLMOCR`를 둡니다.
- `parser/file_parser.py`의 이미지 처리, PDF 그림/스캔 페이지 처리,
  사양표 이미지 가져오기 API, `ocr/ocr_pdf.py`는 공통 선택 경로를 사용합니다.
- 기존 `ocr.llm_ocr.ocr_image` 직접 호출은 LLM 방식으로 호환됩니다.
- DOCX/HWP는 기존 텍스트·표 파서를 유지합니다. 삽입 사진 OCR은 이 파서들의
  기존 지원 범위에 포함되지 않으며, 환경변수 선택으로 추가되지 않습니다.
- VLM은 자체 프로세스에서 모델을 한 번 로드해 재사용하고 요청을 직렬 처리합니다.
  서버 프로세스가 여러 개면 프로세스별 모델이 생성되어 GPU 메모리 사용이 늘어납니다.
- 제한 시간에는 첫 요청 모델 로딩이 포함됩니다. 오류·시간 초과 시 작업 프로세스를
  종료하고, 다음 호출 시 다시 생성합니다. 앱 종료 때도 정리합니다.
- 실행 로그와 임시 캐시는 `temp/paddleocr`에 저장합니다. 원본 모델은 수정하지 않습니다.

## 출력 특성

LLM 프롬프트는 기존 내용을 유지합니다. 문자열/텍스트 블록 응답을 문자열로 통일하고
`<think>` 블록을 제거합니다. VLM의 HTML 표는 병합 셀을 빈 칸으로 펼친 Markdown
표로 바꿉니다. 표 내용의 `|`는 이스케이프합니다.

VLM은 사진 설명을 생성하지 않으며 사진/로고/2D 코드 위치를 `[이미지]`로 표시합니다.
`use_ocr_for_image_block=False`로 QR/장식 이미지의 잘못된 문자 생성을 억제합니다.
본문·표 위주의 OCR이므로 사진 안에 포함된 라벨이나 시각적 의미는 LLM과 결과가 다릅니다.
출력에 존재하지 않는 crop 경로나 큰 base64 이미지 문자열을 넣지 않습니다.

## 재현 명령 (프로젝트 루트)

```powershell
$env:OCR_BACKEND='vlm'
.\.venv\Scripts\python.exe -m ocr.ocr_pdf tests/data --out markdown/ocr_results/vlm

# PDF/이미지는 전체 페이지 OCR, DOCX/HWP는 기존 파서로 실행하고 메타데이터 기록
.\.venv\Scripts\python.exe tests/evaluate_ocr.py --backend vlm --out markdown/ocr_evaluation
.\.venv\Scripts\python.exe tests/evaluate_ocr.py --backend llm --out markdown/ocr_evaluation

# 모델/네트워크 없이 실행하는 회귀 테스트
.\.venv\Scripts\python.exe -m pytest tests/test_ocr_backend.py tests/test_spec_import.py -q
```

LLM 실측 테스트는 설정된 서버로 문서 이미지를 전송합니다.
`run_ocr`는 페이지별 PNG/텍스트, `result.md`, 시간·글자 수·오류를 담은
`summary.json`을 저장합니다. 오류가 있는 CLI 실행은 종료 코드 1을 반환합니다.
`evaluate_ocr.py`는 파일별 SHA-256, 실행 시간, OCR 사용 여부를 추가 기록합니다.

API 참고: [PaddleOCR 공식 구현](https://github.com/PaddlePaddle/PaddleOCR/blob/main/paddleocr/_pipelines/paddleocr_vl.py).
현재 설치된 버전의 소스와 인자 정의를 함께 확인했습니다.

## 전체 문자 평가

[추가 PDF/JPG 7개·80페이지 이미지 OCR 비교](../tests/ocr_dataset_evaluation_2026-11-05.md)는
PDF를 페이지 이미지로 렌더링한 뒤 기존 LLM과 PaddleOCR-VL에 같은 입력을 넣은 후속 평가입니다.

[전체 문자 CER 평가표](../tests/ocr_character_evaluation_2026-11-05.md)와
[21쪽 참조 전사본의 작성 기준](../tests/ocr_reference/kc_n5800/README.md)을 제공합니다.
본문·표·머리글·바닥글·캡션을 전수 비교하고 사진 내부는 제외합니다.
전사본은 AI 보조로 원문 대조했으며 독립적인 사람 검수 전의 평가입니다.

```powershell
# 저장된 결과 재채점: 모델/네트워크 호출 없음
.\.venv\Scripts\python.exe tests/score_ocr_cer.py

# 채점기 및 기존 백엔드/연동 회귀 테스트
.\.venv\Scripts\python.exe -m pytest tests/test_ocr_cer.py tests/test_ocr_backend.py tests/test_spec_import.py -q
```

`tests/run_ocr_transcription.py`의 문자 전사 전용 프롬프트는 비교 실험용입니다.
앱에서 사용하는 기존 `OCR_PROMPT`는 그대로 유지합니다.
