import os
import requests
import re
import sys
import time
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Ayarlar ---
custom_user_agent = 'VLC/3.0.2.LibVLC/3.0.2'
m3u_file = 'download.m3u'
MAX_WORKERS = 4  # Aynı anda kaç dosya insin?
DOWNLOAD_DIR = "Downloads" # Tüm indirmeler burada toplanacak

# Bağlantı hatalarını (IncompleteRead dahil) aşmak için Session yapılandırması
def get_session():
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelcelist=[500, 502, 503, 504])
    session.mount('http://', HTTPAdapter(max_retries=retries))
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session

def clean_name(name):
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def download_task(item):
    url, main_folder, sub_folder, filename = item
    
    # Klasörleme Mantığı: Her şeyi Downloads içinde topluyoruz
    if main_folder:
        # Dizi ise: Downloads/Dizi_Adi/S01/bolum.mkv
        target_dir = os.path.join(DOWNLOAD_DIR, clean_name(main_folder), clean_name(sub_folder))
    else:
        # Film ise: Downloads/film.mkv
        target_dir = DOWNLOAD_DIR

    os.makedirs(target_dir, exist_ok=True)
    download_path = os.path.join(target_dir, filename)
    
    headers = {'User-Agent': custom_user_agent}
    session = get_session()

    try:
        # IncompleteRead hatasına karşı stream kontrolü
        with session.get(url, headers=headers, stream=True, timeout=30) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('Content-length', 0))
            
            # Eğer dosya zaten tam inmişse atla
            if os.path.exists(download_path) and os.path.getsize(download_path) == total_size:
                return f"✅ Atlandı (Zaten var): {filename}"

            with open(download_path, 'wb') as f:
                with tqdm(total=total_size, unit='B', unit_scale=True, desc=filename[:20], leave=False) as bar:
                    for chunk in r.iter_content(chunk_size=1024*1024): # 1MB'lık parçalarla oku
                        if chunk:
                            f.write(chunk)
                            bar.update(len(chunk))
            return f"✅ İndi: {filename}"
            
    except Exception as e:
        # Hata olsa bile dosyayı silme, belki manuel müdahale gerekir ama bildir
        return f"❌ Hata ({filename}): {str(e)}"

def main():
    print(f'--- VOD Downloader Pro v1.0 (Klasör Düzenlenmiş & Retry Eklenmiş) ---')
    
    if not os.path.exists(m3u_file):
        print(f'Hata: {m3u_file} bulunamadı.')
        input("Kapatmak için Enter'a basın..."); sys.exit(1)

    with open(m3u_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    download_queue = []
    current_main, current_sub, current_file = "", "", ""

    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF:'):
            # tvg-name'den dizi adını veya klasör adını çek
            folder_match = re.search(r'tvg-name="([^"]+)"', line)
            folder_raw = folder_match.group(1) if folder_match else ""
            
            name_part = line.split(',')[-1].strip()
            filename = clean_name(name_part.replace('/', '_')) + '.mkv'

            # Dizi mi Film mi ayrımı (S01/E01 kontrolü)
            if 'S0' in filename and 'E' in filename:
                parts = filename.split('S0', 1)
                current_main = parts[0].strip()
                current_sub = 'S0' + parts[1].split('E', 1)[0].strip()
            else:
                current_main = "" # Film ise ana klasör yok
                current_sub = ""

            current_file = filename

        elif line.startswith('http'):
            download_queue.append((line, current_main, current_sub, current_file))

    print(f'{len(download_queue)} dosya analiz edildi. "Downloads" klasörüne indirme başlıyor...\n')

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for result in executor.map(download_task, download_queue):
            print(result)

    print('\n--- İşlem Tamamlandı ---')
    input("Kapatmak için Enter'a basın...")

if __name__ == "__main__":
    main()
