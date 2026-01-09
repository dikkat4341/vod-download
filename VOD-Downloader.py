import os, requests, re, sys, time, random, glob, json
from tqdm import tqdm
from urllib.parse import urlparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- TURBO YAPILANDIRMA ---
ua_file = 'user_agents.txt'
proxy_cache_file = 'turkey_proxies_cache.json'
MAX_RETRIES = 15  # Turbo modda deneme sayısı optimize edildi
DOWNLOAD_DIR_DEFAULT = "Downloads"
TARGET_PROXY_COUNT = 200
TURBO_CHUNK_SIZE = 1024 * 512  # 512KB Buffer (Hız için kritik)
CONCURRENT_DOWNLOADS = 3 # Aynı anda kaç dosya indirilsin?

# Global Değişkenler
PROXY_POOL = []
PROXY_AUTO_ENABLED = False # Turbo modda varsayılan KAPALI (Hız için)

def generate_random_ua():
    chrome_v = f"{random.randint(110, 125)}.0.{random.randint(1000, 6000)}.{random.randint(10, 150)}"
    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_v} Safari/537.36"

def turkish_to_english_engine(text):
    name, ext = os.path.splitext(text)
    m = {'ı':'i','ü':'u','ğ':'g','ö':'o','ş':'s','ç':'c','İ':'I','Ü':'U','Ğ':'G','Ö':'O','Ş':'S','Ç':'C',' ':'_','-':'_'}
    for tr, en in m.items(): name = name.replace(tr, en)
    clean_name = re.sub(r'[^a-zA-Z0-9_]', '', name)
    return re.sub(r'_+', '_', clean_name).strip('_') + ext.lower()

# --- TURBO STREAM MOTORU ---

def turbo_download_worker(task, target_dir):
    """Tekil bir dosya için turbo indirme işlemini yönetir."""
    url, name = task
    success = False
    retries = 0
    
    # Session seviyesinde hız optimizasyonu (Keep-Alive aktif)
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10)
    session.mount('http://', adapter)
    session.mount('https://', adapter)

    clean_filename = turkish_to_english_engine(name + ".mp4") # Uzantı varsayılan .mp4
    path = os.path.join(target_dir, clean_filename)

    while retries < MAX_RETRIES and not success:
        try:
            # Proxy kullanımı sadece PROXY_AUTO_ENABLED True ise ve hız gerekmiyorsa devreye girer
            proxies = None
            if PROXY_AUTO_ENABLED and PROXY_POOL:
                p = random.choice(PROXY_POOL[:10])['proxy']
                proxies = {'http': p, 'https': p}

            with session.get(url, headers={'User-Agent': generate_random_ua()}, 
                             proxies=proxies, stream=True, timeout=(5, 30)) as r:
                r.raise_for_status()
                total = int(r.headers.get('content-length', 0))
                
                with open(path, 'wb') as f:
                    with tqdm(total=total, unit='B', unit_scale=True, leave=False,
                              desc=f"⚡ {clean_filename[:20]}", 
                              bar_format='{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{rate_fmt}]') as bar:
                        for chunk in r.iter_content(chunk_size=TURBO_CHUNK_SIZE):
                            if chunk:
                                f.write(chunk)
                                bar.update(len(chunk))
                success = True
                return True
        except Exception as e:
            retries += 1
            time.sleep(1)
    return False

def turbo_manager(tasks, target_dir):
    """Aynı anda birden fazla dosyayı turbo hızda indirir."""
    if not tasks: return
    os.makedirs(target_dir, exist_ok=True)
    
    print(f"\n🚀 Turbo Stream Motoru Başlatıldı ({CONCURRENT_DOWNLOADS} Eşzamanlı)")
    print(f"📂 Hedef: {target_dir}\n")

    

    with ThreadPoolExecutor(max_workers=CONCURRENT_DOWNLOADS) as executor:
        future_to_task = {executor.submit(turbo_download_worker, task, target_dir): task for task in tasks}
        
        completed = 0
        for future in as_completed(future_to_task):
            if future.result():
                completed += 1
            
    print(f"\n✅ Tüm işlemler tamamlandı. Başarılı: {completed}/{len(tasks)}")

# --- YARDIMCI MENÜLER ---

def folder_cleaner(path):
    if not os.path.exists(path): return
    files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]
    fixed = 0
    print(f"\n🛠 {len(files)} dosya denetleniyor...")
    for f in files:
        new_name = turkish_to_english_engine(f)
        if f != new_name:
            os.rename(os.path.join(path, f), os.path.join(path, new_name))
            fixed += 1
    print(f"📊 Rapor: {len(files)-fixed} Düzgün, {fixed} Düzeltildi.")

def main_menu():
    global PROXY_AUTO_ENABLED
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"""
==========================================
    VOD PRO v14 - TURBO STREAM ENGINE
==========================================
Hız Modu: {"🔴 PROXY (Yavaş)" if PROXY_AUTO_ENABLED else "🚀 DIRECT TURBO (Hızlı)"}
------------------------------------------
1- M3U URL GİR (TURBO İNDİR)
2- M3U DOSYA SEÇ (YEREL)
3- DOSYA İSİMLERİNİ DÜZELT (DENETLEME)
4- HIZ MODU DEĞİŞTİR (PROXY AÇ/KAPAT)
5- ÇIKIŞ
==========================================
""")
        choice = input("Seçiminiz: ")
        
        if choice == '1':
            url = input("\nM3U URL: ")
            if url == '0': continue
            try:
                # Örnek kategori parse işlemi (Senin mevcut parse kodunla birleştirilmeli)
                content = requests.get(url, timeout=10).text
                # Basit test için ilk 3 linki alalım
                links = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', content)
                tasks = [(link, f"Video_{i}") for i, link in enumerate(links[:5])]
                turbo_manager(tasks, DOWNLOAD_DIR_DEFAULT)
                input("\nDevam için Enter...")
            except: print("❌ Bağlantı hatası.")
            
        elif choice == '3':
            path = input("\nKlasör Yolu: ")
            folder_cleaner(path)
            input("\nDevam için Enter...")
            
        elif choice == '4':
            PROXY_AUTO_ENABLED = not PROXY_AUTO_ENABLED
            print(f"✅ Hız modu güncellendi!")
            time.sleep(1)
            
        elif choice == '5': break

if __name__ == "__main__":
    main_menu()
