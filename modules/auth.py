"""
Enhanced authentication module for the Copytrader system.
Provides secure decorators and utilities for access control with rate limiting.
"""
from functools import wraps
from typing import Callable, Any, Dict, List
import logging
import time
from datetime import datetime, timedelta
from collections import defaultdict, deque
from telegram import Update
from telegram.ext import ContextTypes
from modules.config import ALLOWED_CHAT_IDS

logger = logging.getLogger(__name__)

class SecurityManager:
    """Enhanced security manager with rate limiting and session management"""
    
    def __init__(self):
        # Rate limiting storage
        self.failed_attempts: Dict[int, deque] = defaultdict(lambda: deque(maxlen=10))
        self.blocked_users: Dict[int, datetime] = {}
        self.successful_logins: Dict[int, datetime] = {}
        
        # Session management
        self.active_sessions: Dict[int, Dict[str, Any]] = {}
        
        # Security settings
        self.max_attempts = 5
        self.block_duration_minutes = 60
        self.rate_limit_window_minutes = 15
        self.session_timeout_hours = 24
        
    def is_user_blocked(self, user_id: int) -> bool:
        """Check if user is currently blocked"""
        if user_id in self.blocked_users:
            block_expiry = self.blocked_users[user_id]
            if datetime.now() < block_expiry:
                return True
            else:
                # Block expired, remove from blocked users
                del self.blocked_users[user_id]
                self.failed_attempts[user_id].clear()
        return False
    
    def is_rate_limited(self, user_id: int) -> bool:
        """Check if user is rate limited"""
        now = datetime.now()
        attempts = self.failed_attempts[user_id]
        
        # Remove old attempts outside the window
        while attempts and attempts[0] < now - timedelta(minutes=self.rate_limit_window_minutes):
            attempts.popleft()
        
        # Check if too many attempts in window
        if len(attempts) >= self.max_attempts:
            # Block the user
            self.blocked_users[user_id] = now + timedelta(minutes=self.block_duration_minutes)
            logger.warning(f"User {user_id} blocked for {self.block_duration_minutes} minutes due to too many failed attempts")
            return True
            
        return False
    
    def record_failed_attempt(self, user_id: int):
        """Record a failed authentication attempt"""
        self.failed_attempts[user_id].append(datetime.now())
        logger.warning(f"Failed authentication attempt from user {user_id}. "
                      f"Attempts in last {self.rate_limit_window_minutes} minutes: {len(self.failed_attempts[user_id])}")
    
    def record_successful_login(self, user_id: int, chat_id: int):
        """Record successful authentication and create session"""
        now = datetime.now()
        self.successful_logins[user_id] = now
        
        # Clear failed attempts on successful login
        if user_id in self.failed_attempts:
            self.failed_attempts[user_id].clear()
        
        # Create/update session
        self.active_sessions[user_id] = {
            'chat_id': chat_id,
            'login_time': now,
            'last_activity': now,
            'commands_executed': 0
        }
        
        logger.info(f"Successful authentication for user {user_id} in chat {chat_id}")
    
    def is_session_valid(self, user_id: int) -> bool:
        """Check if user has a valid active session"""
        if user_id not in self.active_sessions:
            return False
            
        session = self.active_sessions[user_id]
        session_age = datetime.now() - session['login_time']
        
        if session_age > timedelta(hours=self.session_timeout_hours):
            del self.active_sessions[user_id]
            logger.info(f"Session expired for user {user_id}")
            return False
            
        return True
    
    def update_session_activity(self, user_id: int, command: str = None):
        """Update session activity timestamp"""
        if user_id in self.active_sessions:
            session = self.active_sessions[user_id]
            session['last_activity'] = datetime.now()
            session['commands_executed'] += 1
            
            if command is not None:
                session['last_command'] = command
    
    def get_session_info(self, user_id: int) -> Dict[str, Any]:
        """Get session information for user"""
        return self.active_sessions.get(user_id, {})
    
    def cleanup_expired_sessions(self):
        """Clean up expired sessions and blocks"""
        now = datetime.now()
        
        # Clean expired sessions
        expired_sessions = []
        for user_id, session in self.active_sessions.items():
            if now - session['login_time'] > timedelta(hours=self.session_timeout_hours):
                expired_sessions.append(user_id)
        
        for user_id in expired_sessions:
            del self.active_sessions[user_id]
            
        # Clean expired blocks
        expired_blocks = []
        for user_id, block_expiry in self.blocked_users.items():
            if now >= block_expiry:
                expired_blocks.append(user_id)
        
        for user_id in expired_blocks:
            del self.blocked_users[user_id]

# Global security manager instance
security_manager = SecurityManager()

def enhanced_restricted(func: Callable) -> Callable:
    """
    Enhanced decorator to restrict telegram commands to authorized users with security features.
    
    Features:
    - Rate limiting
    - Session management
    - Failed attempt tracking
    - User blocking
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
        command_name = func.__name__
        
        # Check if user is blocked
        if security_manager.is_user_blocked(user_id):
            logger.warning(f"Blocked user {user_id} attempted to access {command_name}")
            if update.message:
                await update.message.reply_text(
                    "🚫 Hozzáférés ideiglenesen letiltva. Túl sok sikertelen próbálkozás miatt.\n"
                    "Kérlek próbáld újra később."
                )
            return None
        
        # Check if user is in allowed list
        if user_id not in ALLOWED_CHAT_IDS:
            security_manager.record_failed_attempt(user_id)
            
            # Check if now rate limited after this attempt
            if security_manager.is_rate_limited(user_id):
                if update.message:
                    await update.message.reply_text(
                        "🚫 Túl sok sikertelen próbálkozás. Hozzáférés ideiglenesen letiltva.\n"
                        f"Próbáld újra {security_manager.block_duration_minutes} perc múlva."
                    )
            else:
                if update.message:
                    await update.message.reply_text(
                        "⛔ Nincs jogosultságod használni ezt a botot.\n"
                        "Kérlek vedd fel a kapcsolatot az adminisztrátorral."
                    )
            
            logger.warning(f"Unauthorized access attempt from user {user_id} in chat {chat_id} for command {command_name}")
            return None
        
        # Check session validity
        if not security_manager.is_session_valid(user_id):
            # Create new session for authorized user
            if chat_id is not None:
                security_manager.record_successful_login(user_id, chat_id)
        else:
            # Update existing session activity
            security_manager.update_session_activity(user_id, command_name)
        
        logger.info(f"Authorized access from user {user_id} in chat {chat_id} for command {command_name}")
        
        try:
            # Execute the original function
            result = await func(update, context, *args, **kwargs)
            
            # Clean up expired sessions periodically
            if user_id % 10 == 0:  # Cleanup every 10th command
                security_manager.cleanup_expired_sessions()
                
            return result
            
        except Exception as e:
            logger.error(f"Error executing command {command_name} for user {user_id}: {e}", exc_info=True)
            if update.message:
                await update.message.reply_text(
                    "❌ Hiba történt a parancs végrehajtása közben. Az adminisztrátor értesítve lett."
                )
            raise
        
    return wrapped

# Backward compatibility alias
restricted = enhanced_restricted

def is_authorized(user_id: int) -> bool:
    """
    Utility function to check if a user ID is authorized.
    Also considers if user is currently blocked.
    """
    if user_id not in ALLOWED_CHAT_IDS:
        return False
        
    return not security_manager.is_user_blocked(user_id)

def get_security_stats() -> Dict[str, Any]:
    """Get security statistics for monitoring"""
    return {
        'active_sessions': len(security_manager.active_sessions),
        'blocked_users': len(security_manager.blocked_users),
        'users_with_failed_attempts': len([
            uid for uid, attempts in security_manager.failed_attempts.items() 
            if len(attempts) > 0
        ]),
        'total_failed_attempts': sum(
            len(attempts) for attempts in security_manager.failed_attempts.values()
        )
    }

def force_logout_user(user_id: int) -> bool:
    """Force logout a specific user (admin function)"""
    if user_id in security_manager.active_sessions:
        del security_manager.active_sessions[user_id]
        logger.info(f"Force logged out user {user_id}")
        return True
    return False

def unblock_user(user_id: int) -> bool:
    """Unblock a specific user (admin function)"""
    if user_id in security_manager.blocked_users:
        del security_manager.blocked_users[user_id]
        security_manager.failed_attempts[user_id].clear()
        logger.info(f"Unblocked user {user_id}")
        return True
    return False 