from pydantic import BaseModel, Field

# ---------- 판단용 구조화 출력 ----------

class AnswerabilityCheck(BaseModel):
    is_answerable: bool = Field(description="검색된 문서만으로 질문에 답할 수 있는지 여부")
    reason: str = Field(description="판단 근거를 한두 문장으로")
