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
MAX_RETRIES = 30
DOWNLOAD_DIR_DEFAULT = "Downloads"

def generate_new_ua():
    """Banlanan UA yerine rastgele taze bir UA üretir."""
    versions = [f"{random.randint(100, 120)}.0.{random.randint(1000, 6000)}.{random.randint(10, 150)}" for _ in range(5)]
    new_uas = [
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.choice(versions)} Safari/537.36",
        f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.choice(versions)} Safari/537.36",
        f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.choice(versions)} Safari/537.36",
        f"VLC/3.0.{random.randint(10, 20)} LibVLC/3.0.{random.randint(10, 20)}",
        f"AppleCoreMedia/1.0.0.{random.randint(10, 30)}G{random.randint(50, 99)} (iPhone; CPU OS 16_5 like Mac OS X)"
    ]
    return random.choice(new_uas)

def load_and_fix_ua_pool():
    """UA havuzunu kontrol eder, 30'un altındaysa tamamlar."""
    pool = []
    if os.path.exists(ua_file):
        with open(ua_file, 'r', encoding='utf-8') as f:
            pool = [line.strip() for line in f if line.strip()]
    
    while len(pool) < 30:
        pool.append(generate_new_ua())
    
    with open(ua_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(pool))
    return pool

def remove_banned_ua(banned_ua):
    """Banlanan UA'yı dosyadan siler ve yerine yenisini ekler."""
    pool = load_and_fix_ua_pool()
    if banned_ua in pool:
        pool.remove(banned_ua)
        pool.append(generate_new_ua())
        with open(ua_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(pool))

def turkish_to_english(text):
    mapping = {
        'ı': 'i', 'ü': 'u', 'ğ': 'g', 'ö': 'o', 'ş': 's', 'ç': 'c',
        'İ': 'I', 'Ü': 'U', 'Ğ': 'G', 'Ö': 'O', 'Ş': 'S', 'Ç': 'C', ' ': '_'
    }
    for tr, en in mapping.items():
        text = text.replace(tr, en)
    return re.sub(r'[^a-zA-Z0-9._-]', '', text)

def get_ip_from_url(url):
    parsed_url = urlparse(url)
    try:
        ip = socket.gethostbyname(parsed_url.hostname)
        return url.replace(parsed_url.hostname, ip), parsed_url.hostname
    except:
        return url, parsed_url.hostname

def download_file(url, filename, target_dir):
    os.makedirs(target_dir, exist_ok=True)
    clean_filename = turkish_to_english(filename)
    if not clean_filename.lower().endswith('.mkv'): clean_filename += '.mkv'
    
    download_path = os.path.join(target_dir, clean_filename)
    direct_url, original_host = get_ip_from_url(url)
    
    retries = 0
    while retries < MAX_RETRIES:
        ua_pool = load_and_fix_ua_pool()
        selected_ua = random.choice(ua_pool)
        headers = {'User-Agent': selected_ua, 'Host': original_host, 'Connection': 'keep-alive'}
        
        try:
            if os.path.exists(download_path) and os.path.getsize(download_path) == 0:
                os.remove(download_path)

            initial_pos = os.path.getsize(download_path) if os.path.exists(download_path) else 0
            
            # Boyut Bilgisi Al (Zorlamalı Mod)
            total_size = 0
            try:
                with requests.head(direct_url, headers=headers, timeout=10, allow_redirects=True) as h:
                    total_size = int(h.headers.get('content-length', 0))
            except: pass # Boyut alınamazsa indirmeye yine de devam et

            if initial_pos >= total_size and total_size != 0:
                print(f"📦 {clean_filename}: Zaten var, boyut kontrolü yapıldı.")
                return True

            if initial_pos > 0: headers['Range'] = f'bytes={initial_pos}-'
            
            with requests.get(direct_url, headers=headers, stream=True, timeout=20) as r:
                if r.status_code in [403, 429, 503]: # Ban durumları
                    remove_banned_ua(selected_ua)
                    raise Exception(f"Sunucu Reddi ({r.status_code}). UA değiştirildi.")
                
                r.raise_for_status()
                actual_total = total_size if total_size > 0 else int(r.headers.get('content-length', 0)) + initial_pos
                
                mode = 'ab' if initial_pos > 0 else 'wb'
                with open(download_path, mode) as f:
                    # Gelişmiş tqdm Barı
                    with tqdm(total=actual_total, unit='B', unit_scale=True, unit_divisor=1024, 
                              desc=f"🚀 {clean_filename[:30]}", initial=initial_pos,
                              bar_format='{desc}: {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt} [{rate_fmt}]') as bar:
                        
                        start_time = time.time()
                        session_data = 0
                        for chunk in r.iter_content(chunk_size=1024*1024):
                            if chunk:
                                f.write(chunk)
                                bar.update(len(chunk))
                                session_data += len(chunk)
                                
                                # Hız Kontrolü
                                elapsed = time.time() - start_time
                                if elapsed > 15:
                                    speed = (session_data / elapsed) * 8 / (1024*1024)
                                    if speed < 1.0: raise Exception("Hız kritik seviyede düşük.")

            if os.path.getsize(download_path) > 0:
                print(f"✅ Bitti: {clean_filename}")
                return True
        except Exception as e:
            retries += 1
            print(f"⚠️ Hata: {e}. Retry: {retries}/{MAX_RETRIES}")
            time.sleep(2)
    return False

def main():
    print("--- VOD Pro Downloader: ULTIMATE EDITION ---")
    m3u_file = glob.glob("*.m3u")[0] if glob.glob("*.m3u") else None
    if not m3u_file: print("❌ M3U bulunamadı!"); return
    
    target_dir = input("Yol (Enter=Downloads): ").strip() or DOWNLOAD_DIR_DEFAULT
    
    # Mevcut isimleri düzelt
    if os.path.exists(target_dir):
        for f in os.listdir(target_dir):
            if f != turkish_to_english(f):
                os.rename(os.path.join(target_dir, f), os.path.join(target_dir, turkish_to_english(f)))

    with open(m3u_file, 'r', encoding='utf-8', errors='ignore') as f:
        tasks = []
        name = ""
        for line in f:
            if line.startswith('#EXTINF:'): name = line.split(',')[-1].strip()
            elif line.startswith('http'): tasks.append((line.strip(), name)); name = ""

    for url, name in tasks: download_file(url, name, target_dir)
    input("\nBitti. Kapatmak için Enter...")

if __name__ == "__main__": main()
