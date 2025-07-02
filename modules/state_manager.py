import json
import logging
from pathlib import Path
from modules.logger_setup import send_admin_alert

logger = logging.getLogger()

class StateManager:
    """
    Osztály a program állapotának (last_processed_exec_id, position_map)
    mentésére és betöltésére egy központi data könyvtárból.
    """
    def __init__(self, data_dir: Path):
        self.file_path = data_dir / "copier_state.json"
        self._is_new = not self.file_path.exists()
        self.state = {"last_processed_exec_id": None, "position_map": {}}
        self.load()

    def load(self):
        """Betölti az állapotot a JSON fájlból."""
        if self._is_new:
            logger.info("Állapotfájl nem található, új lesz létrehozva.")
            return # 
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.state = json.load(f)
            logger.info("Állapot sikeresen betöltve a fájlból.")
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Hiba az állapotfájl betöltésekor: {e}.")
            send_admin_alert(f"Hiba az állapotfájl betöltésekor: {e}.", user=str(self.file_path.parent.name), account=str(self.file_path.name))
            # Hiba esetén visszaállunk egy üres állapotra a biztonság kedvéért
            self.state = {"last_processed_exec_id": None, "position_map": {}} # 
    
    def is_new_state(self):
        """Visszaadja, hogy a state fájl újonnan lett-e létrehozva."""
        return self._is_new
        
    def save(self):
        """Elmenti a jelenlegi állapotot a JSON fájlba."""
        # Biztosítjuk, hogy a szülő könyvtár létezik
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f: # 
                json.dump(self.state, f, indent=4)
        except IOError as e:
            logger.critical(f"KRITIKUS HIBA: Az állapotfájl mentése sikertelen! {e}") # 
            send_admin_alert(f"KRITIKUS HIBA: Az állapotfájl mentése sikertelen! {e}", user=str(self.file_path.parent.name), account=str(self.file_path.name))

    def get_last_id(self):
        """Visszaadja az utoljára feldolgozott esemény ID-jét."""
        return self.state.get("last_processed_exec_id")

    def set_last_id(self, exec_id):
        """Beállítja az utoljára feldolgozott esemény ID-jét és ment."""
        self.state["last_processed_exec_id"] = exec_id
        self.save()

    def get_mapped_position_key(self, symbol, side):
        """Generál egy egyedi kulcsot a pozícióhoz."""
        return f"{symbol}-{side}"

    def is_position_mapped(self, symbol, side):
        """Ellenőrzi, hogy egy pozíció már követve van-e."""
        return self.get_mapped_position_key(symbol, side) in self.state.get("position_map", {}) # 

    def map_position(self, symbol, side):
        """Rögzít egy új, követett pozíciót."""
        key = self.get_mapped_position_key(symbol, side)
        if not self.is_position_mapped(symbol, side):
            self.state.setdefault("position_map", {})[key] = True
            logger.info(f"Pozíció leképezve: {key}")
            self.save() # 

    def remove_mapping(self, symbol, side):
        """Töröl egy pozíciót a követettek listájából."""
        key = self.get_mapped_position_key(symbol, side)
        if self.is_position_mapped(symbol, side):
            # A 'del' biztonságosabb, mint a pop, ha nem kell a visszatérési érték
            del self.state["position_map"][key]
            logger.info(f"Leképezés törölve: {key}")
            self.save()
