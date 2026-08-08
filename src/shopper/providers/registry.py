"""Which sites the agent currently searches.

To add the Flipkart adapter once it lands: install the plugin, confirm its
columns match the agreed contract, then add `flipkart` to ENABLED. That is the
whole integration.
"""

from __future__ import annotations

from shopper.providers import amazon_in, flipkart, myntra
from shopper.providers.base import SearchProvider

ENABLED: list[SearchProvider] = [
    amazon_in,  # type: ignore[list-item]  # modules satisfy the protocol
    myntra,  # type: ignore[list-item]
    flipkart,  # type: ignore[list-item]
]
