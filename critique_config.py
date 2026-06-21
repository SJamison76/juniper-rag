import sys
import os
import anthropic
import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH        = os.path.join(os.path.expanduser("~"), "juniper_vector_db")
TOP_K          = 12     # number of chunks to keep after filtering
FETCH_K        = 24     # fetch more candidates before filtering/dedup
MAX_CONTEXT    = 12000  # chars of book context sent to Claude
MIN_RELEVANCE  = 1.2    # ChromaDB L2 distance ceiling
CLAUDE_MODEL   = "claude-sonnet-4-6"
# ─────────────────────────────────────────────────────────────────────────────

load_dotenv()

# ── API key check ─────────────────────────────────────────────────────────────
if not os.environ.get("ANTHROPIC_API_KEY"):
    print("❌ ANTHROPIC_API_KEY is not set.")
    print("   Add it to ~/.bashrc:  export ANTHROPIC_API_KEY='sk-ant-...'")
    sys.exit(1)

# ── Args ──────────────────────────────────────────────────────────────────────
if len(sys.argv) < 2:
    print("Usage: python critique_config.py <config.txt> [focus]")
    print("")
    print("Examples:")
    print("  python critique_config.py config.txt")
    print("  python critique_config.py config.txt 'harden this config'")
    print("  python critique_config.py config.txt 'review BGP configuration'")
    print("  python critique_config.py config.txt 'check OSPF setup'")
    print("")
    print("If no focus is given, a general best-practice review is performed.")
    sys.exit(1)

config_file = sys.argv[1]
focus       = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "general best-practice review"

# ── Read config file ──────────────────────────────────────────────────────────
if not os.path.exists(config_file):
    print(f"❌ Config file not found: {config_file}")
    sys.exit(1)

with open(config_file, "r") as f:
    config_text = f.read().strip()

if not config_text:
    print(f"❌ Config file is empty: {config_file}")
    sys.exit(1)

MAX_CONFIG_CHARS = 12000
if len(config_text) > MAX_CONFIG_CHARS:
    config_text = config_text[:MAX_CONFIG_CHARS]
    print(f"⚠️  Config truncated to {MAX_CONFIG_CHARS} chars to fit context window.")

print("")
print("=" * 60)
print(f" Juniper Config Critique")
print(f" File  : {config_file}")
print(f" Focus : {focus}")
print(f" Lines : {config_text.count(chr(10)) + 1}")
print("=" * 60)
print("")

# ── Load ChromaDB ─────────────────────────────────────────────────────────────
print("🔍 Searching knowledge base...")

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
    print(f"❌ Could not open vector database: {e}")
    print("   Run index_books.py first to build the database.")
    sys.exit(1)

try:
    results = collection.query(
        query_texts=[focus],
        n_results=FETCH_K,
        include=["documents", "metadatas", "distances"]
    )
except Exception as e:
    print(f"❌ Search failed: {e}")
    sys.exit(1)

docs      = results["documents"][0]
metas     = results["metadatas"][0]
distances = results["distances"][0]

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
    print(f"❌ No relevant content found for: {focus}")
    print(f"   Try rephrasing or raise MIN_RELEVANCE above {MIN_RELEVANCE}")
    sys.exit(1)

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
print(f"✅ Found {len(relevant)} relevant chunk(s) from {len(sources)} source(s)")

# ── Ask Claude ────────────────────────────────────────────────────────────────
print(f"🤖 Asking Claude to critique the config...\n")

system_prompt = (
    "You are an expert network engineer with deep knowledge of multiple vendors "
    "including Juniper Junos OS, Cisco IOS, IOS XE, NX-OS, and others. "
    "You are performing a configuration audit.\n"
    "You will be given a device configuration and reference material from vendor hardening guides.\n"
    "Produce a concise, practical critique. Be brief — one line per point, commands first.\n\n"
    "Structure your output exactly as follows:\n\n"
    "SUMMARY\n"
    "One or two sentences maximum. Overall verdict and number of issues found.\n\n"
    "ISSUES\n"
    "For each issue, use exactly this format with no extra text:\n"
    "  ISSUE N: <short title>\n"
    "  <set or delete command(s)>\n"
    "  <one line explanation of why it matters>\n\n"
    "RECOMMENDATIONS\n"
    "For each recommendation, use exactly this format:\n"
    "  REC N: <short title>\n"
    "  <set or delete command(s)>\n"
    "  <one line explanation>\n\n"
    "CORRECT\n"
    "A single short list of things already configured correctly. One line each.\n\n"
    "RULES:\n"
    "1. Base your critique ONLY on the provided reference material and the config given.\n"
    "2. Always show actual Junos set/delete commands.\n"
    "3. Plain text only, no markdown, no asterisks, no bullet symbols.\n"
    "4. Keep every explanation to one line maximum.\n"
    "5. Never say refer to documentation or point to URLs."
)

user_prompt = (
    f"Reference material from Juniper Day One books:\n\n{context}\n\n"
    f"Device configuration to review:\n\n{config_text}\n\n"
    f"Focus: {focus}\n\n"
    f"Produce a full critique of this configuration:"
)

try:
    client = anthropic.Anthropic()

    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"}  # cache system prompt
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Reference material from Juniper Day One books:\n\n{context}",
                        "cache_control": {"type": "ephemeral"}  # cache book context
                    },
                    {
                        "type": "text",
                        "text": (
                            f"\nDevice configuration to review:\n\n{config_text}\n\n"
                            f"Focus: {focus}\n\n"
                            f"Produce a full critique of this configuration:"
                        )
                    }
                ]
            }
        ],
        temperature=0
    )

    critique = message.content[0].text

    usage = message.usage
    if hasattr(usage, "cache_read_input_tokens") and usage.cache_read_input_tokens:
        print(f"💾 Cache hit: {usage.cache_read_input_tokens} tokens read from cache")
    elif hasattr(usage, "cache_creation_input_tokens") and usage.cache_creation_input_tokens:
        print(f"💾 Cache written: {usage.cache_creation_input_tokens} tokens cached for next run")

except anthropic.AuthenticationError:
    print("❌ Invalid API key.")
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
print(f" CRITIQUE: {config_file}")
print("=" * 60)
print(critique)
print("=" * 60)
print("SOURCES:")
for src, pages in sources.items():
    sorted_pages = sorted(pages)
    page_str = ", ".join(f"p.{p}" for p in sorted_pages[:5])
    print(f"  {src} — {page_str}")
print("=" * 60)

# ── Determine output location ─────────────────────────────────────────────────
report_dir  = os.environ.get("REPORT_DIR", os.path.dirname(os.path.abspath(config_file)))
base_name   = "critique"
report_file = os.path.join(report_dir, f"{base_name}.txt")

save = input(f"\nSave critique to {report_file}? (yes/no): ").strip().lower()
if save == "yes":
    with open(report_file, "w") as f:
        f.write(f"Juniper Config Critique\n")
        f.write(f"File  : {config_file}\n")
        f.write(f"Focus : {focus}\n")
        f.write("=" * 60 + "\n\n")
        f.write(critique)
        f.write("\n\n" + "=" * 60 + "\n")
        f.write("SOURCES:\n")
        for src, pages in sources.items():
            sorted_pages = sorted(pages)
            page_str = ", ".join(f"p.{p}" for p in sorted_pages[:5])
            f.write(f"  {src} — {page_str}\n")
    print(f"✅ Critique saved to {report_file}")
else:
    print("✅ Done.")
