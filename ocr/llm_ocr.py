import base64
import re

from langchain_core.messages import HumanMessage
from agent.llm_provider import get_llm_model
from ocr.base import OCRBackend



OCR_PROMPT = """
당신은 기업 문서의 이미지(스캔된 문서 페이지, 또는 문서에 포함된 그림)를 텍스트로 변환해
검색(RAG) 시스템에 저장하는 OCR 어시스턴트입니다.
이미지의 모든 요소를 읽기 순서(위→아래, 왼쪽→오른쪽)대로 출력하되, 요소 종류별로 아래 규칙을 따르세요.
여러 종류가 섞여 있으면 각 요소에 해당 규칙을 적용하세요.

## 1. 텍스트
- 보이는 텍스트를 빠짐없이 원문 그대로 옮겨 적으세요. 요약, 해석, 오탈자 수정을 하지 마세요.
- 제목은 마크다운 제목(#, ##)으로 쓰고, 목록은 원래 번호나 기호를 유지하세요.
- 코드는 코드 블록으로 감싸세요.
- 흐리거나 가려져 읽을 수 없는 글자는 추측하지 말고 [판독불가]로 표시하세요.

## 2. 표
- 마크다운 표로 작성하세요. 병합된 셀은 내용을 한 번만 적고 나머지 칸은 비워두세요.
- 숫자, 단위, 기호(±, ≤, ℃, μm 등)는 표기된 그대로 옮기세요.
- 체크박스는 체크 여부에 따라 ☑ 또는 ☐로 표시하세요.

## 3. 그래프·차트
그래프가 있는 위치에 아래 형식으로 작성하세요.
<figure type="chart">
- 제목:
- 유형: (꺾은선, 막대, 산점도, 원형 등)
- X축: 축 이름(단위), 범위
- Y축: 축 이름(단위), 범위
- 범례: 계열 이름
- 데이터: 그래프에 숫자로 표기된 값은 마크다운 표로 정확히 옮기세요.
  숫자 표기 없이 눈금으로 읽어야 하는 값은 앞에 "약"을 붙여 근삿값으로 적고,
  눈금으로도 읽기 어려우면 값을 만들지 말고 생략하세요.
- 기준선: 허용 한계, 규격값, 목표값 등 표시된 선이 있으면 그 값과 의미
- 요약: 추세, 최대·최소, 기준 초과 여부 등 그래프가 보여주는 핵심을 1~3문장으로
- 축과 데이터 레이블의 단위·기호(×, %, ℃ 등)는 원본 표기를 그대로 쓰고, 근삿값은 눈금 간격에 맞는 자릿수로 통일하세요.
</figure>

## 4. 사진·그림·도면·스크린샷
<figure type="image">
- 캡션: 그림 번호와 캡션이 있으면 그대로
- 내용: 무엇을 보여주는지 사실 위주로 1~3문장 (예: 제품 외관, 시료 상태, 장비 구성, 불량·파단 부위)
- 표기: 그림 안의 라벨, 화살표 설명, 치수, 텍스트를 그대로
</figure>
<figure type="diagram">
- 캡션: 그림 번호와 캡션이 있으면 그대로
- 구성: 영역이나 단계별로, 그 안의 텍스트를 원문 그대로 한 번씩만 적으세요.
  원본에 화살표나 선으로 연결된 요소만 "A → B"로 적으세요.
</figure>
- 다이어그램이나 흐름도는 type="diagram"으로 쓰고, 구성 요소와 연결 관계를 "A → B → C"처럼 적으세요.
- 스크린샷은 type="screenshot"으로 쓰고, 어떤 화면인지와 화면 속 주요 항목·값을 적으세요.
- 제품명, 부품명, 모델명 등 고유명사가 보이면 검색에 쓰이도록 반드시 포함하세요.
- 눈에 보이는 것만 설명하고, 보이지 않는 원인이나 결론은 추측하지 마세요.
- 색상이나 모양 같은 시각적 디테일은 정보 전달과 무관하면 생략하세요.
- 아이콘이나 삽화는 그 자체가 정보를 담을 때만 짧게 언급하고, 장식용 그림의 세부 모양은 묘사하지 마세요.
- 다른 항목과 구별되게 일부만 강조된 경우에만 강조를 표시하세요. 모든 제목·라벨에 똑같이 적용된 디자인 스타일은 강조가 아닙니다.

## 5. 공통
- 출력은 문서의 언어로 작성하세요. 원문에 없는 한자나 중국어, 다른 언어 표현을 섞지 마세요.
- 특정 항목이나 셀이 테두리, 강조색, 화살표, 굵은 글씨 등으로 강조되어 있으면 어떤 항목이 강조되었는지 적으세요.
- 도장, 서명, 로고는 [도장], [서명], [로고]로 표시하세요. 안의 글자가 선명하게 읽히면 [도장: 글자], [로고: 글자]로 적으세요.
- 머리글, 바닥글, 페이지 번호도 그대로 포함하세요.
- 배경 무늬나 구분선 같은 순수 장식 요소는 생략하세요.
- 서론이나 맺음말, 반복 표현("이미지에는 텍스트가 없습니다" 등) 없이 변환 결과만 출력하세요.
"""

# 파일 시그니처(매직 바이트) -> MIME 타입
_IMAGE_SIGNATURES = {
    b"\x89PNG": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF8": "image/gif",
    b"BM": "image/bmp",
}


class LLMOCR(OCRBackend):
    name = "llm"

    def ocr_image(self, image_bytes: bytes) -> str:
        return ocr_image(image_bytes)


def ocr_image(image_bytes: bytes) -> str:
    """기존 직접 호출 호환용. 환경 선택은 ocr.provider.ocr_image를 사용한다."""
    text, _ = ocr_image_with_meta(image_bytes)
    return text


def ocr_image_with_meta(image_bytes: bytes, prompt: str = OCR_PROMPT, llm=None) -> tuple[str, dict]:
    llm = llm if llm is not None else get_llm_model(mode="local")
    b64_image = base64.b64encode(image_bytes).decode(encoding="utf-8")
    message = HumanMessage(content=[
        {"type": "text", "text": prompt},
        {
            "type": "image_url",
            "image_url": {"url": f"data:{_detect_mime(image_bytes)};base64,{b64_image}"}
        }
    ])
    response = llm.invoke([message])
    content = response.content
    if isinstance(content, list):
        content = "".join(
            part if isinstance(part, str) else part.get("text", "")
            for part in content
            if isinstance(part, str) or (isinstance(part, dict) and part.get("type", "text") == "text")
        )
    if not isinstance(content, str):
        raise TypeError(f"지원하지 않는 OCR 응답: {type(content).__name__}")
    text = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    return text, dict(getattr(response, "usage_metadata", None) or {})


def _detect_mime(image_bytes: bytes) -> str:
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    for signature, mime in _IMAGE_SIGNATURES.items():
        if image_bytes.startswith(signature):
            return mime
    return "image/png"
