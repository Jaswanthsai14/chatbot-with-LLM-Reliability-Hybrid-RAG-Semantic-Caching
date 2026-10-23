import os
import json
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv
from langsmith import Client, evaluate
from .checkpoint import check_guardrail

load_dotenv()

client = Client(api_key=os.getenv("LANGSMITH_API_KEY"))



DATASET_NAME = "Similarity-Guardrail-Eval1"
JSONL_FILE = "guardrails/guardrail_eval_1000_malicious"
EXPERIMENT_PREFIX = "top3-similarity-threshold-080"



logger = logging.getLogger("guardrail_eval")
logger.setLevel(logging.INFO)
logger.handlers.clear()

file_handler = logging.FileHandler(
    "guardrail_eval.log",
    encoding="utf-8",
)
file_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(file_handler)


def log_json(record: dict):
    logger.info(json.dumps(record, ensure_ascii=False))




def target(inputs: dict) -> dict:
    query = inputs["query"]

    should_block = check_guardrail(query)
    decision = "block" if should_block else "allow"

    return {"decision": decision}




def evaluate_guardrail(
    inputs: dict,
    outputs: dict,
    reference_outputs: dict,
) -> dict:
    expected = reference_outputs["expected_decision"]
    actual = outputs["decision"]
    correct = actual == expected

    log_json({
        "event": "guardrail_prediction",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": inputs["query"],
        "expected_decision": expected,
        "actual_decision": actual,
        "correct": correct,
        "score": int(correct),
    })

    return {
        "key": "decision_correctness",
        "score": int(correct),
    }




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
            description="ChromaDB guardrail evaluation dataset",
        )
        log_json({
            "event": "dataset_created",
            "dataset": DATASET_NAME,
        })

    return dataset




def upload_dataset_if_empty(dataset):
    existing_examples = list(
        client.list_examples(
            dataset_id=dataset.id,
            limit=1,
        )
    )

    if existing_examples:
        log_json({
            "event": "upload_skipped",
            "dataset": DATASET_NAME,
            "reason": "Dataset already contains examples",
        })
        return

    if not os.path.exists(JSONL_FILE):
        raise FileNotFoundError(
            f"Dataset file not found: {JSONL_FILE}"
        )

    count = 0

    with open(JSONL_FILE, "r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            record = json.loads(line)

            client.create_example(
                dataset_id=dataset.id,
                inputs=record["inputs"],
                outputs=record["outputs"],
            )

            count += 1

    log_json({
        "event": "dataset_uploaded",
        "dataset": DATASET_NAME,
        "file": JSONL_FILE,
        "examples_uploaded": count,
    })




try:
    dataset = get_or_create_dataset()
    upload_dataset_if_empty(dataset)

    results = evaluate(
        target,
        data=DATASET_NAME,
        evaluators=[evaluate_guardrail],
        experiment_prefix=EXPERIMENT_PREFIX,
    )

    log_json({
        "event": "evaluation_completed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset": DATASET_NAME,
        "experiment_prefix": EXPERIMENT_PREFIX,
        "results": str(results),
    })

except Exception as exc:
    log_json({
        "event": "evaluation_failed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset": DATASET_NAME,
        "error": str(exc),
    })
    logger.exception("Evaluation traceback")
    raise