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
MAX_RETRIES = 5  # aria2 kendi retry yapıyor
DOWNLOAD_DIR_DEFAULT = "Downloads"
MAX_PROXY_COUNT = 200
MIN_PROXY_THRESHOLD = 150
CACHE_VALID_HOURS = 24
ARIA2_EXE = "aria2c.exe"  # Windows için
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
    'https://www.proxy-list.download/api/v1/get?type=https&country=TR',
    'https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt',
    'https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt',
    'https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt',
    'https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt',
]

# --- ARIA2 OTOMATİK İNDİRME (ALT KLASÖRLERİ DE KONTROL EDİYOR) ---
def setup_aria2():
    if os.path.exists(ARIA2_EXE):
        return True
    print("🌍 aria2 indiriliyor (hızlı indirme için gerekli)...")
    try:
        r = requests.get(ARIA2_URL, stream=True, timeout=60)
        r.raise_for_status()
        with open(ARIA2_ZIP, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk:
                    f.write(chunk)
        
        with zipfile.ZipFile(ARIA2_ZIP) as z:
            extracted_path = None
            for member in z.namelist():
                if member.endswith('aria2c.exe'):
                    z.extract(member)
                    extracted_path = member
                    break
            if not extracted_path:
                print("❌ aria2c.exe zip içinde bulunamadı!")
                os.remove(ARIA2_ZIP)
                return False
            
            # Alt klasördeyse ana dizine taşı
            if '/' in extracted_path or '\\' in extracted_path:
                os.rename(extracted_path, ARIA2_EXE)
            else:
                os.rename(extracted_path, ARIA2_EXE)
        
        os.remove(ARIA2_ZIP)
        print("✅ aria2c.exe başarıyla indirildi ve hazır!")
        return True
    except Exception as e:
        print(f"❌ aria2 indirilemedi: {e}")
        print("Manuel indirin: https://github.com/aria2/aria2/releases")
        return False

# --- ORİJİNAL DOSYA ADINI ALMA ---
def get_original_filename(url):
    try:
        session = requests.Session()
        # HEAD isteğiyle header'ları al
        head = session.head(url, allow_redirects=True, timeout=12)
        head.raise_for_status()
        
        # Content-Disposition'dan dosya adı
        if 'Content-Disposition' in head.headers:
            cd = head.headers['Content-Disposition']
            filename_match = re.findall(r'filename[*]?=["\']?([^";\']+)', cd)
            if filename_match:
                return unquote(filename_match[-1].strip())
        
        # URL'nin son kısmından
        parsed = urlparse(url)
        path = parsed.path
        filename = os.path.basename(unquote(path))
        if filename and '.' in filename and len(filename) > 4:
            return filename
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
                    print(f"📂 Önbellekten {len(PROXY_POOL)} proxy yüklendi.")
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
        print("\n🇹🇷 200 adet %100 çalışan Türk proxy toplanıyor...")
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
        print(f"✅ {len(PROXY_POOL)} adet çalışan Türk proxy hazır!")

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

# --- ANA FONKSİYONLAR ---
def check_m3u_info(url):
    print("\n🔍 XTREAM API Analizi...")
    proxy = get_random_working_proxy() if PROXY_AUTO_ENABLED else None
    proxies = {'http': proxy['proxy'], 'https': proxy['proxy']} if proxy else None
    try:
        parsed = urlparse(url)
        params = dict(re.findall(r'(\w+)=([^&]+)', parsed.query))
        username = params.get('username')
        password = params.get('password')
        if not username or not password:
            print("❌ Username/password bulunamadı.")
            return
        api_url = f"{parsed.scheme}://{parsed.netloc}/player_api.php?username={username}&password={password}"
        r = requests.get(api_url, proxies=proxies, timeout=15).json()
        u = r.get('user_info', {})
        exp = datetime.fromtimestamp(int(u.get('exp_date', 0))) if u.get('exp_date') else "Sınırsız"
        print(f"🚦 Durum: {u.get('status')}")
        print(f"📅 Bitiş: {exp}")
        print(f"🔗 Bağlantı: {u.get('active_cons',0)} / {u.get('max_connections',0)}")
    except Exception as e:
        print("❌ API hatası.")

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

def select_from_categories(categories):
    if not categories:
        print("❌ Kategori bulunamadı.")
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
        except: print("❌ Geçersiz seçim.")
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

def folder_cleaner():
    path = input("Klasör yolu (boş=Downloads): ").strip() or DOWNLOAD_DIR_DEFAULT
    if not os.path.exists(path):
        print("❌ Klasör yok.")
        return
    fixed = 0
    for f in os.listdir(path):
        full = os.path.join(path, f)
        if os.path.isfile(full):
            new = turkish_to_english_engine(f)
            if f != new:
                try:
                    new_full = os.path.join(path, new)
                    base, ext = os.path.splitext(new)
                    i = 1
                    while os.path.exists(new_full):
                        new_full = os.path.join(path, f"{base}_{i}{ext}")
                        i += 1
                    os.rename(full, new_full)
                    print(f"🔄 {f} → {os.path.basename(new_full)}")
                    fixed += 1
                except: pass
    print(f"\n📊 {fixed} dosya düzeltildi.")

# --- İNDİRME MOTORU (ORİJİNAL DOSYA ADI + ARIA2) ---
def download_engine(tasks, target_dir):
    if not tasks or tasks == "BACK": return
    if not setup_aria2():
        print("❌ aria2 olmadan indirme yapılamıyor.")
        input("Devam için Enter...")
        return
    
    os.makedirs(target_dir, exist_ok=True)
    success_count = 0
    
    for url, fallback_name in tasks:
        # Server'dan orijinal dosya adını al
        original_name = get_original_filename(url)
        if not original_name or len(original_name) < 4:
            original_name = turkish_to_english_engine(fallback_name)  # fallback
        
        out_file = original_name
        out_path = os.path.join(target_dir, out_file)
        
        # Çakışma varsa numara ekle
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
        
        print(f"\nİndiriliyor: {out_file} (server orijinal ismi)")
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                if any(keyword in line for keyword in ['%', 'DL:', 'ETA', 'CN:']):
                    print(line.strip())
            process.wait()
            if process.returncode == 0:
                success_count += 1
                print(f"✅ TAMAMLANDI: {out_file}")
                if proxy: mark_proxy_result(proxy['proxy'], True)
            else:
                print(f"❌ BAŞARISIZ: {fallback_name}")
                if proxy: mark_proxy_result(proxy['proxy'], False)
        except Exception as e:
            print(f"❌ Aria2 hatası: {e}")
            if proxy: mark_proxy_result(proxy['proxy'], False)
    
    print(f"\nToplam {success_count}/{len(tasks)} dosya indirildi (orijinal isimlerle).")

# --- MENÜ ---
def main_menu():
    initialize_proxy_pool()
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"=== VOD PRO v23 (Orijinal İsim + aria2 Hızlı İndirme) ===\n🇹🇷 Proxy: {len(PROXY_POOL)}/200 (Otomatik: {'Açık' if PROXY_AUTO_ENABLED else 'Kapalı'})\n")
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
                    print(f"❌ URL hatası: {e}")
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
                print("❌ Dosya bulunamadı.")
            input("\nEnter...")
            
        elif choice == '3':
            url = input("\nXtream URL: ").strip()
            if url: check_m3u_info(url)
            input("\nEnter...")
            
        elif choice == '4':
            load_ua_pool(True)
            print("✅ UA havuzu yenilendi.")
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
                print(f"✅ Proxy otomatik {'AÇILDI' if state else 'KAPATILDI'}")
            input("\nEnter...")
            
        elif choice == '7':
            print("\n👋 Görüşürüz Serdar abi! İyi indirimler! 🇹🇷\n")
            break

if __name__ == "__main__":
    main_menu()
