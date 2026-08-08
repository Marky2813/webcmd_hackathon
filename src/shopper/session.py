"""Session wiring: one long-lived ADK session per Telegram user.

A missing session is the onboarding trigger, so `auto_create_session` is left
off on the Runner — letting ADK create sessions implicitly would mean every
user looks like a returning one and onboarding would never fire.
"""

from __future__ import annotations

from google.adk.sessions import DatabaseSessionService, Session

from shopper.config import APP_NAME, DB_URL, session_id_for

session_service = DatabaseSessionService(db_url=DB_URL)


async def get_or_create(telegram_user_id: int | str) -> tuple[Session, bool]:
    """Fetch this user's session, creating it if they are new.

    Args:
        telegram_user_id: The Telegram user id, used as the ADK user id.

    Returns:
        The session, and whether it was created just now. A newly created
        session means the user has never spoken to the bot before.
    """
    user_id = str(telegram_user_id)
    session_id = session_id_for(user_id)

    existing = await session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    if existing is not None:
        return existing, False

    created = await session_service.create_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    return created, True
