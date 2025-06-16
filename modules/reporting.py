import logging
import json
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

from modules.api_handler import make_api_request

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

class ReportingManager:
    """Felelős a status.json, pnl_report.json és chart_data.json fájlok generálásáért."""

    # JAVÍTÁS: A konstruktornak fogadnia kell a 'version' argumentumot is.
    def __init__(self, live_api, demo_api, version="N/A"):
        self.live_api = live_api
        self.demo_api = demo_api
        self.version = version
        self.status_file = DATA_DIR / "status.json"
        self.pnl_report_file = DATA_DIR / "pnl_report.json"
        self.live_chart_file = DATA_DIR / "live_chart_data.json"
        self.demo_chart_file = DATA_DIR / "demo_chart_data.json"
        self.activity_file = DATA_DIR / "activity.json"
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _load_json(self, file_path, default_data=None):
        if default_data is None: default_data = {}
        if not file_path.exists(): return default_data
        try:
            with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logging.error(f"Hiba a(z) {file_path} fájl olvasása közben: {e}", exc_info=True); return default_data

    def _save_json(self, file_path, data):
        try:
            with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
        except IOError as e: logging.error(f"Hiba a(z) {file_path} fájl írása közben: {e}", exc_info=True)

    def update_reports(self, pnl_update_needed=False):
        logger = logging.getLogger()
        logger.info("Riportok frissítése...")
        live_account_data = self._get_account_data(self.live_api, "Élő", pnl_update_needed)
        demo_account_data = self._get_account_data(self.demo_api, "Demó", pnl_update_needed)
        self._update_status_report(live_account_data, demo_account_data)
        if pnl_update_needed:
            self._update_pnl_report(live_account_data, demo_account_data)
        self._update_chart_data(live_account_data, demo_account_data)

    def update_activity_log(self, activity_type="copy"):
        logger = logging.getLogger()
        activity_data = self._load_json(self.activity_file, {"last_copy_activity": "Még nem történt", "startup_time": ""})
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if activity_type == "copy": activity_data['last_copy_activity'] = now_str
        elif activity_type == "startup": activity_data['startup_time'] = now_str
        self._save_json(self.activity_file, activity_data)
        logger.info(f"Aktivitás napló frissítve: {activity_type}")

    def _fetch_history_in_chunks(self, api, endpoint, start_time_ms, **extra_params):
        logger = logging.getLogger()
        all_records = []
        current_start_ms = start_time_ms
        end_time_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        logger.info(f"Adatok lekérése 7 napos blokkokban a(z) {endpoint} végpontról...")
        while current_start_ms < end_time_ms:
            chunk_end_ms = min(current_start_ms + int(timedelta(days=7).total_seconds() * 1000) - 1, end_time_ms)
            start_date_str = datetime.fromtimestamp(current_start_ms/1000, tz=timezone.utc).strftime('%Y-%m-%d')
            end_date_str = datetime.fromtimestamp(chunk_end_ms/1000, tz=timezone.utc).strftime('%Y-%m-%d')
            logger.info(f"  Lekérdezési blokk: {start_date_str} -> {end_date_str}")
            cursor = ""
            for _ in range(200):
                params = {"limit": 100, "cursor": cursor, "startTime": int(current_start_ms), "endTime": int(chunk_end_ms), **extra_params}
                response = make_api_request(api, endpoint, "GET", params)
                if response and response.get("retCode") == 0:
                    data = response.get("result", {})
                    records = data.get("list", [])
                    if records: all_records.extend(records)
                    cursor = data.get("nextPageCursor", "")
                    if not cursor: break
                else:
                    error_msg = response.get('retMsg', 'N/A') if response else 'Nincs válasz'
                    logger.warning(f"   Lekérdezési hiba vagy üres válasz a blokkon belül: {error_msg}"); break
                time.sleep(0.5)
            current_start_ms = chunk_end_ms + 1
            time.sleep(0.5)
        unique_records = list({rec.get('orderId', rec.get('execId')): rec for rec in all_records}.values())
        logger.info(f"Összesen {len(unique_records)} egyedi rekord begyűjtve a(z) {endpoint} végpontról.")
        return unique_records

    def _get_account_data(self, api, account_name, pnl_update_needed):
        logger = logging.getLogger()
        logger.debug(f"Adatok gyűjtése: {account_name} számla...")
        
        balance_data = make_api_request(api, "/v5/account/wallet-balance", "GET", {"accountType": "UNIFIED"})
        total_balance = 0
        if balance_data and balance_data.get("retCode") == 0 and balance_data.get('result', {}).get('list'):
            try:
                total_balance = float(balance_data['result']['list'][0]['totalEquity'])
            except (ValueError, IndexError, KeyError):
                logger.warning(f"Nem sikerült beolvasni az egyenleget: {account_name}")

        pos_params = {'category': 'linear', 'settleCoin': 'USDT'}
        positions_data = make_api_request(api, "/v5/position/list", "GET", pos_params)
        positions = positions_data.get('result', {}).get('list', []) if positions_data else []
        active_positions = [p for p in positions if float(p.get('size', '0')) > 0]
        unrealized_pnl = sum(float(p.get('unrealisedPnl', 0)) for p in active_positions)
        position_count = len(active_positions)
        
        pnl_history = []
        if pnl_update_needed:
            start_ms = int((datetime.now(timezone.utc) - timedelta(days=90)).timestamp() * 1000)
            pnl_history = self._fetch_history_in_chunks(api, "/v5/position/closed-pnl", start_ms, category="linear")
        else:
            pnl_report = self._load_json(self.pnl_report_file, {})
            account_report = pnl_report.get(account_name, {})
            pnl_history = account_report.get("raw_history", []) if isinstance(account_report, dict) else []
            
        return {"name": account_name, "balance": total_balance, "unrealized_pnl": unrealized_pnl, "position_count": position_count, "pnl_history": pnl_history or []}

    def _update_status_report(self, live_data, demo_data):
        logger = logging.getLogger()
        status_payload = {
            "version": self.version,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "live_balance": live_data['balance'],
            "demo_balance": demo_data['balance'],
            "live_pnl": live_data['unrealized_pnl'],
            "demo_pnl": demo_data['unrealized_pnl'],
            "live_pos_count": live_data['position_count'],
            "demo_pos_count": demo_data['position_count']
        }
        self._save_json(self.status_file, status_payload)
        logger.info("status.json sikeresen frissítve.")
    
    def _update_pnl_report(self, live_data, demo_data):
        logger = logging.getLogger()
        pnl_report_payload = {
            "Élő": self._calculate_periodic_pnl(live_data['pnl_history']), 
            "Demó": self._calculate_periodic_pnl(demo_data['pnl_history'])
        }
        pnl_report_payload["Élő"]["raw_history"] = live_data['pnl_history']
        pnl_report_payload["Demó"]["raw_history"] = demo_data['pnl_history']
        self._save_json(self.pnl_report_file, pnl_report_payload)
        logger.info("pnl_report.json sikeresen frissítve.")

    def _calculate_periodic_pnl(self, pnl_history):
        now = datetime.now(timezone.utc)
        periods = {"Napi": {"pnl": 0.0, "trade_count": 0}, "Heti": {"pnl": 0.0, "trade_count": 0}, "Havi": {"pnl": 0.0, "trade_count": 0}, "90 Napos": {"pnl": 0.0, "trade_count": 0}, "Teljes": {"pnl": 0.0, "trade_count": 0}}
        start_date = "Nincs rögzített kereskedés"
        if pnl_history:
            timestamps = [int(p['createdTime']) for p in pnl_history if p.get('createdTime')]
            if timestamps: start_date = datetime.fromtimestamp(min(timestamps) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        
        for pnl_entry in pnl_history:
            created_time = datetime.fromtimestamp(int(pnl_entry['createdTime']) / 1000, tz=timezone.utc)
            pnl_value = float(pnl_entry.get('closedPnl', 0))
            days_diff = (now - created_time).days
            periods["Teljes"]["pnl"] += pnl_value
            periods["Teljes"]["trade_count"] += 1
            if days_diff < 1: periods["Napi"]["pnl"] += pnl_value; periods["Napi"]["trade_count"] += 1
            if days_diff < 7: periods["Heti"]["pnl"] += pnl_value; periods["Heti"]["trade_count"] += 1
            if days_diff < 30: periods["Havi"]["pnl"] += pnl_value; periods["Havi"]["trade_count"] += 1
            if days_diff < 90: periods["90 Napos"]["pnl"] += pnl_value; periods["90 Napos"]["trade_count"] += 1
        
        for period_data in periods.values(): period_data["pnl"] = round(period_data["pnl"], 2)
        return {"start_date": start_date, "periods": periods}
    
    def _update_chart_data(self, live_data, demo_data):
        logger = logging.getLogger()
        logger.info("Egyenleggörbe adatainak frissítése...")
        def append_to_chart(file_path, balance):
            if balance is None: return
            try:
                chart_data = self._load_json(file_path, [])
                new_entry = {"time": int(time.time()), "value": round(balance, 4)}
                if not chart_data or chart_data[-1]['value'] != new_entry['value']:
                    chart_data.append(new_entry)
                self._save_json(file_path, chart_data)
            except Exception as e: logger.error(f"Hiba a chart adatfájl ({file_path}) írása közben: {e}", exc_info=True)
        append_to_chart(self.live_chart_file, live_data['balance'])
        append_to_chart(self.demo_chart_file, demo_data['balance'])

    def get_pnl_update_after_close(self, api, symbol):
        logger = logging.getLogger()
        logger.info(f"Friss PnL adatok lekérése a(z) {symbol} bezárása után...")
        start_ms_trade = int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp() * 1000)
        pnl_history_trade = self._fetch_history_in_chunks(api, "/v5/position/closed-pnl", start_ms_trade, category="linear", symbol=symbol)
        if not pnl_history_trade: return None, None
        
        latest_trade = max(pnl_history_trade, key=lambda x: int(x['createdTime']))
        closed_pnl = float(latest_trade.get('closedPnl', 0))
        
        start_ms_daily = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        full_history_daily = self._fetch_history_in_chunks(api, "/v5/position/closed-pnl", start_ms_daily, category="linear")
        daily_pnl = self._calculate_periodic_pnl(full_history_daily).get("periods", {}).get("Napi", {}).get("pnl", 0)
        
        return closed_pnl, daily_pnl
