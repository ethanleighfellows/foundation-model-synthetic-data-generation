# Policy Definitions

This directory contains the markdown files representing each guardrail policy. The data generation script parses these files to enrich the synthetic prompts it generates.

### Important: Do Not Commit Sensitive Policies
We advise keeping actual, live policy definitions **private**. 

- The `.gitignore` at the root of this repository is configured to exclude `policies/*.md`. 
- **Only** `policies/template.md` and this `README.md` are allowed to be tracked in Git.

### How to Add a Policy
To generate a new dataset, create a markdown file inside this directory (e.g., `policies/fraud_detection.md`) that follows the exact structure shown in `template.md`.

You must include:
1. `Policy Title`
2. `Policy Description`
3. `Allowed Behaviors`
4. `Prohibited Behaviors`

The main Python generation script will automatically find all `.md` files in this directory and parse them section-by-section.
