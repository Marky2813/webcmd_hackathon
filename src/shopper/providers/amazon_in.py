"""Amazon.in, backed by the installed `amazon-in` webcmd adapter.

The adapter returns typed numerics and takes native price bounds, so budget
filtering is pushed into the CLI rather than done here. Search works without a
login; only cart preparation needs cookies.
"""

from __future__ import annotations

from shopper.models import Product, SearchParams
from shopper.providers.base import to_int_inr
from shopper.webcmd_client import run

site = "amazon.in"


def search(params: SearchParams) -> list[Product]:
    """Search Amazon.in and normalize the adapter's rows onto `Product`."""
    args: list[str] = [params.query]

    if params.max_price_inr > 0:
        args += ["--max-price", str(params.max_price_inr)]
    if params.min_price_inr > 0:
        args += ["--min-price", str(params.min_price_inr)]
    args += ["--limit", str(params.limit)]

    rows = run("amazon-in", "search", *args)
    return [_to_product(row) for row in rows if row.get("product_url")]


def _to_product(row: dict) -> Product:
    return Product(
        site=site,
        product_id=str(row.get("asin") or ""),
        title=str(row.get("title") or ""),
        url=str(row.get("product_url") or ""),
        price_inr=to_int_inr(row.get("price")),
        mrp_inr=to_int_inr(row.get("mrp")),
        # Amazon search results don't carry a brand field; the title leads with
        # it often enough that ranking matches on the title instead.
        brand="",
        rating=_to_rating(row.get("rating")),
        review_count=to_int_inr(row.get("review_count")),
        # Sizes live on the product page, not the search listing.
        sizes=[],
        image_url=str(row.get("image_url") or ""),
        is_sponsored=bool(row.get("is_sponsored")),
    )


def _to_rating(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None
