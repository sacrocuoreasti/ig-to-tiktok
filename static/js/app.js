// ReelSync Frontend Application Logic

let currentTab = 'feed';
let currentFilter = 'all';
let allReels = [];
let botStatus = {};
let selectedUploadFile = null;

document.addEventListener('DOMContentLoaded', () => {
    initEventListeners();
    fetchStatus();
    loadReels();
    loadSettings();
    loadLogs();

    // Auto-refresh status and reels every 6 seconds
    setInterval(fetchStatus, 6000);
});

function initEventListeners() {
    // Header buttons
    document.getElementById('btn-force-sync').addEventListener('click', forceSync);
    document.getElementById('btn-toggle-bot').addEventListener('click', toggleBot);

    // Auto-publish toggle switch in banner
    const autoPublishSwitch = document.getElementById('toggle-auto-publish');
    autoPublishSwitch.addEventListener('change', async (e) => {
        const enabled = e.target.checked;
        await saveSetting('auto_publish', enabled ? 'true' : 'false');
        showToast(enabled ? 'Auto-pubblicazione su TikTok ATTIVATA' : 'Auto-pubblicazione DISATTIVATA', 'info');
        fetchStatus();
    });

    // Caption character counter
    const captionInput = document.getElementById('modal-publish-caption');
    if (captionInput) {
        captionInput.addEventListener('input', () => {
            const count = captionInput.value.length;
            document.getElementById('caption-char-count').innerText = `${count} / 2200`;
        });
    }
}

// ----------------------------------------------------
// TABS & NAVIGATION
// ----------------------------------------------------
function switchTab(tabName) {
    currentTab = tabName;
    const tabs = ['feed', 'settings', 'logs', 'guide'];

    tabs.forEach(t => {
        const sec = document.getElementById(`tab-${t}`);
        const btn = document.getElementById(`tab-btn-${t}`);
        if (t === tabName) {
            sec.classList.remove('hidden');
            btn.className = 'py-3 px-1 border-b-2 font-medium text-pink-400 border-pink-500 flex items-center gap-2 transition';
        } else {
            sec.classList.add('hidden');
            btn.className = 'py-3 px-1 border-b-2 font-medium text-slate-400 border-transparent hover:text-slate-200 flex items-center gap-2 transition';
        }
    });

    if (tabName === 'logs') {
        loadLogs();
    } else if (tabName === 'feed') {
        loadReels();
    } else if (tabName === 'settings') {
        loadSettings();
    }

    lucide.createIcons();
}

// ----------------------------------------------------
// STATUS & MONITORING
// ----------------------------------------------------
async function fetchStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();

        botStatus = data.bot;
        const stats = data.stats;
        const ig = data.instagram;

        // Header Bot Status
        const pulse = document.getElementById('header-bot-pulse');
        const statusText = document.getElementById('header-bot-status-text');
        const toggleBtnText = document.getElementById('btn-toggle-bot-text');
        const toggleBtn = document.getElementById('btn-toggle-bot');

        if (botStatus.running) {
            pulse.className = 'inline-block w-2 h-2 rounded-full bg-emerald-400 animate-pulse';
            statusText.innerText = botStatus.is_checking ? 'Verifica in corso...' : 'Monitoraggio Attivo';
            toggleBtnText.innerText = 'Bot Attivo';
            toggleBtn.className = 'inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-600/30 transition';
        } else {
            pulse.className = 'inline-block w-2 h-2 rounded-full bg-amber-400';
            statusText.innerText = 'In Pausa';
            toggleBtnText.innerText = 'Bot in Pausa';
            toggleBtn.className = 'inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-amber-600/20 text-amber-400 border border-amber-500/30 hover:bg-amber-600/30 transition';
        }

        // Stats Cards
        document.getElementById('stat-total').innerText = stats.total_reels || 0;
        document.getElementById('stat-published').innerText = stats.published || 0;
        document.getElementById('stat-pending').innerText = stats.pending || 0;
        document.getElementById('stat-restricted').innerText = stats.restricted || 0;

        // Filter badges counts
        document.getElementById('count-all').innerText = stats.total_reels || 0;
        document.getElementById('count-published').innerText = stats.published || 0;
        document.getElementById('count-downloaded').innerText = stats.pending || 0;
        document.getElementById('count-restricted').innerText = stats.restricted || 0;
        document.getElementById('count-error').innerText = stats.errors || 0;

        // Banner info
        if (ig && ig.username) {
            document.getElementById('banner-ig-user').innerText = `@${ig.username}`;
        }
        document.getElementById('banner-last-check').innerText = botStatus.last_check ? formatTime(botStatus.last_check) : 'Non ancora eseguito';
        document.getElementById('banner-next-check').innerText = botStatus.next_check ? formatTime(botStatus.next_check) : '--:--';

        // Auto publish toggle sync
        const autoPublishSwitch = document.getElementById('toggle-auto-publish');
        if (autoPublishSwitch && document.activeElement !== autoPublishSwitch) {
            autoPublishSwitch.checked = botStatus.auto_publish;
        }

    } catch (err) {
        console.error('Errore fetchStatus:', err);
    }
}

async function toggleBot() {
    try {
        const res = await fetch('/api/bot/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
        const data = await res.json();
        showToast(data.running ? 'Bot avviato' : 'Bot messo in pausa', 'info');
        fetchStatus();
    } catch (err) {
        showToast('Errore durante il cambio di stato del bot', 'error');
    }
}

async function forceSync() {
    const btn = document.getElementById('btn-force-sync');
    const originalHtml = btn.innerHTML;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 animate-spin"></i><span>Controllo in corso...</span>`;
    btn.disabled = true;
    lucide.createIcons();

    try {
        const res = await fetch('/api/bot/sync', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(`Controllo completato! Trovati ${data.new_count} nuovi Reel (${data.downloaded_count} scaricati)`, 'success');
        } else {
            showToast(`Errore: ${data.error || data.message}`, 'error');
        }
        await loadReels();
        await fetchStatus();
    } catch (err) {
        showToast('Errore durante la verifica', 'error');
    } finally {
        btn.innerHTML = originalHtml;
        btn.disabled = false;
        lucide.createIcons();
    }
}

// ----------------------------------------------------
// REELS FEED & CARDS
// ----------------------------------------------------
async function loadReels() {
    try {
        const res = await fetch(`/api/reels?status=${currentFilter}&limit=60`);
        const data = await res.json();
        if (data.success) {
            allReels = data.reels;
            renderReels(data.reels);
        }
    } catch (err) {
        console.error('Errore loadReels:', err);
    }
}

function setFilter(filter) {
    currentFilter = filter;
    document.querySelectorAll('.filter-btn').forEach(b => {
        if (b.dataset.filter === filter) {
            b.className = 'filter-btn active px-3 py-1.5 rounded-lg text-xs font-semibold bg-rose-600 text-white border border-rose-500';
        } else {
            b.className = 'filter-btn px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-900 text-slate-400 border border-slate-800 hover:text-slate-200';
        }
    });
    loadReels();
}

function renderReels(reels) {
    const container = document.getElementById('reels-grid');
    if (!reels || reels.length === 0) {
        container.innerHTML = `
            <div class="col-span-full py-16 text-center text-slate-500 bg-slate-900/30 rounded-2xl border border-slate-800/60">
                <i data-lucide="inbox" class="w-10 h-10 mx-auto mb-2 text-slate-600"></i>
                <p class="text-sm font-semibold text-slate-400">Nessun Reel trovato per questo filtro.</p>
                <p class="text-xs text-slate-600 mt-1">Clicca su "Verifica Ora" in alto per interrogare Instagram.</p>
            </div>
        `;
        lucide.createIcons();
        return;
    }

    container.innerHTML = reels.map(r => createReelCardHtml(r)).join('');
    lucide.createIcons();
}

function createReelCardHtml(reel) {
    const statusBadges = {
        'new': `<span class="px-2 py-0.5 text-[10px] font-bold rounded-md bg-blue-500/20 text-blue-400 border border-blue-500/30">Nuovo</span>`,
        'downloaded': `<span class="px-2 py-0.5 text-[10px] font-bold rounded-md bg-amber-500/20 text-amber-400 border border-amber-500/30 flex items-center gap-1"><i data-lucide="check" class="w-3 h-3"></i> Pronto per TikTok</span>`,
        'published': `<span class="px-2 py-0.5 text-[10px] font-bold rounded-md bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 flex items-center gap-1"><i data-lucide="share-2" class="w-3 h-3"></i> Pubblicato su TikTok</span>`,
        'published_test': `<span class="px-2 py-0.5 text-[10px] font-bold rounded-md bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 flex items-center gap-1"><i data-lucide="flask-conical" class="w-3 h-3"></i> Simulato (Test TikTok)</span>`,
        'audio_restricted': `<span class="px-2 py-0.5 text-[10px] font-bold rounded-md bg-purple-500/20 text-purple-300 border border-purple-500/30 flex items-center gap-1"><i data-lucide="disc" class="w-3 h-3"></i> Audio Copyright (Carica MP4)</span>`,
        'error': `<span class="px-2 py-0.5 text-[10px] font-bold rounded-md bg-rose-500/20 text-rose-400 border border-rose-500/30">Errore</span>`,
        'skipped': `<span class="px-2 py-0.5 text-[10px] font-bold rounded-md bg-slate-700 text-slate-400">Ignorato</span>`
    };

    const statusBadge = statusBadges[reel.status] || `<span class="px-2 py-0.5 text-[10px] rounded-md bg-slate-800 text-slate-400">${reel.status}</span>`;
    const formattedDate = formatDate(reel.timestamp);
    const shortCaption = reel.caption ? (reel.caption.length > 130 ? reel.caption.substring(0, 130) + '...' : reel.caption) : 'Nessuna didascalia';

    const hasVideo = reel.status === 'downloaded' || reel.status === 'published' || reel.status === 'published_test';

    return `
        <div class="reel-card bg-slate-900/70 border border-slate-800/80 rounded-2xl overflow-hidden flex flex-col justify-between" id="card-${reel.id}">
            <!-- Media / Thumbnail Header -->
            <div class="relative bg-slate-950 aspect-[9/10] overflow-hidden group">
                <img src="${reel.thumbnail_url || 'https://images.unsplash.com/photo-1611162617213-7d7a39e9b1d7?w=600&auto=format&fit=crop&q=80'}" 
                     alt="Reel Cover" 
                     class="w-full h-full object-cover group-hover:scale-105 transition duration-500"
                     loading="lazy"
                     onerror="this.src='https://images.unsplash.com/photo-1611162617213-7d7a39e9b1d7?w=600&auto=format&fit=crop&q=80'">
                
                <!-- Overlay gradient -->
                <div class="absolute inset-0 bg-gradient-to-t from-slate-950 via-transparent to-black/40"></div>

                <!-- Top Badges -->
                <div class="absolute top-3 left-3 right-3 flex items-center justify-between">
                    <div>${statusBadge}</div>
                    <a href="${reel.permalink}" target="_blank" class="w-7 h-7 rounded-full bg-black/60 backdrop-blur hover:bg-pink-600 text-white flex items-center justify-center transition shadow">
                        <i data-lucide="external-link" class="w-3.5 h-3.5"></i>
                    </a>
                </div>

                <!-- Play button overlay if downloaded -->
                ${hasVideo ? `
                    <button onclick="openVideoModal('${reel.id}')" class="absolute inset-0 flex items-center justify-center bg-black/30 opacity-80 hover:opacity-100 transition group-hover:scale-110">
                        <div class="w-12 h-12 rounded-full bg-pink-500/90 text-white flex items-center justify-center shadow-lg shadow-pink-500/40">
                            <i data-lucide="play" class="w-6 h-6 ml-0.5 fill-current"></i>
                        </div>
                    </button>
                ` : ''}

                <!-- Date chip -->
                <div class="absolute bottom-2 left-3 text-[11px] text-slate-300 font-medium drop-shadow">
                    <i data-lucide="calendar" class="w-3 h-3 inline mr-1 text-slate-400"></i>
                    ${formattedDate}
                </div>
            </div>

            <!-- Content Body -->
            <div class="p-4 flex-1 flex flex-col justify-between space-y-3">
                <p class="text-xs text-slate-300 leading-relaxed font-normal whitespace-pre-line line-clamp-3">
                    ${escapeHtml(shortCaption)}
                </p>

                ${reel.error_message ? `
                    <div class="text-[11px] p-2 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-300 flex items-start gap-1.5">
                        <i data-lucide="alert-circle" class="w-3.5 h-3.5 flex-shrink-0 mt-0.5"></i>
                        <span class="break-all">${escapeHtml(reel.error_message)}</span>
                    </div>
                ` : ''}

                <!-- Actions -->
                <div class="pt-2 border-t border-slate-800/80 flex items-center justify-between gap-2">
                    ${hasVideo ? `
                        <button onclick="openPublishModal('${reel.id}')" class="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold bg-gradient-to-r from-pink-500 to-cyan-500 hover:opacity-95 text-slate-950 shadow-md shadow-pink-500/20 transition">
                            <i data-lucide="send" class="w-3.5 h-3.5"></i>
                            <span>${reel.status.startsWith('published') ? 'Ripubblica' : 'Pubblica su TikTok'}</span>
                        </button>
                    ` : (reel.status === 'audio_restricted' ? `
                        <button onclick="openUploadModal('${reel.id}')" class="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold bg-purple-600 hover:bg-purple-500 text-white shadow-md shadow-purple-600/20 transition">
                            <i data-lucide="upload" class="w-3.5 h-3.5"></i>
                            <span>Carica MP4</span>
                        </button>
                    ` : `
                        <span class="text-[11px] text-slate-500 italic">In attesa del video...</span>
                    `)}

                    <button onclick="skipReel('${reel.id}')" title="Ignora Reel" class="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition">
                        <i data-lucide="eye-off" class="w-3.5 h-3.5"></i>
                    </button>
                </div>
            </div>
        </div>
    `;
}

// ----------------------------------------------------
// MODAL: VIDEO PREVIEW
// ----------------------------------------------------
function openVideoModal(reelId) {
    const modal = document.getElementById('modal-video');
    const player = document.getElementById('modal-video-player');
    player.src = `/api/video/${reelId}`;
    modal.classList.remove('hidden');
    player.play().catch(() => {});
}

function closeVideoModal() {
    const modal = document.getElementById('modal-video');
    const player = document.getElementById('modal-video-player');
    player.pause();
    player.src = '';
    modal.classList.add('hidden');
}

// ----------------------------------------------------
// MODAL: PUBLISH TO TIKTOK
// ----------------------------------------------------
function openPublishModal(reelId) {
    const reel = allReels.find(r => r.id === reelId);
    if (!reel) return;

    document.getElementById('modal-publish-reel-id').value = reelId;
    
    // Format preview caption using current settings
    const prefix = document.getElementById('setting-caption-prefix')?.value || '';
    const suffix = document.getElementById('setting-caption-suffix')?.value || '#reel #chiesa #comunita';
    const orig = reel.caption || '';
    
    let defaultCaption = orig;
    if (prefix) defaultCaption = `${prefix}\n\n${defaultCaption}`;
    if (suffix) defaultCaption = `${defaultCaption}\n\n${suffix}`;

    const captionInput = document.getElementById('modal-publish-caption');
    captionInput.value = defaultCaption.trim();
    document.getElementById('caption-char-count').innerText = `${captionInput.value.length} / 2200`;

    document.getElementById('modal-publish').classList.remove('hidden');
    lucide.createIcons();
}

function closePublishModal() {
    document.getElementById('modal-publish').classList.add('hidden');
}

async function submitPublishReel() {
    const reelId = document.getElementById('modal-publish-reel-id').value;
    const caption = document.getElementById('modal-publish-caption').value;
    const privacy = document.getElementById('modal-publish-privacy').value;
    const btn = document.getElementById('btn-confirm-publish');

    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>Invio a TikTok...</span>`;
    lucide.createIcons();

    try {
        const res = await fetch(`/api/reels/${reelId}/publish`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ caption, privacy_level: privacy })
        });
        const data = await res.json();

        if (data.success) {
            showToast(`Reel pubblicato su TikTok! ${data.mode === 'test_mode' ? '(Simulazione Test)' : ''}`, 'success');
            closePublishModal();
            loadReels();
            fetchStatus();
        } else {
            showToast(`Errore pubblicazione: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast('Errore durante la pubblicazione', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i data-lucide="send" class="w-4 h-4"></i><span>Pubblica Ora</span>`;
        lucide.createIcons();
    }
}

// ----------------------------------------------------
// MODAL: UPLOAD MP4
// ----------------------------------------------------
function openUploadModal(reelId) {
    document.getElementById('modal-upload-reel-id').value = reelId;
    document.getElementById('input-video-file').value = '';
    document.getElementById('upload-file-label').innerText = 'Clicca qui per selezionare il video (.mp4)';
    selectedUploadFile = null;
    document.getElementById('modal-upload').classList.remove('hidden');
    lucide.createIcons();
}

function closeUploadModal() {
    document.getElementById('modal-upload').classList.add('hidden');
}

function handleFileSelect(e) {
    const file = e.target.files[0];
    if (file) {
        selectedUploadFile = file;
        const sizeMb = (file.size / (1024 * 1024)).toFixed(1);
        document.getElementById('upload-file-label').innerText = `${file.name} (${sizeMb} MB)`;
    }
}

async function submitVideoUpload() {
    const reelId = document.getElementById('modal-upload-reel-id').value;
    if (!selectedUploadFile) {
        showToast('Seleziona prima un file MP4', 'error');
        return;
    }

    const btn = document.getElementById('btn-confirm-upload');
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i><span>Caricamento...</span>`;
    lucide.createIcons();

    try {
        const formData = new FormData();
        formData.append('video', selectedUploadFile);

        const res = await fetch(`/api/reels/${reelId}/upload`, {
            method: 'POST',
            body: formData
        });
        const data = await res.json();

        if (data.success) {
            showToast('Video MP4 caricato con successo! Ora è pronto per TikTok.', 'success');
            closeUploadModal();
            loadReels();
            fetchStatus();
        } else {
            showToast(`Errore: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast('Errore durante il caricamento del file', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = `<i data-lucide="upload-cloud" class="w-4 h-4"></i><span>Carica Video</span>`;
        lucide.createIcons();
    }
}

async function skipReel(reelId) {
    if (!confirm('Vuoi contrassegnare questo Reel come ignorato?')) return;
    try {
        await fetch(`/api/reels/${reelId}/skip`, { method: 'POST' });
        showToast('Reel ignorato', 'info');
        loadReels();
        fetchStatus();
    } catch (err) {
        showToast('Errore operazione', 'error');
    }
}

function toggleTikTokFields() {
    const mode = document.getElementById('setting-tiktok-mode').value;
    const zernioFields = document.getElementById('fields-zernio');
    const webFields = document.getElementById('fields-web-session');
    const apiFields = document.getElementById('fields-official-api');
    const helper = document.getElementById('mode-helper-text');

    if (mode === 'zernio') {
        if (zernioFields) zernioFields.classList.remove('hidden');
        if (webFields) webFields.classList.add('hidden');
        if (apiFields) apiFields.classList.add('hidden');
        if (helper) helper.innerText = 'Zernio gestisce la pubblicazione TikTok ufficiale in cloud senza consumare RAM o spazio disco su Render.';
    } else if (mode === 'web_session') {
        if (zernioFields) zernioFields.classList.add('hidden');
        if (webFields) webFields.classList.remove('hidden');
        if (apiFields) apiFields.classList.add('hidden');
        if (helper) helper.innerText = 'La modalità con cookie sessionid ti permette di pubblicare direttamente senza registrare app da sviluppatore.';
    } else if (mode === 'official_api') {
        if (zernioFields) zernioFields.classList.add('hidden');
        if (webFields) webFields.classList.add('hidden');
        if (apiFields) apiFields.classList.remove('hidden');
        if (helper) helper.innerText = 'Richiede Client Key, Client Secret e Access Token approvato da developers.tiktok.com.';
    } else {
        if (zernioFields) zernioFields.classList.add('hidden');
        if (webFields) webFields.classList.add('hidden');
        if (apiFields) apiFields.classList.add('hidden');
        if (helper) helper.innerText = 'Modalità Test / Simulazione: scarica i reel e simula la pubblicazione senza inviare nulla ai server di TikTok.';
    }
}

async function testZernioConnection() {
    const keyInput = document.getElementById('setting-zernio-api-key');
    const apiKey = keyInput ? keyInput.value.trim() : '';

    if (!apiKey) {
        showToast('Inserisci prima la tua Zernio API Key', 'warning');
        return;
    }

    showToast('Verifica account Zernio in corso...', 'info');

    try {
        const res = await fetch('/api/zernio/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: apiKey })
        });
        const data = await res.json();

        if (data.success) {
            const select = document.getElementById('setting-zernio-account-id');
            if (select) {
                select.innerHTML = '';
                const tiktokAccounts = data.accounts.filter(a => a.platform === 'tiktok');
                if (tiktokAccounts.length === 0) {
                    select.innerHTML = '<option value="">Nessun account TikTok trovato su Zernio</option>';
                    showToast('Chiave valida, ma nessun account TikTok collegato su Zernio!', 'warning');
                } else {
                    tiktokAccounts.forEach(acc => {
                        const opt = document.createElement('option');
                        opt.value = acc._id || acc.id;
                        opt.textContent = `TikTok: @${acc.username || acc.name || acc._id}`;
                        select.appendChild(opt);
                    });
                    showToast(`Trovati ${tiktokAccounts.length} account TikTok collegati!`, 'success');
                }
            }
        } else {
            showToast(`Errore Zernio: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast(`Errore connessione Zernio: ${err.message}`, 'error');
    }
}

// ----------------------------------------------------
// SETTINGS
// ----------------------------------------------------
async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        const data = await res.json();
        if (data.success) {
            const s = data.settings;
            document.getElementById('setting-ig-user').value = s.instagram_username || '';
            document.getElementById('setting-ig-id').value = s.instagram_id || '';
            document.getElementById('setting-ig-token').value = s.instagram_token || '';

            document.getElementById('setting-tiktok-mode').value = s.tiktok_mode || 'zernio';
            const zKeyElem = document.getElementById('setting-zernio-api-key');
            if (zKeyElem) zKeyElem.value = s.zernio_api_key || '';

            const zAccElem = document.getElementById('setting-zernio-account-id');
            if (zAccElem && s.zernio_tiktok_account_id) {
                zAccElem.innerHTML = `<option value="${s.zernio_tiktok_account_id}">Account Salvato (${s.zernio_tiktok_account_id})</option>`;
            }

            document.getElementById('setting-tiktok-session-id').value = s.tiktok_session_id || '';
            document.getElementById('setting-tiktok-token').value = s.tiktok_access_token || '';
            document.getElementById('setting-tiktok-key').value = s.tiktok_client_key || '';
            document.getElementById('setting-tiktok-secret').value = s.tiktok_client_secret || '';
            document.getElementById('setting-tiktok-privacy').value = s.tiktok_privacy_level || 'PUBLIC_TO_EVERYONE';
            document.getElementById('setting-tiktok-post-type').value = s.tiktok_post_type || 'direct';

            document.getElementById('setting-check-interval').value = s.check_interval_minutes || '10';
            document.getElementById('setting-auto-publish-check').checked = s.auto_publish === 'true';
            document.getElementById('setting-clean-mentions').checked = s.clean_ig_mentions === 'true';

            document.getElementById('setting-caption-prefix').value = s.caption_prefix || '';
            document.getElementById('setting-caption-suffix').value = s.caption_suffix || '';
            document.getElementById('setting-include-original-caption').checked = s.include_original_caption !== 'false';

            toggleTikTokFields();
        }
    } catch (err) {
        console.error('Errore loadSettings:', err);
    }
}

async function saveAllSettings() {
    const zKeyElem = document.getElementById('setting-zernio-api-key');
    const zAccElem = document.getElementById('setting-zernio-account-id');

    const payload = {
        instagram_id: document.getElementById('setting-ig-id').value.trim(),
        instagram_token: document.getElementById('setting-ig-token').value.trim(),
        tiktok_mode: document.getElementById('setting-tiktok-mode').value,
        zernio_api_key: zKeyElem ? zKeyElem.value.trim() : '',
        zernio_tiktok_account_id: zAccElem ? zAccElem.value : '',
        tiktok_session_id: document.getElementById('setting-tiktok-session-id').value.trim(),
        tiktok_access_token: document.getElementById('setting-tiktok-token').value.trim(),
        tiktok_client_key: document.getElementById('setting-tiktok-key').value.trim(),
        tiktok_client_secret: document.getElementById('setting-tiktok-secret').value.trim(),
        tiktok_privacy_level: document.getElementById('setting-tiktok-privacy').value,
        tiktok_post_type: document.getElementById('setting-tiktok-post-type').value,
        check_interval_minutes: document.getElementById('setting-check-interval').value,
        auto_publish: document.getElementById('setting-auto-publish-check').checked ? 'true' : 'false',
        clean_ig_mentions: document.getElementById('setting-clean-mentions').checked ? 'true' : 'false',
        caption_prefix: document.getElementById('setting-caption-prefix').value.trim(),
        caption_suffix: document.getElementById('setting-caption-suffix').value.trim(),
        include_original_caption: document.getElementById('setting-include-original-caption').checked ? 'true' : 'false'
    };

    try {
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
            showToast('Tutte le impostazioni sono state salvate!', 'success');
            fetchStatus();
        } else {
            showToast('Errore salvataggio impostazioni', 'error');
        }
    } catch (err) {
        showToast('Errore di connessione', 'error');
    }
}

async function saveSetting(key, value) {
    try {
        await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [key]: value })
        });
    } catch (err) {
        console.error('saveSetting error:', err);
    }
}

async function testInstagramConnection() {
    try {
        showToast('Verifica account Instagram...', 'info');
        const res = await fetch('/api/test/instagram');
        const data = await res.json();
        if (data.success) {
            showToast(`Instagram Connesso! Utente: @${data.username} (${data.account_type})`, 'success');
        } else {
            showToast(`Errore Instagram: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast('Errore test connessione', 'error');
    }
}

async function refreshInstagramToken() {
    try {
        showToast('Rinnovo token Instagram...', 'info');
        const res = await fetch('/api/instagram/refresh', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            const days = Math.round(data.expires_in / 86400);
            showToast(`Token Instagram rinnovato con successo per altri ${days} giorni!`, 'success');
            loadSettings();
        } else {
            showToast(`Errore rinnovo token: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast('Errore rinnovo', 'error');
    }
}

async function testTikTokConnection() {
    try {
        showToast('Verifica account TikTok...', 'info');
        const res = await fetch('/api/test/tiktok');
        const data = await res.json();
        if (data.success) {
            showToast(`TikTok OK! Account: ${data.creator_nickname}`, 'success');
        } else {
            showToast(`Errore TikTok: ${data.error}`, 'error');
        }
    } catch (err) {
        showToast('Errore test TikTok', 'error');
    }
}

// ----------------------------------------------------
// LOGS
// ----------------------------------------------------
async function loadLogs() {
    const level = document.getElementById('log-filter-level')?.value || 'ALL';
    try {
        const res = await fetch(`/api/logs?level=${level}&limit=120`);
        const data = await res.json();
        if (data.success) {
            renderLogs(data.logs);
        }
    } catch (err) {
        console.error('Errore loadLogs:', err);
    }
}

function renderLogs(logs) {
    const container = document.getElementById('logs-container');
    if (!logs || logs.length === 0) {
        container.innerHTML = '<p class="text-slate-600">Nessun log registrato.</p>';
        return;
    }

    container.innerHTML = logs.map(l => {
        const cls = `log-${l.level.toLowerCase()}`;
        return `
            <div class="flex items-start gap-2 border-b border-slate-900/60 pb-1">
                <span class="text-slate-500 select-none">${l.timestamp}</span>
                <span class="font-bold uppercase px-1.5 py-0.2 rounded text-[10px] bg-slate-900 ${cls}">${l.level}</span>
                <div class="flex-1">
                    <span class="text-slate-200">${escapeHtml(l.message)}</span>
                    ${l.details ? `<pre class="text-[10px] text-slate-500 mt-0.5 whitespace-pre-wrap">${escapeHtml(l.details)}</pre>` : ''}
                </div>
            </div>
        `;
    }).join('');
}

async function clearAllLogs() {
    if (!confirm('Vuoi svuotare tutti i log?')) return;
    try {
        await fetch('/api/logs/clear', { method: 'POST' });
        showToast('Log svuotati', 'info');
        loadLogs();
    } catch (err) {
        showToast('Errore cancellazione log', 'error');
    }
}

// ----------------------------------------------------
// TOAST NOTIFICATIONS
// ----------------------------------------------------
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');

    const typeStyles = {
        'success': 'bg-emerald-950 border-emerald-500/50 text-emerald-200',
        'error': 'bg-rose-950 border-rose-500/50 text-rose-200',
        'info': 'bg-slate-900 border-slate-700 text-slate-200'
    };

    const icons = {
        'success': 'check-circle-2',
        'error': 'alert-circle',
        'info': 'info'
    };

    const style = typeStyles[type] || typeStyles['info'];
    const icon = icons[type] || 'info';

    toast.className = `toast max-w-sm pointer-events-auto flex items-center gap-2.5 px-4 py-3 rounded-xl border text-xs font-medium shadow-xl backdrop-blur ${style}`;
    toast.innerHTML = `
        <i data-lucide="${icon}" class="w-4 h-4 flex-shrink-0"></i>
        <span>${escapeHtml(message)}</span>
    `;

    container.appendChild(toast);
    lucide.createIcons();

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4500);
}

// ----------------------------------------------------
// UTILS
// ----------------------------------------------------
function formatDate(isoStr) {
    if (!isoStr) return '';
    try {
        const d = new Date(isoStr);
        return d.toLocaleDateString('it-IT', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch {
        return isoStr;
    }
}

function formatTime(isoStr) {
    if (!isoStr) return '';
    try {
        const parts = isoStr.split(' ');
        return parts.length > 1 ? parts[1].substring(0, 5) : isoStr;
    } catch {
        return isoStr;
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

