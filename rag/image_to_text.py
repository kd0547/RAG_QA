import os.path

import pymupdf
import base64

from langchain_core.messages import HumanMessage
from agent.llm_provider import get_llm_model
from rag.type import Page


def image2base64(bytes_image):
    return base64.b64encode(bytes_image).decode(encoding="utf-8")


def run_llm(bytes_image,image_ext: str = "png"):
    """

    :param bytes_image:
    :return:
    """

    SystemPrompt = """
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


    llm = get_llm_model(mode="local")
    bytes_image = bytes_image   # 실제 PNG/JPEG bytes
    b64_image= image2base64(bytes_image)
    message = HumanMessage(content=[
        {"type": "text", "text": SystemPrompt},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/{image_ext};base64,{b64_image}"}
        }
    ])
    response = llm.invoke([message])
    return response.content

def image_to_text_from_pdf(current_page:Page) -> None:
    """PDF의 특정 페이지에 포함된 이미지들을 추출해 LLM으로 설명을 생성한다.
    :param current_page:
    """
    for box in current_page.boxes:
        if box.boxclass != "picture" or box.image is None:
            continue

        if not os.path.isfile(box.image):
            print(f"{box.image}파일이 존재하지 않습니다.")
            continue

        image_path = box.image
        with open(image_path, "rb") as f:
            bytes_image = f.read()
        result = run_llm(bytes_image)
        box.image_description = result
        #print("=" * 50)
        #print(result)
        #print("=" * 50)

        #print(f"[Page {current_page.page_number}] {box.image} -> {result[:50]}...")





