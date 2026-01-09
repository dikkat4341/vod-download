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
MAX_RETRIES = 50  # Daha fazla deneme
DOWNLOAD_DIR_DEFAULT = "Downloads"
MAX_PROXY_COUNT = 200
MIN_PROXY_THRESHOLD = 150
CACHE_VALID_HOURS = 24

# GLOBAL DEĞİŞKENLER
PROXY_POOL = []
PROXY_STATS = {}
PROXY_AUTO_ENABLED = True  # Hız için açık başlıyor
BACKGROUND_REFRESH_RUNNING = False

# Güncel Türk Proxy Kaynakları
TURKEY_PROXY_SOURCES = [
    'https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=TR',
    'https://www.proxy-list.download/api/v1/get?type=http&country=TR',
    'https://www.proxy-list.download/api/v1/get?type=https&country=TR',
    'https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt',
    'https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt',
    'https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt',
    'https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt',
]

# --- GÜVENLİ DOSYA ADI TEMİZLEME (SADECE İSİM) ---
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
    return '.mp4'

# --- FİNAL DOSYA ADI ---
def get_final_filename(url, m3u_name):
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

# --- PROXY YÖNETİMİ ---
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
        print("\n200 adet çalışan Türk proxy toplanıyor...")
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
    if PROXY_AUTO_ENABLED and (not load_proxy_cache() or len(PROXY_POOL) < 50):
        collect_turkey_proxies()

# --- M3U PARSE ---
def parse_m3u_to_categories(content):
    cats = {}
    curr = "Diğer"
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('#EXTINF:'):
            name_match = re.search(r',(.+)$', line)
            name = name_match.group(1).strip() if name_match else "İsimsiz"
            group_match = re.search(r'group-title="([^"]*)"', line)
            curr = group_match.group(1) if group_match else "Belirtilmemiş"
            i += 1
            if i < len(lines) and lines[i].strip().startswith('http'):
                url = lines[i].strip()
                cats.setdefault(curr, []).append((url, name))
        i += 1
    return cats

# --- KATEGORİ SEÇİM ---
def select_from_categories(categories):
    if not categories:
        print("Kategori bulunamadı.")
        return "BACK"
    names = sorted(categories.keys())
    print("\n0 - GERİ")
    for i, name in enumerate(names, 1):
        print(f"{i} - {name} [{len(categories[name])}]")
    while True:
        choice = input("\nKategori seç: ").strip()
        if choice == '0': return "BACK"
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                selected = categories[names[idx]]
                break
        except: print("Geçersiz seçim.")
    print("\n0 - TÜMÜNÜ İNDİR")
    for i, (_, name) in enumerate(selected, 1):
        print(f"{i} - {name[:70]}")
    choice = input("\nSeçim (0=tümü, virgülle seç): ").strip()
    if not choice or choice == '0': return selected
    result = []
    for n in [x.strip() for x in choice.split(',') if x.strip().isdigit()]:
        try:
            result.append(selected[int(n)-1])
        except: pass
    return result or "BACK"

# --- İSİM DÜZELT ---
def folder_cleaner():
    path = input("Klasör yolu (boş=Downloads): ").strip() or DOWNLOAD_DIR_DEFAULT
    if not os.path.exists(path):
        print("Klasör yok.")
        return
    fixed = 0
    for f in os.listdir(path):
        full = os.path.join(path, f)
        if os.path.isfile(full):
            name, ext = os.path.splitext(f)
            new_name = clean_name_only(name) + ext
            if f != new_name:
                try:
                    new_full = os.path.join(path, new_name)
                    i = 1
                    base, ext2 = os.path.splitext(new_name)
                    while os.path.exists(new_full):
                        new_full = os.path.join(path, f"{base}_{i}{ext2}")
                        i += 1
                    os.rename(full, new_full)
                    print(f"{f} → {os.path.basename(new_full)}")
                    fixed += 1
                except: pass
    print(f"{fixed} dosya düzeltildi.")

# --- İNDİRME MOTORU (HIZ İYİLEŞTİRİLMİŞ) ---
def download_engine(tasks, target_dir):
    if not tasks or tasks == "BACK": return
    os.makedirs(target_dir, exist_ok=True)
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
        session = requests.Session()  # Her dosya için yeni session
        for retry in range(MAX_RETRIES):
            proxy = get_random_working_proxy() if PROXY_AUTO_ENABLED else None
            proxies = {'http': proxy['proxy'], 'https': proxy['proxy']} if proxy else None
            
            try:
                headers = {'User-Agent': random.choice(load_ua_pool())}
                with session.get(url, headers=headers, proxies=proxies, stream=True, timeout=180) as r:
                    r.raise_for_status()
                    total = int(r.headers.get('content-length', 0))
                    with open(out_path, 'wb') as f, tqdm(total=total, unit='B', unit_scale=True, desc=final_name[:40], bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{rate_fmt}]') as bar:
                        for chunk in r.iter_content(chunk_size=16*1024*1024):  # 16MB chunk
                            if chunk:
                                f.write(chunk)
                                bar.update(len(chunk))
                success = True
                success_count += 1
                if proxy: mark_proxy_result(proxy['proxy'], True)
                print(f"TAMAM: {final_name}")
                break
            except Exception as e:
                if proxy: mark_proxy_result(proxy['proxy'], False)
                print(f"Bağlantı kesildi ({retry+1}/{MAX_RETRIES}), 10-30 sn bekleniyor...")
                time.sleep(random.uniform(10, 30))
                session = requests.Session()  # Yeni session
        if not success:
            print(f"BAŞARISIZ (50 denemeden sonra): {m3u_name}")
    
    print(f"\n{success_count}/{len(tasks)} dosya indirildi.")

# --- MENÜ ---
def main_menu():
    initialize_proxy_pool()
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"=== VOD PRO v31 (Hızlı İndirme) ===\nProxy: {len(PROXY_POOL)}/200 (Otomatik: {'Açık' if PROXY_AUTO_ENABLED else 'Kapalı'})\n")
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
                    print(f"Hata: {e}")
            input("\nEnter...")
            
        elif choice == '2':
            file = input("\nM3U dosya adı: ").strip()
            if os.path.exists(file):
                with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                cats = parse_m3u_to_categories(content)
                tasks = select_from_categories(cats)
                download_engine(tasks, DOWNLOAD_DIR_DEFAULT)
            else:
                print("Dosya yok.")
            input("\nEnter...")
            
        elif choice == '3':
            url = input("\nXtream URL: ").strip()
            if url: check_m3u_info(url)
            input("\nEnter...")
            
        elif choice == '4':
            load_ua_pool(True)
            print("UA yenilendi.")
            input("\nEnter...")
            
        elif choice == '5':
            folder_cleaner()
            input("\nEnter...")
            
        elif choice == '6':
            print(f"\nProxy sayısı: {len(PROXY_POOL)}")
            sub = input("1 - Manuel Yenile\n2 - Otomatik Aç/Kapa\n3 - Geri\nSeçim: ").strip()
            if sub == '1':
                collect_turkey_proxies()
            elif sub == '2':
                state = toggle_proxy_auto()
                print(f"Proxy {'AÇILDI' if state else 'KAPATILDI'}")
            input("\nEnter...")
            
        elif choice == '7':
            print("\nGörüşürüz Serdar abi! 🇹🇷\n")
            break

if __name__ == "__main__":
    main_menu()
