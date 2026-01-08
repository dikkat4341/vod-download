# VideoOnDemand Downloader 0.1 beta - Multi-Threaded Version
# Author: Kilian Sommer / Optimized for Speed, EXE & Actions

import os
import requests
import re
import sys
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor

# Yapılandırma
custom_user_agent = 'VLC/3.0.2.LibVLC/3.0.2'
m3u_file = 'download.m3u'
headers = {'User-Agent': custom_user_agent}
MAX_WORKERS = 4  # Aynı anda indirilecek dosya sayısı (İsteğe göre artırılabilir)

def clean_name(name):
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def download_task(item):
    """Her bir dosya için indirme görevini yürütür."""
    url, folder, filename = item
    download_path = os.path.join(folder, filename)
    
    os.makedirs(folder, exist_ok=True)
    local_size = os.path.getsize(download_path) if os.path.exists(download_path) else 0

    try:
        with requests.get(url, headers=headers, stream=True, timeout=30) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('Content-length', 0))

            if total_size != 0 and total_size != local_size:
                with open(download_path, 'wb') as f:
                    # Çoklu indirmede tqdm'i tek bir satırda düzgün göstermek için konum (pos) veriyoruz
                    with tqdm(total=total_size, unit='B', unit_scale=True, desc=filename[:20], leave=False) as bar:
                        for chunk in r.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                bar.update(len(chunk))
                return f"Bitti: {filename}"
            else:
                return f"Atlandı: {filename}"
    except Exception as e:
        return f"Hata: {filename} -> {e}"

def main():
    print(f'--- VOD Downloader Başlatıldı (Çoklu İndirme: {MAX_WORKERS}) ---')
    
    if not os.path.exists(m3u_file):
        print(f'Hata: "{m3u_file}" bulunamadı.')
        input("Kapatmak için Enter'a basın...")
        sys.exit(1)

    try:
        with open(m3u_file, 'r', encoding='utf-8') as file:
            lines = file.readlines()
    except Exception as e:
        print(f'Dosya okuma hatası: {e}')
        sys.exit(1)

    download_list = []
    current_folder = ""

    # M3U dosyasını tara ve indirme listesini oluştur
    for line in lines:
        line = line.strip()
        if not line: continue

        if line.startswith('#EXTINF:'):
            folder_start = line.find('tvg-name="') + len('tvg-name="')
            folder_end = line.find('"', folder_start)
            folder = clean_name(line[folder_start:folder_end])

            name_start = line.find('"', folder_end + 1) + 1
            full_name = line[name_start:].strip()
            
            filename = clean_name(full_name.split(',', 1)[1] if ',' in full_name else full_name) + '.mkv'
            current_folder = folder
            current_filename = filename

        elif line.startswith('http'):
            download_list.append((line, current_folder, current_filename))

    # ThreadPoolExecutor ile çoklu indirmeyi başlat
    print(f'{len(download_list)} dosya kuyruğa alındı. İndirme başlıyor...\n')
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Sonuçları anlık olarak ekrana basar
        for result in executor.map(download_task, download_list):
            print(result)

    print('\n--- Tüm işlemler tamamlandı ---')
    input("Kapatmak için Enter'a basın...")

if __name__ == "__main__":
    main()
