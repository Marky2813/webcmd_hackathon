"""Normalized data shapes shared across providers, ranking, and tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["footwear", "clothing", "other"]
FilterOrigin = Literal["profile", "request"]


class Product(BaseModel):
    """One search result, normalized across every shopping site.

    Providers are responsible for mapping their site's raw fields onto this
    shape. Fields a site does not expose stay empty rather than absent, so
    ranking never has to special-case a provider.
    """

    site: str
    product_id: str
    title: str
    url: str
    price_inr: int
    mrp_inr: int = 0
    brand: str = ""
    rating: float | None = None
    review_count: int = 0
    sizes: list[str] = Field(default_factory=list)
    image_url: str = ""
    is_sponsored: bool = False

    @property
    def discount_pct(self) -> int:
        if self.mrp_inr <= self.price_inr:
            return 0
        return round((self.mrp_inr - self.price_inr) / self.mrp_inr * 100)


class UserProfile(BaseModel):
    """Durable preferences. Persisted under the ADK `user:` state prefix.

    Only ever written by save_profile / update_preference, both of which
    require an explicit user statement. Never inferred from behaviour.
    """

    name: str = ""
    shoe_size_uk: str = ""
    clothing_size: str = ""
    budget_ceiling_inr: int = 0
    preferred_brands: list[str] = Field(default_factory=list)
    avoid_brands: list[str] = Field(default_factory=list)
    city: str = ""

    # "men", "women", "kids", or empty. Without this, a search for running
    # shoes cheerfully returns women's and boys' shoes to a man and they rank
    # near the top, because nothing downstream knows any better.
    shops_for: str = ""

    # What they actually like, in their own terms — "plain over logos",
    # "buys one good thing a year", "same black tee three times over".
    # Brand lists capture almost none of this, and it is the part that makes a
    # recommendation sound like it came from someone who knows them.
    style_notes: list[str] = Field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """Enough to start being useful — a name is the only hard requirement.

        Sizes are logistics, collected when a search actually needs them, so a
        thin profile is a valid profile rather than an unfinished form.
        """
        return bool(self.name)


class SearchParams(BaseModel):
    """What a provider is actually asked to fetch.

    This is the merged result of profile + this message's constraints. It is
    passed down to providers and thrown away afterwards — nothing here is
    persisted, which is what stops a one-off budget leaking into the profile.
    """

    query: str
    category: Category = "other"
    min_price_inr: int = 0
    max_price_inr: int = 0
    limit: int = 15


class AppliedFilter(BaseModel):
    """One filter that shaped the results, and where it came from.

    Surfaced back to the user so personalization is visible rather than
    implied — the agent states these in its reply.
    """

    label: str
    value: str
    origin: FilterOrigin


class SearchOutcome(BaseModel):
    """Everything the search tool hands back to the agent."""

    applied_filters: list[AppliedFilter] = Field(default_factory=list)
    results: list[Product] = Field(default_factory=list)
    sites_searched: list[str] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)
