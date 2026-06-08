"""Example: create and send a Brevo (Sendinblue) marketing campaign.

Requires `sib-api-v3-sdk` and `python-dotenv` (optional) in the active environment.

Edit `sender`, `recipients.listIds`, and `html_content` before running.
"""
import os
from dotenv import load_dotenv

from sib_api_v3_sdk import Configuration, ApiClient
from sib_api_v3_sdk.api.email_campaigns_api import EmailCampaignsApi
from sib_api_v3_sdk.models.create_email_campaign import CreateEmailCampaign
from sib_api_v3_sdk.rest import ApiException


def main():
    load_dotenv()

    api_key = os.environ.get("BREVO_API_KEY")
    if not api_key:
        raise SystemExit("Set BREVO_API_KEY in the environment or in a .env file")

    conf = Configuration()
    conf.api_key["api-key"] = api_key

    with ApiClient(conf) as api_client:
        api_instance = EmailCampaignsApi(api_client)

        campaign = CreateEmailCampaign(
            name="Campaign sent via the API",
            subject="My subject",
            sender={"name": "From name", "email": "myfromemail@mycompany.com"},
            type="classic",
            html_content="<p>Congratulations! You successfully sent this example campaign via the Brevo API.</p>",
            # Replace with your marketing list IDs from Brevo dashboard
            recipients={"listIds": [2, 7]},
            # scheduled_at=None sends immediately; otherwise use "YYYY-MM-DD HH:MM:SS"
            scheduled_at=None,
        )

        try:
            resp = api_instance.create_email_campaign(campaign)
            # Response object may include an `id` attribute for the created campaign
            print("Created campaign id:", getattr(resp, "id", resp))
        except ApiException as e:
            print("API Exception when creating campaign:\n", e)


if __name__ == "__main__":
    main()
