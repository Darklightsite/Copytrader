# FÁJL: modules/telegram_formatter.py (Teljes, javított kód)

from collections import defaultdict

def format_qty(qty_str: str) -> str:
    """Eltávolítja a felesleges .0 és .0000 végződéseket a mennyiségekről."""
    try:
        num = float(qty_str)
        if num == int(num):
            return str(int(num))
        else:
            # Biztonságos formázás, amely elkerüli a tudományos jelölést
            return f"{num:.8f}".rstrip('0').rstrip('.')
    except (ValueError, TypeError):
        return qty_str

def format_cycle_summary(events: list, version: str) -> str:
    """
    Összeállítja a ciklus végi összefoglaló üzenetet a begyűjtött eseményekből,
    szimbólumok szerint csoportosítva.
    """
    if not events:
        return ""

    header = f"📰 *Ciklus Összefoglaló (v{version})*\n\n"
    
    # Események csoportosítása szimbólum szerint
    events_by_symbol = defaultdict(list)
    for event in events:
        if 'symbol' in event.get('data', {}):
             events_by_symbol[event['data']['symbol']].append(event)

    final_message = header
    has_content = False

    for symbol, symbol_events in events_by_symbol.items():
        # Csak akkor adjuk hozzá a szimbólum fejlécét, ha van hozzá esemény
        if symbol_events:
            final_message += f"⦿ `{symbol}`\n"
            has_content = True
        
        for event in symbol_events:
            event_type = event.get('type')
            data = event.get('data')
            
            if event_type == 'open':
                side = data.get('side', '')
                side_display = "Long" if side == 'Buy' else "Short" if side == 'Sell' else side
                qty = format_qty(data.get('qty', '0'))
                
                # JAVÍTÁS: Különbséget teszünk a nyitás és a növelés között, és mindkét esetben kiírjuk az irányt
                if data.get('is_increase'):
                    action_text = f"{side_display} növelés" # Pl.: "Long növelés"
                else:
                    action_text = f"{side_display} nyitás" # Pl.: "Short nyitás"
                
                final_message += f"  - 📈 {action_text}: {qty} db\n"
            
            elif event_type == 'close':
                side = data.get('side', '') # Ez a pozíció oldala (pl. Buy a long pozíciónál)
                side_display = "Long" if side == 'Buy' else "Short" if side == 'Sell' else side
                
                pnl = data.get('pnl')
                daily_pnl = data.get('daily_pnl')

                if daily_pnl is None:
                    daily_pnl = 0.0

                pnl_str = f"Trade PnL: `${pnl:,.2f}`" if pnl is not None else "Trade PnL: $N/A"
                daily_pnl_str = f"| Mai PnL: `${daily_pnl:,.2f}`"
                pnl_emoji = "✅" if (pnl or 0) > 0 else "❌" if (pnl or 0) < 0 else "➖"

                # Az olvashatóság kedvéért a PnL sorokat új sorba tördeljük behúzással
                final_message += f"  - 📉 {side_display} pozíció zárva. {pnl_emoji}\n    `{pnl_str} {daily_pnl_str}`\n"

            elif event_type == 'sl':
                side = data.get('side', '')
                side_display = "Long" if side == 'Buy' else "Short" if side == 'Sell' else side
                pnl_value = data.get('pnl_value', 0)
                pnl_int = int(round(pnl_value, 0))
                final_message += f"  - 🛡️ SL módosítva ({side_display}): `~${pnl_int}`\n"
        
        # Üres sor két szimbólum között
        final_message += "\n"

    # Az üzenet végéről levágjuk a felesleges üres sorokat
    return final_message.strip() if has_content else ""