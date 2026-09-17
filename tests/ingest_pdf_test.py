from rag.ingest import ingest_pdf_image





if __name__ == "__main__":
    from langchain_ollama import ChatOllama
    from agent.llm_provider import set_llm_model

    llm = ChatOllama(model="qwen3.8:27b", num_ctx=65536)
    set_llm_model(model=llm)

    nomal_path = r"D:\TG_Input_API\TG_Input_API_사용_가이드v1.3.pdf"

    chunks = ingest_pdf_image(nomal_path)
    parts = []
    for chunk in chunks:
        parts.append(chunk)
