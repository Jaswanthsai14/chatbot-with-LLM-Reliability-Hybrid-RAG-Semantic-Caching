
from pathlib import Path

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from db import db2



BASE_DIR = Path(__file__).resolve().parent
file_path = BASE_DIR / "indian_history.md"

# 1. Load the Markdown file
loader = TextLoader(str(file_path), encoding="utf-8")
documents = loader.load()

# 2. Split documents into chunks
splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=150,
    add_start_index=True
)

chunks = splitter.split_documents(documents)

# 3. Add metadata
for i, chunk in enumerate(chunks):
    chunk.metadata["source"] = "indian_history.md"
    chunk.metadata["chunk_number"] = i
    chunk.metadata["topic"] = "Indian History"

# 4. Generate IDs
ids = [f"indian_history_{i}" for i in range(len(chunks))]

# 5. Insert into ChromaDB
db2.add_documents(
    documents=chunks,
    ids=ids
)

print(f"Successfully inserted {len(chunks)} chunks!")
