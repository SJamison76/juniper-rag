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

config_file     = sys.argv[1]
severity_filter = sys.argv[2].lower() if len(sys.argv) > 2 else None
device_type     = os.environ.get("STIG_DEVICE_TYPE")  # passed from start.py

# ── Device type to STIG title keyword mapping ─────────────────────────────────
DEVICE_TYPE_MAP = {
    "ex":     ["EX Series", "EX Switches"],
    "srx":    ["SRX Services Gateway", "SRX SG"],
    "router": ["Juniper Router"],
}

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
print(f" Config      : {config_file}")
print(f" Severity    : {severity_filter if severity_filter else 'all'}")
print(f" Device type : {device_type if device_type else 'all'}")
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

# Retrieve rules — filter by severity and/or device type
# Build where clause
where_clauses = [{"type": {"$eq": "network_stig"}}]
if severity_filter:
    where_clauses.append({"severity": {"$eq": severity_filter}})

if len(where_clauses) > 1:
    stig_results = stig_collection.get(
        where={"$and": where_clauses},
        include=["documents", "metadatas"]
    )
else:
    stig_results = stig_collection.get(
        where={"type": {"$eq": "network_stig"}},
        include=["documents", "metadatas"]
    )

rules     = stig_results["documents"]
metadatas = stig_results["metadatas"]

# Apply device type filter in Python (ChromaDB doesn't support substring matching)
if device_type and device_type in DEVICE_TYPE_MAP:
    keywords = DEVICE_TYPE_MAP[device_type]
    filtered = [
        (doc, meta) for doc, meta in zip(rules, metadatas)
        if any(kw.lower() in meta.get("stig", "").lower() for kw in keywords)
    ]
    if filtered:
        rules, metadatas = zip(*filtered)
        rules     = list(rules)
        metadatas = list(metadatas)
    else:
        print(f"⚠️  No rules matched device type '{device_type}' — using all rules.")

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
structured_findings  = []   # list of dicts for CKL export
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

        # Count pass/fail and build structured findings for CKL
        current_finding = {}
        fix_lines = []

        for line in batch_output.splitlines():
            if line.startswith("VULN_ID:"):
                if current_finding:
                    current_finding["fix"] = " | ".join(fix_lines) if fix_lines else "NONE"
                    structured_findings.append(current_finding)
                current_finding = {"vuln_id": line.replace("VULN_ID:", "").strip(), "status": "", "justification": "", "fix": ""}
                fix_lines = []
            elif line.startswith("STATUS:"):
                status = line.replace("STATUS:", "").strip()
                current_finding["status"] = status
                if "PASS" in status:
                    pass_count += 1
                elif "FAIL" in status:
                    fail_count += 1
            elif line.startswith("JUSTIFICATION:"):
                current_finding["justification"] = line.replace("JUSTIFICATION:", "").strip()
            elif line.startswith("FIX:") and "NONE" not in line:
                cmd = line.replace("FIX:", "").strip().strip("`'\" ")
                if cmd.startswith(("set ", "delete ")):
                    fix_lines.append(cmd)
                    remediation_commands.append(cmd)

        # Flush last finding in batch
        if current_finding:
            current_finding["fix"] = " | ".join(fix_lines) if fix_lines else "NONE"
            structured_findings.append(current_finding)

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
report_dir  = os.environ.get("REPORT_DIR", os.path.dirname(os.path.abspath(config_file)))
report_file = os.path.join(report_dir, "stig_audit.txt")
remed_file  = os.path.join(report_dir, "stig_remediation.txt")
ckl_file    = os.path.join(report_dir, "stig_audit.ckl")

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

# ── Generate CKL file for STIG Viewer ────────────────────────────────────────
import xml.etree.ElementTree as ET
from datetime import datetime
import socket

hostname    = socket.gethostname()
timestamp   = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

# Build a lookup from vuln_id to metadata
meta_lookup = {m.get("vuln_id"): m for m in metadatas}

def esc(s):
    """Escape special XML characters."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

ckl_lines = []
ckl_lines.append('<?xml version="1.0" encoding="UTF-8"?>')
ckl_lines.append('<CHECKLIST>')
ckl_lines.append('  <ASSET>')
ckl_lines.append(f'    <ROLE>None</ROLE>')
ckl_lines.append(f'    <ASSET_TYPE>Computing</ASSET_TYPE>')
ckl_lines.append(f'    <HOST_NAME>{esc(hostname)}</HOST_NAME>')
ckl_lines.append(f'    <HOST_IP></HOST_IP>')
ckl_lines.append(f'    <HOST_MAC></HOST_MAC>')
ckl_lines.append(f'    <HOST_FQDN></HOST_FQDN>')
ckl_lines.append(f'    <TARGET_COMMENT>Generated by juniper-ask-books stig_audit.py on {timestamp}</TARGET_COMMENT>')
ckl_lines.append(f'    <WEB_OR_DATABASE>false</WEB_OR_DATABASE>')
ckl_lines.append(f'    <WEB_DB_SITE></WEB_DB_SITE>')
ckl_lines.append(f'    <WEB_DB_INSTANCE></WEB_DB_INSTANCE>')
ckl_lines.append('  </ASSET>')
ckl_lines.append('  <STIGS>')
ckl_lines.append('    <iSTIG>')
ckl_lines.append('      <STIG_INFO>')
ckl_lines.append(f'        <SI_DATA><SID_NAME>title</SID_NAME><SID_DATA>Juniper AI Audit</SID_DATA></SI_DATA>')
ckl_lines.append(f'        <SI_DATA><SID_NAME>version</SID_NAME><SID_DATA>1</SID_DATA></SI_DATA>')
ckl_lines.append(f'        <SI_DATA><SID_NAME>releaseinfo</SID_NAME><SID_DATA>Generated {timestamp}</SID_DATA></SI_DATA>')
ckl_lines.append('      </STIG_INFO>')

for finding in structured_findings:
    vuln_id      = finding.get("vuln_id", "UNKNOWN")
    status       = finding.get("status", "NOT_REVIEWED")
    justification = finding.get("justification", "")
    fix          = finding.get("fix", "NONE")
    meta         = meta_lookup.get(vuln_id, {})
    severity     = meta.get("severity", "medium")
    title        = meta.get("title", "")

    # Map to CKL status values
    if "PASS" in status.upper():
        ckl_status = "NotAFinding"
    elif "FAIL" in status.upper():
        ckl_status = "Open"
    else:
        ckl_status = "Not_Reviewed"

    # Map severity to CAT
    cat_map = {"high": "CAT I", "medium": "CAT II", "low": "CAT III"}
    cat = cat_map.get(severity.lower(), "CAT II")

    ckl_lines.append('      <VULN>')
    ckl_lines.append(f'        <STIG_DATA><VULN_ATTRIBUTE>Vuln_Num</VULN_ATTRIBUTE><ATTRIBUTE_DATA>{esc(vuln_id)}</ATTRIBUTE_DATA></STIG_DATA>')
    ckl_lines.append(f'        <STIG_DATA><VULN_ATTRIBUTE>Severity</VULN_ATTRIBUTE><ATTRIBUTE_DATA>{esc(cat)}</ATTRIBUTE_DATA></STIG_DATA>')
    ckl_lines.append(f'        <STIG_DATA><VULN_ATTRIBUTE>Rule_Title</VULN_ATTRIBUTE><ATTRIBUTE_DATA>{esc(title)}</ATTRIBUTE_DATA></STIG_DATA>')
    ckl_lines.append(f'        <STATUS>{esc(ckl_status)}</STATUS>')
    ckl_lines.append(f'        <FINDING_DETAILS>{esc(justification)}</FINDING_DETAILS>')
    ckl_lines.append(f'        <COMMENTS>{esc(fix)}</COMMENTS>')
    ckl_lines.append('      </VULN>')

ckl_lines.append('    </iSTIG>')
ckl_lines.append('  </STIGS>')
ckl_lines.append('</CHECKLIST>')

with open(ckl_file, "w", encoding="utf-8") as f:
    f.write("\n".join(ckl_lines))

print(f"📋 STIG Viewer CKL  : {ckl_file}")

# ── Generate CKLB file for STIG Viewer 3.x ───────────────────────────────────
import json

cklb_file = os.path.join(report_dir, "stig_audit.cklb")

cklb_status_map = {
    "PASS": "not_a_finding",
    "FAIL": "open",
}

cklb = {
    "title": "Juniper AI STIG Audit",
    "id": timestamp,
    "active": True,
    "mode": 1,
    "has_path": True,
    "target_data": {
        "target_type": "Computing",
        "host_name": hostname,
        "ip_address": "",
        "mac_address": "",
        "fqdn": "",
        "comments": f"Generated by juniper-ask-books stig_audit.py on {timestamp}",
        "role": "None",
        "is_web_database": False,
        "technology_area": "",
        "web_db_site": "",
        "web_db_instance": ""
    },
    "stigs": [
        {
            "stig_id": "Juniper_AI_Audit",
            "stig_name": "Juniper AI Audit",
            "display_name": "Juniper AI Audit",
            "checks": []
        }
    ]
}

for finding in structured_findings:
    vuln_id       = finding.get("vuln_id", "UNKNOWN")
    status        = finding.get("status", "NOT_REVIEWED").upper()
    justification = finding.get("justification", "")
    fix           = finding.get("fix", "NONE")
    meta          = meta_lookup.get(vuln_id, {})
    severity      = meta.get("severity", "medium")
    title         = meta.get("title", "")

    cat_map = {"high": "high", "medium": "medium", "low": "low"}
    cklb_status = cklb_status_map.get(status, "not_reviewed")

    cklb["stigs"][0]["checks"].append({
        "uuid": vuln_id,
        "stig_uuid": "Juniper_AI_Audit",
        "group_id": vuln_id,
        "rule_id": vuln_id,
        "rule_id_src": vuln_id,
        "weight": "10.0",
        "classification": "UNCLASSIFIED",
        "severity": cat_map.get(severity.lower(), "medium"),
        "rule_version": vuln_id,
        "group_title": title,
        "rule_title": title,
        "fix_text": fix,
        "false_positives": "",
        "false_negatives": "",
        "discussion": "",
        "check_content": "",
        "documentable": False,
        "mitigations": "",
        "potential_impact": "",
        "third_party_tools": "",
        "mitigation_control": "",
        "responsibility": "",
        "ia_controls": "",
        "status": cklb_status,
        "finding_details": justification,
        "comments": fix if cklb_status == "open" else "",
        "severity_override": "",
        "severity_justification": ""
    })

with open(cklb_file, "w", encoding="utf-8") as f:
    json.dump(cklb, f, indent=2)

print(f"📋 STIG Viewer CKLB : {cklb_file}")
print(f"\n   Review the remediation script carefully before applying.")
print(f"   You can feed it into do_configure.py or apply commands manually.")
print(f"   Open .cklb in STIG Viewer 3.x (Open Checklists → Open)")
print(f"   Or open .ckl in STIG Viewer 3.x (Open Checklists → Import V2 Checklist)")

