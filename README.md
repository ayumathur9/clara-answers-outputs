 Overview

The pipeline processes two types of calls:

1. **Demo Call (Pipeline A)**
   Extracts initial operational assumptions from a demo conversation and creates **Version 1 configuration**.

2. **Onboarding Call (Pipeline B)**
   Extracts confirmed operational data from onboarding conversations and upgrades the configuration to **Version 2**, while generating a full change log.

The output includes:

* Structured account configuration
* AI agent prompt
* Agent specification
* Versioned changelog
* GitHub repository storage

---

 System Architecture

```
Transcript
   │
   ▼
Groq LLM Extraction
   │
   ▼
Structured JSON Data
   │
   ▼
Account Memo
   │
   ▼
Agent Prompt Generator
   │
   ▼
Versioned Output (v1 / v2)
   │
   ▼
Saved Locally + GitHub
```

---

 Features

* Automated transcript parsing
* LLM powered data extraction
* Chunked transcript processing for long calls
* Versioned configuration generation
* Automatic changelog creation
* GitHub output storage
* AI receptionist prompt generation
* Operational rule extraction

---

 Running the Pipeline

## Run Pipeline A (Demo Call → Version 1)

```
python run.py data/demo.txt
```

This will:

1. Extract operational data
2. Generate account memo
3. Create AI agent prompt
4. Save outputs locally
5. Upload outputs to GitHub

Example output:

```
Account ID: acme_plumbing_a13f9c
Company: Acme Plumbing
Unknowns: 3 flagged
```

---

# Run Pipeline B (Onboarding → Version 2)

After Pipeline A is complete, run:

```
python run.py data/onboarding.txt <account_id>
```

Example:

```
python run.py data/onboarding.txt acme_plumbing_a13f9c
```

Pipeline B will:

* Load Version 1 memo
* Extract confirmed onboarding configuration
* Merge v1 → v2
* Generate a diff changelog
* Create updated agent prompt
* Save results locally and to GitHub

---

# Output Files

## account_memo.json

Structured operational configuration for the company.

Example fields:

* company_name
* business_hours
* services_supported
* emergency_definition
* routing_rules
* integration_constraints

---

## agent_spec.json

Configuration used to deploy the Clara AI agent.

Includes:

* system prompt
* agent version
* key operational variables

---

## agent_prompt.txt

Full system prompt used by the AI receptionist.

Example capabilities:

* Call classification
* Emergency handling
* Transfer logic
* After hours routing

---

## changelog.md

Generated during Pipeline B to track changes between versions.

Example:

```
business_hours.start — Updated
Was: 8:00 AM
Now: 7:30 AM
```

---

# Versioning Model

| Version | Source          | Description                         |
| ------- | --------------- | ----------------------------------- |
| v1      | Demo Call       | Initial assumptions                 |
| v2      | Onboarding Call | Confirmed operational configuration |

Future versions may include:

* v3 – operational tuning
* v4 – production telemetry updates

---


 Example Workflow

```
1. Receive demo call transcript
2. Run Pipeline A
3. Review generated configuration
4. Receive onboarding call transcript
5. Run Pipeline B
6. Deploy Clara AI agent
```



 Future Improvements

* Web dashboard for transcript uploads
* Automatic CRM integration
* Real-time call flow testing
* Deployment API for Clara agents
* Monitoring and analytics
