import os
import requests
import re
import sys
import time
import random
import glob
import json
import threading
import subprocess
import zipfile
from tqdm import tqdm
from urllib.parse import urlparse, unquote
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- YAPILANDIRMA ---
ua_file = 'user_agents.txt'
proxy_cache_file = 'turkey_proxies_cache.json'
DOWNLOAD_DIR_DEFAULT = "Downloads"
MAX_PROXY_COUNT = 200
MIN_PROXY_THRESHOLD = 150
CACHE_VALID_HOURS = 24
ARIA2_EXE = "aria2c.exe"
ARIA2_ZIP = "aria2.zip"
ARIA2_URL = "https://github.com/aria2/aria2/releases/download/release-1.37.0/aria2-1.37.0-win-64bit-build1.zip"

# GLOBAL DEĞİŞKENLER
PROXY_POOL = []
PROXY_STATS = {}
PROXY_AUTO_ENABLED = True
BACKGROUND_REFRESH_RUNNING = False

# Güncel Türk Proxy Kaynakları
TURKEY_PROXY_SOURCES = [
    'https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=TR',
    'https://www.proxy-list.download/api/v1/get?type=http&country=TR',
    'https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt',
    'https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt',
    'https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt',
]

# --- ARIA2 SETUP (GÜVENLİ EXTRACT) ---
def setup_aria2():
    if os.path.exists(ARIA2_EXE):
        return True
    print("\naria2 indiriliyor (hızlı indirme için)...")
    try:
        r = requests.get(ARIA2_URL, stream=True, timeout=60)
        r.raise_for_status()
        with open(ARIA2_ZIP, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk: f.write(chunk)
        
        with zipfile.ZipFile(ARIA2_ZIP) as z:
            extracted_path = None
            for member in z.namelist():
                if member.endswith('aria2c.exe'):
                    z.extract(member)
                    extracted_path = member
                    break
            if not extracted_path:
                print("❌ aria2c.exe bulunamadı!")
                return False
            # Taşı ana dizine
            os.rename(extracted_path, ARIA2_EXE)
        
        os.remove(ARIA2_ZIP)
        print("✅ aria2c.exe hazır!")
        return True
    except Exception as e:
        print(f"❌ aria2 indirilemedi: {e}")
        return False

# --- GÜVENLİ DOSYA ADI TEMİZLEME (ORİJİNAL UZANTI KORUNUR) ---
def safe_filename(filename):
    # Türkçe karakterleri düzelt
    trans = str.maketrans('ıüğöşçİÜĞÖŞÇ', 'iugoscIUGOSC')
    filename = filename.translate(trans)
    
    # Boşlukları _ yap
    filename = filename.replace(' ', '_')
    
    # Yasak Windows karakterlerini temizle
    filename = re.sub(r'[\/:*?"<>|]', '', filename)
    
    # Çoklu _ temizle
    filename = re.sub(r'_+', '_', filename)
    
    # Baş/sondaki _ veya . temizle
    filename = filename.strip('_ .')
    
    if not filename:
        filename = "Dosya"
    
    return filename

# --- ORİJİNAL DOSYA ADI + UZANTI ALMA ---
def get_original_filename_and_ext(url):
    try:
        session = requests.Session()
        head = session.head(url, allow_redirects=True, timeout=12)
        head.raise_for_status()
        
        # Content-Disposition'dan
        if 'Content-Disposition' in head.headers:
            cd = head.headers['Content-Disposition']
            match = re.findall(r'filename[*]?=["\']?([^";\']+)', cd)
            if match:
                raw_name = unquote(match[-1])
                name, ext = os.path.splitext(raw_name)
                return safe_filename(name) + ext.lower()
        
        # URL'den dosya adı + uzantı
        path = unquote(urlparse(url).path)
        raw_filename = os.path.basename(path)
        if raw_filename and '.' in raw_filename and len(raw_filename) > 4:
            name, ext = os.path.splitext(raw_filename)
            return safe_filename(name) + ext.lower()
    except:
        pass
    return None

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

# --- PROXY YÖNETİMİ (aynı) ---
def load_proxy_cache():
    global PROXY_POOL
    if os.path.exists(proxy_cache_file):
        try:
            with open(proxy_cache_file, 'r') as f:
                data = json.load(f)
                if (time.time() - data.get('timestamp', 0)) / 3600 < CACHE_VALID_HOURS:
                    PROXY_POOL = [{'proxy': p, 'response_time': 0.5} for p in data.get('proxies', [])]
                    return True
        except: pass
    return False

def save_proxy_cache():
    global PROXY_POOL
    try:
        with open(proxy_cache_file, 'w') as f:
            json.dump({'timestamp': time.time(), 'proxies': [p['proxy'] for p in PROXY_POOL]}, f)
    except: pass

def check_proxy_location(proxy_url, timeout=8):
    proxies = {'http': proxy_url, 'https': proxy_url}
    try:
        start = time.time()
        r = requests.get('http://ip-api.com/json/', proxies=proxies, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            if data.get('countryCode') == 'TR':
                return {'working': True, 'proxy': proxy_url, 'response_time': time.time() - start}
    except: pass
    return {'working': False, 'proxy': proxy_url}

def collect_turkey_proxies(background=False):
    global PROXY_POOL, BACKGROUND_REFRESH_RUNNING
    if BACKGROUND_REFRESH_RUNNING: return
    BACKGROUND_REFRESH_RUNNING = True
    
    if not background:
        print("\n200 adet %100 çalışan Türk proxy toplanıyor...")
    all_raw = set()
    for source in TURKEY_PROXY_SOURCES:
        try:
            r = requests.get(source, timeout=15)
            if r.status_code == 200:
                found = re.findall(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5}', r.text)
                all_raw.update([f'http://{ip}' for ip in found])
        except: pass
    unique_raw = list(all_raw)[:1000]
    new_working = []
    with ThreadPoolExecutor(max_workers=40) as executor:
        futures = [executor.submit(check_proxy_location, p) for p in unique_raw]
        for f in tqdm(as_completed(futures), total=len(unique_raw), desc="Test", disable=background):
            res = f.result()
            if res['working']:
                new_working.append(res)
                if len(new_working) + len(PROXY_POOL) >= MAX_PROXY_COUNT:
                    break
    current = {p['proxy'] for p in PROXY_POOL}
    for p in sorted(new_working, key=lambda x: x['response_time']):
        if p['proxy'] not in current and len(PROXY_POOL) < MAX_PROXY_COUNT:
            PROXY_POOL.append(p)
    PROXY_POOL.sort(key=lambda x: x['response_time'])
    PROXY_POOL = PROXY_POOL[:MAX_PROXY_COUNT]
    save_proxy_cache()
    BACKGROUND_REFRESH_RUNNING = False
    
    if not background:
        print(f"{len(PROXY_POOL)} adet çalışan Türk proxy hazır!")

def background_proxy_refresher():
    if len(PROXY_POOL) < MIN_PROXY_THRESHOLD and not BACKGROUND_REFRESH_RUNNING:
        threading.Thread(target=collect_turkey_proxies, args=(True,), daemon=True).start()

def get_random_working_proxy():
    global PROXY_STATS, PROXY_POOL
    if not PROXY_POOL: return None
    candidates = [p for p in PROXY_POOL if PROXY_STATS.get(p['proxy'], {}).get('f', 0) < 5]
    return random.choice(candidates[:20]) if candidates else None

def mark_proxy_result(proxy_url, success=True):
    global PROXY_POOL, PROXY_STATS
    if not proxy_url: return
    stats = PROXY_STATS.setdefault(proxy_url, {'s':0, 'f':0})
    if success:
        stats['s'] += 1
    else:
        stats['f'] += 1
        if stats['f'] >= 5:
            PROXY_POOL = [p for p in PROXY_POOL if p['proxy'] != proxy_url]
            background_proxy_refresher()

def toggle_proxy_auto():
    global PROXY_AUTO_ENABLED
    PROXY_AUTO_ENABLED = not PROXY_AUTO_ENABLED
    return PROXY_AUTO_ENABLED

def initialize_proxy_pool():
    load_ua_pool()
    if not load_proxy_cache() or len(PROXY_POOL) < 50:
        collect_turkey_proxies()

# --- İNDİRME MOTORU (ORİJİNAL İSİM + UZANTI KORUMA) ---
def download_engine(tasks, target_dir):
    if not tasks or tasks == "BACK": return
    if not setup_aria2():
        print("aria2 olmadan devam edilemiyor.")
        input("Enter...")
        return
    
    os.makedirs(target_dir, exist_ok=True)
    success_count = 0
    
    for url, fallback_name in tasks:
        # Orijinal isim + uzantı al
        original_full = get_original_filename_and_ext(url)
        if not original_full:
            # Fallback: M3U'daki isimden temizle + .mp4 ekle
            original_full = safe_filename(fallback_name) + ".mp4"
        
        out_file = original_full
        out_path = os.path.join(target_dir, out_file)
        
        # Çakışma kontrolü
        i = 1
        base, ext = os.path.splitext(out_file)
        while os.path.exists(out_path):
            out_file = f"{base}_{i}{ext}"
            out_path = os.path.join(target_dir, out_file)
            i += 1
        
        proxy = get_random_working_proxy() if PROXY_AUTO_ENABLED else None
        proxy_str = proxy['proxy'] if proxy else None
        
        cmd = [
            ARIA2_EXE,
            '--max-connection-per-server=16',
            '--split=16',
            '--min-split-size=1M',
            '--max-tries=10',
            '--retry-wait=5',
            '--continue=true',
            '--auto-file-renaming=false',
            '--allow-overwrite=true',
            '--summary-interval=5',
            '--human-readable=true',
            '--console-log-level=warn',
            '--dir=' + target_dir,
            '--out=' + out_file,
            url
        ]
        
        if proxy_str:
            cmd.append('--all-proxy=' + proxy_str)
        
        print(f"\nİndiriliyor: {out_file}")
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                if any(k in line for k in ['%', 'DL:', 'ETA', 'CN:']):
                    print(line.strip())
            process.wait()
            if process.returncode == 0:
                success_count += 1
                print(f"✅ TAMAM: {out_file}")
                if proxy: mark_proxy_result(proxy['proxy'], True)
            else:
                print(f"❌ BAŞARISIZ: {fallback_name}")
                if proxy: mark_proxy_result(proxy['proxy'], False)
        except Exception as e:
            print(f"❌ Hata: {e}")
            if proxy: mark_proxy_result(proxy['proxy'], False)
    
    print(f"\n{success_count}/{len(tasks)} dosya indirildi (orijinal isim + uzantı).")

# --- MENÜ VE DİĞER FONKSİYONLAR (check_m3u_info, parse_m3u_to_categories, select_from_categories, folder_cleaner, main_menu) önceki gibi aynı kalıyor ---

if __name__ == "__main__":
    main_menu()
