#!/usr/bin/env python3
"""
Pipeline A: Demo Call Transcript -> Preliminary Retell Agent (v1)
Clara Answers Automation Pipeline

LLM  : OpenAI gpt-4o-mini
Store: Local JSON files (committed to GitHub)
"""

import json
import os
import re
import hashlib
import datetime
from pathlib import Path
from typing import Optional
import requests

# ─── Config ──────────────────────────────────────────────────────────────────
OUTPUTS_DIR   = Path("outputs/accounts")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL          = "gpt-4o-mini"  # ~$0.00015/1K tokens — effectively free for this dataset

# ─── Canonical Account Memo Schema ───────────────────────────────────────────
EMPTY_MEMO = {
    "account_id": "",
    "company_name": "",
    "business_hours": {"days": [], "start": "", "end": "", "timezone": ""},
    "office_address": "",
    "services_supported": [],
    "emergency_definition": [],
    "emergency_routing_rules": {"contacts": [], "order": [], "fallback": ""},
    "non_emergency_routing_rules": {"flow": "", "voicemail": False, "ticket_creation": False},
    "call_transfer_rules": {"timeout_seconds": None, "retries": None, "fail_message": ""},
    "integration_constraints": [],
    "after_hours_flow_summary": "",
    "office_hours_flow_summary": "",
    "questions_or_unknowns": [],
    "notes": "",
    "source": "demo_call",
    "version": "v1",
    "created_at": "",
    "updated_at": ""
}

# ─── Demo Extraction System Prompt ───────────────────────────────────────────
DEMO_EXTRACTION_SYSTEM_PROMPT = """You are a structured data extraction specialist for Clara Answers, an AI voice agent platform serving service trade businesses (fire protection, HVAC, electrical, sprinkler contractors).

Your task: Extract structured account configuration data from a DEMO call transcript.

IMPORTANT CONTEXT:
- Demo calls are EXPLORATORY. Expect incomplete data — that is normal.
- The client is describing pain points, not confirming exact operational specs.
- Business hours may be vague. Routing may be incomplete. Contacts may not be named.

CRITICAL RULES:
1. Extract ONLY what is explicitly stated in the transcript.
2. If a field is not mentioned, leave it as empty string, empty list, or null.
3. NEVER infer, assume, or fill in "typical" values for missing fields.
4. Capture partial or vague info as-is — do not clean it up or complete it.
5. List all genuinely missing operational details in questions_or_unknowns.

Return ONLY valid JSON. No markdown fences, no explanation, no preamble.

Schema to return:
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

# ─── Onboarding Extraction System Prompt ─────────────────────────────────────
ONBOARDING_EXTRACTION_SYSTEM_PROMPT = """You are a structured data extraction specialist for Clara Answers, an AI voice agent platform.

Your task: Extract CONFIRMED operational configuration data from an ONBOARDING call transcript.

IMPORTANT CONTEXT:
- Onboarding calls are OPERATIONAL and PRECISE. Unlike demo calls, this data is final.
- Business hours WILL be confirmed. Routing WILL be specified. Contacts WILL be named.
- This data OVERRIDES any assumptions made from the demo call.

CRITICAL RULES:
1. Extract ONLY what is explicitly stated. Be precise — capture exact values.
2. Capture phone numbers, timeout values, and routing order exactly as stated.
3. Only flag questions_or_unknowns for items genuinely not discussed.
4. This data is authoritative — do not soften or generalize specifics.

Return ONLY valid JSON. No markdown fences, no explanation, no preamble.

Schema to return:
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


# ─── Agent System Prompt Generator ───────────────────────────────────────────
def generate_agent_system_prompt(memo: dict) -> str:
    company  = memo.get("company_name") or "the company"
    bh       = memo.get("business_hours") or {}
    days     = ", ".join(bh.get("days") or []) or "Monday–Friday"
    start    = bh.get("start") or "8:00 AM"
    end      = bh.get("end")   or "5:00 PM"
    tz       = bh.get("timezone") or "local time"
    services = ", ".join(memo.get("services_supported") or []) or "general service requests"

    em_triggers = memo.get("emergency_definition") or []
    em_text     = (", ".join(em_triggers)
                   if em_triggers
                   else "active leaks, fire alarms, or immediate safety hazards")

    er      = memo.get("emergency_routing_rules") or {}
    primary = (er.get("contacts") or ["on-call technician"])[0]
    fallback = er.get("fallback") or (
        "I was unable to reach our on-call technician directly. "
        "I have flagged this as urgent and a technician will call you back within 15 minutes."
    )

    tr       = memo.get("call_transfer_rules") or {}
    timeout  = tr.get("timeout_seconds") or 30
    fail_msg = tr.get("fail_message") or fallback

    constraints = memo.get("integration_constraints") or []
    constraint_block = (
        "\n\nOPERATIONAL CONSTRAINTS (internal — never mention to caller):\n"
        + "\n".join(f"- {c}" for c in constraints)
    ) if constraints else ""

    return f"""You are Clara, a professional and calm AI receptionist for {company}. You handle inbound calls with warmth, efficiency, and precision.

BUSINESS HOURS: {days}, {start} – {end} {tz}
SERVICES HANDLED: {services}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DURING BUSINESS HOURS FLOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1 — GREETING
Say: "Thank you for calling {company}. This is Clara. How can I help you today?"

STEP 2 — UNDERSTAND PURPOSE
Listen carefully. Internally classify the call as one of:
- Emergency (requires immediate technician response)
- Service request (non-urgent repair or maintenance)
- Inspection scheduling
- Billing or account inquiry
- General question

STEP 3 — COLLECT CALLER INFORMATION
Ask for the caller's full name and best callback number.
Do NOT ask for more than what is needed to route the call.

STEP 4 — TRANSFER OR ROUTE
Transfer the caller to the appropriate contact immediately.
If the transfer connects: confirm the caller is connected, then end the call politely.
If the transfer does not connect within {timeout} seconds:
  Say: "{fail_msg}"

STEP 5 — CONFIRM NEXT STEPS
Clearly state what will happen next (callback window, ticket created, etc.).

STEP 6 — CLOSE
Ask: "Is there anything else I can help you with today?"
If no: "Thank you for calling {company}. Have a great day. Goodbye."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AFTER HOURS FLOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 1 — GREETING
Say: "Thank you for calling {company}. You've reached us outside of our regular business hours. I'm Clara, and I'm here to help."

STEP 2 — DETERMINE URGENCY
Ask: "Is this an emergency situation that requires immediate attention?"

STEP 3A — IF EMERGENCY (e.g. {em_text}):
Say: "I understand — let me get you connected to our emergency line right away."
Collect immediately in this order:
  1. Full name
  2. Best callback number
  3. Service address or site location
Attempt transfer to: {primary}
If transfer fails after {timeout} seconds:
  Say: "{fail_msg}"
  Assure: "Our technician has been notified and will call you back within 15 minutes."

STEP 3B — IF NON-EMERGENCY:
Say: "I understand. Our team will follow up with you during business hours."
Collect: full name, callback number, brief description of the issue.
Confirm: "Our team will reach out to you on the next business day, {days}, {start}–{end}."

STEP 4 — CLOSE
Ask: "Is there anything else I can help you with?"
If no: "Thank you for calling {company}. Take care. Goodbye."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
UNIVERSAL RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- NEVER mention function calls, tools, APIs, or backend systems to the caller.
- NEVER invent information. If unsure: "Let me make sure the right person follows up with you."
- NEVER put the caller on hold for more than 30 seconds without a status update.
- Keep responses concise and conversational. Do not over-explain.
- Always confirm the caller's name and number before attempting any transfer.
- If a caller becomes distressed, acknowledge their concern calmly before proceeding.{constraint_block}

[Agent Version: {memo.get('version', 'v1')} | Source: {memo.get('source', 'demo_call')}]"""


# ─── Retell Agent Spec Builder ────────────────────────────────────────────────
def build_agent_spec(memo: dict, version: str = "v1") -> dict:
    bh = memo.get("business_hours") or {}
    er = memo.get("emergency_routing_rules") or {}
    tr = memo.get("call_transfer_rules") or {}

    return {
        "agent_name": f"Clara – {memo.get('company_name', 'Unknown')} ({version})",
        "version": version,
        "voice_style": {
            "provider": "elevenlabs",
            "voice_id": "professional_female_calm",
            "speed": 1.0,
            "stability": 0.75
        },
        "system_prompt": generate_agent_system_prompt(memo),
        "key_variables": {
            "timezone":             bh.get("timezone", ""),
            "business_hours_start": bh.get("start", ""),
            "business_hours_end":   bh.get("end", ""),
            "business_days":        bh.get("days", []),
            "office_address":       memo.get("office_address", ""),
            "emergency_contacts":   er.get("contacts", [])
        },
        "tool_invocation_placeholders": [
            {"name": "transfer_call",        "description": "Transfer the active call to a specified phone number or extension.", "hidden_from_caller": True},
            {"name": "create_ticket",        "description": "Create a service ticket in the backend FSM system.", "hidden_from_caller": True},
            {"name": "check_business_hours", "description": "Check if current time falls within business hours.", "hidden_from_caller": True}
        ],
        "call_transfer_protocol": {
            "timeout_seconds": tr.get("timeout_seconds") or 30,
            "retries":         tr.get("retries") or 1,
            "fail_action":     "notify_and_callback",
            "fail_message":    tr.get("fail_message", "")
        },
        "fallback_protocol": {
            "action":                   "collect_callback_info",
            "message":                  "I wasn't able to connect you directly, but I've flagged this for our team and someone will reach out to you shortly.",
            "escalation_delay_minutes": 15
        },
        "generated_at":   datetime.datetime.utcnow().isoformat(),
        "generated_from": "clara_pipeline_a"
    }


# ─── OpenAI LLM Call ──────────────────────────────────────────────────────────
def call_openai(system_prompt: str, user_message: str) -> str:
    if not OPENAI_API_KEY:
        raise ValueError(
            "OPENAI_API_KEY is not set. "
            "Export it: export OPENAI_API_KEY=sk-..."
        )
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type":  "application/json"
        },
        json={
            "model":       MODEL,
            "temperature": 0,
            "max_tokens":  2000,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message}
            ]
        },
        timeout=60
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def extract_via_llm(transcript: str, system_prompt: str) -> dict:
    raw = call_openai(
        system_prompt=system_prompt,
        user_message=f"Extract structured account data from this transcript:\n\n{transcript}"
    )
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$",     "", raw)
    return json.loads(raw.strip())


# ─── Account ID Generator ─────────────────────────────────────────────────────
def generate_account_id(company_name: str) -> str:
    slug       = re.sub(r"[^a-z0-9]+", "_", company_name.lower()).strip("_")
    short_hash = hashlib.md5(company_name.encode()).hexdigest()[:6]
    return f"{slug}_{short_hash}"


# ─── Pipeline A Core ──────────────────────────────────────────────────────────
def run_pipeline_a(transcript_path: str, account_id: Optional[str] = None) -> dict:
    print(f"\n{'='*60}")
    print(f"  PIPELINE A — Demo Call → v1")
    print(f"  File: {transcript_path}")
    print(f"{'='*60}")

    transcript = Path(transcript_path).read_text(encoding="utf-8")
    if len(transcript.strip()) < 50:
        raise ValueError("Transcript appears empty or too short.")

    print("  [1/4] Extracting structured data via OpenAI gpt-4o-mini...")
    extracted = extract_via_llm(transcript, DEMO_EXTRACTION_SYSTEM_PROMPT)

    print("  [2/4] Building canonical account memo (v1)...")
    memo = dict(EMPTY_MEMO)
    memo.update(extracted)

    company_name = memo.get("company_name") or "unknown_company"
    if not account_id:
        account_id = generate_account_id(company_name)

    now = datetime.datetime.utcnow().isoformat()
    memo["account_id"] = account_id
    memo["version"]    = "v1"
    memo["source"]     = "demo_call"
    memo["created_at"] = now
    memo["updated_at"] = now

    print("  [3/4] Generating Retell agent spec v1...")
    agent_spec = build_agent_spec(memo, version="v1")

    print("  [4/4] Writing outputs to disk...")
    out_dir = OUTPUTS_DIR / account_id / "v1"
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "account_memo.json").write_text(json.dumps(memo, indent=2))
    (out_dir / "agent_spec.json").write_text(json.dumps(agent_spec, indent=2))
    (out_dir / "agent_prompt.txt").write_text(agent_spec["system_prompt"])

    unknowns = memo.get("questions_or_unknowns") or []
    print(f"\n  ✅ Pipeline A complete")
    print(f"     Account ID  : {account_id}")
    print(f"     Company     : {company_name}")
    print(f"     Unknowns    : {len(unknowns)} field(s) flagged for onboarding")
    print(f"     Output      : {out_dir}/")
    print(f"\n  ⚠️  Save this account_id — you need it to run Pipeline B:")
    print(f"     {account_id}\n")

    return {"account_id": account_id, "memo": memo, "agent_spec": agent_spec}


# ─── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python pipeline_a_demo.py <transcript.txt>")
        print("  python pipeline_a_demo.py <transcript.txt> <account_id>  # force a specific ID")
        sys.exit(1)

    run_pipeline_a(
        transcript_path=sys.argv[1],
        account_id=sys.argv[2] if len(sys.argv) > 2 else None
    )
