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
MAX_PROXY_COUNT = 200          # Maksimum proxy sayısı
MIN_PROXY_THRESHOLD = 150      # Bu sayının altına düşerse otomatik yenileme başlar
MIN_PROXY_COUNT_INITIAL = 50   # İlk açılışta en az bu kadar proxy topla
CACHE_VALID_HOURS = 24         # Önbellek ne kadar süre geçerli olsun (saat)

# Proxy yapılandırması
PROXY_POOL = []
PROXY_STATS = {}
PROXY_AUTO_ENABLED = True
BACKGROUND_REFRESH_RUNNING = False

# Güncel ve Çalışan Türk Proxy Kaynakları (2026 itibarıyla aktif olanlar)
TURKEY_PROXY_SOURCES = [
    'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=TR&ssl=all&anonymity=all',
    'https://www.proxy-list.download/api/v1/get?type=http&country=TR',
    'https://www.proxy-list.download/api/v1/get?type=https&country=TR',
    'https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt',
    'https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt',
    'https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt',
    'https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt',
    'https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt',
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
    m = {
        'ı':'i','ü':'u','ğ':'g','ö':'o','ş':'s','ç':'c',
        'İ':'I','Ü':'U','Ğ':'G','Ö':'O','Ş':'S','Ç':'C',
        ' ':'_', '-':'_', '.':'_'
    }
    for tr, en in m.items():
        name = name.replace(tr, en)
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
                age_hours = (time.time() - data.get('timestamp', 0)) / 3600
                if age_hours < CACHE_VALID_HOURS:
                    proxies = data.get('proxies', [])
                    PROXY_POOL = [{'proxy': p, 'response_time': 0.5} for p in proxies]  # varsayılan rt
                    print(f"📂 Önbellekten {len(PROXY_POOL)} proxy yüklendi ({age_hours:.1f} saat önce)")
                    return True
        except Exception as e:
            print(f"Önbellek okuma hatası: {e}")
    return False

def save_proxy_cache():
    with open(proxy_cache_file, 'w') as f:
        json.dump({
            'timestamp': time.time(),
            'proxies': [p['proxy'] for p in PROXY_POOL]
        }, f)

def check_proxy_location(proxy_url, timeout=8):
    proxies = {'http': proxy_url, 'https': proxy_url}
    try:
        start = time.time()
        response = requests.get('http://ip-api.com/json/', proxies=proxies, timeout=timeout)
        rt = time.time() - start
        if response.status_code == 200:
            data = response.json()
            if data.get('countryCode') == 'TR':
                return {
                    'working': True,
                    'proxy': proxy_url,
                    'response_time': rt,
                    'ip': data.get('query')
                }
    except:
        pass
    return {'working': False, 'proxy': proxy_url}

def collect_turkey_proxies(background=False):
    global PROXY_POOL, BACKGROUND_REFRESH_RUNNING
    if not background:
        print("\n🌍 Türk proxy'ler toplanıyor... (Bu biraz sürebilir)")

    all_raw = set()
    for source in TURKEY_PROXY_SOURCES:
        try:
            r = requests.get(source, timeout=12)
            if r.status_code == 200:
                found = re.findall(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5}', r.text)
                for ip_port in found:
                    all_raw.add(f'http://{ip_port}')
        except:
            continue

    unique_raw = list(all_raw)
    new_working = []
    
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(check_proxy_location, p): p for p in unique_raw}
        for future in tqdm(as_completed(futures), total=len(unique_raw), desc="TR Proxy Test", disable=background):
            res = future.result()
            if res['working']:
                new_working.append(res)
                if len(new_working) + len(PROXY_POOL) >= MAX_PROXY_COUNT:
                    break

    new_working.sort(key=lambda x: x['response_time'])
    
    # Mevcut havuzu güncelle (en hızlıları önde)
    current_proxies = {p['proxy'] for p in PROXY_POOL}
    for p in new_working:
        if p['proxy'] not in current_proxies and len(PROXY_POOL) < MAX_PROXY_COUNT:
            PROXY_POOL.append(p)
            current_proxies.add(p['proxy'])

    PROXY_POOL.sort(key=lambda x: x['response_time'])
    PROXY_POOL = PROXY_POOL[:MAX_PROXY_COUNT]  # Max 200

    save_proxy_cache()
    
    if not background:
        print(f"✅ {len(new_working)} yeni çalışan Türk proxy eklendi. Toplam: {len(PROXY_POOL)}")
    
    BACKGROUND_REFRESH_RUNNING = False

def background_proxy_refresher():
    global BACKGROUND_REFRESH_RUNNING
    if BACKGROUND_REFRESH_RUNNING:
        return
    BACKGROUND_REFRESH_RUNNING = True
    threading.Thread(target=collect_turkey_proxies, kwargs={'background': True}, daemon=True).start()

def get_random_working_proxy():
    global PROXY_POOL
    if not PROXY_POOL:
        return None
    # Başarısızları az olanları önceliklendir
    candidates = [p for p in PROXY_POOL if PROXY_STATS.get(p['proxy'], {}).get('f', 0) < 5]
    if not candidates:
        return None
    return random.choice(candidates[:20])  # En hızlı 20'den seç

def mark_proxy_result(proxy_url, success=True):
    if not proxy_url:
        return
    if proxy_url not in PROXY_STATS:
        PROXY_STATS[proxy_url] = {'s': 0, 'f': 0}
    if success:
        PROXY_STATS[proxy_url]['s'] += 1
    else:
        PROXY_STATS[proxy_url]['f'] += 1
        if PROXY_STATS[proxy_url]['f'] > 5:
            global PROXY_POOL
            PROXY_POOL = [p for p in PROXY_POOL if p['proxy'] != proxy_url]
            # Havuz azaldıysa arka planda yenile
            if len(PROXY_POOL) < MIN_PROXY_THRESHOLD:
                background_proxy_refresher()

# İlk yükleme ve kontrol
def initialize_proxy_pool():
    if not load_proxy_cache():
        print("Önbellek yok veya eski → Yeni proxy toplanıyor...")
        collect_turkey_proxies()
    else:
        if len(PROXY_POOL) < MIN_PROXY_COUNT_INITIAL:
            print("Yeterli proxy yok → Ek proxy toplanıyor...")
            collect_turkey_proxies()
    
    # Her durumda azalmayı izle
    if len(PROXY_POOL) < MIN_PROXY_THRESHOLD:
        print("Proxy sayısı düşük → Arka planda yenileme başlatılıyor...")
        background_proxy_refresher()

# --- DİĞER FONKSİYONLAR (önceki kodundan aynı, kısaltarak ekliyorum) ---
# check_m3u_info, folder_cleaner, download_engine, parse_m3u_to_categories, select_from_categories aynı kalıyor
# (Yer tasarrufu için aynı bırakıyorum, önceki mesajımdan kopyala)

def check_m3u_info(url):
    print("\n🔍 XTREAM API Sorgulanıyor...")
    p_info = get_random_working_proxy() if PROXY_AUTO_ENABLED else None
    proxies = {'http': p_info['proxy'], 'https': p_info['proxy']} if p_info else None
    try:
        parsed = urlparse(url)
        params = dict(re.findall(r'(\w+)=([^&]+)', parsed.query))
        username = params.get('username')
        password = params.get('password')
        if not username or not password:
            print("❌ URL'de username/password bulunamadı.")
            return
        api_url = f"{parsed.scheme}://{parsed.netloc}/player_api.php?username={username}&password={password}"
        r = requests.get(api_url, proxies=proxies, timeout=15).json()
        u = r.get('user_info', {})
        status = u.get('status', 'Bilinmiyor')
        exp = u.get('exp_date')
        exp_date = datetime.fromtimestamp(int(exp)).strftime('%d.%m.%Y %H:%M') if exp and int(exp) > 0 else "Sınırsız"
        active = u.get('active_cons', 0)
        max_cons = u.get('max_connections', 0)
        print(f"🚦 Durum: {status}")
        print(f"📅 Bitiş: {exp_date}")
        print(f"🔗 Bağlantı: {active} / {max_cons}")
    except Exception as e:
        print("❌ API bilgisi alınamadı:", str(e))

def folder_cleaner(path=None):
    if not path:
        path = input("Klasör yolu (boşsa Downloads): ").strip() or DOWNLOAD_DIR_DEFAULT
    if not os.path.exists(path):
        print("❌ Klasör bulunamadı.")
        return
    files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
    fixed, clean, error = 0, 0, 0
    print(f"\n🛠 {len(files)} dosya denetleniyor...\n")
    for f in files:
        old_path = os.path.join(path, f)
        new_name = turkish_to_english_engine(f)
        new_path = os.path.join(path, new_name)
        if f == new_name:
            print(f"✅ [DÜZGÜN]: {f}"); clean += 1
        else:
            try:
                if os.path.exists(new_path):
                    base, ext = os.path.splitext(new_name)
                    i = 1
                    while os.path.exists(new_path):
                        new_path = os.path.join(path, f"{base}_{i}{ext}"); i += 1
                os.rename(old_path, new_path)
                print(f"🔄 [DÜZELTİLDİ]: {f} → {os.path.basename(new_path)}"); fixed += 1
            except Exception as e:
                print(f"❌ [HATA]: {f}"); error += 1
    print(f"\n📊 RAPOR: {clean} Düzgün, {fixed} Düzeltildi, {error} Hata.")

def download_engine(tasks, target_dir):
    if not tasks or tasks == "BACK":
        return
    os.makedirs(target_dir, exist_ok=True)
    session = requests.Session()
    ua_pool = load_ua_pool()

    for url, name in tasks:
        success, retries = False, 0
        clean_name = turkish_to_english_engine(name)
        f_path = os.path.join(target_dir, clean_name)
        if os.path.exists(f_path):
            base, ext = os.path.splitext(clean_name)
            i = 1
            while os.path.exists(f_path):
                f_path = os.path.join(target_dir, f"{base}_{i}{ext}"); i += 1

        while retries < MAX_RETRIES and not success:
            p_info = get_random_working_proxy() if PROXY_AUTO_ENABLED else None
            proxy_url = p_info['proxy'] if p_info else None
            proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None

            try:
                headers = {'User-Agent': random.choice(ua_pool)}
                with session.get(url, headers=headers, proxies=proxies, stream=True, timeout=(10, 90)) as r:
                    r.raise_for_status()
                    total = int(r.headers.get('content-length', 0))
                    with open(f_path, 'wb') as f:
                        with tqdm(total=total, unit='B', unit_scale=True, desc=f"🎬 {os.path.basename(f_path)[:30]}",
                                  bar_format='{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{rate_fmt}]') as bar:
                            for chunk in r.iter_content(chunk_size=1024*1024):
                                if chunk:
                                    f.write(chunk)
                                    bar.update(len(chunk))
                    success = True
                    mark_proxy_result(proxy_url, True)
                    print(f"✅ Başarılı: {os.path.basename(f_path)}")
            except Exception as e:
                retries += 1
                mark_proxy_result(proxy_url, False)
                print(f"⚠️ Hata ({retries}/{MAX_RETRIES}): {str(e)[:60]}")
                time.sleep(random.uniform(1, 4))
        if not success:
            print(f"❌ Başarısız: {os.path.basename(f_path)}")

# parse_m3u_to_categories ve select_from_categories (önceki mesajımdan aynı)

def parse_m3u_to_categories(content):
    cats = {}
    curr = "Diğer"
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('#EXTINF:'):
            name_match = re.search(r',(.+)$', line)
            name = name_match.group(1).strip() if name_match else f"İsimsiz_{i}"
            group_match = re.search(r'group-title="([^"]+)"', line)
            curr = group_match.group(1) if group_match else "Belirtilmemiş"
            i += 1
            if i < len(lines) and lines[i].strip().startswith('http'):
                url = lines[i].strip()
                if curr not in cats: cats[curr] = []
                cats[curr].append((url, name))
        i += 1
    return cats

def select_from_categories(categories):
    if not categories:
        print("❌ Kategori bulunamadı.")
        return "BACK"
    names = sorted(categories.keys())
    print("\n0- GERİ DÖN")
    for i, n in enumerate(names, 1):
        print(f"{i}- {n} [{len(categories[n])} içerik]")
    while True:
        idx = input("\nKategori seçin: ").strip()
        if idx == '0': return "BACK"
        if idx.isdigit() and 1 <= int(idx) <= len(names):
            selected_cat = categories[names[int(idx)-1]]
            break
        print("❌ Geçersiz seçim.")
    print("\n0- TÜMÜNÜ İNDİR")
    for i, (_, name) in enumerate(selected_cat, 1):
        print(f"{i}- {name[:70]}")
    choice = input("\nSeçiminiz (0 = tümü, virgülle birden fazla, boş = geri): ").strip()
    if not choice: return "BACK"
    if choice == '0': return selected_cat
    selected = []
    for num in choice.replace(' ', '').split(','):
        if num.isdigit():
            idx = int(num) - 1
            if 0 <= idx < len(selected_cat):
                selected.append(selected_cat[idx])
    return selected if selected else "BACK"

# --- MENÜ ---
def main_menu():
    load_ua_pool()
    initialize_proxy_pool()

    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        status = "Açık" if PROXY_AUTO_ENABLED else "Kapalı"
        print(f"=== VOD PRO v14 ===\n🇹🇷 Türk Proxy: {len(PROXY_POOL)} / {MAX_PROXY_COUNT} (Otomatik: {status})\n")
        print("1- URL GİR (M3U)")
        print("2- DOSYA SEÇ (M3U)")
        print("3- API ANALİZ")
        print("4- UA YENİLE")
        print("5- İSİM DÜZELT")
        print("6- PROXY AYAR")
        print("7- ÇIKIŞ")
        
        c = input("\nSeçim: ").strip()
        
        if c == '1':
            url = input("\nM3U URL: ").strip()
            if url:
                try:
                    res = requests.get(url, timeout=15).text
                    cats = parse_m3u_to_categories(res)
                    tasks = select_from_categories(cats)
                    download_engine(tasks, DOWNLOAD_DIR_DEFAULT)
                except Exception as e:
                    print(f"❌ Hata: {e}")
                input("\nEnter...")
                
        elif c == '2':
            files = glob.glob("*.m3u") + glob.glob("*.m3u8")
            if files:
                print("Bulunanlar:", ', '.join([os.path.basename(f) for f in files]))
            file = input("\nDosya adı: ").strip()
            if os.path.exists(file):
                with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                cats = parse_m3u_to_categories(content)
                tasks = select_from_categories(cats)
                download_engine(tasks, DOWNLOAD_DIR_DEFAULT)
            input("\nEnter...")
            
        elif c == '3':
            url = input("\nXtream URL: ").strip()
            if url: check_m3u_info(url)
            input("\nEnter...")
            
        elif c == '4':
            load_ua_pool(update=True)
            print("✅ UA yenilendi.")
            input("Enter...")
            
        elif c == '5':
            folder_cleaner()
            input("\nEnter...")
            
        elif c == '6':
            print(f"\nProxy: {len(PROXY_POOL)} adet")
            print(f"Otomatik: {'Açık' if PROXY_AUTO_ENABLED else 'Kapalı'}")
            ch = input("\n1- Manuel Yenile\n2- Otomatik Aç/Kapa\n3- Geri\nSeçim: ")
            if ch == '1':
                collect_turkey_proxies()
            elif ch == '2':
                global PROXY_AUTO_ENABLED
                PROXY_AUTO_ENABLED = not PROXY_AUTO_ENABLED
                print(f"Otomatik {'açıldı' if PROXY_AUTO_ENABLED else 'kapatıldı'}.")
            input("Enter...")
            
        elif c == '7':
            print("👋 Çıkış...")
            break

if __name__ == "__main__":
    main_menu()
