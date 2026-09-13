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
    let shuffle = false;
    let repeat = false;
    let currentView = 'recent';
    let searchTimeout = null;
    let isSelectingMode = false;
    let selectedTrackIds = new Set();
    let currentTrack = null;
    let dlPollInterval = null;
    let currentLayout = localStorage.getItem('zoink_layout') || 'auto';

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
    document.addEventListener('keydown', (e) => {
        if (document.activeElement === searchInput || document.activeElement === cmdInput) {
            return;
        }
        if (e.key === '/') {
            e.preventDefault();
            searchInput.focus();
            searchInput.select();
        } else if (e.code === 'Space') {
            e.preventDefault();
            togglePlay();
        } else if (e.key === 'j' || e.key === 'J') {
            prevTrack();
        } else if (e.key === 'k' || e.key === 'K') {
            nextTrack();
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
        btnShuffle.classList.toggle('active', shuffle);
        showToast(shuffle ? 'Shuffle enabled' : 'Shuffle disabled');
    }

    function toggleRepeat() {
        repeat = !repeat;
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
    seekBar.addEventListener('input', () => {
        if (audio.duration) {
            const seekTo = (seekBar.value / 100) * audio.duration;
            audio.currentTime = seekTo;
            seekProgressFill.style.width = seekBar.value + '%';
        }
    });

    audio.addEventListener('timeupdate', () => {
        if (audio.duration) {
            const pct = (audio.currentTime / audio.duration) * 100;
            seekBar.value = pct;
            seekProgressFill.style.width = pct + '%';
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
        volProgressFill.style.width = volumeBar.value + '%';
        if (audio.muted) toggleMute();
    });
    volProgressFill.style.width = volumeBar.value + '%';
    audio.volume = 0.85;

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
            const res = await fetch('/api/search?q=' + encodeURIComponent(query) + '&limit=15');
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
    function showToast(msg, type = 'info') {
        const toast = document.createElement('div');
        toast.className = 'toast';
        if (type === 'error') toast.style.borderColor = 'var(--danger)';
        if (type === 'success') toast.style.borderColor = 'var(--success)';
        toast.textContent = msg;
        toastContainer.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(10px)';
            toast.style.transition = 'all 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 2800);
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

    // Initial load
    switchView('recent');
    startDownloadPolling();
})();

