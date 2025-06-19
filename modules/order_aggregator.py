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
        # A gyűjtött megbízások tárolására szolgáló szótár.
        # Struktúra: {'ARBUSDT-Buy-OPEN': {'total_qty': Decimal, 'timestamp': float, ...}}
        self.pending_orders = {}
        self.aggregation_window = aggregation_window_seconds
        logger.info(f"OrderAggregator inicializálva {self.aggregation_window} másodperces időablakkal.")

    def add_fill(self, fill_data):
        """
        Hozzáad egy új kötést (fill) az aggregálandó megbízásokhoz.
        """
        symbol = fill_data['symbol']
        side = fill_data['side']
        action = fill_data['action']  # 'OPEN' vagy 'CLOSE'
        qty = Decimal(fill_data['qty'])
        
        # Egyedi kulcs generálása a szimbólum, irány és akció alapján
        agg_key = f"{symbol}-{side}-{action}"

        if agg_key not in self.pending_orders:
            # Ha ez az első esemény ehhez a kulcshoz, létrehozzuk a bejegyzést
            self.pending_orders[agg_key] = {
                'total_qty': Decimal('0'),
                'timestamp': time.time(),
                # Elmentjük az első esemény fontos adatait
                'is_increase': fill_data.get('is_increase', False),
                'position_side_for_close': fill_data.get('position_side_for_close')
            }
            logger.info(f"Új aggregációs kulcs létrehozva: {agg_key}")

        # Hozzáadjuk a mennyiséget a teljeshez
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
            # Ellenőrizzük, hogy eltelt-e elég idő az első esemény óta
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
        
        # Eltávolítjuk a feldolgozásra átadott megbízásokat a gyűjtőből
        for key in keys_to_remove:
            logger.info(f"Aggregált megbízás ({key}) átadva feldolgozásra. Teljes mennyiség: {self.pending_orders[key]['total_qty']:.4f}")
            del self.pending_orders[key]

        return ready_orders