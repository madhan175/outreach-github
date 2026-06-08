"""
stages/stage1_apollo.py
Stage 1 — Apollo.io  (replaces Ocean.io)
==========================================
Given a seed domain, uses Apollo's /organizations/search endpoint to find
similar companies (same industry, similar employee count).

Apollo.io docs: https://apolloio.github.io/apollo-api-docs/
Auth: api_key in request body (or X-Api-Key header).
Key endpoint: POST https://api.apollo.io/v1/organizations/search

Pipeline:
  seed domain → resolve org via Apollo → extract industry/size →
  search for similar orgs → return list of domains
"""

import logging
import time
from utils.http import post, APIError, RateLimitError

APOLLO_BASE = "https://api.apollo.io/v1"
ORG_SEARCH_ENDPOINT = f"{APOLLO_BASE}/organizations/search"
ORG_ENRICH_ENDPOINT = f"{APOLLO_BASE}/organizations/enrich"

# How many lookalike domains to return (Apollo free: 10k credits/mo)
MAX_RESULTS = 20

# Delay between paginated API calls
REQUEST_DELAY = 0.5


def find_lookalikes(
    seed_domain: str,
    config: dict,
    logger: logging.Logger,
) -> list[str]:
    """
    Use Apollo.io to find companies similar to seed_domain.

    Strategy:
      1. Enrich the seed domain → get industry, employee_count, keywords
      2. Search Apollo for orgs matching the same industry/size
      3. Return their domains (excluding the seed itself)

    Returns [] on failure.
    """
    api_key = config["APOLLO_API_KEY"]

    # ── Step 1: Enrich seed domain to get its profile ────────────────────
    logger.info("[Stage 1] Apollo: enriching seed domain '%s'", seed_domain)
    seed_org = _enrich_org(seed_domain, api_key, logger)

    if not seed_org:
        logger.warning(
            "[Stage 1] Apollo couldn't enrich '%s'. "
            "Falling back to keyword-only search.", seed_domain
        )
        industry_tags = []
        employee_range = None
    else:
        industry_tags = seed_org.get("industry", "")
        # Apollo returns employee_count as int; map to range string
        employee_range = _employee_range(seed_org.get("employee_count") or 0)
        logger.info(
            "[Stage 1] Seed profile — industry: '%s', employees: ~%s",
            industry_tags, employee_range or "unknown"
        )

    # ── Step 2: Search for lookalike companies ───────────────────────────
    domains = _search_lookalikes(
        seed_domain=seed_domain,
        industry=industry_tags,
        employee_range=employee_range,
        api_key=api_key,
        logger=logger,
    )

    logger.info("[Stage 1] Returning %d lookalike domains.", len(domains))
    return domains


# ─────────────────────────────────────────────────────────────────────────────

def _enrich_org(domain: str, api_key: str, logger: logging.Logger) -> dict | None:
    """
    Call Apollo /organizations/enrich to get full profile of a domain.
    Returns the org dict or None on failure.
    """
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": api_key,
    }
    payload = {
        "domain": domain,
    }
    try:
        data = post(ORG_ENRICH_ENDPOINT, headers, payload, context=f"Apollo/enrich/{domain}")
        return data.get("organization") or {}
    except APIError as e:
        if e.status == 401:
            logger.error("[Stage 1] Apollo: invalid API key (401). Check APOLLO_API_KEY.")
        else:
            logger.warning("[Stage 1] Apollo enrich error for %s: %s", domain, e)
        return None
    except Exception as e:
        logger.warning("[Stage 1] Apollo enrich unexpected error: %s", e)
        return None


def _search_lookalikes(
    seed_domain: str,
    industry: str | list,
    employee_range: str | None,
    api_key: str,
    logger: logging.Logger,
) -> list[str]:
    """
    Search Apollo for companies matching industry/size profile.
    Returns a deduplicated list of domains, seed excluded.
    """
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": api_key,
    }

    # Build industry filter — Apollo accepts a list of industry strings
    industries = [industry] if isinstance(industry, str) and industry else (industry or [])

    # Apollo employee_ranges format: ["1,10", "11,50", "51,200", ...]
    emp_ranges = [employee_range] if employee_range else []

    payload = {
        "page": 1,
        "per_page": MAX_RESULTS + 5,   # request extra to absorb the seed + dupes
        "organization_industry_tag_ids": [],  # optional: use if you have tag IDs
        # Text-based industry filter (works without tag IDs)
        "q_organization_keyword_tags": industries[:3] if industries else [],
        # Employee count range
        **({"organization_num_employees_ranges": emp_ranges} if emp_ranges else {}),
        # Exclude the seed itself
        "q_not_domain": seed_domain,
    }

    logger.info(
        "[Stage 1] Apollo search — industries: %s, employee_range: %s",
        industries, employee_range
    )

    try:
        data = post(ORG_SEARCH_ENDPOINT, headers, payload, context="Apollo/search")
    except APIError as e:
        if e.status == 401:
            logger.error("[Stage 1] Apollo: invalid API key (401). Check APOLLO_API_KEY.")
        elif e.status == 422:
            logger.error(
                "[Stage 1] Apollo: unprocessable search params (422). "
                "Retrying with relaxed filters…"
            )
            return _search_relaxed(seed_domain, api_key, logger)
        else:
            logger.error("[Stage 1] Apollo search error: %s", e)
        return []
    except RateLimitError as e:
        logger.error("[Stage 1] Apollo rate limit: %s", e)
        return []
    except Exception as e:
        logger.exception("[Stage 1] Unexpected Apollo error: %s", e)
        return []

    orgs = data.get("organizations") or data.get("accounts") or []
    if not orgs:
        logger.warning("[Stage 1] Apollo search returned 0 organizations.")
        return []

    domains = []
    seen = set()
    for org in orgs:
        domain = _extract_domain(org)
        if not domain or domain == seed_domain or domain in seen:
            continue
        seen.add(domain)
        domains.append(domain)
        logger.debug("[Stage 1] + %s (%s)", domain, org.get("name", ""))
        if len(domains) >= MAX_RESULTS:
            break

    return domains


def _search_relaxed(seed_domain: str, api_key: str, logger: logging.Logger) -> list[str]:
    """Fallback: search with minimal filters if the full search fails."""
    logger.info("[Stage 1] Relaxed Apollo search (no industry filter)")
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": api_key,
    }
    payload = {
        "page": 1,
        "per_page": MAX_RESULTS,
        "q_not_domain": seed_domain,
    }
    try:
        data = post(ORG_SEARCH_ENDPOINT, headers, payload, context="Apollo/relaxed")
        orgs = data.get("organizations") or []
        domains = []
        seen = set()
        for org in orgs:
            d = _extract_domain(org)
            if d and d != seed_domain and d not in seen:
                seen.add(d)
                domains.append(d)
        return domains[:MAX_RESULTS]
    except Exception as e:
        logger.warning("[Stage 1] Relaxed search also failed: %s", e)
        return []


def _extract_domain(org: dict) -> str | None:
    """Safely extract a clean domain string from an Apollo org object."""
    raw = (
        org.get("primary_domain")
        or org.get("website_url")
        or org.get("domain")
        or ""
    ).strip().lower()
    for prefix in ("https://", "http://", "www."):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
    raw = raw.split("/")[0].strip()
    return raw if "." in raw else None


def _employee_range(count: int) -> str | None:
    """Map Apollo employee_count int to Apollo range filter string."""
    if count <= 0:
        return None
    if count <= 10:
        return "1,10"
    if count <= 50:
        return "11,50"
    if count <= 200:
        return "51,200"
    if count <= 500:
        return "201,500"
    if count <= 1000:
        return "501,1000"
    if count <= 5000:
        return "1001,5000"
    return "5001,10000"
