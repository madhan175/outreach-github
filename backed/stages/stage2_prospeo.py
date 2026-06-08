"""
stages/stage2_prospeo.py
Stage 2 — Prospeo (contacts + emails)
=======================================
Prospeo's domain-search endpoint returns people WITH email addresses
in a single call — so this stage now does the job of the old Stage 2
(find decision-makers) AND the old Stage 3 (resolve emails).

Eazyreach is no longer used.

Prospeo docs: https://app.prospeo.io/api
Auth: X-KEY header.
Key endpoint: POST https://api.prospeo.io/domain-search

Response shape:
  {
    "error": false,
    "data": {
      "email_list": [
        {
          "first_name": "...",
          "last_name": "...",
          "full_name": "...",
          "email": { "value": "...", "cadence": "verified|guessed|..." },
          "job_title": "...",
          "seniority": "...",
          "linkedin_url": "...",
          "company": { "name": "...", "domain": "..." }
        },
        ...
      ]
    }
  }
"""

import logging
import time
from utils.http import post, APIError, RateLimitError

PROSPEO_BASE = "https://api.prospeo.io"
SEARCH_PERSON_ENDPOINT = f"{PROSPEO_BASE}/search-person"
BULK_ENRICH_ENDPOINT = f"{PROSPEO_BASE}/bulk-enrich-person"

# Seniority levels to keep
TARGET_SENIORITIES = {
    "c_level", "c-level", "cxo",
    "vp", "vice_president", "vice president",
    "director",
    "owner",
    "founder", "co-founder", "co_founder",
    "partner",
    "president",
}

# Title keywords as fallback when seniority field is absent/empty
TITLE_KEYWORDS = (
    "ceo", "cto", "coo", "cfo", "cpo", "cmo", "cso",
    "vp ", "v.p.", "vice president",
    "head of", "head,",
    "founder", "co-founder",
    "director",
    "president",
    "partner",
    "owner",
)

# Email verification statuses to accept (Prospeo-specific)
ACCEPTED_EMAIL_STATUS = {"verified", "guessed", "pattern"}

# Seconds between domain requests — set conservatively to match Prospeo limits (~1 req/sec)
REQUEST_DELAY = 1.1

# Conservative cap on how many person records we attempt to enrich in one run.
# Prospeo free plan limits: ~20 requests/min, 50/day in the user's account —
# keep this low to avoid hitting per-minute/day quotas during a single run.
ENRICH_MAX_RECORDS = 20

# How many lookalike domains to search per run (helps avoid 429s on small plans)
PROSPEO_SEARCH_MAX_DOMAINS = 5
# Absolute safety cap to prevent accidental large runs that trigger rate limits
HARD_MAX_SEARCH_DOMAINS = 5

# Search retry behaviour (for search-person)
SEARCH_MAX_ATTEMPTS = 5
SEARCH_BASE_BACKOFF = 1.0


def find_decision_makers(
    domains: list[str],
    config: dict,
    logger: logging.Logger,
) -> list[dict]:
    """
    For each domain, call Prospeo's domain-search to get C-suite / VP
    contacts WITH their verified email addresses in one shot.

    Returns a flat list of contact dicts:
        {
            "name": str,
            "first_name": str,
            "last_name": str,
            "title": str,
            "seniority": str,
            "domain": str,
            "linkedin_url": str,
            "email": str,              ← included directly by Prospeo
            "email_status": str,       ← "verified" | "guessed" | ...
        }

    Contacts without an email are dropped.
    """
    api_key = config["PROSPEO_API_KEY"]
    mock_mode = str(config.get("PROSPEO_MOCK", "")).strip().lower() in (
        "1", "true", "yes", "on"
    )

    if mock_mode:
        logger.warning(
            "[Stage 2] Prospeo mock mode enabled — returning test contacts without calling Prospeo"
        )
        return _mock_contacts(domains)

    if not api_key:
        logger.error(
            "[Stage 2] PROSPEO_API_KEY is missing and mock mode is not enabled. "
            "Set PROSPEO_MOCK=true to run with fake contacts for testing."
        )
        return []
    headers = {
        "X-KEY": api_key,
        "Content-Type": "application/json",
    }

    all_contacts = []
    seen_emails = set()       # global dedup across all domains

    # Step 1: use Search Person to find useful person_ids per domain
    persons_to_enrich: list[dict] = []
    # Respect configured cap for how many domains we probe in search-person
    try:
        cap = int(config.get("PROSPEO_SEARCH_MAX_DOMAINS") or config.get("PROSPEO_SEARCH_MAX_DOMAINS", PROSPEO_SEARCH_MAX_DOMAINS))
    except Exception:
        cap = PROSPEO_SEARCH_MAX_DOMAINS

    try:
        req_delay = float(config.get("PROSPEO_REQUEST_DELAY") or config.get("PROSPEO_REQUEST_DELAY", REQUEST_DELAY))
    except Exception:
        req_delay = REQUEST_DELAY

    # Normalize incoming domains and enforce a hard cap to avoid bursts
    def _normalize_domain_input(d: str) -> str:
        d = (d or "").strip().lower()
        if d.startswith("http://") or d.startswith("https://"):
            # strip scheme
            d = d.split("://", 1)[1]
        # remove any trailing slash
        d = d.rstrip("/")
        # strip leading www.
        if d.startswith("www."):
            d = d[4:]
        return d

    norm_domains = [_normalize_domain_input(d) for d in domains]
    domains_to_search = norm_domains[: min(cap, HARD_MAX_SEARCH_DOMAINS)]

    for i, domain in enumerate(domains_to_search):
        logger.info(
            "[Stage 2] Prospeo search-person: %s (%d/%d)",
            domain, i + 1, len(domains_to_search)
        )
        persons = _search_persons(domain, headers, logger)
        if persons:
            # keep domain association for later
            for p in persons:
                p["_origin_domain"] = domain
            persons_to_enrich.extend(persons)

        logger.info("[Stage 2] %s → %d persons found (un-enriched)", domain, len(persons))

        # Wait before the next search to avoid rate limits
        if i < len(domains_to_search) - 1:
            time.sleep(req_delay)

    if not persons_to_enrich:
        logger.info("[Stage 2] No person records found by search-person for provided domains")
        return []

    # Cap total records to attempt enriching to avoid exceeding Prospeo per-minute/day limits
    if len(persons_to_enrich) > ENRICH_MAX_RECORDS:
        logger.info("[Stage 2] Limiting enrich candidates from %d -> %d to respect rate limits", len(persons_to_enrich), ENRICH_MAX_RECORDS)
        persons_to_enrich = persons_to_enrich[:ENRICH_MAX_RECORDS]

    # Step 2: Bulk enrich persons to reveal emails (smaller batches to avoid rate limits)
    BATCH = 10
    for start in range(0, len(persons_to_enrich), BATCH):
        batch = persons_to_enrich[start : start + BATCH]
        enriched = _bulk_enrich(batch, headers, logger)

        for c in enriched:
            email = c.get("email", "")
            if not email:
                logger.debug("[Stage 2] Skipping enriched record — no email: %s", c.get("name", "?"))
                continue
            if email in seen_emails:
                logger.debug("[Stage 2] Duplicate email skipped: %s", email)
                continue
            if not _is_target_seniority(c):
                logger.debug("[Stage 2] Skipping %s — seniority '%s' not in target set", c.get("name", "?"), c.get("seniority", ""))
                continue

            seen_emails.add(email)
            all_contacts.append(c)

        # small delay between enrich batches to avoid bursts
        time.sleep(req_delay)

    logger.info(
        "[Stage 2] Total contacts with verified emails: %d", len(all_contacts)
    )
    # If no enriched contacts were found (common when rate-limited),
    # fall back to returning person records discovered by search-person
    # (they don't have emails but let the frontend show contacts).
    if not all_contacts and persons_to_enrich:
        logger.warning(
            "[Stage 2] No emails returned by bulk-enrich; returning %d person-only contacts (no email) for UI display",
            min(len(persons_to_enrich), 25),
        )
        fallback = []
        for p in persons_to_enrich[:25]:
            pp = p or {}
            fallback.append({
                "name": pp.get("full_name") or (f"{pp.get('first_name','')} {pp.get('last_name','')}").strip(),
                "first_name": pp.get("first_name", ""),
                "last_name": pp.get("last_name", ""),
                "title": pp.get("title", ""),
                "seniority": pp.get("seniority", ""),
                "domain": pp.get("_origin_domain", ""),
                "linkedin_url": pp.get("linkedin_url", ""),
                "email": "",
                "email_status": "",
                "email_confidence": 0,
            })
        return fallback

    return all_contacts


# ─────────────────────────────────────────────────────────────────────────────

def _search_persons(
    domain: str,
    headers: dict,
    logger: logging.Logger,
) -> list[dict]:
    """Search Prospeo `/search-person` for a domain and return person objects.

    Returns a list of simplified person dicts (no email) with keys:
      - person_id, first_name, last_name, full_name, title, seniority, linkedin_url
    """
    # Prospeo expects website filters in a valid URL format for some inputs
    # (e.g. LinkedIn company pages). Normalize common cases so plain
    # 'linkedin.com' doesn't get rejected as an invalid website format.
    # domain passed here should already be normalized (no scheme, no www)
    if domain.startswith("http://") or domain.startswith("https://"):
        website_value = domain
    elif "linkedin.com" in domain and not domain.startswith("http"):
        website_value = "https://" + domain
    else:
        website_value = domain

    payload = {
        "page": 1,
        "filters": {
            "company": {
                "websites": {"include": [website_value]}
            }
        }
    }
    # Retry loop to tolerate transient 429s / rate limits on search-person
    data = None
    for attempt in range(1, SEARCH_MAX_ATTEMPTS + 1):
        try:
            data = post(SEARCH_PERSON_ENDPOINT, headers, payload, context=f"Prospeo/search-person/{domain}")
            break
        except RateLimitError as e:
            # If the RateLimitError exposes a Retry-After header or attribute, respect it
            retry_after = None
            retry_after = getattr(e, "retry_after", None) or getattr(e, "retry_after_seconds", None)
            if not retry_after:
                # try to parse numeric value from message if present
                try:
                    msg = str(e)
                    # simple heuristic: find first integer in the message
                    import re
                    m = re.search(r"(\d+)", msg)
                    if m:
                        retry_after = int(m.group(1))
                except Exception:
                    retry_after = None

            if attempt == SEARCH_MAX_ATTEMPTS:
                logger.warning("[Stage 2] Prospeo search-person rate limited for %s (final): %s", domain, e)
                return []

            if retry_after:
                wait = float(retry_after)
            else:
                wait = SEARCH_BASE_BACKOFF * (2 ** (attempt - 1))
            logger.warning("[Stage 2] Prospeo search-person rate limited for %s — retrying in %.1fs (attempt %d/%d)", domain, wait, attempt, SEARCH_MAX_ATTEMPTS)
            time.sleep(wait)
            continue
        except APIError as e:
            # Handle DEPRECATED / auth / credit errors distinctly
            err_text = str(getattr(e, "message", ""))
            if e.status == 400 and "DEPRECATED" in err_text.upper():
                logger.warning("[Stage 2] Prospeo search-person deprecated for %s — skipping", domain)
                return []
            if e.status == 401:
                logger.error("[Stage 2] Prospeo: invalid API key (401). Check PROSPEO_API_KEY")
                return []
            if e.status == 402:
                logger.error("[Stage 2] Prospeo: credit limit reached (402).")
                return []
            # For other API errors, don't retry endlessly — log and bail
            logger.warning("[Stage 2] Prospeo search-person error for %s: %s", domain, e)
            return []
        except Exception as e:
            logger.exception("[Stage 2] Unexpected error for %s: %s", domain, e)
            return []

    # Make 'data' safe to access -- post() may have failed to set it leaving None
    info = data or {}
    if info.get("error", False):
        logger.warning(
            "[Stage 2] Prospeo search-person returned error for %s: %s",
            domain,
            info.get("error_code") or info.get("message"),
        )
        return []

    results = info.get("results") or []
    persons: list[dict] = []
    for item in results:
        # Be defensive: some API responses may include null/None entries.
        person = (item or {}).get("person") or {}
        persons.append({
            "person_id": person.get("person_id") or person.get("id") or "",
            "first_name": person.get("first_name", "").strip(),
            "last_name": person.get("last_name", "").strip(),
            "full_name": person.get("full_name") or f"{person.get('first_name','').strip()} {person.get('last_name','').strip()}",
            "title": person.get("current_job_title") or person.get("headline") or "",
            "seniority": (person.get("seniority") or "").strip().lower(),
            "linkedin_url": person.get("linkedin_url") or person.get("linkedin") or "",
        })

    return persons


def _bulk_enrich(person_refs: list[dict], headers: dict, logger: logging.Logger) -> list[dict]:
    """Call Prospeo `/bulk-enrich-person` for up to 50 persons and return enriched contact dicts.

    `person_refs` is a list of dicts containing at least `person_id` and optional `_origin_domain`.
    """
    if not person_refs:
        return []

    payload = {
        "only_verified_email": False,
        "enrich_mobile": False,
        "data": [],
    }
    # Use predictable identifiers so we can match responses
    for i, p in enumerate(person_refs):
        identifier = str(i + 1)
        payload["data"].append({
            "identifier": identifier,
            "person_id": p.get("person_id"),
        })

    # Retry loop for rate limits / transient errors
    data = None
    max_attempts = 5
    base_backoff = 1.0
    for attempt in range(1, max_attempts + 1):
        try:
            data = post(BULK_ENRICH_ENDPOINT, headers, payload, context="Prospeo/bulk-enrich-person")
            break
        except RateLimitError as e:
            # Rate limited: wait and retry with exponential backoff
            if attempt == max_attempts:
                logger.warning(f"[Stage 2] Prospeo bulk-enrich rate limited (final): {e}")
                return []
            wait = base_backoff * (2 ** (attempt - 1))
            logger.warning(f"[Stage 2] Prospeo bulk-enrich rate limited — retrying in {wait:.1f}s (attempt {attempt}/{max_attempts})")
            time.sleep(wait)
            continue
        except APIError as e:
            # Non-rate-limit API error — log and abort this batch
            logger.warning("[Stage 2] Prospeo bulk-enrich error: %s", e)
            return []
        except Exception as e:
            logger.exception("[Stage 2] Unexpected error during bulk enrich: %s", e)
            return []

    if data is None:
        logger.warning("[Stage 2] Prospeo bulk-enrich failed after retries")
        return []

    matched = data.get("matched") or []
    contacts: list[dict] = []
    for m in matched:
        person = m.get("person") or {}
        company = m.get("company") or {}

        # Extract email robustly
        email = ""
        efield = person.get("email") or {}
        if isinstance(efield, dict):
            email = efield.get("email") or efield.get("value") or ""
        else:
            email = str(efield or "").strip()

        # Determine email status/confidence using the already-extracted `efield` above
        email_status = ""
        if isinstance(efield, dict):
            email_status = (efield.get("status", "") or "").lower()
        else:
            email_status = ""

        email_confidence = 100 if email_status == "verified" else 75

        contact = {
            "name": person.get("full_name") or f"{person.get('first_name','')} {person.get('last_name','')}".strip(),
            "first_name": person.get("first_name", "").strip(),
            "last_name": person.get("last_name", "").strip(),
            "title": person.get("current_job_title") or person.get("headline") or "",
            "seniority": (person.get("seniority") or "").strip().lower(),
            "domain": (company.get("domain") or company.get("website") or person.get("company_website") or "").replace("https://", "").replace("http://", "").strip('/'),
            "linkedin_url": person.get("linkedin_url") or person.get("linkedin") or "",
            "email": (email or "").strip().lower(),
            "email_status": email_status,
            "email_confidence": email_confidence,
        }
        contacts.append(contact)

    return contacts


def _mock_contacts(domains: list[str]) -> list[dict]:
    """Return simple mock contacts so the pipeline can be tested without Prospeo."""
    contacts = []
    for i, domain in enumerate(domains):
        company = domain.split(".")[0].capitalize() if domain else "Company"
        contacts.append({
            "name": f"John Doe {i+1}",
            "first_name": "John",
            "last_name": "Doe",
            "title": "CEO",
            "seniority": "c_level",
            "domain": domain,
            "linkedin_url": f"https://www.linkedin.com/in/john-doe-{company.lower()}",
            "email": f"john.doe+{i+1}@{domain}",
            "email_status": "verified",
            "email_confidence": 100,
        })
    return contacts


def _normalise(person: dict, domain: str) -> dict:
    """
    Flatten a Prospeo person record into the standard contact dict used
    by the rest of the pipeline.
    """
    # Email can be a nested object {"value": "...", "cadence": "..."} or plain string
    email_field = person.get("email", "")
    if isinstance(email_field, dict):
        email_value = email_field.get("value", "").strip().lower()
        email_status = email_field.get("cadence", "").lower()
    else:
        email_value = str(email_field).strip().lower()
        email_status = "unknown"

    first = person.get("first_name", "").strip()
    last = person.get("last_name", "").strip()
    full = person.get("full_name") or f"{first} {last}".strip()

    li = person.get("linkedin_url") or person.get("linkedin") or ""
    # Ensure URL starts with https
    if li and not li.startswith("http"):
        li = "https://" + li

    title = (
        person.get("job_title")
        or person.get("position")
        or person.get("title")
        or ""
    ).strip()

    seniority = (
        person.get("seniority")
        or person.get("seniority_level")
        or ""
    ).strip().lower()

    return {
        "name": full,
        "first_name": first,
        "last_name": last,
        "title": title,
        "seniority": seniority,
        "domain": domain,
        "linkedin_url": li,
        "email": email_value,
        "email_status": email_status,
        # pass-through for downstream use
        "email_confidence": 100 if email_status == "verified" else 75,
    }


def _is_target_seniority(contact: dict) -> bool:
    """Return True if this contact is senior enough to outreach."""
    seniority = (
        contact.get("seniority", "")
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )
    if seniority in TARGET_SENIORITIES:
        return True
    # Normalise and check against set again (handles "c-level" vs "c_level" etc.)
    for target in TARGET_SENIORITIES:
        if target.replace("_", "") in seniority.replace("_", ""):
            return True
    # Fallback: check job title keywords
    title = contact.get("title", "").lower()
    return any(kw in title for kw in TITLE_KEYWORDS)
