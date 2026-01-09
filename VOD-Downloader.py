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

# GLOBAL DEĞİŞKENLER - EN ÜSTTE TANIMLANIYOR!
PROXY_POOL = []
PROXY_STATS = {}
PROXY_AUTO_ENABLED = True
BACKGROUND_REFRESH_RUNNING = False

# Güncel Türk Proxy Kaynakları (2026)
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
                    PROXY_POOL = [{'proxy': p, 'response_time': 0.5} for p in proxies]
                    print(f"📂 Önbellekten {len(PROXY_POOL)} proxy yüklendi ({age_hours:.1f} saat eski)")
                    return True
        except Exception as e:
            print(f"Önbellek hatası: {e}")
    return False

def save_proxy_cache():
    global PROXY_POOL
    try:
        with open(proxy_cache_file, 'w') as f:
            json.dump({
                'timestamp': time.time(),
                'proxies': [p['proxy'] for p in PROXY_POOL]
            }, f)
    except: pass

def check_proxy_location(proxy_url, timeout=8):
    proxies = {'http': proxy_url, 'https': proxy_url}
    try:
        start = time.time()
        response = requests.get('http://ip-api.com/json/', proxies=proxies, timeout=timeout)
        rt = time.time() - start
        if response.status_code == 200:
            data = response.json()
            if data.get('countryCode') == 'TR' and data.get('status') == 'success':
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
    if BACKGROUND_REFRESH_RUNNING and not background:
        print("⏳ Arka planda zaten proxy toplanıyor...")
        return
    
    if not background:
        print("\n🌍 Türk proxy havuzu güncelleniyor... (maks 200 adet %100 çalışan)")
    
    BACKGROUND_REFRESH_RUNNING = True
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

    unique_raw = list(all_raw)[:1000]  # Max 1000 test et
    new_working = []
    
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(check_proxy_location, p): p for p in unique_raw}
        for future in tqdm(as_completed(futures), total=min(500, len(unique_raw)), 
                          desc="🇹🇷 Proxy Test", disable=background or len(unique_raw)<50):
            res = future.result()
            if res['working'] and len(new_working) < MAX_PROXY_COUNT:
                new_working.append(res)

    # Mevcut havuza ekle (çakışma kontrolü ile)
    new_proxies = []
    current_proxies = {p['proxy'] for p in PROXY_POOL}
    for p in new_working:
        if p['proxy'] not in current_proxies and len(PROXY_POOL) + len(new_proxies) < MAX_PROXY_COUNT:
            new_proxies.append(p)
    
    PROXY_POOL.extend(new_proxies)
    PROXY_POOL.sort(key=lambda x: x['response_time'])
    PROXY_POOL = PROXY_POOL[:MAX_PROXY_COUNT]
    
    save_proxy_cache()
    BACKGROUND_REFRESH_RUNNING = False
    
    if not background:
        print(f"✅ {len(new_working)} yeni proxy eklendi. Toplam: {len(PROXY_POOL)}/{MAX_PROXY_COUNT}")
    else:
        print(f"🔄 Arka plan proxy yenileme: {len(PROXY_POOL)} adet hazır")

def background_proxy_refresher():
    global BACKGROUND_REFRESH_RUNNING
    if BACKGROUND_REFRESH_RUNNING or len(PROXY_POOL) >= MIN_PROXY_THRESHOLD:
        return
    threading.Thread(target=collect_turkey_proxies, kwargs={'background': True}, daemon=True).start()

def get_random_working_proxy():
    global PROXY_POOL
    if not PROXY_POOL:
        return None
    # Sadece çalışan proxy'leri seç (5+ başarısızlık yok)
    candidates = [p for p in PROXY_POOL[:30] if PROXY_STATS.get(p['proxy'], {}).get('f', 0) < 5]
    return random.choice(candidates) if candidates else None

def mark_proxy_result(proxy_url, success=True):
    global PROXY_POOL, PROXY_AUTO_ENABLED
    if not proxy_url or not PROXY_AUTO_ENABLED:
        return
    
    if proxy_url not in PROXY_STATS:
        PROXY_STATS[proxy_url] = {'s': 0, 'f': 0}
    
    if success:
        PROXY_STATS[proxy_url]['s'] += 1
    else:
        PROXY_STATS[proxy_url]['f'] += 1
        
        # 5+ başarısızlık = proxy listeden çıkar
        if PROXY_STATS[proxy_url]['f'] >= 5:
            PROXY_POOL[:] = [p for p in PROXY_POOL if p['proxy'] != proxy_url]
            print(f"🗑️ Ölü proxy kaldırıldı: {proxy_url}")
        
        # Havuz azaldıysa arka planda yenile
        if len(PROXY_POOL) < MIN_PROXY_THRESHOLD:
            background_proxy_refresher()

def initialize_proxy_pool():
    global PROXY_AUTO_ENABLED
    print("🚀 Proxy sistemi başlatılıyor...")
    load_ua_pool()
    
    if load_proxy_cache():
        working_count = len([p for p in PROXY_POOL if PROXY_STATS.get(p['proxy'], {}).get('f', 0) < 5])
        print(f"📂 {len(PROXY_POOL)} proxy önbellekten yüklendi ({working_count} çalışan)")
        
        if working_count < MIN_PROXY_COUNT_INITIAL:
            print("⚠️  Yeterli çalışan proxy yok → Yeni toplama başlıyor...")
            collect_turkey_proxies()
    else:
        collect_turkey_proxies()

# --- ANA FONKSİYONLAR ---
def check_m3u_info(url):
    print("\n🔍 XTREAM API Analizi...")
    p_info = get_random_working_proxy() if PROXY_AUTO_ENABLED else None
    proxies = {'http': p_info['proxy'], 'https': p_info['proxy']} if p_info else None
    try:
        parsed = urlparse(url)
        params = dict(re.findall(r'(\w+)=([^&]+)', parsed.query))
        username = params.get('username')
        password = params.get('password')
        if not username or not password:
            print("❌ URL'de username/password yok!")
            return
        api_url = f"{parsed.scheme}://{parsed.netloc}/player_api.php?username={username}&password={password}"
        r = requests.get(api_url, proxies=proxies, timeout=15, headers={'User-Agent': generate_random_ua()}).json()
        u = r.get('user_info', {})
        status = u.get('status', 'Bilinmiyor')
        exp = u.get('exp_date', 0)
        exp_date = datetime.fromtimestamp(int(exp)).strftime('%d.%m.%Y %H:%M') if exp else "Sınırsız"
        print(f"🚦 Durum: {status} | 📅 Bitiş: {exp_date}")
        print(f"👥 Aktif: {u.get('active_cons',0)}/{u.get('max_connections',0)}")
        print(f"📦 Live: {u.get('live',0)} | VOD: {u.get('vod',0)} | Movie: {u.get('movie',0)}")
    except Exception as e:
        print(f"❌ API hatası: {str(e)[:100]}")

def parse_m3u_to_categories(content):
    cats = {}
    curr_cat = "Diğer"
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('#EXTINF:'):
            name_match = re.search(r',(.+)$', line)
            name = name_match.group(1).strip() if name_match else f"İsimsiz_{i}"
            group_match = re.search(r'group-title="([^"]*)"', line)
            curr_cat = group_match.group(1) if group_match else "Belirtilmemiş"
            i += 1
            if i < len(lines):
                url = lines[i].strip()
                if url.startswith('http'):
                    if curr_cat not in cats: cats[curr_cat] = []
                    cats[curr_cat].append((url, name))
        i += 1
    return cats

def select_from_categories(categories):
    if not categories:
        print("❌ Hiç kategori bulunamadı!")
        return "BACK"
    
    names = sorted(cats := {k: len(v) for k, v in categories.items()}.keys())
    print("\n📂 Kategoriler:")
    print("0- GERİ")
    for i, cat in enumerate(names, 1):
        print(f"{i:2}- {cat:<25} [{categories[cat]:>3}]")
    
    while True:
        try:
            choice = input("\nKategori: ").strip()
            if choice == '0': return "BACK"
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                selected_cat = categories[names[idx]]
                break
            print("❌ Geçersiz!")
        except: print("❌ Sayı gir!")
    
    # İçerik seçimi
    print(f"\n🎬 {names[idx]} ({len(selected_cat)} içerik):")
    print("0- TÜMÜNÜ İNDİR")
    for i, (_, name) in enumerate(selected_cat, 1):
        print(f"{i:2}- {name[:60]}")
    
    choice = input("\nSeçim (virgülle, 0=tümü, boş=geri): ").strip()
    if not choice or choice == '0': return selected_cat
    
    selected = []
    for num in choice.split(','):
        try:
            idx = int(num.strip()) - 1
            if 0 <= idx < len(selected_cat):
                selected.append(selected_cat[idx])
        except: pass
    return selected if selected else "BACK"

def folder_cleaner(path=None):
    path = path or input("Klasör (boş=Downloads): ").strip() or DOWNLOAD_DIR_DEFAULT
    if not os.path.exists(path):
        print("❌ Klasör yok!")
        return
    files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
    fixed, clean, error = 0, 0, 0
    print(f"\n🛠️ {len(files)} dosya kontrol ediliyor...")
    for f in files:
        old = os.path.join(path, f)
        new_name = turkish_to_english_engine(f)
        new_path = os.path.join(path, new_name)
        if f == new_name:
            print(f"✅ {f}")
            clean += 1
            continue
        try:
            # Çakışma kontrolü
            base, ext = os.path.splitext(new_name)
            counter = 1
            while os.path.exists(new_path):
                new_path = os.path.join(path, f"{base}_{counter}{ext}")
                counter += 1
            os.rename(old, new_path)
            print(f"🔧 {f} → {os.path.basename(new_path)}")
            fixed += 1
        except Exception as e:
            print(f"❌ {f}: {e}")
            error += 1
    print(f"\n📊 {clean} OK, {fixed} düzeltildi, {error} hata")

def download_engine(tasks, target_dir):
    global PROXY_AUTO_ENABLED
    if not tasks or tasks == "BACK": return
    
    os.makedirs(target_dir, exist_ok=True)
    session = requests.Session()
    ua_pool = load_ua_pool()
    success_count = 0
    
    for url, name in tasks:
        clean_name = turkish_to_english_engine(name)
        f_path = os.path.join(target_dir, clean_name)
        
        # Dosya çakışması kontrolü
        base, ext = os.path.splitext(clean_name)
        counter = 1
        while os.path.exists(f_path):
            f_path = os.path.join(target_dir, f"{base}_{counter}{ext}")
            counter += 1
        
        file_success = False
        for attempt in range(MAX_RETRIES):
            p_info = get_random_working_proxy() if PROXY_AUTO_ENABLED else None
            proxy_url = p_info['proxy'] if p_info else None
            proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else None
            
            try:
                headers = {'User-Agent': random.choice(ua_pool)}
                with session.get(url, headers=headers, proxies=proxies, 
                               stream=True, timeout=(15, 120)) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get('content-length', 0))
                    
                    with open(f_path, 'wb') as f, tqdm(
                        total=total_size, unit='B', unit_scale=True, 
                        desc=f"📹 {os.path.basename(f_path):<40}",
                        bar_format='{desc}{percentage:3.0f}%|{bar}|{n_fmt}/{total_fmt} {rate_fmt}{postfix}'
                    ) as pbar:
                        for chunk in r.iter_content(chunk_size=2*1024*1024):
                            if chunk:
                                f.write(chunk)
                                pbar.update(len(chunk))
                
                file_success = True
                success_count += 1
                mark_proxy_result(proxy_url, True)
                print(f"✅ TAMAMLANDI: {os.path.basename(f_path)}")
                break
                
            except Exception as e:
                mark_proxy_result(proxy_url, False)
                print(f"⚠️  Deneme {attempt+1}/{MAX_RETRIES}: {str(e)[:80]}")
                time.sleep(random.uniform(2, 5))
        
        if not file_success:
            print(f"❌ BAŞARISIZ: {name}")
    
    print(f"\n🎉 Oturum tamamlandı: {success_count}/{len(tasks)} başarılı")

# --- ANA MENÜ ---
def main_menu():
    global PROXY_AUTO_ENABLED
    
    # CRITICAL: Global değişkenler düzgün initialize ediliyor
    initialize_proxy_pool()
    
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        working_proxies = len([p for p in PROXY_POOL if PROXY_STATS.get(p['proxy'], {}).get('f', 0) < 5])
        status = "🟢" if PROXY_AUTO_ENABLED else "🔴"
        print(f"""
╔══════════════════════════════════════╗
║     🇹🇷 VOD PRO v15 - TURK PROXY     ║
║  Proxy: {len(PROXY_POOL)}/{MAX_PROXY_COUNT} ({working_proxies} çalışan) {status} ║
╚══════════════════════════════════════╝
        """)
        print("1️⃣  M3U URL Gir")
        print("2️⃣  M3U Dosya Seç") 
        print("3️⃣  API Analiz")
        print("4️⃣  UA Yenile")
        print("5️⃣  İsim Düzelt")
        print("6️⃣  Proxy Ayar")
        print("0️⃣  ÇIKIŞ")
        
        c = input("\n👉 Seçim: ").strip()
        
        if c == '1':
            url = input("\n🌐 M3U URL: ").strip()
            if url and url != '0':
                try:
                    print("📥 M3U okunuyor...")
                    res = requests.get(url, timeout=20).text
                    cats = parse_m3u_to_categories(res)
                    tasks = select_from_categories(cats)
                    download_engine(tasks, DOWNLOAD_DIR_DEFAULT)
                except Exception as e:
                    print(f"❌ Hata: {e}")
            input("\n⏸️  Enter...")
            
        elif c == '2':
            m3u_files = glob.glob("*.m3u*")
            if m3u_files:
                print("📁 Bulunan M3U:", ', '.join([os.path.basename(f) for f in m3u_files[:10]]))
            file = input("📄 Dosya adı: ").strip()
            if os.path.exists(file):
                with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                cats = parse_m3u_to_categories(content)
                tasks = select_from_categories(cats)
                download_engine(tasks, DOWNLOAD_DIR_DEFAULT)
            else:
                print("❌ Dosya yok!")
            input("\n⏸️  Enter...")
            
        elif c == '3':
            url = input("\n🔗 Xtream URL: ").strip()
            check_m3u_info(url)
            input("\n⏸️  Enter...")
            
        elif c == '4':
            load_ua_pool(True)
            print("✅ UA havuzu yenilendi!")
            input("⏸️  Enter...")
            
        elif c == '5':
            folder_cleaner()
            input("⏸️  Enter...")
            
        elif c == '6':
            print(f"\n📊 PROXY İSTATİSTİK")
            print(f"  • Toplam: {len(PROXY_POOL)}")
            print(f"  • Çalışan: {working_proxies}")
            print(f"  • Otomatik: {'AÇIK' if PROXY_AUTO_ENABLED else 'KAPALI'}")
            print("\n1- Manuel Yenile (200 proxy)")
            print("2- Otomatik Aç/Kapat")
            print("3- Önbelleği Sil")
            ch = input("👉: ").strip()
            
            if ch == '1':
                collect_turkey_proxies()
            elif ch == '2':
                PROXY_AUTO_ENABLED = not PROXY_AUTO_ENABLED
                print(f"✅ Otomatik proxy {'AÇILDI' if PROXY_AUTO_ENABLED else 'KAPATILDI'}")
            elif ch == '3':
                if os.path.exists(proxy_cache_file):
                    os.remove(proxy_cache_file)
                    PROXY_POOL.clear()
                    print("🗑️  Önbellek silindi!")
                    initialize_proxy_pool()
            input("⏸️  Enter...")
            
        elif c == '0':
            print("👋 Görüşürüz!")
            break

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\n\n⏹️  Program kullanıcı tarafından durduruldu.")
    except Exception as e:
        print(f"\n💥 Kritik hata: {e}")
