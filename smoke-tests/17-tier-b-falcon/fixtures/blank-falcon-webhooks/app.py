"""
Payment Webhook Receiver — Falcon REST Framework

No observability. Run `Observe this project.` to add it.

Receives incoming Stripe webhook events (charge.succeeded,
payment_intent.payment_failed, charge.dispute.created) and routes them
to the appropriate business handlers.
"""

import os
import logging
import wsgiref.simple_server

import falcon

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HealthResource:
    def on_get(self, req, resp):
        resp.media = {"status": "ok"}
        resp.status = falcon.HTTP_200


class WebhookResource:
    """
    POST /webhooks/stripe

    Body (JSON — Stripe event envelope):
        type     (str)  — event type, e.g. 'charge.succeeded'
        livemode (bool) — True for production events
        data.object     — event-specific payload

    Responses:
        200 — event received and processed
    """

    def on_post(self, req, resp):
        event      = req.media
        event_type = event.get("type")
        livemode   = event.get("livemode", False)
        event_data = event.get("data", {}).get("object", {})
        amount_usd = event_data.get("amount", 0) / 100

        if event_type == "charge.succeeded":
            logger.info(
                "charge.succeeded webhook processed",
                extra={"event_type": event_type,
                       "payment_amount_usd": amount_usd,
                       "customer_id": event_data.get("customer"),
                       "charge_id": event_data.get("id"),
                       "livemode": livemode},
            )

        elif event_type == "payment_intent.payment_failed":
            failure_code = (
                event_data.get("last_payment_error", {}).get("code", "unknown")
            )
            logger.warning(
                "payment failed webhook",
                extra={"event_type": event_type,
                       "payment_amount_usd": amount_usd,
                       "payment_failure_code": failure_code,
                       "livemode": livemode},
            )

        elif event_type == "charge.dispute.created":
            logger.error(
                "dispute opened",
                extra={"event_type": event_type,
                       "payment_amount_usd": amount_usd,
                       "dispute_reason": event_data.get("reason"),
                       "dispute_id": event_data.get("id"),
                       "livemode": livemode},
            )

        resp.status = falcon.HTTP_200
        resp.media  = {"received": True}


def create_app():
    application = falcon.App()
    application.add_route("/health", HealthResource())
    application.add_route("/webhooks/stripe", WebhookResource())
    return application


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    with wsgiref.simple_server.make_server("0.0.0.0", port, app) as httpd:
        logger.info(f"Webhook receiver listening on port {port}")
        httpd.serve_forever()
