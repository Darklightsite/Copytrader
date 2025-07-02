"""
Authentication module for the Copytrader system.
Provides decorators and utilities for access control.
"""
from functools import wraps
from typing import Callable, Any
import logging
from telegram import Update
from telegram.ext import ContextTypes
from modules.config import ALLOWED_CHAT_IDS

logger = logging.getLogger(__name__)

def restricted(func: Callable) -> Callable:
    """
    Decorator to restrict telegram commands to authorized users only.
    Checks if the user's chat ID is in the ALLOWED_CHAT_IDS list.
    """
    @wraps(func)
    async def wrapped(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *args: Any,
        **kwargs: Any
    ) -> Any:
        if not update.effective_user:
            logger.warning("No effective user found in update")
            return None
            
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id if update.effective_chat else None
        
        if user_id not in ALLOWED_CHAT_IDS:
            logger.warning(f"Unauthorized access attempt from user {user_id} in chat {chat_id}")
            if update.message:
                await update.message.reply_text(
                    "⛔ Nincs jogosultságod használni ezt a botot.\n"
                    "Kérlek vedd fel a kapcsolatot az adminisztrátorral."
                )
            return None
            
        logger.info(f"Authorized access from user {user_id} in chat {chat_id}")
        return await func(update, context, *args, **kwargs)
        
    return wrapped

def is_authorized(user_id: int) -> bool:
    """
    Utility function to check if a user ID is authorized.
    """
    return user_id in ALLOWED_CHAT_IDS 