import os
import requests
import re
import sys
import time
import random
import socket
import glob
from tqdm import tqdm
from urllib.parse import urlparse

# --- YAPILANDIRMA ---
ua_file = 'user_agents.txt'
MAX_RETRIES = 20
DOWNLOAD_DIR_DEFAULT = "Downloads"

# Varsayılan User-Agent Havuzu
DEFAULT_UA = [
    'VLC/3.0.18 LibVLC/3.0.18', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (SMART-TV; Linux; Tizen 6.0) AppleWebkit/537.36 SamsungBrowser/4.0 Safari/537.36',
    'Mag.250/2.2.0 (OS; Linux; Flash; Version/0.2.18-r14-250)', 'GStreamer/1.18.5',
    'AppleCoreMedia/1.0.0.19G82 (iPhone; U; CPU OS 15_6 like Mac OS X)', 'Lavf/58.76.100',
    'Mozilla/5.0 (Web0S; Linux/SmartTV) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.79 Safari/537.36'
]

def get_m3u_file():
    """Klasördeki ilk .m3u uzantılı dosyayı bulur."""
    m3u_files = glob.glob("*.m3u")
    if not m3u_files:
        return None
    return m3u_files[0]

def turkish_to_english(text):
    """Türkçe karakterleri değiştirir ve boşlukları alt çizgi yapar."""
    mapping = {
        'ı': 'i', 'ü': 'u', 'ğ': 'g', 'ö': 'o', 'ş': 's', 'ç': 'c',
        'İ': 'I', 'Ü': 'U', 'Ğ': 'G', 'Ö': 'O', 'Ş': 'S', 'Ç': 'C',
        ' ': '_'
    }
    for tr, en in mapping.items():
        text = text.replace(tr, en)
    # Sadece güvenli karakterleri bırak
    clean = re.sub(r'[^a-zA-Z0-9._-]', '', text)
    return clean

def get_ip_from_url(url):
    """DNS çözümlemesi yaparak domain yerine IP döndürür (DNS engellerini aşmak için)."""
    parsed_url = urlparse(url)
    try:
        ip = socket.gethostbyname(parsed_url.hostname)
        return url.replace(parsed_url.hostname, ip), parsed_url.hostname
    except:
        return url, parsed_url.hostname

def load_user_agents():
    """UA havuzunu yükler, yoksa oluşturur."""
    if not os.path.exists(ua_file):
        with open(ua_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(DEFAULT_UA))
        return DEFAULT_UA
    with open(ua_file, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]

def download_file(url, filename, target_dir):
    os.makedirs(target_dir, exist_ok=True)
    clean_filename = turkish_to_english(filename)
    if not clean_filename.lower().endswith('.mkv'):
        clean_filename += '.mkv'
    
    download_path = os.path.join(target_dir, clean_filename)
    
    # Domain'den IP'ye geçiş ve Host header ayarı
    direct_url, original_host = get_ip_from_url(url)
    ua_list = load_user_agents()
    
    retries = 0
    while retries < MAX_RETRIES:
        selected_ua = random.choice(ua_list)
        headers = {
            'User-Agent': selected_ua,
            'Host': original_host, # IP üzerinden giderken sunucunun rotayı şaşırmaması için şart
            'Connection': 'keep-alive'
        }
        
        try:
            initial_pos = os.path.getsize(download_path) if os.path.exists(download_path) else 0
            
            # Sunucudan dosya boyutu kontrolü
            with requests.head(direct_url, headers=headers, timeout=15, allow_redirects=True) as head:
                total_size = int(head.headers.get('content-length', 0))

            # Boyut Kontrolü (Zaten var mı?)
            if initial_pos >= total_size and total_size != 0:
                print(f"📦 {clean_filename}: Zaten var, boyut kontrolü yapıldı.")
                return True

            if initial_pos > 0:
                headers['Range'] = f'bytes={initial_pos}-'
            
            # İndirme Başlat
            with requests.get(direct_url, headers=headers, stream=True, timeout=25) as r:
                r.raise_for_status()
                mode = 'ab' if initial_pos > 0 else 'wb'
                
                with open(download_path, mode) as f:
                    with tqdm(total=total_size, unit='B', unit_scale=True, desc=clean_filename[:25], initial=initial_pos) as bar:
                        start_time = time.time()
                        downloaded_in_session = 0
                        
                        for chunk in r.iter_content(chunk_size=1024*256): # 256KB parçalar stabilite sağlar
                            if chunk:
                                f.write(chunk)
                                bar.update(len(chunk))
                                downloaded_in_session += len(chunk)
                                
                                # Hız Kontrolü (Hız 1.5 Mbps altına düşerse bağlantıyı tazele)
                                elapsed = time.time() - start_time
                                if elapsed > 8: # İlk 8 saniyeden sonra kontrol et
                                    speed_mbps = (downloaded_in_session / elapsed) * 8 / (1024*1024)
                                    if speed_mbps < 1.5:
                                        raise Exception("Düşük hız algılandı (Hız artırma teknolojisi tetiklendi)...")

            print(f"✅ Tamamlandı: {clean_filename}")
            return True

        except Exception as e:
            retries += 1
            print(f"\n⚠️ Hata: {e}. Yeniden deneniyor ({retries}/{MAX_RETRIES})...")
            time.sleep(2)
    return False

def main():
    print("--- VOD Pro Downloader: Expert Mode v2 ---")
    
    # Otomatik M3U Bulma
    m3u_file = get_m3u_file()
    if not m3u_file:
        print("❌ Hata: Klasörde .m3u dosyası bulunamadı!")
        input("Kapatmak için Enter..."); sys.exit(1)
    
    print(f"📂 Bulunan Liste: {m3u_file}")
    
    # Yol Seçimi
    user_path = input("İndirme yolu (Enter = Downloads): ").strip()
    target_dir = user_path if user_path else DOWNLOAD_DIR_DEFAULT
    
    # M3U İşleme
    with open(m3u_file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    tasks = []
    current_name = ""
    
    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF:'):
            # Virgül sonrası ismi al
            current_name = line.split(',')[-1].strip()
        elif line.startswith('http'):
            if current_name:
                tasks.append((line, current_name))
                current_name = ""

    print(f"🚀 {len(tasks)} adet içerik kuyruğa alındı. İndirme başlıyor...\n")

    for url, name in tasks:
        download_file(url, name, target_dir)

    print("\n--- Tüm liste başarıyla işlendi. ---")
    input("Kapatmak için Enter'a basın...")

if __name__ == "__main__":
    main()
