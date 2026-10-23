
import json
import uuid
import numpy as np
import redis

from celery import Celery
from sentence_transformers import SentenceTransformer


REDIS_URL = "redis://localhost:6379/0"
SIMILARITY_THRESHOLD = 0.75
CACHE_TTL = 172800

redis_client = redis.Redis.from_url(
    REDIS_URL,
    decode_responses=True
)

celery = Celery(
    "semantic_cache",
    broker=REDIS_URL,
    backend=REDIS_URL
)

embedding_model = SentenceTransformer(
    "sentence-transformers/all-MiniLM-L6-v2"
)


def embed_query(query: str) -> np.ndarray:
    """Generate a normalized embedding."""
    vector = embedding_model.encode(
        query,
        convert_to_numpy=True,
        normalize_embeddings=True
    )

    return np.asarray(vector, dtype=np.float32)


def cosine_similarity(vec1, vec2) -> float:
    """Calculate cosine similarity safely."""

    vec1 = np.asarray(vec1, dtype=np.float32).flatten()
    vec2 = np.asarray(vec2, dtype=np.float32).flatten()

    if vec1.shape != vec2.shape:
        raise ValueError(
            f"Embedding dimension mismatch: "
            f"{vec1.shape} vs {vec2.shape}"
        )

    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)

    if norm1 == 0 or norm2 == 0:
        return 0.0

    # General cosine similarity formula
    similarity = np.dot(vec1, vec2) / (norm1 * norm2)

    return float(np.clip(similarity, -1.0, 1.0))


def get_cached_response(
    query: str,
    threshold: float = SIMILARITY_THRESHOLD
) -> str | None:

    if not query or not query.strip():
        return None

    query_vector = embed_query(query.strip())

    best_similarity = None
    best_response = None
    compared_entries = 0
    skipped_entries = 0

    for key in redis_client.scan_iter(
        match="semantic_cache:entry:*",
        count=100
    ):
        cached = redis_client.get(key)

        if not cached:
            continue

        try:
            entry = json.loads(cached)

            stored_vector = np.asarray(
                entry["embedding"],
                dtype=np.float32
            ).flatten()

            similarity = cosine_similarity(
                query_vector,
                stored_vector
            )

            compared_entries += 1

            print(
                f"Compared with: {entry.get('query', 'unknown')} "
                f"| similarity: {similarity:.4f}"
            )

            if (
                best_similarity is None
                or similarity > best_similarity
            ):
                best_similarity = similarity
                best_response = entry.get("response")

        except (ValueError, KeyError, TypeError) as error:
            skipped_entries += 1
            print(f"Skipping invalid cache entry {key}: {error}")

    print(
        f"Cache debug | compared={compared_entries}, "
        f"skipped={skipped_entries}"
    )

    if (
        best_response is not None
        and best_similarity is not None
        and best_similarity >= threshold
    ):
        print(f"Semantic cache HIT: {best_similarity:.4f}")
        return best_response

    score = (
        f"{best_similarity:.4f}"
        if best_similarity is not None
        else "N/A (no valid entries)"
    )

    print(f"Semantic cache MISS: {score}")
    return None


@celery.task(name="cache.store_response")
def store_response_task(query: str, response: str) -> bool:

    if not query or not query.strip():
        return False

    if not response or not response.strip():
        return False

    query = query.strip()
    response = response.strip()

    vector = embed_query(query)

    entry = {
        "query": query,
        "embedding": vector.tolist(),
        "response": response
    }

    key = f"semantic_cache:entry:{uuid.uuid4().hex}"

    redis_client.set(
        key,
        json.dumps(entry),
        ex=CACHE_TTL
    )

    print(f"Stored cache entry: {query}")
    return True


def cache_response(query: str, response: str):
    """Queue cache insertion using Celery."""
    return store_response_task.delay(query, response)
