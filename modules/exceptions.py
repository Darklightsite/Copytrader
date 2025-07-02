"""
Custom exceptions for the Copytrader system.
Provides specific exception types for better error handling and debugging.
"""
from typing import Optional, Dict, Any


class CopytraderException(Exception):
    """Base exception for all Copytrader-related errors"""
    
    def __init__(self, message: str, error_code: Optional[str] = None, context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.context = context or {}
    
    def __str__(self) -> str:
        parts = [self.message]
        if self.error_code:
            parts.append(f"Code: {self.error_code}")
        if self.context:
            parts.append(f"Context: {self.context}")
        return " | ".join(parts)


# Configuration related exceptions
class ConfigurationError(CopytraderException):
    """Raised when there are configuration-related issues"""
    pass


class MissingConfigurationError(ConfigurationError):
    """Raised when required configuration is missing"""
    pass


class InvalidConfigurationError(ConfigurationError):
    """Raised when configuration values are invalid"""
    pass


# API related exceptions  
class APIError(CopytraderException):
    """Base class for API-related errors"""
    pass


class APIAuthenticationError(APIError):
    """Raised when API authentication fails"""
    pass


class APIRateLimitError(APIError):
    """Raised when API rate limits are exceeded"""
    pass


class APINetworkError(APIError):
    """Raised when network-related API errors occur"""
    pass


class APIResponseError(APIError):
    """Raised when API returns unexpected response format"""
    pass


# Trading related exceptions
class TradingError(CopytraderException):
    """Base class for trading-related errors"""
    pass


class OrderExecutionError(TradingError):
    """Raised when order execution fails"""
    pass


class InsufficientBalanceError(TradingError):
    """Raised when account has insufficient balance"""
    pass


class InvalidPositionError(TradingError):
    """Raised when position operations are invalid"""
    pass


class RiskManagementError(TradingError):
    """Raised when risk management rules are violated"""
    pass


# Synchronization related exceptions
class SynchronizationError(CopytraderException):
    """Base class for synchronization-related errors"""
    pass


class PositionSyncError(SynchronizationError):
    """Raised when position synchronization fails"""
    pass


class DataSyncError(SynchronizationError):
    """Raised when data synchronization fails"""
    pass


# Authentication related exceptions
class AuthenticationError(CopytraderException):
    """Base class for authentication-related errors"""
    pass


class UnauthorizedAccessError(AuthenticationError):
    """Raised when unauthorized access is attempted"""
    pass


class SessionExpiredError(AuthenticationError):
    """Raised when user session has expired"""
    pass


class RateLimitExceededError(AuthenticationError):
    """Raised when rate limits are exceeded"""
    pass


# Telegram related exceptions
class TelegramError(CopytraderException):
    """Base class for Telegram-related errors"""
    pass


class TelegramBotError(TelegramError):
    """Raised when Telegram bot operations fail"""
    pass


class TelegramMessageError(TelegramError):
    """Raised when Telegram message operations fail"""
    pass


# Data related exceptions
class DataError(CopytraderException):
    """Base class for data-related errors"""
    pass


class DataValidationError(DataError):
    """Raised when data validation fails"""
    pass


class DataSerializationError(DataError):
    """Raised when data serialization/deserialization fails"""
    pass


class FileOperationError(DataError):
    """Raised when file operations fail"""
    pass


# Recovery strategies
class RecoveryError(CopytraderException):
    """Raised when error recovery fails"""
    pass


def handle_exception_with_context(
    exception: Exception, 
    context: Dict[str, Any], 
    logger=None
) -> CopytraderException:
    """
    Convert a generic exception to a Copytrader-specific exception with context.
    
    Args:
        exception: The original exception
        context: Additional context information
        logger: Optional logger instance
        
    Returns:
        CopytraderException with context
    """
    error_message = str(exception)
    error_type = type(exception).__name__
    
    # Map common exceptions to specific Copytrader exceptions
    exception_mapping = {
        'ConnectionError': APINetworkError,
        'TimeoutError': APINetworkError,
        'ValueError': DataValidationError,
        'KeyError': ConfigurationError,
        'FileNotFoundError': FileOperationError,
        'PermissionError': FileOperationError,
        'JSONDecodeError': DataSerializationError,
    }
    
    exception_class = exception_mapping.get(error_type, CopytraderException)
    
    # Create new exception with context
    new_exception = exception_class(
        message=f"{error_type}: {error_message}",
        error_code=error_type,
        context=context
    )
    
    if logger:
        logger.error(f"Exception converted: {new_exception}", exc_info=True)
    
    return new_exception


def create_error_context(
    operation: str,
    user_id: Optional[int] = None,
    symbol: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Create standardized error context dictionary.
    
    Args:
        operation: The operation being performed
        user_id: Optional user ID
        symbol: Optional trading symbol
        **kwargs: Additional context fields
        
    Returns:
        Context dictionary
    """
    context = {
        'operation': operation,
        'timestamp': __import__('datetime').datetime.now().isoformat()
    }
    
    if user_id is not None:
        context['user_id'] = user_id
    if symbol is not None:
        context['symbol'] = symbol
        
    context.update(kwargs)
    return context