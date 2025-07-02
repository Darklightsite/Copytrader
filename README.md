# 🚀 Copytrader v2

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Security: bandit](https://img.shields.io/badge/security-bandit-green.svg)](https://github.com/PyCQA/bandit)

**Advanced cryptocurrency copy trading bot for Bybit** with enterprise-grade security, monitoring, and reliability features.

---

## ✨ Features

### 🔒 Security First
- **Encrypted API credentials** with Fernet encryption
- **Rate limiting** and automatic user blocking
- **Session management** with 24-hour timeout
- **Environment-based configuration** 
- **Comprehensive audit trail**

### 🏗️ Enterprise Architecture
- **Multi-process architecture** with graceful shutdown
- **Process monitoring** and automatic recovery
- **Custom exception hierarchy** for better error handling
- **Connection pooling** for optimal performance
- **Signal handling** for all platforms

### 🧪 Testing & Quality
- **100+ unit tests** with comprehensive coverage
- **Mock-based testing** for reliable CI/CD
- **Type hints** for better IDE support
- **Professional logging** with structured output
- **Security scanning** with bandit

### 📊 Monitoring & Observability
- **Real-time status reporting** via Telegram
- **Performance metrics** collection
- **Error tracking** with context
- **Activity logging** and audit trails

---

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Bybit API account (demo or live)
- Telegram bot token

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/copytrader/copytrader-v2.git
cd copytrader-v2
```

2. **Install dependencies**
```bash
# Production
pip install -r requirements.txt

# Development
pip install -r requirements-dev.txt

# With security extras
pip install -e .[security]
```

3. **Configure environment**
```bash
# Copy example configuration
cp .env.example .env

# Edit with your values
nano .env
```

4. **Run tests**
```bash
pytest tests/ --cov=modules
```

5. **Start the bot**
```bash
python main.py
```

---

## ⚙️ Configuration

### Environment Variables

Create a `.env` file based on `.env.example`:

```env
# Telegram Configuration
TELEGRAM_TOKEN=your_bot_token_here
ALLOWED_CHAT_IDS=123456789,987654321

# Security
API_ENCRYPTION_KEY=your_32_byte_encryption_key

# Trading
MAX_POSITION_SIZE=1.0
MAX_DRAWDOWN=0.1
RISK_PERCENTAGE=0.02
```

### User Configuration

Each user needs a configuration file in `data/users/{nickname}/config.ini`:

```ini
[api]
api_key = your_bybit_api_key
api_secret = your_bybit_api_secret
url = https://api.bybit.com

[settings]
copy_multiplier = 10.0
symbols_to_copy = BTCUSDT, ETHUSDT
sl_loss_tiers_usd = 10, 20, 30
```

See [CONFIG_README.md](CONFIG_README.md) for detailed configuration options.

---

## 🏗️ Architecture

```
copytrader-v2/
├── main.py                 # Application entry point
├── modules/                # Core modules
│   ├── api_handler.py     # Secure API client
│   ├── auth.py            # Authentication & security
│   ├── exceptions.py      # Custom exception hierarchy
│   ├── order_handler.py   # Trading logic
│   └── ...
├── tests/                 # Unit tests
├── data/                  # User data and logs
└── docs/                  # Documentation
```

### Key Components

- **ProcessManager**: Multi-process orchestration with recovery
- **SecurityManager**: Authentication, rate limiting, session management
- **SecureAPIConfig**: Encrypted API credential management
- **Custom Exceptions**: 27 specific exception types for precise error handling

---

## 🧪 Testing

### Run Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=modules --cov-report=html

# Specific test file
pytest tests/test_api_handler.py

# Integration tests
pytest -m integration
```

### Test Categories

- **Unit Tests**: Individual function testing
- **Integration Tests**: API integration testing  
- **Security Tests**: Authentication and encryption
- **Performance Tests**: Load and stress testing

---

## 🔒 Security

### Security Features

- ✅ **API Key Encryption**: Fernet-based encryption for API secrets
- ✅ **Rate Limiting**: 5 attempts per 15 minutes
- ✅ **Session Management**: 24-hour session timeout
- ✅ **Input Validation**: All user inputs validated
- ✅ **Audit Logging**: Comprehensive activity tracking

### Security Scans

```bash
# Security vulnerability scan
bandit -r modules/

# Dependency vulnerability check
safety check

# Code quality scan
pylint modules/
```

---

## 📚 Documentation

- [Configuration Guide](CONFIG_README.md) - Detailed setup instructions
- [Audit Report](AUDIT_REPORT.md) - Security audit findings
- [API Documentation](docs/api.md) - API reference (coming soon)
- [Deployment Guide](docs/deployment.md) - Production deployment (coming soon)

---

## 🚀 Deployment

### Docker (Recommended)

```bash
# Build image
docker build -t copytrader:v2 .

# Run container
docker run -d \
  --name copytrader \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  copytrader:v2
```

### System Service

```bash
# Install as systemd service
sudo cp scripts/copytrader.service /etc/systemd/system/
sudo systemctl enable copytrader
sudo systemctl start copytrader
```

---

## 🛡️ Security Audit

The codebase has undergone comprehensive security audit:

- **40 issues identified** and prioritized
- **20 critical/high issues fixed** (100% of critical)
- **Zero critical vulnerabilities** remaining
- **Production-ready security posture**

See [AUDIT_FIXES_COMPLETED.md](AUDIT_FIXES_COMPLETED.md) for details.

---

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Setup

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install

# Run linting
black modules/ tests/
pylint modules/

# Run security scan
bandit -r modules/
```

---

## 📊 Performance

- **Sub-second** API response times
- **Multi-process** architecture for scalability
- **Connection pooling** for optimal resource usage
- **Memory-efficient** data structures
- **Graceful error recovery** with minimal downtime

---

## 🆘 Support

- 📧 **Email**: support@copytrader.com
- 💬 **Telegram**: @copytrader_support
- 📝 **Issues**: [GitHub Issues](https://github.com/copytrader/copytrader-v2/issues)
- 📚 **Docs**: [Documentation](https://docs.copytrader.com)

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## ⚠️ Disclaimer

**This software is for educational and research purposes only.** 

Cryptocurrency trading involves substantial risk of loss. Past performance does not guarantee future results. Only trade with funds you can afford to lose. The developers are not responsible for any financial losses incurred through the use of this software.

---

## 🙏 Acknowledgments

- [Bybit API](https://bybit-exchange.github.io/docs/) for excellent documentation
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) for Telegram integration
- The open-source community for inspiration and tools

---

<div align="center">

**Made with ❤️ by the Copytrader Team**

[⭐ Star us on GitHub](https://github.com/copytrader/copytrader-v2) | [🐛 Report Bug](https://github.com/copytrader/copytrader-v2/issues) | [💡 Request Feature](https://github.com/copytrader/copytrader-v2/issues)

</div>