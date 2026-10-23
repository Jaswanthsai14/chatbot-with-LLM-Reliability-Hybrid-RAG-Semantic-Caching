
from langchain_core.documents import Document

from db import db2



SEMANTIC_K = 5


def hybrid_retrieve1(query: str, k: int ) -> list[Document]:
    

    if not query or not query.strip():
        return []

    results = db2.similarity_search(
        query.strip(),
        k=k
    )

    return results
