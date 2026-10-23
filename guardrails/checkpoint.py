# guardrail_check.py

from db import db1


TOP_K = 5
BLOCK_THRESHOLD = 0.75



def check_guardrail(user_query: str) -> bool:
    results = db1.similarity_search_with_score(
        user_query,
        k=TOP_K,
    )

    print(BLOCK_THRESHOLD)

    malicious_score = 0.0
    benign_score = 0.0

    for document, distance in results:
        label = document.metadata.get("label", "").lower()

        # Assumes cosine distance.
        similarity = max(0.0, min(1.0, 1.0 - float(distance)))

        if label == "benign":
            benign_score = max(benign_score, similarity)
        else:
            malicious_score = max(malicious_score, similarity)

    if malicious_score >= BLOCK_THRESHOLD:
        return True

   

    return False