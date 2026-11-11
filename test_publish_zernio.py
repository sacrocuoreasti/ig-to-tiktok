import sys
import os
import time
import requests

def run_test(api_key=None):
    key = api_key or os.environ.get("ZERNIO_API_KEY")
    if not key:
        print("[!] Errore: Nessuna Zernio API Key fornita. Passala come argomento: python3 test_publish_zernio.py <API_KEY>")
        return

    base_url = "https://zernio.com/api/v1"
    headers = {
        "Authorization": f"Bearer {key.strip()}",
        "Content-Type": "application/json"
    }

    print("==================================================")
    print("[1] Verifica account connessi su Zernio...")
    print("==================================================")

    resp = requests.get(f"{base_url}/accounts", headers=headers, timeout=15)
    if resp.status_code != 200:
        print(f"[!] Errore connessione a Zernio (HTTP {resp.status_code}): {resp.text}")
        return

    data = resp.json()
    accounts = data.get("accounts") or data.get("data") or (data if isinstance(data, list) else [])
    print(f"[+] Trovati {len(accounts)} account collegati:")

    tiktok_account_id = None
    tiktok_username = None

    for acc in accounts:
        plat = acc.get("platform")
        uname = acc.get("username") or acc.get("displayName")
        acc_id = acc.get("_id") or acc.get("id")
        print(f"    - Piattaforma: {plat} | Utente: @{uname} | ID: {acc_id}")
        if plat == "tiktok" and not tiktok_account_id:
            tiktok_account_id = acc_id
            tiktok_username = uname

    if not tiktok_account_id:
        print("\n[!] ERRORE: Nessun account TikTok collegato trovato su Zernio!")
        print("    Vai su zernio.com e assicurati di aver fatto 'Connect Account' per TikTok.")
        return

    print(f"\n[+] Account TikTok selezionato: @{tiktok_username} (ID: {tiktok_account_id})")

    # 2. Crea un video di test se non esiste
    test_video_path = "test_video.mp4"
    if not os.path.exists(test_video_path):
        print("\n[2] Generazione video MP4 di test verticale (1080x1920)...")
        os.system("ffmpeg -y -f lavfi -i color=c=blue:s=1080x1920:d=5 -f lavfi -i anullsrc=r=44100:cl=stereo -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest test_video.mp4 > /dev/null 2>&1")

    file_size = os.path.getsize(test_video_path)
    print(f"[+] File video di test pronto: {test_video_path} ({file_size // 1024} KB)")

    # 3. Richiesta Presigned URL
    print("\n[3] Richiesta Presigned URL a Zernio...")
    presign_payload = {
        "filename": "test_video.mp4",
        "contentType": "video/mp4",
        "size": file_size
    }
    presign_res = requests.post(f"{base_url}/media/presign", headers=headers, json=presign_payload, timeout=15)
    if presign_res.status_code not in (200, 201):
        print(f"[!] Errore presign (HTTP {presign_res.status_code}): {presign_res.text}")
        return

    presign_data = presign_res.json()
    data_obj = presign_data.get("data", presign_data)
    upload_url = data_obj.get("uploadUrl")
    public_url = data_obj.get("publicUrl")

    print(f"[+] URL pubblico Zernio: {public_url}")

    # 4. Upload Binario
    print("\n[4] Caricamento del video su cloud storage Zernio...")
    with open(test_video_path, "rb") as f:
        put_res = requests.put(upload_url, data=f, headers={"Content-Type": "video/mp4"}, timeout=120)

    if put_res.status_code not in (200, 201, 204):
        print(f"[!] Errore upload binario (HTTP {put_res.status_code})")
        return

    print("[+] Video caricato con successo!")

    # 5. Pubblicazione su TikTok
    print("\n[5] Invio ordine di pubblicazione immediata a TikTok (publishNow: true)...")
    post_payload = {
        "content": "Test automatico Zernio -> TikTok 🚀 #test #parrocchia",
        "publishNow": True,
        "mediaItems": [
            {
                "type": "video",
                "url": public_url
            }
        ],
        "platforms": [
            {
                "platform": "tiktok",
                "accountId": tiktok_account_id,
                "platformSpecificData": {
                    "privacyLevel": "PUBLIC_TO_EVERYONE",
                    "allowComment": True,
                    "allowDuet": True,
                    "allowStitch": True,
                    "contentPreviewConfirmed": True,
                    "expressConsentGiven": True
                }
            }
        ]
    }

    post_res = requests.post(f"{base_url}/posts", headers=headers, json=post_payload, timeout=30)
    print(f"HTTP Status: {post_res.status_code}")
    print(f"Risposta Zernio:\n{post_res.text}")

    if post_res.status_code in (200, 201):
        pdata = post_res.json()
        print("\n==================================================")
        print("🎉 SUCCESSO! Il video è stato inviato a TikTok!")
        post_obj = pdata.get("post", pdata)
        for p in post_obj.get("platforms", []):
            if p.get("platform") == "tiktok":
                print(f"Stato TikTok: {p.get('status')}")
                if p.get("platformPostUrl"):
                    print(f"Link al video su TikTok: {p.get('platformPostUrl')}")
        print("==================================================")
    else:
        print("\n[!] Pubblicazione fallita. Leggi il messaggio di errore sopra.")

if __name__ == "__main__":
    key_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_test(key_arg)

