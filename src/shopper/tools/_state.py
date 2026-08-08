"""Reading and writing the durable profile in ADK session state."""

from __future__ import annotations

from google.adk.tools import ToolContext

from shopper.config import PROFILE_STATE_KEY
from shopper.models import UserProfile


def load_profile(tool_context: ToolContext) -> UserProfile:
    """Read the stored profile, or an empty one for a first-time user."""
    raw = tool_context.state.get(PROFILE_STATE_KEY)
    if not raw:
        return UserProfile()
    if isinstance(raw, UserProfile):
        return raw
    return UserProfile.model_validate(raw)


def store_profile(tool_context: ToolContext, profile: UserProfile) -> None:
    """Persist the profile. ADK turns this into a state delta on the event.

    Stored as a plain dict so it survives the JSON round-trip through SQLite.
    """
    tool_context.state[PROFILE_STATE_KEY] = profile.model_dump()
