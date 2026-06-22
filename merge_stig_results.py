import sys
import os
import json

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Blank CKLB templates created by STIG Viewer — one per device type
TEMPLATES = {
    # Juniper
    "ex":            os.path.join(SCRIPT_DIR, "EX_New_Checklist.cklb"),
    "srx":           os.path.join(SCRIPT_DIR, "SRX_New_Checklist.cklb"),
    "router":        os.path.join(SCRIPT_DIR, "RTR_New_Checklist.cklb"),
    # Cisco
    "cisco_switch":  os.path.join(SCRIPT_DIR, "Cisco_Switch_Checklist.cklb"),
    "cisco_router":  os.path.join(SCRIPT_DIR, "Cisco_Router_Checklist.cklb"),
}
# ─────────────────────────────────────────────────────────────────────────────

# ── Usage ─────────────────────────────────────────────────────────────────────
if len(sys.argv) < 2:
    print("Usage: python3 merge_stig_results.py <stig_audit.txt> [device_type] [output.cklb]")
    print("")
    print("Device types: ex, srx, router, cisco_switch, cisco_router  (default: ex)")
    print("")
    print("Examples:")
    print("  python3 merge_stig_results.py reports/.../stig_audit.txt")
    print("  python3 merge_stig_results.py reports/.../stig_audit.txt ex")
    print("  python3 merge_stig_results.py reports/.../stig_audit.txt srx")
    sys.exit(1)

audit_file  = sys.argv[1]
device_type = sys.argv[2].lower() if len(sys.argv) > 2 else "ex"
output_file = sys.argv[3] if len(sys.argv) > 3 else \
              os.path.join(os.path.dirname(os.path.abspath(audit_file)),
                           f"stig_results_{device_type}.cklb")

if not os.path.exists(audit_file):
    print(f"❌ Audit file not found: {audit_file}")
    sys.exit(1)

if device_type not in TEMPLATES:
    print(f"❌ Unknown device type '{device_type}'. Use: ex, srx, router")
    sys.exit(1)

template_file = TEMPLATES[device_type]
if not os.path.exists(template_file):
    print(f"❌ Template not found: {template_file}")
    print(f"   Place the blank CKLB from STIG Viewer at that path.")
    sys.exit(1)

# ── Load blank CKLB template ──────────────────────────────────────────────────
print(f"📥 Loading blank checklist template: {os.path.basename(template_file)}")
with open(template_file, "r", encoding="utf-8") as f:
    cklb = json.load(f)

total_rules = sum(len(s.get("rules", [])) for s in cklb.get("stigs", []))
print(f"   {len(cklb.get('stigs', []))} STIGs, {total_rules} rules")
for s in cklb.get("stigs", []):
    print(f"   - {s.get('display_name', s.get('stig_name','?'))} ({len(s.get('rules',[]))} rules)")

# ── Parse audit results ───────────────────────────────────────────────────────
print(f"\n📥 Parsing audit results: {os.path.basename(audit_file)}")

findings = {}  # vuln_id -> {status, justification, fix}

with open(audit_file, "r", encoding="utf-8") as f:
    content = f.read()

blocks = content.split("---")

for block in blocks:
    lines   = block.strip().splitlines()
    current = {}
    fix_lines = []

    for line in lines:
        line = line.strip()
        if line.startswith("VULN_ID:"):
            current["vuln_id"] = line.replace("VULN_ID:", "").strip()
        elif line.startswith("STATUS:"):
            current["status"] = line.replace("STATUS:", "").strip()
        elif line.startswith("JUSTIFICATION:"):
            current["justification"] = line.replace("JUSTIFICATION:", "").strip()
        elif line.startswith("FIX:") and "NONE" not in line:
            cmd = line.replace("FIX:", "").strip()
            if cmd:
                fix_lines.append(cmd)

    if "vuln_id" in current:
        current["fix"] = "\n".join(fix_lines) if fix_lines else ""
        findings[current["vuln_id"]] = current

print(f"   Parsed {len(findings)} findings from audit")

# ── Status mapping ────────────────────────────────────────────────────────────
STATUS_MAP = {
    "PASS": "not_a_finding",
    "FAIL": "open",
}

# ── Merge findings into CKLB ──────────────────────────────────────────────────
print("\n🔀 Merging results into checklist...")

matched   = 0
unmatched = 0
pass_count = 0
fail_count = 0

for stig in cklb.get("stigs", []):
    for rule in stig.get("rules", []):
        vuln_id = rule.get("group_id", "")

        if vuln_id in findings:
            finding = findings[vuln_id]
            status  = finding.get("status", "").upper()
            cklb_status = STATUS_MAP.get(status, "not_reviewed")

            rule["status"]          = cklb_status
            rule["finding_details"] = finding.get("justification", "")
            rule["comments"]        = finding.get("fix", "")
            matched += 1

            if cklb_status == "not_a_finding":
                pass_count += 1
            elif cklb_status == "open":
                fail_count += 1
        else:
            rule["status"] = "not_reviewed"
            unmatched += 1

print(f"   Matched    : {matched} rules populated")
print(f"   Not reviewed (not in audit scope): {unmatched} rules")
print(f"   Open (FAIL): {fail_count}")
print(f"   Not a Finding (PASS): {pass_count}")

# ── Save output ───────────────────────────────────────────────────────────────
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(cklb, f, indent=2)

print(f"\n✅ Done. Results saved to: {output_file}")
print(f"   Open in STIG Viewer 3.x: Checklists → Load Checklist")
