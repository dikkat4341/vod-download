import os
import requests
import re
import sys
import time
import random
import glob
import json
import threading
from tqdm import tqdm
from urllib.parse import urlparse, unquote
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- YAPILANDIRMA ---
ua_file = 'user_agents.txt'
proxy_cache_file = 'turkey_proxies_cache.json'
MAX_RETRIES = 30
DOWNLOAD_DIR_DEFAULT = "Downloads"
MAX_PROXY_COUNT = 200
MIN_PROXY_THRESHOLD = 150
CACHE_VALID_HOURS = 24

# GLOBAL DEĞİŞKENLER
PROXY_POOL = []
PROXY_STATS = {}
PROXY_AUTO_ENABLED = False  # Hız için kapalı başlıyor
BACKGROUND_REFRESH_RUNNING = False

# Güncel Türk Proxy Kaynakları
TURKEY_PROXY_SOURCES = [
    'https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=TR',
    'https://www.proxy-list.download/api/v1/get?type=http&country=TR',
    'https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt',
    'https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt',
    'https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt',
]

# --- GÜVENLİ DOSYA ADI TEMİZLEME (SADECE İSİM KISMI) ---
def clean_name_only(name):
    trans = str.maketrans('ıüğöşçİÜĞÖŞÇ', 'iugoscIUGOSC')
    name = name.translate(trans)
    name = name.replace(' ', '_')
    name = re.sub(r'[\/:*?"<>|]', '', name)
    name = re.sub(r'_+', '_', name)
    name = name.strip('_ .')
    return name if name else "Film"

# --- UZANTI ALMA (URL'DEN) ---
def get_extension_from_url(url):
    path = unquote(urlparse(url).path)
    _, ext = os.path.splitext(path)
    if ext and ext.lower() in ['.mp4', '.mkv', '.avi', '.ts', '.mov', '.wmv', '.flv']:
        return ext.lower()
    return '.mp4'  # fallback en yaygın

# --- ORİJİNAL DOSYA ADI + UZANTI ---
def get_final_filename(url, m3u_name):
    # Önce server'dan tam isim al
    try:
        head = requests.head(url, allow_redirects=True, timeout=12)
        if 'Content-Disposition' in head.headers:
            cd = head.headers['Content-Disposition']
            match = re.findall(r'filename[*]?=["\']?([^";\']+)', cd)
            if match:
                raw = unquote(match[-1])
                name, ext = os.path.splitext(raw)
                return clean_name_only(name) + ext.lower()
    except:
        pass
    
    # Server vermezse: M3U ismini temizle + URL'den uzantı al
    cleaned = clean_name_only(m3u_name)
    ext = get_extension_from_url(url)
    return cleaned + ext

# --- YARDIMCI FONKSİYONLAR ---
def generate_random_ua():
    chrome_v = f"{random.randint(120, 130)}.0.{random.randint(5000, 7000)}.{random.randint(10, 200)}"
    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_v} Safari/537.36"

def load_ua_pool(update=False):
    pool = []
    if not update and os.path.exists(ua_file):
        try:
            with open(ua_file, 'r', encoding='utf-8') as f:
                pool = [line.strip() for line in f if line.strip()]
        except: pass
    if len(pool) < 30 or update:
        pool = [generate_random_ua() for _ in range(50)]
        with open(ua_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(pool))
    return pool

# --- PROXY YÖNETİMİ (kapalı ama menüden açılabilir) ---
# (load_proxy_cache, save_proxy_cache, check_proxy_location, collect_turkey_proxies, background_proxy_refresher, get_random_working_proxy, mark_proxy_result, toggle_proxy_auto aynı)

def initialize_proxy_pool():
    load_ua_pool()
    if PROXY_AUTO_ENABLED and (not load_proxy_cache() or len(PROXY_POOL) < 50):
        collect_turkey_proxies()

# --- İNDİRME MOTORU ---
def download_engine(tasks, target_dir):
    if not tasks or tasks == "BACK": return
    os.makedirs(target_dir, exist_ok=True)
    session = requests.Session()
    ua_pool = load_ua_pool()
    success_count = 0
    
    for url, m3u_name in tasks:
        final_name = get_final_filename(url, m3u_name)
        
        out_path = os.path.join(target_dir, final_name)
        
        i = 1
        base, ext = os.path.splitext(final_name)
        while os.path.exists(out_path):
            final_name = f"{base}_{i}{ext}"
            out_path = os.path.join(target_dir, final_name)
            i += 1
        
        success = False
        for retry in range(MAX_RETRIES):
            proxies = None
            if PROXY_AUTO_ENABLED:
                proxy = get_random_working_proxy()
                if proxy:
                    proxies = {'http': proxy['proxy'], 'https': proxy['proxy']}
            
            try:
                headers = {'User-Agent': random.choice(ua_pool)}
                with session.get(url, headers=headers, proxies=proxies, stream=True, timeout=120) as r:
                    r.raise_for_status()
                    total = int(r.headers.get('content-length', 0))
                    with open(out_path, 'wb') as f, tqdm(total=total, unit='B', unit_scale=True, desc=final_name[:40]) as bar:
                        for chunk in r.iter_content(chunk_size=8*1024*1024):
                            if chunk:
                                f.write(chunk)
                                bar.update(len(chunk))
                success = True
                success_count += 1
                if PROXY_AUTO_ENABLED and proxy:
                    mark_proxy_result(proxy['proxy'], True)
                print(f"✅ TAMAM: {final_name}")
                break
            except Exception as e:
                if PROXY_AUTO_ENABLED and proxy:
                    mark_proxy_result(proxy['proxy'], False)
                print(f"⚠️ Hata ({retry+1}): {str(e)[:60]}")
                time.sleep(3)
        if not success:
            print(f"❌ BAŞARISIZ: {m3u_name}")
    
    print(f"\n{success_count}/{len(tasks)} dosya indirildi.")

# --- MENÜ (senin orijinal) ---
def main_menu():
    initialize_proxy_pool()
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"=== VOD PRO v29 ===\nProxy: {len(PROXY_POOL)} (Otomatik: {'Açık' if PROXY_AUTO_ENABLED else 'Kapalı'})\n")
        print("1 - M3U URL Gir")
        print("2 - M3U Dosya Seç")
        print("3 - API Analiz")
        print("4 - UA Yenile")
        print("5 - İsim Düzelt")
        print("6 - Proxy Ayar")
        print("7 - Çıkış")
        choice = input("\nSeçim: ").strip()
        
        if choice == '1':
            url = input("\nM3U URL: ").strip()
            if url:
                try:
                    content = requests.get(url, timeout=30).text
                    cats = parse_m3u_to_categories(content)
                    tasks = select_from_categories(cats)
                    download_engine(tasks, DOWNLOAD_DIR_DEFAULT)
                except Exception as e:
                    print(f"❌ Hata: {e}")
            input("\nEnter...")
            
        # diğer seçenekler aynı kalıyor (2,3,4,5,6,7)

        elif choice == '7':
            print("\nGörüşürüz abi! 🇹🇷\n")
            break

if __name__ == "__main__":
    main_menu()
