"""
Secure API handler for Bybit V5 API with enhanced security and error handling.
"""
import time
import hmac
import hashlib
import json
import logging
import os
from typing import Dict, Optional, Union, Any
import requests
from requests.adapters import HTTPAdapter

# Optional imports with fallbacks
try:
    from cryptography.fernet import Fernet
    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("cryptography package not available. API secrets will not be encrypted.")

try:
    from urllib3.util.retry import Retry
    URLLIB3_AVAILABLE = True
except ImportError:
    URLLIB3_AVAILABLE = False
    # Fallback retry class
    class Retry:
        def __init__(self, **kwargs):
            pass

logger = logging.getLogger(__name__)

# Custom exceptions for better error handling
class APIException(Exception):
    """Base API exception"""
    pass

class APIAuthenticationError(APIException):
    """Authentication related errors"""
    pass

class APIRateLimitError(APIException):
    """Rate limit exceeded"""
    pass

class APINetworkError(APIException):
    """Network related errors"""
    pass

class SecureAPIConfig:
    """Secure API configuration with encrypted credentials"""
    
    def __init__(self, api_key: str, api_secret: str, url: str = "https://api.bybit.com"):
        self.api_key = api_key
        self.url = url
        
        if CRYPTOGRAPHY_AVAILABLE:
            self._encryption_key = self._get_or_create_encryption_key()
            self._encrypted_secret = self._encrypt_secret(api_secret)
        else:
            # Fallback to plaintext storage with warning
            self._api_secret = api_secret
            logger.warning("API secret stored in plaintext. Install 'cryptography' package for encryption.")
            
        # Setup session with connection pooling and retries
        self.session = self._create_secure_session()
    
    def _get_or_create_encryption_key(self) -> bytes:
        """Get or create encryption key from environment"""
        if not CRYPTOGRAPHY_AVAILABLE:
            return b""
            
        key_env = os.getenv('API_ENCRYPTION_KEY')
        if key_env:
            return key_env.encode()
        
        # Generate new key if not exists (should be stored securely in production)
        new_key = Fernet.generate_key()
        logger.warning("Generated new encryption key. Store API_ENCRYPTION_KEY in environment!")
        return new_key
    
    def _encrypt_secret(self, secret: str) -> bytes:
        """Encrypt API secret"""
        if not CRYPTOGRAPHY_AVAILABLE:
            return secret.encode()
            
        f = Fernet(self._encryption_key)
        return f.encrypt(secret.encode())
    
    def _decrypt_secret(self) -> str:
        """Decrypt API secret"""
        if not CRYPTOGRAPHY_AVAILABLE:
            return self._api_secret
            
        f = Fernet(self._encryption_key)
        return f.decrypt(self._encrypted_secret).decode()
    
    def _create_secure_session(self) -> requests.Session:
        """Create session with security best practices"""
        session = requests.Session()
        
        if URLLIB3_AVAILABLE:
            # Retry strategy
            retry_strategy = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "POST"]
            )
            
            adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)
        else:
            adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
            
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Security headers
        session.headers.update({
            'User-Agent': 'Copytrader/2.0',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
        
        return session
    
    def get_api_secret(self) -> str:
        """Safely get decrypted API secret"""
        return self._decrypt_secret()

def create_api_config(config_data: Dict[str, Any]) -> SecureAPIConfig:
    """Create secure API configuration from config data"""
    try:
        api_key = config_data.get('api_key')
        api_secret = config_data.get('api_secret') 
        url = config_data.get('url', 'https://api.bybit.com')
        
        if not api_key or not api_secret:
            raise APIAuthenticationError("API key or secret missing from configuration")
            
        return SecureAPIConfig(api_key, api_secret, url)
    except Exception as e:
        logger.error(f"Failed to create API config: {e}", exc_info=True)
        raise APIException(f"API configuration error: {e}")

def make_api_request(
    api_config: SecureAPIConfig, 
    endpoint: str, 
    method: str = "POST", 
    params: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """
    Enhanced API request with security and error handling.
    
    Args:
        api_config: Secure API configuration
        endpoint: API endpoint path
        method: HTTP method (GET/POST)
        params: Request parameters
        
    Returns:
        API response data or None on error
        
    Raises:
        APIException: On various API errors
    """
    if params is None:
        params = {}
    
    try:
        timestamp = str(int(time.time() * 1000))
        recv_window = "20000"

        # Build query string
        if method == "GET":
            query_string = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
            data_to_sign = timestamp + api_config.api_key + recv_window + query_string
        else:  # POST
            query_string = json.dumps(params, separators=(',', ':'))
            data_to_sign = timestamp + api_config.api_key + recv_window + query_string

        # Create signature
        signature = hmac.new(
            bytes(api_config.get_api_secret(), "utf-8"),
            bytes(data_to_sign, "utf-8"),
            hashlib.sha256
        ).hexdigest()

        # Prepare headers
        headers = {
            'X-BAPI-API-KEY': api_config.api_key,
            'X-BAPI-TIMESTAMP': timestamp,
            'X-BAPI-RECV-WINDOW': recv_window,
            'X-BAPI-SIGN': signature,
            'Content-Type': 'application/json'
        }
        
        # Build URL
        url = f"{api_config.url}{endpoint}"
        if method == "GET" and query_string:
            url += "?" + query_string

        # Make request
        logger.debug(f"Making {method} request to {endpoint}")
        
        if method == "GET":
            response = api_config.session.get(url, headers=headers, timeout=30)
        else:
            response = api_config.session.post(url, headers=headers, data=query_string, timeout=30)
        
        # Handle HTTP errors
        if response.status_code == 429:
            raise APIRateLimitError("Rate limit exceeded")
        elif response.status_code == 401:
            raise APIAuthenticationError("Authentication failed")
        elif response.status_code >= 500:
            raise APINetworkError(f"Server error: {response.status_code}")
        
        response.raise_for_status()
        response_json = response.json()

        # Check Bybit API error codes
        ret_code = response_json.get('retCode', -1)
        if ret_code != 0:
            ret_msg = response_json.get('retMsg', 'Unknown error')
            logger.error(f"API error on {endpoint}: {ret_msg} (Code: {ret_code})")
            
            if ret_code in [10003, 10004]:  # Auth errors
                raise APIAuthenticationError(f"Authentication error: {ret_msg}")
            elif ret_code == 10006:  # Rate limit
                raise APIRateLimitError(f"Rate limit: {ret_msg}")
            else:
                raise APIException(f"API error {ret_code}: {ret_msg}")
            
        return response_json

    except requests.exceptions.Timeout:
        logger.error(f"Timeout on {endpoint}")
        raise APINetworkError(f"Request timeout on {endpoint}")
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error on {endpoint}: {e}")
        raise APINetworkError(f"Connection failed: {e}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error on {endpoint}: {e}")
        raise APINetworkError(f"Request failed: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error on {endpoint}: {e}")
        raise APIException(f"Invalid JSON response: {e}")
    except Exception as e:
        logger.error(f"Unexpected error on {endpoint}: {e}", exc_info=True)
        raise APIException(f"Unexpected error: {e}")

def get_data(
    api_config: SecureAPIConfig, 
    endpoint: str, 
    params: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """
    Simplified wrapper for GET requests.
    
    Returns the 'result' part of successful responses.
    """
    try:
        response = make_api_request(api_config, endpoint, method="GET", params=params)
        if response and response.get('retCode') == 0:
            return response.get('result', {})
        return None
    except APIException as e:
        logger.error(f"Failed to get data from {endpoint}: {e}")
        return None

def get_instrument_info(api_config: SecureAPIConfig, symbol: str) -> Optional[Dict[str, Any]]:
    """
    Get instrument information for a trading symbol.
    
    Args:
        api_config: Secure API configuration
        symbol: Trading symbol (e.g., 'BTCUSDT')
        
    Returns:
        Instrument data or None on error
    """
    logger.debug(f"Getting instrument info for: {symbol}")
    
    try:
        params = {
            'category': 'linear',
            'symbol': symbol
        }
        
        instrument_data = get_data(api_config, "/v5/market/instruments-info", params=params)
        
        if instrument_data and instrument_data.get('list'):
            return instrument_data['list'][0]
        else:
            logger.warning(f"No instrument data found for symbol: {symbol}")
            return None
            
    except APIException as e:
        logger.error(f"Failed to get instrument info for {symbol}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting instrument info for {symbol}: {e}", exc_info=True)
        return None
        