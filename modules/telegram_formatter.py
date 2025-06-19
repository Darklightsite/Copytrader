# FÁJL: modules/telegram_formatter.py

def format_qty(qty_str: str) -> str:
    """Eltávolítja a felesleges .0 és .0000 végződéseket a mennyiségekről."""
    try:
        num = float(qty_str)
        if num == int(num):
            return str(int(num))
        else:
            return f"{num:.4f}".rstrip('0').rstrip('.')
    except (ValueError, TypeError):
        return qty_str

def format_cycle_summary(events: list, version: str) -> str:
    """Összeállítja a ciklus végi összefoglaló üzenetet a begyűjtött eseményekből."""
    if not events:
        return ""

    header = f"📰 *Ciklus Összefoglaló (v{version})*\n\n"
    sections = {
        "opened": "📈 *Nyitások/Növelések:*\n",
        "closed": "📉 *Zárások:*\n",
        "sl_set": "🛡️ *Stop-Loss Módosítások:*\n"
    }
    
    for event in events:
        event_type = event.get('type')
        data = event.get('data')
        
        if event_type == 'open':
            symbol, side, qty = data.get('symbol'), data.get('side', '').capitalize(), format_qty(data.get('qty', '0'))
            action_text = "Növelve" if data.get('is_increase') else side
            sections["opened"] += f"  - `{symbol}`: {action_text} {qty}\n"
            
        elif event_type == 'close':
            symbol, side, qty = data.get('symbol'), data.get('side', ''), format_qty(data.get('qty', '0'))
            pnl, daily_pnl = data.get('pnl'), data.get('daily_pnl')+data.get('pnl')

            pnl_str = f"Trade PnL: `${pnl:,.2f}`" if pnl is not None else ""
            daily_pnl_str = f" | Mai PnL: `${daily_pnl:,.2f}`" if daily_pnl is not None else ""
            pnl_emoji = "✅" if (pnl or 0) > 0 else "❌" if (pnl or 0) < 0 else "➖"

            sections["closed"] += f"  - `{symbol}` ({side}): Zárva. {pnl_emoji} {pnl_str}{daily_pnl_str}\n"

        elif event_type == 'sl':
            symbol, side, pnl_value = data.get('symbol'), data.get('side', ''), data.get('pnl_value', 0)
            pnl_int = int(round(pnl_value, 0)) # Kerekítés egész számra
            sections["sl_set"] += f"  - `{symbol}` ({side}): `~${pnl_int}`\n"

    final_message = header
    has_content = False
    for key, content in sections.items():
        if len(content.splitlines()) > 1:
            final_message += content + "\n"
            has_content = True

    return final_message if has_content else ""