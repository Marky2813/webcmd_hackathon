"""Tools that read and write the user's durable profile.

These are the only writers of durable state in the app, and each one requires
the user to have said something outright. Nothing here may be called on a
hunch — a profile someone never agreed to is a profile they cannot correct.
"""

from __future__ import annotations

from google.adk.tools import ToolContext

from shopper.models import UserProfile
from shopper.tools._state import load_profile, store_profile

_LIST_FIELDS = {"preferred_brands", "avoid_brands", "style_notes"}
_INT_FIELDS = {"budget_ceiling_inr"}

_MAX_STYLE_NOTES = 12


def save_profile(
    name: str,
    shoe_size_uk: str,
    clothing_size: str,
    budget_ceiling_inr: int,
    preferred_brands: list[str],
    avoid_brands: list[str],
    city: str,
    shops_for: str,
    style_notes: list[str],
    tool_context: ToolContext,
) -> dict:
    """Saves what you have learned about this person so far.

    A thin profile is a real profile. Call this as soon as you know their name
    and roughly who they are — you do not need sizes, budget or city first,
    and you should not stall the conversation collecting them. Everything
    missing can be picked up later with update_preference when it matters.

    Never invent a value. Pass an empty string, 0, or an empty list for
    anything they haven't told you or chose to skip.

    Args:
        name: What they want to be called.
        shoe_size_uk: UK shoe size as they said it, e.g. "9" or "8.5". Empty
            if you haven't needed it yet.
        clothing_size: Letter size, one of XS, S, M, L, XL, XXL. Empty if
            not yet known.
        budget_ceiling_inr: What they usually spend on a single item, in
            rupees. A fallback for requests that state no budget; 0 if unknown.
        preferred_brands: Brands they named as ones they like.
        avoid_brands: Brands they want excluded from every search.
        city: Their city, for delivery expectations.
        shops_for: Who they're shopping for — "men", "women" or "kids". This
            one matters: without it, a search for running shoes returns
            women's and children's shoes and they rank near the top. Ask
            casually the first time a clothing or footwear search needs it,
            the same way you'd ask for a size. Empty if not yet known.
        style_notes: Short, concrete observations about their taste, in their
            own terms — e.g. ["wears the same plain black tee on repeat",
            "buys one good thing a year", "hates logos"]. This is what lets a
            recommendation sound like it came from someone who knows them, so
            record what they actually said rather than a label you inferred.

    Returns:
        A dict with 'status' and 'profile'. Confirm it back in a line that
        sounds like you understood them, not like a receipt.
    """
    profile = UserProfile(
        name=name.strip(),
        shoe_size_uk=shoe_size_uk.strip(),
        clothing_size=clothing_size.strip().upper(),
        budget_ceiling_inr=max(0, budget_ceiling_inr),
        preferred_brands=[b.strip() for b in preferred_brands if b.strip()],
        avoid_brands=[b.strip() for b in avoid_brands if b.strip()],
        city=city.strip(),
        shops_for=shops_for.strip().lower(),
        style_notes=[n.strip() for n in style_notes if n.strip()][:_MAX_STYLE_NOTES],
    )
    store_profile(tool_context, profile)
    return {"status": "saved", "profile": profile.model_dump()}


def get_profile(tool_context: ToolContext) -> dict:
    """Reads what you already know about this person. Call this first, always.

    'not_yet_known' is context, not a checklist. Do not walk it asking one
    question per entry — collect a field when the conversation reaches it, or
    when a search genuinely needs it.

    Returns:
        A dict with 'known' (whether you've met them), 'profile' (everything
        stored, including style_notes in their own words), and 'not_yet_known'
        (fields still empty).
    """
    profile = load_profile(tool_context)
    not_yet_known = [
        field
        for field in (
            "name",
            "shoe_size_uk",
            "clothing_size",
            "budget_ceiling_inr",
            "city",
            "shops_for",
            "style_notes",
        )
        if not getattr(profile, field)
    ]
    return {
        "known": profile.is_complete,
        "profile": profile.model_dump(),
        "not_yet_known": not_yet_known,
    }


def remember_taste(note: str, tool_context: ToolContext) -> dict:
    """Records one lasting observation about their taste, after they agreed.

    Call this only when they have confirmed the pattern out loud. The flow is:
    you notice something, you say it ("third time you've picked plain over a
    logo, want me to default to that?"), they say yes, and only then do you
    call this. Never call it straight off an observation.

    A one-off reaction to a single product is not taste and does not belong
    here. Neither does anything you inferred without saying it.

    Args:
        note: The observation in short, concrete terms, phrased the way they
            put it — e.g. "prefers plain over logos".

    Returns:
        A dict with 'status' and the full 'style_notes' list after the update.
        Status is 'duplicate' if you already knew this.
    """
    text = note.strip()
    if not text:
        return {"status": "error", "message": "Empty note."}

    profile = load_profile(tool_context)

    if any(text.lower() == existing.lower() for existing in profile.style_notes):
        return {
            "status": "duplicate",
            "style_notes": profile.style_notes,
        }

    profile.style_notes = (profile.style_notes + [text])[-_MAX_STYLE_NOTES:]
    store_profile(tool_context, profile)
    return {"status": "remembered", "style_notes": profile.style_notes}


def update_preference(field: str, value: str, tool_context: ToolContext) -> dict:
    """Updates one durable preference after they state a lasting change.

    Call this when they say something outright: "I'm a 10 now", "stop showing
    me Puma", "I'm in Pune these days". Also use it to fill in a field you
    simply hadn't collected yet, once they tell you.

    A one-off constraint like "under 2k this time" is NOT a preference and
    must never be saved. Never call this on something you inferred rather than
    heard.

    Args:
        field: One of "name", "shoe_size_uk", "clothing_size",
            "budget_ceiling_inr", "preferred_brands", "avoid_brands", "city",
            "shops_for", "style_notes".
        value: The new value as a string. For list fields, a comma-separated
            list which replaces the existing one entirely — to add a single
            taste observation without discarding the others, use
            remember_taste instead.

    Returns:
        A dict with 'status', 'field', 'old_value' and 'new_value', so you can
        confirm the change in your own words.
    """
    profile = load_profile(tool_context)

    if field not in UserProfile.model_fields:
        return {
            "status": "error",
            "message": f"Unknown preference '{field}'.",
            "valid_fields": sorted(UserProfile.model_fields),
        }

    old = getattr(profile, field)

    if field in _LIST_FIELDS:
        new: object = [v.strip() for v in value.split(",") if v.strip()]
    elif field in _INT_FIELDS:
        digits = "".join(ch for ch in value if ch.isdigit())
        if not digits:
            return {
                "status": "error",
                "field": field,
                "message": f"Could not read a rupee amount from '{value}'.",
            }
        new = int(digits)
    else:
        new = value.strip()

    setattr(profile, field, new)
    store_profile(tool_context, profile)

    return {
        "status": "updated",
        "field": field,
        "old_value": old,
        "new_value": new,
    }
