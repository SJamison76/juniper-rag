import sys
import os
import anthropic
import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

# ── API key check ─────────────────────────────────────────────────────────────
if not os.environ.get("ANTHROPIC_API_KEY"):
    print("❌ ANTHROPIC_API_KEY is not set.")
    print("   Add it to your ~/.bashrc:  export ANTHROPIC_API_KEY='sk-ant-...'")
    print("   Or create a .env file in this directory with that line.")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH        = os.path.join(os.path.expanduser("~"), "juniper_vector_db")
TOP_K          = 10     # number of chunks to keep after filtering
FETCH_K        = 20     # fetch more candidates before filtering/dedup
MAX_CONTEXT    = 14000  # max characters of context sent to Claude
MIN_RELEVANCE  = 1.2    # ChromaDB L2 distance ceiling
CLAUDE_MODEL   = "claude-sonnet-4-6"
# ─────────────────────────────────────────────────────────────────────────────

# ── Load ChromaDB ─────────────────────────────────────────────────────────────
print("🔍 Connecting to Juniper Day One vector database...")

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

# ── System prompt (cached across all turns) ───────────────────────────────────
system_prompt = (
    "You are an expert network engineer with deep knowledge of multiple vendors "
    "including Juniper Junos OS, Cisco IOS, IOS XE, NX-OS, and others. "
    "Answer the user's question using ONLY the provided text snippets.\n\n"
    "RULES:\n"
    "1. Always show actual CLI commands and config blocks from the snippets.\n"
    "2. Format ALL config and CLI examples exactly like this:\n\n"
    "   EXAMPLE CONFIG:\n"
    "   set protocols bgp group EBGP type external\n"
    "   set protocols bgp group EBGP peer-as 65001\n\n"
    "3. After the config block, explain what each line does in plain English.\n"
    "4. If the snippets don't contain exact syntax, say so clearly.\n"
    "5. Never say 'refer to the documentation' or point to URLs.\n"
    "6. Keep the answer focused and practical — show the config first, explain second.\n"
    "7. Use plain text only, no markdown, no asterisks, no bullet symbols.\n"
    "8. Always identify which vendor/platform the commands apply to."
)

client = anthropic.Anthropic()

# ── Handle single question mode (argument passed) or chat loop ────────────────
single_question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None

if single_question:
    questions = [single_question]
    loop_mode = False
else:
    print("╔══════════════════════════════════════════════════════════╗")
    print("║         Juniper Day One - Interactive Q&A                ║")
    print("║  Ask questions about Junos OS. Type 'exit' to quit.      ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print("")
    loop_mode = True
    questions = []


def search_and_ask(question, conversation_history):
    """Search ChromaDB and ask Claude, maintaining conversation history."""

    # ── Semantic search ───────────────────────────────────────────────────────
    try:
        results = collection.query(
            query_texts=[question],
            n_results=FETCH_K,
            include=["documents", "metadatas", "distances"]
        )
    except Exception as e:
        print(f"❌ Search failed: {e}")
        return None, None, None

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
        print("❌ No sufficiently relevant content found. Try rephrasing.")
        return None, None, None

    # Build context
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
    print(f"📖 Found {len(relevant)} relevant chunk(s). Asking Claude...\n")

    # Build user message with fresh context for this question
    user_message = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": f"Context snippets from Juniper Day One books:\n\n{context}",
                "cache_control": {"type": "ephemeral"}  # cache book context
            },
            {
                "type": "text",
                "text": (
                    f"\nQuestion: {question}\n\n"
                    f"Show the actual Junos CLI commands first, then explain each one clearly:"
                )
            }
        ]
    }

    # Build full message history for this turn
    messages = conversation_history + [user_message]

    try:
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}  # cache system prompt
                }
            ],
            messages=messages
        )

        answer = message.content[0].text

        usage = message.usage
        if hasattr(usage, "cache_read_input_tokens") and usage.cache_read_input_tokens:
            print(f"💾 Cache hit: {usage.cache_read_input_tokens} tokens read from cache")
        elif hasattr(usage, "cache_creation_input_tokens") and usage.cache_creation_input_tokens:
            print(f"💾 Cache written: {usage.cache_creation_input_tokens} tokens cached for next run")

        # Add this turn to conversation history
        new_history = conversation_history + [
            user_message,
            {"role": "assistant", "content": answer}
        ]

        return answer, sources, new_history

    except anthropic.AuthenticationError:
        print("❌ Invalid API key.")
        sys.exit(1)
    except anthropic.RateLimitError:
        print("❌ Rate limit hit. Wait a moment and try again.")
        return None, None, conversation_history
    except anthropic.APIConnectionError:
        print("❌ Could not reach the Anthropic API. Check your internet connection.")
        return None, None, conversation_history
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return None, None, conversation_history


def print_answer(answer, sources):
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


# ── Main loop ─────────────────────────────────────────────────────────────────
conversation_history = []

if not loop_mode:
    # Single question mode
    question = questions[0]
    answer, sources, conversation_history = search_and_ask(question, conversation_history)
    if answer:
        print_answer(answer, sources)
else:
    # Interactive chat loop
    while True:
        try:
            print("")
            question = input("Ask a question (or 'exit' to quit): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n👋 Goodbye.")
            break

        if not question:
            continue

        if question.lower() in ("exit", "quit", "q"):
            print("👋 Goodbye.")
            break

        answer, sources, conversation_history = search_and_ask(question, conversation_history)
        if answer:
            print_answer(answer, sources)
