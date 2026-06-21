import sys
import os
import anthropic
import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv
from getpass import getpass

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH        = "/home/geekom/juniper_vector_db"
TOP_K          = 6      # number of chunks to keep after filtering
FETCH_K        = 12     # fetch more candidates before filtering/dedup
MAX_CONTEXT    = 6000   # chars of book context sent to Claude
MIN_RELEVANCE  = 1.2    # ChromaDB L2 distance ceiling
CLAUDE_MODEL   = "claude-sonnet-4-6"
NETCONF_PORT   = 830
# ─────────────────────────────────────────────────────────────────────────────

load_dotenv()

# ── API key check ─────────────────────────────────────────────────────────────
if not os.environ.get("ANTHROPIC_API_KEY"):
    print("❌ ANTHROPIC_API_KEY is not set.")
    print("   Add it to ~/.bashrc:  export ANTHROPIC_API_KEY='sk-ant-...'")
    sys.exit(1)

# ── Args ──────────────────────────────────────────────────────────────────────
if len(sys.argv) < 3:
    print("Usage: python do_configure.py <device-ip> 'what you want to do'")
    print("")
    print("Examples:")
    print("  python do_configure.py 192.168.1.1 'harden this switch'")
    print("  python do_configure.py 192.168.1.1 'configure OSPF on all uplink interfaces'")
    print("  python do_configure.py 192.168.1.1 'set up NTP with authentication'")
    sys.exit(1)

device_ip = sys.argv[1]
task      = " ".join(sys.argv[2:])

# ── PyEZ import check ─────────────────────────────────────────────────────────
try:
    from jnpr.junos import Device
    from jnpr.junos.utils.config import Config
    from jnpr.junos.exception import ConnectError, CommitError, ConfigLoadError
except ImportError:
    print("❌ PyEZ not installed. Run:")
    print("   pip install junos-eznc --break-system-packages")
    print("   or: ./juniper-env/bin/pip install junos-eznc")
    sys.exit(1)

# ── Credentials ───────────────────────────────────────────────────────────────
print("")
print("=" * 60)
print(f" Juniper AI Configurator")
print(f" Device : {device_ip}")
print(f" Task   : {task}")
print("=" * 60)
print("")

username = input("Username: ").strip()
password = getpass("Password: ")

# ── Connect to device ─────────────────────────────────────────────────────────
print(f"\n🔌 Connecting to {device_ip} via NETCONF...")

try:
    dev = Device(
        host=device_ip,
        user=username,
        password=password,
        port=NETCONF_PORT
    )
    dev.open()
    print(f"✅ Connected. Model: {dev.facts.get('model', 'unknown')}  "
          f"Junos: {dev.facts.get('version', 'unknown')}")
except ConnectError as e:
    print(f"❌ Could not connect to {device_ip}: {e}")
    print("   Check the IP, credentials, and that NETCONF is enabled:")
    print("   set system services netconf ssh")
    sys.exit(1)
except Exception as e:
    print(f"❌ Unexpected connection error: {e}")
    sys.exit(1)

# ── Pull current config ───────────────────────────────────────────────────────
print("\n📥 Pulling current device configuration...")

try:
    cu = Config(dev)
    current_config = dev.rpc.get_config(options={"format": "set"})
    config_text = current_config.text
    if not config_text:
        # fallback: get as text
        current_config = dev.rpc.get_config()
        config_text = str(current_config.tostring(pretty_print=True).decode())
    print(f"✅ Retrieved config ({len(config_text)} characters)")
except Exception as e:
    print(f"❌ Failed to retrieve config: {e}")
    dev.close()
    sys.exit(1)

# Truncate config if very large to leave room for book context
MAX_CONFIG_CHARS = 8000
if len(config_text) > MAX_CONFIG_CHARS:
    config_text = config_text[:MAX_CONFIG_CHARS]
    print(f"⚠️  Config truncated to {MAX_CONFIG_CHARS} chars to fit context window.")

# ── RAG: find relevant book chunks ───────────────────────────────────────────
print(f"\n🔍 Searching knowledge base for: {task}")

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
    dev.close()
    sys.exit(1)

try:
    results = collection.query(
        query_texts=[task],
        n_results=FETCH_K,
        include=["documents", "metadatas", "distances"]
    )
except Exception as e:
    print(f"❌ Search failed: {e}")
    dev.close()
    sys.exit(1)

docs      = results["documents"][0]
metas     = results["metadatas"][0]
distances = results["distances"][0]

# Filter and deduplicate
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
    print(f"❌ No relevant content found for: {task}")
    print(f"   Try rephrasing or raise MIN_RELEVANCE above {MIN_RELEVANCE}")
    dev.close()
    sys.exit(1)

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
print(f"✅ Found {len(relevant)} relevant chunk(s) from {len(sources)} source(s)")

# ── Ask Claude ────────────────────────────────────────────────────────────────
print(f"\n🤖 Asking Claude to generate configuration...")

system_prompt = (
    "You are an expert Juniper network engineer. You will be given:\n"
    "1. The current running configuration of a Junos device in set format\n"
    "2. Reference snippets from Juniper Day One books\n"
    "3. A task to perform\n\n"
    "Your job is to generate ONLY the set commands needed to complete the task.\n\n"
    "RULES:\n"
    "1. Analyse the current config first. Do NOT generate commands for things already correctly configured.\n"
    "2. Output ONLY the set commands, one per line, no explanations, no headers.\n"
    "3. Use exact Junos set command syntax.\n"
    "4. If a setting needs to be removed first, include the 'delete' command before the 'set' command.\n"
    "5. If the task cannot be completed safely from the available information, output only: CANNOT_COMPLETE: <reason>\n"
    "6. Do not output anything except set/delete commands or CANNOT_COMPLETE."
)

user_prompt = (
    f"Current device configuration:\n\n{config_text}\n\n"
    f"Reference material from Juniper Day One books:\n\n{context}\n\n"
    f"Task: {task}\n\n"
    f"Output only the set/delete commands needed:"
)

try:
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    )
    raw_output = message.content[0].text.strip()
except anthropic.AuthenticationError:
    print("❌ Invalid API key.")
    dev.close()
    sys.exit(1)
except Exception as e:
    print(f"❌ Claude API error: {e}")
    dev.close()
    sys.exit(1)

# ── Check for CANNOT_COMPLETE ─────────────────────────────────────────────────
if raw_output.startswith("CANNOT_COMPLETE"):
    print(f"\n⚠️  Claude cannot complete this task:")
    print(f"   {raw_output.replace('CANNOT_COMPLETE: ', '')}")
    dev.close()
    sys.exit(0)

# Parse commands — only lines starting with set or delete
commands = [
    line.strip()
    for line in raw_output.splitlines()
    if line.strip().startswith(("set ", "delete "))
]

if not commands:
    print("\n⚠️  Claude did not generate any valid set/delete commands.")
    print("   Raw output:")
    print(raw_output)
    dev.close()
    sys.exit(0)

# ── Show proposed changes ─────────────────────────────────────────────────────
print("")
print("=" * 60)
print(" PROPOSED CONFIGURATION CHANGES")
print("=" * 60)
for cmd in commands:
    print(f"  {cmd}")
print("=" * 60)
print(f" {len(commands)} command(s) | Sources: {', '.join(sources.keys())}")
print("=" * 60)

# ── Dry run / commit check ────────────────────────────────────────────────────
print("\n🔍 Running commit check (dry run)...")

try:
    cu.lock()
    config_block = "\n".join(commands)
    cu.load(config_block, format="set")
    check_result = cu.commit_check()
    if check_result:
        print("✅ Commit check passed — configuration is valid.")
    else:
        print("❌ Commit check failed — configuration has errors.")
        cu.rollback()
        cu.unlock()
        dev.close()
        sys.exit(1)
except ConfigLoadError as e:
    print(f"❌ Config load error: {e}")
    try:
        cu.rollback()
        cu.unlock()
    except Exception:
        pass
    dev.close()
    sys.exit(1)
except Exception as e:
    print(f"❌ Dry run error: {e}")
    try:
        cu.rollback()
        cu.unlock()
    except Exception:
        pass
    dev.close()
    sys.exit(1)

# ── Confirm and apply ─────────────────────────────────────────────────────────
print("")
confirm = input("Apply this configuration? (yes/no): ").strip().lower()

if confirm != "yes":
    print("\n⚠️  Aborted. Rolling back...")
    cu.rollback()
    cu.unlock()
    dev.close()
    print("✅ No changes were made.")
    sys.exit(0)

print("\n📤 Applying configuration...")

try:
    cu.commit(comment=f"AI configurator: {task}")
    cu.unlock()
    print("✅ Configuration committed successfully.")
except CommitError as e:
    print(f"❌ Commit failed: {e}")
    print("   Rolling back...")
    cu.rollback()
    cu.unlock()
    dev.close()
    sys.exit(1)
except Exception as e:
    print(f"❌ Unexpected error during commit: {e}")
    try:
        cu.rollback()
        cu.unlock()
    except Exception:
        pass
    dev.close()
    sys.exit(1)

# ── Done ──────────────────────────────────────────────────────────────────────
dev.close()

print("")
print("=" * 60)
print(" DONE")
print("=" * 60)
print(f" Task   : {task}")
print(f" Device : {device_ip}")
print(f" Changes: {len(commands)} command(s) applied")
print("=" * 60)
