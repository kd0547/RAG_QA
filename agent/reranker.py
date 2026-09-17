from sentence_transformers import CrossEncoder

model = None
def load_rerank():
    global model

    if model is None:
        try :
            model = CrossEncoder("BAAI/bge-reranker-v2-m3", max_length=512)
            return True
        except Exception as e:
            print(e)
            return False
    return True

def rerank(user_content, documents: list[dict], top_n: int = 5):
    if model is None:
        return []

    pairs = [(user_content, doc["text"]) for doc in documents]
    scores = model.predict(pairs)

    reranked = sorted(zip(documents, scores), key=lambda x: x[1], reverse=True)[:top_n]
    return [doc for doc, score in reranked]