# FÁJL: teszt.py
import logging
import configparser
from telegram.ext import Application, JobQueue
import pytz
import traceback

logging.basicConfig(level=logging.INFO)
print("--- TESZT INDUL ---")

try:
    config = configparser.ConfigParser()
    config.read('config.ini')
    token = config['telegram']['bot_token']
    print(">>> Config beolvasva, token rendben.")

    print(">>> JobQueue létrehozása és időzóna beállítása (a kritikus pont)...")
    # Kézzel beállítjuk az időzónát, hogy kikerüljük az auto-detekciós hibát.
    job_queue = JobQueue()
    job_queue.scheduler.timezone = pytz.utc
    print(">>> Időzóna sikeresen beállítva.")

    # Az Application-t már a kézileg beállított job_queue-val hozzuk létre.
    application = (
        Application.builder()
        .token(token)
        .job_queue(job_queue)
        .build()
    )
    print("--- SIKER! Az Application objektum hiba nélkül létrejött. ---")

except Exception as e:
    print(f"\n--- HIBA! A teszt sikertelen. Hiba oka: ---")
    traceback.print_exc()

print("\n--- TESZT VÉGE ---")