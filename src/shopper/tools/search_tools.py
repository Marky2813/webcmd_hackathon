"""The search tool.

Note there is no parameter here that could persist anything. The tool reads
the profile and never writes it, so a constraint from one message physically
cannot survive into the next search.
"""

from __future__ import annotations

import asyncio

from google.adk.tools import ToolContext

from shopper.models import Category
from shopper.search import search_all
from shopper.tools._state import load_profile

_VALID_CATEGORIES = ("footwear", "clothing", "other")


async def search_products(
    query: str,
    category: str,
    max_price_inr: int,
    min_price_inr: int,
    tool_context: ToolContext,
) -> dict:
    """Searches every connected shopping site and returns personalized results.

    This tool merges the user's stored profile with the constraints in their
    current message by itself. Pass ONLY what the user asked for in this
    message. In particular, never pass their saved budget as max_price_inr —
    leave it 0 and the tool applies the saved ceiling for you.

    Args:
        query: The product search terms as the user described them, e.g.
            "running shoes". Do not add their size or preferred brands to the
            query; those are applied as filters automatically.
        category: One of "footwear", "clothing", or "other". This decides
            whether shoe size or clothing size is used to judge fit.
        max_price_inr: An upper price limit in rupees stated in THIS message.
            Pass 0 if the user did not state one.
        min_price_inr: A lower price limit in rupees stated in THIS message.
            Pass 0 if the user did not state one.

    Returns:
        A dict with:
          'applied_filters': the filters actually used, each tagged with an
              origin of "profile" or "request". You MUST tell the user which
              filters were applied so the personalization is visible.
          'results': the ranked products, each with site, title, brand,
              price_inr, mrp_inr, discount_pct, rating, sizes and url.
          'sites_searched': the sites that answered.
          'errors': sites that failed, keyed by site. Mention these briefly
              rather than silently returning a shorter list.
    """
    profile = load_profile(tool_context)

    normalized: Category = (
        category if category in _VALID_CATEGORIES else "other"
    )  # type: ignore[assignment]

    # ADK runs sync tools straight on the event loop, and this drives three
    # browser subprocesses for ~13s. Left inline it freezes the loop, which
    # stalls the typing indicator and times out every Telegram request.
    outcome = await asyncio.to_thread(
        search_all,
        profile=profile,
        query=query,
        category=normalized,
        max_price_inr=max(0, max_price_inr),
        min_price_inr=max(0, min_price_inr),
    )

    return {
        "applied_filters": [f.model_dump() for f in outcome.applied_filters],
        "results": [
            {**p.model_dump(), "discount_pct": p.discount_pct} for p in outcome.results
        ],
        "sites_searched": outcome.sites_searched,
        "errors": outcome.errors,
    }
