# VideoOnDemand Downloader 0.1 beta - Multi-Threaded Series Version
# Author: Kilian Sommer / Optimized by IPTV Expert
# Target: Series with Season/Episode structure

import os
import requests
import re
import sys
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor

# --- Konfiguration ---
custom_user_agent = 'VLC/3.0.2.LibVLC/3.0.2'
m3u_file = 'download.m3u'
headers = {'User-Agent': custom_user_agent}
MAX_WORKERS = 5  # Anzahl der gleichzeitigen Downloads

def clean_name(name):
    """Reinigt Dateinamen von ungültigen Zeichen für Windows/Linux."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def download_episode(item):
    """Funktion für den einzelnen Download-Task (Thread)."""
    url, main_folder, sub_folder, filename = item
    
    # Pfad-Logik für Serien (Main/Season/Episode)
    if sub_folder:
        target_dir = os.path.join(main_folder, sub_folder)
    else:
        target_dir = main_folder

    os.makedirs(target_dir, exist_ok=True)
    download_path = os.path.join(target_dir, filename)

    # Resume-Check (Überprüfung der Dateigröße)
    local_size = os.path.getsize(download_path) if os.path.exists(download_path) else 0

    try:
        # Stream=True ist wichtig für große Videodateien
        with requests.get(url, headers=headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('Content-length', 0))

            if total_size != 0 and total_size != local_size:
                with open(download_path, 'wb') as f:
                    # leave=False verhindert Chaos in der Konsole bei Multithreading
                    with tqdm(total=total_size, unit='B', unit_scale=True, desc=filename[:25], leave=False) as bar:
                        for chunk in r.iter_content(chunk_size=16384): # Optimierte Chunk-Größe
                            if chunk:
                                f.write(chunk)
                                bar.update(len(chunk))
                return f"✅ Abgeschlossen: {filename}"
            else:
                return f"ℹ️ Übersprungen (Bereits vorhanden): {filename}"
    except Exception as e:
        return f"❌ Fehler bei {filename}: {str(e)}"

def main():
    print(f'--- VOD Series Downloader (Multithreading: {MAX_WORKERS}) ---')
    
    if not os.path.exists(m3u_file):
        print(f'Fehler: "{m3u_file}" wurde nicht gefunden.')
        input("Drücken Sie Enter zum Beenden...")
        sys.exit(1)

    try:
        with open(m3u_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Fehler beim Lesen der M3U: {e}")
        sys.exit(1)

    download_queue = []
    current_main_folder = ""
    current_sub_folder = ""
    current_filename = ""

    # Parsing der M3U Datei
    for line in lines:
        line = line.strip()
        if not line: continue

        if line.startswith('#EXTINF:'):
            # Extraktion der Infos (tvg-name Logik beibehalten)
            folder_start = line.find('tvg-name="') + len('tvg-name="')
            folder_end = line.find('"', folder_start)
            folder = clean_name(line[folder_start:folder_end])

            name_start = line.find('"', folder_end + 1) + 1
            full_name = line[name_start:].strip()
            
            # Dateiname aus dem Namen nach dem Komma extrahieren
            raw_filename = full_name.split(',', 1)[1].strip().replace('/', '_') if ',' in full_name else full_name
            filename = clean_name(raw_filename) + '.mkv'

            # Serien-Struktur Logik (S01, E01 etc.)
            parts = filename.split('S0', 1)
            if len(parts) > 1:
                main_f = parts[0].strip()
                sub_f = 'S0' + parts[1].split('E', 1)[0].strip()
            else:
                main_f = folder
                sub_f = ""
            
            current_main_folder = main_f
            current_sub_folder = sub_f
            current_filename = filename

        elif line.startswith('http'):
            download_queue.append((line, current_main_folder, current_sub_folder, current_filename))

    print(f'{len(download_queue)} Episoden in der Warteschlange. Starte Downloads...\n')

    # Start des Multithreading-Pools
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Ergebnisse werden ausgegeben, sobald ein Thread fertig ist
        for result in executor.map(download_episode, download_queue):
            print(result)

    print('\n--- Alle Serien-Downloads abgeschlossen ---')
    input("Drücken Sie Enter zum Beenden...")

if __name__ == "__main__":
    main()
