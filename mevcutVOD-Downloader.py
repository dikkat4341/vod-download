import os
import requests
import re
import sys
import time
import random
from tqdm import tqdm

# --- AYARLAR ---
m3u_file = 'download.m3u'
MAX_RETRIES = 15

# 30 Farklı User-Agent Listesi (Önceki listedeki gibi zengin tutuldu)
USER_AGENTS = [
    'VLC/3.0.18 LibVLC/3.0.18',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (SMART-TV; Linux; Tizen 6.0) AppleWebkit/537.36 (KHTML, like Gecko) SamsungBrowser/4.0 Chrome/76.0.3809.146 Safari/537.36',
    'Mag.250/2.2.0 (OS; Linux; Flash; Version/0.2.18-r14-250)',
    # ... (Diğer UA'lar çalışma mantığında saklıdır)
]

def clean_name(name):
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def download_file(url, filename, download_dir):
    # Klasör oluşturma (Eğer yoksa)
    if not os.path.exists(download_dir):
        try:
            os.makedirs(download_dir, exist_ok=True)
        except Exception as e:
            print(f"❌ Klasör oluşturulamadı: {e}")
            return False

    download_path = os.path.join(download_dir, filename)
    selected_ua = random.choice(USER_AGENTS)
    headers = {'User-Agent': selected_ua}
    
    retries = 0
    while retries < MAX_RETRIES:
        try:
            initial_pos = os.path.getsize(download_path) if os.path.exists(download_path) else 0
            if initial_pos > 0:
                headers['Range'] = f'bytes={initial_pos}-'
            
            response = requests.get(url, headers=headers, stream=True, timeout=30)
            
            if response.status_code not in [200, 206]:
                print(f"\n❌ Sunucu hatası ({response.status_code}): {filename}")
                return False

            total_size = int(response.headers.get('content-length', 0)) + initial_pos
            if initial_pos >= total_size and total_size != 0:
                print(f"✅ Zaten var: {filename}")
                return True

            mode = 'ab' if initial_pos > 0 else 'wb'
            with open(download_path, mode) as f:
                with tqdm(total=total_size, unit='B', unit_scale=True, desc=filename[:30], initial=initial_pos, leave=True) as bar:
                    for chunk in response.iter_content(chunk_size=1024*1024):
                        if chunk:
                            f.write(chunk)
                            bar.update(len(chunk))
            return True

        except Exception as e:
            retries += 1
            print(f"\n⚠️ Bağlantı koptu, yeniden deneniyor ({retries}/{MAX_RETRIES})...")
            headers['User-Agent'] = random.choice(USER_AGENTS)
            time.sleep(3)
            continue
    return False

def main():
    print(f'--- VOD Downloader Pro (Custom Path & Stealth) ---')
    
    # --- YOL SEÇİMİ BÖLÜMÜ ---
    print("\nLütfen indirme yapmak istediğiniz klasör yolunu yapıştırın.")
    print("Örn: D:\\IPTV_Indirmeleri veya C:\\Users\\Ad\\Desktop\\VOD")
    user_path = input("Klasör Yolu (Boş bırakırsanız 'Downloads' klasörü kullanılır): ").strip()
    
    if not user_path:
        target_dir = "Downloads"
    else:
        # Tırnak işaretlerini temizle (yolu kopyalayıp yapıştırırken gelebilir)
        target_dir = user_path.replace('"', '').replace("'", "")

    print(f"Hedef Klasör: {target_dir}\n")
    # ------------------------

    if not os.path.exists(m3u_file):
        print(f'Hata: {m3u_file} bulunamadı.'); sys.exit(1)

    with open(m3u_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    download_list = []
    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF:'):
            name_part = line.split(',')[-1].strip()
            current_file = clean_name(name_part.replace('/', '_')) + '.mkv'
        elif line.startswith('http'):
            download_list.append((line, current_file))

    for url, filename in download_list:
        download_file(url, filename, target_dir)

    print('\n--- Tüm işlemler bitti ---')
    input("Kapatmak için Enter'a basın...")

if __name__ == "__main__":
    main()
