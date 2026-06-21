import os
import time
import json
import chromadb
from chromadb.utils import embedding_functions
from pypdf import PdfReader

# ── Config ────────────────────────────────────────────────────────────────────
BOOK_DIR        = "/srv/ftp/dayone"
DB_PATH         = "/home/geekom/juniper_vector_db"
CHECKPOINT_FILE = "/home/geekom/juniper_index_checkpoint.json"
CHUNK_SIZE      = 1200
CHUNK_STEP      = 900
BATCH_SIZE      = 10
PAGE_SLEEP      = 0.2
# ─────────────────────────────────────────────────────────────────────────────

# Load checkpoint
if os.path.exists(CHECKPOINT_FILE):
    with open(CHECKPOINT_FILE, "r") as f:
        completed = set(json.load(f))
    print(f"📋 Checkpoint found: {len(completed)} file(s) already indexed, skipping.\n")
else:
    completed = set()

chroma_client = chromadb.PersistentClient(path=DB_PATH)

ollama_ef = embedding_functions.OllamaEmbeddingFunction(
    url="http://localhost:11434/api/embeddings",
    model_name="all-minilm"
)

collection = chroma_client.get_or_create_collection(
    name="juniper_books",
    embedding_function=ollama_ef
)

pdf_files = [f for f in os.listdir(BOOK_DIR) if f.endswith(".pdf")]
print(f"📚 Found {len(pdf_files)} PDF(s) to index into ChromaDB at {DB_PATH}\n")

total_chunks = 0

for file_idx, file in enumerate(pdf_files, 1):
    if file in completed:
        print(f"[{file_idx}/{len(pdf_files)}] Skipping (already indexed): {file}")
        continue

    filepath = os.path.join(BOOK_DIR, file)
    print(f"[{file_idx}/{len(pdf_files)}] Indexing: {file}")

    try:
        reader = PdfReader(filepath)
        file_chunks = 0
        batch_docs, batch_metas, batch_ids = [], [], []

        for page_num, page in enumerate(reader.pages):
            text = page.extract_text()
            if not text or len(text.strip()) < 100:
                continue

            chunks = [text[i:i + CHUNK_SIZE] for i in range(0, len(text), CHUNK_STEP)]

            for chunk_idx, chunk in enumerate(chunks):
                doc_id = f"{file}_{page_num}_{chunk_idx}"
                batch_docs.append(chunk)
                batch_metas.append({"source": file, "page": page_num})
                batch_ids.append(doc_id)
                if len(batch_docs) >= BATCH_SIZE:
                    collection.add(documents=batch_docs, metadatas=batch_metas, ids=batch_ids)
                    batch_docs, batch_metas, batch_ids = [], [], []
                    file_chunks += BATCH_SIZE
                    total_chunks += BATCH_SIZE

            time.sleep(PAGE_SLEEP)

        # Flush remaining batch
        if batch_docs:
            collection.add(documents=batch_docs, metadatas=batch_metas, ids=batch_ids)
            file_chunks += len(batch_docs)
            total_chunks += len(batch_docs)

        completed.add(file)
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump(list(completed), f)

        print(f"    ✅ Done: {file_chunks} chunks indexed\n")

    except Exception as e:
        print(f"    ❌ Error indexing {file}: {e}\n")

print(f"🎉 Indexing complete! Total chunks: {total_chunks}")
