"""Telling a good listing from a bad one.

Indian marketplace search is full of listings that are optimised for the
ranking algorithm rather than the buyer: invented MRPs, keyword-stuffed
titles, and review counts that don't mean what they look like. These helpers
encode the signals that separate the two, so ranking can act on them.
"""

from __future__ import annotations

import re

from shopper.models import Product

# Above this, the "discount" is usually measured against a price nobody ever
# charged. Genuine clearance exists, but 80% off is a red flag, not a deal.
IMPLAUSIBLE_DISCOUNT_PCT = 70

# A listing rated below this is bad enough that no price makes up for it.
MIN_RATING = 3.7

_WOMENS = re.compile(r"\b(women|women's|womens|girl|girls|ladies|female)\b", re.I)
_MENS = re.compile(r"\b(men|men's|mens|boy|boys|male|gents)\b", re.I)
_KIDS = re.compile(r"\b(kid|kids|boys|girls|child|children|youth|toddler|infant|baby)\b", re.I)

# "Men Jeans || Baggy Fit Jean's for Man || Looses Fit Denim" — pipes, repeated
# keywords and comma runs are how a listing shouts at a search engine.
_PIPE_SPAM = re.compile(r"\|\s*\|")
_COMMA_RUN = re.compile(r"(,\s*\w+){4,}")


def gender_matches(product: Product, shops_for: str) -> bool:
    """Is this listing plausibly for the person we're shopping for?

    Titles are the only gender signal the sites give us, so this is a
    heuristic — but "Women Running Shoes" reaching a man's top five is a much
    worse failure than dropping an ambiguously-titled unisex listing.
    """
    if not shops_for:
        return True

    title = product.title
    wants = shops_for.strip().lower()

    if wants == "kids":
        return bool(_KIDS.search(title))

    # Kids' items are never right for an adult, even when the gender lines up
    # ("Puma Kids Coarse Youth Running Shoe" matches "boys" too).
    if _KIDS.search(title):
        return False

    if wants == "men":
        # Unlabelled titles pass; explicitly women's ones don't.
        return not (_WOMENS.search(title) and not _MENS.search(title))
    if wants == "women":
        return not (_MENS.search(title) and not _WOMENS.search(title))

    return True


def looks_like_spam(product: Product) -> bool:
    """Is the title written for a search engine rather than a human?"""
    title = product.title
    if _PIPE_SPAM.search(title):
        return True
    if title.count("|") >= 2:
        return True
    if _COMMA_RUN.search(title):
        return True
    return False


def has_invented_mrp(product: Product) -> bool:
    """Is the 'was' price fiction?"""
    return product.discount_pct >= IMPLAUSIBLE_DISCOUNT_PCT


def is_poorly_rated(product: Product) -> bool:
    """Rated, and rated badly. Unrated products are unknown, not bad."""
    return product.rating is not None and product.rating < MIN_RATING
