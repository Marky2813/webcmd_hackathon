"""Telegram front end.

Searches take ten to fifteen seconds because three browser-backed sites are
driven concurrently. Silence that long reads as a broken bot, so this keeps a
typing indicator alive and posts a status line the moment a search starts.
"""

from __future__ import annotations

import asyncio
import logging

from google.genai import types
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from shopper.agent import runner
from shopper.config import PROFILE_STATE_KEY, require_telegram_token, session_id_for
from shopper.models import UserProfile
from shopper.session import get_or_create

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s | %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("shopper.bot")

# Telegram clears the typing bubble after ~5s, so refresh inside that window.
_TYPING_REFRESH_S = 4.0
_TELEGRAM_MAX_CHARS = 4096

_SEARCHING_NOTE = "Searching Amazon, Myntra and Flipkart..."

# Throwaway identity used only to warm the model at startup.
_WARMUP_USER = "warmup"
_WARMUP_ATTEMPTS = 4
_WARMUP_RETRY_DELAY_S = 4.0


async def _keep_typing(bot, chat_id: int) -> None:
    """Hold the typing indicator until cancelled."""
    try:
        while True:
            await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            await asyncio.sleep(_TYPING_REFRESH_S)
    except asyncio.CancelledError:
        pass


async def _send(update: Update, text: str) -> None:
    """Send a reply, split to respect Telegram's per-message limit."""
    for start in range(0, len(text), _TELEGRAM_MAX_CHARS):
        # No parse_mode: product titles contain _ * [ ] that would break
        # Markdown parsing, and Telegram auto-links bare URLs anyway.
        await update.message.reply_text(text[start : start + _TELEGRAM_MAX_CHARS])


async def _run_agent(update: Update, user_id: str, text: str) -> None:
    """Drive one turn and stream user-visible progress back to the chat."""
    chat_id = update.effective_chat.id
    typing = asyncio.create_task(_keep_typing(update.get_bot(), chat_id))
    announced_search = False
    chunks: list[str] = []

    try:
        message = types.Content(role="user", parts=[types.Part(text=text)])

        async for event in runner.run_async(
            user_id=user_id, session_id=session_id_for(user_id), new_message=message
        ):
            if not (event.content and event.content.parts):
                continue

            for part in event.content.parts:
                call = getattr(part, "function_call", None)
                if call and call.name == "search_products" and not announced_search:
                    announced_search = True
                    await update.message.reply_text(_SEARCHING_NOTE)
                elif part.text:
                    chunks.append(part.text)

        reply = "".join(chunks).strip()
        await _send(update, reply or "Sorry, I didn't manage a reply. Try again?")

    except Exception as exc:
        log.exception("turn failed for %s", user_id)
        text_ = f"{type(exc).__name__} {exc}".lower()
        transient = any(
            marker in text_
            for marker in ("timeout", "timed out", "connect", "network", "overload")
        )
        await _send(
            update,
            "That took too long to reach the shops. Ask me again?"
            if transient
            else "Something went wrong on my side. Try that again in a moment.",
        )
    finally:
        typing.cancel()


async def on_message(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    # Creates the session on first contact; the agent notices the empty
    # profile and starts onboarding by itself.
    _, is_new = await get_or_create(user_id)
    if is_new:
        log.info("new user %s", user_id)

    await _run_agent(update, user_id, update.message.text)


async def on_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    await get_or_create(user_id)
    await _run_agent(update, user_id, "Hi")


async def on_profile(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Show what's stored, so preferences are inspectable and correctable."""
    user_id = str(update.effective_user.id)
    session, _created = await get_or_create(user_id)

    raw = session.state.get(PROFILE_STATE_KEY)
    if not raw:
        await _send(update, "I don't know anything about you yet. Say hi to get started.")
        return

    p = UserProfile.model_validate(raw)
    lines = ["Here's what I've got:", ""]

    if p.name:
        lines.append(f"Name: {p.name}")
    if p.shoe_size_uk:
        lines.append(f"Shoe size: UK {p.shoe_size_uk}")
    if p.clothing_size:
        lines.append(f"Clothing size: {p.clothing_size}")
    if p.budget_ceiling_inr:
        lines.append(f"Usual budget: Rs.{p.budget_ceiling_inr:,}")
    if p.preferred_brands:
        lines.append(f"Likes: {', '.join(p.preferred_brands)}")
    if p.avoid_brands:
        lines.append(f"Avoids: {', '.join(p.avoid_brands)}")
    if p.city:
        lines.append(f"City: {p.city}")

    # The part that actually shapes recommendations, so show it plainly.
    if p.style_notes:
        lines += ["", "What I've picked up about your taste:"]
        lines += [f"- {note}" for note in p.style_notes]

    lines += ["", 'Anything off, just say so. "I\'m a 10 now" works.']
    await _send(update, "\n".join(lines))


async def _warmup(_app: Application) -> None:
    """Pay litellm's one-time init cost before any user can hit it.

    The first model call in a process does a blocking setup fetch that can
    freeze the event loop for ~25s on a slow network. Left until the first
    real message, that stalls the typing indicator and times out every
    Telegram request, which reads to the user as the bot being broken.
    """
    log.info("warming the model...")
    started = asyncio.get_running_loop().time()

    for attempt in range(1, _WARMUP_ATTEMPTS + 1):
        try:
            await get_or_create(_WARMUP_USER)
            message = types.Content(role="user", parts=[types.Part(text="hi")])
            async for _ in runner.run_async(
                user_id=_WARMUP_USER,
                session_id=session_id_for(_WARMUP_USER),
                new_message=message,
            ):
                pass
        except Exception as exc:
            # A failed warmup leaves the cost unpaid, so the first real user
            # eats the freeze. Worth several attempts before giving up.
            log.warning("warmup attempt %d failed: %s", attempt, exc)
            if attempt < _WARMUP_ATTEMPTS:
                await asyncio.sleep(_WARMUP_RETRY_DELAY_S)
                continue
            log.error("model NOT warm — the first message may stall. Restart to retry.")
            return
        else:
            elapsed = asyncio.get_running_loop().time() - started
            log.info("model warm after %.1fs — replies will be fast now", elapsed)
            return


def main() -> None:
    app = (
        Application.builder()
        .token(require_telegram_token())
        .post_init(_warmup)
        # Defaults are 5s with no bootstrap retry, so a single slow handshake
        # kills the process at startup. On conference wifi that is a coin flip.
        .connect_timeout(20.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(20.0)
        .build()
    )
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("profile", on_profile))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    log.info("bot up, polling")
    app.run_polling(bootstrap_retries=5)


if __name__ == "__main__":
    main()
