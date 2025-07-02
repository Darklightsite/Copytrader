"""
Setup script for Copytrader v2
"""
from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
this_directory = Path(__file__).parent
long_description = (this_directory / "CONFIG_README.md").read_text(encoding='utf-8')

# Read requirements
requirements = []
requirements_file = this_directory / "requirements.txt"
if requirements_file.exists():
    with open(requirements_file, 'r', encoding='utf-8') as f:
        requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]

# Read dev requirements
dev_requirements = []
dev_requirements_file = this_directory / "requirements-dev.txt"
if dev_requirements_file.exists():
    with open(dev_requirements_file, 'r', encoding='utf-8') as f:
        dev_requirements = [
            line.strip() for line in f 
            if line.strip() and not line.startswith('#') and not line.startswith('-r')
        ]

setup(
    name="copytrader",
    version="2.0.0",
    author="Copytrader Team",
    author_email="dev@copytrader.com",
    description="Advanced cryptocurrency copy trading bot for Bybit",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/copytrader/copytrader-v2",
    packages=find_packages(exclude=["tests", "tests.*"]),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Financial and Insurance Industry",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Topic :: Office/Business :: Financial :: Investment",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    extras_require={
        "dev": dev_requirements,
        "security": [
            "cryptography>=41.0.0",
            "bandit>=1.7.0",
        ],
        "monitoring": [
            "prometheus-client>=0.17.0",
            "sentry-sdk>=1.30.0",
        ],
        "async": [
            "aiohttp>=3.8.0",
            "asyncio-mqtt>=0.13.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "copytrader=main:main",
            "copytrader-test=pytest:main",
        ],
    },
    include_package_data=True,
    package_data={
        "copytrader": [
            "*.md",
            "*.ini",
            "*.example",
        ],
    },
    keywords=[
        "cryptocurrency", 
        "trading", 
        "bot", 
        "bybit", 
        "copy-trading", 
        "automated-trading"
    ],
    project_urls={
        "Bug Reports": "https://github.com/copytrader/copytrader-v2/issues",
        "Source": "https://github.com/copytrader/copytrader-v2",
        "Documentation": "https://docs.copytrader.com",
    },
)