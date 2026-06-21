import sys
import os
import json
import xml.etree.ElementTree as ET
import chromadb
from chromadb.utils import embedding_functions

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH         = os.path.join(os.path.expanduser("~"), "juniper_vector_db")
STIG_DIR        = "/srv/ftp/stigs"
CHECKPOINT_FILE = os.path.join(os.path.expanduser("~"), "juniper_stig_checkpoint.json")
# ─────────────────────────────────────────────────────────────────────────────

# ── Optional single file mode ─────────────────────────────────────────────────
# Can still be called with a specific XML file, or with no args to scan all
single_file = sys.argv[1] if len(sys.argv) > 1 else None

if single_file and not os.path.exists(single_file):
    print(f"❌ XML file not found: {single_file}")
    sys.exit(1)

# ── Load checkpoint ───────────────────────────────────────────────────────────
if os.path.exists(CHECKPOINT_FILE):
    with open(CHECKPOINT_FILE, "r") as f:
        completed = set(json.load(f))
    print(f"📋 Checkpoint found: {len(completed)} STIG file(s) already indexed.\n")
else:
    completed = set()

# ── Find XML files to index ───────────────────────────────────────────────────
if single_file:
    xml_files = [single_file]
else:
    xml_files = []
    for root_dir, dirs, files in os.walk(STIG_DIR):
        for f in sorted(files):
            if f.endswith(".xml"):
                xml_files.append(os.path.join(root_dir, f))
    xml_files.sort()

if not xml_files:
    print(f"❌ No XML files found in {STIG_DIR}")
    print(f"   Download STIG XML files from https://public.cyber.mil/stigs/downloads/")
    sys.exit(1)

print(f"📚 Found {len(xml_files)} STIG XML file(s) to process.\n")

# ── ChromaDB setup ────────────────────────────────────────────────────────────
try:
    chroma_client = chromadb.PersistentClient(path=DB_PATH)
    ollama_ef = embedding_functions.OllamaEmbeddingFunction(
        url="http://localhost:11434/api/embeddings",
        model_name="all-minilm"
    )
    stig_collection = chroma_client.get_or_create_collection(
        name="juniper_stigs",
        embedding_function=ollama_ef
    )
except Exception as e:
    print(f"❌ Database error: {e}")
    sys.exit(1)

# ── Process each XML file ─────────────────────────────────────────────────────
grand_total   = 0
grand_skipped = 0

for file_idx, xml_file in enumerate(xml_files, 1):
    filename = os.path.basename(xml_file)

    if xml_file in completed:
        print(f"[{file_idx}/{len(xml_files)}] Skipping (already indexed): {filename}")
        continue

    print(f"[{file_idx}/{len(xml_files)}] Indexing: {filename}")

    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
    except Exception as e:
        print(f"    ❌ Failed to parse XML: {e}\n")
        continue

    ns     = {"xccdf": "http://checklists.nist.gov/xccdf/1.1"}
    groups = root.findall(".//xccdf:Group", ns)

    if not groups:
        print(f"    ⚠️  No vulnerability groups found. Skipping.\n")
        continue

    benchmark      = root.find("xccdf:title", ns)
    stig_title     = benchmark.text if benchmark is not None else filename
    benchmark_id   = root.get("id", filename)  # e.g. Juniper_EX_NDM_STIG
    print(f"    STIG : {stig_title}")
    print(f"    ID   : {benchmark_id}")
    print(f"    Rules: {len(groups)}")

    batch_docs, batch_metas, batch_ids = [], [], []
    total_indexed = 0
    skipped       = 0

    for group in groups:
        vuln_id = group.get("id", "UNKNOWN")
        rule    = group.find(".//xccdf:Rule", ns)

        if rule is None:
            skipped += 1
            continue

        severity     = rule.get("severity", "unknown")
        rule_id      = rule.get("id", vuln_id)          # e.g. SV-253878r1028864_rule
        rule_version = rule.findtext("xccdf:version", default="", namespaces=ns)  # e.g. JUEX-NM-000010
        title        = rule.findtext("xccdf:title", default="No Title", namespaces=ns)
        check        = rule.findtext(".//xccdf:check-content", default="No Check Content", namespaces=ns)
        fix          = rule.findtext(".//xccdf:fixtext", default="No Fix Text", namespaces=ns)

        # Skip duplicates already in the collection
        existing = stig_collection.get(ids=[vuln_id])
        if existing["ids"]:
            skipped += 1
            continue

        document_content = (
            f"STIG ID: {vuln_id}\n"
            f"Severity: {severity}\n"
            f"Title: {title}\n"
            f"Check: {check}\n"
            f"Fix: {fix}"
        )

        batch_docs.append(document_content)
        batch_metas.append({
            "vuln_id":      vuln_id,
            "rule_id":      rule_id,
            "rule_version": rule_version,
            "severity":     severity,
            "title":        title[:200],
            "stig":         stig_title[:200],
            "benchmark_id": benchmark_id,
            "type":         "network_stig"
        })
        batch_ids.append(vuln_id)

        if len(batch_docs) >= 50:
            stig_collection.add(documents=batch_docs, metadatas=batch_metas, ids=batch_ids)
            total_indexed += len(batch_docs)
            batch_docs, batch_metas, batch_ids = [], [], []

    # Flush remaining
    if batch_docs:
        stig_collection.add(documents=batch_docs, metadatas=batch_metas, ids=batch_ids)
        total_indexed += len(batch_docs)

    # Save checkpoint for this file
    completed.add(xml_file)
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(list(completed), f)

    grand_total   += total_indexed
    grand_skipped += skipped
    print(f"    ✅ {total_indexed} rules indexed, {skipped} skipped.\n")

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"🎉 Done. {grand_total} rules indexed this run, {grand_skipped} skipped.")
print(f"   Collection 'juniper_stigs' now contains {stig_collection.count()} total rules.")
print(f"\n   Run stig_audit.py to evaluate a device config against these rules.")
