"""
Copytrader v2 - File Management and Configuration System
Handles all file operations, directory structure, and account configurations
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timezone, timedelta
import shutil
import tempfile
from dataclasses import dataclass, asdict
from .exceptions import (
    FileOperationError, 
    ConfigurationError, 
    DataSerializationError,
    create_error_context
)

@dataclass
class AccountConfig:
    """Account configuration data structure"""
    nickname: str
    api_key: str
    api_secret: str
    url: str
    account_type: str  # 'live' or 'demo'
    role: str  # 'master' or 'slave'
    telegram_id: Optional[int] = None
    copy_multiplier: float = 1.0
    symbols_to_copy: Optional[List[str]] = None
    sl_loss_tiers_usd: Optional[List[float]] = None
    max_balance_today: Optional[float] = None
    min_balance_today: Optional[float] = None
    pnl_today: float = 0.0
    drawdown_alerted_levels: Optional[List[float]] = None
    last_trade_id: Optional[str] = None
    enabled: bool = True

def ensure_directory_structure():
    """Create all necessary directories if they don't exist"""
    directories = [
        "data",
        "data/accounts",
        "data/logs", 
        "data/reports",
        "data/charts",
        "data/history",
        "data/sync_state",
        "data/backups",
        "config",
        "telegram_bot",
        "modules"
    ]
    
    base_path = Path.cwd()
    
    for directory in directories:
        dir_path = base_path / directory
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise FileOperationError(f"Failed to create directory {directory}: {e}")

def load_account_configs() -> Dict[str, AccountConfig]:
    """Load all account configurations from data/accounts/"""
    accounts = {}
    accounts_dir = Path("data/accounts")
    
    if not accounts_dir.exists():
        ensure_directory_structure()
        create_sample_configs()
        
    try:
        for config_file in accounts_dir.glob("*.json"):
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                
            # Validate required fields
            required_fields = ['nickname', 'api_key', 'api_secret', 'url', 'account_type', 'role']
            for field in required_fields:
                if field not in config_data:
                    raise ConfigurationError(f"Missing required field '{field}' in {config_file.name}")
            
            # Create AccountConfig object
            account = AccountConfig(**config_data)
            accounts[account.nickname] = account
            
    except json.JSONDecodeError as e:
        raise DataSerializationError(f"Invalid JSON in account config: {e}")
    except Exception as e:
        raise FileOperationError(f"Failed to load account configs: {e}")
    
    return accounts

def save_account_config(account: AccountConfig):
    """Save account configuration to file"""
    config_file = Path(f"data/accounts/{account.nickname}.json")
    
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(asdict(account), f, indent=2, ensure_ascii=False)
    except Exception as e:
        raise FileOperationError(f"Failed to save account config for {account.nickname}: {e}")

def create_sample_configs():
    """Create sample configuration files if none exist"""
    sample_master = AccountConfig(
        nickname="master",
        api_key="your_live_api_key_here",
        api_secret="your_live_api_secret_here", 
        url="https://api.bybit.com",
        account_type="live",
        role="master",
        telegram_id=123456789,
        symbols_to_copy=["BTCUSDT", "ETHUSDT"]
    )
    
    sample_slave = AccountConfig(
        nickname="slave1",
        api_key="your_demo_api_key_here",
        api_secret="your_demo_api_secret_here",
        url="https://api-testnet.bybit.com", 
        account_type="demo",
        role="slave",
        telegram_id=123456789,
        copy_multiplier=1.0,
        sl_loss_tiers_usd=[10.0, 20.0, 30.0]
    )
    
    save_account_config(sample_master)
    save_account_config(sample_slave)

def load_json_file(file_path: Union[str, Path], default: Any = None) -> Any:
    """Safely load JSON file with error handling"""
    file_path = Path(file_path)
    
    try:
        if not file_path.exists():
            return default
            
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
            
    except json.JSONDecodeError as e:
        raise DataSerializationError(f"Invalid JSON in {file_path}: {e}")
    except Exception as e:
        raise FileOperationError(f"Failed to load {file_path}: {e}")

def save_json_file(file_path: Union[str, Path], data: Any, backup: bool = True):
    """Safely save JSON file with atomic write and optional backup"""
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # Create backup if file exists and backup is requested
        if backup and file_path.exists():
            backup_path = file_path.with_suffix(f".backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            shutil.copy2(file_path, backup_path)
        
        # Atomic write using temporary file
        with tempfile.NamedTemporaryFile(
            mode='w', 
            encoding='utf-8', 
            dir=file_path.parent,
            delete=False,
            suffix='.tmp'
        ) as tmp_file:
            json.dump(data, tmp_file, indent=2, ensure_ascii=False)
            tmp_path = Path(tmp_file.name)
        
        # Replace original file
        tmp_path.replace(file_path)
        
    except Exception as e:
        # Clean up temporary file if it exists
        if 'tmp_path' in locals() and tmp_path.exists():
            tmp_path.unlink()
        raise FileOperationError(f"Failed to save {file_path}: {e}")

def get_balance_history_file(account: str) -> Path:
    """Get path to balance history file for account"""
    return Path(f"data/reports/{account}_balance_history.json")

def get_pnl_summary_file(account: str) -> Path:
    """Get path to PnL summary file for account"""
    return Path(f"data/reports/{account}_pnl_summary.json")

def get_sync_state_file(master: str, slave: str) -> Path:
    """Get path to sync state file for account pair"""
    return Path(f"data/sync_state/{master}_{slave}_state.json")

def save_balance_history(account: str, balance_data: List[Dict[str, Any]]):
    """Save balance history for an account"""
    file_path = get_balance_history_file(account)
    save_json_file(file_path, {
        "account": account,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "data": balance_data
    })

def load_balance_history(account: str) -> List[Dict[str, Any]]:
    """Load balance history for an account"""
    file_path = get_balance_history_file(account)
    data = load_json_file(file_path, {"data": []})
    return data.get("data", [])

def save_pnl_summary(account: str, pnl_data: Dict[str, Any]):
    """Save PnL summary for an account"""
    file_path = get_pnl_summary_file(account)
    save_json_file(file_path, {
        "account": account,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        **pnl_data
    })

def load_pnl_summary(account: str) -> Dict[str, Any]:
    """Load PnL summary for an account"""
    file_path = get_pnl_summary_file(account)
    return load_json_file(file_path, {
        "daily": {},
        "weekly": {}, 
        "monthly": {},
        "total": 0.0
    })

def save_sync_state(master: str, slave: str, state_data: Dict[str, Any]):
    """Save synchronization state for account pair"""
    file_path = get_sync_state_file(master, slave)
    save_json_file(file_path, {
        "master": master,
        "slave": slave,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        **state_data
    })

def load_sync_state(master: str, slave: str) -> Dict[str, Any]:
    """Load synchronization state for account pair"""
    file_path = get_sync_state_file(master, slave)
    return load_json_file(file_path, {
        "last_trade_id": None,
        "position_ids": {},
        "order_ids": {},
        "last_sync": None
    })

def reset_daily_data(account: str):
    """Reset daily data for an account (called at UTC 00:00)"""
    try:
        # Load current account config
        accounts = load_account_configs()
        if account not in accounts:
            raise ConfigurationError(f"Account {account} not found")
        
        account_config = accounts[account]
        
        # Reset daily fields but keep last_trade_id
        account_config.max_balance_today = None
        account_config.min_balance_today = None
        account_config.pnl_today = 0.0
        account_config.drawdown_alerted_levels = []
        
        # Save updated config
        save_account_config(account_config)
        
    except Exception as e:
        raise FileOperationError(f"Failed to reset daily data for {account}: {e}")

def cleanup_old_files(days_to_keep: int = 30):
    """Clean up old log files and backups"""
    cutoff_date = datetime.now() - timedelta(days=days_to_keep)
    
    cleanup_dirs = [
        Path("data/logs/archive"),
        Path("data/backups"),
        Path("data/charts")
    ]
    
    for cleanup_dir in cleanup_dirs:
        if not cleanup_dir.exists():
            continue
            
        try:
            for file_path in cleanup_dir.rglob("*"):
                if file_path.is_file():
                    file_time = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if file_time < cutoff_date:
                        file_path.unlink()
        except Exception as e:
            # Log error but don't fail
            pass

def backup_data(backup_name: Optional[str] = None):
    """Create a backup of all important data"""
    if backup_name is None:
        backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    backup_dir = Path(f"data/backups/{backup_name}")
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Backup account configs
        shutil.copytree("data/accounts", backup_dir / "accounts", dirs_exist_ok=True)
        
        # Backup reports
        if Path("data/reports").exists():
            shutil.copytree("data/reports", backup_dir / "reports", dirs_exist_ok=True)
        
        # Backup sync state
        if Path("data/sync_state").exists():
            shutil.copytree("data/sync_state", backup_dir / "sync_state", dirs_exist_ok=True)
        
        # Create backup manifest
        manifest = {
            "backup_name": backup_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files_backed_up": [
                "accounts",
                "reports", 
                "sync_state"
            ]
        }
        
        save_json_file(backup_dir / "manifest.json", manifest, backup=False)
        
        return str(backup_dir)
        
    except Exception as e:
        raise FileOperationError(f"Failed to create backup: {e}")

def restore_data(backup_name: str):
    """Restore data from a backup"""
    backup_dir = Path(f"data/backups/{backup_name}")
    
    if not backup_dir.exists():
        raise FileOperationError(f"Backup {backup_name} not found")
    
    try:
        # Check manifest
        manifest_file = backup_dir / "manifest.json"
        if manifest_file.exists():
            manifest = load_json_file(manifest_file)
            # Could add version checking here
        
        # Restore account configs
        if (backup_dir / "accounts").exists():
            shutil.rmtree("data/accounts", ignore_errors=True)
            shutil.copytree(backup_dir / "accounts", "data/accounts")
        
        # Restore reports
        if (backup_dir / "reports").exists():
            shutil.rmtree("data/reports", ignore_errors=True)
            shutil.copytree(backup_dir / "reports", "data/reports")
        
        # Restore sync state
        if (backup_dir / "sync_state").exists():
            shutil.rmtree("data/sync_state", ignore_errors=True)
            shutil.copytree(backup_dir / "sync_state", "data/sync_state")
            
    except Exception as e:
        raise FileOperationError(f"Failed to restore backup {backup_name}: {e}")

def get_file_info(file_path: Union[str, Path]) -> Dict[str, Any]:
    """Get information about a file"""
    file_path = Path(file_path)
    
    if not file_path.exists():
        return {}
    
    try:
        stat = file_path.stat()
        return {
            "path": str(file_path),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "is_file": file_path.is_file(),
            "is_dir": file_path.is_dir()
        }
    except Exception as e:
        return {"error": str(e)}

def validate_account_config(config_data: Dict[str, Any]) -> List[str]:
    """Validate account configuration data"""
    errors = []
    
    required_fields = ['nickname', 'api_key', 'api_secret', 'url', 'account_type', 'role']
    for field in required_fields:
        if field not in config_data:
            errors.append(f"Missing required field: {field}")
        elif not config_data[field]:
            errors.append(f"Empty value for required field: {field}")
    
    # Validate account_type
    if 'account_type' in config_data:
        if config_data['account_type'] not in ['live', 'demo']:
            errors.append("account_type must be 'live' or 'demo'")
    
    # Validate role
    if 'role' in config_data:
        if config_data['role'] not in ['master', 'slave']:
            errors.append("role must be 'master' or 'slave'")
    
    # Validate copy_multiplier
    if 'copy_multiplier' in config_data:
        try:
            multiplier = float(config_data['copy_multiplier'])
            if multiplier <= 0:
                errors.append("copy_multiplier must be positive")
        except (ValueError, TypeError):
            errors.append("copy_multiplier must be a valid number")
    
    return errors