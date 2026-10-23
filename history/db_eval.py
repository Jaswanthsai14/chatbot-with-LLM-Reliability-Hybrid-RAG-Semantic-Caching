
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

from history.retrieve2 import hybrid_retrieve1
load_dotenv()

# Configuration
DATASET_NAME = "Indian-History-RAG-Eval-4"
JSONL_FILE = (
    Path(__file__).resolve().parent
    / "id4.jsonl"
)
EXPERIMENT_PREFIX = "hybrid-retrieval-eval"

TOP_K = 5
GEMINI_MODEL = "gemini-2.5-flash"

client = Client(
    api_key=os.getenv("LANGSMITH_API_KEY")
)

# Gemini judge
judge_llm = ChatGoogleGenerativeAI(
    model=GEMINI_MODEL,
    temperature=0,
    google_api_key=os.getenv("GOOGLE_API_KEY"),
)

# Logging
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


# Structured evaluation output
class RetrievalEvaluation(BaseModel):
    document_relevance: List[int] = Field(
        description=(
            "One relevance score per retrieved document, "
            "in ranking order. 0=irrelevant, "
            "1=partially relevant, 2=relevant, "
            "3=highly relevant."
        )
    )

    answer_coverage: float = Field(
        description=(
            "Fraction from 0 to 1 of important facts "
            "in the expected answer supported by "
            "the retrieved documents."
        )
    )

    context_relevance: float = Field(
        description=(
            "Overall relevance of the retrieved "
            "documents to the query, from 0 to 1."
        )
    )


judge_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
You are a strict evaluator for an Indian History RAG retriever.

Evaluate retrieval quality using only the query, expected
answer, and retrieved documents.

Rules:
1. Score each document independently for usefulness in
   answering the query and supporting the expected answer.
2. Document relevance must be an integer from 0 to 3:
   0 = irrelevant, 1 = partially relevant,
   2 = relevant, 3 = highly relevant.
3. Answer coverage and context relevance must be between 0 and 1.
4. Coverage measures how much of the expected answer is
   supported by the retrieved documents.
5. Context relevance measures how relevant the retrieved
   documents are to the query.
6. Do not reward unsupported historical claims.
7. Return the requested structured evaluation.
""",
    ),
    (
        "human",
        """
Query:
{query}

Expected answer:
{expected_answer}

Retrieved documents, in ranking order:
{documents}

Evaluate retrieval quality.
""",
    ),
])

judge = judge_prompt | judge_llm.with_structured_output(
    RetrievalEvaluation
)


# Dataset setup
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
                "Indian History questions and expected "
                "answers for retrieval evaluation."
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
        })
        return

    if not JSONL_FILE.exists():
        raise FileNotFoundError(
            f"Dataset file not found: {JSONL_FILE}"
        )

    count = 0

    with JSONL_FILE.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            record = json.loads(line)

            client.create_example(
                dataset_id=dataset.id,
                inputs={
                    "query": record["query"],
                },
                outputs={
                    "expected_answer": record["expected_answer"],
                },
            )

            count += 1

    log_json({
        "event": "dataset_uploaded",
        "dataset": DATASET_NAME,
        "examples_uploaded": count,
    })


# Retrieval target: no answer generation
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
        doc.page_content for doc in documents
    ]

    context = "\n\n".join(document_texts)

    return {
        "documents": document_texts,
        "context": context,
        "retrieval_latency_ms": retrieval_latency_ms,
    }


# Gemini-based retrieval evaluator
def evaluate_retrieval(
    inputs: dict,
    outputs: dict,
    reference_outputs: dict,
):
    query = inputs["query"]
    expected_answer = reference_outputs["expected_answer"]
    documents = outputs.get("documents", [])

    if not documents:
        scores = {
            "precision_at_k": 0.0,
            "answer_coverage_recall_proxy": 0.0,
            "mrr": 0.0,
            "ndcg_at_k": 0.0,
            "context_relevance": 0.0,
        }

    else:
        evaluation = judge.invoke({
            "query": query,
            "expected_answer": expected_answer,
            "documents": json.dumps(
                documents,
                ensure_ascii=False,
            ),
        })

        # Align Gemini relevance scores with retrieved documents
        relevance = [
            max(0, min(3, int(score)))
            for score in evaluation.document_relevance
        ]

        relevance = relevance[:len(documents)]

        if len(relevance) < len(documents):
            relevance.extend(
                [0] * (len(documents) - len(relevance))
            )

        # Scores 2 and 3 count as relevant
        binary_relevance = [
            1 if score >= 2 else 0
            for score in relevance
        ]

        # Precision@K
        precision = (
            sum(binary_relevance) / len(documents)
            if documents else 0.0
        )

        # Mean Reciprocal Rank
        reciprocal_rank = 0.0

        for rank, is_relevant in enumerate(
            binary_relevance,
            start=1,
        ):
            if is_relevant:
                reciprocal_rank = 1.0 / rank
                break

        # NDCG@K using graded relevance scores
        dcg = sum(
            (2 ** score - 1) / math.log2(rank + 1)
            for rank, score in enumerate(
                relevance,
                start=1,
            )
        )

        ideal_relevance = sorted(
            relevance,
            reverse=True,
        )

        idcg = sum(
            (2 ** score - 1) / math.log2(rank + 1)
            for rank, score in enumerate(
                ideal_relevance,
                start=1,
            )
        )

        ndcg = dcg / idcg if idcg else 0.0

        scores = {
            "precision_at_k": precision,
            "answer_coverage_recall_proxy": max(
                0.0,
                min(1.0, evaluation.answer_coverage),
            ),
            "mrr": reciprocal_rank,
            "ndcg_at_k": ndcg,
            "context_relevance": max(
                0.0,
                min(1.0, evaluation.context_relevance),
            ),
        }

    # Retrieval latency
    scores["retrieval_latency_ms"] = max(
        0.0,
        float(outputs.get("retrieval_latency_ms", 0.0)),
    )

    log_json({
        "event": "retrieval_evaluation",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "retrieved_count": len(documents),
        "metrics": scores,
        "retrieval_latency_ms": outputs.get(
            "retrieval_latency_ms",
            0.0,
        ),
    })

    return [
        {"key": key, "score": value}
        for key, value in scores.items()
    ]


# Run evaluation
if __name__ == "__main__":
    try:
        if not os.getenv("GOOGLE_API_KEY"):
            raise ValueError(
                "GOOGLE_API_KEY is missing from your .env file."
            )

        if not os.getenv("LANGSMITH_API_KEY"):
            raise ValueError(
                "LANGSMITH_API_KEY is missing from your .env file."
            )

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

        print("Retrieval evaluation completed successfully.")
        print(results)

    except Exception as exc:
        log_json({
            "event": "evaluation_failed",
            "dataset": DATASET_NAME,
            "error": str(exc),
        })

        logger.exception("Retrieval evaluation traceback")
        raise
