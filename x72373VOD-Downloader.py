import os
import requests
import re
import sys
import time
import random
from tqdm import tqdm

# --- AYARLAR ---
m3u_file = 'download.m3u'
DOWNLOAD_DIR = "Downloads"
MAX_RETRIES = 15

# 30 Farklı ve Güncel User-Agent Listesi
USER_AGENTS = [
    'VLC/3.0.18 LibVLC/3.0.18',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x46) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0',
    'Mozilla/5.0 (SMART-TV; Linux; Tizen 6.0) AppleWebkit/537.36 (KHTML, like Gecko) SamsungBrowser/4.0 Chrome/76.0.3809.146 Safari/537.36',
    'Mozilla/5.0 (DirectFB; Linux armv7l; HI_CHIP_ID=0x99; {Hisi-3798mv200}) AppleWebkit/537.36 (KHTML, like Gecko) Safari/537.36',
    'Lavf/58.76.100',
    'OTT-Player/2.1.0 (Linux; Android 11; TV Box Build/RQ3A.210705.001) Gecko/20100101 Firefox/85.0',
    'Mozilla/5.0 (Linux; Tizen 2.3) AppleWebkit/538.1 (KHTML, like Gecko) SamsungBrowser/1.0 TV Safari/538.1',
    'Mozilla/5.0 (Linux; Android 9; TESLA MediaBox X903) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36',
    'Mozilla/5.0 (Web0S; Linux/SmartTV) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/79.0.3945.79 Safari/537.36 WebAppManager',
    'GStreamer/1.18.5',
    'Mozilla/5.0 (PlayStation 5 7.40) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Safari/605.1.15',
    'Mozilla/5.0 (Nintendo Switch; WifiWebAuthApplet) AppleWebKit/606.4 (KHTML, like Gecko) NF/6.0.1.15.4 NintendoBrowser/5.1.0.20393',
    'Mozilla/5.0 (Linux; Android 12; Pixel 6 Build/SD1A.210817.036) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.163 Mobile Safari/537.36',
    'AppleCoreMedia/1.0.0.19G82 (iPhone; U; CPU OS 15_6 like Mac OS X; en_us)',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.2151.72',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; WOW64; Trident/7.0; rv:11.0) like Gecko',
    'Kodi/19.4 (Windows NT 10.0; WOW64) App_Ref/19.4.0',
    'Mozilla/5.0 (Linux; Android 11; Nvidia Shield Build/RQ1A.210105.003) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Safari/537.36',
    'Mozilla/5.0 (iPad; CPU OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 [FBAN/FBIOS;FBDV/iPhone14,5;FBMV/Apple;FBOS/iOS;FBPV/16.6;FBCR/Verizon;FBLC/en_US;FBNW/Wi-Fi]',
    'Mozilla/5.0 (SMART-TV; Linux; WebOS) AppleWebkit/538.2 (KHTML, like Gecko) SamsungBrowser/1.0 TV Safari/538.2',
    'Mag.250/2.2.0 (OS; Linux; Flash; Version/0.2.18-r14-250)'
]

def clean_name(name):
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def download_file(url, filename):
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    download_path = os.path.join(DOWNLOAD_DIR, filename)
    
    # Her indirme işlemi için rastgele bir User-Agent seçiliyor
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
            
            print(f"✅ İndi: {filename} (UA: {selected_ua[:30]}...)")
            return True

        except (requests.exceptions.RequestException, Exception) as e:
            retries += 1
            print(f"\n⚠️ Bağlantı koptu, yeni UA ile deneniyor ({retries}/{MAX_RETRIES})...")
            # Hata durumunda User-Agent'ı değiştirerek tekrar dene
            headers['User-Agent'] = random.choice(USER_AGENTS)
            time.sleep(3)
            continue
            
    print(f"❌ Başarısız: {filename}")
    return False

def main():
    print(f'--- VOD Downloader Pro (Anti-Ban & Stealth Mod) ---')
    print(f'Sistemde {len(USER_AGENTS)} adet User-Agent aktif.')
    
    if not os.path.exists(m3u_file):
        print(f'Hata: {m3u_file} bulunamadı.'); sys.exit(1)

    with open(m3u_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    download_list = []
    current_file = ""

    for line in lines:
        line = line.strip()
        if line.startswith('#EXTINF:'):
            name_part = line.split(',')[-1].strip()
            current_file = clean_name(name_part.replace('/', '_')) + '.mkv'
        elif line.startswith('http'):
            download_list.append((line, current_file))

    print(f'{len(download_list)} dosya sırayla indirilecek.\n')

    for url, filename in download_list:
        download_file(url, filename)

    print('\n--- Tüm liste tamamlandı ---')
    input("Kapatmak için Enter'a basın...")

if __name__ == "__main__":
    main()
