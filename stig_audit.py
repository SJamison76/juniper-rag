import sys
import os
import time
import anthropic
import chromadb
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH      = os.path.join(os.path.expanduser("~"), "juniper_vector_db")
CLAUDE_MODEL = "claude-sonnet-4-6"
BATCH_SIZE   = 5    # rules evaluated per Claude call
RATE_SLEEP   = 1    # seconds between batches
# ─────────────────────────────────────────────────────────────────────────────

load_dotenv()

# ── API key check ─────────────────────────────────────────────────────────────
if not os.environ.get("ANTHROPIC_API_KEY"):
    print("❌ ANTHROPIC_API_KEY is not set.")
    print("   Add it to ~/.bashrc:  export ANTHROPIC_API_KEY='sk-ant-...'")
    sys.exit(1)

# ── Args ──────────────────────────────────────────────────────────────────────
if len(sys.argv) < 2:
    print("Usage: python stig_audit.py <config.txt> [severity]")
    print("")
    print("Examples:")
    print("  python stig_audit.py config.txt")
    print("  python stig_audit.py config.txt high        (only evaluate high severity rules)")
    print("  python stig_audit.py config.txt medium")
    print("")
    print("Pull a config from a device first:")
    print("  ssh admin@192.168.1.1 'show configuration | display set' > config.txt")
    sys.exit(1)

config_file    = sys.argv[1]
severity_filter = sys.argv[2].lower() if len(sys.argv) > 2 else None

# ── Read config file ──────────────────────────────────────────────────────────
if not os.path.exists(config_file):
    print(f"❌ Config file not found: {config_file}")
    sys.exit(1)

with open(config_file, "r") as f:
    config_text = f.read().strip()

if not config_text:
    print(f"❌ Config file is empty: {config_file}")
    sys.exit(1)

print("")
print("=" * 60)
print(f" DoD STIG Configuration Auditor")
print(f" Config : {config_file}")
print(f" Filter : {severity_filter if severity_filter else 'all severities'}")
print("=" * 60)

# ── Load STIG rules from ChromaDB ─────────────────────────────────────────────
print("\n📥 Loading STIG rules from vector database...")

try:
    chroma_client   = chromadb.PersistentClient(path=DB_PATH)
    stig_collection = chroma_client.get_collection(name="juniper_stigs")
except Exception as e:
    print(f"❌ Could not open STIG database: {e}")
    print("   Run index_stigs.py first to build the database.")
    sys.exit(1)

# Retrieve rules — optionally filter by severity
if severity_filter:
    stig_results = stig_collection.get(
        where={"$and": [{"type": {"$eq": "network_stig"}}, {"severity": {"$eq": severity_filter}}]},
        include=["documents", "metadatas"]
    )
else:
    stig_results = stig_collection.get(
        where={"type": {"$eq": "network_stig"}},
        include=["documents", "metadatas"]
    )

rules     = stig_results["documents"]
metadatas = stig_results["metadatas"]

if not rules:
    print("❌ No STIG rules found. Run index_stigs.py first.")
    sys.exit(1)

total_batches = (len(rules) + BATCH_SIZE - 1) // BATCH_SIZE
print(f"✅ Loaded {len(rules)} rules — {total_batches} batches of {BATCH_SIZE}")

# ── Claude client and cached config block ─────────────────────────────────────
client = anthropic.Anthropic()

# Cache the device config — it's sent with every batch call so caching saves significantly
cached_config = {
    "type": "text",
    "text": f"DEVICE CONFIGURATION UNDER AUDIT:\n\n{config_text}",
    "cache_control": {"type": "ephemeral"}
}

# Cache the system prompt too
system_prompt = [
    {
        "type": "text",
        "text": (
            "You are a strict DoD STIG compliance auditor evaluating a Juniper Junos configuration.\n"
            "Evaluate EVERY rule in the batch provided. Do not skip any.\n\n"
            "For each rule output exactly this format, then a line with just ---:\n\n"
            "VULN_ID: <rule id>\n"
            "STATUS: PASS or FAIL\n"
            "JUSTIFICATION: <one sentence>\n"
            "FIX: <exact Junos set or delete command, or NONE if PASS>\n"
            "---\n\n"
            "Rules:\n"
            "- Base STATUS only on what is present or absent in the config.\n"
            "- FIX must be a valid Junos set or delete command, never prose.\n"
            "- If multiple commands are needed, put each on its own FIX: line.\n"
            "- Plain text only, no markdown, no backticks."
        ),
        "cache_control": {"type": "ephemeral"}
    }
]

# ── Evaluation loop ───────────────────────────────────────────────────────────
print(f"\n🤖 Evaluating config against STIG rules...\n")

all_findings        = []
remediation_commands = []
pass_count          = 0
fail_count          = 0
cache_hit_reported  = False

for i in range(0, len(rules), BATCH_SIZE):
    batch_rules = rules[i:i + BATCH_SIZE]
    batch_metas = metadatas[i:i + BATCH_SIZE]

    checklist_text = ""
    for idx, rule_text in enumerate(batch_rules):
        vuln_id  = batch_metas[idx].get("vuln_id", "Unknown")
        severity = batch_metas[idx].get("severity", "unknown")
        checklist_text += f"--- RULE ID: {vuln_id} | Severity: {severity} ---\n{rule_text}\n\n"

    current_batch = (i // BATCH_SIZE) + 1

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        cached_config,
                        {
                            "type": "text",
                            "text": f"Evaluate this batch of STIG rules:\n\n{checklist_text}"
                        }
                    ]
                }
            ],
            temperature=0
        )

        batch_output = response.content[0].text.strip()
        all_findings.append(batch_output)

        # Count pass/fail
        for line in batch_output.splitlines():
            if line.startswith("STATUS:"):
                if "PASS" in line:
                    pass_count += 1
                elif "FAIL" in line:
                    fail_count += 1
            # Extract remediation commands
            if line.startswith("FIX:") and "NONE" not in line:
                cmd = line.replace("FIX:", "").strip().strip("`'\" ")
                if cmd.startswith(("set ", "delete ")):
                    remediation_commands.append(cmd)

        # Cache stats
        usage = response.usage
        if not cache_hit_reported:
            if hasattr(usage, "cache_read_input_tokens") and usage.cache_read_input_tokens:
                print(f"   💾 Cache active — cost reduction engaged")
                cache_hit_reported = True
            elif hasattr(usage, "cache_creation_input_tokens") and usage.cache_creation_input_tokens:
                print(f"   💾 Cache written for subsequent batches")
                cache_hit_reported = True

        print(f"   Batch {current_batch}/{total_batches} complete...")
        time.sleep(RATE_SLEEP)

    except anthropic.RateLimitError:
        print("\n⚠️  Rate limit hit. Waiting 15 seconds...")
        time.sleep(15)
    except Exception as e:
        print(f"\n❌ Error on batch {current_batch}: {e}")
        sys.exit(1)

# ── Write output files ────────────────────────────────────────────────────────
print("\n✅ Evaluation complete.")
print(f"   PASS: {pass_count}  FAIL: {fail_count}  Total: {pass_count + fail_count}")

base        = config_file.rsplit(".", 1)[0]
report_file = f"{base}_stig_audit.txt"
remed_file  = f"{base}_stig_remediation.txt"

with open(report_file, "w") as f:
    f.write("DoD STIG Audit Report\n")
    f.write(f"Config : {config_file}\n")
    f.write(f"Filter : {severity_filter if severity_filter else 'all severities'}\n")
    f.write(f"PASS   : {pass_count}\n")
    f.write(f"FAIL   : {fail_count}\n")
    f.write("=" * 60 + "\n\n")
    f.write("\n\n".join(all_findings))

with open(remed_file, "w") as f:
    f.write("! STIG Remediation Script\n")
    f.write(f"! Generated from: {config_file}\n")
    f.write("! WARNING: Review every command before applying to a live device.\n")
    f.write("! Feed into do_configure.py or apply manually after review.\n")
    f.write("=" * 60 + "\n")
    for cmd in remediation_commands:
        f.write(cmd + "\n")

print(f"\n📄 Audit report    : {report_file}")
print(f"🛠️  Remediation script : {remed_file}")
print(f"\n   Review the remediation script carefully before applying.")
print(f"   You can feed it into do_configure.py or apply commands manually.")
