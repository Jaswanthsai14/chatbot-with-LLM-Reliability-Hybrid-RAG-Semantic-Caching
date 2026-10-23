
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from sentence_transformers import CrossEncoder

from db import db2


# Configuration
BM25_K = 20
SEMANTIC_K = 20
FINAL_K = 5

RRF_K = 60
RERANK_CANDIDATES = 30

RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def normalize_text(text: str) -> str:
    return " ".join(text.split())


def load_history_documents() -> list[Document]:
    result = db2.get(include=["documents", "metadatas"])

    contents = result.get("documents") or []
    metadatas = result.get("metadatas") or []

    documents = []
    seen = set()

    for i, content in enumerate(contents):
        if not content or not content.strip():
            continue

        key = normalize_text(content)

        if key in seen:
            continue

        seen.add(key)

        metadata = (
            metadatas[i] or {}
            if i < len(metadatas)
            else {}
        )

        documents.append(
            Document(
                page_content=content,
                metadata=metadata,
            )
        )

    return documents


# Initialize once
history_documents = load_history_documents()

bm25_retriever = None

if history_documents:
    bm25_retriever = BM25Retriever.from_documents(
        history_documents
    )
    bm25_retriever.k = BM25_K

reranker = CrossEncoder(RERANK_MODEL)


def hybrid_retrieve(
    query: str,
    k: int = FINAL_K,
) -> list[Document]:

    if not query or not query.strip() or k <= 0:
        return []

    if bm25_retriever is None:
        return []

    query = query.strip()

    # 1. Keyword retrieval
    keyword_docs = bm25_retriever.invoke(query)

    # 2. Semantic retrieval
    semantic_docs = db2.similarity_search(
        query,
        k=SEMANTIC_K,
    )

    # 3. RRF fusion using normalized content
    fused_scores = {}
    document_lookup = {}

    for docs in (keyword_docs, semantic_docs):
        seen_in_list = set()

        for rank, doc in enumerate(docs, start=1):
            doc_id = normalize_text(doc.page_content)

            if doc_id in seen_in_list:
                continue

            seen_in_list.add(doc_id)
            document_lookup[doc_id] = doc

            fused_scores[doc_id] = (
                fused_scores.get(doc_id, 0.0)
                + 1.0 / (RRF_K + rank)
            )

    if not fused_scores:
        return []

    ranked_ids = sorted(
        fused_scores,
        key=fused_scores.get,
        reverse=True,
    )

    # 4. Select candidates for reranking
    candidate_ids = ranked_ids[
        :min(len(ranked_ids), max(k, RERANK_CANDIDATES))
    ]

    candidates = [
        document_lookup[doc_id]
        for doc_id in candidate_ids
    ]

    # 5. Cross-Encoder reranking
    pairs = [
        (query, doc.page_content)
        for doc in candidates
    ]

    scores = reranker.predict(
        pairs,
        show_progress_bar=False,
        batch_size=16,
    )

    reranked = sorted(
        zip(candidates, scores),
        key=lambda item: float(item[1]),
        reverse=True,
    )

    # 6. Return top-k documents with diagnostic scores
    results = []

    for doc, score in reranked[:k]:
        doc_id = normalize_text(doc.page_content)

        results.append(
            Document(
                page_content=doc.page_content,
                metadata={
                    **doc.metadata,
                    "rrf_score": float(fused_scores[doc_id]),
                    "rerank_score": float(score),
                },
            )
        )

    return results
