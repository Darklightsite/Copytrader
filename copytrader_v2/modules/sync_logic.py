"""
Copytrader v2 - Synchronization Logic
Core engine for copying trades between master and slave accounts
"""
import asyncio
from typing import Dict, List, Optional, Any, Set
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone
import json

from .exceptions import (
    SynchronizationError,
    PositionSyncError,
    OrderSyncError,
    TradingError,
    create_error_context
)
from .logger import get_logger, log_sync_event, log_trading_action
from .api_handler import BybitAPIHandler
from .file_utils import AccountConfig, save_sync_state, load_sync_state

class PositionInfo:
    """Position information wrapper"""
    
    def __init__(self, position_data: Dict[str, Any]):
        self.symbol = position_data.get('symbol', '')
        self.side = position_data.get('side', '')
        self.size = Decimal(str(position_data.get('size', '0')))
        self.entry_price = Decimal(str(position_data.get('avgPrice', '0')))
        self.mark_price = Decimal(str(position_data.get('markPrice', '0')))
        self.unrealized_pnl = Decimal(str(position_data.get('unrealisedPnl', '0')))
        self.position_idx = int(position_data.get('positionIdx', 0))
        self.leverage = position_data.get('leverage', '1')
        self.raw_data = position_data
    
    @property
    def is_open(self) -> bool:
        """Check if position is open"""
        return self.size > 0
    
    def __str__(self) -> str:
        return f"{self.symbol} {self.side} {self.size} @ {self.entry_price}"

class OrderInfo:
    """Order information wrapper"""
    
    def __init__(self, order_data: Dict[str, Any]):
        self.order_id = order_data.get('orderId', '')
        self.order_link_id = order_data.get('orderLinkId', '')
        self.symbol = order_data.get('symbol', '')
        self.side = order_data.get('side', '')
        self.order_type = order_data.get('orderType', '')
        self.qty = Decimal(str(order_data.get('qty', '0')))
        self.price = Decimal(str(order_data.get('price', '0'))) if order_data.get('price') else None
        self.order_status = order_data.get('orderStatus', '')
        self.time_in_force = order_data.get('timeInForce', '')
        self.created_time = order_data.get('createdTime', '')
        self.raw_data = order_data
    
    @property
    def is_active(self) -> bool:
        """Check if order is active"""
        active_statuses = ['New', 'PartiallyFilled', 'Untriggered']
        return self.order_status in active_statuses
    
    def __str__(self) -> str:
        price_str = f" @ {self.price}" if self.price else ""
        return f"{self.symbol} {self.side} {self.qty}{price_str} ({self.order_status})"

class SyncManager:
    """
    Main synchronization manager for copying trades between accounts
    Handles position copying, order copying, and risk management
    """
    
    def __init__(self, master_config: AccountConfig, slave_config: AccountConfig):
        self.master_config = master_config
        self.slave_config = slave_config
        self.logger = get_logger('sync')
        
        # Set logging context
        self.logger.set_context(
            master=master_config.nickname,
            slave=slave_config.nickname
        )
        
        # API handlers
        self.master_api: Optional[BybitAPIHandler] = None
        self.slave_api: Optional[BybitAPIHandler] = None
        
        # Sync state
        self.sync_state = load_sync_state(master_config.nickname, slave_config.nickname)
        self.last_sync_time = None
        
        # Risk management
        self.copy_multiplier = slave_config.copy_multiplier
        self.symbols_to_copy = set(slave_config.symbols_to_copy or [])
        self.sl_loss_tiers = slave_config.sl_loss_tiers_usd or []
        
        # Tracking
        self.synced_positions: Dict[str, PositionInfo] = {}
        self.synced_orders: Dict[str, OrderInfo] = {}
        
    async def initialize(self):
        """Initialize the sync manager"""
        try:
            # Initialize API handlers
            self.master_api = BybitAPIHandler(self.master_config)
            self.slave_api = BybitAPIHandler(self.slave_config)
            
            await self.master_api.initialize()
            await self.slave_api.initialize()
            
            # Health check
            master_healthy = await self.master_api.health_check()
            slave_healthy = await self.slave_api.health_check()
            
            if not master_healthy:
                raise SynchronizationError(f"Master account {self.master_config.nickname} API not healthy")
            if not slave_healthy:
                raise SynchronizationError(f"Slave account {self.slave_config.nickname} API not healthy")
            
            log_sync_event(
                self.logger, 
                "initialized", 
                self.master_config.nickname, 
                self.slave_config.nickname
            )
            
        except Exception as e:
            self.logger.error(f"Failed to initialize sync manager: {e}", exc_info=True)
            raise SynchronizationError(f"Failed to initialize sync manager: {e}")
    
    async def shutdown(self):
        """Shutdown the sync manager"""
        try:
            if self.master_api:
                await self.master_api.close()
            if self.slave_api:
                await self.slave_api.close()
                
            # Save final sync state
            self._save_sync_state()
            
            log_sync_event(
                self.logger, 
                "shutdown", 
                self.master_config.nickname, 
                self.slave_config.nickname
            )
            
        except Exception as e:
            self.logger.error(f"Error during sync manager shutdown: {e}")
    
    async def run_sync_cycle(self):
        """Run a complete synchronization cycle"""
        try:
            self.logger.debug("Starting sync cycle")
            
            # Get current state from both accounts
            master_positions = await self._get_master_positions()
            master_orders = await self._get_master_orders()
            slave_positions = await self._get_slave_positions()
            slave_orders = await self._get_slave_orders()
            
            # Synchronize positions
            await self._sync_positions(master_positions, slave_positions)
            
            # Synchronize orders
            await self._sync_orders(master_orders, slave_orders)
            
            # Check stop-loss conditions
            await self._check_stop_loss_conditions(slave_positions)
            
            # Update sync state
            self.last_sync_time = datetime.now(timezone.utc)
            self._save_sync_state()
            
            self.logger.debug("Sync cycle completed")
            
        except Exception as e:
            self.logger.error(f"Error in sync cycle: {e}", exc_info=True)
            raise SynchronizationError(f"Sync cycle failed: {e}")
    
    async def _get_master_positions(self) -> List[PositionInfo]:
        """Get positions from master account"""
        try:
            positions_data = await self.master_api.get_positions(category="linear")
            positions = []
            
            for pos_data in positions_data:
                position = PositionInfo(pos_data)
                if position.is_open and self._should_copy_symbol(position.symbol):
                    positions.append(position)
            
            return positions
            
        except Exception as e:
            raise PositionSyncError(f"Failed to get master positions: {e}")
    
    async def _get_slave_positions(self) -> List[PositionInfo]:
        """Get positions from slave account"""
        try:
            positions_data = await self.slave_api.get_positions(category="linear")
            return [PositionInfo(pos_data) for pos_data in positions_data if PositionInfo(pos_data).is_open]
            
        except Exception as e:
            raise PositionSyncError(f"Failed to get slave positions: {e}")
    
    async def _get_master_orders(self) -> List[OrderInfo]:
        """Get open orders from master account"""
        try:
            orders_data = await self.master_api.get_open_orders(category="linear")
            orders = []
            
            for order_data in orders_data:
                order = OrderInfo(order_data)
                if order.is_active and self._should_copy_symbol(order.symbol):
                    orders.append(order)
            
            return orders
            
        except Exception as e:
            raise OrderSyncError(f"Failed to get master orders: {e}")
    
    async def _get_slave_orders(self) -> List[OrderInfo]:
        """Get open orders from slave account"""
        try:
            orders_data = await self.slave_api.get_open_orders(category="linear")
            return [OrderInfo(order_data) for order_data in orders_data if OrderInfo(order_data).is_active]
            
        except Exception as e:
            raise OrderSyncError(f"Failed to get slave orders: {e}")
    
    async def _sync_positions(self, master_positions: List[PositionInfo], slave_positions: List[PositionInfo]):
        """Synchronize positions between master and slave"""
        # Create position maps for easy lookup
        master_pos_map = {pos.symbol: pos for pos in master_positions}
        slave_pos_map = {pos.symbol: pos for pos in slave_positions}
        
        # Get all symbols that need sync
        all_symbols = set(master_pos_map.keys()) | set(slave_pos_map.keys())
        
        for symbol in all_symbols:
            master_pos = master_pos_map.get(symbol)
            slave_pos = slave_pos_map.get(symbol)
            
            try:
                if master_pos and not slave_pos:
                    # Master has position, slave doesn't -> Open position on slave
                    await self._open_slave_position(master_pos)
                    
                elif master_pos and slave_pos:
                    # Both have positions -> Check if they match
                    await self._sync_existing_position(master_pos, slave_pos)
                    
                elif not master_pos and slave_pos:
                    # Slave has position, master doesn't -> Close slave position
                    await self._close_slave_position(slave_pos)
                    
            except Exception as e:
                self.logger.error(f"Failed to sync position for {symbol}: {e}")
                # Continue with other symbols
    
    async def _open_slave_position(self, master_position: PositionInfo):
        """Open corresponding position on slave account"""
        try:
            # Calculate quantity based on copy multiplier
            slave_qty = self._calculate_slave_quantity(master_position.size)
            
            if slave_qty <= 0:
                self.logger.warning(f"Calculated slave quantity too small for {master_position.symbol}")
                return
            
            # Place market order to open position
            result = await self.slave_api.place_order(
                category="linear",
                symbol=master_position.symbol,
                side=master_position.side,
                order_type="Market",
                qty=str(slave_qty),
                time_in_force="IOC"  # Immediate or Cancel
            )
            
            log_trading_action(
                self.logger,
                "position_open",
                master_position.symbol,
                master_position.side,
                float(slave_qty),
                slave_account=self.slave_config.nickname
            )
            
        except Exception as e:
            raise PositionSyncError(f"Failed to open slave position for {master_position.symbol}: {e}")
    
    async def _sync_existing_position(self, master_position: PositionInfo, slave_position: PositionInfo):
        """Sync existing positions to match master"""
        try:
            # Check if sides match
            if master_position.side != slave_position.side:
                # Close slave position and open new one
                await self._close_slave_position(slave_position)
                await asyncio.sleep(1)  # Wait a bit before opening new position
                await self._open_slave_position(master_position)
                return
            
            # Check if quantities match (within tolerance)
            expected_slave_qty = self._calculate_slave_quantity(master_position.size)
            qty_diff = abs(slave_position.size - expected_slave_qty)
            tolerance = expected_slave_qty * Decimal('0.05')  # 5% tolerance
            
            if qty_diff > tolerance:
                # Adjust position size
                if slave_position.size < expected_slave_qty:
                    # Need to increase position
                    additional_qty = expected_slave_qty - slave_position.size
                    await self._adjust_slave_position(master_position.symbol, master_position.side, additional_qty)
                else:
                    # Need to decrease position
                    reduce_qty = slave_position.size - expected_slave_qty
                    await self._reduce_slave_position(master_position.symbol, reduce_qty)
            
        except Exception as e:
            raise PositionSyncError(f"Failed to sync existing position for {master_position.symbol}: {e}")
    
    async def _close_slave_position(self, slave_position: PositionInfo):
        """Close position on slave account"""
        try:
            # Determine opposite side for closing
            close_side = "Sell" if slave_position.side == "Buy" else "Buy"
            
            result = await self.slave_api.place_order(
                category="linear",
                symbol=slave_position.symbol,
                side=close_side,
                order_type="Market",
                qty=str(slave_position.size),
                reduce_only=True,
                time_in_force="IOC"
            )
            
            log_trading_action(
                self.logger,
                "position_close",
                slave_position.symbol,
                close_side,
                float(slave_position.size),
                slave_account=self.slave_config.nickname
            )
            
        except Exception as e:
            raise PositionSyncError(f"Failed to close slave position for {slave_position.symbol}: {e}")
    
    async def _adjust_slave_position(self, symbol: str, side: str, quantity: Decimal):
        """Adjust slave position by adding to it"""
        try:
            result = await self.slave_api.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                order_type="Market",
                qty=str(quantity),
                time_in_force="IOC"
            )
            
            log_trading_action(
                self.logger,
                "position_adjust",
                symbol,
                side,
                float(quantity),
                slave_account=self.slave_config.nickname
            )
            
        except Exception as e:
            raise PositionSyncError(f"Failed to adjust slave position for {symbol}: {e}")
    
    async def _reduce_slave_position(self, symbol: str, quantity: Decimal):
        """Reduce slave position by specified quantity"""
        try:
            # Get current position to determine side
            positions = await self.slave_api.get_positions(category="linear", symbol=symbol)
            if not positions:
                return
            
            position = PositionInfo(positions[0])
            if not position.is_open:
                return
            
            # Determine opposite side for reduction
            reduce_side = "Sell" if position.side == "Buy" else "Buy"
            
            result = await self.slave_api.place_order(
                category="linear",
                symbol=symbol,
                side=reduce_side,
                order_type="Market",
                qty=str(quantity),
                reduce_only=True,
                time_in_force="IOC"
            )
            
            log_trading_action(
                self.logger,
                "position_reduce",
                symbol,
                reduce_side,
                float(quantity),
                slave_account=self.slave_config.nickname
            )
            
        except Exception as e:
            raise PositionSyncError(f"Failed to reduce slave position for {symbol}: {e}")
    
    async def _sync_orders(self, master_orders: List[OrderInfo], slave_orders: List[OrderInfo]):
        """Synchronize pending orders between master and slave"""
        # For now, we'll implement a simple strategy:
        # Cancel all slave orders that don't correspond to master orders
        # This prevents conflicting orders and keeps things simple
        
        try:
            # Cancel all existing slave orders
            for slave_order in slave_orders:
                if self._should_copy_symbol(slave_order.symbol):
                    await self._cancel_slave_order(slave_order)
            
            # Note: We don't copy pending orders from master to slave
            # as this could interfere with position synchronization
            # Only positions are copied, not individual orders
            
        except Exception as e:
            self.logger.error(f"Failed to sync orders: {e}")
            # Don't raise exception for order sync failures
    
    async def _cancel_slave_order(self, order: OrderInfo):
        """Cancel an order on slave account"""
        try:
            await self.slave_api.cancel_order(
                category="linear",
                symbol=order.symbol,
                order_id=order.order_id
            )
            
            self.logger.debug(f"Cancelled slave order: {order}")
            
        except Exception as e:
            self.logger.warning(f"Failed to cancel slave order {order.order_id}: {e}")
    
    async def _check_stop_loss_conditions(self, slave_positions: List[PositionInfo]):
        """Check and execute stop-loss conditions"""
        if not self.sl_loss_tiers:
            return
        
        try:
            # Get slave account balance
            balance_data = await self.slave_api.get_wallet_balance()
            total_wallet_balance = Decimal('0')
            
            if 'list' in balance_data and balance_data['list']:
                for account in balance_data['list']:
                    if 'coin' in account and account['coin']:
                        for coin_data in account['coin']:
                            if coin_data.get('coin') == 'USDT':
                                total_wallet_balance = Decimal(str(coin_data.get('walletBalance', '0')))
                                break
            
            # Check if any stop-loss tier is hit
            for tier_usd in self.sl_loss_tiers:
                if total_wallet_balance <= Decimal(str(tier_usd)):
                    await self._execute_stop_loss(slave_positions, tier_usd)
                    break  # Only execute first triggered tier
                    
        except Exception as e:
            self.logger.error(f"Failed to check stop-loss conditions: {e}")
    
    async def _execute_stop_loss(self, positions: List[PositionInfo], tier_usd: float):
        """Execute stop-loss by closing all positions"""
        try:
            self.logger.warning(f"Stop-loss tier ${tier_usd} triggered - closing all positions")
            
            for position in positions:
                await self._close_slave_position(position)
                await asyncio.sleep(0.5)  # Prevent rate limiting
            
            log_sync_event(
                self.logger,
                "stop_loss_executed",
                self.master_config.nickname,
                self.slave_config.nickname,
                tier_usd=tier_usd
            )
            
        except Exception as e:
            self.logger.error(f"Failed to execute stop-loss: {e}")
    
    def _calculate_slave_quantity(self, master_quantity: Decimal) -> Decimal:
        """Calculate slave quantity based on copy multiplier"""
        slave_qty = master_quantity * Decimal(str(self.copy_multiplier))
        
        # Round down to avoid over-leveraging
        return slave_qty.quantize(Decimal('0.001'), rounding=ROUND_DOWN)
    
    def _should_copy_symbol(self, symbol: str) -> bool:
        """Check if symbol should be copied"""
        if not self.symbols_to_copy:
            return True  # Copy all symbols if none specified
        return symbol in self.symbols_to_copy
    
    def _save_sync_state(self):
        """Save current sync state to file"""
        try:
            state_data = {
                "last_sync": self.last_sync_time.isoformat() if self.last_sync_time else None,
                "copy_multiplier": self.copy_multiplier,
                "symbols_to_copy": list(self.symbols_to_copy),
                "sync_stats": {
                    "synced_positions": len(self.synced_positions),
                    "synced_orders": len(self.synced_orders)
                }
            }
            
            save_sync_state(
                self.master_config.nickname,
                self.slave_config.nickname,
                state_data
            )
            
        except Exception as e:
            self.logger.error(f"Failed to save sync state: {e}")
    
    def get_sync_status(self) -> Dict[str, Any]:
        """Get current synchronization status"""
        return {
            "master_account": self.master_config.nickname,
            "slave_account": self.slave_config.nickname,
            "copy_multiplier": self.copy_multiplier,
            "symbols_to_copy": list(self.symbols_to_copy),
            "last_sync": self.last_sync_time.isoformat() if self.last_sync_time else None,
            "synced_positions": len(self.synced_positions),
            "synced_orders": len(self.synced_orders),
            "master_api_active": self.master_api is not None,
            "slave_api_active": self.slave_api is not None
        }