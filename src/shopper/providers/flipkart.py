"""Flipkart, backed by a custom `flipkart` webcmd adapter.

The adapter mirrors `amazon-in/search`: same argument names, same numeric
price fields, so this provider is nearly a copy of the Amazon one.

Known gap: the adapter returns `rating: null` and `review_count: 0` for every
row — Flipkart renders those per-product badges in a form its extraction
doesn't reach. Ranking detects a site reporting no review data anywhere and
treats those products as unrated rather than as zero-reviewed, so they are not
silently filtered out. If the adapter later starts returning real numbers,
nothing here needs to change.
"""

from __future__ import annotations

from shopper.models import Product, SearchParams
from shopper.providers.base import to_int_inr
from shopper.webcmd_client import run

site = "flipkart"

# Browser-driven, so slower than the Amazon adapter.
_TIMEOUT_S = 60


def search(params: SearchParams) -> list[Product]:
    """Search Flipkart and normalize the adapter's rows onto `Product`."""
    args: list[str] = [params.query]

    if params.max_price_inr > 0:
        args += ["--max-price", str(params.max_price_inr)]
    if params.min_price_inr > 0:
        args += ["--min-price", str(params.min_price_inr)]
    args += ["--limit", str(params.limit)]

    rows = run("flipkart", "search", *args, timeout=_TIMEOUT_S)
    return [_to_product(row) for row in rows if row.get("product_url")]


def _to_product(row: dict) -> Product:
    return Product(
        site=site,
        product_id=str(row.get("product_id") or ""),
        title=str(row.get("title") or ""),
        url=str(row.get("product_url") or ""),
        price_inr=to_int_inr(row.get("price")),
        mrp_inr=to_int_inr(row.get("mrp")),
        # The adapter lowercases the brand (it comes from the URL slug).
        brand=str(row.get("brand") or "").title(),
        rating=_to_rating(row.get("rating")),
        review_count=to_int_inr(row.get("review_count")),
        # Contract says comma-separated; currently always empty.
        sizes=[s.strip() for s in str(row.get("sizes") or "").split(",") if s.strip()],
        is_sponsored=bool(row.get("is_sponsored")),
    )


def _to_rating(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None
