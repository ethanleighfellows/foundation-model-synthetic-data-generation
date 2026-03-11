#!/usr/bin/env python3
"""
Synthetic data generator for LLM guardrail training.

For each policy markdown file in ./policies/, this script:
  1. Parses the policy into name, description, allowed behaviors, and prohibited behaviors.
  2. Reads the one-shot prompt template from ./original prompt.
  3. Samples a taxonomy profile (topic, instruction_type, text_features count, difficulty,
     scenario_type) from weighted distributions to ensure diverse coverage.
  4. Enriches the template with policy info + taxonomy steering directive.
  5. Calls the xAI (Grok) API to generate one synthetic prompt per request.
  6. Collects results into a CSV saved to ./output/<policy_name>.csv.
  7. Prints a distribution summary at the end for verification.

Usage:
  # Default: 500 compliant + 500 non_compliant per policy, all policies
  python generate_syndata.py

  # Custom counts
  python generate_syndata.py --compliant 50 --non_compliant 50

  # Single policy
  python generate_syndata.py --policy policies/financialfraud.md

  # Resume a partially completed run
  python generate_syndata.py --resume

  # Adjust concurrency
  python generate_syndata.py --workers 5
"""

import argparse
import csv
import json
import os
import random
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import requests

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROMPT_TEMPLATE_PATH = SCRIPT_DIR / "original prompt"
POLICIES_DIR = SCRIPT_DIR / "policies"
TAXONOMIES_DIR = SCRIPT_DIR / "taxonomies"
OUTPUT_DIR = SCRIPT_DIR / "output"

XAI_API_URL = "https://api.x.ai/v1/chat/completions"
DEFAULT_MODEL = "grok-4-1-fast-non-reasoning"

CSV_COLUMNS = [
    "row_id",
    "policy_name",
    "label",
    "difficulty",
    "scenario_type",
    "topic",
    "instruction_type",
    "text_features",
    "risk_level",
    "prompt",
    "short_rationale",
]

MAX_RETRIES = 5
RETRY_BACKOFF = 2  # seconds, doubled each retry


# ---------------------------------------------------------------------------
# TAXONOMY SAMPLER
# ---------------------------------------------------------------------------
class TaxonomySampler:
    """Samples taxonomy profiles with weighted distributions for diverse coverage."""

    def __init__(self, taxonomies_dir: Path):
        # Load taxonomy values from JSON files
        with open(taxonomies_dir / "topics.json", encoding="utf-8") as f:
            topics_data = json.load(f)
        with open(taxonomies_dir / "instruction_types.json", encoding="utf-8") as f:
            instruction_data = json.load(f)
        with open(taxonomies_dir / "text_features.json", encoding="utf-8") as f:
            features_data = json.load(f)

        self.topics = list(topics_data["topics"].keys())
        self.instruction_types = list(instruction_data["types"].keys())
        self.text_features = list(features_data["features"].keys())

        # --- Weighted distributions ---

        # Topics: domain-relevant ones get higher weight
        high_weight_topics = {
            "ITSecurity", "Finance", "Operations", "LegalCompliance",
            "CustomerSupport", "DataAnalytics", "ProjectManagement",
        }
        medium_weight_topics = {
            "ProductDevelopment", "HumanResources", "Comms",
            "ResearchDevelopment", "EducationTraining",
        }
        self.topic_weights = []
        for t in self.topics:
            if t in high_weight_topics:
                self.topic_weights.append(10)
            elif t in medium_weight_topics:
                self.topic_weights.append(6)
            else:
                self.topic_weights.append(3)

        # Instruction types: common ones get higher weight
        high_weight_instructions = {
            "general_inquiry", "code_write", "message_drafting",
            "explaining_teaching", "data_analysis", "technical_inquiry",
            "copy_drafting", "summarization",
        }
        medium_weight_instructions = {
            "ideation_decision", "project_management_generation", "compare",
            "code_review", "explain", "translation",
        }
        self.instruction_weights = []
        for it in self.instruction_types:
            if it in high_weight_instructions:
                self.instruction_weights.append(10)
            elif it in medium_weight_instructions:
                self.instruction_weights.append(5)
            else:
                self.instruction_weights.append(2)

        # Text features: common ones get higher weight in the sampling pool
        high_weight_features = {
            "plain_text", "lists", "code_python", "data_json",
            "email_elements", "quantitative_data", "code_sql",
            "steps_or_phases", "headers",
        }
        medium_weight_features = {
            "code_javascript", "code_shell", "data_csv", "data_yaml",
            "markup_html", "markdown_syntax", "table", "dates_times",
            "financial_figures", "url", "error_messages",
        }
        self.feature_weights = []
        for tf in self.text_features:
            if tf in high_weight_features:
                self.feature_weights.append(10)
            elif tf in medium_weight_features:
                self.feature_weights.append(5)
            else:
                self.feature_weights.append(2)

        # Scenario types with weights
        self.scenario_types = [
            "direct_request", "indirect_request", "roleplay", "rewrite",
            "translation", "classification", "summary", "contextual",
            "borderline", "evasive", "mixed_intent",
        ]
        self.scenario_weights = [15, 12, 6, 5, 4, 4, 5, 15, 8, 8, 8]

        # Difficulty: uniform
        self.difficulties = ["easy", "medium", "hard"]
        self.difficulty_weights = [1, 1, 1]

        # Text feature count distribution (max 3):
        # ~35% → 1 (plain_text only), ~40% → 2, ~25% → 3
        self._feature_count_buckets = [1, 2, 3]
        self._feature_count_weights = [35, 40, 25]

        # Tracking counters for rebalancing
        self._topic_counts = Counter()
        self._instruction_counts = Counter()
        self._total_sampled = 0

    def _rebalanced_weights(self, items, base_weights, counts, total):
        """Adjust weights to under-sample over-represented items."""
        if total < 20:
            return base_weights

        expected_share = {item: w / sum(base_weights) for item, w in zip(items, base_weights)}
        adjusted = []
        for item, w in zip(items, base_weights):
            actual_share = counts.get(item, 0) / max(total, 1)
            exp = expected_share[item]
            # If over-represented, reduce weight; if under, boost it
            ratio = max(0.2, min(3.0, exp / max(actual_share, 0.001)))
            adjusted.append(w * ratio)
        return adjusted

    def sample(self) -> dict:
        """Sample a taxonomy profile for one prompt."""
        self._total_sampled += 1

        # Topic (rebalanced)
        tw = self._rebalanced_weights(
            self.topics, self.topic_weights, self._topic_counts, self._total_sampled
        )
        topic = random.choices(self.topics, weights=tw, k=1)[0]
        self._topic_counts[topic] += 1

        # Instruction type (rebalanced)
        iw = self._rebalanced_weights(
            self.instruction_types, self.instruction_weights,
            self._instruction_counts, self._total_sampled
        )
        instruction_type = random.choices(self.instruction_types, weights=iw, k=1)[0]
        self._instruction_counts[instruction_type] += 1

        # Difficulty
        difficulty = random.choices(self.difficulties, weights=self.difficulty_weights, k=1)[0]

        # Scenario type
        scenario_type = random.choices(self.scenario_types, weights=self.scenario_weights, k=1)[0]

        # Text feature count
        feature_count = random.choices(self._feature_count_buckets, weights=self._feature_count_weights, k=1)[0]

        # Sample text features
        if feature_count == 1:
            text_features_hint = ["plain_text"]
        else:
            # Always include plain_text as one, then sample the rest
            pool = [f for f in self.text_features if f != "plain_text"]
            pool_weights = [w for f, w in zip(self.text_features, self.feature_weights) if f != "plain_text"]
            extras = min(feature_count - 1, len(pool))
            sampled_extras = []
            remaining_pool = list(zip(pool, pool_weights))
            for _ in range(extras):
                if not remaining_pool:
                    break
                items, weights = zip(*remaining_pool)
                chosen = random.choices(items, weights=weights, k=1)[0]
                sampled_extras.append(chosen)
                remaining_pool = [(i, w) for i, w in remaining_pool if i != chosen]
            text_features_hint = ["plain_text"] + sampled_extras

        return {
            "topic": topic,
            "instruction_type": instruction_type,
            "difficulty": difficulty,
            "scenario_type": scenario_type,
            "text_features_count": feature_count,
            "text_features_hint": text_features_hint,
        }


# ---------------------------------------------------------------------------
# POLICY PARSER
# ---------------------------------------------------------------------------
def parse_policy_md(filepath: Path) -> dict:
    """Parse a policy markdown file into structured sections."""
    text = filepath.read_text(encoding="utf-8")
    lines = text.strip().splitlines()

    policy_name = ""
    skip_headers = {"policy information", "policy title", "behavior"}

    # Extract policy title
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower() in skip_headers:
            continue
        if stripped and not policy_name:
            if i > 0 and lines[i - 1].strip().lower() == "policy title":
                policy_name = stripped
                continue
            if "(" in stripped and "V" in stripped:
                policy_name = stripped
                continue

    if not policy_name:
        for line in lines[:10]:
            s = line.strip()
            if s and s.lower() not in skip_headers and len(s) > 5:
                policy_name = s
                break

    # Split into sections
    current_section = None
    section_lines = {"description": [], "allowed": [], "prohibited": []}

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()
        if lower == "policy description":
            current_section = "description"
            continue
        elif lower in ("allowed behaviors", "allowed behaviour"):
            current_section = "allowed"
            continue
        elif lower in ("prohibited behaviors", "prohibited behaviour"):
            current_section = "prohibited"
            continue
        elif lower == "behavior":
            continue
        if current_section and stripped:
            section_lines[current_section].append(stripped)

    policy_description = " ".join(section_lines["description"])

    def clean_behavior_lines(raw_lines):
        behaviors = []
        current = []
        for ln in raw_lines:
            if re.match(r"^\d+$", ln):
                if current:
                    behaviors.append(" ".join(current))
                    current = []
                continue
            current.append(ln)
        if current:
            behaviors.append(" ".join(current))
        return behaviors

    return {
        "name": policy_name,
        "description": policy_description,
        "allowed": clean_behavior_lines(section_lines["allowed"]),
        "prohibited": clean_behavior_lines(section_lines["prohibited"]),
    }


# ---------------------------------------------------------------------------
# PROMPT BUILDER
# ---------------------------------------------------------------------------
def build_prompt(template: str, policy: dict, label: str, profile: dict) -> str:
    """Fill the prompt template with policy info and taxonomy steering directive."""
    allowed_text = "\n".join(f"- {b}" for b in policy["allowed"])
    prohibited_text = "\n".join(f"- {b}" for b in policy["prohibited"])

    # Collect example prompts from behaviors
    examples = []
    for b in policy["allowed"] + policy["prohibited"]:
        match = re.search(r'example:\s*["\u201c](.+?)["\u201d]', b, re.IGNORECASE)
        if match:
            examples.append(match.group(1))
    examples_text = "\n".join(f"- {e}" for e in examples[:20]) if examples else "(see behaviors above)"

    filled = template.replace("{{POLICY_NAME}}", policy["name"])
    filled = filled.replace("{{POLICY_DESCRIPTION}}", policy["description"])
    filled = filled.replace("{{ALLOWED_BEHAVIORS}}", allowed_text)
    filled = filled.replace("{{DISALLOWED_BEHAVIORS}}", prohibited_text)
    filled = filled.replace("{{EXAMPLE_PROMPTS}}", examples_text)

    # Taxonomy steering directive
    features_str = ", ".join(profile["text_features_hint"])
    directive = f"""

GENERATION CONSTRAINTS (follow these exactly):
- label: "{label}"
- topic: "{profile['topic']}"
- instruction_type: "{profile['instruction_type']}"
- difficulty: "{profile['difficulty']}"
- scenario_type: "{profile['scenario_type']}"
- text_features: use approximately {profile['text_features_count']} text feature(s) in the prompt. Suggested: [{features_str}]. Do NOT over-tag — if the target is 1–2, keep it simple. If 3+, incorporate naturally.
- risk_level: {"'none'" if label == 'compliant' else "choose 'low', 'medium', or 'high' based on the prompt's actual harm potential"}

Follow these constraints precisely. The prompt content must naturally embody the topic and instruction_type specified."""

    filled += directive
    return filled


# ---------------------------------------------------------------------------
# API CALLER
# ---------------------------------------------------------------------------
def call_xai(api_key: str, model: str, system_prompt: str) -> dict | None:
    """Call the xAI API and return the parsed JSON response, or None on failure."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Generate one synthetic prompt now. Respond with only the JSON object."},
        ],
        "temperature": 1.0,
        "max_tokens": 4096,
    }

    content = ""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(XAI_API_URL, headers=headers, json=payload, timeout=120)

            if resp.status_code == 429:
                wait = RETRY_BACKOFF * (2 ** (attempt - 1))
                print(f"    Rate limited. Waiting {wait}s before retry {attempt}/{MAX_RETRIES}...")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()

            # Strip markdown fences if the model wraps its response
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*\n?", "", content)
                content = re.sub(r"\n?```\s*$", "", content)

            return json.loads(content)

        except requests.exceptions.Timeout:
            wait = RETRY_BACKOFF * (2 ** (attempt - 1))
            print(f"    Timeout. Waiting {wait}s before retry {attempt}/{MAX_RETRIES}...")
            time.sleep(wait)
        except requests.exceptions.RequestException as e:
            wait = RETRY_BACKOFF * (2 ** (attempt - 1))
            print(f"    Request error: {e}. Waiting {wait}s before retry {attempt}/{MAX_RETRIES}...")
            time.sleep(wait)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            print(f"    Parse error: {e}. Raw: {content[:200]}")
            wait = RETRY_BACKOFF * (2 ** (attempt - 1))
            time.sleep(wait)

    print("    FAILED after all retries.")
    return None


# ---------------------------------------------------------------------------
# RESUME SUPPORT
# ---------------------------------------------------------------------------
def load_existing_csv(output_path: Path) -> list[dict]:
    """Load existing rows from a partial CSV for resume support."""
    if not output_path.exists():
        return []
    rows = []
    with open(output_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def append_row_to_csv(output_path: Path, row: dict, write_header: bool = False):
    """Append a single row to the CSV (thread-safe via file append mode)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if write_header else "a"
    with open(output_path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerow(row)


# ---------------------------------------------------------------------------
# DISTRIBUTION SUMMARY
# ---------------------------------------------------------------------------
def print_distribution_summary(csv_path: Path):
    """Print a distribution summary for a completed CSV."""
    rows = load_existing_csv(csv_path)
    if not rows:
        print("  No data to summarize.")
        return

    n = len(rows)
    print(f"\n  📊 Distribution Summary for {csv_path.name} ({n} rows)")
    print(f"  {'─' * 55}")

    # Label
    labels = Counter(r["label"] for r in rows)
    print(f"  Labels: {dict(labels)}")

    # Difficulty
    diffs = Counter(r["difficulty"] for r in rows)
    print(f"  Difficulty: {dict(diffs)}")

    # Topic (top 10)
    topics = Counter(r["topic"] for r in rows)
    print(f"  Topics (top 10):")
    for t, c in topics.most_common(10):
        bar = "█" * int(c / n * 50)
        print(f"    {t:30s} {c:4d} ({c/n*100:5.1f}%) {bar}")

    # Instruction type (top 10)
    instr = Counter(r["instruction_type"] for r in rows)
    print(f"  Instruction types (top 10):")
    for t, c in instr.most_common(10):
        bar = "█" * int(c / n * 50)
        print(f"    {t:30s} {c:4d} ({c/n*100:5.1f}%) {bar}")

    # Text features avg count
    feat_counts = []
    for r in rows:
        tf = r.get("text_features", "")
        if tf:
            feat_counts.append(len(tf.split("; ")))
        else:
            feat_counts.append(0)
    avg_feat = sum(feat_counts) / len(feat_counts) if feat_counts else 0
    plain_only = sum(1 for r in rows if r.get("text_features", "").strip() == "plain_text")
    print(f"  Text features: avg {avg_feat:.1f} per prompt, {plain_only} plain_text-only ({plain_only/n*100:.1f}%)")

    # Scenario type
    scenarios = Counter(r["scenario_type"] for r in rows)
    print(f"  Scenario types: {dict(scenarios)}")

    # Risk level
    risks = Counter(r["risk_level"] for r in rows)
    print(f"  Risk levels: {dict(risks)}")
    print()


# ---------------------------------------------------------------------------
# WORKER FUNCTION
# ---------------------------------------------------------------------------
def generate_one(
    idx: int,
    total: int,
    label: str,
    template: str,
    policy: dict,
    sampler: TaxonomySampler,
    api_key: str,
    model: str,
    policy_name: str,
    output_path: Path,
    csv_lock: Lock,
) -> dict | None:
    """Generate a single prompt — designed to run in a thread."""
    profile = sampler.sample()
    prompt = build_prompt(template, policy, label, profile)
    result = call_xai(api_key, model, prompt)

    if result is None:
        print(f"  [{idx}/{total}] {label} — SKIPPED (API failure)")
        return None

    # Normalize text_features to semicolon-separated string
    text_features = result.get("text_features", [])
    if isinstance(text_features, list):
        text_features = "; ".join(text_features)

    row = {
        "row_id": idx,
        "policy_name": policy_name,
        "label": result.get("label", label),
        "difficulty": result.get("difficulty", ""),
        "scenario_type": result.get("scenario_type", ""),
        "topic": result.get("topic", ""),
        "instruction_type": result.get("instruction_type", ""),
        "text_features": text_features,
        "risk_level": result.get("risk_level", ""),
        "prompt": result.get("prompt", ""),
        "short_rationale": result.get("short_rationale", ""),
    }

    # Thread-safe CSV append
    with csv_lock:
        append_row_to_csv(output_path, row)

    topic_short = result.get("topic", "?")
    instr_short = result.get("instruction_type", "?")
    feat_count = len(result.get("text_features", []))
    print(f"  [{idx}/{total}] {label} — {topic_short}/{instr_short} (features: {feat_count})")

    return row


# ---------------------------------------------------------------------------
# MAIN GENERATION
# ---------------------------------------------------------------------------
def generate_for_policy(
    policy_path: Path,
    template: str,
    api_key: str,
    model: str,
    n_compliant: int,
    n_non_compliant: int,
    workers: int,
    resume: bool,
):
    """Generate synthetic data for a single policy and save to CSV."""
    policy = parse_policy_md(policy_path)
    policy_slug = policy_path.stem
    output_path = OUTPUT_DIR / f"{policy_slug}.csv"
    total = n_compliant + n_non_compliant

    print(f"\n{'=' * 60}")
    print(f"POLICY: {policy['name']}")
    print(f"FILE:   {policy_path.name}")
    print(f"TARGET: {n_compliant} compliant + {n_non_compliant} non_compliant = {total}")
    print(f"OUTPUT: {output_path}")
    print(f"{'=' * 60}")

    # Resume support
    start_idx = 1
    if resume:
        existing = load_existing_csv(output_path)
        if existing:
            start_idx = len(existing) + 1
            # Count existing labels
            existing_compliant = sum(1 for r in existing if r.get("label") == "compliant")
            existing_non_compliant = sum(1 for r in existing if r.get("label") == "non_compliant")
            n_compliant = max(0, n_compliant - existing_compliant)
            n_non_compliant = max(0, n_non_compliant - existing_non_compliant)
            print(f"  RESUMING from row {start_idx} ({len(existing)} existing)")
            print(f"  Remaining: {n_compliant} compliant + {n_non_compliant} non_compliant")
            if n_compliant + n_non_compliant == 0:
                print(f"  ✅ Already complete!")
                print_distribution_summary(output_path)
                return
    else:
        # Fresh start — write CSV header
        output_path.parent.mkdir(parents=True, exist_ok=True)
        append_row_to_csv(output_path, {}, write_header=True)

    # Build generation schedule: alternate labels
    schedule = []
    c, nc = n_compliant, n_non_compliant
    while c > 0 or nc > 0:
        if c > 0:
            schedule.append("compliant")
            c -= 1
        if nc > 0:
            schedule.append("non_compliant")
            nc -= 1

    sampler = TaxonomySampler(TAXONOMIES_DIR)
    csv_lock = Lock()
    remaining = len(schedule)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for i, label in enumerate(schedule):
            idx = start_idx + i
            future = executor.submit(
                generate_one,
                idx, total, label, template, policy, sampler,
                api_key, model, policy["name"], output_path, csv_lock,
            )
            futures[future] = idx
            # Small stagger to avoid burst rate limits
            time.sleep(0.15)

        completed = 0
        for future in as_completed(futures):
            completed += 1
            try:
                future.result()
            except Exception as e:
                print(f"  ERROR in row {futures[future]}: {e}")

    print(f"\n  ✅ Completed {policy_slug}: {output_path}")
    print_distribution_summary(output_path)


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic guardrail training data via xAI API.")
    parser.add_argument("--compliant", type=int, default=500, help="Number of compliant prompts per policy (default: 500)")
    parser.add_argument("--non_compliant", type=int, default=500, help="Number of non-compliant prompts per policy (default: 500)")
    parser.add_argument("--policy", type=str, default=None, help="Path to a single policy .md file (default: all in ./policies/)")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help=f"xAI model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--workers", type=int, default=4, help="Number of concurrent workers (default: 4)")
    parser.add_argument("--resume", action="store_true", help="Resume from existing partial CSVs")
    args = parser.parse_args()

    # --- Load API key ---
    api_key = os.environ.get("XAI_API_KEY", "")
    if not api_key:
        env_path = SCRIPT_DIR / "grok.env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("export XAI_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not api_key:
        print("ERROR: XAI_API_KEY not found. Set it via environment or grok.env.", file=sys.stderr)
        sys.exit(1)

    # --- Load prompt template ---
    if not PROMPT_TEMPLATE_PATH.exists():
        print(f"ERROR: Prompt template not found at {PROMPT_TEMPLATE_PATH}", file=sys.stderr)
        sys.exit(1)
    template = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")

    # --- Determine policies ---
    if args.policy:
        policy_files = [Path(args.policy)]
    else:
        policy_files = sorted(POLICIES_DIR.glob("*.md"))

    if not policy_files:
        print("ERROR: No policy files found.", file=sys.stderr)
        sys.exit(1)

    total_prompts = len(policy_files) * (args.compliant + args.non_compliant)
    print(f"Model: {args.model}")
    print(f"Workers: {args.workers}")
    print(f"Policies: {len(policy_files)}")
    print(f"Per policy: {args.compliant} compliant + {args.non_compliant} non_compliant = {args.compliant + args.non_compliant}")
    print(f"Grand total: {total_prompts} prompts")
    if args.resume:
        print("Resume mode: ON")

    # --- Generate sequentially per policy (concurrent within each) ---
    for pf in policy_files:
        generate_for_policy(
            pf, template, api_key, args.model,
            args.compliant, args.non_compliant,
            args.workers, args.resume,
        )

    print(f"\n{'=' * 60}")
    print("DONE. All CSVs saved to ./output/")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
