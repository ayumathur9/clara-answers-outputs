#!/usr/bin/env python3
"""
Pipeline B: Onboarding Call Transcript -> Updated Retell Agent (v2)
Clara Answers Automation Pipeline

Reads  : v1 memo from outputs/accounts/<account_id>/v1/
Writes : v2 memo + agent spec + changelog to outputs/accounts/<account_id>/v2/
"""

import json
import copy
import datetime
from pathlib import Path
import sys
import os

# Import shared utilities from Pipeline A
sys.path.insert(0, str(Path(__file__).parent))
from pipeline_a_demo import (
    OUTPUTS_DIR,
    ONBOARDING_EXTRACTION_SYSTEM_PROMPT,
    extract_via_llm,
    build_agent_spec,
)


# ─── Smart Merge ─────────────────────────────────────────────────────────────
def smart_merge(v1_memo: dict, onboarding_data: dict) -> dict:
    """
    Merge onboarding data into v1 memo — non-destructively.

    Rules:
    - Non-empty onboarding values always override v1 values.
    - Empty/null onboarding values do NOT clear existing v1 data.
    - Lists replaced only if onboarding provides a non-empty list.
    - account_id and created_at are immutable — never changed.
    """
    v2 = copy.deepcopy(v1_memo)

    def _merge(base: dict, update: dict):
        for key, val in update.items():
            if key in ("account_id", "created_at"):
                continue
            if isinstance(val, dict) and isinstance(base.get(key), dict):
                _merge(base[key], val)
            elif isinstance(val, list):
                if val:                   # only override if non-empty
                    base[key] = val
            elif val is not None and val != "":
                base[key] = val

    _merge(v2, onboarding_data)

    v2["version"]    = "v2"
    v2["source"]     = "onboarding_call"
    v2["updated_at"] = datetime.datetime.utcnow().isoformat()

    return v2


# ─── Deep Diff Engine ─────────────────────────────────────────────────────────
def deep_diff(v1: dict, v2: dict, path: str = "") -> list:
    """
    Compare v1 and v2 memos recursively.
    Returns a list of typed change records.
    """
    SKIP = {"version", "updated_at", "created_at", "source", "account_id"}
    changes = []

    all_keys = sorted(set(list(v1.keys()) + list(v2.keys())))
    for key in all_keys:
        if key in SKIP:
            continue

        full_path = f"{path}.{key}" if path else key
        old_val   = v1.get(key)
        new_val   = v2.get(key)

        if json.dumps(old_val, sort_keys=True) == json.dumps(new_val, sort_keys=True):
            continue

        if isinstance(old_val, dict) and isinstance(new_val, dict):
            changes.extend(deep_diff(old_val, new_val, path=full_path))

        elif isinstance(old_val, list) and isinstance(new_val, list):
            added   = [x for x in new_val if x not in old_val]
            removed = [x for x in old_val if x not in new_val]
            if added:
                changes.append({"field": full_path, "change_type": "added_items",   "added":   added})
            if removed:
                changes.append({"field": full_path, "change_type": "removed_items", "removed": removed})

        elif not old_val and old_val != 0 and old_val != False:
            # old was empty/null → now has a value
            changes.append({
                "field":       full_path,
                "change_type": "populated",
                "from":        old_val,
                "to":          new_val,
                "note":        "Previously unknown from demo — confirmed in onboarding"
            })

        else:
            changes.append({
                "field":       full_path,
                "change_type": "updated",
                "from":        old_val,
                "to":          new_val
            })

    return changes


# ─── Changelog Generators ────────────────────────────────────────────────────
def build_changelog_md(account_id: str, changes: list, v1_memo: dict, v2_memo: dict) -> str:
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    company   = v2_memo.get("company_name") or account_id

    lines = [
        f"# Changelog — {company}",
        f"",
        f"| Field         | Value                          |",
        f"|---------------|-------------------------------|",
        f"| Account ID    | `{account_id}`                |",
        f"| Generated     | {timestamp}                   |",
        f"| Transition    | v1 (demo) → v2 (onboarding)   |",
        f"| Total changes | {len(changes)}                |",
        f"",
        f"---",
        f"",
        f"## Changes",
        f"",
    ]

    if not changes:
        lines.append("_No differences detected between v1 and v2._")
        return "\n".join(lines)

    icons = {
        "populated":     "✅",
        "updated":       "🔄",
        "added_items":   "➕",
        "removed_items": "➖",
    }

    for c in changes:
        field  = c["field"]
        ctype  = c["change_type"]
        icon   = icons.get(ctype, "•")

        if ctype == "populated":
            lines += [
                f"### {icon} `{field}`",
                f"**Status:** Empty in demo → confirmed in onboarding  ",
                f"**Now:** `{c['to']}`  ",
                f"_{c.get('note', '')}_",
                "",
            ]
        elif ctype == "updated":
            lines += [
                f"### {icon} `{field}`",
                f"**Was:** `{c['from']}`  ",
                f"**Now:** `{c['to']}`",
                "",
            ]
        elif ctype == "added_items":
            items = "\n".join(f"- `{x}`" for x in c["added"])
            lines += [
                f"### {icon} `{field}` — items added",
                items,
                "",
            ]
        elif ctype == "removed_items":
            items = "\n".join(f"- `{x}`" for x in c["removed"])
            lines += [
                f"### {icon} `{field}` — items removed",
                items,
                "",
            ]

    return "\n".join(lines)


def build_changelog_json(account_id: str, changes: list) -> dict:
    return {
        "account_id":    account_id,
        "generated_at":  datetime.datetime.utcnow().isoformat(),
        "transition":    "v1->v2",
        "changes_count": len(changes),
        "changes":       changes
    }


# ─── Pipeline B Core ──────────────────────────────────────────────────────────
def run_pipeline_b(onboarding_transcript_path: str, account_id: str) -> dict:
    print(f"\n{'='*60}")
    print(f"  PIPELINE B — Onboarding → v2")
    print(f"  Account ID : {account_id}")
    print(f"  File       : {onboarding_transcript_path}")
    print(f"{'='*60}")

    # Step 1: Load v1 memo
    v1_path = OUTPUTS_DIR / account_id / "v1" / "account_memo.json"
    if not v1_path.exists():
        raise FileNotFoundError(
            f"No v1 memo found at {v1_path}.\n"
            f"Run Pipeline A first for account: {account_id}"
        )

    v1_memo = json.loads(v1_path.read_text())
    print(f"  [1/5] Loaded v1 memo — {v1_memo.get('company_name', account_id)}")

    # Step 2: Extract onboarding data
    print("  [2/5] Extracting onboarding data via OpenAI gpt-4o-mini...")
    transcript     = (Path(onboarding_transcript_path)
                      .read_text(encoding="utf-8"))
    onboarding_data = extract_via_llm(transcript, ONBOARDING_EXTRACTION_SYSTEM_PROMPT)

    # Step 3: Smart merge
    print("  [3/5] Merging v1 → v2 (non-destructive)...")
    v2_memo = smart_merge(v1_memo, onboarding_data)

    # Step 4: Diff
    print("  [4/5] Computing diff...")
    changes = deep_diff(v1_memo, v2_memo)

    # Step 5: Build outputs
    print("  [5/5] Generating agent spec v2 + changelog...")
    agent_spec_v2 = build_agent_spec(v2_memo, version="v2")
    changelog_md  = build_changelog_md(account_id, changes, v1_memo, v2_memo)
    changelog_json = build_changelog_json(account_id, changes)

    # Write
    out_dir = OUTPUTS_DIR / account_id / "v2"
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "account_memo.json").write_text(json.dumps(v2_memo,       indent=2))
    (out_dir / "agent_spec.json"  ).write_text(json.dumps(agent_spec_v2, indent=2))
    (out_dir / "agent_prompt.txt" ).write_text(agent_spec_v2["system_prompt"])
    (out_dir / "changelog.md"     ).write_text(changelog_md)
    (out_dir / "changelog.json"   ).write_text(json.dumps(changelog_json, indent=2))

    print(f"\n  ✅ Pipeline B complete")
    print(f"     Company    : {v2_memo.get('company_name', account_id)}")
    print(f"     Changes    : {len(changes)} field(s) updated")
    print(f"     Output     : {out_dir}/")
    print(f"\n  Files written:")
    for f in ["account_memo.json", "agent_spec.json", "agent_prompt.txt",
              "changelog.md", "changelog.json"]:
        print(f"     - {out_dir / f}")
    print()

    return {
        "account_id":    account_id,
        "memo_v2":       v2_memo,
        "agent_spec_v2": agent_spec_v2,
        "changes":       changes
    }


# ─── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage:")
        print("  python pipeline_b_onboarding.py <onboarding_transcript.txt> <account_id>")
        print("")
        print("Example:")
        print("  python pipeline_b_onboarding.py ../data/onboarding.txt acme_fire_a3f9b2")
        sys.exit(1)

    run_pipeline_b(
        onboarding_transcript_path=sys.argv[1],
        account_id=sys.argv[2]
    )
