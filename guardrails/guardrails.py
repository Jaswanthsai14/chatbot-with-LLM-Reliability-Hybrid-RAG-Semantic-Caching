import re
from pathlib import Path


from langchain_core.documents import Document

from db import db1



dataset_files = [
    Path("guardrail_eval_1000_malicious_.md"),
   
]

pattern = re.compile(
    r'## Example (\d+)\s*\n'
    r'- label:\s*"([^"]+)"\s*\n'
    r'- text:\s*"(.*?)"\s*(?=\n## Example |\Z)',
    re.DOTALL,
)

documents = []
ids = []

for file_path in dataset_files:
    if not file_path.exists():
        raise FileNotFoundError(
            f"Dataset file not found: {file_path}"
        )

    content = file_path.read_text(encoding="utf-8")
    examples = pattern.findall(content)

    if not examples:
        raise ValueError(
            f"No examples found in {file_path}"
        )

    prefix = (
        "base"
        if "label_text" in file_path.name
        else "additional"
    )

    for example_id, label, text in examples:
        documents.append(
            Document(
                page_content=text,
                metadata={"label": label},
            )
        )

        # Internal Chroma record ID; not metadata
        ids.append(f"{prefix}_{int(example_id):03d}")

    print(
        f"Loaded {len(examples)} examples from {file_path.name}"
    )


# 4. Insert both datasets into the same collection
db1.add_documents(
    documents=documents,
    ids=ids,
)


# 5. Verify insertion
print("\nInsertion completed successfully!")
print("Examples processed:", len(documents))
print("Total records in collection:", db1._collection.count())
print("Metadata fields: label only")



result = db1._collection.get(
    limit=5,
    include=["documents", "metadatas"],
)

for text, metadata in zip(
    result["documents"],
    result["metadatas"],
):
    print("Text:", text)
    print("Metadata:", metadata)
    print("-" * 40)