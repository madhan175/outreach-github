"""
stages/stage4_brevo.py
Stage 4 — Brevo
================
Sends a personalized cold outreach email to each resolved contact via
the Brevo transactional email API.

Brevo docs: https://developers.brevo.com/reference/sendtransacemail
Auth: api-key header.
Key endpoint: POST /v3/smtp/email

Design notes:
  - Each email is individually addressed (not a batch campaign) so
    personalisation tokens render correctly and replies come back to you.
  - subject, body_text, and body_html are built per-contact from
    a template function — edit _build_email() to customise your pitch.
  - Brevo free tier: 300 emails/day. The stage enforces a small delay
    to avoid hitting burst limits.
"""

import logging
import time
import textwrap
import json
import urllib.request
import socket
from typing import Optional, List

from utils.http import post, APIError, RateLimitError

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"

# Seconds between sends — keeps you well within Brevo's 40/min burst limit
SEND_DELAY = 1.5


def send_outreach(
    contacts: list[dict],
    config: dict,
    logger: logging.Logger,
    dry_run: bool = False,
) -> list[dict]:
    """
    Send one personalized email per contact.

    Returns a list of result dicts:
        {"email": str, "name": str, "status": "sent" | "failed" | "dry_run",
         "message_id": str | None, "error": str | None}
    """
    api_key = config["BREVO_API_KEY"]
    sender_email = config.get("BREVO_SENDER_EMAIL") or "you@yourdomain.com"
    sender_name = config.get("BREVO_SENDER_NAME") or "Your Name"

    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
    }

    results = []

    # Filter out contacts with no email to avoid sending to empty addresses
    contacts_with_email = [c for c in contacts if (c.get("email") or "").strip()]
    skipped = len(contacts) - len(contacts_with_email)
    if skipped:
        logger.warning(f"[Stage 4] Skipping {skipped} contacts with no email address")

    # If configured to use marketing campaigns, create one and return
    if not dry_run and config.get("BREVO_CAMPAIGN_LIST_IDS"):
        campaign_id = _maybe_create_campaign(contacts_with_email, config, logger)
        if campaign_id:
            results = []
            for c in contacts_with_email:
                results.append({
                    "email": c.get("email"),
                    "name": c.get("name"),
                    "status": "sent",
                    "message_id": campaign_id,
                    "error": None,
                })
            logger.info("[Stage 4] Campaign created and queued (id=%s). Marking %d contacts as sent.", campaign_id, len(results))
            return results

    for i, contact in enumerate(contacts_with_email):
        email = contact.get("email", "")
        name = contact.get("name", "")
        logger.info(f"[Stage 4] Sending to {name} <{email}> ({i + 1}/{len(contacts_with_email)})")

        subject, body_text, body_html = _build_email(contact, sender_name)

        if dry_run:
            _print_dry_run(contact, subject, body_text, logger)
            results.append({
                "email": email,
                "name": name,
                "status": "dry_run",
                "message_id": None,
                "error": None,
            })
            continue

        result = _send_single(
            contact=contact,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            sender_email=sender_email,
            sender_name=sender_name,
            headers=headers,
            logger=logger,
        )
        results.append(result)

        if i < len(contacts) - 1:
            time.sleep(SEND_DELAY)

    sent = sum(1 for r in results if r["status"] == "sent")
    logger.info("[Stage 4] Done. Sent: %d / %d", sent, len(contacts))
    return results


def _maybe_create_campaign(contacts: list[dict], config: dict, logger: logging.Logger) -> Optional[str]:
    """If `BREVO_CAMPAIGN_LIST_IDS` is set in config, create a marketing campaign
    targeting those list IDs and return the created campaign id. Returns None
    when not configured or on failure.
    """
    list_ids_raw = config.get("BREVO_CAMPAIGN_LIST_IDS", "")
    if not list_ids_raw:
        return None

    try:
        from sib_api_v3_sdk import Configuration, ApiClient
        from sib_api_v3_sdk.api.email_campaigns_api import EmailCampaignsApi
        from sib_api_v3_sdk.models.create_email_campaign import CreateEmailCampaign
    except Exception as e:
        logger.error("[Stage 4] Failed importing Brevo SDK: %s", e)
        return None

    try:
        api_key = config["BREVO_API_KEY"]
        conf = Configuration()
        conf.api_key["api-key"] = api_key

        # Build simple HTML content summarising recipients (personalisation via lists is possible)
        html_lines = ["<p>This campaign was created from the outreach pipeline.</p>", "<ul>"]
        for c in contacts[:50]:
            html_lines.append(f"<li>{c.get('name','')} &lt;{c.get('email','')}&gt;</li>")
        html_lines.append("</ul>")
        html_content = "\n".join(html_lines)

        sender_email = config.get("BREVO_SENDER_EMAIL") or "you@yourdomain.com"
        sender_name = config.get("BREVO_SENDER_NAME") or "Your Name"

        # Parse list IDs from comma-separated env var (keep tokens as strings
        # initially to avoid int/str mismatches when comparing to API results)
        raw_tokens = [x.strip() for x in list_ids_raw.split(",") if x.strip()]
        list_ids = raw_tokens
        logger.info("[Stage 4] DEBUG: BREVO_CAMPAIGN_LIST_IDS raw=%r -> tokens=%s", list_ids_raw, list_ids)

        # Create ApiClient early so we can validate list IDs using ContactsApi
        api_client = ApiClient(conf)

        # Validate provided list IDs exist in the Brevo account. If none
        # of the configured list IDs are valid, skip campaign creation and
        # fall back to transactional sends.
        try:
            from sib_api_v3_sdk.api.contacts_api import ContactsApi
            contacts_api = ContactsApi(api_client)
            # Prefer validating each configured list id directly using the
            # ContactsApi.get_list(listId) endpoint. This avoids missing ids
            # due to pagination or list visibility rules when calling
            # get_lists(). If the SDK doesn't expose get_list, fall back to
            # listing all lists and comparing.
            valid_list_ids = []
            for tok in list_ids:
                try:
                    lid = int(tok)
                except Exception:
                    logger.debug("[Stage 4] Skipping non-integer list id token: %r", tok)
                    continue
                try:
                    # Try to fetch the list by id. If it exists, add it.
                    resp = contacts_api.get_list(lid)
                    logger.info("[Stage 4] DEBUG: confirmed Brevo list id exists via get_list: %s -> %r", lid, getattr(resp, 'id', resp))
                    valid_list_ids.append(lid)
                except Exception as e_get:
                    # If get_list isn't available or raises (404), we'll try
                    # falling back to get_lists() once below.
                    logger.debug("[Stage 4] get_list(%s) failed: %s", lid, e_get)

            # If none validated via get_list, fall back to retrieving lists
            # and comparing (covers SDK versions without get_list).
            lists_error = None
            if not valid_list_ids:
                try:
                    lists_resp = contacts_api.get_lists()
                    available = []
                    lists_items = []
                    if hasattr(lists_resp, "lists"):
                        lists_items = getattr(lists_resp, "lists") or []
                    elif isinstance(lists_resp, dict):
                        lists_items = lists_resp.get("lists") or []
                    else:
                        lists_items = []

                    if isinstance(lists_items, (list, tuple)):
                        for l in lists_items:
                            try:
                                vid = getattr(l, "id", None) if not isinstance(l, dict) else l.get("id")
                                if vid is not None:
                                    available.append(int(vid))
                            except Exception:
                                pass
                    logger.info("[Stage 4] DEBUG: Brevo account list ids available=%s", available)
                    available_set = set(str(i) for i in available)
                    for tok in list_ids:
                        if str(tok) in available_set:
                            try:
                                valid_list_ids.append(int(tok))
                            except Exception:
                                pass
                except Exception as e_list:
                    lists_error = e_list
                    logger.debug("[Stage 4] fallback get_lists() failed: %s", e_list)

                    # If get_lists failed due to authorised-IPs blocking our caller IP,
                    # don't treat that as definitive evidence the configured ids
                    # are invalid — attempt to proceed using the configured ids
                    # (they may be valid in the Brevo account) and let the
                    # create_email_campaign call surface any definitive error.
                    err_text = str(e_list)
                    if "unrecognised IP" in err_text or "authorised_ips" in err_text or "authorised IP" in err_text:
                        logger.warning("[Stage 4] Brevo lists API blocked by authorised-IP policy: %s", err_text)
                        # Try to coerce configured tokens to ints and use them.
                        for tok in list_ids:
                            try:
                                valid_list_ids.append(int(tok))
                            except Exception:
                                logger.debug("[Stage 4] Could not convert configured list token to int: %r", tok)
            if not valid_list_ids:
                logger.error(
                    "[Stage 4] Provided BREVO_CAMPAIGN_LIST_IDS (%s) contain no valid list ids in your Brevo account.",
                    ",".join(map(str, list_ids)),
                )
                logger.error(
                    "[Stage 4] Create a marketing list in Brevo or correct the IDs. You can list available ids via the Brevo dashboard or API."
                )
                try:
                    close = getattr(api_client, "close", None)
                    if callable(close):
                        close()
                except Exception:
                    pass
                return None
            # Use only valid list ids
            list_ids = valid_list_ids
        except Exception as e:
            # If listing fails for any reason, log a warning and continue so
            # the subsequent create call produces a detailed API error.
            logger.warning("[Stage 4] Could not list Brevo contact lists: %s", e)

        # Build campaign payload and model. We also keep a plain dict copy
        # for logging / debugging so we can inspect the exact JSON sent
        # to Brevo when API calls fail with 400 errors (sender issues etc.).
        campaign_payload = {
            "name": f"Outreach campaign ({contacts[0].get('domain','') if contacts else 'run'})",
            "subject": "Outreach: quick question",
            "sender": {"name": sender_name, "email": sender_email},
            "htmlContent": html_content,
            "recipients": {"listIds": list_ids},
            "scheduledAt": None,
        }

        # Build SDK model without passing a `type` keyword (some SDK
        # versions don't expose `type` as a constructor parameter).
        campaign = CreateEmailCampaign(
            name=campaign_payload["name"],
            subject=campaign_payload["subject"],
            sender={"name": sender_name, "email": sender_email},
            html_content=html_content,
            recipients={"listIds": list_ids},
            scheduled_at=None,
        )

        # Set the campaign type attribute at runtime to avoid constructor
        # signature mismatches reported by some type-checkers.
        try:
            setattr(campaign, "type", "classic")
        except Exception:
            # If SDK model rejects attribute assignment, ignore and proceed.
            pass

        # ApiClient may not implement the context manager protocol in some
        # versions — don't use `with` to avoid __enter__/__exit__ errors.
        try:
            api_instance = EmailCampaignsApi(api_client)
            try:
                # Log the payload we intend to send (helps debug 400 errors)
                try:
                    logger.debug("[Stage 4] Campaign payload: %s", json.dumps(campaign_payload, indent=2))
                except Exception:
                    logger.debug("[Stage 4] Campaign payload (repr): %r", campaign_payload)

                resp = api_instance.create_email_campaign(campaign)
                campaign_id = getattr(resp, "id", None) or str(resp)
                logger.info("[Stage 4] Created Brevo campaign id: %s", campaign_id)
                return str(campaign_id)
            except Exception as e_create:
                # On error, log the payload + any available response body to
                # help diagnose malformed request bodies or field names.
                try:
                    logger.debug("[Stage 4] Campaign create exception; payload: %s", json.dumps(campaign_payload))
                except Exception:
                    logger.debug("[Stage 4] Campaign create exception; payload repr: %r", campaign_payload)

                # Try to extract response details from SDK exception if present
                extra = None
                try:
                    extra = getattr(e_create, 'body', None) or getattr(e_create, 'reason', None)
                except Exception:
                    extra = None
                if extra:
                    logger.debug("[Stage 4] Exception extra response: %r", extra)

                # Detect common sender-related bad-request and log clear fix.
                msg = str(e_create)
                if "Sender is invalid" in msg or "Sender is invalid / inactive" in msg or "sender is invalid" in msg.lower():
                    logger.error("[Stage 4] Brevo campaign creation failed - sender invalid or inactive: %s", msg)
                    logger.error(
                        "[Stage 4] To fix: ensure the sender identity (%s <%s>) is verified and active in Brevo."
                        " Manage senders at: https://app.brevo.com/settings/senders \n"
                        "Or open Brevo UI: Marketing → Campaigns → Sender → Manage sender and activate the address.\n"
                        "Campaign creation will be skipped and the pipeline will fall back to transactional sends.",
                        sender_name, sender_email,
                    )
                    return None
                # Otherwise re-raise so outer handler can log other errors.
                raise
        finally:
            # Close underlying client resources if available
            try:
                close = getattr(api_client, "close", None)
                if callable(close):
                    close()
            except Exception:
                pass

    except Exception as e:
        # Some Brevo accounts restrict API actions to authorised IPs. The
        # API returns a 401 with a message directing the user to
        # https://app.brevo.com/security/authorised_ips when this happens.
        err_text = str(e)
        if "authorised_ips" in err_text or "unrecognised IP" in err_text or "authorised IP" in err_text:
            logger.error(
                "[Stage 4] Brevo campaign creation blocked by authorised-IPs policy: %s",
                err_text,
            )

            pub = _detect_public_ip(logger)
            if pub:
                logger.error(
                    "[Stage 4] Detected public IP: %s — add this to Brevo: https://app.brevo.com/security/authorised_ips",
                    pub,
                )
            else:
                logger.error(
                    "[Stage 4] To fix: add your current public IP to Brevo at: https://app.brevo.com/security/authorised_ips\n"
                    "Or disable the 'Restrict API by IP' setting in your Brevo account.\n"
                    "Campaign creation will be skipped and the pipeline will fall back to sending transactional emails."
                )
            return None

        logger.exception("[Stage 4] Error creating Brevo campaign: %s", e)
        return None


def _send_single(
    contact: dict,
    subject: str,
    body_text: str,
    body_html: str,
    sender_email: str,
    sender_name: str,
    headers: dict,
    logger: logging.Logger,
) -> dict:
    email = contact.get("email", "")
    name = contact.get("name", "")

    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": email, "name": name}],
        "subject": subject,
        "textContent": body_text,
        "htmlContent": body_html,
        # Optional: track opens / clicks via Brevo dashboard
        "headers": {
            "X-Pipeline": "vocallabs-outreach",
        },
    }

    try:
        data = post(BREVO_SEND_URL, headers, payload, context=f"Brevo/{email}")
        message_id = data.get("messageId", "")
        logger.info("[Stage 4] ✓ Sent to %s (messageId: %s)", email, message_id)
        return {"email": email, "name": name, "status": "sent",
                "message_id": message_id, "error": None}

    except RateLimitError as e:
        # RateLimitError is a subclass of APIError; handle it first.
        msg = (e.message or str(e)) if hasattr(e, "message") else str(e)
        logger.warning(f"[Stage 4] Brevo rate limit for {email}: {msg}")
        return {"email": email, "name": name, "status": "failed",
                "message_id": None, "error": "rate_limit"}

    except APIError as e:
        # APIError carries `status` and `message` fields.
        status = getattr(e, "status", None)
        detail = getattr(e, "message", None) or str(e)
        short = str(detail)[:300]
        if status == 400:
            logger.warning(f"[Stage 4] Brevo rejected {email} (400 — bad address?): {short}")
        elif status == 401:
            # Could be invalid API key or authorised-IPs blocking our caller IP.
            msg = str(detail)
            if "authorised_ips" in msg or "unrecognised IP" in msg or "authorised IP" in msg:
                pub = _detect_public_ip(logger)
                if pub:
                    logger.error(
                        "[Stage 4] Brevo 401 — request coming from unrecognised IP (%s). Add it at: https://app.brevo.com/security/authorised_ips",
                        pub,
                    )
                else:
                    logger.error(
                        "[Stage 4] Brevo 401 — unrecognised IP. Add your public IP at: https://app.brevo.com/security/authorised_ips"
                    )
            else:
                logger.error("[Stage 4] Brevo: invalid API key. Check BREVO_API_KEY.")
        else:
            logger.warning(f"[Stage 4] Brevo error for {email}: {short}")
        return {"email": email, "name": name, "status": "failed",
                "message_id": None, "error": detail}
        return {"email": email, "name": name, "status": "failed",
                "message_id": None, "error": detail}

    except Exception as e:
        logger.exception("[Stage 4] Unexpected error sending to %s", email)
        return {"email": email, "name": name, "status": "failed",
                "message_id": None, "error": str(e)}


def _detect_public_ip(logger: logging.Logger) -> Optional[str]:
    """Try multiple simple services to detect public IP.

    Returns the IP as string or None on failure. Logs debug details.
    """
    services: List[str] = [
        "https://ifconfig.co/ip",
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
    ]
    for svc in services:
        try:
            with urllib.request.urlopen(svc, timeout=4) as resp:
                raw = resp.read().decode("utf-8").strip()
                if raw:
                    logger.debug("[Stage 4] Detected public IP via %s: %s", svc, raw)
                    return raw
        except Exception as e:
            logger.debug("[Stage 4] Public IP detection failed for %s: %s", svc, e)
    # Fallback: hostname resolution (may return a private IP)
    try:
        host = socket.gethostname()
        ip = socket.gethostbyname(host)
        logger.debug("[Stage 4] Hostname lookup returned IP: %s", ip)
        return ip
    except Exception as e:
        logger.debug("[Stage 4] Hostname lookup for public IP failed: %s", e)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Email copy — edit this section to customise your pitch
# ─────────────────────────────────────────────────────────────────────────────

def _build_email(contact: dict, sender_name: str) -> tuple[str, str, str]:
    """
    Build subject, plain-text body, and HTML body for one contact.
    Personalise using fields available on the contact dict:
        name, first_name, last_name, title, domain
    """
    first = contact.get("first_name") or contact.get("name", "").split()[0]
    title = contact.get("title", "")
    domain = contact.get("domain", "")
    company = domain.split(".")[0].capitalize()

    subject = f"Quick question for {company}"

    body_text = textwrap.dedent(f"""
        Hi {first},

        I came across {company} while researching companies doing interesting work
        in your space — and I wanted to reach out directly.

        I'm building an automated outreach and sales-intelligence tool that helps
        teams like yours identify and connect with the right prospects faster,
        without the manual work that usually slows things down.

        I'd love to get 15 minutes to show you what it looks like in practice — no
        deck, just a quick live demo. Would you be open to a short call this week
        or next?

        Best,
        {sender_name}

        P.S. If you're not the right person for this, I'd really appreciate a
        pointer to whoever handles sales/growth at {company}.
    """).strip()

    body_html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; font-size: 15px; color: #222; max-width: 600px; line-height: 1.6;">
      <p>Hi {first},</p>
      <p>
        I came across <strong>{company}</strong> while researching companies doing
        interesting work in your space — and I wanted to reach out directly.
      </p>
      <p>
        I'm building an automated outreach and sales-intelligence tool that helps
        teams like yours identify and connect with the right prospects faster,
        without the manual work that usually slows things down.
      </p>
      <p>
        I'd love to get 15 minutes to show you what it looks like in practice —
        no deck, just a quick live demo. Would you be open to a short call this
        week or next?
      </p>
      <p>Best,<br><strong>{sender_name}</strong></p>
      <p style="color: #888; font-size: 13px;">
        P.S. If you're not the right person for this, I'd really appreciate a
        pointer to whoever handles sales/growth at {company}.
      </p>
    </body>
    </html>
    """

    return subject, body_text, body_html


def _print_dry_run(contact: dict, subject: str, body_text: str, logger: logging.Logger):
    """Pretty-print the email that would have been sent in a dry run."""
    sep = "─" * 60
    logger.info(
        "\n%s\n[DRY RUN] To: %s <%s>\nSubject: %s\n\n%s\n%s",
        sep,
        contact.get("name", ""),
        contact.get("email", ""),
        subject,
        body_text,
        sep,
    )
