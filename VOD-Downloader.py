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
        pool = [generate_random_ua() for _ in range(35)]
        with open(ua_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(pool))
        if update: print("✅ User-Agent listesi güncellendi.")
    return pool

def turkish_to_english(text):
    m = {'ı':'i','ü':'u','ğ':'g','ö':'o','ş':'s','ç':'c','İ':'I','Ü':'U','Ğ':'G','Ö':'O','Ş':'S','Ç':'C',' ':'_'}
    for tr, en in m.items(): text = text.replace(tr, en)
    return re.sub(r'[^a-zA-Z0-9._-]', '', text)

def parse_m3u_to_categories(content):
    """M3U içeriğini akıllıca kategorilere ayırır."""
    categories = {}
    current_cat = "Diger"
    lines = content.splitlines()
    
    name = ""
    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF:'):
            # group-title tespiti
            cat_match = re.search(r'group-title="([^"]+)"', line)
            current_cat = cat_match.group(1) if cat_match else "Belirtilmemis"
            name = line.split(',')[-1].strip()
        elif line.startswith('http'):
            if current_cat not in categories:
                categories[current_cat] = []
            categories[current_cat].append((line, name))
            name = ""
    return categories

def select_from_categories(categories):
    """Kullanıcıya kategorileri sunar ve seçimini döner."""
    cat_names = sorted(list(categories.keys()))
    print("\n--- M3U KATEGORİ LİSTESİ ---")
    for i, cat in enumerate(cat_names, 1):
        print(f"{i}- {cat} [{len(categories[cat])} İçerik]")
    
    print(f"{len(cat_names) + 1}- TÜMÜNÜ İNDİR")
    
    try:
        choice = int(input("\nSeçiminiz (Sayı): "))
        if choice == len(cat_names) + 1:
            all_tasks = []
            for c in cat_names: all_tasks.extend(categories[c])
            return all_tasks
        selected_cat = cat_names[choice - 1]
        return categories[selected_cat]
    except:
        print("⚠️ Geçersiz seçim, işlem iptal edildi."); return []

def get_extension_from_response(url, response):
    parsed_path = urlparse(url).path
    ext = os.path.splitext(parsed_path)[1].lower()
    valid_exts = ['.mp4', '.mkv', '.avi', '.ts', '.mov', '.m2ts', '.wmv']
    if ext in valid_exts: return ext
    ctype = response.headers.get('Content-Type', '').lower()
    if 'video/mp4' in ctype: return '.mp4'
    if 'video/x-matroska' in ctype: return '.mkv'
    if 'video/mp2t' in ctype: return '.ts'
    return '.mkv'

def download_engine(tasks, target_dir):
    if not tasks: return
    os.makedirs(target_dir, exist_ok=True)
    print(f"🚀 Toplam {len(tasks)} içerik işleniyor...\n")
    
    for url, name in tasks:
        retries = 0
        success = False
        while retries < MAX_RETRIES and not success:
            ua = random.choice(load_ua_pool())
            try:
                with requests.get(url, headers={'User-Agent': ua}, stream=True, timeout=25) as r:
                    r.raise_for_status()
                    ext = get_extension_from_response(url, r)
                    path = os.path.join(target_dir, turkish_to_english(name) + ext)
                    
                    total = int(r.headers.get('content-length', 0))
                    # Mevcut dosya kontrolü
                    if os.path.exists(path) and os.path.getsize(path) >= total and total > 0:
                        print(f"📦 {name} zaten mevcut, geçildi.")
                        success = True; break

                    with open(path, 'wb') as f:
                        with tqdm(total=total, unit='B', unit_scale=True, desc=f"🎬 {name[:20]}", 
                                  bar_format='{desc}: {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt} [{rate_fmt}]') as bar:
                            for chunk in r.iter_content(chunk_size=1024*512):
                                if chunk: f.write(chunk); bar.update(len(chunk))
                    success = True
            except Exception as e:
                retries += 1
                print(f"⚠️ Hata: {e}. Retry: {retries}")
                time.sleep(1)

def main_menu():
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"""
==========================================
    VOD DOWNLOADER PRO DESIGN BY PROTON MEDIA
==========================================
1- M3U URL GİR (KATEGORİ SEÇMELİ)
2- M3U DOSYA SEÇ (MEVCUT DOSYADAN)
3- M3U BİLGİ KONTROL (URL ANALİZ)
4- USER-AGENT LİSTESİNİ YENİLE
5- DOSYA İSİMLERİNİ DÜZELT (KLASÖR)
6- ÇIKIŞ
==========================================
""")
        choice = input("Seçiminiz: ")

        if choice == '1':
            url = input("M3U URL: ").strip()
            target = input("İndirme Yolu (Enter=Downloads): ") or DOWNLOAD_DIR_DEFAULT
            try:
                print("📡 Liste çekiliyor...")
                content = requests.get(url, timeout=30).text
                categories = parse_m3u_to_categories(content)
                tasks = select_from_categories(categories)
                download_engine(tasks, target)
            except Exception as e: print(f"❌ Hata: {e}")
            input("\nDevam etmek için Enter...")

        elif choice == '2':
            m3u_files = glob.glob("*.m3u")
            if not m3u_files:
                print("❌ Klasörde .m3u dosyası bulunamadı."); time.sleep(2); continue
            
            print("\nBulunan Dosyalar:")
            for i, f in enumerate(m3u_files, 1): print(f"{i}- {f}")
            f_idx = int(input("Dosya No: ")) - 1
            
            target = input("İndirme Yolu (Enter=Downloads): ") or DOWNLOAD_DIR_DEFAULT
            with open(m3u_files[f_idx], 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            categories = parse_m3u_to_categories(content)
            tasks = select_from_categories(categories)
            download_engine(tasks, target)
            input("\nDevam etmek için Enter...")

        elif choice == '4':
            load_ua_pool(update=True)
            time.sleep(2)

        elif choice == '5':
            path = input("Düzenlenecek Klasör Yolu: ").strip()
            if os.path.exists(path):
                for f in os.listdir(path):
                    os.rename(os.path.join(path, f), os.path.join(path, turkish_to_english(f)))
                print("✅ İsimler temizlendi.")
            else: print("❌ Yol bulunamadı.")
            time.sleep(2)

        elif choice == '6': break

if __name__ == "__main__":
    load_ua_pool()
    main_menu()
