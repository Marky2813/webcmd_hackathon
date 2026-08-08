"""The contract every shopping site implements.

Adding a site means writing one module that satisfies this protocol and adding
it to `registry.ENABLED`. Nothing else in the app changes — that is what makes
the pending Flipkart adapter a drop-in rather than a refactor.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from shopper.models import Product, SearchParams


@runtime_checkable
class SearchProvider(Protocol):
    """A single shopping site the agent can search."""

    site: str

    def search(self, params: SearchParams) -> list[Product]:
        """Return normalized results, or an empty list if the site has none.

        Implementations raise on genuine failure (network, bot wall, broken
        parse) so the caller can report which site degraded. They must not
        raise merely because a query matched nothing.
        """
        ...


def to_int_inr(value: object) -> int:
    """Coerce a provider's price field to whole rupees.

    Adapter-backed sites already return numbers; markdown-scraped sites return
    strings like "1,999". Both land here so `Product.price_inr` is always int.
    """
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits:
            return int(digits)
    return 0
