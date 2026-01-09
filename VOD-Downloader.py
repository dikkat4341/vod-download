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
        with open(ua_file, 'r', encoding='utf-8') as f:
            pool = [line.strip() for line in f if line.strip()]
    if len(pool) < 30 or update:
        pool = [generate_random_ua() for _ in range(40)]
        with open(ua_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(pool))
    return pool

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
    if not url or url == '0': return
    print("\n🔍 XTREAM API Sorgulanıyor...")
    try:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        params = dict(re.findall(r'(\w+)=([^&]+)', parsed.query))
        user, pw = params.get('username'), params.get('password')
        
        if not user or not pw:
            print("⚠️ URL Xtream formatında değil.")
            return

        api_url = f"{base}/player_api.php?username={user}&password={pw}"
        r = requests.get(api_url, timeout=15).json()
        u_info = r.get('user_info', {})
        print(f"\n--- HESAP ANALİZİ ---")
        print(f"🚦 Durum: {u_info.get('status', 'Bilinmiyor')}")
        exp = u_info.get('exp_date')
        if exp and exp != "null":
            print(f"📅 Bitiş: {datetime.fromtimestamp(int(exp))}")
        print(f"🔗 Bağlantı: {u_info.get('active_cons', '0')} / {u_info.get('max_connections', '0')}")
        print(f"---------------------\n")
    except: print("❌ API bilgileri alınamadı.")

def download_engine(tasks, target_dir):
    if not tasks or tasks == "BACK": return
    os.makedirs(target_dir, exist_ok=True)
    session = requests.Session()
    
    for url, name in tasks:
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
                    if ext not in ['.mp4', '.mkv', '.avi', '.ts']:
                        ctype = r.headers.get('Content-Type', '').lower()
                        ext = '.mp4' if 'mp4' in ctype else '.ts' if 'mp2t' in ctype else '.mkv'
                    
                    clean_filename = turkish_to_english_engine(name + ext)
                    path = os.path.join(target_dir, clean_filename)
                    
                    total = int(r.headers.get('content-length', 0))
                    if os.path.exists(path) and os.path.getsize(path) >= total and total > 0:
                        print(f"📦 {clean_filename}: Mevcut.")
                        success = True; break

                    with open(path, 'wb') as f:
                        # bar_format içinde {rate_fmt} hızı gösterir
                        with tqdm(total=total, unit='B', unit_scale=True, desc=f"🎬 {clean_filename[:20]}", 
                                  bar_format='{desc}: {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt} [{rate_fmt}]') as bar:
                            for chunk in r.iter_content(chunk_size=1024*1024):
                                if chunk:
                                    f.write(chunk)
                                    bar.update(len(chunk))
                    success = True
            except Exception as e:
                retries += 1
                print(f"⚠️ Hata: {e}. Retry: {retries}")
                time.sleep(1)

def folder_cleaner(path):
    """5. Seçenek: Detaylı raporlama yapan isim düzeltme fonksiyonu."""
    if not os.path.exists(path):
        print("❌ Yol bulunamadı!"); return
    
    files = os.listdir(path)
    fixed_count = 0
    already_clean = 0
    
    print(f"\n🛠 {len(files)} dosya denetleniyor...\n")
    
    for f in files:
        old_path = os.path.join(path, f)
        if os.path.isdir(old_path): continue
        
        new_name = turkish_to_english_engine(f)
        
        if f == new_name:
            print(f"✅ [DÜZGÜN]: {f}")
            already_clean += 1
        else:
            try:
                os.rename(old_path, os.path.join(path, new_name))
                print(f"🔄 [DÜZELTİLDİ]: {f} -> {new_name}")
                fixed_count += 1
            except Exception as e:
                print(f"❌ [HATA]: {f} düzeltilemedi! ({e})")

    print(f"\n--- İŞLEM RAPORU ---")
    print(f"✨ Zaten Düzgün: {already_clean}")
    print(f"🔧 Düzenlenen: {fixed_count}")
    print(f"📂 Toplam: {len(files)}")
    print(f"---------------------\n")

def main_menu():
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"""
==========================================
  VOD DOWNLOADER PRO DESIGN BY PROTON MEDIA
==========================================
1- M3U URL GİR (KATEGORİ SEÇMELİ)
2- M3U DOSYA SEÇ (YEREL)
3- M3U BİLGİ KONTROL (URL ANALİZ)
4- USER-AGENT LİSTESİNİ YENİLE
5- DOSYA İSİMLERİNİ DENETLE & DÜZELT
6- ÇIKIŞ
==========================================
""")
        choice = input("Seçiminiz: ")

        if choice == '1':
            url = input("\nM3U URL (Geri için 0): ").strip()
            if url == '0': continue
            target = input("İndirme Yolu (Enter=Downloads): ") or DOWNLOAD_DIR_DEFAULT
            try:
                content = requests.get(url, timeout=20).text
                cats = {k:v for k,v in sorted(parse_m3u_to_categories(content).items())}
                tasks = select_from_categories(cats)
                if tasks != "BACK": download_engine(tasks, target)
            except: print("❌ Liste yüklenemedi."); time.sleep(2)

        elif choice == '2':
            files = glob.glob("*.m3u")
            if not files: print("❌ M3U bulunamadı."); time.sleep(2); continue
            print("\n0- GERİ")
            for i, f in enumerate(files, 1): print(f"{i}- {f}")
            f_idx = input("\nSeçim: ")
            if f_idx == '0': continue
            target = input("İndirme Yolu: ") or DOWNLOAD_DIR_DEFAULT
            with open(files[int(f_idx)-1], 'r', encoding='utf-8', errors='ignore') as f:
                cats = parse_m3u_to_categories(f.read())
            tasks = select_from_categories(cats)
            if tasks != "BACK": download_engine(tasks, target)

        elif choice == '3':
            url = input("\nAnaliz edilecek URL (Geri için 0): ").strip()
            if url != '0': check_m3u_info(url)
            input("Devam etmek için Enter...")

        elif choice == '5':
            path = input("\nDenetlenecek Klasör Yolu (Geri için 0): ").strip()
            if path != '0': folder_cleaner(path)
            input("Devam etmek için Enter...")

        elif choice == '6': break

def parse_m3u_to_categories(content):
    categories = {}
    current_cat = "Diger"
    name = ""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith('#EXTINF:'):
            cat_match = re.search(r'group-title="([^"]+)"', line)
            current_cat = cat_match.group(1) if cat_match else "Belirtilmemis"
            name = line.split(',')[-1].strip()
        elif line.startswith('http'):
            if current_cat not in categories: categories[current_cat] = []
            categories[current_cat].append((line, name))
            name = ""
    return categories

def select_from_categories(categories):
    cat_names = sorted(list(categories.keys()))
    print("\n--- M3U KATEGORİ LİSTESİ ---")
    print("0- GERİ DÖN")
    for i, cat in enumerate(cat_names, 1):
        print(f"{i}- {cat} [{len(categories[cat])}]")
    print(f"{len(cat_names) + 1}- TÜMÜNÜ İNDİR")
    choice = input("\nSeçim: ")
    if choice == '0': return "BACK"
    try:
        idx = int(choice)
        if idx == len(cat_names) + 1:
            all_t = []; [all_t.extend(categories[c]) for c in cat_names]
            return all_t
        return categories[cat_names[idx-1]]
    except: return []

if __name__ == "__main__":
    load_ua_pool()
    main_menu()
