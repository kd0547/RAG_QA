import json

from langchain_ollama import OllamaEmbeddings
from langchain_openai import ChatOpenAI

from agent.llm_provider import set_llm_model
from agent.rag_agent import run_agent
from retrieval.embedder import set_embedding_model

embedding_model = OllamaEmbeddings(
    model="bge-m3:latest")

set_embedding_model(embedding_model)

llm = ChatOpenAI(
        model="qwen3.8-flash-next",  # vLLM 실행 시 지정한 served-model-name
        base_url="http://14.38.199.190:9090/v1",
        api_key="dummy",  # vLLM은 인증 안 하지만 파라미터는 필수라 아무 값이나 넣어야 함
        max_tokens=65536,  # num_ctx 대신 이렇게, 필요시 조정
    )
set_llm_model(llm)


agent = run_agent(
    question="N5800 하드웨어 사양 알려줘",
    mode="local",
)
print(
    json.dumps(
        agent["sources"],
        ensure_ascii=False,
        indent=2,
    )
)