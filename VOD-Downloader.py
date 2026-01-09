import os, requests, re, sys, time, random, socket, glob
from tqdm import tqdm
from urllib.parse import urlparse

# --- YAPILANDIRMA ---
ua_file = 'user_agents.txt'
MAX_RETRIES = 30
DOWNLOAD_DIR_DEFAULT = "Downloads"

def generate_random_ua():
    """30+ farklı agent için taze UA üretir."""
    chrome_v = f"{random.randint(110, 122)}.0.{random.randint(1000, 6000)}.{random.randint(10, 150)}"
    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_v} Safari/537.36"

def load_ua_pool():
    pool = []
    if os.path.exists(ua_file):
        with open(ua_file, 'r', encoding='utf-8') as f:
            pool = [line.strip() for line in f if line.strip()]
    while len(pool) < 30: pool.append(generate_random_ua())
    with open(ua_file, 'w', encoding='utf-8') as f: f.write('\n'.join(pool))
    return pool

def remove_banned_ua(ua):
    pool = load_ua_pool()
    if ua in pool:
        pool.remove(ua); pool.append(generate_random_ua())
        with open(ua_file, 'w', encoding='utf-8') as f: f.write('\n'.join(pool))

def turkish_to_english(text):
    m = {'ı':'i','ü':'u','ğ':'g','ö':'o','ş':'s','ç':'c','İ':'I','Ü':'U','Ğ':'G','Ö':'O','Ş':'S','Ç':'C',' ':'_'}
    for tr, en in m.items(): text = text.replace(tr, en)
    return re.sub(r'[^a-zA-Z0-9._-]', '', text)

def get_extension_from_response(url, response):
    """URL'den veya Sunucu yanıtından (Mime-Type) gerçek uzantıyı belirler."""
    parsed_path = urlparse(url).path
    ext = os.path.splitext(parsed_path)[1].lower()
    
    if ext in ['.mp4', '.mkv', '.avi', '.ts', '.mov', '.m2ts', '.wmv']:
        return ext
    
    # URL'de yoksa Content-Type'a bak
    content_type = response.headers.get('Content-Type', '').lower()
    if 'video/mp4' in content_type: return '.mp4'
    if 'video/x-matroska' in content_type: return '.mkv'
    if 'video/mp2t' in content_type: return '.ts'
    if 'video/x-msvideo' in content_type: return '.avi'
    
    return '.mkv' # Hiçbir şey bulunamazsa varsayılan

def download_file(url, filename, target_dir):
    os.makedirs(target_dir, exist_ok=True)
    retries = 0
    
    while retries < MAX_RETRIES:
        ua_pool = load_ua_pool()
        selected_ua = random.choice(ua_pool)
        headers = {'User-Agent': selected_ua}
        
        try:
            with requests.get(url, headers=headers, stream=True, timeout=25) as r:
                if r.status_code in [403, 429]:
                    remove_banned_ua(selected_ua); raise Exception("Ban/Limit Algılandı")
                
                r.raise_for_status()
                
                # UZANTIYI BURADA TESPİT EDİYORUZ
                ext = get_extension_from_response(url, r)
                clean_name = turkish_to_english(filename)
                if not clean_name.lower().endswith(ext): clean_name += ext
                
                path = os.path.join(target_dir, clean_name)
                
                # 0 KB Kontrolü ve Resume (Eğer sunucu 416 verirse silip sıfırdan başlar)
                initial_pos = os.path.getsize(path) if os.path.exists(path) else 0
                total_size = int(r.headers.get('content-length', 0)) + initial_pos

                if initial_pos >= total_size and total_size > 0:
                    print(f"📦 {clean_name}: Dosya zaten hazır.")
                    return True

                with open(path, 'wb') as f:
                    with tqdm(total=total_size, unit='B', unit_scale=True, unit_divisor=1024,
                              desc=f"🚀 {clean_name[:25]}",
                              bar_format='{desc}: {percentage:3.0f}% |{bar}| {n_fmt}/{total_fmt} [{rate_fmt}]') as bar:
                        for chunk in r.iter_content(chunk_size=1024*512):
                            if chunk:
                                f.write(chunk)
                                bar.update(len(chunk))
                
                if os.path.getsize(path) > 0:
                    print(f"✅ Tamamlandı: {clean_name}")
                    return True
                    
        except Exception as e:
            retries += 1
            print(f"⚠️ Hata: {e}. Retry: {retries}")
            time.sleep(2)
    return False

def main():
    print("--- VOD Pro Downloader: MULTI-FORMAT MASTER v6 ---")
    m3u_list = glob.glob("*.m3u")
    if not m3u_list: print("❌ M3U Bulunamadı!"); return
    
    target = input("İndirme Yolu (Enter=Downloads): ").strip() or DOWNLOAD_DIR_DEFAULT
    
    # Mevcut dosyaları tara ve isimlerini/uzantılarını senin istediğin temiz formata çevir
    if os.path.exists(target):
        for f in os.listdir(target):
            clean_f = turkish_to_english(f)
            if f != clean_f:
                try: os.rename(os.path.join(target, f), os.path.join(target, clean_f))
                except: pass

    with open(m3u_list[0], 'r', encoding='utf-8', errors='ignore') as f:
        tasks = []; name = ""
        for line in f:
            if line.startswith('#EXTINF:'): name = line.split(',')[-1].strip()
            elif line.startswith('http'): tasks.append((line.strip(), name)); name = ""

    for url, name in tasks: download_file(url, name, target)

if __name__ == "__main__": main()
