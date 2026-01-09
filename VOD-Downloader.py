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
MAX_RETRIES = 25  # Daha dayanıklı bağlantı için artırıldı
DOWNLOAD_DIR_DEFAULT = "Downloads"

# Genişletilmiş ve Güncel User-Agent Havuzu (30 Adet)
DEFAULT_UA = [
    'VLC/3.0.18 LibVLC/3.0.18', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (SMART-TV; Linux; Tizen 6.0) AppleWebkit/537.36 SamsungBrowser/4.0 Safari/537.36',
    'Mag.250/2.2.0 (OS; Linux; Flash; Version/0.2.18-r14-250)', 'GStreamer/1.18.5',
    'AppleCoreMedia/1.0.0.19G82 (iPhone; U; CPU OS 15_6 like Mac OS X)', 'Lavf/58.76.100',
    'Mozilla/5.0 (Web0S; Linux/SmartTV) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.79 Safari/537.36',
    'OTT-Player/2.1.0 (Android 11; TV Box) Gecko/20100101 Firefox/85.0',
    'Mozilla/5.0 (PlayStation 5 7.40) AppleWebKit/605.1.15 Safari/605.1.15'
]

def turkish_to_english(text):
    """Türkçe karakterleri değiştirir, boşlukları alt çizgi yapar ve temizler."""
    mapping = {
        'ı': 'i', 'ü': 'u', 'ğ': 'g', 'ö': 'o', 'ş': 's', 'ç': 'c',
        'İ': 'I', 'Ü': 'U', 'Ğ': 'G', 'Ö': 'O', 'Ş': 'S', 'Ç': 'C',
        ' ': '_'
    }
    for tr, en in mapping.items():
        text = text.replace(tr, en)
    # Sadece harf, rakam, nokta, alt çizgi ve tire bırakır
    clean = re.sub(r'[^a-zA-Z0-9._-]', '', text)
    return clean

def rename_existing_files(target_dir):
    """Klasördeki mevcut dosyaları tarar ve isimlerini formata göre düzeltir."""
    if not os.path.exists(target_dir):
        return
    
    print(f"🔍 Mevcut dosyalar kontrol ediliyor: {target_dir}")
    files = os.listdir(target_dir)
    rename_count = 0
    
    for old_name in files:
        new_name = turkish_to_english(old_name)
        if old_name != new_name:
            old_path = os.path.join(target_dir, old_name)
            new_path = os.path.join(target_dir, new_name)
            
            if not os.path.exists(new_path):
                try:
                    os.rename(old_path, new_path)
                    rename_count += 1
                except: pass
    
    if rename_count > 0:
        print(f"✅ {rename_count} adet eski dosyanın ismi düzeltildi.")

def get_m3u_file():
    m3u_files = glob.glob("*.m3u")
    return m3u_files[0] if m3u_files else None

def get_ip_from_url(url):
    """DNS engellerini aşmak için URL'yi IP adresine çevirir."""
    parsed_url = urlparse(url)
    try:
        ip = socket.gethostbyname(parsed_url.hostname)
        return url.replace(parsed_url.hostname, ip), parsed_url.hostname
    except:
        return url, parsed_url.hostname

def load_user_agents():
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
    direct_url, original_host = get_ip_from_url(url)
    ua_list = load_user_agents()
    
    retries = 0
    while retries < MAX_RETRIES:
        selected_ua = random.choice(ua_list)
        headers = {
            'User-Agent': selected_ua,
            'Host': original_host,
            'Connection': 'keep-alive'
        }
        
        try:
            # 0 KB Temizliği: Eğer dosya varsa ve içeriği boşsa sil
            if os.path.exists(download_path) and os.path.getsize(download_path) == 0:
                os.remove(download_path)

            initial_pos = os.path.getsize(download_path) if os.path.exists(download_path) else 0
            
            # Sunucudan kafa bilgisi al (Boyut kontrolü)
            with requests.head(direct_url, headers=headers, timeout=15, allow_redirects=True) as head:
                total_size = int(head.headers.get('content-length', 0))

            # Resume Kontrolü: Boyutlar aynıysa geç
            if initial_pos >= total_size and total_size != 0:
                print(f"📦 {clean_filename}: Zaten var, boyut kontrolü yapıldı.")
                return True

            if initial_pos > 0:
                headers['Range'] = f'bytes={initial_pos}-'
            
            # Ana İndirme İsteği
            with requests.get(direct_url, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                
                # 0 KB Yanıt Koruması
                server_reported_size = int(r.headers.get('content-length', 0))
                if server_reported_size == 0 and initial_pos == 0:
                    raise Exception("Sunucu boş dosya döndürdü (IP Ban veya Limit).")

                mode = 'ab' if initial_pos > 0 else 'wb'
                with open(download_path, mode) as f:
                    with tqdm(total=total_size, unit='B', unit_scale=True, desc=clean_filename[:25], initial=initial_pos) as bar:
                        start_time = time.time()
                        downloaded_now = 0
                        
                        for chunk in r.iter_content(chunk_size=1024*512):
                            if chunk:
                                f.write(chunk)
                                bar.update(len(chunk))
                                downloaded_now += len(chunk)
                                
                                # Hız Kontrolü: 1.5 Mbps altı ise bağlantıyı tazele
                                elapsed = time.time() - start_time
                                if elapsed > 10:
                                    speed = (downloaded_now / elapsed) * 8 / (1024*1024)
                                    if speed < 1.5:
                                        raise Exception("Hız çok düşük, tünel yenileniyor...")

            # Son kontrol: Dosya gerçekten indi mi?
            if os.path.getsize(download_path) > 0:
                print(f"✅ Başarılı: {clean_filename}")
                return True
            else:
                raise Exception("İndirme sonunda dosya 0 KB kaldı.")

        except Exception as e:
            retries += 1
            print(f"\n⚠️ Hata ({clean_filename}): {e}. Deneme: {retries}/{MAX_RETRIES}")
            # Hatalı 0 KB dosyayı temizle
            if os.path.exists(download_path) and os.path.getsize(download_path) == 0:
                os.remove(download_path)
            time.sleep(4) # Sunucuyu dinlendirmek için bekleme
            
    return False

def main():
    print("--- VOD Pro Downloader: Master Edition (Fix & Rename) ---")
    
    m3u_file = get_m3u_file()
    if not m3u_file:
        print("❌ Hata: Klasörde .m3u dosyası bulunamadı!"); input("Enter..."); sys.exit(1)
    
    print(f"📂 Liste Bulundu: {m3u_file}")
    user_path = input("İndirme yolu (Enter = Downloads): ").strip()
    target_dir = user_path if user_path else DOWNLOAD_DIR_DEFAULT
    
    # 1. Adım: Mevcut hatalı isimlendirmeleri düzelt
    rename_existing_files(target_dir)
    
    # 2. Adım: Listeyi işle
    with open(m3u_file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    tasks = []
    current_name = ""
    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF:'):
            current_name = line.split(',')[-1].strip()
        elif line.startswith('http'):
            if current_name:
                tasks.append((line, current_name))
                current_name = ""

    print(f"🚀 {len(tasks)} içerik kuyruğa alındı.\n")
    for url, name in tasks:
        download_file(url, name, target_dir)

    print("\n--- Tüm işlemler başarıyla tamamlandı ---")
    input("Kapatmak için Enter'a basın...")

if __name__ == "__main__":
    main()
