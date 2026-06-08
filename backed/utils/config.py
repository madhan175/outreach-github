"""
utils/config.py
Loads API keys from environment / .env file.
Updated: Ocean.io → Apollo.io; Eazyreach removed.
"""

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass


REQUIRED_KEYS = {
    "APOLLO_API_KEY":   "Apollo.io  → Settings → Integrations → API",
    "PROSPEO_API_KEY":  "Prospeo    → app.prospeo.io/api → API Key",
    "BREVO_API_KEY":    "Brevo      → Settings → API keys → Create a key",
}

OPTIONAL_KEYS = {
    "BREVO_SENDER_EMAIL": "your-name@yourdomain.com",
    "BREVO_SENDER_NAME":  "Your Name",
    "PROSPEO_MOCK":       "true|false — enable mock Prospeo contacts for testing",
    "PROSPEO_SEARCH_MAX_DOMAINS": "2  # limit domains searched per run to avoid rate limits",
    "ENRICH_MAX_RECORDS": "5 # cap how many person records to attempt enriching",
    "PROSPEO_REQUEST_DELAY": "1.5 # seconds between Prospeo requests (search/enrich)",
    "BREVO_CAMPAIGN_LIST_IDS": "comma-separated marketing list IDs to target when creating campaigns",
}


def load_config() -> dict:
    config = {}
    for key in {**REQUIRED_KEYS, **OPTIONAL_KEYS}:
        config[key] = os.getenv(key, "")
    return config


def validate_config(config: dict) -> None:
    missing = [k for k in REQUIRED_KEYS if not config.get(k)]
    if not missing:
        return
    lines = ["", "  Missing API keys — add them to your .env file:", ""]
    for k in missing:
        lines.append(f"  {k}=<your-key>")
        lines.append(f"    # Get it from: {REQUIRED_KEYS[k]}")
        lines.append("")
    lines.append("  Create a .env file in the project root, or export the vars in your shell.")
    print("\n".join(lines), file=sys.stderr)
    sys.exit(1)
