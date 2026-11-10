# 🎬 ReelSync: Bot da Instagram a TikTok con Interfaccia Web

Un bot completo con interfaccia web moderna per monitorare automaticamente i Reel pubblicati su un account Instagram (nel tuo caso l'account parrocchiale `@sacrocuoreasti`) e pubblicarli automaticamente su TikTok.

---

## 🚀 Avvio Rapido

La dashboard web è già attiva su:
👉 **[http://localhost:5005](http://localhost:5005)**

Per avviare o riavviare l'applicazione in qualsiasi momento dal terminale:
```bash
./start.sh
```

---

## 🌟 Funzionalità Principali

1. **Dashboard Web Moderna & Reattiva (Dark Mode)**
   - Visualizzazione in griglia di tutti i Reel rilevati su Instagram con copertine, date, didascalie e stato.
   - **Player video integrato**: puoi guardare e ascoltare direttamente i Reel scaricati all'interno della dashboard prima di pubblicarli.
   - Contatori in tempo reale: Reel rilevati, Pubblicati, Pronti, e con Audio protetto.

2. **Monitoraggio Automatico Instagram in Background**
   - Interroga periodicamente l'API Meta Graph utilizzando il token a lunga durata (60 giorni) presente in `psw.env`.
   - Rileva automaticamente ogni nuovo Reel pubblicato su `@sacrocuoreasti`.
   - Frequenza di controllo configurabile (es. ogni 5, 10, 15, 30 o 60 minuti).
   - Pulsante **"Rinnova Token (60gg)"** con 1 click direttamente dall'interfaccia.

3. **Download Automatico dei Video**
   - Scarica il file MP4 nativo dai server Meta direttamente nella cartella locale `downloads/`.
   - Formato video ideale per TikTok: risoluzione verticale 720x1280 (9:16), codec video H.264, audio stereo AAC.

4. **Gestione Audio Copyright Meta & Fallback Manuale**
   - Meta, per accordi di licenza sui brani musicali commerciali, non fornisce l'URL di download diretto dei Reel che utilizzano tracce audio con copyright.
   - Per questi Reel, la dashboard mostra un badge viola chiaro (*Audio Copyright*) e fornisce un comodo pulsante **"Carica MP4"** per caricare con drag-and-drop il video originale dal tuo computer e pubblicarlo subito su TikTok.

5. **Pubblicazione su TikTok (Content Posting API v2)**
   - **Pubblicazione Automatica**: se abilitata tramite lo switch nella dashboard, ogni nuovo Reel viene caricato e pubblicato su TikTok non appena scaricato.
   - **Pubblicazione Manuale On-Demand**: puoi cliccare su *"Pubblica su TikTok"* su qualsiasi Reel, modificare o perfezionare la didascalia, aggiungere hashtag e scegliere la privacy.
   - Supporto per diversi livelli di privacy:
     - `PUBLIC_TO_EVERYONE` (Pubblico a tutti)
     - `MUTUAL_FOLLOW_FRIENDS` (Solo amici)
     - `SELF_ONLY` (Solo io / Bozza privata per revisione interna)
   - Supporto **Modalità Test / Simulazione**: puoi collaudare l'intero flusso senza pubblicare realmente su TikTok finché non ottieni l'approvazione delle API sviluppatore.

6. **Personalizzazione Didascalie & Hashtag**
   - Aggiungi prefissi o suffissi automatici (es. `#sacrocuore #asti #chiesa #comunita`).
   - Opzione per rimuovere o mantenere le menzioni Instagram (`@...`).

7. **Log di Sistema in Tempo Reale**
   - Console visuale con filtro per livello (Info, Successi, Avvisi, Errori) per monitorare ogni operazione eseguita dal bot.

---

## 📂 Struttura del Progetto

```
ig to TikTok/
├── app.py                  # Server web Flask e API REST
├── bot_service.py          # Monitoraggio in background e automazione sync
├── instagram_client.py     # Client ufficiale Instagram Graph API
├── tiktok_client.py        # Client ufficiale TikTok Content Posting API v2
├── models.py               # Database SQLite (Reel, impostazioni, log)
├── config.py               # Configurazione percorsi e default
├── psw.env                 # Credenziali Instagram (ID e token Meta)
├── start.sh                # Script di avvio rapido con ambiente virtuale
├── requirements.txt        # Dipendenze Python
├── downloads/              # Cartella contenente i file video MP4 scaricati
├── data/                   # Cartella contenente il database bot.db
├── templates/
│   └── index.html          # Interfaccia grafica dashboard
└── static/
    ├── css/style.css       # Stili e animazioni
    └── js/app.js           # Logica client-side interattiva
```

---

## 🔑 Configurazione TikTok

Nel tab **"Impostazioni"** della dashboard puoi inserire:
- **TikTok Access Token** (generato da [developers.tiktok.com](https://developers.tiktok.com) con scope `video.publish` e `video.upload`).
- Oppure selezionare **"Modalità Test / Simulazione"** per provare tutte le funzionalità in anteprima.

