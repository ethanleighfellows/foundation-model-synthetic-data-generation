# Foundation Model Synthetic Data Generation

This repository provides an automated pipeline for generating high-quality, diverse, and policy-specific synthetic data (user prompts) for training LLM guardrails. 

It leverages the **xAI API (`grok-4.1-fast-non-reasoning`)** to generate datasets that are neatly balanced across a robust taxonomy of topics, instruction types, text features, and scenarios.

## Features

- **Automated Taxonomy Distribution**: ensures the generated prompts don't collapse into generic filler. The script actively samples and rebalances across:
  - 17 Topics (e.g., ITSecurity, Finance, ProjectManagement)
  - 18 Instruction Types (e.g., code_write, general_inquiry, data_analysis)
  - Variable Text Feature counts (35% plain text, 40% 2-features, 25% 3-features)
  - 11 Scenario Types & 3 Difficulties
- **Threaded Concurrency**: Generates data rapidly using parallel workers.
- **Robustness**: Automatically handles rate limits, timeouts, and JSON parsing errors with exponential backoff.
- **Resume Support**: If a run is interrupted, you can resume exactly where you left off.
- **Drop-in Policy Support**: Define allowed/prohibited behaviors in simple Markdown files, and the script handles the rest.

---

## Getting Started

### 1. Prerequisites
- Python 3.9+ 
- An active xAI API key

### 2. Installation
Clone the repository and install the dependencies:
```bash
git clone https://github.com/ethanleighfellows/foundation-model-synthetic-data-generation.git
cd foundation-model-synthetic-data-generation
pip install -r requirements.txt
```

### 3. Setup API Key
You can pass the xAI API key in securely via environment variables or a `.env` file (preferred).

Create a file named `grok.env` in the root directory:
```bash
export XAI_API_KEY="your_api_key_here"
```
*Note: `grok.env` is ignored by git to protect your credentials.*

---

## How to use

### Defining Policies
The script looks inside the `policies/` directory for Markdown files `.md`. For each file, it generates a matched dataset of `compliant` and `non_compliant` prompts.

1. **Create a Markdown file** in `policies/` (e.g., `my_policy.md`).
2. **Follow the required structure**:
   - `Policy Title` / `Policy Description`
   - `Allowed Behaviors`
   - `Prohibited Behaviors`
   
A template is provided in `policies/template.md`. *See [policies/README.md](policies/README.md) for full instructions.*

### Running Generation
Run the script to start generating synthetic data for all policies in the `policies/` directory.

```bash
# Default (500 compliant + 500 non-compliant per policy)
python generate_syndata.py

# Specify exact counts per policy
python generate_syndata.py --compliant 100 --non_compliant 100

# Target a single policy file only
python generate_syndata.py --policy policies/financialfraud.md

# Resume a previous/interrupted run 
python generate_syndata.py --resume

# Adjust the number of concurrent generation threads (default: 4)
python generate_syndata.py --workers 8
```

### Output
When the script finishes (or is interrupted), you will find the generated datasets in the `output/` directory as CSV files, named identically to the policy file (e.g., `output/financialfraud.csv`).

The CSV includes the following metadata for every generated prompt:
- `row_id`
- `policy_name`
- `label` (compliant / non_compliant)
- `difficulty`
- `scenario_type`
- `topic`
- `instruction_type`
- `text_features`
- `risk_level`
- `prompt` (The actual generated synthetic prompt)
- `short_rationale`

---

## Repository Structure
```text
.
├── generate_syndata.py   # Main generation script
├── original prompt       # Core system prompt template
├── requirements.txt      # Python dependencies
├── grok.env              # (Local only) Your xAI API Key
├── taxonomies/           # JSON files defining topics, instructions, features
├── policies/             # Place your Markdown policy definitions here
│   ├── README.md         
│   └── template.md       # Example template structure
└── output/               # (Local only) Generated CSV datasets
```
