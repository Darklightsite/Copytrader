"""
Copytrader v2 - Security Manager
Comprehensive security system with encryption, rate limiting, and validation
"""
import os
import hashlib
import hmac
import secrets
import base64
from typing import Dict, Optional, Any, List, Union
from datetime import datetime, timedelta
import re
from pathlib import Path
import json

from .exceptions import (
    SecurityError, 
    EncryptionError, 
    ValidationError, 
    RateLimitExceededError,
    create_error_context
)
from .logger import get_logger

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False

class EncryptionManager:
    """Manages encryption and decryption of sensitive data"""
    
    def __init__(self):
        self.logger = get_logger('security')
        self._encryption_key = None
        
        if CRYPTOGRAPHY_AVAILABLE:
            self._initialize_encryption()
        else:
            self.logger.warning("Cryptography not available - sensitive data will not be encrypted")
    
    def _initialize_encryption(self):
        """Initialize encryption key from environment or generate new one"""
        # Try to get key from environment
        env_key = os.getenv('COPYTRADER_ENCRYPTION_KEY')
        
        if env_key:
            try:
                # Validate and use existing key
                key_bytes = base64.urlsafe_b64decode(env_key.encode())
                self._encryption_key = Fernet(key_bytes)
                self.logger.info("Loaded encryption key from environment")
                return
            except Exception as e:
                self.logger.error(f"Invalid encryption key in environment: {e}")
        
        # Generate new key
        key = Fernet.generate_key()
        self._encryption_key = Fernet(key)
        
        # Save to environment file
        self._save_key_to_env(key)
        
        self.logger.warning("Generated new encryption key - save COPYTRADER_ENCRYPTION_KEY to environment")
    
    def _save_key_to_env(self, key: bytes):
        """Save encryption key to .env file"""
        try:
            env_file = Path('.env')
            key_line = f"COPYTRADER_ENCRYPTION_KEY={key.decode()}\n"
            
            if env_file.exists():
                # Update existing .env file
                lines = env_file.read_text().splitlines()
                updated = False
                
                for i, line in enumerate(lines):
                    if line.startswith('COPYTRADER_ENCRYPTION_KEY='):
                        lines[i] = key_line.strip()
                        updated = True
                        break
                
                if not updated:
                    lines.append(key_line.strip())
                
                env_file.write_text('\n'.join(lines) + '\n')
            else:
                # Create new .env file
                env_file.write_text(key_line)
                
        except Exception as e:
            self.logger.error(f"Failed to save encryption key to .env: {e}")
    
    def encrypt(self, data: str) -> str:
        """Encrypt sensitive data"""
        if not CRYPTOGRAPHY_AVAILABLE or not self._encryption_key:
            return data  # Return plaintext if encryption not available
        
        try:
            encrypted_bytes = self._encryption_key.encrypt(data.encode())
            return base64.urlsafe_b64encode(encrypted_bytes).decode()
        except Exception as e:
            raise EncryptionError(f"Failed to encrypt data: {e}")
    
    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt sensitive data"""
        if not CRYPTOGRAPHY_AVAILABLE or not self._encryption_key:
            return encrypted_data  # Return as-is if encryption not available
        
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
            decrypted_bytes = self._encryption_key.decrypt(encrypted_bytes)
            return decrypted_bytes.decode()
        except Exception as e:
            raise EncryptionError(f"Failed to decrypt data: {e}")
    
    def hash_sensitive_data(self, data: str, salt: Optional[str] = None) -> str:
        """Create secure hash of sensitive data"""
        if salt is None:
            salt = secrets.token_hex(16)
        
        # Use PBKDF2 for secure hashing
        hash_func = hashlib.pbkdf2_hmac('sha256', data.encode(), salt.encode(), 100000)
        return f"{salt}${base64.urlsafe_b64encode(hash_func).decode()}"
    
    def verify_hash(self, data: str, hashed_data: str) -> bool:
        """Verify data against secure hash"""
        try:
            salt, hash_value = hashed_data.split('$', 1)
            expected_hash = self.hash_sensitive_data(data, salt)
            return hmac.compare_digest(expected_hash, hashed_data)
        except Exception:
            return False

class RateLimiter:
    """Rate limiting for API calls and user actions"""
    
    def __init__(self):
        self.logger = get_logger('security')
        self.request_history: Dict[str, List[datetime]] = {}
        self.blocked_until: Dict[str, datetime] = {}
    
    def is_allowed(self, identifier: str, max_requests: int = 10, window_minutes: int = 1) -> bool:
        """Check if request is allowed within rate limits"""
        now = datetime.now()
        
        # Check if currently blocked
        if identifier in self.blocked_until:
            if now < self.blocked_until[identifier]:
                return False
            else:
                del self.blocked_until[identifier]
        
        # Clean old requests
        if identifier not in self.request_history:
            self.request_history[identifier] = []
        
        cutoff_time = now - timedelta(minutes=window_minutes)
        self.request_history[identifier] = [
            req_time for req_time in self.request_history[identifier]
            if req_time > cutoff_time
        ]
        
        # Check rate limit
        if len(self.request_history[identifier]) >= max_requests:
            # Block for escalating time based on violations
            block_minutes = min(60, len(self.request_history[identifier]) - max_requests + 5)
            self.blocked_until[identifier] = now + timedelta(minutes=block_minutes)
            
            self.logger.warning(f"Rate limit exceeded for {identifier}, blocked for {block_minutes} minutes")
            return False
        
        # Record this request
        self.request_history[identifier].append(now)
        return True
    
    def reset_limits(self, identifier: str):
        """Reset rate limits for identifier"""
        self.request_history.pop(identifier, None)
        self.blocked_until.pop(identifier, None)
    
    def get_remaining_requests(self, identifier: str, max_requests: int = 10, window_minutes: int = 1) -> int:
        """Get remaining requests in current window"""
        if not self.is_allowed(identifier, max_requests, window_minutes):
            return 0
        
        return max_requests - len(self.request_history.get(identifier, []))

class InputValidator:
    """Validates and sanitizes user inputs"""
    
    def __init__(self):
        self.logger = get_logger('security')
    
    def validate_api_key(self, api_key: str) -> bool:
        """Validate API key format"""
        if not api_key or not isinstance(api_key, str):
            return False
        
        # Basic format validation (adjust based on Bybit API key format)
        if len(api_key) < 20 or len(api_key) > 50:
            return False
        
        # Should contain only alphanumeric characters and hyphens
        if not re.match(r'^[A-Za-z0-9\-_]+$', api_key):
            return False
        
        return True
    
    def validate_api_secret(self, api_secret: str) -> bool:
        """Validate API secret format"""
        if not api_secret or not isinstance(api_secret, str):
            return False
        
        # Basic format validation
        if len(api_secret) < 20 or len(api_secret) > 100:
            return False
        
        # Should contain only alphanumeric characters and special chars
        if not re.match(r'^[A-Za-z0-9\-_=+/]+$', api_secret):
            return False
        
        return True
    
    def validate_url(self, url: str) -> bool:
        """Validate URL format"""
        if not url or not isinstance(url, str):
            return False
        
        # Must be HTTPS for security
        if not url.startswith('https://'):
            return False
        
        # Basic URL pattern
        url_pattern = r'^https://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(/.*)?$'
        if not re.match(url_pattern, url):
            return False
        
        return True
    
    def validate_symbol(self, symbol: str) -> bool:
        """Validate trading symbol"""
        if not symbol or not isinstance(symbol, str):
            return False
        
        # Symbol should be uppercase letters/numbers
        if not re.match(r'^[A-Z0-9]{3,20}$', symbol):
            return False
        
        return True
    
    def validate_quantity(self, quantity: Union[str, float, int]) -> bool:
        """Validate trading quantity"""
        try:
            qty = float(quantity)
            return qty > 0 and qty < 1000000  # Reasonable bounds
        except (ValueError, TypeError):
            return False
    
    def validate_telegram_id(self, telegram_id: Union[str, int]) -> bool:
        """Validate Telegram user ID"""
        try:
            tid = int(telegram_id)
            return tid > 0 and tid < 10**12  # Reasonable bounds for Telegram IDs
        except (ValueError, TypeError):
            return False
    
    def sanitize_string(self, text: str, max_length: int = 1000) -> str:
        """Sanitize string input"""
        if not isinstance(text, str):
            return ""
        
        # Remove potentially dangerous characters
        sanitized = re.sub(r'[<>"\'\\/]', '', text)
        
        # Limit length
        return sanitized[:max_length]
    
    def validate_account_config(self, config: Dict[str, Any]) -> List[str]:
        """Validate complete account configuration"""
        errors = []
        
        # Validate API credentials
        if not self.validate_api_key(config.get('api_key', '')):
            errors.append("Invalid API key format")
        
        if not self.validate_api_secret(config.get('api_secret', '')):
            errors.append("Invalid API secret format")
        
        if not self.validate_url(config.get('url', '')):
            errors.append("Invalid URL format (must be HTTPS)")
        
        # Validate telegram ID if present
        if 'telegram_id' in config and config['telegram_id'] is not None:
            if not self.validate_telegram_id(config['telegram_id']):
                errors.append("Invalid Telegram ID")
        
        # Validate symbols if present
        if 'symbols_to_copy' in config and config['symbols_to_copy']:
            for symbol in config['symbols_to_copy']:
                if not self.validate_symbol(symbol):
                    errors.append(f"Invalid symbol format: {symbol}")
        
        return errors

class SecurityManager:
    """Main security manager coordinating all security components"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, 'initialized'):
            return
            
        self.logger = get_logger('security')
        self.encryption_manager = EncryptionManager()
        self.rate_limiter = RateLimiter()
        self.input_validator = InputValidator()
        self.initialized = True
    
    @classmethod
    def initialize(cls):
        """Initialize security manager"""
        instance = cls()
        instance.logger.info("Security manager initialized")
        return instance
    
    def encrypt_sensitive_data(self, data: str) -> str:
        """Encrypt sensitive data"""
        return self.encryption_manager.encrypt(data)
    
    def decrypt_sensitive_data(self, encrypted_data: str) -> str:
        """Decrypt sensitive data"""
        return self.encryption_manager.decrypt(encrypted_data)
    
    def check_rate_limit(self, identifier: str, operation: str = "api_call") -> bool:
        """Check if operation is within rate limits"""
        # Different limits for different operations
        limits = {
            "api_call": (10, 1),  # 10 calls per minute
            "telegram_command": (20, 5),  # 20 commands per 5 minutes
            "login_attempt": (5, 15),  # 5 attempts per 15 minutes
        }
        
        max_requests, window_minutes = limits.get(operation, (10, 1))
        
        if not self.rate_limiter.is_allowed(identifier, max_requests, window_minutes):
            raise RateLimitExceededError(f"Rate limit exceeded for {operation}")
        
        return True
    
    def validate_input(self, input_type: str, value: Any) -> bool:
        """Validate input based on type"""
        validators = {
            'api_key': self.input_validator.validate_api_key,
            'api_secret': self.input_validator.validate_api_secret,
            'url': self.input_validator.validate_url,
            'symbol': self.input_validator.validate_symbol,
            'quantity': self.input_validator.validate_quantity,
            'telegram_id': self.input_validator.validate_telegram_id,
        }
        
        validator = validators.get(input_type)
        if not validator:
            raise ValidationError(f"Unknown input type: {input_type}")
        
        if not validator(value):
            raise ValidationError(f"Invalid {input_type}: {value}")
        
        return True
    
    def sanitize_for_logging(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize data for safe logging (remove sensitive info)"""
        sensitive_keys = [
            'api_key', 'api_secret', 'password', 'token', 'secret',
            'private_key', 'auth_token', 'session_id'
        ]
        
        sanitized = {}
        for key, value in data.items():
            if any(sensitive_key in key.lower() for sensitive_key in sensitive_keys):
                if isinstance(value, str) and len(value) > 4:
                    sanitized[key] = f"{value[:4]}...{value[-4:]}"
                else:
                    sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = value
        
        return sanitized
    
    def generate_session_token(self) -> str:
        """Generate secure session token"""
        return secrets.token_urlsafe(32)
    
    def validate_session_token(self, token: str) -> bool:
        """Validate session token format"""
        if not isinstance(token, str):
            return False
        
        # Should be URL-safe base64
        try:
            decoded = base64.urlsafe_b64decode(token + '==')
            return len(decoded) >= 24  # At least 24 bytes of entropy
        except Exception:
            return False
    
    def create_signature(self, data: str, secret: str) -> str:
        """Create HMAC signature for data verification"""
        return hmac.new(
            secret.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()
    
    def verify_signature(self, data: str, signature: str, secret: str) -> bool:
        """Verify HMAC signature"""
        expected_signature = self.create_signature(data, secret)
        return hmac.compare_digest(expected_signature, signature)
    
    def get_security_report(self) -> Dict[str, Any]:
        """Get security status report"""
        return {
            "encryption_available": CRYPTOGRAPHY_AVAILABLE,
            "active_rate_limits": len(self.rate_limiter.blocked_until),
            "recent_requests": sum(len(reqs) for reqs in self.rate_limiter.request_history.values()),
            "timestamp": datetime.now().isoformat()
        }

# Global security manager instance
def get_security_manager() -> SecurityManager:
    """Get global security manager instance"""
    return SecurityManager.initialize()