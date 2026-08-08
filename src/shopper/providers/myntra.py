"""Myntra, parsed from a rendered page — no adapter exists for it.

There is no Myntra plugin in the webcmd registry, so this drives the generic
`web fetch-browser` command and parses the Markdown it returns. In exchange for
that fragility we get the one field Amazon's search results don't carry:
which sizes are actually in stock.

The listing markup is regular. Each product renders as a run of fields
terminated by a link to its product page:

    4.4
    |
    344
    AD
    ![alt](image url)
    ### CULT
    #### Men Running Shoes
    #### Sizes: UK9
    Rs. 2434Rs. 4069(40% OFF)
    ](https://www.myntra.com/sports-shoes/cult/.../33384081/buy)

So the product-page links are the record separators, and everything between
two of them describes the second one.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from shopper.models import Product, SearchParams
from shopper.providers.base import to_int_inr
from shopper.webcmd_client import run_raw

site = "myntra"

# Rendering the listing needs a moment for the grid to populate.
_PAGE_WAIT_S = 6
_FETCH_TIMEOUT_S = 60

_ANCHOR = re.compile(r"\]\((https://www\.myntra\.com/[^)\s]*?/(\d+)/buy)\)")
_PRICE = re.compile(r"Rs\.\s*([\d,]+)(?:\s*Rs\.\s*([\d,]+))?")
_BRAND = re.compile(r"^\s*###\s+(.+?)\s*$", re.MULTILINE)
_SIZES = re.compile(r"^\s*####\s+Sizes:\s*(.+?)\s*$", re.MULTILINE)
_NAME = re.compile(r"^\s*####\s+(?!Sizes:)(.+?)\s*$", re.MULTILINE)
# The rating opens a Markdown list item, so it arrives as "-   4.4".
_RATING = re.compile(r"^\s*(?:-\s+)?(\d(?:\.\d)?)\s*$", re.MULTILINE)
_REVIEWS = re.compile(r"^\s*([\d.]+k?)\s*$", re.MULTILINE | re.IGNORECASE)
_SPONSORED = re.compile(r"^\s*AD\s*$", re.MULTILINE)


def search(params: SearchParams) -> list[Product]:
    """Search Myntra and normalize the rendered listing onto `Product`.

    Myntra exposes no price bounds on this URL shape, so the budget is applied
    after parsing rather than pushed into the request.
    """
    markdown = run_raw(
        "web",
        "fetch-browser",
        "--url",
        _search_url(params.query),
        "--stdout",
        "--wait",
        str(_PAGE_WAIT_S),
        timeout=_FETCH_TIMEOUT_S,
    )

    products = _parse(markdown)
    return [p for p in products if _within_budget(p, params)][: params.limit]


def _search_url(query: str) -> str:
    """Build a Myntra listing URL.

    The path slug drives the category page; `rawQuery` makes Myntra fall back
    to real search results when the slug isn't a category of its own.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
    return f"https://www.myntra.com/{slug}?rawQuery={quote(query)}"


def _within_budget(product: Product, params: SearchParams) -> bool:
    if params.max_price_inr and product.price_inr > params.max_price_inr:
        return False
    if params.min_price_inr and product.price_inr < params.min_price_inr:
        return False
    return True


def _parse(markdown: str) -> list[Product]:
    """Split the page on product links and read each preceding field block."""
    products: list[Product] = []
    cursor = 0

    for match in _ANCHOR.finditer(markdown):
        block = markdown[cursor : match.start()]
        cursor = match.end()

        product = _parse_block(block, url=match.group(1), product_id=match.group(2))
        if product is not None:
            products.append(product)

    return products


def _parse_block(block: str, *, url: str, product_id: str) -> Product | None:
    """Build one Product from the field run preceding its link.

    Returns None when the block carries no price — that filters out the
    navigation and filter-sidebar links that share the product URL shape.
    """
    price_match = _PRICE.search(block)
    if not price_match:
        return None

    price = to_int_inr(price_match.group(1))
    mrp = to_int_inr(price_match.group(2)) if price_match.group(2) else price
    if not price:
        return None

    brand_match = _BRAND.search(block)
    brand = brand_match.group(1).strip() if brand_match else ""

    # The first #### that isn't the sizes line is the product name. Myntra
    # shows a short descriptor there rather than the full title.
    name_match = _NAME.search(block)
    name = name_match.group(1).strip() if name_match else ""
    title = f"{brand} {name}".strip() or name or brand

    sizes_match = _SIZES.search(block)
    sizes = (
        [s.strip() for s in sizes_match.group(1).split(",") if s.strip()]
        if sizes_match
        else []
    )

    return Product(
        site=site,
        product_id=product_id,
        title=title,
        url=url,
        price_inr=price,
        mrp_inr=mrp,
        brand=brand,
        rating=_parse_rating(block),
        review_count=_parse_reviews(block),
        sizes=sizes,
        is_sponsored=bool(_SPONSORED.search(block)),
    )


def _parse_rating(block: str) -> float | None:
    """The rating is the first bare decimal in the block, and is 0-5."""
    for candidate in _RATING.findall(block):
        value = float(candidate)
        if 0 < value <= 5:
            return value
    return None


def _parse_reviews(block: str) -> int:
    """Review counts render as `344` or `14.5k`."""
    for candidate in _REVIEWS.findall(block):
        text = candidate.lower()
        if text.endswith("k"):
            try:
                return int(float(text[:-1]) * 1000)
            except ValueError:
                continue
        if text.isdigit() and int(text) > 5:
            return int(text)
    return 0
