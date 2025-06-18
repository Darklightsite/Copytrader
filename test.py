# FÁJL: chart_merger.py

import json
from pathlib import Path

# --- KONFIGURÁCIÓ ---
# Add meg annak a mappának a nevét, ahova a régi chart fájlokat másoltad.
SOURCE_FOLDER = "charts_to_merge"

# Add meg a kimeneti fájl nevét.
OUTPUT_FILE = "merged_chart_data.json"
# ---------------------

def merge_chart_data():
    """
    Összefűzi egy mappában található összes chart adatfájlt,
    eltávolítja a duplikátumokat, időrendbe rendezi, majd elmenti az eredményt.
    """
    source_path = Path(SOURCE_FOLDER)
    output_path = Path(OUTPUT_FILE)

    if not source_path.is_dir():
        print(f"HIBA: A forrás mappa ('{SOURCE_FOLDER}') nem található.")
        print("Kérlek, hozd létre a mappát, és másold bele az összefűzendő .json fájlokat.")
        return

    all_data_points = []
    
    # 1. Fájlok beolvasása
    json_files = list(source_path.glob('*.json'))
    if not json_files:
        print(f"HIBA: Nem található egyetlen .json fájl sem a(z) '{SOURCE_FOLDER}' mappában.")
        return
        
    print(f"A következő {len(json_files)} fájl feldolgozása következik:")
    for file_path in json_files:
        print(f"  - Beolvasás: {file_path}")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    all_data_points.extend(data)
                else:
                    print(f"    Figyelmeztetés: A(z) {file_path} fájl nem listát tartalmaz, kihagyom.")
        except json.JSONDecodeError:
            print(f"    Hiba: A(z) {file_path} fájl nem érvényes JSON, kihagyom.")
        except Exception as e:
            print(f"    Hiba a(z) {file_path} olvasása közben: {e}")

    if not all_data_points:
        print("Nem sikerült érvényes adatpontokat beolvasni.")
        return
        
    print(f"\nÖsszesen {len(all_data_points)} adatpont beolvasva.")

    # 2. Duplikátumok eltávolítása az időbélyeg alapján
    unique_points = {point['time']: point for point in all_data_points if 'time' in point}
    deduplicated_data = list(unique_points.values())
    print(f"Duplikátumok eltávolítása után {len(deduplicated_data)} egyedi adatpont maradt.")

    # 3. Adatok rendezése időrendbe
    sorted_data = sorted(deduplicated_data, key=lambda p: p['time'])
    print("Adatpontok időrendbe rendezve.")

    # 4. Eredmény mentése
    try:
        with open(output_path, 'w', encoding='utf-8') as f_out:
            json.dump(sorted_data, f_out, indent=4)
        print(f"\n✅ Siker! Az összefűzött és rendezett adatok elmentve ide: {output_path}")
    except Exception as e:
        print(f"\n❌ HIBA: Nem sikerült elmenteni a kimeneti fájlt. Ok: {e}")


if __name__ == '__main__':
    merge_chart_data()
    input("\nA művelet végzett. Nyomj Entert a kilépéshez.")