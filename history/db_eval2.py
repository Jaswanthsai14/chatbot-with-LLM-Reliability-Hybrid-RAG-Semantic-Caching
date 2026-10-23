
import os
import json
import time
import logging
import math

from pathlib import Path
from datetime import datetime, timezone
from typing import List

from dotenv import load_dotenv
from langsmith import Client, evaluate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from history.retrieve import hybrid_retrieve

load_dotenv()


# =========================================================
# Configuration
# =========================================================

DATASET_NAME = "Indian-History-RAG-No-Expected-Answers"

JSONL_FILE = (
    Path(__file__).resolve().parent
    / "id4.jsonl"
)

EXPERIMENT_PREFIX = "hybrid-retrieval-no-reference-eval"

TOP_K = 5
GEMINI_MODEL = "gemini-2.5-flash"


# =========================================================
# Environment and clients
# =========================================================

LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not LANGSMITH_API_KEY:
    raise ValueError("LANGSMITH_API_KEY is missing from .env")

if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY is missing from .env")


client = Client(api_key=LANGSMITH_API_KEY)

judge_llm = ChatGoogleGenerativeAI(
    model=GEMINI_MODEL,
    temperature=0,
    google_api_key=GOOGLE_API_KEY,
)


# =========================================================
# Logging
# =========================================================

logger = logging.getLogger("rag_retrieval_eval")
logger.setLevel(logging.INFO)
logger.handlers.clear()

file_handler = logging.FileHandler(
    "rag_retrieval_eval.log",
    encoding="utf-8",
)

file_handler.setFormatter(
    logging.Formatter("%(message)s")
)

logger.addHandler(file_handler)


def log_json(record: dict):
    logger.info(
        json.dumps(
            record,
            ensure_ascii=False,
            default=str,
        )
    )


# =========================================================
# Structured evaluation output
# =========================================================

class RetrievalEvaluation(BaseModel):
    document_relevance: List[int] = Field(
        description=(
            "One relevance score per retrieved document, "
            "in ranking order. "
            "0=irrelevant, 1=partially relevant, "
            "2=relevant, 3=highly relevant."
        )
    )

    context_relevance: float = Field(
        description=(
            "Overall relevance of the retrieved documents "
            "to the query, between 0 and 1."
        )
    )


# =========================================================
# Gemini relevance judge
# No expected answer is provided
# =========================================================

judge_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
You are a strict evaluator for an Indian History RAG retriever.

Evaluate retrieval quality using only the user's query
and the retrieved documents.

There is NO expected answer or reference answer.

Rules:

1. Evaluate each retrieved document independently.
2. Score every document using an integer:
   0 = irrelevant
   1 = partially relevant
   2 = relevant
   3 = highly relevant.
3. Judge whether the document contains useful information
   for answering the actual question.
4. Do not reward a document merely for mentioning a
   related historical keyword.
5. Do not assume unsupported historical claims are correct.
6. Context relevance must be between 0 and 1.
7. Return exactly one document relevance score per
   retrieved document, in the original ranking order.
8. If no documents are provided, do not invoke this judge.
"""
    ),
    (
        "human",
        """
Query:
{query}

Retrieved documents, in ranking order:
{documents}

Evaluate retrieval quality.
"""
    ),
])

judge = judge_prompt | judge_llm.with_structured_output(
    RetrievalEvaluation
)


# =========================================================
# LangSmith dataset setup
# =========================================================

def get_or_create_dataset():
    try:
        dataset = client.read_dataset(
            dataset_name=DATASET_NAME
        )

        log_json({
            "event": "dataset_reused",
            "dataset": DATASET_NAME,
        })

    except Exception:
        dataset = client.create_dataset(
            dataset_name=DATASET_NAME,
            description=(
                "Indian History RAG retrieval evaluation "
                "using queries without expected answers."
            ),
        )

        log_json({
            "event": "dataset_created",
            "dataset": DATASET_NAME,
        })

    return dataset


def upload_dataset_if_empty(dataset):
    existing = list(
        client.list_examples(
            dataset_id=dataset.id,
            limit=1,
        )
    )

    if existing:
        log_json({
            "event": "upload_skipped",
            "reason": "Dataset already contains examples",
            "dataset": DATASET_NAME,
        })
        return

    if not JSONL_FILE.exists():
        raise FileNotFoundError(
            f"Dataset file not found: {JSONL_FILE}"
        )

    count = 0

    with JSONL_FILE.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {line_number}: {exc}"
                ) from exc

            query = record.get("query")

            if not isinstance(query, str) or not query.strip():
                raise ValueError(
                    f"Missing or empty query on line {line_number}"
                )

            # Upload inputs only. No expected answer.
            client.create_example(
                dataset_id=dataset.id,
                inputs={
                    "query": query.strip(),
                },
            )

            count += 1

    if count == 0:
        raise ValueError("The JSONL dataset contains no queries.")

    log_json({
        "event": "dataset_uploaded",
        "dataset": DATASET_NAME,
        "examples_uploaded": count,
    })

    print(f"Uploaded {count} queries to LangSmith.")


# =========================================================
# Retrieval target
# =========================================================

def target(inputs: dict) -> dict:
    query = inputs["query"]

    start = time.perf_counter()

    documents = hybrid_retrieve(
        query,
        k=TOP_K,
    )

    retrieval_latency_ms = (
        time.perf_counter() - start
    ) * 1000

    document_texts = [
        doc.page_content
        for doc in documents
    ]

    context = "\n\n".join(document_texts)

    return {
        "documents": document_texts,
        "context": context,
        "retrieval_latency_ms": retrieval_latency_ms,
    }


# =========================================================
# Metric calculation
# =========================================================

def calculate_metrics(relevance: list[int]) -> dict:
    """
    Scores 2 and 3 count as relevant.

    These metrics are estimates because the relevance labels
    are generated by an LLM judge, not human ground truth.
    """

    if not relevance:
        return {
            "precision_at_k": 0.0,
            "mrr": 0.0,
            "ndcg_at_k": 0.0,
        }

    binary_relevance = [
        1 if score >= 1 else 0
        for score in relevance
    ]

    # Precision@K
    precision_at_k = (
        sum(binary_relevance) / len(binary_relevance)
    )

    # Mean Reciprocal Rank for this individual query
    mrr = 0.0

    for rank, is_relevant in enumerate(
        binary_relevance,
        start=1,
    ):
        if is_relevant:
            mrr = 1.0 / rank
            break

    # NDCG@K with graded relevance
    dcg = sum(
        (2**score - 1) / math.log2(rank + 1)
        for rank, score in enumerate(relevance, start=1)
    )

    ideal_relevance = sorted(
        relevance,
        reverse=True,
    )

    idcg = sum(
        (2**score - 1) / math.log2(rank + 1)
        for rank, score in enumerate(
            ideal_relevance,
            start=1,
        )
    )

    ndcg_at_k = dcg / idcg if idcg else 0.0

    return {
        "precision_at_k": precision_at_k,
        "mrr": mrr,
        "ndcg_at_k": ndcg_at_k,
    }


# =========================================================
# Retrieval evaluator
# =========================================================

def evaluate_retrieval(
    inputs: dict,
    outputs: dict,
) -> list[dict]:

    query = inputs["query"]
    documents = outputs.get("documents", [])

    if not documents:
        relevance = []
        context_relevance = 0.0

    else:
        evaluation = judge.invoke({
            "query": query,
            "documents": json.dumps(
                documents,
                ensure_ascii=False,
            ),
        })

        relevance = [
            max(0, min(3, int(score)))
            for score in evaluation.document_relevance
        ]

        # Ensure one score per retrieved document
        relevance = relevance[:len(documents)]

        if len(relevance) < len(documents):
            relevance.extend(
                [0] * (len(documents) - len(relevance))
            )

        context_relevance = max(
            0.0,
            min(1.0, evaluation.context_relevance),
        )

    metrics = calculate_metrics(relevance)

    metrics["context_relevance"] = context_relevance

    metrics["retrieval_latency_ms"] = max(
        0.0,
        float(outputs.get("retrieval_latency_ms", 0.0)),
    )

    log_json({
        "event": "retrieval_evaluation",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "retrieved_count": len(documents),
        "document_relevance": relevance,
        "metrics": metrics,
    })

    print(f"\nQuery: {query}")
    print(f"Retrieved documents: {len(documents)}")
    print(f"Relevance scores: {relevance}")

    for key, value in metrics.items():
        print(f"{key}: {value:.4f}")

    return [
        {
            "key": key,
            "score": value,
        }
        for key, value in metrics.items()
    ]


# =========================================================
# Run evaluation
# =========================================================

if __name__ == "__main__":
    try:
        dataset = get_or_create_dataset()

        upload_dataset_if_empty(dataset)

        results = evaluate(
            target,
            data=DATASET_NAME,
            evaluators=[evaluate_retrieval],
            experiment_prefix=EXPERIMENT_PREFIX,
            max_concurrency=1,
        )

        log_json({
            "event": "evaluation_completed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dataset": DATASET_NAME,
            "experiment_prefix": EXPERIMENT_PREFIX,
            "results": str(results),
        })

        print("\nRetrieval evaluation completed successfully.")
        print(results)

    except Exception as exc:
        log_json({
            "event": "evaluation_failed",
            "dataset": DATASET_NAME,
            "error": str(exc),
        })

        logger.exception("Retrieval evaluation traceback")
        raise
