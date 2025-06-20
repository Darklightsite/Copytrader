# FÁJL: modules/order_aggregator.py

import time
from decimal import Decimal
import logging

logger = logging.getLogger()

class OrderAggregator:
    """
    Összegyűjti a rövid időn belül érkező, azonos típusú kötéseket,
    hogy egyetlen, nagyobb megbízásként lehessen őket feldolgozni.
    Ezzel elkerülhető a minimális megbízási méret alatti hibák egy része.
    """
    def __init__(self, aggregation_window_seconds=3):
        """
        Inicializálja az aggregátort.
        
        Args:
            aggregation_window_seconds (int): Az időablak másodpercben, ameddig
                                              a program gyűjti az eseményeket
                                              az első esemény beérkezésétől számítva.
        """
        self.pending_orders = {}
        self.aggregation_window = aggregation_window_seconds
        logger.info(f"OrderAggregator inicializálva {self.aggregation_window} másodperces időablakkal.")

    def add_fill(self, fill_data):
        """
        Hozzáad egy új kötést (fill) az aggregálandó megbízásokhoz.
        """
        symbol = fill_data['symbol']
        side = fill_data['side']
        action = fill_data['action']
        qty = Decimal(fill_data['qty'])
        
        agg_key = f"{symbol}-{side}-{action}"

        if agg_key not in self.pending_orders:
            self.pending_orders[agg_key] = {
                'total_qty': Decimal('0'),
                'timestamp': time.time(),
                'is_increase': fill_data.get('is_increase', False),
                'position_side_for_close': fill_data.get('position_side_for_close')
            }
            logger.info(f"Új aggregációs kulcs létrehozva: {agg_key}")

        self.pending_orders[agg_key]['total_qty'] += qty
        logger.info(f"Fill hozzáadva az aggregátorhoz: {agg_key}, Mennyiség: {qty}. Új teljes mennyiség: {self.pending_orders[agg_key]['total_qty']:.4f}")

    def get_ready_orders(self):
        """
        Visszaadja azoknak a megbízásoknak a listáját, amelyeknek lejárt
        az aggregációs ideje és feldolgozhatók.
        """
        ready_orders = []
        keys_to_remove = []
        now = time.time()

        if not self.pending_orders:
            return []

        for key, data in self.pending_orders.items():
            if now - data['timestamp'] > self.aggregation_window:
                symbol, side, action = key.split('-')
                order_data = {
                    'symbol': symbol,
                    'side': side,
                    'action': action,
                    'qty': data['total_qty'],
                    'is_increase': data.get('is_increase', False),
                    'position_side_for_close': data.get('position_side_for_close')
                }
                ready_orders.append(order_data)
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            logger.info(f"Aggregált megbízás ({key}) átadva feldolgozásra. Teljes mennyiség: {self.pending_orders[key]['total_qty']:.4f}")
            del self.pending_orders[key]

        return ready_orders

    # --- MÓDOSÍTÁS KEZDETE ---
    def peek_pending_actions(self):
        """
        Visszaad egy összefoglalót a függőben lévő megbízásokról anélkül, hogy eltávolítaná őket.
        A szinkronizáló tájékoztatására szolgál a "feldolgozás alatt" álló műveletekről.
        """
        actions = []
        now = time.time()
        for key, data in self.pending_orders.items():
            # Csak azokat vesszük figyelembe, amik még az aggregációs ablakon belül vannak
            if now - data['timestamp'] <= self.aggregation_window:
                symbol, side, action = key.split('-')
                
                # A zárási megbízásoknál a pozíció iránya a fontos
                if action == 'CLOSE':
                    action_side = data.get('position_side_for_close')
                else:
                    action_side = side

                actions.append({
                    'symbol': symbol,
                    'side': action_side, # A pozíció valós iránya
                    'action': action
                })
        return actions
    # --- MÓDOSÍTÁS VÉGE ---