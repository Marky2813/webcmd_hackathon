"""Cart preparation. This module never completes a purchase.

The guard holds on both sites for the same reasons:

  1. Every argv built here is a fixed list with no order-submitting flag.
  2. On Amazon, `--payment` is pinned to cash-on-delivery, so no payment
     instrument is ever selected on the user's behalf. Flipkart's adapter
     exposes no checkout command at all, only `cart-add`.
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
_FLIPKART_HOST = "flipkart.com"
_CHECKOUT_TIMEOUT_S = 90


async def prepare_cart(
    product_url: str,
    size: str,
    colour: str,
    tool_context: ToolContext,
) -> dict:
    """Prepares a cart for the user to review. Never pays, on any site.

    Works for Amazon.in and Flipkart. For any other site it returns the plain
    product link, which is the expected outcome rather than a failure.

    This stops at the cart and hands back a link. You must tell the user
    plainly that they complete the purchase themselves — this app does not and
    cannot place an order.

    On Flipkart the size is checked against what's actually in stock first, so
    if the size is gone you get the available list back instead of a cart.

    Args:
        product_url: The full product URL from a search result.
        size: The exact size label to add, e.g. "UK 9" on Amazon or "9" on
            Flipkart. Empty string if the product has no size choice.
        colour: The exact colour label. Amazon only; ignored elsewhere. Empty
            string if not needed.

    Returns:
        A dict with 'status' and, on success, the item details plus
        'handoff_url' for the user to finish checkout themselves. Status is
        'size_unavailable' with an 'available_sizes' list if the size is out of
        stock, or 'link_only' for a site with no cart support.
    """
    url = product_url.strip()
    if not url:
        return {"status": "error", "message": "No product URL was given."}

    if _AMAZON_HOST in url:
        return await _prepare_amazon(url, size, colour)
    if _FLIPKART_HOST in url:
        return await _prepare_flipkart(url, size)

    return {
        "status": "link_only",
        "handoff_url": url,
        "message": (
            "I can only build a cart on Amazon.in and Flipkart. "
            "Open this link to buy it on the original site."
        ),
    }


async def _prepare_amazon(url: str, size: str, colour: str) -> dict:
    args: list[str] = [url]
    if size.strip():
        args += ["--size", size.strip()]
    if colour.strip():
        args += ["--colour", colour.strip()]

    try:
        # Offloaded: a browser cart action on the event loop would stall every
        # other Telegram request.
        rows = await asyncio.to_thread(
            run, "amazon-in", "cart-add", *args, timeout=_CHECKOUT_TIMEOUT_S
        )
    except WebcmdError as exc:
        return _failed(url, exc)

    if not rows:
        return {"status": "error", "message": "Cart add returned nothing.", "handoff_url": url}

    row = rows[0]
    return {
        "status": row.get("status", "prepared"),
        "site": "amazon.in",
        "title": row.get("title", ""),
        "size": row.get("size", ""),
        "colour": row.get("colour", ""),
        "quantity": 1,
        "handoff_url": "https://www.amazon.in/gp/cart/view.html",
        "payment_note": "It's in your Amazon cart. You complete the payment yourself.",
    }


async def _prepare_flipkart(url: str, size: str) -> dict:
    wanted = size.strip()

    # Search results carry no sizes on Flipkart, so confirm against the
    # product page before adding — a failed add mid-conversation is worse
    # than telling them up front which sizes exist.
    if wanted:
        try:
            details = await asyncio.to_thread(
                run, "flipkart", "product", url, timeout=_CHECKOUT_TIMEOUT_S
            )
        except WebcmdError:
            details = []  # non-fatal; let cart-add be the judge

        if details:
            available = [s.strip() for s in str(details[0].get("sizes") or "").split(",") if s.strip()]
            if available and not _size_in(wanted, available):
                return {
                    "status": "size_unavailable",
                    "site": "flipkart",
                    "title": details[0].get("title", ""),
                    "requested_size": wanted,
                    "available_sizes": available,
                    "handoff_url": url,
                    "message": "That size isn't in stock. Offer them what is.",
                }

    args: list[str] = [url]
    if wanted:
        args += ["--size", wanted]

    try:
        rows = await asyncio.to_thread(
            run, "flipkart", "cart-add", *args, timeout=_CHECKOUT_TIMEOUT_S
        )
    except WebcmdError as exc:
        return _failed(url, exc)

    if not rows:
        return {"status": "error", "message": "Cart add returned nothing.", "handoff_url": url}

    row = rows[0]
    return {
        "status": row.get("status", "prepared"),
        "site": "flipkart",
        "title": row.get("title", ""),
        "size": row.get("size", ""),
        "quantity": 1,
        "handoff_url": "https://www.flipkart.com/viewcart",
        "payment_note": "It's in your Flipkart cart. You complete the payment yourself.",
    }


def _size_in(wanted: str, available: list[str]) -> bool:
    """Compare sizes loosely — "UK 9", "9" and "9.0" are the same shoe."""
    from shopper.ranking import _normalize_size

    target = _normalize_size(wanted)
    return any(_normalize_size(s) == target for s in available)


def _failed(url: str, exc: WebcmdError) -> dict:
    return {
        "status": "error",
        "message": str(exc),
        "handoff_url": url,
        "hint": "Offer the plain product link instead.",
    }
