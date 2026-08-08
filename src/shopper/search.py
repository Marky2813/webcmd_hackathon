"""Fan out one query across every enabled site and merge the results.

Providers are blocking subprocess calls into browser-backed commands, so they
run concurrently — searching two sites serially would routinely exceed the
patience of someone waiting in a Telegram chat. A site that fails or times out
degrades to an entry in `errors` and never takes the reply down with it.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from shopper import ranking
from shopper.models import Category, Product, SearchOutcome, UserProfile
from shopper.providers.registry import ENABLED

# Bounds the whole fan-out. Individual providers have their own tighter
# subprocess timeouts; this is the backstop for the reply as a whole.
FANOUT_TIMEOUT_S = 70


def search_all(
    profile: UserProfile,
    query: str,
    category: Category,
    max_price_inr: int = 0,
    min_price_inr: int = 0,
) -> SearchOutcome:
    """Search every enabled site, then rank the combined results.

    Args:
        profile: Durable preferences, used to fill gaps and to rank.
        query: Search terms as the user phrased them.
        category: "footwear", "clothing", or "other".
        max_price_inr: Budget stated in this message, or 0 to fall back
            to the profile ceiling.
        min_price_inr: Lower bound stated in this message, or 0.

    Returns:
        The applied filters, the ranked products, which sites answered, and
        which sites failed.
    """
    params, applied = ranking.merge(
        profile, query, category, max_price_inr, min_price_inr
    )

    found: list[Product] = []
    searched: list[str] = []
    errors: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=max(len(ENABLED), 1)) as pool:
        futures = {pool.submit(provider.search, params): provider for provider in ENABLED}

        for future in as_completed(futures, timeout=FANOUT_TIMEOUT_S):
            provider = futures[future]
            try:
                results = future.result()
            except Exception as exc:  # one bad site must not sink the reply
                errors[provider.site] = f"{type(exc).__name__}: {exc}"
                continue
            found.extend(results)
            searched.append(provider.site)

    return SearchOutcome(
        applied_filters=applied,
        results=ranking.rank(found, profile, category),
        sites_searched=searched,
        errors=errors,
    )
