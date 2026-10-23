from sentence_transformers import SentenceTransformer
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings


class HFEmbeddings(Embeddings):
    def __init__(self):
        self.model = SentenceTransformer(
            "sentence-transformers/all-MiniLM-L6-v2"
        )

    def embed_documents(self, texts):
        return self.model.encode(texts).tolist()

    def embed_query(self, text):
        return self.model.encode(text).tolist()


embeddings = HFEmbeddings()

db1 = Chroma(
    collection_name="guardrails",
    embedding_function=embeddings,
    persist_directory="./chroma_db"
)

db2 = Chroma(
    collection_name="history",
    embedding_function=embeddings,
    persist_directory="./chroma_db"
)

print("Both collections initialized successfully!")