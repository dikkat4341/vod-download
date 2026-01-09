import os, requests, re, sys, time, random, socket, glob
from tqdm import tqdm
from urllib.parse import urlparse
from datetime import datetime

# --- YAPILANDIRMA ---
ua_file = 'user_agents.txt'
MAX_RETRIES = 30
DOWNLOAD_DIR_DEFAULT = "Downloads"

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

def turkish_to_english_engine(text):
    """Gelişmiş isim düzeltme motoru."""
    name, ext = os.path.splitext(text)
    m = {
        'ı':'i','ü':'u','ğ':'g','ö':'o','ş':'s','ç':'c',
        'İ':'I','Ü':'U','Ğ':'G','Ö':'O','Ş':'S','Ç':'C',
        ' ':'_', '-':'_', '.':'_'
    }
    # Önce sözlükteki karakterleri çevir
    for tr, en in m.items():
        name = name.replace(tr, en)
    
    # Kalan tüm özel karakterleri temizle (Sadece Alfanümerik ve Alt çizgi)
    clean_name = re.sub(r'[^a-zA-Z0-9_]', '', name)
    
    # Çift alt çizgileri teke indir
    clean_name = re.sub(r'_+', '_', clean_name).strip('_')
    
    return clean_name + ext.lower()

def check_m3u_info(url):
    if not url or url == '0': 
        return
    
    print("\n🔍 XTREAM API Sorgulanıyor...")
    try:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        params = dict(re.findall(r'(\w+)=([^&]+)', parsed.query))
        user, pw = params.get('username'), params.get('password')
        
        if not user or pw:
            print("⚠️ URL Xtream formatında değil.")
            return

        api_url = f"{base}/player_api.php?username={user}&password={pw}"
        r = requests.get(api_url, timeout=15)
        r.raise_for_status()
        data = r.json()
        
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
    
    except requests.exceptions.RequestException as e:
        print(f"❌ API bağlantı hatası: {e}")
    except Exception as e:
        print(f"❌ API bilgileri alınamadı: {e}")

def download_engine(tasks, target_dir):
    if not tasks or tasks == "BACK": 
        return
    
    os.makedirs(target_dir, exist_ok=True)
    session = requests.Session()
    session.timeout = (10, 45)  # Bağlantı ve okuma timeout'u
    
    total_files = len(tasks)
    completed = 0
    failed = 0
    
    for idx, (url, name) in enumerate(tasks, 1):
        print(f"\n[{idx}/{total_files}] İşleniyor...")
        retries = 0
        success = False
        
        while retries < MAX_RETRIES and not success:
            ua = random.choice(load_ua_pool())
            try:
                with session.get(url, headers={'User-Agent': ua}, stream=True, timeout=(10, 45)) as r:
                    r.raise_for_status()
                    
                    # Uzantı ve İsim Belirleme
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
                            ext = '.mp4'  # Varsayılan
                    
                    clean_filename = turkish_to_english_engine(name + ext)
                    path = os.path.join(target_dir, clean_filename)
                    
                    total = int(r.headers.get('content-length', 0))
                    if os.path.exists(path) and os.path.getsize(path) >= total and total > 0:
                        print(f"✅ {clean_filename}: Zaten mevcut.")
                        success = True
                        completed += 1
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
                    
                    print(f"✅ İndirme tamamlandı: {clean_filename}")
                    success = True
                    completed += 1
                    
            except requests.exceptions.Timeout:
                retries += 1
                print(f"⏱️ Zaman aşımı. Retry: {retries}/{MAX_RETRIES}")
                time.sleep(2)
            except requests.exceptions.RequestException as e:
                retries += 1
                print(f"⚠️ Bağlantı hatası: {e}. Retry: {retries}/{MAX_RETRIES}")
                time.sleep(2)
            except Exception as e:
                retries += 1
                print(f"⚠️ Beklenmeyen hata: {e}. Retry: {retries}/{MAX_RETRIES}")
                time.sleep(2)
        
        if not success:
            print(f"❌ İndirilemedi: {name}")
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"📊 İNDİRME RAPORU")
    print(f"{'='*50}")
    print(f"✅ Başarılı: {completed}/{total_files}")
    print(f"❌ Başarısız: {failed}/{total_files}")
    print(f"{'='*50}\n")

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
                
                # Aynı isimde dosya varsa benzersiz isim oluştur
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
                print(f"❌ [HATA]: {f} düzeltilemedi! ({e})")
                error_count += 1

    print(f"\n{'='*50}")
    print(f"📊 İŞLEM RAPORU")
    print(f"{'='*50}")
    print(f"✅ Zaten Düzgün: {already_clean}")
    print(f"🔧 Düzeltilen: {fixed_count}")
    print(f"❌ Hatalı: {error_count}")
    print(f"📂 Toplam: {len(files)}")
    print(f"{'='*50}\n")

def main_menu():
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"""
{'='*50}
  VOD DOWNLOADER PRO
  DESIGN BY PROTON MEDIA
{'='*50}
1- M3U URL GİR (KATEGORİ SEÇMELİ)
2- M3U DOSYA SEÇ (YEREL)
3- M3U BİLGİ KONTROL (URL ANALİZ)
4- USER-AGENT LİSTESİNİ YENİLE
5- DOSYA İSİMLERİNİ DENETLE & DÜZELT
6- ÇIKIŞ
{'='*50}
""")
        choice = input("Seçiminiz: ").strip()

        if choice == '1':
            url = input("\nM3U URL (Geri için 0): ").strip()
            if url == '0': 
                continue
            
            target = input("İndirme Yolu (Enter=Downloads): ").strip() or DOWNLOAD_DIR_DEFAULT
            
            try:
                print("\n⏳ M3U listesi yükleniyor...")
                response = requests.get(url, timeout=20)
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
                    input("\nDevam etmek için Enter...")
                    
            except requests.exceptions.RequestException as e:
                print(f"❌ Liste yüklenemedi: {e}")
                time.sleep(3)
            except Exception as e:
                print(f"❌ Beklenmeyen hata: {e}")
                time.sleep(3)

        elif choice == '2':
            files = glob.glob("*.m3u")
            if not files: 
                print("❌ Bu dizinde .m3u dosyası bulunamadı!")
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
                target = input("İndirme Yolu (Enter=Downloads): ").strip() or DOWNLOAD_DIR_DEFAULT
                
                with open(selected_file, 'r', encoding='utf-8', errors='ignore') as f:
                    cats = parse_m3u_to_categories(f.read())
                
                if not cats:
                    print("❌ M3U içeriği bulunamadı!")
                    time.sleep(2)
                    continue
                
                tasks = select_from_categories(cats)
                if tasks != "BACK":
                    download_engine(tasks, target)
                    input("\nDevam etmek için Enter...")
                    
            except (ValueError, IndexError):
                print("❌ Geçersiz seçim!")
                time.sleep(2)
            except Exception as e:
                print(f"❌ Dosya okunamadı: {e}")
                time.sleep(2)

        elif choice == '3':
            url = input("\nAnaliz edilecek URL (Geri için 0): ").strip()
            if url != '0': 
                check_m3u_info(url)
            input("\nDevam etmek için Enter...")

        elif choice == '4':
            print("\n🔄 User-Agent listesi yenileniyor...")
            load_ua_pool(update=True)
            print("✅ 40 yeni User-Agent oluşturuldu!")
            print("📝 Dosya: user_agents.txt")
            time.sleep(2)

        elif choice == '5':
            path = input("\nDenetlenecek Klasör Yolu (Geri için 0): ").strip()
            if path != '0': 
                folder_cleaner(path)
            input("\nDevam etmek için Enter...")

        elif choice == '6': 
            print("\n👋 Görüşmek üzere!")
            time.sleep(1)
            break
        
        else:
            print("❌ Geçersiz seçim! Lütfen 1-6 arası bir sayı girin.")
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
            
            # İsmi bul (virgülden sonraki kısım)
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
    
    print(f"\n{'='*50}")
    print("M3U KATEGORİ LİSTESİ")
    print(f"{'='*50}")
    print("0- GERİ DÖN")
    
    for i, cat in enumerate(cat_names, 1):
        print(f"{i}- {cat} [{len(categories[cat])} içerik]")
    
    print(f"{len(cat_names) + 1}- TÜMÜNÜ İNDİR ({sum(len(v) for v in categories.values())} içerik)")
    print(f"{'='*50}")
    
    choice = input("\nSeçim: ").strip()
    
    if choice == '0': 
        return "BACK"
    
    try:
        idx = int(choice)
        if idx == len(cat_names) + 1:
            all_tasks = []
            for cat in cat_names:
                all_tasks.extend(categories[cat])
            
            confirm = input(f"\n⚠️ {len(all_tasks)} içerik indirilecek. Emin misiniz? (E/H): ").strip().upper()
            if confirm == 'E':
                return all_tasks
            else:
                return "BACK"
        
        if 1 <= idx <= len(cat_names):
            return categories[cat_names[idx-1]]
        else:
            print("❌ Geçersiz seçim!")
            time.sleep(2)
            return "BACK"
            
    except ValueError:
        print("❌ Lütfen sayı girin!")
        time.sleep(2)
        return "BACK"

if __name__ == "__main__":
    try:
        print("\n🚀 VOD Downloader başlatılıyor...")
        load_ua_pool()
        print("✅ Hazır!\n")
        time.sleep(1)
        main_menu()
    except KeyboardInterrupt:
        print("\n\n⚠️ Program kullanıcı tarafından durduruldu.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Kritik hata: {e}")
        input("Çıkmak için Enter...")
        sys.exit(1)
