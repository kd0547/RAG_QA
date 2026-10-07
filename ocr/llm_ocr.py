import base64

from langchain_core.messages import HumanMessage
from agent.llm_provider import get_llm_model


OCR_PROMPT = """
당신은 기업 문서에 포함된 이미지를 분석해 검색(RAG) 시스템에 저장할 설명을 만드는 어시스턴트입니다.

다음 우선순위로 판단하고 작성하세요:

1. 이미지 안에 텍스트가 있으면, 그 텍스트를 그대로 정확히 추출하세요. (표, 라벨, 코드, 캡션 등 포함)

2. 텍스트가 없고 다이어그램/차트/스크린샷/아이콘 흐름도처럼 정보를 전달하는 이미지라면,
   그 이미지가 전달하는 내용(구조, 관계, 프로세스, 데이터)을 핵심 위주로 간결하게 설명하세요.
   색상이나 모양 같은 시각적 디테일은 정보 전달과 무관하면 생략하세요.

3. 색상 그라데이션, 기하학적 도형, 로고 조각처럼 순수 디자인/배경 장식 요소이고
   문서 내용과 무관하다고 판단되면, 다음 한 문장으로만 답하세요:
   "장식용 이미지이며 문서 내용과 관련된 정보 없음."

불필요한 서론이나 반복 표현("이미지에는 텍스트가 없습니다" 등) 없이 바로 본론만 작성하세요.
"""

# 파일 시그니처(매직 바이트) -> MIME 타입
_IMAGE_SIGNATURES = {
    b"\x89PNG": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF8": "image/gif",
    b"BM": "image/bmp",
}


def ocr_image(image_bytes: bytes) -> str:
    """이미지 바이트를 LLM에 보내 텍스트 추출/설명 결과를 반환한다."""
    llm = get_llm_model(mode="local")
    b64_image = base64.b64encode(image_bytes).decode(encoding="utf-8")
    message = HumanMessage(content=[
        {"type": "text", "text": OCR_PROMPT},
        {
            "type": "image_url",
            "image_url": {"url": f"data:{_detect_mime(image_bytes)};base64,{b64_image}"}
        }
    ])
    response = llm.invoke([message])
    return response.content


def _detect_mime(image_bytes: bytes) -> str:
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    for signature, mime in _IMAGE_SIGNATURES.items():
        if image_bytes.startswith(signature):
            return mime
    return "image/png"
