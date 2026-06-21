import sys
import os
import anthropic
import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

# Load .env file if present (won't override existing environment variables)
load_dotenv()

# ── API key check ─────────────────────────────────────────────────────────────
if not os.environ.get("ANTHROPIC_API_KEY"):
    print("❌ ANTHROPIC_API_KEY is not set.")
    print("   Add it to your ~/.bashrc:  export ANTHROPIC_API_KEY='sk-ant-...'")
    print("   Or create a .env file in this directory with that line.")
    sys.exit(1)
# ─────────────────────────────────────────────────────────────────────────────

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH        = "/home/geekom/juniper_vector_db"
TOP_K          = 6      # number of chunks to keep after filtering
FETCH_K        = 12     # fetch more candidates before filtering/dedup
MAX_CONTEXT    = 7000   # max characters of context sent to Claude
MIN_RELEVANCE  = 1.2    # ChromaDB L2 distance ceiling (tightened from 1.4)
CLAUDE_MODEL   = "claude-sonnet-4-6"
# ─────────────────────────────────────────────────────────────────────────────

if len(sys.argv) < 2:
    print("Usage: python ask_books.py 'your question here'")
    sys.exit(1)

question = " ".join(sys.argv[1:])

# ── Load ChromaDB ─────────────────────────────────────────────────────────────
print("🔍 Querying Juniper Day One vector database...")

ollama_ef = embedding_functions.OllamaEmbeddingFunction(
    url="http://localhost:11434/api/embeddings",
    model_name="all-minilm"
)

try:
    chroma_client = chromadb.PersistentClient(path=DB_PATH)
    collection = chroma_client.get_collection(
        name="juniper_books",
        embedding_function=ollama_ef
    )
except Exception as e:
    print(f"❌ Could not open vector database at '{DB_PATH}': {e}")
    print("   Run index_books.py first to build the database.")
    sys.exit(1)

# ── Semantic search ───────────────────────────────────────────────────────────
try:
    results = collection.query(
        query_texts=[question],
        n_results=FETCH_K,   # fetch more, filter down below
        include=["documents", "metadatas", "distances"]
    )
except Exception as e:
    print(f"❌ Search failed: {e}")
    sys.exit(1)

docs      = results["documents"][0]
metas     = results["metadatas"][0]
distances = results["distances"][0]

# Filter by relevance threshold and deduplicate by (source, page)
seen_pages = set()
relevant = []

for doc, meta, dist in zip(docs, metas, distances):
    if dist > MIN_RELEVANCE:
        continue
    key = (meta.get("source", "unknown"), meta.get("page", "?"))
    if key in seen_pages:
        continue
    seen_pages.add(key)
    relevant.append((doc, meta, dist))
    if len(relevant) >= TOP_K:
        break

if not relevant:
    print("❌ No sufficiently relevant content found. Try different keywords,")
    print(f"   or raise MIN_RELEVANCE above {MIN_RELEVANCE} in the script.")
    sys.exit(1)

# Build context block and source list
context_parts = []
sources = {}
char_count = 0

for doc, meta, dist in relevant:
    src  = meta.get("source", "unknown")
    page = meta.get("page", "?")
    snippet = f"[{src}, p.{page}]\n{doc}"

    if char_count + len(snippet) > MAX_CONTEXT:
        break

    context_parts.append(snippet)
    char_count += len(snippet)

    if src not in sources:
        sources[src] = set()
    sources[src].add(page)

context = "\n\n---\n\n".join(context_parts)

# ── Build prompt & call Claude ────────────────────────────────────────────────
system_prompt = (
    "You are an expert Juniper Network Engineer specialising in Junos OS. "
    "Answer the user's question using ONLY the provided text snippets.\n\n"
    "RULES:\n"
    "1. Always show actual Junos CLI commands and config blocks from the snippets.\n"
    "2. Format ALL config and CLI examples exactly like this:\n\n"
    "   EXAMPLE CONFIG:\n"
    "   set protocols bgp group EBGP type external\n"
    "   set protocols bgp group EBGP peer-as 65001\n"
    "   set protocols bgp group EBGP neighbor 10.0.0.1\n\n"
    "3. After the config block, explain what each line does in plain English.\n"
    "4. If the snippets don't contain exact syntax, say so clearly.\n"
    "5. Never say 'refer to the documentation' or point to URLs.\n"
    "6. Keep the answer focused and practical — show the config first, explain second.\n"
    "7. Use plain text only, no markdown, no asterisks, no bullet symbols."
)

user_prompt = (
    f"Context snippets from Juniper Day One books:\n\n{context}\n\n"
    f"Question: {question}\n\n"
    f"Show the actual Junos CLI commands first, then explain each one clearly:"
)

print(f"📖 Found {len(relevant)} relevant chunk(s). Asking Claude...\n")

# ── Claude API call ───────────────────────────────────────────────────────────
try:
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from environment

    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    answer = message.content[0].text

except anthropic.AuthenticationError:
    print("❌ Invalid API key. Set ANTHROPIC_API_KEY in your environment:")
    print("   export ANTHROPIC_API_KEY='sk-ant-...'")
    sys.exit(1)
except anthropic.RateLimitError:
    print("❌ Rate limit hit. Wait a moment and try again.")
    sys.exit(1)
except anthropic.APIConnectionError:
    print("❌ Could not reach the Anthropic API. Check your internet connection.")
    sys.exit(1)
except Exception as e:
    print(f"❌ Unexpected error: {e}")
    sys.exit(1)

# ── Output ────────────────────────────────────────────────────────────────────
print("=" * 60)
print("ANSWER:")
print("=" * 60)
print(answer)
print("=" * 60)
print("SOURCES:")
for src, pages in sources.items():
    sorted_pages = sorted(pages)
    page_str = ", ".join(f"p.{p}" for p in sorted_pages[:5])
    print(f"  {src} — {page_str}")
print("=" * 60)
