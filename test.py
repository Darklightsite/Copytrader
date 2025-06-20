# FÁJL: test_order_lookup.py (Végleges, javított teszt program)
# Leírás: Ez a szkript kizárólag a meglévő, módosítatlan modulokat használja
# a megadott Order ID-k részleteinek lekérdezéséhez.

import logging
from pprint import pprint
import sys

# A fő program moduljainak importálása a helyes nevekkel
# A program feltételezi, hogy a 'modules' mappa a script mellett van.
try:
    from modules.config_loader import load_configuration
    from modules.api_handler import make_api_request
except ImportError as e:
    print(f"Hiba a modulok betöltése közben: {e}")
    print("Győződj meg róla, hogy a szkriptet a projekt gyökérkönyvtárából futtatod,")
    print("és a 'modules' mappa a helyén van.")
    sys.exit(1)


# --- KONFIGURÁCIÓ ---
# Add meg itt a keresendő Order ID-ket.
ORDER_IDS_TO_CHECK = [
    '169421833',  # Az EURUSD pozíció azonosítója
    '169422965'   # A DE40 pozíció azonosítója
]
# ---------------------


def setup_basic_logging():
    """Egyszerű naplózást állít be a konzolra, hogy lássuk a háttérfolyamatokat."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s',
        stream=sys.stdout,
    )

def run_order_investigation():
    """
    Lekérdezi és kiírja a megadott Order ID-k részleteit a forrásfiókról.
    """
    print("--- Order ID Nyomozó Program ---")
    setup_basic_logging()

    # 1. Konfiguráció betöltése a fő program függvényével
    config = load_configuration('config.ini')
    if not config:
        logging.error("Nem sikerült betölteni a konfigurációt. A program leáll.")
        return

    # 2. A forrás ('Élő') fiók API adatainak kinyerése
    # A config.ini alapján a te esetedben az 'Élő' fiók a 'demo_api' alatt van.
    source_api_config = config.get('demo_api')
    if not source_api_config:
        logging.error("A 'demo_api' szekció nem található a konfigurációban.")
        return

    logging.info(f"A nyomozás a '{source_api_config.get('url')}' szerveren történik.")
    print("-" * 50)

    # 3. Order ID-k lekérdezése egyenként
    for order_id in ORDER_IDS_TO_CHECK:
        logging.info(f"Keresés a következő Order ID-re: {order_id}")

        # A Bybit V5 API végpontja az előzmények lekérdezésére: /v5/order/history
        # A szűréshez használhatjuk az 'orderId' paramétert.
        params = {
            'category': 'linear',
            'orderId': order_id
        }

        # API hívás a fő program meglévő függvényével
        response = make_api_request(
            api_config=source_api_config,
            endpoint="/v5/order/history",
            method="GET",
            params=params
        )

        # 4. Válasz feldolgozása
        if response and response.get('retCode') == 0:
            order_list = response.get('result', {}).get('list', [])
            if order_list:
                print(f"✅ A(z) {order_id} ID-jű megbízás adatai MEGTALÁLVA:")
                # A pprint "szépen" formázva írja ki a kapott adatokat
                pprint(order_list[0])
            else:
                print(f"❌ A(z) {order_id} ID-jű megbízás NEM TALÁLHATÓ a bróker rendszerében ezen a fiókon.")
        else:
            print(f"API hiba a(z) {order_id} lekérdezésekor. A kapott válasz:")
            pprint(response)

        print("-" * 50)

    print("--- A nyomozás befejeződött. ---")


if __name__ == "__main__":
    run_order_investigation()