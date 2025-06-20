# FÁJL: modules/reporting.py

import logging
import json
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from .api_handler import make_api_request, get_data

logger = logging.getLogger()

class ReportingManager:
    def __init__(self, live_api, demo_api, data_dir: Path, version, config):
        self.live_api, self.demo_api = live_api, demo_api
        self.data_dir, self.version, self.config = data_dir, version, config
        self.status_file = self.data_dir / "status.json"
        self.pnl_report_file = self.data_dir / "pnl_report.json"
        self.daily_stats_file = self.data_dir / "daily_stats.json"
        self.activity_file = self.data_dir / "activity.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.pnl_cache = {}
        self.live_chart_file = self.data_dir / "live_chart_data.json"
        self.demo_chart_file = self.data_dir / "demo_chart_data.json"

    def _load_json(self, file_path, default_data=None):
        if default_data is None: default_data = {}
        if not file_path.exists(): return default_data
        try:
            with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
        except (json.JSONDecodeError, IOError): return default_data

    def _save_json(self, file_path, data):
        try:
            with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
        except IOError as e: logger.error(f"Hiba a(z) {file_path} írása közben: {e}")

    def _update_chart_data(self, account_data):
        """Hozzáadja az aktuális egyenleg adatpontot a megfelelő chart fájlhoz."""
        account_name = account_data.get('name')
        if not account_name:
            return

        file_path = self.live_chart_file if account_name == "Élő" else self.demo_chart_file
        
        try:
            chart_data = self._load_json(file_path, default_data=[])
            
            new_point = {
                "time": int(time.time()),
                "value": round(account_data.get('balance', 0), 4)
            }

            if chart_data:
                last_point = chart_data[-1]
                if new_point['time'] - last_point.get('time', 0) < 60 and new_point['value'] == last_point.get('value'):
                    return 

            chart_data.append(new_point)
            self._save_json(file_path, chart_data)
            logger.info(f"Chart adatok frissítve a(z) '{account_name}' fiókhoz. Fájl: {file_path.name}")

        except Exception as e:
            logger.error(f"Hiba a chart adatok frissítése közben ({file_path.name}): {e}", exc_info=True)

    def update_activity_log(self, activity_type="copy"):
        """Frissíti az aktivitási naplót (utolsó másolás, indulás ideje)."""
        activity_data = self._load_json(self.activity_file, {"last_copy_activity": "Még nem történt", "startup_time": ""})
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if activity_type == "copy":
            activity_data['last_copy_activity'] = now_str
        elif activity_type == "startup":
            activity_data['startup_time'] = now_str
        self._save_json(self.activity_file, activity_data)
        logger.info(f"Aktivitás napló frissítve: {activity_type}")

    def _update_daily_stats(self, account_data):
        if account_data.get('name', '').lower() != 'demó':
            return
        account_name_key = 'demo'
        today_iso = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        stats = self._load_json(self.daily_stats_file, {})
        account_stats = stats.get(account_name_key, {})
        last_day = account_stats.get('day_start_iso', '')
        current_equity = account_data.get('balance', 0)
        if last_day != today_iso:
            account_stats = {'day_start_iso': today_iso, 'day_start_equity': current_equity, 'day_peak_equity': current_equity}
        else:
            account_stats.setdefault('day_peak_equity', current_equity)
            if current_equity > account_stats['day_peak_equity']:
                account_stats['day_peak_equity'] = current_equity
        stats[account_name_key] = account_stats
        self._save_json(self.daily_stats_file, stats)

    def update_reports(self, pnl_update_needed=False):
        """Frissíti az összes riportot: státusz, PnL, napi statisztikák és chart adatok."""
        logger.info("Riportok frissítése...")
        live_account_data = self._get_account_data(self.live_api, "Élő", pnl_update_needed)
        demo_account_data = self._get_account_data(self.demo_api, "Demó", pnl_update_needed)
        
        self._update_chart_data(live_account_data)
        self._update_chart_data(demo_account_data)
        
        self._update_daily_stats(demo_account_data)
        self._update_status_report(live_account_data, demo_account_data)
        if pnl_update_needed:
            self._update_pnl_report(live_account_data, demo_account_data)

    def _fetch_history_in_chunks(self, api, endpoint, **extra_params):
        """Stabil, 7 napos blokkokban történő lekérdezési logika."""
        all_records = []
        now_utc = datetime.now(timezone.utc)
        
        start_time_ms = extra_params.pop('startTime', None)
        current_start_ms = start_time_ms if start_time_ms is not None else int((now_utc - timedelta(days=729)).timestamp() * 1000)
        end_time_ms = int(now_utc.timestamp() * 1000)

        if current_start_ms >= end_time_ms:
            return []

        logger.info(f"Adatok lekérése {datetime.fromtimestamp(current_start_ms/1000, tz=timezone.utc).strftime('%Y-%m-%d')}-tól/től...")
        
        while current_start_ms < end_time_ms:
            chunk_end_ms = min(current_start_ms + int(timedelta(days=7).total_seconds() * 1000) - 1, end_time_ms)
            cursor = ""
            for _ in range(200): # Max 200 oldal (20,000 rekord) egy 7 napos blokkban
                params = {"limit": 100, "cursor": cursor, "startTime": current_start_ms, "endTime": chunk_end_ms, **extra_params}
                response = make_api_request(api, endpoint, "GET", params)
                if response and response.get("retCode") == 0:
                    data = response.get("result", {})
                    records = data.get("list", [])
                    if records:
                        all_records.extend(records)
                    
                    cursor = data.get("nextPageCursor", "")
                    if not cursor:
                        break
                else:
                    break 
                time.sleep(0.5)
            
            current_start_ms = chunk_end_ms + 1
            time.sleep(0.5)
        
        unique_records = list({rec.get('orderId', rec.get('execId')): rec for rec in all_records}.values())
        logger.info(f"Összesen {len(unique_records)} egyedi rekord begyűjtve a(z) {endpoint} végpontról.")
        return unique_records

    def _get_account_data(self, api, account_name, pnl_update_needed):
        balance_data = get_data(api, "/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        total_balance = float(balance_data['list'][0]['totalEquity']) if balance_data and balance_data.get('list') else 0
        positions_data = get_data(api, "/v5/position/list", {'category': 'linear', 'settleCoin': 'USDT'})
        positions = positions_data.get('list', []) if positions_data else []
        active_positions = [p for p in positions if float(p.get('size', '0')) > 0]
        unrealized_pnl = sum(float(p.get('unrealisedPnl', 0)) for p in active_positions)
        
        pnl_history = self.pnl_cache.get(account_name, [])
        if pnl_update_needed or not pnl_history:
            start_date_str = self.config['settings'].get('demo_start_date') if api.get('is_demo') else self.config['settings'].get('live_start_date')
            start_time_ms = None
            if start_date_str:
                start_time_dt = None
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                    try:
                        start_time_dt = datetime.strptime(start_date_str.strip(), fmt)
                        break
                    except ValueError: pass
                if start_time_dt: start_time_ms = int(start_time_dt.timestamp() * 1000)
            
            fetch_params = {'category': 'linear'}
            if start_time_ms: fetch_params['startTime'] = start_time_ms
            pnl_history = self._fetch_history_in_chunks(api, "/v5/position/closed-pnl", **fetch_params)
            self.pnl_cache[account_name] = pnl_history
        
        return {"name": account_name, "balance": total_balance, "unrealized_pnl": unrealized_pnl, "position_count": len(active_positions), "pnl_history": pnl_history}

    def _update_status_report(self, live_data, demo_data):
        status_payload = {"version": self.version, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"live_balance": live_data['balance'],"demo_balance": demo_data['balance'],"live_pnl": live_data['unrealized_pnl'],"demo_pnl": demo_data['unrealized_pnl'],"live_pos_count": live_data['position_count'],"demo_pos_count": demo_data['position_count']}
        self._save_json(self.status_file, status_payload)

    def _update_pnl_report(self, live_data, demo_data):
        """
        Frissíti a PnL riportot, elmentve az aggregált adatokat és a nyers
        tranzakciós listát is a napokra bontott PnL grafikonhoz.
        """
        pnl_report_payload = {
            "Élő": {
                "summary": self._calculate_periodic_pnl(live_data['pnl_history']),
                "raw_history": live_data['pnl_history']
            },
            "Demó": {
                "summary": self._calculate_periodic_pnl(demo_data['pnl_history']),
                "raw_history": demo_data['pnl_history']
            }
        }
        self._save_json(self.pnl_report_file, pnl_report_payload)
        logger.info("PnL riport (aggregált és nyers) sikeresen frissítve.")

    def _calculate_periodic_pnl(self, pnl_history):
        now_utc, today_utc = datetime.now(timezone.utc), datetime.now(timezone.utc).date()
        start_of_week, start_of_month = today_utc - timedelta(days=today_utc.weekday()), today_utc.replace(day=1)
        periods = {"Mai": {"pnl": 0.0, "trade_count": 0},"Heti": {"pnl": 0.0, "trade_count": 0},"Havi": {"pnl": 0.0, "trade_count": 0},"Teljes": {"pnl": 0.0, "trade_count": 0}}
        if pnl_history and (timestamps := [int(p['createdTime']) for p in pnl_history if p.get('createdTime')]):
            start_date = datetime.fromtimestamp(min(timestamps) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        else: start_date = "N/A"
        for entry in pnl_history:
            created_date_utc = datetime.fromtimestamp(int(entry['createdTime']) / 1000, tz=timezone.utc).date()
            pnl = float(entry.get('closedPnl', 0))
            periods["Teljes"]["pnl"] += pnl; periods["Teljes"]["trade_count"] += 1
            if created_date_utc >= start_of_month: periods["Havi"]["pnl"] += pnl; periods["Havi"]["trade_count"] += 1
            if created_date_utc >= start_of_week: periods["Heti"]["pnl"] += pnl; periods["Heti"]["trade_count"] += 1
            if created_date_utc == today_utc: periods["Mai"]["pnl"] += pnl; periods["Mai"]["trade_count"] += 1
        for data in periods.values(): data["pnl"] = round(data["pnl"], 2)
        return {"start_date": start_date, "periods": periods}
        
    def get_pnl_update_after_close(self, api, symbol):
        """
        Lekérdezi a legutóbbi zárt PnL-t és a teljes napi PnL-t.
        Újrapróbálkozási logikát tartalmaz a megbízhatóság növelése érdekében.
        """
        closed_pnl = None
        
        for i in range(4): # Max 4 próbálkozás
            try:
                start_ms_trade = int((datetime.now(timezone.utc) - timedelta(minutes=15)).timestamp() * 1000)
                pnl_history_trade = get_data(api, "/v5/position/closed-pnl", {'category': 'linear', 'symbol': symbol, 'startTime': start_ms_trade, 'limit': 1})
                if pnl_history_trade and pnl_history_trade.get('list'):
                    closed_pnl = float(pnl_history_trade['list'][0].get('closedPnl', 0))
                    logger.info(f"A legutóbbi trade PnL-je sikeresen lekérdezve: {closed_pnl}")
                    break 
                else:
                    logger.warning(f"Zárt PnL adat még nem elérhető a(z) {symbol} szimbólumra. ({i+1}. próba)")
                    time.sleep(i * 2 + 1) # Növekvő várakozási idő (1, 3, 5 mp)
            except Exception as e:
                logger.error(f"Hiba a PnL lekérdezése közben: {e}", exc_info=True)
                time.sleep(2)
        
        if closed_pnl is None:
            logger.error(f"A PnL adatot több próbálkozás után sem sikerült lekérdezni a(z) {symbol} szimbólumra.")
            
        try:
            start_ms_daily = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            pnl_history_daily_data = get_data(api, "/v5/position/closed-pnl", {'category': 'linear', 'startTime': start_ms_daily})
            daily_pnl = sum(float(p.get('closedPnl', 0)) for p in pnl_history_daily_data.get('list', [])) if pnl_history_daily_data else 0.0
        except Exception:
            logger.error("Hiba a napi PnL lekérdezése közben.", exc_info=True)
            daily_pnl = 0.0
            
        return closed_pnl, daily_pnl