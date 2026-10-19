import logging
import time

from sentence_transformers import CrossEncoder

RERANK_MODEL = "BAAI/bge-reranker-v2-m3"

logger = logging.getLogger(__name__)

model = None
def load_rerank():
    global model

    if model is None:
        try :
            started = time.perf_counter()
            model = CrossEncoder(RERANK_MODEL, max_length=512)
            logger.info("리랭커 로드 완료: %s (%.1f초)", RERANK_MODEL, time.perf_counter() - started)
            return True
        except Exception:
            # 실패해도 서버는 뜨지만 rerank()가 빈 목록만 돌려줘 답변 품질이 떨어진다
            logger.exception("리랭커 로드 실패: %s — 재정렬 없이 동작합니다", RERANK_MODEL)
            return False
    return True

def rerank(user_content, documents: list[dict], top_n: int = 5):
    if model is None:
        logger.warning("리랭커가 로드되지 않아 재정렬 결과 없음: 후보 %d건", len(documents))
        return []

    pairs = [(user_content, doc["text"]) for doc in documents]
    scores = model.predict(pairs)

    reranked = sorted(zip(documents, scores), key=lambda x: x[1], reverse=True)[:top_n]
    return [doc for doc, score in reranked]
