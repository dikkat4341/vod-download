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
from urllib.parse import urlparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- YAPILANDIRMA ---
ua_file = 'user_agents.txt'
proxy_cache_file = 'turkey_proxies_cache.json'
MAX_RETRIES = 30
DOWNLOAD_DIR_DEFAULT = "Downloads"
MAX_PROXY_COUNT = 200
MIN_PROXY_THRESHOLD = 150
MIN_PROXY_COUNT_INITIAL = 50
CACHE_VALID_HOURS = 24

# GLOBAL DEĞİŞKENLER
PROXY_POOL = []
PROXY_STATS = {}
PROXY_AUTO_ENABLED = True
BACKGROUND_REFRESH_RUNNING = False

# Güncel Türk Proxy Kaynakları (2026)
TURKEY_PROXY_SOURCES = [
    'https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=TR',
    'https://www.proxy-list.download/api/v1/get?type=http&country=TR',
    'https://www.proxy-list.download/api/v1/get?type=https&country=TR',
    'https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt',
    'https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt',
    'https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt',
    'https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt',
    'https://www.proxyscan.io/download?type=http',
]

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

def turkish_to_english_engine(text):
    name, ext = os.path.splitext(text)
    trans = str.maketrans('ıüğöşçİÜĞÖŞÇ -.', 'iugoscIUGOSC___')
    name = name.translate(trans)
    clean_name = re.sub(r'[^a-zA-Z0-9_]', '', name)
    clean_name = re.sub(r'_+', '_', clean_name).strip('_')
    return clean_name + (ext.lower() if ext else ".mp4")

# --- PROXY YÖNETİMİ ---
def load_proxy_cache():
    global PROXY_POOL
    if os.path.exists(proxy_cache_file):
        try:
            with open(proxy_cache_file, 'r') as f:
                data = json.load(f)
                if (time.time() - data.get('timestamp', 0)) / 3600 < CACHE_VALID_HOURS:
                    PROXY_POOL = [{'proxy': p, 'response_time': 0.5} for p in data.get('proxies', [])]
                    print(f"Önbellekten {len(PROXY_POOL)} proxy yüklendi.")
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
        print("\nTürk proxy'ler toplanıyor...")

    all_raw = set()
    for source in TURKEY_PROXY_SOURCES:
        try:
            r = requests.get(source, timeout=15)
            if r.status_code == 200:
                found = re.findall(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5}', r.text)
                all_raw.update([f'http://{ip}' for ip in found])
        except: pass

    unique_raw = list(all_raw)
    new_working = []
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = [executor.submit(check_proxy_location, p) for p in unique_raw]
        for f in tqdm(as_completed(futures), total=len(unique_raw), desc="Proxy Test", disable=background):
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
    global PROXY_POOL, PROXY_STATS
    if not PROXY_POOL: return None
    candidates = [p for p in PROXY_POOL if PROXY_STATS.get(p['proxy'], {}).get('f', 0) < 5]
    return random.choice(candidates[:20]) if candidates else None

def mark_proxy_result(proxy_url, success=True):
    global PROXY_POOL, PROXY_STATS, PROXY_AUTO_ENABLED
    if not proxy_url or not PROXY_AUTO_ENABLED: return
    stats = PROXY_STATS.setdefault(proxy_url, {'s':0, 'f':0})
    if success:
        stats['s'] += 1
    else:
        stats['f'] += 1
        if stats['f'] >= 5:
            PROXY_POOL = [p for p in PROXY_POOL if p['proxy'] != proxy_url]
            background_proxy_refresher()

def initialize_proxy_pool():
    load_ua_pool()
    if not load_proxy_cache() or len(PROXY_POOL) < MIN_PROXY_COUNT_INITIAL:
        collect_turkey_proxies()

# --- ANA FONKSİYONLAR ---
def check_m3u_info(url):
    print("\nXTREAM API Kontrol Ediliyor...")
    proxy = get_random_working_proxy() if PROXY_AUTO_ENABLED else None
    proxies = {'http': proxy['proxy'], 'https': proxy['proxy']} if proxy else None
    try:
        parsed = urlparse(url)
        params = dict(re.findall(r'(\w+)=([^&]+)', parsed.query))
        api_url = f"{parsed.scheme}://{parsed.netloc}/player_api.php?username={params.get('username')}&password={params.get('password')}"
        r = requests.get(api_url, proxies=proxies, timeout=15).json()
        u = r.get('user_info', {})
        exp = datetime.fromtimestamp(int(u.get('exp_date', 0))) if u.get('exp_date') else "Sınırsız"
        print(f"Durum: {u.get('status')} | Bitiş: {exp}")
        print(f"Aktif Bağlantı: {u.get('active_cons',0)} / {u.get('max_connections',0)}")
    except:
        print("API bilgisi alınamadı.")

def parse_m3u_to_categories(content):
    cats = {}
    curr = "Diğer"
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('#EXTINF:'):
            name = re.search(r',(.+)$', line)
            name = name.group(1).strip() if name else "İsimsiz"
            group = re.search(r'group-title="([^"]*)"', line)
            curr = group.group(1) if group else "Belirtilmemiş"
            i += 1
            if i < len(lines) and lines[i].strip().startswith('http'):
                url = lines[i].strip()
                cats.setdefault(curr, []).append((url, name))
        i += 1
    return cats

def select_from_categories(categories):
    if not categories:
        print("Kategori bulunamadı!")
        return "BACK"
    names = sorted(categories.keys())
    print("\n0 - Geri")
    for i, name in enumerate(names, 1):
        print(f"{i} - {name} [{len(categories[name])}]")
    while True:
        try:
            choice = input("\nKategori seç: ").strip()
            if choice == '0': return "BACK"
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                selected = categories[names[idx]]
                break
        except: print("Geçersiz seçim!")
    print("\n0 - Tümünü İndir")
    for i, (_, name) in enumerate(selected, 1):
        print(f"{i} - {name[:70]}")
    choice = input("\nSeçim (0=tümü, virgülle birden fazla): ").strip()
    if not choice or choice == '0': return selected
    result = []
    for n in [x.strip() for x in choice.split(',') if x.strip().isdigit()]:
        result.append(selected[int(n)-1])
    return result or "BACK"

def folder_cleaner():
    path = input("Klasör yolu (boş=Downloads): ").strip() or DOWNLOAD_DIR_DEFAULT
    if not os.path.exists(path):
        print("Klasör bulunamadı!")
        return
    fixed = 0
    for f in os.listdir(path):
        full = os.path.join(path, f)
        if os.path.isfile(full):
            new_name = turkish_to_english_engine(f)
            if f != new_name:
                try:
                    os.rename(full, os.path.join(path, new_name))
                    print(f"{f} → {new_name}")
                    fixed += 1
                except: print(f"Hata: {f}")
    print(f"{fixed} dosya düzeltildi.")

def download_engine(tasks, target_dir):
    if not tasks or tasks == "BACK": return
    os.makedirs(target_dir, exist_ok=True)
    session = requests.Session()
    ua_pool = load_ua_pool()
    success_count = 0
    for url, name in tasks:
        clean_name = turkish_to_english_engine(name)
        path = os.path.join(target_dir, clean_name)
        i = 1
        base, ext = os.path.splitext(clean_name)
        while os.path.exists(path):
            path = os.path.join(target_dir, f"{base}_{i}{ext}")
            i += 1
        success = False
        for retry in range(MAX_RETRIES):
            proxy = get_random_working_proxy() if PROXY_AUTO_ENABLED else None
            proxies = {'http': proxy['proxy'], 'https': proxy['proxy']} if proxy else None
            try:
                with session.get(url, headers={'User-Agent': random.choice(ua_pool)}, proxies=proxies, stream=True, timeout=120) as r:
                    r.raise_for_status()
                    total = int(r.headers.get('content-length', 0))
                    with open(path, 'wb') as f, tqdm(total=total, unit='B', unit_scale=True, desc=os.path.basename(path)[:30]) as bar:
                        for chunk in r.iter_content(1024*1024):
                            if chunk:
                                f.write(chunk)
                                bar.update(len(chunk))
                success = True
                success_count += 1
                mark_proxy_result(proxy['proxy'] if proxy else None, True)
                print(f"Başarılı: {os.path.basename(path)}")
                break
            except Exception as e:
                mark_proxy_result(proxy['proxy'] if proxy else None, False)
                print(f"Hata ({retry+1}): {str(e)[:60]}")
                time.sleep(2)
        if not success:
            print(f"Başarısız: {name}")
    print(f"\nToplam {success_count}/{len(tasks)} indirildi.")

# --- MENÜ ---
def main_menu():
    initialize_proxy_pool()
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"=== VOD PRO v17 ===\nTürk Proxy: {len(PROXY_POOL)} (Otomatik: {'Açık' if PROXY_AUTO_ENABLED else 'Kapalı'})\n")
        print("1 - M3U URL Gir")
        print("2 - M3U Dosya Seç")
        print("3 - API Analiz")
        print("4 - UA Yenile")
        print("5 - İsim Düzelt")
        print("6 - Proxy Ayar")
        print("7 - Çıkış")
        choice = input("\nSeçim: ")
        if choice == '1':
            url = input("M3U URL: ").strip()
            if url:
                try:
                    content = requests.get(url, timeout=20).text
                    cats = parse_m3u_to_categories(content)
                    tasks = select_from_categories(cats)
                    download_engine(tasks, DOWNLOAD_DIR_DEFAULT)
                except: print("URL alınamadı.")
            input("Enter...")
        elif choice == '2':
            file = input("M3U dosya adı: ").strip()
            if os.path.exists(file):
                with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                    cats = parse_m3u_to_categories(f.read())
                tasks = select_from_categories(cats)
                download_engine(tasks, DOWNLOAD_DIR_DEFAULT)
            else:
                print("Dosya yok!")
            input("Enter...")
        elif choice == '3':
            check_m3u_info(input("Xtream URL: "))
            input("Enter...")
        elif choice == '4':
            load_ua_pool(True)
            print("UA yenilendi.")
            input("Enter...")
        elif choice == '5':
            folder_cleaner()
            input("Enter...")
        elif choice == '6':
            global PROXY_AUTO_ENABLED
            print(f"Proxy sayısı: {len(PROXY_POOL)}")
            sub = input("1-Yenile 2-Aç/Kapa 3-Geri: ")
            if sub == '1':
                collect_turkey_proxies()
            elif sub == '2':
                PROXY_AUTO_ENABLED = not PROXY_AUTO_ENABLED
                print(f"Otomatik proxy {'açıldı' if PROXY_AUTO_ENABLED else 'kapatıldı'}.")
            input("Enter...")
        elif choice == '7':
            print("Görüşürüz Serdar!")
            break

if __name__ == "__main__":
    main_menu()
