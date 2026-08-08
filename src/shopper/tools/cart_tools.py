"""Cart preparation. This module never completes a purchase.

Three things keep that true:

  1. The argv built here is a fixed list with no order-submitting flag in it.
  2. `--payment` is pinned to cash-on-delivery, so no payment instrument is
     ever selected on the user's behalf.
  3. `webcmd_client` refuses `--place-order` from any caller, so even a
     prompt-injected product title cannot reach it.

Scraped titles flow into the model's context, so the guard deliberately lives
below this layer rather than in the instruction text.
"""

from __future__ import annotations

import asyncio

from google.adk.tools import ToolContext

from shopper.webcmd_client import WebcmdError, run

_AMAZON_HOST = "amazon.in"
_CHECKOUT_TIMEOUT_S = 90


async def prepare_cart(
    product_url: str,
    size: str,
    colour: str,
    quantity: int,
    tool_context: ToolContext,
) -> dict:
    """Prepares an Amazon.in cart for the user to review. Never pays.

    This stops at the review step and hands back a link. You must tell the
    user plainly that they complete the purchase themselves — this app does
    not and cannot place the order.

    Only works for amazon.in products. For any other site, it returns the
    product link for the user to open, which is the expected outcome rather
    than a failure.

    Args:
        product_url: The full product URL from a search result.
        size: The exact size label to select, e.g. "UK 9". Empty string if the
            product has no size choice.
        colour: The exact colour label to select. Empty string if not needed.
        quantity: How many units, from 1 to 10.

    Returns:
        A dict with 'status', and on success 'title', 'item_price', 'total',
        'delivery_date' and 'handoff_url' for the user to finish checkout
        themselves. On a non-Amazon product, status is 'link_only' with the
        url to open.
    """
    url = product_url.strip()
    if not url:
        return {"status": "error", "message": "No product URL was given."}

    if _AMAZON_HOST not in url:
        return {
            "status": "link_only",
            "handoff_url": url,
            "message": (
                "Cart preparation is only wired up for Amazon.in. "
                "Open this link to buy it on the original site."
            ),
        }

    args: list[str] = [url, "--payment", "cod", "--quantity", str(max(1, min(quantity, 10)))]
    if size.strip():
        args += ["--size", size.strip()]
    if colour.strip():
        args += ["--colour", colour.strip()]

    try:
        # Offloaded for the same reason as search: a 90s browser checkout on
        # the event loop would stall every other Telegram request.
        rows = await asyncio.to_thread(
            run, "amazon-in", "checkout", *args, timeout=_CHECKOUT_TIMEOUT_S
        )
    except WebcmdError as exc:
        return {
            "status": "error",
            "message": str(exc),
            "handoff_url": url,
            "hint": "Offer the plain product link instead.",
        }

    if not rows:
        return {"status": "error", "message": "Checkout returned nothing.", "handoff_url": url}

    row = rows[0]
    return {
        "status": row.get("status", "prepared"),
        "title": row.get("title", ""),
        "size": row.get("size", ""),
        "colour": row.get("colour", ""),
        "quantity": row.get("quantity", quantity),
        "item_price": row.get("item_price", ""),
        "total": row.get("total", ""),
        "delivery_date": row.get("delivery_date", ""),
        "handoff_url": url,
        "payment_note": "Cart is ready for review. You complete the payment yourself.",
    }
