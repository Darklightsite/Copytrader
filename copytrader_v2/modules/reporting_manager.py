"""
Copytrader v2 - Reporting Manager
Comprehensive reporting and analytics system with chart generation
"""
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
from pathlib import Path

from .exceptions import (
    ReportingError,
    ChartGenerationError,
    FileOperationError,
    create_error_context
)
from .logger import get_logger
from .file_utils import (
    load_json_file,
    save_json_file,
    save_balance_history,
    load_balance_history,
    save_pnl_summary,
    load_pnl_summary
)

try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.figure import Figure
    import numpy as np
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

class PerformanceMetrics:
    """Performance calculation utilities"""
    
    @staticmethod
    def calculate_total_return(initial_balance: float, current_balance: float) -> float:
        """Calculate total return percentage"""
        if initial_balance <= 0:
            return 0.0
        return ((current_balance - initial_balance) / initial_balance) * 100
    
    @staticmethod
    def calculate_daily_pnl(balance_history: List[Dict]) -> List[float]:
        """Calculate daily PnL from balance history"""
        if len(balance_history) < 2:
            return []
        
        daily_pnl = []
        for i in range(1, len(balance_history)):
            prev_balance = float(balance_history[i-1].get('balance', 0))
            curr_balance = float(balance_history[i].get('balance', 0))
            pnl = curr_balance - prev_balance
            daily_pnl.append(pnl)
        
        return daily_pnl
    
    @staticmethod
    def calculate_max_drawdown(balance_history: List[Dict]) -> Tuple[float, float]:
        """Calculate maximum drawdown percentage and amount"""
        if not balance_history:
            return 0.0, 0.0
        
        balances = [float(entry.get('balance', 0)) for entry in balance_history]
        peak = balances[0]
        max_drawdown_pct = 0.0
        max_drawdown_amount = 0.0
        
        for balance in balances:
            if balance > peak:
                peak = balance
            
            drawdown_amount = peak - balance
            drawdown_pct = (drawdown_amount / peak * 100) if peak > 0 else 0
            
            if drawdown_pct > max_drawdown_pct:
                max_drawdown_pct = drawdown_pct
                max_drawdown_amount = drawdown_amount
        
        return max_drawdown_pct, max_drawdown_amount
    
    @staticmethod
    def calculate_sharpe_ratio(daily_returns: List[float], risk_free_rate: float = 0.02) -> float:
        """Calculate Sharpe ratio"""
        if not daily_returns or len(daily_returns) < 2:
            return 0.0
        
        import statistics
        
        # Convert annual risk-free rate to daily
        daily_rf_rate = risk_free_rate / 365
        
        excess_returns = [r - daily_rf_rate for r in daily_returns]
        
        if len(excess_returns) < 2:
            return 0.0
        
        mean_excess_return = statistics.mean(excess_returns)
        std_excess_return = statistics.stdev(excess_returns)
        
        if std_excess_return == 0:
            return 0.0
        
        # Annualize the Sharpe ratio
        return (mean_excess_return / std_excess_return) * (365 ** 0.5)
    
    @staticmethod
    def calculate_win_rate(trades: List[Dict]) -> float:
        """Calculate win rate from trade history"""
        if not trades:
            return 0.0
        
        winning_trades = sum(1 for trade in trades if float(trade.get('pnl', 0)) > 0)
        return (winning_trades / len(trades)) * 100

class ChartGenerator:
    """Chart generation for performance visualization"""
    
    def __init__(self):
        self.logger = get_logger('reporting')
        
        if not MATPLOTLIB_AVAILABLE:
            self.logger.warning("Matplotlib not available - charts will not be generated")
    
    def generate_balance_chart(
        self, 
        balance_history: List[Dict], 
        account_name: str,
        output_path: Optional[str] = None
    ) -> Optional[str]:
        """Generate balance over time chart"""
        if not MATPLOTLIB_AVAILABLE:
            return None
        
        try:
            if not balance_history:
                return None
            
            # Extract data
            dates = []
            balances = []
            
            for entry in balance_history:
                try:
                    date = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00'))
                    balance = float(entry.get('balance', 0))
                    dates.append(date)
                    balances.append(balance)
                except (ValueError, KeyError) as e:
                    continue
            
            if not dates:
                return None
            
            # Create chart
            fig, ax = plt.subplots(figsize=(12, 6))
            ax.plot(dates, balances, linewidth=2, color='#2E8B57')
            
            # Formatting
            ax.set_title(f'Balance History - {account_name}', fontsize=16, fontweight='bold')
            ax.set_xlabel('Date', fontsize=12)
            ax.set_ylabel('Balance (USDT)', fontsize=12)
            ax.grid(True, alpha=0.3)
            
            # Format x-axis
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(dates)//10)))
            plt.xticks(rotation=45)
            
            # Add performance metrics
            if len(balances) >= 2:
                initial_balance = balances[0]
                current_balance = balances[-1]
                total_return = PerformanceMetrics.calculate_total_return(initial_balance, current_balance)
                
                textstr = f'Initial: ${initial_balance:,.2f}\nCurrent: ${current_balance:,.2f}\nReturn: {total_return:+.2f}%'
                props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
                ax.text(0.02, 0.98, textstr, transform=ax.transAxes, fontsize=10,
                       verticalalignment='top', bbox=props)
            
            plt.tight_layout()
            
            # Save chart
            if output_path is None:
                output_path = f"data/charts/{account_name}_balance_{datetime.now().strftime('%Y%m%d')}.png"
            
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(output_path, dpi=300, bbox_inches='tight')
            plt.close()
            
            return output_path
            
        except Exception as e:
            self.logger.error(f"Failed to generate balance chart: {e}", exc_info=True)
            raise ChartGenerationError(f"Failed to generate balance chart: {e}")
    
    def generate_pnl_chart(
        self,
        daily_pnl: List[float],
        account_name: str,
        output_path: Optional[str] = None
    ) -> Optional[str]:
        """Generate daily PnL chart"""
        if not MATPLOTLIB_AVAILABLE or not daily_pnl:
            return None
        
        try:
            # Create chart
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
            
            # Daily PnL bar chart
            days = list(range(1, len(daily_pnl) + 1))
            colors = ['green' if pnl >= 0 else 'red' for pnl in daily_pnl]
            
            ax1.bar(days, daily_pnl, color=colors, alpha=0.7)
            ax1.set_title(f'Daily PnL - {account_name}', fontsize=14, fontweight='bold')
            ax1.set_xlabel('Day')
            ax1.set_ylabel('PnL (USDT)')
            ax1.grid(True, alpha=0.3)
            ax1.axhline(y=0, color='black', linestyle='-', alpha=0.3)
            
            # Cumulative PnL line chart
            cumulative_pnl = np.cumsum(daily_pnl)
            ax2.plot(days, cumulative_pnl, linewidth=2, color='blue')
            ax2.fill_between(days, cumulative_pnl, alpha=0.3, color='blue')
            ax2.set_title('Cumulative PnL', fontsize=14, fontweight='bold')
            ax2.set_xlabel('Day')
            ax2.set_ylabel('Cumulative PnL (USDT)')
            ax2.grid(True, alpha=0.3)
            ax2.axhline(y=0, color='black', linestyle='-', alpha=0.3)
            
            # Add statistics
            total_pnl = sum(daily_pnl)
            avg_daily_pnl = total_pnl / len(daily_pnl)
            winning_days = sum(1 for pnl in daily_pnl if pnl > 0)
            win_rate = (winning_days / len(daily_pnl)) * 100
            
            textstr = f'Total PnL: ${total_pnl:+.2f}\nAvg Daily: ${avg_daily_pnl:+.2f}\nWin Rate: {win_rate:.1f}%'
            props = dict(boxstyle='round', facecolor='lightblue', alpha=0.8)
            ax2.text(0.02, 0.98, textstr, transform=ax2.transAxes, fontsize=10,
                    verticalalignment='top', bbox=props)
            
            plt.tight_layout()
            
            # Save chart
            if output_path is None:
                output_path = f"data/charts/{account_name}_pnl_{datetime.now().strftime('%Y%m%d')}.png"
            
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(output_path, dpi=300, bbox_inches='tight')
            plt.close()
            
            return output_path
            
        except Exception as e:
            self.logger.error(f"Failed to generate PnL chart: {e}", exc_info=True)
            raise ChartGenerationError(f"Failed to generate PnL chart: {e}")

class ReportingManager:
    """
    Main reporting manager for generating performance reports and analytics
    """
    
    def __init__(self):
        self.logger = get_logger('reporting')
        self.chart_generator = ChartGenerator()
        self.performance_metrics = PerformanceMetrics()
        
        # Ensure chart directory exists
        Path("data/charts").mkdir(parents=True, exist_ok=True)
    
    async def initialize(self):
        """Initialize the reporting manager"""
        self.logger.info("Reporting manager initialized")
    
    async def shutdown(self):
        """Shutdown the reporting manager"""
        self.logger.info("Reporting manager shutdown")
    
    async def update_balance_history(self, account_name: str, balance: float, additional_data: Optional[Dict] = None):
        """Update balance history for an account"""
        try:
            # Load existing history
            history = load_balance_history(account_name)
            
            # Create new entry
            entry = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'balance': balance,
                'date': datetime.now().strftime('%Y-%m-%d'),
                'hour': datetime.now().hour
            }
            
            if additional_data:
                entry.update(additional_data)
            
            # Add to history
            history.append(entry)
            
            # Keep only last 90 days
            cutoff_date = datetime.now() - timedelta(days=90)
            history = [
                h for h in history 
                if datetime.fromisoformat(h['timestamp'].replace('Z', '+00:00')) > cutoff_date
            ]
            
            # Save updated history
            save_balance_history(account_name, history)
            
            self.logger.debug(f"Updated balance history for {account_name}: ${balance}")
            
        except Exception as e:
            self.logger.error(f"Failed to update balance history for {account_name}: {e}")
            raise ReportingError(f"Failed to update balance history: {e}")
    
    async def generate_daily_report(self, account_name: str) -> Dict[str, Any]:
        """Generate comprehensive daily report for an account"""
        try:
            # Load data
            balance_history = load_balance_history(account_name)
            pnl_summary = load_pnl_summary(account_name)
            
            if not balance_history:
                return {"error": "No balance history available"}
            
            # Calculate metrics
            current_balance = float(balance_history[-1].get('balance', 0))
            initial_balance = float(balance_history[0].get('balance', 0)) if len(balance_history) > 1 else current_balance
            
            total_return = self.performance_metrics.calculate_total_return(initial_balance, current_balance)
            daily_pnl = self.performance_metrics.calculate_daily_pnl(balance_history)
            max_drawdown_pct, max_drawdown_amount = self.performance_metrics.calculate_max_drawdown(balance_history)
            
            # Calculate today's PnL
            today_pnl = 0.0
            if len(balance_history) >= 2:
                yesterday_balance = float(balance_history[-2].get('balance', 0))
                today_pnl = current_balance - yesterday_balance
            
            # Generate charts
            balance_chart_path = None
            pnl_chart_path = None
            
            try:
                balance_chart_path = self.chart_generator.generate_balance_chart(
                    balance_history, account_name
                )
                
                if daily_pnl:
                    pnl_chart_path = self.chart_generator.generate_pnl_chart(
                        daily_pnl, account_name
                    )
            except Exception as e:
                self.logger.warning(f"Failed to generate charts: {e}")
            
            # Create report
            report = {
                'account': account_name,
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'balance': {
                    'current': current_balance,
                    'initial': initial_balance,
                    'change_24h': today_pnl,
                    'change_24h_pct': (today_pnl / yesterday_balance * 100) if yesterday_balance > 0 else 0
                },
                'performance': {
                    'total_return_pct': total_return,
                    'max_drawdown_pct': max_drawdown_pct,
                    'max_drawdown_amount': max_drawdown_amount,
                    'sharpe_ratio': self.performance_metrics.calculate_sharpe_ratio(daily_pnl) if daily_pnl else 0
                },
                'trading': {
                    'total_days': len(balance_history),
                    'profitable_days': sum(1 for pnl in daily_pnl if pnl > 0) if daily_pnl else 0,
                    'avg_daily_pnl': sum(daily_pnl) / len(daily_pnl) if daily_pnl else 0
                },
                'charts': {
                    'balance_chart': balance_chart_path,
                    'pnl_chart': pnl_chart_path
                }
            }
            
            # Save report
            report_path = f"data/reports/{account_name}_daily_report_{datetime.now().strftime('%Y%m%d')}.json"
            save_json_file(report_path, report, backup=False)
            
            self.logger.info(f"Generated daily report for {account_name}")
            return report
            
        except Exception as e:
            self.logger.error(f"Failed to generate daily report for {account_name}: {e}")
            raise ReportingError(f"Failed to generate daily report: {e}")
    
    async def generate_summary_report(self, accounts: List[str]) -> Dict[str, Any]:
        """Generate summary report for multiple accounts"""
        try:
            account_reports = {}
            total_balance = 0.0
            total_pnl_24h = 0.0
            
            for account in accounts:
                try:
                    report = await self.generate_daily_report(account)
                    if 'error' not in report:
                        account_reports[account] = report
                        total_balance += report['balance']['current']
                        total_pnl_24h += report['balance']['change_24h']
                except Exception as e:
                    self.logger.error(f"Failed to generate report for {account}: {e}")
            
            summary = {
                'generated_at': datetime.now(timezone.utc).isoformat(),
                'total_accounts': len(accounts),
                'active_accounts': len(account_reports),
                'portfolio': {
                    'total_balance': total_balance,
                    'total_pnl_24h': total_pnl_24h,
                    'total_pnl_24h_pct': (total_pnl_24h / (total_balance - total_pnl_24h) * 100) if total_balance > total_pnl_24h else 0
                },
                'accounts': account_reports
            }
            
            # Save summary report
            summary_path = f"data/reports/portfolio_summary_{datetime.now().strftime('%Y%m%d')}.json"
            save_json_file(summary_path, summary, backup=False)
            
            self.logger.info(f"Generated summary report for {len(accounts)} accounts")
            return summary
            
        except Exception as e:
            self.logger.error(f"Failed to generate summary report: {e}")
            raise ReportingError(f"Failed to generate summary report: {e}")
    
    async def update_all_reports(self):
        """Update all reports (called from main loop)"""
        try:
            # This would typically be called with actual account data
            # For now, it's a placeholder that can be extended
            self.logger.debug("Report update cycle completed")
            
        except Exception as e:
            self.logger.error(f"Failed to update reports: {e}")
    
    def get_latest_report(self, account_name: str) -> Optional[Dict[str, Any]]:
        """Get the latest report for an account"""
        try:
            # Find latest report file
            reports_dir = Path("data/reports")
            if not reports_dir.exists():
                return None
            
            pattern = f"{account_name}_daily_report_*.json"
            report_files = list(reports_dir.glob(pattern))
            
            if not report_files:
                return None
            
            # Get most recent file
            latest_file = max(report_files, key=lambda f: f.stat().st_mtime)
            return load_json_file(latest_file)
            
        except Exception as e:
            self.logger.error(f"Failed to get latest report for {account_name}: {e}")
            return None
    
    def cleanup_old_reports(self, days_to_keep: int = 30):
        """Clean up old report files"""
        try:
            reports_dir = Path("data/reports")
            charts_dir = Path("data/charts")
            
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            
            for directory in [reports_dir, charts_dir]:
                if not directory.exists():
                    continue
                
                for file_path in directory.glob("*"):
                    if file_path.is_file():
                        file_time = datetime.fromtimestamp(file_path.stat().st_mtime)
                        if file_time < cutoff_date:
                            file_path.unlink()
                            self.logger.debug(f"Deleted old report file: {file_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to cleanup old reports: {e}")