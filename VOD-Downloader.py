import os, requests, re, sys, time, random, glob, json
from tqdm import tqdm
from urllib.parse import urlparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- YAPILANDIRMA ---
ua_file = 'user_agents.txt'
proxy_cache_file = 'turkey_proxies_cache.json'
MAX_RETRIES = 30
DOWNLOAD_DIR_DEFAULT = "Downloads"
MIN_PROXY_COUNT = 30

# Proxy yapılandırması
PROXY_POOL = []
PROXY_STATS = {}
PROXY_AUTO_ENABLED = True

# Ücretsiz Türk Proxy API'leri
TURKEY_PROXY_SOURCES = [
    'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=TR&ssl=all&anonymity=all',
    'https://www.proxy-list.download/api/v1/get?type=http&country=TR',
    'https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt',
    'https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt',
    'https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt',
]

# --- YARDIMCI FONKSİYONLAR ---

def generate_random_ua():
    chrome_v = f"{random.randint(110, 125)}.0.{random.randint(1000, 6000)}.{random.randint(10, 150)}"
    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_v} Safari/537.36"

def load_ua_pool(update=False):
    pool = []
    if not update and os.path.exists(ua_file):
        try:
            with open(ua_file, 'r', encoding='utf-8') as f:
                pool = [line.strip() for line in f if line.strip()]
        except: pass
    if len(pool) < 30 or update:
        pool = [generate_random_ua() for _ in range(40)]
        with open(ua_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(pool))
    return pool

def turkish_to_english_engine(text):
    """XTREAM Standartlarına Uygun İsim Temizleyici"""
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
    return clean_name + ext.lower()

# --- PROXY YÖNETİMİ ---

def check_proxy_location(proxy_url, timeout=8):
    proxies = {'http': proxy_url, 'https': proxy_url}
    try:
        response = requests.get('http://ip-api.com/json/', proxies=proxies, timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            return {
                'working': True,
                'ip': data.get('query'),
                'is_turkey': data.get('countryCode') == 'TR',
                'proxy': proxy_url,
                'response_time': response.elapsed.total_seconds()
            }
    except: pass
    return {'working': False, 'proxy': proxy_url}

def collect_turkey_proxies():
    global PROXY_POOL
    print("\n🌍 TÜRKİYE PROXY HAVUZU OLUŞTURULUYOR...")
    all_raw = []
    for source in TURKEY_PROXY_SOURCES:
        try:
            r = requests.get(source, timeout=10)
            if r.status_code == 200:
                found = re.findall(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5}', r.text)
                all_raw.extend([f'http://{p}' for p in found])
        except: pass
    
    unique_raw = list(set(all_raw))
    turkey_proxies = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(check_proxy_location, p) for p in unique_raw]
        for f in tqdm(as_completed(futures), total=len(unique_raw), desc="TR Proxy Filtre"):
            res = f.result()
            if res['working'] and res['is_turkey']:
                turkey_proxies.append(res)
                if len(turkey_proxies) >= MIN_PROXY_COUNT: break
    
    turkey_proxies.sort(key=lambda x: x['response_time'])
    PROXY_POOL = turkey_proxies
    with open(proxy_cache_file, 'w') as f:
        json.dump({'timestamp': time.time(), 'proxies': [p['proxy'] for p in turkey_proxies]}, f)
    return len(PROXY_POOL)

def get_random_working_proxy():
    if not PROXY_POOL: return None
    top = PROXY_POOL[:10]
    return random.choice(top)

def mark_proxy_result(proxy_url, success=True):
    global PROXY_POOL
    if proxy_url not in PROXY_STATS: PROXY_STATS[proxy_url] = {'s':0, 'f':0}
    if success: PROXY_STATS[proxy_url]['s'] += 1
    else:
        PROXY_STATS[proxy_url]['f'] += 1
        if PROXY_STATS[proxy_url]['f'] > 5:
            PROXY_POOL = [p for p in PROXY_POOL if p['proxy'] != proxy_url]

# --- ANA MOTORLAR ---

def check_m3u_info(url):
    print("\n🔍 XTREAM API Sorgulanıyor...")
    p_info = get_random_working_proxy() if PROXY_AUTO_ENABLED else None
    proxies = {'http': p_info['proxy'], 'https': p_info['proxy']} if p_info else None
    try:
        parsed = urlparse(url)
        params = dict(re.findall(r'(\w+)=([^&]+)', parsed.query))
        api_url = f"{parsed.scheme}://{parsed.netloc}/player_api.php?username={params.get('username')}&password={params.get('password')}"
        r = requests.get(api_url, proxies=proxies, timeout=15).json()
        u = r.get('user_info', {})
        print(f"🚦 Durum: {u.get('status')} | 📅 Bitiş: {datetime.fromtimestamp(int(u.get('exp_date', 0)))}")
        print(f"🔗 Bağlantı: {u.get('active_cons')} / {u.get('max_connections')}")
    except: print("❌ API bilgisi alınamadı.")

def folder_cleaner(path):
    if not os.path.exists(path): return
    files = os.listdir(path)
    fixed, clean, error = 0, 0, 0
    print(f"\n🛠 {len(files)} dosya denetleniyor...\n")
    for f in files:
        old_path = os.path.join(path, f)
        if os.path.isdir(old_path): continue
        new_name = turkish_to_english_engine(f)
        if f == new_name:
            print(f"✅ [DÜZGÜN]: {f}"); clean += 1
        else:
            try:
                os.rename(old_path, os.path.join(path, new_name))
                print(f"🔄 [DÜZELTİLDİ]: {f} -> {new_name}"); fixed += 1
            except: print(f"❌ [HATA]: {f}"); error += 1
    print(f"\n📊 RAPOR: {clean} Düzgün, {fixed} Düzeltildi, {error} Hata.")

def download_engine(tasks, target_dir):
    if not tasks or tasks == "BACK": return
    os.makedirs(target_dir, exist_ok=True)
    session = requests.Session()
    for url, name in tasks:
        success, retries = False, 0
        while retries < MAX_RETRIES and not success:
            p_info = get_random_working_proxy() if PROXY_AUTO_ENABLED else None
            proxies = {'http': p_info['proxy'], 'https': p_info['proxy']} if p_info else None
            try:
                with session.get(url, headers={'User-Agent': random.choice(load_ua_pool())}, 
                                 proxies=proxies, stream=True, timeout=(10, 60)) as r:
                    r.raise_for_status()
                    ext = ".mp4" # Basit uzantı mantığı
                    clean_name = turkish_to_english_engine(name + ext)
                    f_path = os.path.join(target_dir, clean_name)
                    total = int(r.headers.get('content-length', 0))
                    
                    with open(f_path, 'wb') as f:
                        with tqdm(total=total, unit='B', unit_scale=True, desc=f"🎬 {clean_name[:20]}", 
                                  bar_format='{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{rate_fmt}]') as bar:
                            for chunk in r.iter_content(chunk_size=1024*1024):
                                if chunk: f.write(chunk); bar.update(len(chunk))
                    success = True
            except: 
                retries += 1
                time.sleep(1)

# --- MENÜ SİSTEMİ ---

def parse_m3u_to_categories(content):
    cats = {}
    curr = "Diger"
    for line in content.splitlines():
        if line.startswith('#EXTINF:'):
            m = re.search(r'group-title="([^"]+)"', line)
            curr = m.group(1) if m else "Belirtilmemis"
            name = line.split(',')[-1].strip()
        elif line.startswith('http'):
            if curr not in cats: cats[curr] = []
            cats[curr].append((line, name))
    return cats

def select_from_categories(categories):
    names = sorted(list(categories.keys()))
    print("\n0- GERİ DÖN")
    for i, n in enumerate(names, 1): print(f"{i}- {n} [{len(categories[n])}]")
    idx = input("\nSeçim: ")
    if idx == '0' or not idx: return "BACK"
    return categories[names[int(idx)-1]]

def main_menu():
    if PROXY_AUTO_ENABLED: collect_turkey_proxies()
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"=== VOD PRO v12 (TR PROXY: {len(PROXY_POOL)}) ===\n1- URL GİR\n2- DOSYA SEÇ\n3- API ANALİZ\n4- UA YENİLE\n5- İSİM DÜZELT\n6- PROXY AYAR\n7- ÇIKIŞ")
        c = input("\nSeçim: ")
        if c == '1':
            url = input("URL: ")
            if url == '0': continue
            res = requests.get(url, timeout=15).text
            tasks = select_from_categories(parse_m3u_to_categories(res))
            download_engine(tasks, DOWNLOAD_DIR_DEFAULT)
        elif c == '5':
            folder_cleaner(input("Klasör: "))
            input("\nEnter...")
        elif c == '7': break

if __name__ == "__main__":
    load_ua_pool()
    main_menu()
