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

def generate_random_ua():
    chrome_v = f"{random.randint(110, 125)}.0.{random.randint(1000, 6000)}.{random.randint(10, 150)}"
    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_v} Safari/537.36"

def load_ua_pool(update=False):
    pool = []
    if not update and os.path.exists(ua_file):
        try:
            with open(ua_file, 'r', encoding='utf-8') as f:
                pool = [line.strip() for line in f if line.strip()]
        except Exception as e:
            print(f"⚠️ User-Agent dosyası okunamadı: {e}")
    
    if len(pool) < 30 or update:
        pool = [generate_random_ua() for _ in range(40)]
        try:
            with open(ua_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(pool))
        except Exception as e:
            print(f"⚠️ User-Agent dosyası yazılamadı: {e}")
    
    return pool if pool else [generate_random_ua() for _ in range(5)]

def check_proxy_location(proxy_url, timeout=8):
    """Proxy'nin lokasyonunu ve çalışırlığını kontrol et"""
    proxies = {'http': proxy_url, 'https': proxy_url}
    
    try:
        # IP ve lokasyon bilgisi al
        response = requests.get('http://ip-api.com/json/', proxies=proxies, timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            country = data.get('country', 'Unknown')
            country_code = data.get('countryCode', 'XX')
            ip = data.get('query', 'Unknown')
            
            # Türkiye mi kontrol et
            is_turkey = country_code == 'TR'
            
            return {
                'working': True,
                'ip': ip,
                'country': country,
                'country_code': country_code,
                'is_turkey': is_turkey,
                'proxy': proxy_url,
                'response_time': response.elapsed.total_seconds()
            }
    except:
        pass
    
    return {'working': False, 'proxy': proxy_url}

def fetch_proxies_from_source(source_url):
    """Tek bir kaynaktan proxy listesi çek"""
    try:
        response = requests.get(source_url, timeout=15)
        if response.status_code == 200:
            # Proxy'leri ayıkla (IP:PORT formatında)
            proxies = re.findall(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5}', response.text)
            return [f'http://{p}' for p in proxies]
    except Exception as e:
        print(f"   ⚠️ {source_url[:50]}... hatası: {e}")
    return []

def collect_turkey_proxies():
    """Türk proxy'leri topla ve test et"""
    global PROXY_POOL
    
    print("\n🌍 TÜRKİYE PROXY HAVUZU OLUŞTURULUYOR...")
    print(f"🎯 Hedef: Minimum {MIN_PROXY_COUNT} aktif Türk proxy")
    print("="*60)
    
    all_proxies = []
    
    # 1. Önce cache'den yükle
    if os.path.exists(proxy_cache_file):
        try:
            with open(proxy_cache_file, 'r') as f:
                cached = json.load(f)
                cache_age = time.time() - cached.get('timestamp', 0)
                
                if cache_age < 3600:  # 1 saat içindeyse
                    print(f"📦 Cache'den {len(cached.get('proxies', []))} proxy yüklendi (Yaş: {int(cache_age/60)}dk)")
                    all_proxies.extend(cached.get('proxies', []))
        except:
            pass
    
    # 2. Yeni proxy'ler çek
    print("\n🔄 Yeni proxy'ler aranıyor...")
    for i, source in enumerate(TURKEY_PROXY_SOURCES, 1):
        print(f"[{i}/{len(TURKEY_PROXY_SOURCES)}] {source[:50]}...")
        proxies = fetch_proxies_from_source(source)
        all_proxies.extend(proxies)
        print(f"   ✅ {len(proxies)} proxy bulundu")
        time.sleep(0.5)  # Rate limit
    
    # Tekrarları kaldır
    all_proxies = list(set(all_proxies))
    print(f"\n📊 Toplam {len(all_proxies)} benzersiz proxy bulundu")
    
    # 3. Paralel test et
    print(f"\n🧪 PROXY TEST EDİLİYOR (Türkiye filtresi aktif)...")
    turkey_proxies = []
    
    with ThreadPoolExecutor(max_workers=20) as executor:
        future_to_proxy = {executor.submit(check_proxy_location, proxy): proxy for proxy in all_proxies}
        
        with tqdm(total=len(all_proxies), desc="Testing", unit="proxy") as pbar:
            for future in as_completed(future_to_proxy):
                result = future.result()
                pbar.update(1)
                
                if result['working'] and result.get('is_turkey', False):
                    turkey_proxies.append(result)
                    tqdm.write(f"✅ TR Proxy: {result['ip']} ({result['response_time']:.2f}s)")
                    
                    # Hedef sayıya ulaştıysak dur
                    if len(turkey_proxies) >= MIN_PROXY_COUNT:
                        print(f"\n🎉 Hedef ulaşıldı! {len(turkey_proxies)} Türk proxy aktif!")
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
    
    # 4. Hıza göre sırala
    turkey_proxies.sort(key=lambda x: x['response_time'])
    
    # 5. Cache'e kaydet
    try:
        with open(proxy_cache_file, 'w') as f:
            json.dump({
                'timestamp': time.time(),
                'proxies': [p['proxy'] for p in turkey_proxies]
            }, f)
        print(f"💾 {len(turkey_proxies)} proxy cache'e kaydedildi")
    except:
        pass
    
    # 6. Global pool'a yükle
    PROXY_POOL = turkey_proxies
    
    print(f"\n{'='*60}")
    print(f"📊 SONUÇ RAPORU")
    print(f"{'='*60}")
    print(f"✅ Aktif Türk Proxy: {len(turkey_proxies)}")
    if turkey_proxies:
        avg_time = sum(p['response_time'] for p in turkey_proxies) / len(turkey_proxies)
        print(f"⚡ Ortalama Yanıt: {avg_time:.2f}s")
        print(f"🚀 En Hızlı: {turkey_proxies[0]['ip']} ({turkey_proxies[0]['response_time']:.2f}s)")
    print(f"{'='*60}\n")
    
    return len(turkey_proxies) >= MIN_PROXY_COUNT

def get_random_working_proxy():
    """Rastgele çalışan bir proxy al"""
    global PROXY_POOL
    
    if not PROXY_POOL:
        print("⚠️ Proxy havuzu boş! Yeniden oluşturuluyor...")
        if not collect_turkey_proxies():
            print("❌ Yeterli Türk proxy bulunamadı!")
            return None
    
    # En hızlı 10 proxy'den rastgele seç
    top_proxies = PROXY_POOL[:min(10, len(PROXY_POOL))]
    selected = random.choice(top_proxies)
    
    # İstatistik güncelle
    proxy_url = selected['proxy']
    if proxy_url not in PROXY_STATS:
        PROXY_STATS[proxy_url] = {'success': 0, 'fail': 0}
    
    return selected

def mark_proxy_result(proxy_url, success=True):
    """Proxy kullanım sonucunu kaydet"""
    global PROXY_POOL
    
    if proxy_url in PROXY_STATS:
        if success:
            PROXY_STATS[proxy_url]['success'] += 1
        else:
            PROXY_STATS[proxy_url]['fail'] += 1
            
            # Başarısızlık oranı yüksekse havuzdan çıkar
            stats = PROXY_STATS[proxy_url]
            total = stats['success'] + stats['fail']
            if total >= 5 and stats['fail'] / total > 0.7:
                PROXY_POOL = [p for p in PROXY_POOL if p['proxy'] != proxy_url]
                print(f"🗑️ Proxy havuzdan çıkarıldı: {proxy_url[:50]}")
                
                # Havuz küçüldüyse yenile
                if len(PROXY_POOL) < 10:
                    print("🔄 Proxy havuzu yenileniyor...")
                    collect_turkey_proxies()

def turkish_to_english_engine(text):
    """Gelişmiş isim düzeltme motoru."""
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

def check_m3u_info(url):
    if not url or url == '0': 
        return
    
    print("\n🔍 XTREAM API Sorgulanıyor...")
    
    proxies = None
    if PROXY_AUTO_ENABLED and PROXY_POOL:
        proxy_info = get_random_working_proxy()
        if proxy_info:
            proxies = {'http': proxy_info['proxy'], 'https': proxy_info['proxy']}
            print(f"🌐 TR Proxy: {proxy_info['ip']}")
    
    try:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        params = dict(re.findall(r'(\w+)=([^&]+)', parsed.query))
        user, pw = params.get('username'), params.get('password')
        
        if not user or not pw:
            print("⚠️ URL Xtream formatında değil.")
            return

        api_url = f"{base}/player_api.php?username={user}&password={pw}"
        r = requests.get(api_url, proxies=proxies, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        if proxies:
            mark_proxy_result(proxies['http'], success=True)
        
        u_info = data.get('user_info', {})
        print(f"\n--- HESAP ANALİZİ ---")
        print(f"🚦 Durum: {u_info.get('status', 'Bilinmiyor')}")
        
        exp = u_info.get('exp_date')
        if exp and exp != "null":
            try:
                print(f"📅 Bitiş: {datetime.fromtimestamp(int(exp))}")
            except:
                print(f"📅 Bitiş: {exp}")
        
        print(f"🔗 Bağlantı: {u_info.get('active_cons', '0')} / {u_info.get('max_connections', '0')}")
        print(f"---------------------\n")
    
    except Exception as e:
        if proxies:
            mark_proxy_result(proxies['http'], success=False)
        print(f"❌ API hatası: {e}")

def download_engine(tasks, target_dir):
    if not tasks or tasks == "BACK": 
        return
    
    os.makedirs(target_dir, exist_ok=True)
    session = requests.Session()
    
    total_files = len(tasks)
    completed = 0
    failed = 0
    
    for idx, (url, name) in enumerate(tasks, 1):
        print(f"\n[{idx}/{total_files}] İşleniyor: {name[:40]}")
        retries = 0
        success = False
        
        while retries < MAX_RETRIES and not success:
            # Her denemede farklı proxy ve UA
            ua = random.choice(load_ua_pool())
            headers = {'User-Agent': ua}
            
            proxies = None
            current_proxy_url = None
            if PROXY_AUTO_ENABLED and PROXY_POOL:
                proxy_info = get_random_working_proxy()
                if proxy_info:
                    proxies = {'http': proxy_info['proxy'], 'https': proxy_info['proxy']}
                    current_proxy_url = proxy_info['proxy']
                    if retries == 0:
                        print(f"🌐 TR Proxy: {proxy_info['ip']}")
            
            try:
                with session.get(url, headers=headers, proxies=proxies, stream=True, timeout=(10, 60)) as r:
                    r.raise_for_status()
                    
                    # Uzantı belirleme
                    parsed_path = urlparse(url).path
                    ext = os.path.splitext(parsed_path)[1].lower()
                    
                    if ext not in ['.mp4', '.mkv', '.avi', '.ts', '.flv', '.mov']:
                        ctype = r.headers.get('Content-Type', '').lower()
                        if 'mp4' in ctype:
                            ext = '.mp4'
                        elif 'mp2t' in ctype or 'mpegts' in ctype:
                            ext = '.ts'
                        elif 'matroska' in ctype or 'mkv' in ctype:
                            ext = '.mkv'
                        elif 'x-flv' in ctype:
                            ext = '.flv'
                        else:
                            ext = '.mp4'
                    
                    clean_filename = turkish_to_english_engine(name + ext)
                    path = os.path.join(target_dir, clean_filename)
                    
                    total = int(r.headers.get('content-length', 0))
                    if os.path.exists(path) and os.path.getsize(path) >= total and total > 0:
                        print(f"✅ Zaten mevcut: {clean_filename}")
                        success = True
                        completed += 1
                        if current_proxy_url:
                            mark_proxy_result(current_proxy_url, success=True)
                        break

                    with open(path, 'wb') as f:
                        with tqdm(
                            total=total, 
                            unit='B', 
                            unit_scale=True, 
                            desc=f"🎬 {clean_filename[:25]}", 
                            bar_format='{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]'
                        ) as bar:
                            for chunk in r.iter_content(chunk_size=1024*1024):
                                if chunk:
                                    f.write(chunk)
                                    bar.update(len(chunk))
                    
                    print(f"✅ Tamamlandı: {clean_filename}")
                    success = True
                    completed += 1
                    if current_proxy_url:
                        mark_proxy_result(current_proxy_url, success=True)
                    
            except Exception as e:
                retries += 1
                if current_proxy_url:
                    mark_proxy_result(current_proxy_url, success=False)
                print(f"⚠️ Hata ({retries}/{MAX_RETRIES}): {str(e)[:60]}")
                time.sleep(2)
        
        if not success:
            print(f"❌ İndirilemedi: {name}")
            failed += 1
    
    print(f"\n{'='*60}")
    print(f"📊 İNDİRME RAPORU")
    print(f"{'='*60}")
    print(f"✅ Başarılı: {completed}/{total_files}")
    print(f"❌ Başarısız: {failed}/{total_files}")
    print(f"{'='*60}\n")

def folder_cleaner(path):
    """Detaylı raporlama yapan isim düzeltme fonksiyonu."""
    if not os.path.exists(path):
        print("❌ Yol bulunamadı!")
        return
    
    try:
        files = os.listdir(path)
    except PermissionError:
        print("❌ Klasöre erişim izni yok!")
        return
    
    fixed_count = 0
    already_clean = 0
    error_count = 0
    
    print(f"\n🛠 {len(files)} dosya denetleniyor...\n")
    
    for f in files:
        old_path = os.path.join(path, f)
        if os.path.isdir(old_path): 
            continue
        
        new_name = turkish_to_english_engine(f)
        
        if f == new_name:
            print(f"✅ [DÜZGÜN]: {f}")
            already_clean += 1
        else:
            try:
                new_path = os.path.join(path, new_name)
                
                if os.path.exists(new_path):
                    base, ext = os.path.splitext(new_name)
                    counter = 1
                    while os.path.exists(new_path):
                        new_name = f"{base}_{counter}{ext}"
                        new_path = os.path.join(path, new_name)
                        counter += 1
                
                os.rename(old_path, new_path)
                print(f"🔄 [DÜZELTİLDİ]: {f} -> {new_name}")
                fixed_count += 1
            except Exception as e:
                print(f"❌ [HATA]: {f} ({e})")
                error_count += 1

    print(f"\n{'='*60}")
    print(f"📊 İŞLEM RAPORU")
    print(f"{'='*60}")
    print(f"✅ Zaten Düzgün: {already_clean}")
    print(f"🔧 Düzeltilen: {fixed_count}")
    print(f"❌ Hatalı: {error_count}")
    print(f"📂 Toplam: {len(files)}")
    print(f"{'='*60}\n")

def proxy_status_menu():
    """Proxy durum bilgisi"""
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"""
{'='*60}
  PROXY SİSTEM DURUMU
{'='*60}
🟢 Durum: {'AKTİF' if PROXY_AUTO_ENABLED else 'KAPALI'}
📊 Havuz: {len(PROXY_POOL)} Türk Proxy
⚡ Cache: {'Var' if os.path.exists(proxy_cache_file) else 'Yok'}

""")
    
    if PROXY_POOL:
        print("🏆 EN HIZLI 5 PROXY:")
        for i, p in enumerate(PROXY_POOL[:5], 1):
            stats = PROXY_STATS.get(p['proxy'], {'success': 0, 'fail': 0})
            print(f"{i}. {p['ip']} - {p['response_time']:.2f}s (✅{stats['success']} ❌{stats['fail']})")
    
    print(f"\n{'='*60}")
    print("1- Proxy Havuzunu Yenile")
    print("2- Proxy Sistemini Kapat/Aç")
    print("0- Geri Dön")
    print(f"{'='*60}")
    
    choice = input("\nSeçim: ").strip()
    
    if choice == '1':
        collect_turkey_proxies()
        input("\nDevam için Enter...")
    elif choice == '2':
        global PROXY_AUTO_ENABLED
        PROXY_AUTO_ENABLED = not PROXY_AUTO_ENABLED
        print(f"✅ Proxy sistemi {'AKTİF' if PROXY_AUTO_ENABLED else 'KAPALI'}!")
        time.sleep(2)

def main_menu():
    global PROXY_AUTO_ENABLED
    
    # İlk başlangıçta proxy havuzunu oluştur
    if PROXY_AUTO_ENABLED and not PROXY_POOL:
        collect_turkey_proxies()
    
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        proxy_status = f"🟢 {len(PROXY_POOL)} TR Proxy" if PROXY_AUTO_ENABLED else "🔴 Kapalı"
        print(f"""
{'='*60}
  VOD DOWNLOADER PRO + AUTO TURKEY PROXY
  DESIGN BY PROTON MEDIA
{'='*60}
🌐 Proxy Durumu: {proxy_status}

1- M3U URL GİR (KATEGORİ SEÇMELİ)
2- M3U DOSYA SEÇ (YEREL)
3- M3U BİLGİ KONTROL (URL ANALİZ)
4- USER-AGENT LİSTESİNİ YENİLE
5- DOSYA İSİMLERİNİ DENETLE & DÜZELT
6- PROXY SİSTEM DURUMU & AYARLAR
7- ÇIKIŞ
{'='*60}
""")
        choice = input("Seçiminiz: ").strip()

        if choice == '1':
            url = input("\nM3U URL (Geri için 0): ").strip()
            if url == '0': 
                continue
            
            target = input("İndirme Yolu (Enter=Downloads): ").strip() or DOWNLOAD_DIR_DEFAULT
            
            try:
                print("\n⏳ M3U listesi yükleniyor...")
                
                proxies = None
                if PROXY_AUTO_ENABLED and PROXY_POOL:
                    proxy_info = get_random_working_proxy()
                    if proxy_info:
                        proxies = {'http': proxy_info['proxy'], 'https': proxy_info['proxy']}
                        print(f"🌐 TR Proxy kullanılıyor: {proxy_info['ip']}")
                
                response = requests.get(url, proxies=proxies, timeout=20)
                response.raise_for_status()
                content = response.text
                
                cats = parse_m3u_to_categories(content)
                if not cats:
                    print("❌ M3U içeriği bulunamadı!")
                    time.sleep(2)
                    continue
                
                cats = {k:v for k,v in sorted(cats.items())}
                tasks = select_from_categories(cats)
                
                if tasks != "BACK":
                    download_engine(tasks, target)
                    input("\nDevam için Enter...")
                    
            except Exception as e:
                print(f"❌ Hata: {e}")
                time.sleep(3)

        elif choice == '2':
            files = glob.glob("*.m3u")
            if not files: 
                print("❌ .m3u dosyası bulunamadı!")
                time.sleep(2)
                continue
            
            print("\n0- GERİ")
            for i, f in enumerate(files, 1): 
                print(f"{i}- {f}")
            
            f_idx = input("\nSeçim: ").strip()
            if f_idx == '0': 
                continue
            
            try:
                selected_file = files[int(f_idx)-1]
                target = input("İndirme Yolu: ").strip() or DOWNLOAD_DIR_DEFAULT
                
                with open(selected_file, 'r', encoding='utf-8', errors='ignore') as f:
                    cats = parse_m3u_to_categories(f.read())
                
                if not cats:
                    print("❌ M3U içeriği bulunamadı!")
                    time.sleep(2)
                    continue
                
                tasks = select_from_categories(cats)
                if tasks != "BACK":
                    download_engine(tasks, target)
                    input("\nDevam için Enter...")
                    
            except Exception as e:
                print(f"❌ Hata: {e}")
                time.sleep(2)

        elif choice == '3':
            url = input("\nAnaliz edilecek URL (Geri için 0): ").strip()
            if url != '0': 
                check_m3u_info(url)
            input("\nDevam için Enter...")

        elif choice == '4':
            print("\n🔄 User-Agent yenileniyor...")
            load_ua_pool(update=True)
            print("✅ 40 yeni User-Agent oluşturuldu!")
            time.sleep(2)

        elif choice == '5':
            path = input("\nKlasör Yolu (Geri için 0): ").strip()
            if path != '0': 
                folder_cleaner(path)
            input("\nDevam için Enter...")

        elif choice == '6':
            proxy_status_menu()

        elif choice == '7': 
            print("\n👋 Görüşmek üzere!")
            time.sleep(1)
            break
        
        else:
            print("❌ Geçersiz seçim!")
            time.sleep(2)

def parse_m3u_to_categories(content):
    categories = {}
    current_cat = "Diger"
    name = ""
    
    for line in content.splitlines():
        line = line.strip()
        if line.startswith('#EXTINF:'):
            cat_match = re.search(r'group-title="([^"]+)"', line)
            current_cat = cat_match.group(1) if cat_match else "Belirtilmemis"
            
            parts = line.split(',', 1)
            name = parts[1].strip() if len(parts) > 1 else "Bilinmeyen"
            
        elif line.startswith('http'):
            if current_cat not in categories: 
                categories[current_cat] = []
            categories[current_cat].append((line, name))
            name = ""
    
    return categories

def select_from_categories(categories):
    cat_names = sorted(list(categories.keys()))
    
    print(f"\n{'='*60}")
    print("M3U KATEGORİ LİSTESİ")
    print(f"{'='*60}")
    print("0- GERİ DÖN")
    
    for i, cat in enumerate(cat_names, 1):
        print(f"{i}- {cat} [{len(categories[cat])}]")
    
    print(f"{len(cat_names) + 1}- TÜMÜNÜ İNDİR ({sum(len(v) for v in categories.values())})")
    print(f"{'='*60}")
    
    choice = input("\nSeçim: ").strip()
    
    if choice == '0': 
        return "BACK"
    
    try:
        idx = int(choice)
        if idx == len(cat_names) + 1:
            all_tasks = []
            for cat in cat_names:
                all_tasks.extend(categories[cat])
            
            confirm = input(f"\n⚠️ {len(all_tasks)} içerik indirilecek. Emin misiniz? (E/H): ").upper()
            return all_tasks if confirm == 'E' else "BACK"
        
        if 1 <= idx <= len(cat_names):
            return categories[cat_names[idx-1]]
            
    except:
        pass
    
    print("❌ Geçersiz seçim!")
    time.sleep(2)
    return "BACK"

if __name__ == "__main__":
    try:
        print("\n" + "="*60)
        print("🚀 VOD DOWNLOADER PRO + AUTO TURKEY PROXY")
        print("="*60)
        print("\n⏳ Sistem başlatılıyor...")
        
        # User-Agent havuzunu yükle
        load_ua_pool()
        print("✅ User-Agent havuzu hazır!")
        
        # Proxy sistemini başlat
        if PROXY_AUTO_ENABLED:
            print("\n🌍 Türkiye Proxy Sistemi başlatılıyor...")
            success = collect_turkey_proxies()
            
            if not success:
                print("\n⚠️ UYARI: Yeterli Türk proxy bulunamadı!")
                choice = input("Proxy olmadan devam edilsin mi? (E/H): ").strip().upper()
                if choice != 'E':
                    print("❌ Program kapatılıyor...")
                    sys.exit(0)
                PROXY_AUTO_ENABLED = False
        
        print("\n✅ Sistem hazır!\n")
        time.sleep(2)
        main_menu()
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Program kullanıcı tarafından durduruldu.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Kritik hata: {e}")
        import traceback
        traceback.print_exc()
        input("\nÇıkmak için Enter...")
        sys.exit(1)
