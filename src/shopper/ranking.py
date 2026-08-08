"""Merge the stored profile with this message's constraints, then rank.

Two rules define the whole module:

  * An explicit constraint in the current message always beats the profile.
  * The profile only ever fills a gap the message left open.

The merge also records where each applied filter came from, so the agent can
tell the user what it did rather than leaving personalization invisible.
"""

from __future__ import annotations

import math

from shopper import quality
from shopper.models import AppliedFilter, Category, Product, SearchParams, UserProfile

# Sponsored listings dominate Amazon's first page, and the cheapest of them are
# usually junk. Over-fetch well past what we show, then rank down to the best.
OVERFETCH_LIMIT = 20
RESULT_LIMIT = 5

# Deliberately low. This exists to drop listings with no feedback at all, not
# to rank by popularity — a high floor cut well-rated products from real
# brands on Myntra while leaving Amazon's review-farmed listings untouched.
MIN_REVIEW_COUNT = 5


def merge(
    profile: UserProfile,
    query: str,
    category: Category,
    max_price_inr: int,
    min_price_inr: int,
) -> tuple[SearchParams, list[AppliedFilter]]:
    """Combine durable preferences with this request's explicit constraints.

    Args:
        profile: The user's stored preferences.
        query: Search terms as the user phrased them.
        category: Drives which stored size is relevant.
        max_price_inr: Upper bound stated in this message, or 0 if none.
        min_price_inr: Lower bound stated in this message, or 0 if none.

    Returns:
        The params to search with, and the filters to report back.
    """
    applied: list[AppliedFilter] = []

    # Budget: this message wins outright. The profile ceiling is a fallback,
    # never an additional constraint on top of an explicit request — that is
    # what would let a t-shirt budget bleed into a laptop search.
    if max_price_inr > 0:
        budget = max_price_inr
        applied.append(AppliedFilter(label="budget", value=f"under Rs.{budget}", origin="request"))
    elif profile.budget_ceiling_inr > 0:
        budget = profile.budget_ceiling_inr
        applied.append(
            AppliedFilter(
                label="budget", value=f"under Rs.{budget} (your usual)", origin="profile"
            )
        )
    else:
        budget = 0

    if min_price_inr > 0:
        applied.append(
            AppliedFilter(label="minimum", value=f"over Rs.{min_price_inr}", origin="request")
        )

    size = _relevant_size(profile, category)
    if size:
        applied.append(AppliedFilter(label="size", value=size, origin="profile"))

    if profile.avoid_brands:
        applied.append(
            AppliedFilter(
                label="excluded", value=", ".join(profile.avoid_brands), origin="profile"
            )
        )

    if profile.preferred_brands:
        applied.append(
            AppliedFilter(
                label="prefers", value=", ".join(profile.preferred_brands), origin="profile"
            )
        )

    params = SearchParams(
        query=query,
        category=category,
        max_price_inr=budget,
        min_price_inr=min_price_inr,
        limit=OVERFETCH_LIMIT,
    )
    return params, applied


def rank(
    products: list[Product],
    profile: UserProfile,
    category: Category,
    limit: int = RESULT_LIMIT,
) -> list[Product]:
    """Drop unusable results and order what remains by fit to the profile."""
    size = _relevant_size(profile, category)
    avoid = {b.lower() for b in profile.avoid_brands}
    prefer = {b.lower() for b in profile.preferred_brands}
    unrated = _sites_without_review_data(products)
    shops_for = profile.shops_for

    keep = [p for p in products if _is_usable(p, avoid, unrated, shops_for)]
    # Sort before deduping so each group keeps its best member, not whichever
    # variant the site happened to list first.
    keep.sort(key=lambda p: _score(p, size, prefer, unrated), reverse=True)
    return _spread_across_sites(_dedupe(keep), limit)


def _dedupe(products: list[Product]) -> list[Product]:
    """Collapse the same product appearing more than once.

    Sites list one product under several ids — colour and pack-size variants
    each get their own listing. Left alone, a single popular shirt fills the
    whole comparison.
    """
    seen: set[tuple[str, str]] = set()
    unique: list[Product] = []

    for product in products:
        # Title prefix within a site, ignoring price — colour and fit variants
        # share a title and differ only by a few rupees, and two of them would
        # otherwise take two of the five slots.
        key = (product.site, product.title.strip().lower()[:45])
        if key in seen:
            continue
        seen.add(key)
        unique.append(product)

    return unique


def _spread_across_sites(ranked: list[Product], limit: int) -> list[Product]:
    """Give every site that returned something a place in the comparison.

    Pure score ordering lets one site take every slot, which makes a
    cross-site comparison that never actually compares. Each site's best
    result is seated first, then the remaining slots go by score.
    """
    best_per_site: list[Product] = []
    remainder: list[Product] = []
    claimed: set[str] = set()

    for product in ranked:  # already in score order
        if product.site not in claimed:
            claimed.add(product.site)
            best_per_site.append(product)
        else:
            remainder.append(product)

    return (best_per_site + remainder)[:limit]


def _sites_without_review_data(products: list[Product]) -> set[str]:
    """Find sites that reported no review counts at all this search.

    "This product has no reviews" and "this site doesn't tell us about
    reviews" both arrive as review_count == 0, but they mean opposite things.
    A site that reports zero everywhere is missing the data, so applying the
    review threshold to it would silently discard everything it returned.
    """
    by_site: dict[str, bool] = {}
    for product in products:
        by_site[product.site] = by_site.get(product.site, False) or (
            product.review_count > 0
        )
    return {site for site, has_data in by_site.items() if not has_data}


def _is_usable(
    product: Product, avoid: set[str], unrated_sites: set[str], shops_for: str
) -> bool:
    if product.price_inr <= 0:
        return False

    # Wrong person entirely. A women's shoe in a man's results is the most
    # visibly wrong thing the app can do, so this is a hard drop.
    if not quality.gender_matches(product, shops_for):
        return False

    if quality.is_poorly_rated(product):
        return False

    # Only demand reviews from sites that report them, and only demand that
    # there be *some*. A high review floor cut real brands on Myntra while
    # letting review-farmed Amazon listings through, which is backwards.
    if product.site not in unrated_sites and product.review_count < MIN_REVIEW_COUNT:
        return False

    haystack = f"{product.brand} {product.title}".lower()
    return not any(brand in haystack for brand in avoid)


def _score(
    product: Product, size: str, prefer: set[str], unrated_sites: set[str]
) -> float:
    score = 0.0

    # We can't vouch for a product whose site gave us no social proof, so it
    # ranks below verified ones rather than winning on price alone.
    if product.site in unrated_sites:
        score -= 1.5

    # A confirmed size in stock is worth a lot. A missing one is worth
    # nothing either way: Myntra surfaces only one size per listing, so
    # "not listed" means our data is thin, not that it doesn't fit.
    if size and product.sizes:
        wanted = _normalize_size(size)
        available = {_normalize_size(s) for s in product.sizes}
        if wanted in available:
            score += 3.0

    if prefer and any(b in f"{product.brand} {product.title}".lower() for b in prefer):
        score += 2.0

    # Rating is the strongest honest signal we get, so it carries the most.
    score += (product.rating or 0.0) * 1.5

    # Popularity as confidence, not as a prize — log-scaled and capped so a
    # review-farmed listing can't outrank a well-rated one on volume alone.
    if product.review_count > 0:
        score += min(math.log10(product.review_count) / 4, 0.5)

    # A discount used to be worth points, which handed the top spot to
    # whichever listing invented the largest "was" price.
    if quality.has_invented_mrp(product):
        score -= 1.5

    if quality.looks_like_spam(product):
        score -= 2.0

    # Sponsored placement is paid for, not earned.
    if product.is_sponsored:
        score -= 1.5

    return score


def _normalize_size(size: str) -> str:
    """Reduce a size label to something comparable across sites.

    The profile stores a bare "9" while Myntra renders "UK9" and Amazon uses
    "UK 9". Without this they never match and the size filter silently does
    nothing — which looks exactly like working code.
    """
    text = size.strip().upper().replace(" ", "").replace("-", "")
    for prefix in ("UK", "US", "EU"):
        if text.startswith(prefix):
            text = text[len(prefix) :]

    # "9.0" and "9" are the same shoe; keep "8.5" intact.
    try:
        value = float(text)
    except ValueError:
        return text
    return str(int(value)) if value.is_integer() else str(value)


def _relevant_size(profile: UserProfile, category: Category) -> str:
    if category == "footwear":
        return profile.shoe_size_uk
    if category == "clothing":
        return profile.clothing_size
    return ""
