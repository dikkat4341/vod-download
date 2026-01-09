import os
import requests
import re
import sys
import time
import random
import glob
import json
import threading
import subprocess
from tqdm import tqdm
from urllib.parse import urlparse, unquote
from datetime import datetime

# --- YAPILANDIRMA ---
ua_file = 'user_agents.txt'
MAX_RETRIES = 30
DOWNLOAD_DIR_DEFAULT = "Downloads"
ARIA2_EXE = "aria2c.exe"  # Bu dosyayı program klasörüne koy!

# --- ARIA2 KONTROL ---
def check_aria2():
    if not os.path.exists(ARIA2_EXE):
        print("\n❌ aria2c.exe bulunamadı!")
        print("Lütfen https://aria2.github.io/ adresinden Windows 64-bit sürümü indirin.")
        print("aria2c.exe'yi bu programın yanına koyun.")
        input("Enter tuşuna bas...")
        return False
    return True

# --- GÜVENLİ DOSYA ADI TEMİZLEME ---
def clean_name_only(name):
    trans = str.maketrans('ıüğöşçİÜĞÖŞÇ', 'iugoscIUGOSC')
    name = name.translate(trans)
    name = name.replace(' ', '_')
    name = re.sub(r'[\/:*?"<>|]', '', name)
    name = re.sub(r'_+', '_', name)
    name = name.strip('_ .')
    return name if name else "Film"

# --- UZANTI ALMA ---
def get_extension_from_url(url):
    path = unquote(urlparse(url).path)
    _, ext = os.path.splitext(path)
    if ext and ext.lower() in ['.mp4', '.mkv', '.avi', '.ts', '.mov', '.wmv', '.flv']:
        return ext.lower()
    return '.mp4'

# --- FİNAL DOSYA ADI ---
def get_final_filename(url, m3u_name):
    try:
        head = requests.head(url, allow_redirects=True, timeout=12)
        if 'Content-Disposition' in head.headers:
            cd = head.headers['Content-Disposition']
            match = re.findall(r'filename[*]?=["\']?([^";\']+)', cd)
            if match:
                raw = unquote(match[-1])
                name, ext = os.path.splitext(raw)
                return clean_name_only(name) + ext.lower()
    except:
        pass
    
    cleaned = clean_name_only(m3u_name)
    ext = get_extension_from_url(url)
    return cleaned + ext

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

# --- API ANALİZ ---
def check_m3u_info(url):
    print("\nXTREAM API Analizi...")
    try:
        parsed = urlparse(url)
        params = dict(re.findall(r'(\w+)=([^&]+)', parsed.query))
        username = params.get('username')
        password = params.get('password')
        if not username or not password:
            print("Username/password bulunamadı.")
            return
        api_url = f"{parsed.scheme}://{parsed.netloc}/player_api.php?username={username}&password={password}"
        r = requests.get(api_url, timeout=15).json()
        u = r.get('user_info', {})
        exp = datetime.fromtimestamp(int(u.get('exp_date', 0))) if u.get('exp_date') else "Sınırsız"
        print(f"Durum: {u.get('status')}")
        print(f"Bitiş: {exp}")
        print(f"Bağlantı: {u.get('active_cons',0)} / {u.get('max_connections',0)}")
    except Exception as e:
        print("API hatası.")

# --- M3U PARSE VE SEÇİM ---
def parse_m3u_to_categories(content):
    cats = {}
    curr = "Diğer"
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith('#EXTINF:'):
            name_match = re.search(r',(.+)$', line)
            name = name_match.group(1).strip() if name_match else "İsimsiz"
            group_match = re.search(r'group-title="([^"]*)"', line)
            curr = group_match.group(1) if group_match else "Belirtilmemiş"
            i += 1
            if i < len(lines) and lines[i].strip().startswith('http'):
                url = lines[i].strip()
                cats.setdefault(curr, []).append((url, name))
        i += 1
    return cats

def select_from_categories(categories):
    if not categories:
        print("Kategori bulunamadı.")
        return "BACK"
    names = sorted(categories.keys())
    print("\n0 - GERİ")
    for i, name in enumerate(names, 1):
        print(f"{i} - {name} [{len(categories[name])}]")
    while True:
        choice = input("\nKategori seç: ").strip()
        if choice == '0': return "BACK"
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(names):
                selected = categories[names[idx]]
                break
        except: print("Geçersiz seçim.")
    print("\n0 - TÜMÜNÜ İNDİR")
    for i, (_, name) in enumerate(selected, 1):
        print(f"{i} - {name[:70]}")
    choice = input("\nSeçim (0=tümü, virgülle seç): ").strip()
    if not choice or choice == '0': return selected
    result = []
    for n in [x.strip() for x in choice.split(',') if x.strip().isdigit()]:
        try:
            result.append(selected[int(n)-1])
        except: pass
    return result or "BACK"

# --- İSİM DÜZELT ---
def folder_cleaner():
    path = input("Klasör yolu (boş=Downloads): ").strip() or DOWNLOAD_DIR_DEFAULT
    if not os.path.exists(path):
        print("Klasör yok.")
        return
    fixed = 0
    for f in os.listdir(path):
        full = os.path.join(path, f)
        if os.path.isfile(full):
            name, ext = os.path.splitext(f)
            new_name = clean_name_only(name) + ext
            if f != new_name:
                try:
                    new_full = os.path.join(path, new_name)
                    i = 1
                    base, ext2 = os.path.splitext(new_name)
                    while os.path.exists(new_full):
                        new_full = os.path.join(path, f"{base}_{i}{ext2}")
                        i += 1
                    os.rename(full, new_full)
                    print(f"{f} → {os.path.basename(new_full)}")
                    fixed += 1
                except: pass
    print(f"{fixed} dosya düzeltildi.")

# --- ARIA2 İLE İNDİRME MOTORU ---
def download_engine(tasks, target_dir):
    if not tasks or tasks == "BACK": return
    if not check_aria2():
        return
    
    os.makedirs(target_dir, exist_ok=True)
    success_count = 0
    
    for url, m3u_name in tasks:
        final_name = get_final_filename(url, m3u_name)
        
        out_path = os.path.join(target_dir, final_name)
        
        i = 1
        base, ext = os.path.splitext(final_name)
        while os.path.exists(out_path):
            final_name = f"{base}_{i}{ext}"
            out_path = os.path.join(target_dir, final_name)
            i += 1
        
        cmd = [
            ARIA2_EXE,
            '--max-connection-per-server=16',
            '--split=16',
            '--min-split-size=1M',
            '--max-tries=10',
            '--retry-wait=5',
            '--continue=true',
            '--auto-file-renaming=false',
            '--allow-overwrite=true',
            '--summary-interval=5',
            '--human-readable=true',
            '--console-log-level=warn',
            '--dir=' + target_dir,
            '--out=' + final_name,
            url
        ]
        
        print(f"\nİndiriliyor: {final_name}")
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                print(line.strip())
            process.wait()
            if process.returncode == 0:
                success_count += 1
                print(f"✅ TAMAM: {final_name}")
            else:
                print(f"❌ BAŞARISIZ: {m3u_name}")
        except Exception as e:
            print(f"Aria2 hatası: {e}")
    
    print(f"\n{success_count}/{len(tasks)} dosya indirildi (aria2 ile).")

# --- MENÜ ---
def main_menu():
    initialize_proxy_pool()
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"=== VOD PRO v35 (aria2 + Proxy'siz) ===\n")
        print("1 - M3U URL Gir")
        print("2 - M3U Dosya Seç")
        print("3 - API Analiz")
        print("4 - UA Yenile")
        print("5 - İsim Düzelt")
        print("6 - Proxy Ayar (devre dışı)")
        print("7 - Çıkış")
        choice = input("\nSeçim: ").strip()
        
        if choice == '1':
            url = input("\nM3U URL: ").strip()
            if url:
                try:
                    content = requests.get(url, timeout=30).text
                    cats = parse_m3u_to_categories(content)
                    tasks = select_from_categories(cats)
                    download_engine(tasks, DOWNLOAD_DIR_DEFAULT)
                except Exception as e:
                    print(f"Hata: {e}")
            input("\nEnter...")
            
        elif choice == '2':
            file = input("\nM3U dosya adı: ").strip()
            if os.path.exists(file):
                with open(file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                cats = parse_m3u_to_categories(content)
                tasks = select_from_categories(cats)
                download_engine(tasks, DOWNLOAD_DIR_DEFAULT)
            else:
                print("Dosya yok.")
            input("\nEnter...")
            
        elif choice == '3':
            url = input("\nXtream URL: ").strip()
            if url: check_m3u_info(url)
            input("\nEnter...")
            
        elif choice == '4':
            load_ua_pool(True)
            print("UA yenilendi.")
            input("\nEnter...")
            
        elif choice == '5':
            folder_cleaner()
            input("\nEnter...")
            
        elif choice == '6':
            print("\nProxy sistemi devre dışı bırakıldı.")
            input("\nEnter...")
            
        elif choice == '7':
            print("\nGörüşürüz Serdar abi! İyi indirimler! 🇹🇷\n")
            break

if __name__ == "__main__":
    main_menu()
