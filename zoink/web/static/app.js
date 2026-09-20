/* ZoinK — Modern Music Player & Downloader Client */
(function () {
    'use strict';

    // Core Audio & Elements
    const audio = document.getElementById('audioEl');
    const content = document.getElementById('content');
    const appEl = document.getElementById('app');
    const playerBar = document.getElementById('playerBar');
    const searchInput = document.getElementById('searchInput');
    const searchKbd = document.getElementById('searchKbd');
    const clearSearchBtn = document.getElementById('clearSearchBtn');

    // Player Elements
    const playerArt = document.getElementById('playerArt');
    const playerTitle = document.getElementById('playerTitle');
    const playerArtist = document.getElementById('playerArtist');
    const btnPlay = document.getElementById('btnPlay');
    const btnPrev = document.getElementById('btnPrev');
    const btnNext = document.getElementById('btnNext');
    const btnShuffle = document.getElementById('btnShuffle');
    const btnRepeat = document.getElementById('btnRepeat');
    const btnMute = document.getElementById('btnMute');
    const btnQueue = document.getElementById('btnQueue');
    const btnLyrics = document.getElementById('btnLyrics');
    const btnDownloadCurrent = document.getElementById('btnDownloadCurrent');
    const seekBar = document.getElementById('seekBar');
    const seekProgressFill = document.getElementById('seekProgressFill');
    const volumeBar = document.getElementById('volumeBar');
    const volProgressFill = document.getElementById('volProgressFill');
    const currentTimeEl = document.getElementById('currentTime');
    const durationEl = document.getElementById('duration');

    // Modals & Sheets
    const cmdPalette = document.getElementById('cmdPalette');
    const cmdInput = document.getElementById('cmdInput');
    const cmdList = document.getElementById('cmdList');
    const closeCmdBtn = document.getElementById('closeCmdBtn');

    const downloadsModal = document.getElementById('downloadsModal');
    const downloadQueueList = document.getElementById('downloadQueueList');
    const closeDownloadsModal = document.getElementById('closeDownloadsModal');
    const btnCancelAllDownloads = document.getElementById('btnCancelAllDownloads');

    const lyricsPanel = document.getElementById('lyricsPanel');
    const lyricsContent = document.getElementById('lyricsContent');
    const lyricsTrackTitle = document.getElementById('lyricsTrackTitle');
    const lyricsTrackArtist = document.getElementById('lyricsTrackArtist');
    const closeLyrics = document.getElementById('closeLyrics');

    const queuePanel = document.getElementById('queuePanel');
    const queueList = document.getElementById('queueList');
    const queueCount = document.getElementById('queueCount');
    const btnClearQueue = document.getElementById('btnClearQueue');
    const closeQueue = document.getElementById('closeQueue');

    const searchOverlay = document.getElementById('searchResultsOverlay');
    const searchOnlineList = document.getElementById('searchOnlineList');
    const searchQueryLabel = document.getElementById('searchQueryLabel');
    const closeSearchOverlay = document.getElementById('closeSearchOverlay');

    // Multi-Selection
    const selectionBar = document.getElementById('selectionBar');
    const selectedCountEl = document.getElementById('selectedCount');
    const btnPlaySelected = document.getElementById('btnPlaySelected');
    const btnQueueSelected = document.getElementById('btnQueueSelected');
    const btnZipSelected = document.getElementById('btnZipSelected');
    const btnCancelSelected = document.getElementById('btnCancelSelected');

    // Header & Sidebar Controls
    const btnDownloadsTop = document.getElementById('btnDownloadsTop');
    const btnToggleSelect = document.getElementById('btnToggleSelect');
    const btnLayoutToggle = document.getElementById('btnLayoutToggle');
    const layoutIcon = document.getElementById('layoutIcon');
    const topDlBadge = document.getElementById('topDlBadge');
    const sidebarDlBadge = document.getElementById('sidebarDlBadge');
    const btnRescanLib = document.getElementById('btnRescanLib');
    const btnZipAll = document.getElementById('btnZipAll');
    const btnOpenCmdSidebar = document.getElementById('btnOpenCmdSidebar');
    const toastContainer = document.getElementById('toastContainer');

    // State
    let queue = [];
    let queueIndex = -1;
    let savedShuffle = localStorage.getItem('zoink_shuffle') === 'true';
    let savedRepeat = localStorage.getItem('zoink_repeat') === 'true';
    let shuffle = savedShuffle;
    let repeat = savedRepeat;
    let currentView = 'recent';
    let searchTimeout = null;
    let isSelectingMode = false;
    let selectedTrackIds = new Set();
    let currentTrack = null;
    let dlPollInterval = null;
    let currentLayout = localStorage.getItem('zoink_layout') || 'auto';

    const _abortControllers = {};
    function abortableFetch(key, url, opts = {}) {
        if (_abortControllers[key]) _abortControllers[key].abort();
        const ctrl = new AbortController();
        _abortControllers[key] = ctrl;
        return fetch(url, { ...opts, signal: ctrl.signal });
    }

    // Apply layout
    setLayout(currentLayout);

    // -- Slash Commands Registry --
    const SLASH_COMMANDS = [
        { cmd: '/search', desc: 'Search online songs or direct YouTube URL', action: (arg) => arg ? searchOnline(arg) : searchInput.focus() },
        { cmd: '/recent', desc: 'Switch to Recently Added', action: () => switchView('recent') },
        { cmd: '/songs', desc: 'Browse all songs in library', action: () => switchView('songs') },
        { cmd: '/artists', desc: 'Browse artists in library', action: () => switchView('artists') },
        { cmd: '/albums', desc: 'Browse albums in library', action: () => switchView('albums') },
        { cmd: '/downloads', desc: 'Open active downloads manager', action: () => openDownloadsModal() },
        { cmd: '/play', desc: 'Play / Resume current track', action: () => { if (audio.paused) togglePlay(); } },
        { cmd: '/pause', desc: 'Pause playback', action: () => { if (!audio.paused) togglePlay(); } },
        { cmd: '/next', desc: 'Skip to next track in queue', action: () => nextTrack() },
        { cmd: '/prev', desc: 'Skip to previous track', action: () => prevTrack() },
        { cmd: '/shuffle', desc: 'Toggle shuffle mode', action: () => toggleShuffle() },
        { cmd: '/repeat', desc: 'Toggle repeat mode', action: () => toggleRepeat() },
        { cmd: '/mute', desc: 'Toggle audio mute', action: () => toggleMute() },
        { cmd: '/queue', desc: 'Open playback queue', action: () => openQueueModal() },
        { cmd: '/lyrics', desc: 'View lyrics for now-playing track', action: () => openLyricsModal() },
        { cmd: '/desktop', desc: 'Force Desktop mode layout', action: () => setLayout('desktop') },
        { cmd: '/mobile', desc: 'Force Mobile mode layout', action: () => setLayout('mobile') },
        { cmd: '/auto', desc: 'Auto-responsive layout mode', action: () => setLayout('auto') },
        { cmd: '/download-all', desc: 'Download entire library as ZIP', action: () => downloadAllZip() },
        { cmd: '/rescan', desc: 'Rescan storage directory for new music', action: () => rescanLibrary() },
        { cmd: '/help', desc: 'Show all slash commands', action: () => openCommandPalette() }
    ];

    // -- Layout Switching --
    function setLayout(mode) {
        currentLayout = mode;
        localStorage.setItem('zoink_layout', mode);
        appEl.setAttribute('data-layout', mode);
        if (mode === 'desktop') {
            layoutIcon.textContent = '📱';
            layoutIcon.parentElement.title = 'Switch to Mobile View';
            showToast('Desktop layout enabled');
        } else if (mode === 'mobile') {
            layoutIcon.textContent = '💻';
            layoutIcon.parentElement.title = 'Switch to Auto/Desktop View';
            showToast('Mobile layout enabled');
        } else {
            layoutIcon.textContent = '🖥️';
            layoutIcon.parentElement.title = 'Toggle Layout Mode';
        }
    }

    btnLayoutToggle.addEventListener('click', () => {
        if (currentLayout === 'auto') setLayout('desktop');
        else if (currentLayout === 'desktop') setLayout('mobile');
        else setLayout('auto');
    });

    // -- Navigation Tabs & Sidebar --
    function switchView(viewName) {
        currentView = viewName;
        document.querySelectorAll('.tab-btn, .nav-item').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.view === viewName);
        });
        loadView(viewName);
    }

    document.querySelectorAll('.tab-btn, .nav-item').forEach(btn => {
        btn.addEventListener('click', () => switchView(btn.dataset.view));
    });

    // -- Global Search & Slash Commands --
    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        const val = searchInput.value.trim();
        clearSearchBtn.classList.toggle('hidden', val.length === 0);

        if (val.startsWith('/')) {
            openCommandPalette(val);
            return;
        }

        if (val.length < 2) {
            searchOverlay.classList.add('hidden');
            return;
        }

        searchTimeout = setTimeout(() => searchOnline(val), 350);
    });

    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            clearSearch();
        } else if (e.key === 'Enter') {
            const val = searchInput.value.trim();
            if (val.startsWith('/')) {
                executeSlashCommand(val);
                clearSearch();
            } else if (val.length >= 2) {
                searchOnline(val);
            }
        }
    });

    clearSearchBtn.addEventListener('click', clearSearch);

    function clearSearch() {
        searchInput.value = '';
        clearSearchBtn.classList.add('hidden');
        searchOverlay.classList.add('hidden');
    }

    // Keyboard Shortcuts
    function closeAllModals() {
        cmdPalette.classList.add('hidden');
        downloadsModal.classList.add('hidden');
        lyricsPanel.classList.add('hidden');
        queuePanel.classList.add('hidden');
        searchOverlay.classList.add('hidden');
        const contextMenu = document.getElementById('context-menu');
        if (contextMenu) contextMenu.classList.add('hidden');
    }

    function openShortcutsModal() {
        openCommandPalette(); // Fallback for now since there's no dedicated modal in instructions
    }

    document.addEventListener('keydown', (e) => {
        // Don't trigger if user is typing in an input
        const tag = (e.target.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || e.target.isContentEditable) {
            if (e.key === 'Escape') e.target.blur();
            return;
        }
        
        switch (e.key) {
            case ' ':
                e.preventDefault();
                togglePlay();
                break;
            case 'ArrowRight':
                if (e.shiftKey) { nextTrack(); }
                else if (audio && audio.duration) { audio.currentTime = Math.min(audio.duration, audio.currentTime + 5); }
                break;
            case 'ArrowLeft':
                if (e.shiftKey) { prevTrack(); }
                else if (audio) { audio.currentTime = Math.max(0, audio.currentTime - 5); }
                break;
            case 'ArrowUp':
                e.preventDefault();
                if (audio) { audio.volume = Math.min(1, audio.volume + 0.05); updateVolumeUI(); localStorage.setItem('zoink_volume', audio.volume); }
                break;
            case 'ArrowDown':
                e.preventDefault();
                if (audio) { audio.volume = Math.max(0, audio.volume - 0.05); updateVolumeUI(); localStorage.setItem('zoink_volume', audio.volume); }
                break;
            case 'm': case 'M':
                toggleMute();
                break;
            case 's': case 'S':
                toggleShuffle();
                break;
            case 'r': case 'R':
                toggleRepeat();
                break;
            case 'l': case 'L':
                openLyricsModal();
                break;
            case '/':
                e.preventDefault();
                if (searchInput) searchInput.focus();
                break;
            case '?':
                openShortcutsModal();
                break;
            case 'Escape':
                closeAllModals();
                break;
        }
    });

    // -- Command Palette System --
    function openCommandPalette(filter = '') {
        cmdPalette.classList.remove('hidden');
        cmdInput.value = filter;
        cmdInput.focus();
        renderCommandList(filter);
    }

    function closeCommandPalette() {
        cmdPalette.classList.add('hidden');
        cmdInput.value = '';
    }

    cmdInput.addEventListener('input', () => renderCommandList(cmdInput.value));
    closeCmdBtn.addEventListener('click', closeCommandPalette);
    cmdPalette.addEventListener('click', (e) => {
        if (e.target === cmdPalette) closeCommandPalette();
    });

    cmdInput.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeCommandPalette();
        } else if (e.key === 'Enter') {
            const first = cmdList.querySelector('.cmd-item');
            if (first) first.click();
            else {
                executeSlashCommand(cmdInput.value.trim());
                closeCommandPalette();
            }
        }
    });

    btnOpenCmdSidebar.addEventListener('click', () => openCommandPalette('/'));

    function renderCommandList(query) {
        cmdList.innerHTML = '';
        const q = query.toLowerCase().trim();
        const filtered = SLASH_COMMANDS.filter(c => c.cmd.includes(q) || c.desc.toLowerCase().includes(q));

        if (filtered.length === 0) {
            cmdList.innerHTML = '<div class="empty-state-small" style="padding:14px;color:var(--muted)">No matching commands</div>';
            return;
        }

        filtered.forEach(item => {
            const div = document.createElement('div');
            div.className = 'cmd-item';
            div.innerHTML = `
                <div>
                    <strong>${esc(item.cmd)}</strong>
                    <span style="margin-left:8px;font-size:0.78rem;color:var(--muted)">${esc(item.desc)}</span>
                </div>
                <kbd>Enter</kbd>
            `;
            div.addEventListener('click', () => {
                closeCommandPalette();
                item.action();
            });
            cmdList.appendChild(div);
        });
    }

    function executeSlashCommand(raw) {
        const parts = raw.split(' ');
        const name = parts[0].toLowerCase();
        const arg = parts.slice(1).join(' ');
        const found = SLASH_COMMANDS.find(c => c.cmd === name);
        if (found) {
            found.action(arg);
        } else {
            showToast('Unknown command: ' + name, 'error');
        }
    }

    // -- Audio Playback Core --
    function playTrack(track, addToQueue = true) {
        if (!track) return;
        currentTrack = track;

        if (addToQueue) {
            const idx = queue.findIndex(t => t.id === track.id);
            if (idx >= 0) {
                queueIndex = idx;
            } else {
                queue.push(track);
                queueIndex = queue.length - 1;
            }
        }

        const streamUrl = '/api/stream/' + encodeURIComponent(track.id);
        audio.src = streamUrl;
        audio.play().then(() => {
            btnPlay.innerHTML = '⏸';
            updateMediaSession(track);
            // Record play history
            fetch('/api/history/play', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ track_id: track.id })
            }).catch(() => {});
        }).catch(err => {
            console.error('Audio play error:', err);
        });

        playerBar.classList.remove('hidden');
        playerTitle.textContent = track.title || 'Unknown Title';
        playerArtist.textContent = track.artist || 'Unknown Artist';

        // Album Art
        const artSrc = track.artwork_url || ('/api/artwork/' + encodeURIComponent(track.id));
        playerArt.src = artSrc;
        playerArt.style.opacity = '1';
        playerArt.onerror = () => { playerArt.style.opacity = '0'; };

        // Highlight active track in lists
        document.querySelectorAll('.track-row').forEach(row => {
            row.classList.toggle('playing', row.dataset.id === track.id);
        });

        renderQueue();
    }

    function togglePlay() {
        if (!audio.src) {
            if (queue.length > 0) {
                playTrack(queue[0]);
            }
            return;
        }
        if (audio.paused) {
            audio.play();
            btnPlay.innerHTML = '⏸';
        } else {
            audio.pause();
            btnPlay.innerHTML = '▶';
        }
    }

    function nextTrack() {
        if (queue.length === 0) return;
        if (shuffle) {
            queueIndex = Math.floor(Math.random() * queue.length);
        } else {
            queueIndex = (queueIndex + 1) % queue.length;
        }
        playTrack(queue[queueIndex], false);
    }

    function prevTrack() {
        if (queue.length === 0) return;
        if (audio.currentTime > 3) {
            audio.currentTime = 0;
            return;
        }
        queueIndex = (queueIndex - 1 + queue.length) % queue.length;
        playTrack(queue[queueIndex], false);
    }

    function toggleShuffle() {
        shuffle = !shuffle;
        localStorage.setItem('zoink_shuffle', shuffle);
        btnShuffle.classList.toggle('active', shuffle);
        showToast(shuffle ? 'Shuffle enabled' : 'Shuffle disabled');
    }

    function toggleRepeat() {
        repeat = !repeat;
        localStorage.setItem('zoink_repeat', repeat);
        btnRepeat.classList.toggle('active', repeat);
        showToast(repeat ? 'Repeat track enabled' : 'Repeat disabled');
    }

    function toggleMute() {
        audio.muted = !audio.muted;
        btnMute.classList.toggle('active', audio.muted);
        btnMute.textContent = audio.muted ? '🔇' : '🔊';
    }

    btnPlay.addEventListener('click', togglePlay);
    btnNext.addEventListener('click', nextTrack);
    btnPrev.addEventListener('click', prevTrack);
    btnShuffle.addEventListener('click', toggleShuffle);
    btnRepeat.addEventListener('click', toggleRepeat);
    btnMute.addEventListener('click', toggleMute);

    // Seekbar Updates
    function updateScrubberFill(bar, value) {
        const pct = value + '%';
        bar.style.background = `linear-gradient(to right, var(--accent) ${pct}, rgba(255,255,255,0.15) ${pct})`;
    }

    seekBar.addEventListener('input', () => {
        if (audio.duration) {
            const seekTo = (seekBar.value / 100) * audio.duration;
            audio.currentTime = seekTo;
            seekProgressFill.style.width = seekBar.value + '%';
            updateScrubberFill(seekBar, seekBar.value);
        }
    });

    audio.addEventListener('timeupdate', () => {
        if (audio.duration) {
            const pct = (audio.currentTime / audio.duration) * 100;
            seekBar.value = pct;
            seekProgressFill.style.width = pct + '%';
            updateScrubberFill(seekBar, pct);
            currentTimeEl.textContent = formatTime(audio.currentTime);
            durationEl.textContent = formatTime(audio.duration);
        }
    });

    audio.addEventListener('ended', () => {
        if (repeat) {
            audio.currentTime = 0;
            audio.play();
        } else {
            nextTrack();
        }
    });

    // Volume Slider
    volumeBar.addEventListener('input', () => {
        audio.volume = volumeBar.value / 100;
        localStorage.setItem('zoink_volume', audio.volume);
        volProgressFill.style.width = volumeBar.value + '%';
        if (audio.muted) toggleMute();
    });
    
    function updateVolumeUI() {
        if (audio) {
            volumeBar.value = audio.volume * 100;
            volProgressFill.style.width = volumeBar.value + '%';
        }
    }

    let savedVolume = localStorage.getItem('zoink_volume');
    if (savedVolume !== null) {
        audio.volume = parseFloat(savedVolume);
    } else {
        audio.volume = 0.85;
    }
    updateVolumeUI();

    // MediaSession API Integration
    function updateMediaSession(t) {
        if ('mediaSession' in navigator) {
            const artUrl = t.artwork_url || (window.location.origin + '/api/artwork/' + encodeURIComponent(t.id));
            navigator.mediaSession.metadata = new MediaMetadata({
                title: t.title || 'Unknown Title',
                artist: t.artist || 'Unknown Artist',
                album: t.album || '',
                artwork: [{ src: artUrl, sizes: '512x512', type: 'image/jpeg' }]
            });

            navigator.mediaSession.setActionHandler('play', () => togglePlay());
            navigator.mediaSession.setActionHandler('pause', () => togglePlay());
            navigator.mediaSession.setActionHandler('previoustrack', () => prevTrack());
            navigator.mediaSession.setActionHandler('nexttrack', () => nextTrack());
            navigator.mediaSession.setActionHandler('seekto', (details) => {
                if (details.seekTime && audio.duration) audio.currentTime = details.seekTime;
            });
        }
    }

    // Direct Download Current Track
    btnDownloadCurrent.addEventListener('click', () => {
        if (currentTrack) {
            downloadLocalTrack(currentTrack);
        }
    });

    function downloadLocalTrack(t) {
        const a = document.createElement('a');
        a.href = '/api/file/' + encodeURIComponent(t.id);
        a.download = '';
        a.click();
        showToast(`Downloading "${t.title}"`);
    }

    // -- Queue Modal --
    btnQueue.addEventListener('click', openQueueModal);
    closeQueue.addEventListener('click', () => queuePanel.classList.add('hidden'));
    queuePanel.addEventListener('click', (e) => { if (e.target === queuePanel) queuePanel.classList.add('hidden'); });

    btnClearQueue.addEventListener('click', () => {
        queue = [];
        queueIndex = -1;
        renderQueue();
        showToast('Queue cleared');
    });

    function openQueueModal() {
        queuePanel.classList.remove('hidden');
        renderQueue();
    }

    function renderQueue() {
        queueCount.textContent = queue.length;
        queueList.innerHTML = '';
        if (queue.length === 0) {
            queueList.innerHTML = '<div class="empty-state-small" style="padding:24px;text-align:center;color:var(--muted)">Queue is empty</div>';
            return;
        }

        queue.forEach((t, i) => {
            const row = document.createElement('div');
            row.className = 'track-row' + (i === queueIndex ? ' playing' : '');
            row.innerHTML = `
                <div style="font-size:0.75rem;color:var(--muted);width:20px">${i + 1}</div>
                <div class="track-details">
                    <div class="track-name">${esc(t.title)}</div>
                    <div class="track-sub">${esc(t.artist || '')}</div>
                </div>
                <button class="icon-action-btn remove-btn" title="Remove from queue">&times;</button>
            `;
            row.addEventListener('click', (e) => {
                if (!e.target.classList.contains('remove-btn')) {
                    queueIndex = i;
                    playTrack(t, false);
                }
            });
            row.querySelector('.remove-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                queue.splice(i, 1);
                if (queueIndex === i) {
                    nextTrack();
                } else if (queueIndex > i) {
                    queueIndex--;
                }
                renderQueue();
            });
            queueList.appendChild(row);
        });
    }

    // -- Lyrics Modal --
    btnLyrics.addEventListener('click', openLyricsModal);
    closeLyrics.addEventListener('click', () => lyricsPanel.classList.add('hidden'));
    lyricsPanel.addEventListener('click', (e) => { if (e.target === lyricsPanel) lyricsPanel.classList.add('hidden'); });

    async function openLyricsModal() {
        lyricsPanel.classList.remove('hidden');
        if (!currentTrack) {
            lyricsContent.textContent = 'No track currently playing.';
            return;
        }
        lyricsTrackTitle.textContent = currentTrack.title || 'Lyrics';
        lyricsTrackArtist.textContent = currentTrack.artist || '';
        lyricsContent.innerHTML = '<div class="loading-spinner"><div class="spinner"></div></div>';

        try {
            const res = await fetch('/api/lyrics/' + encodeURIComponent(currentTrack.id));
            const data = await res.json();
            lyricsContent.textContent = (data.lyrics && data.lyrics.trim()) ? data.lyrics.trim() : 'No lyrics found for this song.';
        } catch {
            lyricsContent.textContent = 'Failed to load lyrics.';
        }
    }

    // -- Online Search View --
    closeSearchOverlay.addEventListener('click', () => searchOverlay.classList.add('hidden'));

    async function searchOnline(query) {
        searchOverlay.classList.remove('hidden');
        searchQueryLabel.textContent = `"${query}"`;
        searchOnlineList.innerHTML = '<div class="loading-spinner"><div class="spinner"></div></div>';

        try {
            const res = await abortableFetch('search', '/api/search?q=' + encodeURIComponent(query) + '&limit=15');
            const results = await res.json();
            searchOnlineList.innerHTML = '';

            if (!results || results.length === 0) {
                searchOnlineList.innerHTML = '<div class="empty-state" style="padding:32px">No results found online.</div>';
                return;
            }

            results.forEach(t => {
                const row = document.createElement('div');
                row.className = 'track-row';
                const art = t.artwork_url || '';
                row.innerHTML = `
                    <img class="track-img" src="${esc(art)}" alt="" onerror="this.style.opacity='0'">
                    <div class="track-details">
                        <div class="track-name">${esc(t.title)}</div>
                        <div class="track-sub">${esc(t.artist || 'YouTube')} &middot; ${t.duration_str || ''}</div>
                    </div>
                    <button class="icon-action-btn dl-online-btn" title="Download song">⬇️</button>
                `;
                row.addEventListener('click', (e) => {
                    if (!e.target.classList.contains('dl-online-btn')) {
                        // Play preview
                        playTrack(t);
                    }
                });
                row.querySelector('.dl-online-btn').addEventListener('click', (e) => {
                    e.stopPropagation();
                    startDownload(t);
                });
                searchOnlineList.appendChild(row);
            });
        } catch (err) {
            if (err.name === 'AbortError') return;
            searchOnlineList.innerHTML = '<div class="empty-state" style="padding:32px;color:var(--danger)">Search failed. Please check network.</div>';
        }
    }

    // -- Download Engine & Queue Management --
    async function startDownload(track) {
        try {
            const res = await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(track)
            });
            const data = await res.json();
            if (res.ok) {
                showToast(`Queued: "${track.title}"`, 'success');
                startDownloadPolling();
                openDownloadsModal();
            } else {
                showToast(data.error || 'Failed to queue download', 'error');
            }
        } catch (err) {
            showToast('Download request failed', 'error');
        }
    }

    btnDownloadsTop.addEventListener('click', openDownloadsModal);
    closeDownloadsModal.addEventListener('click', () => downloadsModal.classList.add('hidden'));
    downloadsModal.addEventListener('click', (e) => { if (e.target === downloadsModal) downloadsModal.classList.add('hidden'); });

    function openDownloadsModal() {
        downloadsModal.classList.remove('hidden');
        pollDownloadQueue();
    }

    btnCancelAllDownloads.addEventListener('click', async () => {
        try {
            const res = await fetch('/api/download/queue');
            const jobs = await res.json();
            for (const j of jobs) {
                if (j.state === 'downloading' || j.state === 'pending') {
                    await fetch('/api/download/' + encodeURIComponent(j.id), { method: 'DELETE' });
                }
            }
            showToast('Cancelled all downloads');
            pollDownloadQueue();
        } catch {}
    });

    function startDownloadPolling() {
        if (!dlPollInterval) {
            pollDownloadQueue();
            dlPollInterval = setInterval(pollDownloadQueue, 1500);
        }
    }

    async function pollDownloadQueue() {
        try {
            const res = await fetch('/api/download/queue');
            if (!res.ok) return;
            const jobs = await res.json();
            renderDownloadsList(jobs);

            const activeCount = jobs.filter(j => j.state === 'downloading' || j.state === 'pending' || j.state === 'verifying').length;
            topDlBadge.classList.toggle('hidden', activeCount === 0);
            if (sidebarDlBadge) {
                sidebarDlBadge.textContent = activeCount;
                sidebarDlBadge.classList.toggle('hidden', activeCount === 0);
            }

            if (activeCount === 0 && dlPollInterval) {
                clearInterval(dlPollInterval);
                dlPollInterval = null;
            }
        } catch {}
    }

    function renderDownloadsList(jobs) {
        if (!jobs || jobs.length === 0) {
            downloadQueueList.innerHTML = '<div class="empty-state-small" style="padding:24px;text-align:center;color:var(--muted)">No active or recent downloads</div>';
            return;
        }

        downloadQueueList.innerHTML = '';
        jobs.slice().reverse().forEach(j => {
            const div = document.createElement('div');
            div.className = 'download-job-item';
            const pct = j.progress || 0;
            const stateColor = j.state === 'done' ? 'var(--success)' : (j.state === 'failed' ? 'var(--danger)' : 'var(--accent)');

            div.innerHTML = `
                <div class="job-top">
                    <div class="job-title">${esc(j.title || j.id)}</div>
                    <div style="font-size:0.75rem;font-weight:700;color:${stateColor}">${esc(j.state.toUpperCase())}</div>
                </div>
                <div class="job-progress-bg">
                    <div class="job-progress-bar" style="width:${pct}%;background:${stateColor}"></div>
                </div>
                <div class="job-meta-row">
                    <span>${esc(j.status_text || '')}</span>
                    <span>${pct.toFixed(0)}%</span>
                </div>
            `;
            downloadQueueList.appendChild(div);
        });
    }

    // -- Multi-Selection Actions --
    btnToggleSelect.addEventListener('click', toggleSelectionMode);
    btnCancelSelected.addEventListener('click', toggleSelectionMode);

    function toggleSelectionMode() {
        isSelectingMode = !isSelectingMode;
        content.classList.toggle('selecting-mode', isSelectingMode);
        selectionBar.classList.toggle('hidden', !isSelectingMode);
        btnToggleSelect.classList.toggle('active', isSelectingMode);
        if (!isSelectingMode) {
            selectedTrackIds.clear();
            updateSelectionBar();
            document.querySelectorAll('.track-select-box input').forEach(cb => cb.checked = false);
        }
    }

    function updateSelectionBar() {
        selectedCountEl.textContent = selectedTrackIds.size;
    }

    btnPlaySelected.addEventListener('click', () => {
        if (selectedTrackIds.size === 0) return;
        const tracks = Array.from(selectedTrackIds).map(id => getTrackFromDOM(id)).filter(Boolean);
        if (tracks.length > 0) {
            queue = tracks;
            queueIndex = 0;
            playTrack(queue[0], false);
            toggleSelectionMode();
            showToast(`Playing ${tracks.length} selected tracks`);
        }
    });

    btnQueueSelected.addEventListener('click', () => {
        if (selectedTrackIds.size === 0) return;
        const tracks = Array.from(selectedTrackIds).map(id => getTrackFromDOM(id)).filter(Boolean);
        queue.push(...tracks);
        renderQueue();
        toggleSelectionMode();
        showToast(`Added ${tracks.length} tracks to queue`);
    });

    btnZipSelected.addEventListener('click', () => {
        if (selectedTrackIds.size === 0) return;
        const ids = Array.from(selectedTrackIds).join(',');
        const a = document.createElement('a');
        a.href = `/api/download-bulk-zip?tracks=${encodeURIComponent(ids)}`;
        a.download = 'ZoinK_Selected.zip';
        a.click();
        showToast('Packaging selected tracks into ZIP...');
        toggleSelectionMode();
    });

    function getTrackFromDOM(id) {
        const row = document.querySelector(`.track-row[data-id="${id}"]`);
        if (row && row._trackData) return row._trackData;
        return null;
    }

    // -- Global Actions: Rescan & Full ZIP --
    btnRescanLib.addEventListener('click', rescanLibrary);
    btnZipAll.addEventListener('click', downloadAllZip);

    async function rescanLibrary() {
        showToast('Scanning storage for music...');
        try {
            const res = await fetch('/api/library/rescan', { method: 'POST' });
            const data = await res.json();
            showToast(`Indexed ${data.scanned} new songs (Total: ${data.total})`, 'success');
            loadView(currentView);
        } catch {
            showToast('Rescan failed', 'error');
        }
    }

    function downloadAllZip() {
        const a = document.createElement('a');
        a.href = '/api/download-all';
        a.download = 'ZoinK_Full_Library.zip';
        a.click();
        showToast('Packaging full library into ZIP...');
    }

    // -- View Loaders --
    async function loadView(view) {
        content.innerHTML = '<div class="loading-spinner"><div class="spinner"></div></div>';
        try {
            if (view === 'recent') await loadRecent();
            else if (view === 'songs') await loadSongs();
            else if (view === 'artists') await loadArtists();
            else if (view === 'albums') await loadAlbums();
            else if (view === 'downloads') await loadDownloadsView();
        } catch (e) {
            console.error('Error loading view:', e);
            content.innerHTML = '<div class="empty-state">Failed to load content.</div>';
        }
    }

    async function loadRecent() {
        const res = await fetch('/api/recent');
        const tracks = await res.json();
        if (!tracks || tracks.length === 0) {
            content.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">🎵</div>
                    <div>Your library is empty.</div>
                    <div style="margin-top:8px;font-size:0.8rem;color:var(--muted)">Use the search bar to search and download your favorite songs.</div>
                </div>`;
            return;
        }

        content.innerHTML = `
            <div class="section-title-bar">
                <span class="section-title">Recently Added</span>
                <div class="section-actions">
                    <button class="sel-btn play-sel" id="btnPlayAllRecent">▶ Play All</button>
                </div>
            </div>
            <div id="trackListContainer"></div>
        `;

        const container = content.querySelector('#trackListContainer');
        tracks.forEach(t => container.appendChild(createTrackRow(t)));

        content.querySelector('#btnPlayAllRecent').addEventListener('click', () => {
            queue = tracks;
            queueIndex = 0;
            playTrack(queue[0], false);
        });
    }

    async function loadSongs() {
        const res = await fetch('/api/library?limit=500');
        const tracks = await res.json();
        if (!tracks || tracks.length === 0) {
            content.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🎵</div><div>No songs found.</div></div>';
            return;
        }

        content.innerHTML = `
            <div class="section-title-bar">
                <span class="section-title">All Songs (${tracks.length})</span>
                <div class="section-actions">
                    <button class="sel-btn play-sel" id="btnPlayAllSongs">▶ Play All</button>
                </div>
            </div>
            <div id="trackListContainer"></div>
        `;

        const container = content.querySelector('#trackListContainer');
        tracks.forEach(t => container.appendChild(createTrackRow(t)));

        content.querySelector('#btnPlayAllSongs').addEventListener('click', () => {
            queue = tracks;
            queueIndex = 0;
            playTrack(queue[0], false);
        });
    }

    async function loadArtists() {
        const res = await fetch('/api/artists');
        const artists = await res.json();
        if (!artists || artists.length === 0) {
            content.innerHTML = '<div class="empty-state"><div class="empty-state-icon">👤</div><div>No artists found.</div></div>';
            return;
        }

        content.innerHTML = `
            <div class="section-title-bar">
                <span class="section-title">Artists (${artists.length})</span>
            </div>
            <div class="card-grid" id="artistGrid"></div>
        `;

        const grid = content.querySelector('#artistGrid');
        artists.forEach(a => {
            const card = document.createElement('div');
            card.className = 'media-card';
            card.innerHTML = `
                <div class="card-img-wrap">
                    <div style="font-size:2.2rem">👤</div>
                </div>
                <div class="card-title">${esc(a.artist)}</div>
                <div class="card-sub">${a.track_count} ${a.track_count === 1 ? 'track' : 'tracks'}</div>
            `;
            card.addEventListener('click', () => loadArtistDetail(a.artist));
            grid.appendChild(card);
        });
    }

    async function loadArtistDetail(artistName) {
        content.innerHTML = '<div class="loading-spinner"><div class="spinner"></div></div>';
        const res = await fetch('/api/artists/' + encodeURIComponent(artistName) + '/tracks');
        const tracks = await res.json();

        content.innerHTML = `
            <div class="section-title-bar">
                <span class="section-title">👤 ${esc(artistName)} (${tracks.length})</span>
                <div class="section-actions">
                    <button class="sel-btn" id="btnBackArtists">← Back</button>
                    <button class="sel-btn play-sel" id="btnPlayArtist">▶ Play All</button>
                </div>
            </div>
            <div id="artistTracksContainer"></div>
        `;

        content.querySelector('#btnBackArtists').addEventListener('click', () => switchView('artists'));
        content.querySelector('#btnPlayArtist').addEventListener('click', () => {
            queue = tracks;
            queueIndex = 0;
            playTrack(queue[0], false);
        });

        const container = content.querySelector('#artistTracksContainer');
        tracks.forEach(t => container.appendChild(createTrackRow(t)));
    }

    async function loadAlbums() {
        const res = await fetch('/api/albums');
        const albums = await res.json();
        if (!albums || albums.length === 0) {
            content.innerHTML = '<div class="empty-state"><div class="empty-state-icon">💿</div><div>No albums found.</div></div>';
            return;
        }

        content.innerHTML = `
            <div class="section-title-bar">
                <span class="section-title">Albums (${albums.length})</span>
            </div>
            <div class="card-grid" id="albumGrid"></div>
        `;

        const grid = content.querySelector('#albumGrid');
        albums.forEach(alb => {
            const card = document.createElement('div');
            card.className = 'media-card';
            card.innerHTML = `
                <div class="card-img-wrap">
                    <div style="font-size:2.2rem">💿</div>
                </div>
                <div class="card-title">${esc(alb.album)}</div>
                <div class="card-sub">${esc(alb.artist || 'Various Artists')} &middot; ${alb.track_count} tracks</div>
            `;
            card.addEventListener('click', () => loadAlbumDetail(alb.album, alb.artist));
            grid.appendChild(card);
        });
    }

    async function loadAlbumDetail(albumName, artistName) {
        content.innerHTML = '<div class="loading-spinner"><div class="spinner"></div></div>';
        const url = `/api/albums/${encodeURIComponent(albumName)}/tracks` + (artistName ? `?artist=${encodeURIComponent(artistName)}` : '');
        const res = await fetch(url);
        const tracks = await res.json();

        content.innerHTML = `
            <div class="section-title-bar">
                <span class="section-title">💿 ${esc(albumName)}</span>
                <div class="section-actions">
                    <button class="sel-btn" id="btnBackAlbums">← Back</button>
                    <button class="sel-btn play-sel" id="btnPlayAlbum">▶ Play</button>
                    <button class="sel-btn zip-sel" id="btnZipAlbum">📦 ZIP</button>
                </div>
            </div>
            <div id="albumTracksContainer"></div>
        `;

        content.querySelector('#btnBackAlbums').addEventListener('click', () => switchView('albums'));
        content.querySelector('#btnPlayAlbum').addEventListener('click', () => {
            queue = tracks;
            queueIndex = 0;
            playTrack(queue[0], false);
        });
        content.querySelector('#btnZipAlbum').addEventListener('click', () => {
            const a = document.createElement('a');
            a.href = `/api/albums/${encodeURIComponent(albumName)}/zip` + (artistName ? `?artist=${encodeURIComponent(artistName)}` : '');
            a.download = '';
            a.click();
            showToast(`Downloading album "${albumName}" as ZIP`);
        });

        const container = content.querySelector('#albumTracksContainer');
        tracks.forEach(t => container.appendChild(createTrackRow(t)));
    }

    async function loadDownloadsView() {
        content.innerHTML = `
            <div class="section-title-bar">
                <span class="section-title">📥 Downloads Queue</span>
                <div class="section-actions">
                    <button class="sel-btn" id="btnRefreshDl">🔄 Refresh</button>
                </div>
            </div>
            <div id="dlViewContainer" style="margin-top:10px"></div>
        `;
        content.querySelector('#btnRefreshDl').addEventListener('click', loadDownloadsView);
        const res = await fetch('/api/download/queue');
        const jobs = await res.json();
        const container = content.querySelector('#dlViewContainer');
        if (!jobs || jobs.length === 0) {
            container.innerHTML = '<div class="empty-state">No downloads in history.</div>';
            return;
        }
        jobs.slice().reverse().forEach(j => {
            const div = document.createElement('div');
            div.className = 'download-job-item';
            const pct = j.progress || 0;
            const stateColor = j.state === 'done' ? 'var(--success)' : (j.state === 'failed' ? 'var(--danger)' : 'var(--accent)');
            div.innerHTML = `
                <div class="job-top">
                    <div class="job-title">${esc(j.title || j.id)}</div>
                    <div style="font-size:0.75rem;font-weight:700;color:${stateColor}">${esc(j.state.toUpperCase())}</div>
                </div>
                <div class="job-progress-bg">
                    <div class="job-progress-bar" style="width:${pct}%;background:${stateColor}"></div>
                </div>
                <div class="job-meta-row">
                    <span>${esc(j.status_text || '')}</span>
                    <span>${pct.toFixed(0)}%</span>
                </div>
            `;
            container.appendChild(div);
        });
    }

    // -- DOM Track Row Builder --
    function createTrackRow(t) {
        const row = document.createElement('div');
        row.className = 'track-row' + (currentTrack && currentTrack.id === t.id ? ' playing' : '');
        row.dataset.id = t.id;
        row._trackData = t;

        const artSrc = t.artwork_url || ('/api/artwork/' + encodeURIComponent(t.id));
        row.innerHTML = `
            <div class="track-select-box">
                <input type="checkbox" data-id="${esc(t.id)}">
            </div>
            <img class="track-img" src="${esc(artSrc)}" alt="" onerror="this.style.opacity='0'">
            <div class="track-details">
                <div class="track-name">${esc(t.title)}</div>
                <div class="track-sub">${esc(t.artist || '')}${t.album ? ' &middot; ' + esc(t.album) : ''}</div>
            </div>
            <span class="track-dur">${t.duration_str || ''}</span>
            <div class="track-btns">
                <button class="icon-action-btn row-play" title="Play">▶</button>
                <button class="icon-action-btn row-dl" title="Download File">⬇️</button>
            </div>
        `;

        const cb = row.querySelector('input[type="checkbox"]');
        cb.addEventListener('change', (e) => {
            if (cb.checked) selectedTrackIds.add(t.id);
            else selectedTrackIds.delete(t.id);
            updateSelectionBar();
        });

        row.addEventListener('click', (e) => {
            if (isSelectingMode) {
                cb.checked = !cb.checked;
                cb.dispatchEvent(new Event('change'));
                return;
            }
            if (!e.target.closest('.track-btns')) {
                playTrack(t);
            }
        });

        row.addEventListener('contextmenu', (e) => {
            if (isSelectingMode) return;
            showContextMenu(e, t);
        });

        row.querySelector('.row-play').addEventListener('click', (e) => {
            e.stopPropagation();
            playTrack(t);
        });

        row.querySelector('.row-dl').addEventListener('click', (e) => {
            e.stopPropagation();
            downloadLocalTrack(t);
        });

        return row;
    }

    // -- Toast Notifications --
    function showToast(message, type = 'info', duration = 3000) {
        const container = toastContainer || document.getElementById('toastContainer');
        if (!container) return;
        const toast = document.createElement('div');
        toast.className = `toast-item toast-${type}`;
        toast.innerHTML = `<span>${esc(message)}</span>`;
        container.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add('toast-visible'));
        setTimeout(() => {
            toast.classList.remove('toast-visible');
            toast.addEventListener('transitionend', () => toast.remove());
        }, duration);
    }

    function formatTime(secs) {
        if (!secs || isNaN(secs)) return '0:00';
        const m = Math.floor(secs / 60);
        const s = Math.floor(secs % 60);
        return `${m}:${s < 10 ? '0' : ''}${s}`;
    }

    function esc(s) {
        if (!s) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    // -- Context Menu System --
    let _ctxMenuTrack = null;
    function showContextMenu(e, track) {
        e.preventDefault();
        _ctxMenuTrack = track;
        const menu = document.getElementById('context-menu');
        if (!menu) return;
        menu.style.left = Math.min(e.clientX, window.innerWidth - 220) + 'px';
        menu.style.top = Math.min(e.clientY, window.innerHeight - 320) + 'px';
        menu.classList.remove('hidden');
        // Update favorite button text
        const favBtn = menu.querySelector('[data-action="toggle-fav"]');
        if (favBtn) {
            fetch('/api/favorites/' + encodeURIComponent(track.id) + '/status')
                .then(r => r.json())
                .then(d => { favBtn.textContent = d.favorited ? '♥ Unfavorite' : '♡ Add to Favorites'; })
                .catch(() => {});
        }
    }

    function handleContextAction(action) {
        const menu = document.getElementById('context-menu');
        if (menu) menu.classList.add('hidden');
        if (!_ctxMenuTrack) return;
        const track = _ctxMenuTrack;
        switch (action) {
            case 'play-next':
                queue.splice(queueIndex + 1, 0, track);
                showToast('Playing next: ' + (track.title || 'Unknown'), 'success');
                break;
            case 'add-queue':
                queue.push(track);
                showToast('Added to queue', 'success');
                break;
            case 'add-playlist':
                addToPlaylistPrompt([track.id]);
                break;
            case 'toggle-fav':
                fetch('/api/favorites/' + encodeURIComponent(track.id), { method: 'POST' })
                    .then(r => r.json())
                    .then(d => showToast(d.favorited ? 'Added to favorites ♥' : 'Removed from favorites', d.favorited ? 'success' : 'info'))
                    .catch(() => showToast('Failed to update favorite', 'error'));
                break;
            case 'go-artist':
                if (track.artist) loadArtistDetail(track.artist);
                break;
            case 'go-album':
                if (track.album) loadAlbumDetail(track.album);
                break;
            case 'download':
                window.open('/api/file/' + encodeURIComponent(track.id), '_blank');
                break;
        }
    }

    // Close context menu on click elsewhere
    document.addEventListener('click', () => {
        const menu = document.getElementById('context-menu');
        if (menu) menu.classList.add('hidden');
    });

    window.handleContextAction = handleContextAction; // Export for inline event handlers if needed

    // -- Favorites Toggle (Currently Playing) --
    function toggleFavoriteCurrent() {
        if (!currentTrack || !currentTrack.id) return;
        fetch('/api/favorites/' + encodeURIComponent(currentTrack.id), { method: 'POST' })
            .then(r => r.json())
            .then(d => {
                showToast(d.favorited ? 'Added to favorites ♥' : 'Removed from favorites', d.favorited ? 'success' : 'info');
                updateFavoriteUI(d.favorited);
            })
            .catch(() => showToast('Failed to update favorite', 'error'));
    }

    function updateFavoriteUI(isFav) {
        document.querySelectorAll('[data-favorite-btn]').forEach(btn => {
            if (isFav) {
                btn.classList.add('text-red-400');
                btn.classList.remove('text-[var(--text-muted)]');
            } else {
                btn.classList.remove('text-red-400');
                btn.classList.add('text-[var(--text-muted)]');
            }
        });
    }

    window.toggleFavoriteCurrent = toggleFavoriteCurrent;

    // -- SSE Client for Real-time Download Progress --
    let _eventSource = null;
    function connectSSE() {
        if (_eventSource) return;
        try {
            _eventSource = new EventSource('/api/events');
            _eventSource.addEventListener('download_progress', (e) => {
                try {
                    const data = JSON.parse(e.data);
                    // Update download UI if modal is open
                    if (downloadsModal && !downloadsModal.classList.contains('hidden')) {
                        pollDownloadQueue();
                    }
                } catch (_) {}
            });
            _eventSource.addEventListener('download_complete', (e) => {
                try {
                    const data = JSON.parse(e.data);
                    showToast('Downloaded: ' + (data.title || 'track'), 'success');
                    switchView(currentView); // Refresh current view
                } catch (_) {}
            });
            _eventSource.onerror = () => {
                if (_eventSource) _eventSource.close();
                _eventSource = null;
                setTimeout(connectSSE, 5000);
            };
        } catch (_) {
            // SSE not supported, fall back to polling
        }
    }

    // -- Playlist Management --
    function loadPlaylists() {
        fetch('/api/playlists').then(r => r.json()).then(playlists => {
            const container = document.getElementById('playlists-list');
            if (!container) return;
            if (!playlists.length) {
                container.innerHTML = '<p class="text-xs text-[var(--text-muted)] px-3 py-2 italic">No playlists yet</p>';
                return;
            }
            container.innerHTML = playlists.map(pl => `
                <button onclick="loadPlaylistDetail('${esc(pl.id)}')" class="w-full flex items-center space-x-3 px-3 py-2 rounded-lg text-sm text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-surface)] transition text-left">
                    <span class="w-6 h-6 rounded bg-purple-500/20 text-purple-400 flex items-center justify-center text-xs">♫</span>
                    <span class="truncate flex-1">${esc(pl.name)}</span>
                    <span class="text-[10px] text-[var(--text-muted)]">${pl.track_count || 0}</span>
                </button>
            `).join('');
        }).catch(() => {});
    }

    function createPlaylistPrompt() {
        const name = prompt('Playlist name:');
        if (!name || !name.trim()) return;
        fetch('/api/playlists', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name.trim() })
        })
        .then(r => r.json())
        .then(() => { showToast('Playlist created!', 'success'); loadPlaylists(); })
        .catch(() => showToast('Failed to create playlist', 'error'));
    }

    function loadPlaylistDetail(playlistId) {
        fetch('/api/playlists/' + encodeURIComponent(playlistId))
            .then(r => r.json())
            .then(pl => {
                if (pl.tracks && pl.tracks.length) {
                    // Load tracks into queue and play
                    queue = pl.tracks.slice();
                    queueIndex = 0;
                    playTrack(queue[0]);
                    showToast('Playing: ' + pl.name, 'success');
                } else {
                    showToast('Playlist is empty', 'info');
                }
            })
            .catch(() => showToast('Failed to load playlist', 'error'));
    }

    function addToPlaylistPrompt(trackIds) {
        fetch('/api/playlists').then(r => r.json()).then(playlists => {
            if (!playlists.length) {
                const name = prompt('No playlists yet. Create one:');
                if (!name) return;
                fetch('/api/playlists', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: name.trim() })
                }).then(r => r.json()).then(pl => {
                    return fetch('/api/playlists/' + pl.id + '/tracks', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ track_ids: trackIds })
                    });
                }).then(() => { showToast('Added to new playlist!', 'success'); loadPlaylists(); })
                .catch(() => showToast('Failed', 'error'));
                return;
            }
            const choices = playlists.map((pl, i) => `${i + 1}. ${pl.name}`).join('\n');
            const pick = prompt('Add to which playlist?\n' + choices);
            if (!pick) return;
            const idx = parseInt(pick) - 1;
            if (idx < 0 || idx >= playlists.length) return;
            fetch('/api/playlists/' + playlists[idx].id + '/tracks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ track_ids: trackIds })
            }).then(() => { showToast('Added to ' + playlists[idx].name, 'success'); loadPlaylists(); })
            .catch(() => showToast('Failed to add to playlist', 'error'));
        }).catch(() => showToast('Could not load playlists', 'error'));
    }

    // -- Recently Played --
    function loadRecentlyPlayed() {
        fetch('/api/history/recent?limit=10').then(r => r.json()).then(tracks => {
            const section = document.getElementById('recently-played-section');
            const list = document.getElementById('recently-played-list');
            if (!section || !list) return;
            if (!tracks.length) { section.classList.add('hidden'); return; }
            section.classList.remove('hidden');
            list.innerHTML = '';
            tracks.forEach(t => list.appendChild(createTrackRow(t)));
        }).catch(() => {});
    }

    // -- Shortcuts Modal --
    function openShortcutsModal() {
        const modal = document.getElementById('shortcuts-modal');
        if (modal) modal.classList.remove('hidden');
    }

    function closeAllModals() {
        ['shortcuts-modal', 'settings-modal', 'context-menu'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.classList.add('hidden');
        });
        // Close other modals/panels
        if (downloadsModal) downloadsModal.classList.add('hidden');
        if (lyricsPanel) lyricsPanel.classList.add('hidden');
        if (queuePanel) queuePanel.classList.add('hidden');
        if (searchOverlay) searchOverlay.classList.add('hidden');
        if (cmdPalette) cmdPalette.classList.add('hidden');
    }

    // Export functions for inline HTML event handlers
    window.createPlaylistPrompt = createPlaylistPrompt;
    window.loadPlaylistDetail = loadPlaylistDetail;
    window.addToPlaylistPrompt = addToPlaylistPrompt;
    window.openShortcutsModal = openShortcutsModal;

    // Initial load
    if (shuffle) btnShuffle.classList.add('active');
    if (repeat) btnRepeat.classList.add('active');
    switchView('recent');
    startDownloadPolling();
    connectSSE();
    loadPlaylists();
    loadRecentlyPlayed();
})();

