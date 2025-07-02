"""
Unit tests for the API handler module.
"""
try:
    import pytest
    PYTEST_AVAILABLE = True
except ImportError:
    PYTEST_AVAILABLE = False
    # Mock pytest for when it's not available
    class pytest:
        @staticmethod
        def raises(*args, **kwargs):
            class ContextManager:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
            return ContextManager()
        
        class mark:
            @staticmethod
            def integration(func):
                return func
        
        @staticmethod
        def fixture(func):
            return func

from unittest.mock import Mock, patch, MagicMock
import json
import time
from modules.api_handler import (
    SecureAPIConfig, 
    make_api_request, 
    get_data, 
    get_instrument_info,
    create_api_config,
    APIException,
    APIAuthenticationError,
    APIRateLimitError,
    APINetworkError
)


class TestSecureAPIConfig:
    """Tests for SecureAPIConfig class"""
    
    def test_init_basic(self):
        """Test basic initialization"""
        config = SecureAPIConfig("test_key", "test_secret")
        assert config.api_key == "test_key"
        assert config.url == "https://api.bybit.com"
        
    def test_init_custom_url(self):
        """Test initialization with custom URL"""
        custom_url = "https://api-testnet.bybit.com"
        config = SecureAPIConfig("test_key", "test_secret", custom_url)
        assert config.url == custom_url
    
    @patch.dict('os.environ', {'API_ENCRYPTION_KEY': 'test_key'})
    def test_encryption_with_env_key(self):
        """Test encryption when environment key is available"""
        with patch('modules.api_handler.CRYPTOGRAPHY_AVAILABLE', True):
            with patch('modules.api_handler.Fernet') as mock_fernet:
                mock_cipher = Mock()
                mock_fernet.return_value = mock_cipher
                mock_cipher.encrypt.return_value = b'encrypted_secret'
                
                config = SecureAPIConfig("test_key", "test_secret")
                assert hasattr(config, '_encrypted_secret')
    
    def test_fallback_without_cryptography(self):
        """Test fallback when cryptography is not available"""
        with patch('modules.api_handler.CRYPTOGRAPHY_AVAILABLE', False):
            config = SecureAPIConfig("test_key", "test_secret")
            assert config._api_secret == "test_secret"


class TestCreateAPIConfig:
    """Tests for create_api_config function"""
    
    def test_create_valid_config(self):
        """Test creating valid API config"""
        config_data = {
            'api_key': 'test_key',
            'api_secret': 'test_secret',
            'url': 'https://api.bybit.com'
        }
        
        api_config = create_api_config(config_data)
        assert api_config.api_key == 'test_key'
        assert api_config.url == 'https://api.bybit.com'
    
    def test_create_config_missing_key(self):
        """Test creating config with missing API key"""
        config_data = {
            'api_secret': 'test_secret'
        }
        
        with pytest.raises(APIException):
            create_api_config(config_data)
    
    def test_create_config_missing_secret(self):
        """Test creating config with missing API secret"""
        config_data = {
            'api_key': 'test_key'
        }
        
        with pytest.raises(APIException):
            create_api_config(config_data)


class TestMakeAPIRequest:
    """Tests for make_api_request function"""
    
    def setup_method(self):
        """Setup for each test"""
        self.api_config = SecureAPIConfig("test_key", "test_secret")
    
    @patch('modules.api_handler.time.time')
    def test_signature_generation(self, mock_time):
        """Test that signature is generated correctly"""
        mock_time.return_value = 1640995200.0  # Fixed timestamp
        
        with patch.object(self.api_config.session, 'post') as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {'retCode': 0, 'result': {}}
            mock_post.return_value = mock_response
            
            result = make_api_request(
                self.api_config, 
                '/v5/order/create', 
                'POST', 
                {'symbol': 'BTCUSDT'}
            )
            
            # Verify the request was made
            assert mock_post.called
            call_args = mock_post.call_args
            
            # Check headers contain required fields
            headers = call_args[1]['headers']
            assert 'X-BAPI-API-KEY' in headers
            assert 'X-BAPI-TIMESTAMP' in headers
            assert 'X-BAPI-SIGN' in headers
            assert headers['X-BAPI-API-KEY'] == 'test_key'
    
    def test_successful_post_request(self):
        """Test successful POST request"""
        with patch.object(self.api_config.session, 'post') as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'retCode': 0,
                'result': {'orderId': '12345'}
            }
            mock_post.return_value = mock_response
            
            result = make_api_request(
                self.api_config,
                '/v5/order/create',
                'POST',
                {'symbol': 'BTCUSDT', 'side': 'Buy'}
            )
            
            assert result['retCode'] == 0
            assert result['result']['orderId'] == '12345'
    
    def test_successful_get_request(self):
        """Test successful GET request"""
        with patch.object(self.api_config.session, 'get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'retCode': 0,
                'result': {'list': []}
            }
            mock_get.return_value = mock_response
            
            result = make_api_request(
                self.api_config,
                '/v5/position/list',
                'GET',
                {'category': 'linear'}
            )
            
            assert result['retCode'] == 0
            assert 'result' in result
    
    def test_api_error_handling(self):
        """Test API error handling"""
        with patch.object(self.api_config.session, 'post') as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'retCode': 10001,
                'retMsg': 'API key invalid'
            }
            mock_post.return_value = mock_response
            
            with pytest.raises(APIException):
                make_api_request(
                    self.api_config,
                    '/v5/order/create',
                    'POST',
                    {'symbol': 'BTCUSDT'}
                )
    
    def test_authentication_error(self):
        """Test authentication error handling"""
        with patch.object(self.api_config.session, 'post') as mock_post:
            mock_response = Mock()
            mock_response.status_code = 401
            mock_post.return_value = mock_response
            
            with pytest.raises(APIAuthenticationError):
                make_api_request(
                    self.api_config,
                    '/v5/order/create',
                    'POST',
                    {'symbol': 'BTCUSDT'}
                )
    
    def test_rate_limit_error(self):
        """Test rate limit error handling"""
        with patch.object(self.api_config.session, 'post') as mock_post:
            mock_response = Mock()
            mock_response.status_code = 429
            mock_post.return_value = mock_response
            
            with pytest.raises(APIRateLimitError):
                make_api_request(
                    self.api_config,
                    '/v5/order/create',
                    'POST',
                    {'symbol': 'BTCUSDT'}
                )
    
    def test_network_error(self):
        """Test network error handling"""
        with patch.object(self.api_config.session, 'post') as mock_post:
            mock_post.side_effect = Exception("Connection failed")
            
            with pytest.raises(APIException):
                make_api_request(
                    self.api_config,
                    '/v5/order/create',
                    'POST',
                    {'symbol': 'BTCUSDT'}
                )


class TestGetData:
    """Tests for get_data function"""
    
    def setup_method(self):
        """Setup for each test"""
        self.api_config = SecureAPIConfig("test_key", "test_secret")
    
    @patch('modules.api_handler.make_api_request')
    def test_successful_get_data(self, mock_make_request):
        """Test successful data retrieval"""
        mock_make_request.return_value = {
            'retCode': 0,
            'result': {'list': [{'symbol': 'BTCUSDT'}]}
        }
        
        result = get_data(self.api_config, '/v5/position/list', {'category': 'linear'})
        
        assert result is not None
        assert 'list' in result
        assert result['list'][0]['symbol'] == 'BTCUSDT'
    
    @patch('modules.api_handler.make_api_request')
    def test_failed_get_data(self, mock_make_request):
        """Test failed data retrieval"""
        mock_make_request.return_value = {
            'retCode': 10001,
            'retMsg': 'Error'
        }
        
        result = get_data(self.api_config, '/v5/position/list', {'category': 'linear'})
        
        assert result is None
    
    @patch('modules.api_handler.make_api_request')
    def test_exception_in_get_data(self, mock_make_request):
        """Test exception handling in get_data"""
        mock_make_request.side_effect = APIException("Test error")
        
        result = get_data(self.api_config, '/v5/position/list', {'category': 'linear'})
        
        assert result is None


class TestGetInstrumentInfo:
    """Tests for get_instrument_info function"""
    
    def setup_method(self):
        """Setup for each test"""
        self.api_config = SecureAPIConfig("test_key", "test_secret")
    
    @patch('modules.api_handler.get_data')
    def test_successful_instrument_info(self, mock_get_data):
        """Test successful instrument info retrieval"""
        mock_get_data.return_value = {
            'list': [{
                'symbol': 'BTCUSDT',
                'priceFilter': {'tickSize': '0.01'}
            }]
        }
        
        result = get_instrument_info(self.api_config, 'BTCUSDT')
        
        assert result is not None
        assert result['symbol'] == 'BTCUSDT'
        assert 'priceFilter' in result
    
    @patch('modules.api_handler.get_data')
    def test_no_instrument_found(self, mock_get_data):
        """Test when no instrument is found"""
        mock_get_data.return_value = {'list': []}
        
        result = get_instrument_info(self.api_config, 'NONEXISTENT')
        
        assert result is None
    
    @patch('modules.api_handler.get_data')
    def test_exception_in_instrument_info(self, mock_get_data):
        """Test exception handling in instrument info"""
        mock_get_data.side_effect = APIException("Test error")
        
        result = get_instrument_info(self.api_config, 'BTCUSDT')
        
        assert result is None


# Integration tests
class TestAPIIntegration:
    """Integration tests for API functionality"""
    
    @pytest.mark.integration
    def test_full_api_flow(self):
        """Test full API flow with mocked responses"""
        config_data = {
            'api_key': 'test_key',
            'api_secret': 'test_secret',
            'url': 'https://api-testnet.bybit.com'
        }
        
        api_config = create_api_config(config_data)
        
        with patch.object(api_config.session, 'get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'retCode': 0,
                'result': {
                    'list': [{
                        'symbol': 'BTCUSDT',
                        'priceFilter': {'tickSize': '0.01'}
                    }]
                }
            }
            mock_get.return_value = mock_response
            
            # Test getting instrument info
            instrument = get_instrument_info(api_config, 'BTCUSDT')
            
            assert instrument is not None
            assert instrument['symbol'] == 'BTCUSDT'


# Test fixtures
@pytest.fixture
def sample_api_config():
    """Fixture for sample API configuration"""
    return SecureAPIConfig("test_key", "test_secret")


@pytest.fixture
def mock_successful_response():
    """Fixture for successful API response"""
    return {
        'retCode': 0,
        'result': {'orderId': '12345'},
        'retMsg': 'OK'
    }