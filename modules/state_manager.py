import json
import logging
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

class StateManager:
    """Osztály a program állapotának (state) mentésére és betöltésére."""
    def __init__(self, file_name="copier_state.json"):
        self.file_path = DATA_DIR / file_name
        self.state = {"last_processed_exec_id": None, "position_map": {}}
        self.load()

    def load(self):
        """Betölti az állapotot a JSON fájlból."""
        logger = logging.getLogger()
        if not self.file_path.exists():
            logger.info("Állapotfájl nem található, új lesz létrehozva.")
            return
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.state = json.load(f)
            logger.info("Állapot sikeresen betöltve a fájlból.")
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Hiba az állapotfájl betöltésekor: {e}.")
            self.state = {"last_processed_exec_id": None, "position_map": {}}

    def save(self):
        """Elmenti a jelenlegi állapotot a JSON fájlba."""
        logger = logging.getLogger()
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=4)
        except IOError as e:
            logger.critical(f"KRITIKUS HIBA: Az állapotfájl mentése sikertelen! {e}")

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
        return self.get_mapped_position_key(symbol, side) in self.state.get("position_map", {})

    def map_position(self, symbol, side):
        """Rögzít egy új, követett pozíciót."""
        logger = logging.getLogger()
        key = self.get_mapped_position_key(symbol, side)
        self.state["position_map"][key] = True
        logger.info(f"Pozíció leképezve: {key}")
        self.save()

    def remove_mapping(self, symbol, side):
        """Töröl egy pozíciót a követettek listájából."""
        logger = logging.getLogger()
        key = self.get_mapped_position_key(symbol, side)
        if key in self.state.get("position_map", {}):
            del self.state["position_map"][key]
            logger.info(f"Leképezés törölve: {key}")
            self.save()

