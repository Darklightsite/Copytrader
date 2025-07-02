"""
Copytrader v2 - Bybit V5 API Handler
Complete async API client with authentication, rate limiting, and error handling
"""
import asyncio
import aiohttp
import hmac
import hashlib
import time
import json
from typing import Dict, List, Optional, Any, Union
from decimal import Decimal
from urllib.parse import urlencode

from .exceptions import (
    APIError,
    APIConnectionError, 
    APIAuthenticationError,
    APIRateLimitError,
    APITimeoutError,
    APIResponseError,
    create_error_context
)
from .logger import get_logger, log_api_call
from .security import get_security_manager
from .file_utils import AccountConfig

class BybitAPIHandler:
    """
    Comprehensive Bybit V5 API handler with async support
    Handles authentication, rate limiting, retries, and error recovery
    """
    
    # Bybit V5 API endpoints
    ENDPOINTS = {
        # Account & Wallet
        'wallet_balance': '/v5/account/wallet-balance',
        'account_info': '/v5/account/info',
        
        # Trading
        'place_order': '/v5/order/create',
        'cancel_order': '/v5/order/cancel',
        'cancel_all_orders': '/v5/order/cancel-all',
        'modify_order': '/v5/order/amend',
        
        # Positions
        'position_list': '/v5/position/list',
        'set_leverage': '/v5/position/set-leverage',
        'trading_stop': '/v5/position/trading-stop',
        
        # Orders
        'open_orders': '/v5/order/realtime',
        'order_history': '/v5/order/history',
        'execution_list': '/v5/execution/list',
        
        # Market Data
        'instruments_info': '/v5/market/instruments-info',
        'orderbook': '/v5/market/orderbook',
        'recent_trades': '/v5/market/recent-trade',
        'kline': '/v5/market/kline',
        'tickers': '/v5/market/tickers',
        
        # Asset
        'coin_balance': '/v5/asset/transfer/query-inter-transfer-list'
    }
    
    def __init__(self, account_config: AccountConfig):
        self.account_config = account_config
        self.logger = get_logger('api')
        self.security_manager = get_security_manager()
        
        # Set context for this API handler
        self.logger.set_context(
            account=account_config.nickname,
            account_type=account_config.account_type
        )
        
        # Session configuration
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limit_delay = 0.1  # 100ms between requests
        self.max_retries = 3
        self.timeout = 30
        
        # Request tracking
        self.request_count = 0
        self.last_request_time = 0
        
    async def __aenter__(self):
        """Async context manager entry"""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
    
    async def initialize(self):
        """Initialize the API handler"""
        try:
            # Create aiohttp session with custom connector
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            connector = aiohttp.TCPConnector(
                limit=10,  # Maximum pool size
                limit_per_host=5,  # Maximum pool size per host
                ttl_dns_cache=300,  # DNS cache TTL
                use_dns_cache=True,
            )
            
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': 'Copytrader-v2/1.0'
                }
            )
            
            self.logger.info("API handler initialized", url=self.account_config.url)
            
        except Exception as e:
            self.logger.error(f"Failed to initialize API handler: {e}", exc_info=True)
            raise APIConnectionError(f"Failed to initialize API handler: {e}")
    
    async def close(self):
        """Close the API handler and cleanup resources"""
        if self.session:
            await self.session.close()
            self.session = None
        
        self.logger.info("API handler closed")
    
    def _generate_signature(self, timestamp: str, params: str) -> str:
        """Generate API signature for authentication"""
        try:
            recv_window = "5000"  # 5 second window
            param_str = timestamp + self.account_config.api_key + recv_window + params
            
            signature = hmac.new(
                bytes(self.account_config.api_secret, "utf-8"),
                bytes(param_str, "utf-8"),
                hashlib.sha256
            ).hexdigest()
            
            return signature
        except Exception as e:
            raise APIAuthenticationError(f"Failed to generate signature: {e}")
    
    def _prepare_headers(self, timestamp: str, signature: str) -> Dict[str, str]:
        """Prepare authentication headers"""
        return {
            'X-BAPI-API-KEY': self.account_config.api_key,
            'X-BAPI-TIMESTAMP': timestamp,
            'X-BAPI-RECV-WINDOW': "5000",
            'X-BAPI-SIGN': signature,
            'Content-Type': 'application/json'
        }
    
    async def _rate_limit_check(self):
        """Implement rate limiting"""
        now = time.time()
        if now - self.last_request_time < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - (now - self.last_request_time)
            await asyncio.sleep(sleep_time)
        
        self.last_request_time = time.time()
        self.request_count += 1
        
        # Check security manager rate limits
        try:
            self.security_manager.check_rate_limit(
                f"api_{self.account_config.nickname}",
                "api_call"
            )
        except Exception as e:
            self.logger.warning(f"Rate limit check failed: {e}")
    
    async def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None,
        retry_count: int = 0
    ) -> Dict[str, Any]:
        """Make authenticated API request with retries"""
        
        if not self.session:
            await self.initialize()
        
        # Rate limiting
        await self._rate_limit_check()
        
        # Prepare parameters
        if params is None:
            params = {}
        
        timestamp = str(int(time.time() * 1000))
        
        try:
            if method.upper() == 'GET':
                query_string = urlencode(sorted(params.items())) if params else ""
                signature = self._generate_signature(timestamp, query_string)
                url = f"{self.account_config.url}{endpoint}"
                if query_string:
                    url += f"?{query_string}"
                headers = self._prepare_headers(timestamp, signature)
                
                log_api_call(self.logger, endpoint, method, None, **params)
                
                async with self.session.get(url, headers=headers) as response:
                    return await self._process_response(response, endpoint, method)
            
            else:  # POST, PUT, DELETE
                json_params = json.dumps(params, separators=(',', ':'))
                signature = self._generate_signature(timestamp, json_params)
                url = f"{self.account_config.url}{endpoint}"
                headers = self._prepare_headers(timestamp, signature)
                
                log_api_call(self.logger, endpoint, method, None, **params)
                
                async with self.session.request(
                    method, url, data=json_params, headers=headers
                ) as response:
                    return await self._process_response(response, endpoint, method)
                    
        except aiohttp.ClientError as e:
            if retry_count < self.max_retries:
                self.logger.warning(f"Request failed, retrying {retry_count + 1}/{self.max_retries}: {e}")
                await asyncio.sleep(2 ** retry_count)  # Exponential backoff
                return await self._make_request(method, endpoint, params, retry_count + 1)
            else:
                raise APIConnectionError(f"Network error after {self.max_retries} retries: {e}")
        
        except asyncio.TimeoutError:
            if retry_count < self.max_retries:
                self.logger.warning(f"Request timeout, retrying {retry_count + 1}/{self.max_retries}")
                await asyncio.sleep(2 ** retry_count)
                return await self._make_request(method, endpoint, params, retry_count + 1)
            else:
                raise APITimeoutError(f"Request timeout after {self.max_retries} retries")
        
        except Exception as e:
            context = create_error_context(
                operation=f"{method} {endpoint}",
                account=self.account_config.nickname,
                endpoint=endpoint
            )
            self.logger.error(f"Unexpected error in API request: {e}", extra=context, exc_info=True)
            raise APIError(f"Unexpected error: {e}")
    
    async def _process_response(
        self, 
        response: aiohttp.ClientResponse, 
        endpoint: str, 
        method: str
    ) -> Dict[str, Any]:
        """Process API response and handle errors"""
        
        log_api_call(self.logger, endpoint, method, response.status)
        
        # Handle HTTP errors
        if response.status == 401:
            raise APIAuthenticationError("Authentication failed - check API credentials")
        elif response.status == 403:
            raise APIAuthenticationError("Access forbidden - insufficient permissions")
        elif response.status == 429:
            raise APIRateLimitError("Rate limit exceeded")
        elif response.status >= 500:
            raise APIConnectionError(f"Server error: {response.status}")
        elif response.status >= 400:
            error_text = await response.text()
            raise APIResponseError(f"Client error {response.status}: {error_text}")
        
        # Parse JSON response
        try:
            data = await response.json()
        except json.JSONDecodeError as e:
            raise APIResponseError(f"Invalid JSON response: {e}")
        
        # Check Bybit API error codes
        ret_code = data.get('retCode', 0)
        if ret_code != 0:
            ret_msg = data.get('retMsg', 'Unknown error')
            
            # Map specific Bybit error codes
            if ret_code in [10003, 10004, 33004]:  # Auth errors
                raise APIAuthenticationError(f"Authentication error: {ret_msg}")
            elif ret_code == 10006:  # Rate limit
                raise APIRateLimitError(f"Rate limit: {ret_msg}")
            elif ret_code in [110001, 110003, 110004]:  # Order errors
                self.logger.warning(f"Order execution error {ret_code}: {ret_msg}")
                # Don't raise exception for order errors, return the response
                return data
            else:
                raise APIError(f"Bybit API error {ret_code}: {ret_msg}")
        
        return data
    
    # Public API methods
    
    async def get_wallet_balance(self, account_type: str = "UNIFIED") -> Dict[str, Any]:
        """Get wallet balance"""
        params = {"accountType": account_type}
        response = await self._make_request('GET', self.ENDPOINTS['wallet_balance'], params)
        return response.get('result', {})
    
    async def get_positions(self, category: str = "linear", symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get positions"""
        params = {"category": category}
        if symbol:
            params["symbol"] = symbol
        
        response = await self._make_request('GET', self.ENDPOINTS['position_list'], params)
        return response.get('result', {}).get('list', [])
    
    async def get_open_orders(self, category: str = "linear", symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get open orders"""
        params = {"category": category}
        if symbol:
            params["symbol"] = symbol
        
        response = await self._make_request('GET', self.ENDPOINTS['open_orders'], params)
        return response.get('result', {}).get('list', [])
    
    async def get_order_history(
        self, 
        category: str = "linear", 
        symbol: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get order history"""
        params = {
            "category": category,
            "limit": str(limit)
        }
        if symbol:
            params["symbol"] = symbol
        
        response = await self._make_request('GET', self.ENDPOINTS['order_history'], params)
        return response.get('result', {}).get('list', [])
    
    async def get_execution_list(
        self,
        category: str = "linear",
        symbol: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get execution/trade history"""
        params = {
            "category": category,
            "limit": str(limit)
        }
        if symbol:
            params["symbol"] = symbol
        
        response = await self._make_request('GET', self.ENDPOINTS['execution_list'], params)
        return response.get('result', {}).get('list', [])
    
    async def place_order(
        self,
        category: str,
        symbol: str,
        side: str,
        order_type: str,
        qty: str,
        price: Optional[str] = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
        close_on_trigger: bool = False
    ) -> Dict[str, Any]:
        """Place a new order"""
        params = {
            "category": category,
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": qty,
            "timeInForce": time_in_force
        }
        
        if price:
            params["price"] = price
        if reduce_only:
            params["reduceOnly"] = "true"
        if close_on_trigger:
            params["closeOnTrigger"] = "true"
        
        response = await self._make_request('POST', self.ENDPOINTS['place_order'], params)
        return response.get('result', {})
    
    async def cancel_order(
        self,
        category: str,
        symbol: str,
        order_id: Optional[str] = None,
        order_link_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Cancel an order"""
        params = {
            "category": category,
            "symbol": symbol
        }
        
        if order_id:
            params["orderId"] = order_id
        elif order_link_id:
            params["orderLinkId"] = order_link_id
        else:
            raise ValueError("Either order_id or order_link_id must be provided")
        
        response = await self._make_request('POST', self.ENDPOINTS['cancel_order'], params)
        return response.get('result', {})
    
    async def cancel_all_orders(self, category: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Cancel all orders"""
        params = {"category": category}
        if symbol:
            params["symbol"] = symbol
        
        response = await self._make_request('POST', self.ENDPOINTS['cancel_all_orders'], params)
        return response.get('result', {})
    
    async def set_leverage(
        self,
        category: str,
        symbol: str,
        buy_leverage: str,
        sell_leverage: str
    ) -> Dict[str, Any]:
        """Set leverage for a symbol"""
        params = {
            "category": category,
            "symbol": symbol,
            "buyLeverage": buy_leverage,
            "sellLeverage": sell_leverage
        }
        
        response = await self._make_request('POST', self.ENDPOINTS['set_leverage'], params)
        return response.get('result', {})
    
    async def set_trading_stop(
        self,
        category: str,
        symbol: str,
        position_idx: int = 0,
        stop_loss: Optional[str] = None,
        take_profit: Optional[str] = None,
        tpsl_mode: str = "Full"
    ) -> Dict[str, Any]:
        """Set stop loss and take profit"""
        params = {
            "category": category,
            "symbol": symbol,
            "positionIdx": position_idx,
            "tpslMode": tpsl_mode
        }
        
        if stop_loss:
            params["stopLoss"] = stop_loss
        if take_profit:
            params["takeProfit"] = take_profit
        
        response = await self._make_request('POST', self.ENDPOINTS['trading_stop'], params)
        return response.get('result', {})
    
    async def get_instruments_info(
        self,
        category: str = "linear",
        symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get instruments info"""
        params = {"category": category}
        if symbol:
            params["symbol"] = symbol
        
        response = await self._make_request('GET', self.ENDPOINTS['instruments_info'], params)
        return response.get('result', {}).get('list', [])
    
    async def get_orderbook(self, category: str, symbol: str, limit: int = 25) -> Dict[str, Any]:
        """Get orderbook data"""
        params = {
            "category": category,
            "symbol": symbol,
            "limit": str(limit)
        }
        
        response = await self._make_request('GET', self.ENDPOINTS['orderbook'], params)
        return response.get('result', {})
    
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information"""
        response = await self._make_request('GET', self.ENDPOINTS['account_info'])
        return response.get('result', {})
    
    # Utility methods
    
    async def health_check(self) -> bool:
        """Perform health check on API connection"""
        try:
            await self.get_account_info()
            self.logger.info("API health check passed")
            return True
        except Exception as e:
            self.logger.error(f"API health check failed: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get API usage statistics"""
        return {
            "request_count": self.request_count,
            "account": self.account_config.nickname,
            "account_type": self.account_config.account_type,
            "url": self.account_config.url,
            "session_active": self.session is not None
        }