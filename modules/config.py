"""
Configuration module for the Copytrader system.
Handles environment variables and settings.
"""
from typing import List, Optional
from pathlib import Path
import os
import json
import logging
from dotenv import load_dotenv
from modules.logger_setup import send_admin_alert

# Load environment variables
load_dotenv()

# Telegram Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_CHAT_IDS = [int(id.strip()) for id in os.getenv("ALLOWED_CHAT_IDS", "").split(",") if id.strip()]

# API Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "https://api.example.com")
API_KEY = os.getenv("API_KEY")

# Trading Configuration
MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "1.0"))
MAX_DRAWDOWN = float(os.getenv("MAX_DRAWDOWN", "0.1"))
RISK_PERCENTAGE = float(os.getenv("RISK_PERCENTAGE", "0.02"))

# File paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

def validate_config() -> bool:
    """
    Validates that all required configuration is present.
    Returns True if valid, False otherwise.
    """
    required_vars = [
        ("TELEGRAM_TOKEN", TELEGRAM_TOKEN),
        ("ALLOWED_CHAT_IDS", ALLOWED_CHAT_IDS),
        ("API_KEY", API_KEY)
    ]
    
    is_valid = True
    for var_name, var_value in required_vars:
        if not var_value:
            logging.error(f"Hiányzó kötelező környezeti változó: {var_name}")
            send_admin_alert(f"Hiányzó kötelező környezeti változó: {var_name}", user=None)
            is_valid = False
            
    return is_valid

def get_data_file_path(filename: str) -> Path:
    """Returns full path for a data file."""
    return DATA_DIR / filename

def get_log_file_path(filename: str) -> Path:
    """Returns full path for a log file."""
    return LOGS_DIR / filename 