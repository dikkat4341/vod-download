import os, requests, re, sys, time, random, socket, glob
from tqdm import tqdm
from urllib.parse import urlparse

# --- YAPILANDIRMA ---
ua_file = 'user_agents.txt'
MAX_RETRIES = 30
DOWNLOAD_DIR_DEFAULT = "Downloads"

def generate_random_ua():
    """Taze ve güncel User-Agent üretir."""
    chrome_v = f"{random.randint(110, 122)}.0.{random.randint(1000, 6000)}.{random.randint(10, 150)}"
    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_v} Safari/537.36"

def load_ua_pool():
    """UA havuzunu yönetir, eksikse 30'a tamamlar."""
    pool = []
    if os.path.exists(ua_file):
        with open(ua_file, 'r', encoding='utf-8') as f:
            pool = [line.strip() for line in f if line.strip()]
    
    while len(pool) < 30:
        pool.append(generate_random_ua())
    
    with open(ua_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(pool))
    return pool

def remove_banned_ua(ua):
    """Banlanan UA'yı havuzdan çıkarır ve yenisini ekler."""
    pool = load_ua_pool()
    if ua in pool:
        pool.remove(ua)
        pool.append(generate_random_ua())
        with open(ua_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(pool))

def turkish_to_english(text):
    """Türkçe karakterleri ve geçersiz karakterleri temizler."""
    m = {'ı':'i','ü':'u','ğ':'g','ö':'o','ş':'s','ç':'c','İ':'I','Ü':'U','Ğ':'G','Ö':'O','Ş':'S','Ç':'C',' ':'_'}
    for tr, en in m.items(): text = text.replace(tr, en)
    # Sadece izin verilen karakterleri bırak: a-z, 0-9, nokta, alt çizgi, tire
    return re.sub(r'[^a-zA-Z0-9._-]', '', text)

def get_extension_from_response(url, response):
    """URL veya Mime-Type üzerinden en doğru uzantıyı bulur."""
    parsed_path = urlparse(url).path
    ext = os.path.splitext(parsed_path)[1].lower()
    
    valid_exts = ['.mp4', '.mkv', '.avi', '.ts', '.mov', '.m2ts', '.wmv', '.flv', '.mpg']
    if ext in valid_exts:
        return ext
    
    # Sunucu yanıtındaki Content-Type'ı kontrol et
    ctype = response.headers.get('Content-Type', '').lower()
    if 'video/mp4' in ctype: return '.mp4'
    if 'video/x-matroska' in ctype: return '.mkv'
    if 'video/mp2t' in ctype: return '.ts'
    if 'video/x-msvideo' in ctype: return '.avi'
    if 'video/quicktime' in ctype: return '.mov'
    
    return '.mkv' # Bulunamazsa güvenli liman mkv

def download_file(url, filename, target_dir):
    """Asıl indirme motoru: Kontrol, Resume ve Bar Yönetimi."""
    os.makedirs(target_dir, exist_ok=True)
    retries = 0
    
    while retries < MAX_RETRIES:
        ua_pool = load_ua_pool()
        selected_ua = random.choice(ua_pool)
        headers = {'User-Agent': selected_ua}
        
        try:
            # Önce sunucudan kafa bilgisini al (Boyut ve tip kontrolü için)
            with requests.get(url, headers=headers, stream=True, timeout=20) as r:
                if r.status_code in [403, 429]:
                    remove_banned_ua(selected_ua)
                    raise Exception(f"Ban/Limit Algılandı (UA Değiştiriliyor)")
                
                r.raise_for_status()
                
                # Uzantıyı ve temiz ismi belirle
                ext = get_extension_from_response(url, r)
                clean_name = turkish_to_english(filename)
                if not clean_name.lower().endswith(ext): clean_name += ext
                
                path = os.path.join(target_dir, clean_name)
                
                # --- MEVCUT DOSYA KONTROLÜ ---
                # Sunucunun bildirdiği toplam boyut
                server_size = int(r.headers.get('content-length', 0))
                
                if os.path.exists(path):
                    local_size = os.path.getsize(path)
                    if server_size > 0 and local_size >= server_size:
                        print(f"📦 {clean_name}: Zaten mevcut ve tam boyutta. Geçiliyor.")
                        return True
                    # Dosya varsa ama 0 KB ise veya eksikse temizle (veya resume mantığı eklenebilir)
                    if local_size == 0:
                        os.remove(path)

                # --- İNDİRME BAŞLATMA ---
                with open(path, 'wb') as f:
                    with tqdm(total=server_size, unit='B', unit_scale=True, unit_divisor=1024,
                              desc=f"🚀 {clean_name[:25]}",
                              bar_format='{desc}: {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt} [{rate_fmt}]') as bar:
                        for chunk in r.iter_content(chunk_size=1024*512):
                            if chunk:
                                f.write(chunk)
                                bar.update(len(chunk))
                
                if os.path.getsize(path) > 0:
                    print(f"✅ Başarıyla İndi: {clean_name}")
                    return True
                    
        except Exception as e:
            retries += 1
            print(f"⚠️ Hata: {e}. Deneme: {retries}/{MAX_RETRIES}")
            time.sleep(2)
            
    return False

def main():
    print("--- VOD Pro Downloader: DESIGN BY PROTON MEDIA SERVER ---")
    
    # M3U Dosyası bul
    m3u_list = glob.glob("*.m3u")
    if not m3u_list:
        print("❌ Hata: Klasörde .m3u dosyası bulunamadı!"); return
    
    # Yol al ve Klasör Oluştur (Eksiksiz Kontrol)
    target_input = input("İndirme Yolu (Enter = Downloads): ").strip()
    target_dir = target_input if target_input else DOWNLOAD_DIR_DEFAULT
    if not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)
        print(f"📁 Klasör oluşturuldu: {target_dir}")

    # Mevcut dosyaları tara ve isimlendirmeyi standart hale getir
    print("🔍 Mevcut dosyalar kontrol ediliyor...")
    for f in os.listdir(target_dir):
        clean_f = turkish_to_english(f)
        if f != clean_f:
            try:
                os.rename(os.path.join(target_dir, f), os.path.join(target_dir, clean_f))
            except: pass

    # M3U Listesini işle
    tasks = []
    with open(m3u_list[0], 'r', encoding='utf-8', errors='ignore') as f:
        current_name = ""
        for line in f:
            line = line.strip()
            if line.startswith('#EXTINF:'):
                current_name = line.split(',')[-1].strip()
            elif line.startswith('http'):
                if current_name:
                    tasks.append((line, current_name))
                    current_name = ""

    print(f"🚀 {len(tasks)} içerik kuyruğa alındı.\n")
    for url, name in tasks:
        download_file(url, name, target_dir)

    print("\n--- İşlem Tamamlandı ---")
    input("Kapatmak için Enter'a basın...")

if __name__ == "__main__":
    main()
