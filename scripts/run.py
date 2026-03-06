import json
import os
import re
import hashlib
import datetime
import requests
from pathlib import Path

# ─── CONFIG ───────────────────────────────────────────────────────
GROQ_API_KEY = "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"
GITHUB_TOKEN = os.getenv("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") or "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"
GITHUB_REPO  = "ayumathur9/clara-answers-outputs"
OUTPUTS_DIR  = Path("outputs/accounts")

# ─── PROMPTS ──────────────────────────────────────────────────────
DEMO_PROMPT = """You are a data extraction specialist for Clara Answers.
Extract ONLY explicitly stated data from this demo call transcript.
Return ONLY valid JSON, no markdown, no explanation.
Schema:
{
  "company_name": "",
  "business_hours": {"days": [], "start": "", "end": "", "timezone": ""},
  "office_address": "",
  "services_supported": [],
  "emergency_definition": [],
  "emergency_routing_rules": {"contacts": [], "order": [], "fallback": ""},
  "non_emergency_routing_rules": {"flow": "", "voicemail": false, "ticket_creation": false},
  "call_transfer_rules": {"timeout_seconds": null, "retries": null, "fail_message": ""},
  "integration_constraints": [],
  "after_hours_flow_summary": "",
  "office_hours_flow_summary": "",
  "questions_or_unknowns": [],
  "notes": ""
}"""

ONBOARDING_PROMPT = """You are a data extraction specialist for Clara Answers.
Extract CONFIRMED operational configuration from this ONBOARDING call transcript.
This data is precise and overrides demo assumptions.
Return ONLY valid JSON, no markdown, no explanation.
Schema:
{
  "company_name": "",
  "business_hours": {"days": [], "start": "", "end": "", "timezone": ""},
  "office_address": "",
  "services_supported": [],
  "emergency_definition": [],
  "emergency_routing_rules": {"contacts": [], "order": [], "fallback": ""},
  "non_emergency_routing_rules": {"flow": "", "voicemail": false, "ticket_creation": false},
  "call_transfer_rules": {"timeout_seconds": null, "retries": null, "fail_message": ""},
  "integration_constraints": [],
  "after_hours_flow_summary": "",
  "office_hours_flow_summary": "",
  "questions_or_unknowns": [],
  "notes": ""
}"""

# ─── GROQ CALL ────────────────────────────────────────────────────
def call_groq(system_prompt, transcript):
    # Split transcript into chunks and extract from each, then merge
    # This handles long transcripts properly
    chunk_size = 5000
    chunks = [transcript[i:i+chunk_size] for i in range(0, min(len(transcript), 20000), chunk_size)]
    
    all_extracted = []
    for i, chunk in enumerate(chunks):
        print(f"    Processing chunk {i+1}/{len(chunks)}...")
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.1-8b-instant",
                "temperature": 0,
                "max_tokens": 4000,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Extract data from this transcript chunk:\n\n{chunk}"}
                ]
            },
            timeout=60
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*', '', raw)
        raw = re.sub(r'\s*```\s*$', '', raw)
        try:
            extracted = json.loads(raw)
            all_extracted.append(extracted)
        except:
            continue
    
    if not all_extracted:
        raise ValueError("No data extracted from any chunk")
    
    # Merge all chunks - non-empty values win
    merged = all_extracted[0]
    for chunk_data in all_extracted[1:]:
        for key, val in chunk_data.items():
            if isinstance(val, list) and val:
                if not merged.get(key):
                    merged[key] = val
                else:
                    # Add new unique items
                    for item in val:
                        if item not in merged[key]:
                            merged[key].append(item)
            elif isinstance(val, dict):
                if not merged.get(key):
                    merged[key] = val
                else:
                    for k, v in val.items():
                        if v and not merged[key].get(k):
                            merged[key][k] = v
            elif val and not merged.get(key):
                merged[key] = val
    
    return merged

# ─── ACCOUNT ID ───────────────────────────────────────────────────
def make_account_id(company_name):
    slug = re.sub(r'[^a-z0-9]+', '_', company_name.lower()).strip('_')
    h = hashlib.md5(company_name.encode()).hexdigest()[:6]
    return f"{slug}_{h}"

# ─── AGENT PROMPT ─────────────────────────────────────────────────
def build_agent_prompt(memo, version):
    company  = memo.get("company_name") or "the company"
    bh       = memo.get("business_hours") or {}
    days     = ", ".join(bh.get("days") or []) or "Monday-Friday"
    start    = bh.get("start") or "8:00 AM"
    end      = bh.get("end")   or "5:00 PM"
    tz       = bh.get("timezone") or "local time"
    services = ", ".join(memo.get("services_supported") or []) or "general service requests"
    er       = memo.get("emergency_routing_rules") or {}
    primary  = (er.get("contacts") or ["on-call technician"])[0]
    tr       = memo.get("call_transfer_rules") or {}
    timeout  = tr.get("timeout_seconds") or 30
    em_list  = memo.get("emergency_definition") or []
    em_text  = ", ".join(em_list) or "active leaks, fire alarms, safety hazards"
    fallback = er.get("fallback") or "I was unable to reach our team. A technician will call you back within 15 minutes."

    constraints = memo.get("integration_constraints") or []
    c_block = ""
    if constraints:
        c_block = "\n\nOPERATIONAL CONSTRAINTS (never mention to caller):\n" + "\n".join(f"- {c}" for c in constraints)

    return f"""You are Clara, a professional AI receptionist for {company}.

BUSINESS HOURS: {days}, {start} - {end} {tz}
SERVICES: {services}

DURING BUSINESS HOURS:
1. Greeting: "Thank you for calling {company}. This is Clara. How can I help you today?"
2. Listen and classify the call.
3. Collect: full name and callback number only.
4. Transfer to appropriate contact. If transfer fails after {timeout}s: "{fallback}"
5. Confirm next steps.
6. "Is there anything else?" then close.

AFTER HOURS:
1. Greeting: "Thank you for calling {company}. You've reached us after hours. I'm Clara."
2. "Is this an emergency requiring immediate attention?"
3A. IF EMERGENCY (e.g. {em_text}):
    Collect: name, callback number, site address immediately.
    Transfer to {primary}. If fails: "{fallback}"
    Assure: "A technician will contact you within 15 minutes."
3B. IF NON-EMERGENCY:
    Collect: name, number, brief description.
    Confirm next business day follow-up.
4. "Anything else?" then close.

RULES:
- Never mention function calls, tools, or APIs to the caller.
- Never invent information.
- Always confirm name and number before transferring.{c_block}

[Version: {version}]"""

# ─── SAVE TO GITHUB ───────────────────────────────────────────────
def save_to_github(path, content, message):
    import base64
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    
    # Check if file exists to get sha
    sha = None
    check = requests.get(url, headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    })
    if check.status_code == 200:
        sha = check.json()["sha"]
    
    body = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode()
    }
    if sha:
        body["sha"] = sha
    
    resp = requests.put(url, headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json"
    }, json=body)
    resp.raise_for_status()
    print(f"  ✅ Saved to GitHub: {path}")

# ─── PIPELINE A ───────────────────────────────────────────────────
def pipeline_a(transcript_path):
    print(f"\n{'='*50}")
    print(f"PIPELINE A — Demo Call → v1")
    print(f"File: {transcript_path}")
    print(f"{'='*50}")

    transcript = Path(transcript_path).read_text(encoding="utf-8")
    
    print("  [1/4] Calling Groq for extraction...")
    extracted = call_groq(DEMO_PROMPT, transcript)
    
    print("  [2/4] Building memo...")
    company_name = extracted.get("company_name") or "unknown_company"
    account_id = make_account_id(company_name)
    now = datetime.datetime.utcnow().isoformat()
    
    memo = {
        "account_id": account_id,
        "company_name": extracted.get("company_name", ""),
        "business_hours": extracted.get("business_hours", {"days": [], "start": "", "end": "", "timezone": ""}),
        "office_address": extracted.get("office_address", ""),
        "services_supported": extracted.get("services_supported", []),
        "emergency_definition": extracted.get("emergency_definition", []),
        "emergency_routing_rules": extracted.get("emergency_routing_rules", {"contacts": [], "order": [], "fallback": ""}),
        "non_emergency_routing_rules": extracted.get("non_emergency_routing_rules", {"flow": "", "voicemail": False, "ticket_creation": False}),
        "call_transfer_rules": extracted.get("call_transfer_rules", {"timeout_seconds": None, "retries": None, "fail_message": ""}),
        "integration_constraints": extracted.get("integration_constraints", []),
        "after_hours_flow_summary": extracted.get("after_hours_flow_summary", ""),
        "office_hours_flow_summary": extracted.get("office_hours_flow_summary", ""),
        "questions_or_unknowns": extracted.get("questions_or_unknowns", []),
        "notes": extracted.get("notes", ""),
        "version": "v1",
        "source": "demo_call",
        "created_at": now,
        "updated_at": now
    }

    print("  [3/4] Building agent spec...")
    agent_prompt = build_agent_prompt(memo, "v1")
    agent_spec = {
        "agent_name": f"Clara - {company_name} (v1)",
        "version": "v1",
        "system_prompt": agent_prompt,
        "key_variables": {
            "timezone": memo["business_hours"].get("timezone", ""),
            "business_hours_start": memo["business_hours"].get("start", ""),
            "business_hours_end": memo["business_hours"].get("end", ""),
            "emergency_contacts": memo["emergency_routing_rules"].get("contacts", [])
        },
        "generated_at": now
    }

    print("  [4/4] Saving outputs...")
    out_dir = OUTPUTS_DIR / account_id / "v1"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "account_memo.json").write_text(json.dumps(memo, indent=2))
    (out_dir / "agent_spec.json").write_text(json.dumps(agent_spec, indent=2))
    (out_dir / "agent_prompt.txt").write_text(agent_prompt)

    save_to_github(f"outputs/accounts/{account_id}/v1/account_memo.json", json.dumps(memo, indent=2), f"feat: add v1 memo for {company_name}")
    save_to_github(f"outputs/accounts/{account_id}/v1/agent_spec.json", json.dumps(agent_spec, indent=2), f"feat: add v1 agent spec for {company_name}")

    print(f"\n  ✅ Pipeline A complete")
    print(f"     Account ID : {account_id}")
    print(f"     Company    : {company_name}")
    print(f"     Unknowns   : {len(memo['questions_or_unknowns'])} flagged")
    print(f"     Output     : {out_dir}")
    print(f"\n  ⚠️  SAVE THIS ACCOUNT ID FOR PIPELINE B: {account_id}\n")
    
    return account_id, memo

# ─── PIPELINE B ───────────────────────────────────────────────────
def pipeline_b(transcript_path, account_id):
    print(f"\n{'='*50}")
    print(f"PIPELINE B — Onboarding → v2")
    print(f"Account ID: {account_id}")
    print(f"{'='*50}")

    # Load v1 memo
    v1_path = OUTPUTS_DIR / account_id / "v1" / "account_memo.json"
    if not v1_path.exists():
        raise FileNotFoundError(f"No v1 memo found. Run Pipeline A first.")
    
    v1_memo = json.loads(v1_path.read_text())
    print(f"  [1/5] Loaded v1 memo for {v1_memo.get('company_name')}")

    # Extract onboarding data
    print("  [2/5] Calling Groq for onboarding extraction...")
    transcript = Path(transcript_path).read_text(encoding="utf-8")
    onboarding_data = call_groq(ONBOARDING_PROMPT, transcript)

    # Smart merge
    print("  [3/5] Merging v1 → v2...")
    import copy
    v2_memo = copy.deepcopy(v1_memo)
    
    def merge(base, update):
        for key, val in update.items():
            if key in ("account_id", "created_at"):
                continue
            if isinstance(val, list) and val:
                base[key] = val
            elif isinstance(val, dict) and isinstance(base.get(key), dict):
                merge(base[key], val)
            elif val is not None and val != "":
                base[key] = val
    
    merge(v2_memo, onboarding_data)
    v2_memo["version"] = "v2"
    v2_memo["source"] = "onboarding_call"
    v2_memo["updated_at"] = datetime.datetime.utcnow().isoformat()

    # Diff
    print("  [4/5] Computing diff...")
    changes = []
    skip = {"version", "updated_at", "created_at", "source", "account_id"}
    
    def diff(v1, v2, path=""):
        for key in set(list(v1.keys()) + list(v2.keys())):
            if key in skip:
                continue
            fp = f"{path}.{key}" if path else key
            ov, nv = v1.get(key), v2.get(key)
            if json.dumps(ov, sort_keys=True) == json.dumps(nv, sort_keys=True):
                continue
            if isinstance(ov, list) and isinstance(nv, list):
                added   = [x for x in nv if x not in ov]
                removed = [x for x in ov if x not in nv]
                if added:   changes.append({"field": fp, "type": "added",   "items": added})
                if removed: changes.append({"field": fp, "type": "removed", "items": removed})
            elif isinstance(ov, dict) and isinstance(nv, dict):
                diff(ov, nv, fp)
            elif not ov:
                changes.append({"field": fp, "type": "populated", "from": ov, "to": nv})
            else:
                changes.append({"field": fp, "type": "updated", "from": ov, "to": nv})
    
    diff(v1_memo, v2_memo)

    # Build changelog
    lines = [
        f"# Changelog — {v2_memo.get('company_name')}",
        f"**Account ID:** {account_id}",
        f"**Transition:** v1 → v2",
        f"**Total changes:** {len(changes)}",
        "", "---", ""
    ]
    for c in changes:
        if c["type"] == "populated":
            lines.append(f"### ✅ `{c['field']}` — Confirmed in onboarding")
            lines.append(f"- **Now:** `{c['to']}`")
        elif c["type"] == "updated":
            lines.append(f"### 🔄 `{c['field']}` — Updated")
            lines.append(f"- **Was:** `{c['from']}`")
            lines.append(f"- **Now:** `{c['to']}`")
        elif c["type"] == "added":
            lines.append(f"### ➕ `{c['field']}` — Added")
            for i in c["items"]: lines.append(f"- `{i}`")
        elif c["type"] == "removed":
            lines.append(f"### ➖ `{c['field']}` — Removed")
            for i in c["items"]: lines.append(f"- `{i}`")
        lines.append("")
    
    changelog_md = "\n".join(lines)

    # Build agent spec v2
    agent_prompt_v2 = build_agent_prompt(v2_memo, "v2")
    now = datetime.datetime.utcnow().isoformat()
    agent_spec_v2 = {
        "agent_name": f"Clara - {v2_memo.get('company_name')} (v2)",
        "version": "v2",
        "system_prompt": agent_prompt_v2,
        "key_variables": {
            "timezone": v2_memo["business_hours"].get("timezone", ""),
            "business_hours_start": v2_memo["business_hours"].get("start", ""),
            "business_hours_end": v2_memo["business_hours"].get("end", ""),
            "emergency_contacts": v2_memo["emergency_routing_rules"].get("contacts", [])
        },
        "generated_at": now
    }

    # Save
    print("  [5/5] Saving outputs...")
    out_dir = OUTPUTS_DIR / account_id / "v2"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "account_memo.json").write_text(json.dumps(v2_memo, indent=2), encoding="utf-8")
    (out_dir / "agent_spec.json").write_text(json.dumps(agent_spec_v2, indent=2), encoding="utf-8")
    (out_dir / "agent_prompt.txt").write_text(agent_prompt_v2, encoding="utf-8")
    (out_dir / "changelog.md").write_text(changelog_md, encoding="utf-8")
    (out_dir / "changelog.json").write_text(json.dumps({"changes": changes}, indent=2), encoding="utf-8")

    save_to_github(f"outputs/accounts/{account_id}/v2/account_memo.json", json.dumps(v2_memo, indent=2), f"feat: add v2 memo for {v2_memo.get('company_name')}")
    save_to_github(f"outputs/accounts/{account_id}/v2/changelog.md", changelog_md, f"feat: add changelog for {v2_memo.get('company_name')}")

    print(f"\n  ✅ Pipeline B complete")
    print(f"     Company  : {v2_memo.get('company_name')}")
    print(f"     Changes  : {len(changes)} fields updated")
    print(f"     Output   : {out_dir}")

# ─── MAIN ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) == 2:
        # Run Pipeline A only
        pipeline_a(sys.argv[1])
    
    elif len(sys.argv) == 3:
        # Run Pipeline B
        pipeline_b(sys.argv[1], sys.argv[2])
    
    elif len(sys.argv) == 1:
        # Run both interactively
        print("CLARA ANSWERS PIPELINE")
        print("=" * 50)
        demo_path = input("Enter path to demo transcript: ").strip()
        account_id, _ = pipeline_a(demo_path)
        
        run_b = input("\nRun Pipeline B now? (y/n): ").strip().lower()
        if run_b == 'y':
            onboard_path = input("Enter path to onboarding transcript: ").strip()
            pipeline_b(onboard_path, account_id)
    
    else:
        print("Usage:")
        print("  python run.py data/demo.txt")
        print("  python run.py data/onboarding.txt <account_id>")