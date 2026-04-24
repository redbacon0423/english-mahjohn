// --- Global Initialization ---
window.socket = (typeof io !== 'undefined') ? io() : null;
if (!window.socket) {
    console.error("Socket.io failed to load! Library 'io' is undefined.");
}
const socket = window.socket;

// --- Global State ---
let myHand = [];
let gameState = null;
let roomID = "";
let username = "";
try { username = localStorage.getItem('mahjong_username') || ""; } catch(e) {}
let isSpectator = false;
let myRole = 'player';
let localHand = [];
let previousLastDiscard = null;
let dragSourceIdx = null;
let selectedTileIdx = -1; 
let isDraggingTile = false;
let dragStartX = 0;
let dragStartY = 0;
let currentDragX = 0;
let currentDragY = 0;
let currentGameMode = null; 
let activePointerId = null; // 🚀 Prevent multi-touch interference
let showHands = false; // Spectator: whether to show all hands
let lastWallTilesLeft = -1; // 🚀 Optimize: Track tiles left to avoid redrawing wall
let renderScheduled = false; // 🚀 Render throttle flag



// --- Mahjong Positions ---
const POS_NAMES = ['P1', 'P2', 'P3', 'P4'];
const POS_CLASSES = ['pos-east', 'pos-south', 'pos-west', 'pos-north'];

// --- Audio ---
window.addEventListener('error', function(e) {
    const errBox = document.createElement('div');
    errBox.style = 'position:fixed;top:10%;left:10%;right:10%;background:rgba(255,0,0,0.9);color:white;z-index:999999;padding:20px;font-size:18px;border-radius:10px;box-shadow:0 0 20px black;';
    errBox.innerHTML = '<b>JS ERROR:</b> ' + e.message + '<br>Line: ' + e.lineno;
    document.body.appendChild(errBox);
});

let audioCtx = null;
try {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
} catch (e) {
    console.warn("AudioContext not supported or blocked.");
}
let isDrawing = false;
function playSynthSound(freq, duration, type = 'triangle', gain = 0.5) {
    try {
        if (!audioCtx) return;
        if (audioCtx.state === 'suspended') audioCtx.resume();
        const osc = audioCtx.createOscillator();
        const gainNode = audioCtx.createGain();
        osc.type = type;
        osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(10, audioCtx.currentTime + duration);
        gainNode.gain.setValueAtTime(gain, audioCtx.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + duration);
        osc.connect(gainNode);
        gainNode.connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + duration);
    } catch (e) { }
}

function playCardSound() { playSynthSound(800, 0.05); }
function playChiSound() { playSynthSound(440, 0.3, 'sine'); playSynthSound(880, 0.3, 'sine', 0.2); }
function playHuSound() {
    const now = audioCtx.currentTime;
    [440, 554, 659, 880].forEach((f, i) => {
        const osc = audioCtx.createOscillator();
        const g = audioCtx.createGain();
        osc.frequency.setValueAtTime(f, now + i * 0.1);
        g.gain.setValueAtTime(0.3, now + i * 0.1);
        g.gain.exponentialRampToValueAtTime(0.01, now + i * 0.1 + 0.5);
        osc.connect(g); g.connect(audioCtx.destination);
        osc.start(now + i * 0.1); osc.stop(now + i * 0.1 + 0.5);
    });
}
function playWheelTick() { playSynthSound(1000, 0.02, 'square', 0.1); }
function playWheelSuccess() { playSynthSound(1200, 0.5, 'triangle', 0.3); }
function playDrawSound() { playSynthSound(900, 0.1, 'sine', 0.2); }
function playDblClickSound() { playSynthSound(1500, 0.03, 'sine', 0.3); }
function playTileSwapSound() { 
    // 🀄 Soft, tactile 'thock/click' sound for Mahjong tiles sliding past each other
    playSynthSound(400, 0.03, 'triangle', 0.15); 
    playSynthSound(1200, 0.02, 'sine', 0.05);
}

// --- UI Actions ---
// --- UI Actions ---
function startSinglePlayer() {
    username = "PLAYER_" + Math.random().toString(36).substr(2, 4).toUpperCase();
    roomID = "SINGLE_" + Math.random().toString(36).substr(2, 4).toUpperCase();
    localStorage.setItem('mahjong_username', username);
    
    currentGameMode = 'single';
    myRole = 'player';
    
    const userInp = document.getElementById('username-input');
    if (userInp) userInp.value = username;
    const roomInp = document.getElementById('room-id-input');
    if (roomInp) roomInp.value = roomID;
    
    // Instead of direct emit, use the standardized joinRoom logic if possible
    // but here we just manually trigger it to ensure single mode is passed
    socket.emit('join', { 
        room: roomID, 
        username, 
        mode: 'single',
        role: 'player',
        difficulty: document.getElementById('ai-difficulty-select')?.value || 'normal'
    });
    
    document.getElementById('menu-overlay').classList.add('hidden');
    document.getElementById('chat-container').classList.add('hidden');
    
    showToast("👤 SINGLE PLAYER READY");
}

function showJoin(mode) {
    if (mode === 'host') {
        isSpectator = true;
        myRole = 'spectator';
        roomID = Math.floor(1000 + Math.random() * 9000).toString();
        
        username = "TV_ROOM_" + Math.random().toString(36).substr(2, 4).toUpperCase();
        
        socket.emit('join', { username, room: roomID, mode: 'spectator', role: 'spectator' });
        
        document.body.classList.remove('controller-mode');
        document.body.classList.remove('mobile-mode');
        document.body.classList.add('spectator-mode');
        document.getElementById('spectator-controls').classList.remove('hidden');
        document.getElementById('menu-overlay').classList.add('hidden');
        document.getElementById('waiting-overlay').classList.remove('hidden');
        updateDynamicQR();
    }
}

function startPerformanceMode() {
    roomID = "demo_" + Math.random().toString(36).substr(2, 5);
    socket.emit('start_demo_mode', { room: roomID });
    
    // Automatically switch to spectator mode to watch the AI
    isSpectator = true;
    myRole = 'spectator';
    document.body.classList.remove('mobile-mode');
    document.body.classList.add('spectator-mode');
    document.getElementById('spectator-controls').classList.remove('hidden');
    document.getElementById('menu-overlay').classList.add('hidden');
    document.getElementById('reveal-hands-toggle').checked = true; // Auto-reveal hands for demo
    showHands = true;
    
    showToast("🤖 PERFORMANCE MODE (AI vs AI) READY");
}
window.startPerformanceMode = startPerformanceMode;



function joinRoom() {
    const user = document.getElementById('username-input').value || "Anonymous";
    roomID = document.getElementById('room-id-input').value || "Lobby";
    username = user;
    localStorage.setItem('mahjong_username', user);
    
    document.getElementById('join-overlay').classList.add('hidden');
    if (socket) {
        console.log("Joined room:", roomID);
        currentGameMode = 'multi'; 
        socket.emit('join', { room: roomID, username: user, role: myRole });
    }
}
window.joinRoom = joinRoom;

// 🚀 Ensure All "Start Game" buttons work
const triggerStart = (e) => {
    if (e && e.target) {
        const btn = e.target;
        btn.innerText = "STARTING...";
        btn.disabled = true;
        btn.style.opacity = "0.5";
        btn.style.pointerEvents = "none";
    }

    if (!roomID) {
        console.warn("Cannot start game: roomID is missing.");
        showToast("❌ Error: Room ID not found. Try reconnecting.");
        return;
    }
    if (socket) {
        console.log("Emitting start_game for room:", roomID);
        socket.emit('start_game', { room: roomID });
    }
};

// Safe event binding - Make functions global for inline onclick
window.startSinglePlayer = startSinglePlayer;
window.showJoin = showJoin;
window.toggleRules = toggleRules;
window.triggerStart = triggerStart;

const bindStartButtons = () => {
    console.log("Binding Start Buttons... current roomID:", roomID);
    const startBtn = document.getElementById('start-btn');
    const tableStartBtn = document.getElementById('table-start-btn');
    
    if (startBtn) {
        startBtn.removeEventListener('click', triggerStart);
        startBtn.addEventListener('click', triggerStart);
    }
    if (tableStartBtn) {
        tableStartBtn.removeEventListener('click', triggerStart);
        tableStartBtn.addEventListener('click', triggerStart);
    }
};
bindStartButtons();
window.addEventListener('load', bindStartButtons);




function renderBoard() {
    if (renderScheduled) return;
    renderScheduled = true;
    
    requestAnimationFrame(() => {
        actuallyRenderBoard();
        renderScheduled = false;
    });
}

function actuallyRenderBoard() {
    if (!gameState) return;

    // Detect new discard
    if (gameState.last_discard) {
        const currentDiscardStr = JSON.stringify(gameState.last_discard);
        if (currentDiscardStr !== previousLastDiscard) {
            playCardSound();
            previousLastDiscard = currentDiscardStr;
        }
    }

    const positions = ['bottom', 'right', 'top', 'left'];
    const myIndex = getMyIndex();
    // 🚀 Robust Indexing: Priority to SID, fallback to unique localStorage ID (if implemented),
    // next fallback to name, last fallback to index 0 (if Single Player/only one human)
    let effectiveMyIdx = (myIndex !== -1) ? myIndex : gameState.players.findIndex(p => p.name === username && !p.sid.startsWith('ai_'));
    
    if (effectiveMyIdx === -1) {
        // 📺 SPECTATOR/TV STABILITY: For spectators, fix the view to Player 0's perspective.
        // This prevents the board from rotating suddenly if human players join or leave.
        effectiveMyIdx = 0;
    }

    for (let index = 0; index < 4; index++) {
        const player = gameState.players[index];

        let relIdx = (index - (effectiveMyIdx === -1 ? 0 : effectiveMyIdx) + 4) % 4;
        const pos = positions[relIdx];

        const nameEl = document.getElementById(`name-${pos}`);
        const handEl = document.getElementById(`hand-${pos}`);
        const meldsEl = document.getElementById(`melds-${pos}`);

        if (handEl) handEl.innerHTML = '';
        if (nameEl) {
            if (player) {
                const posLabel = ""; // No more wind labels
                
                // --- Win Probability Badge (Spectator / TV mode only) ---
                let probBadge = "";
                if (isSpectator && gameState.game_started) {
                    const prob = calculateWinProb(player);
                    probBadge = `<div class="win-prob-badge">WIN: ${prob}%</div>`;
                }

                nameEl.innerHTML = `
                    ${probBadge}
                    ${posLabel}
                    <div class="p-name">${player.name}</div>
                    <div class="p-meta">${gameState.game_started ? player.hand_size + ' Tiles' : 'Waiting...'}</div>
                `;
                nameEl.className = 'player-name' + (gameState.current_turn === index ? ' active-turn active-turn-glow' : '');
                nameEl.style.opacity = "1";
                nameEl.classList.remove('hidden');
                // 🕒 Numeric Timer (Only visible to the ACTIVE local player OR host/TV)
                const isMyHand = (!isSpectator && index === effectiveMyIdx);
                const canSeeHand = player.hand && (isMyHand || (isSpectator && showHands));

                if (gameState.current_turn === index && (isMyHand || isSpectator)) {
                    const timerFloating = document.createElement('div');
                    timerFloating.className = `timer-floating ${player.turn_time <= 3 ? 'urgent' : ''}`;
                    timerFloating.innerHTML = `
                        <div class="timer-val">${Math.ceil(player.turn_time > 0 ? player.turn_time : player.bank_time)}</div>
                    `;
                    if (handEl) handEl.appendChild(timerFloating);
                }

                if (canSeeHand) {
                    // 🛡️ Enhanced Sync: Fallback to localHand if server hand is temporarily missing in public broadcast
                    if (isMyHand) {
                        const handData = player.hand || myHand || [];
                        if (handData && handData.length > 0) {
                            syncLocalHand(handData);
                        }
                    }
                    const handToRender = isMyHand ? localHand : player.hand;
                    handToRender.forEach((tile, tileIdx) => {
                        const tileEl = createTileElement(tile, false, pos);
                        tileEl.setAttribute('data-idx', tileIdx); 
                        
                        if (isMyHand && pos === 'bottom') {
                            // --- Enhanced Pointer-Based Drag-and-Drop ---
                            tileEl.addEventListener('pointerdown', (e) => {
                                const isTurn = (gameState.current_turn === index && gameState.state !== 'WAITING_ACTION');
                                
                                // 🚀 Prevent multi-touch / palm rejection interference freezing the board
                                if (activePointerId !== null && activePointerId !== e.pointerId) return;
                                activePointerId = e.pointerId;
                                
                                // Prevent default to avoid scroll while dragging
                                if (e.pointerType === 'touch') {
                                    // We don't preventDefault here to allow clicking but we'll monitor movement
                                } else {
                                    e.preventDefault(); // This is critical to prevent native HTML5 drag-and-drop (semi-transparent ghost) on desktop
                                }

                                dragSourceIdx = parseInt(tileEl.getAttribute('data-idx'));
                                
                                // ABSOLUTE ORIGIN DRAG: Get untransformed layout position
                                const oldTransform = tileEl.style.transform;
                                tileEl.style.transform = "";
                                const rect = tileEl.getBoundingClientRect();
                                tileEl.style.transform = oldTransform;
                                
                                dragStartX = e.clientX - rect.left; // grabOffsetX
                                dragStartY = e.clientY - rect.top;  // grabOffsetY
                                isDraggingTile = false; // Reset dragging state
                                
                                tileEl.setPointerCapture(e.pointerId);
                            });

                            tileEl.addEventListener('pointermove', (e) => {
                                if (dragSourceIdx !== parseInt(tileEl.getAttribute('data-idx'))) return;
                                
                                // 🚀 Throttle dragging logic to 60fps
                                if (window.dragFrameScheduled) return;
                                window.dragFrameScheduled = true;
                                
                                requestAnimationFrame(() => {
                                    window.dragFrameScheduled = false;
                                    
                                    // 🛑 GUARD: Prevents async rAF callback from resurrecting a canceled drag
                                    if (activePointerId !== e.pointerId) return;
                                    
                                    // ABSOLUTE ORIGIN DRAG: calculate dx, dy from the current layout slot
                                    const oldTransform = tileEl.style.transform;
                                    tileEl.style.transform = "";
                                    const rect = tileEl.getBoundingClientRect();
                                    tileEl.style.transform = oldTransform;
                                    
                                    let dx = e.clientX - dragStartX - rect.left;
                                    let dy = e.clientY - dragStartY - rect.top;
                                    
                                    // Threshold to distinguish between click and drag
                                    if (!isDraggingTile && (Math.abs(dx) > 10 || Math.abs(dy) > 10)) {
                                        isDraggingTile = true;
                                        tileEl.classList.add('dragging-visual');
                                    }
                                    
                                    if (isDraggingTile) {
                                        tileEl.style.transform = `translate3d(${dx}px, ${dy}px, 0) scale(1.1)`; // 🚀 Use translate3d for GPU acceleration
                                        tileEl.style.zIndex = "999";
                                        
                                        // 🚀 OPTIMIZATION: Real-time reordering without destructive re-render
                                        const elements = document.elementsFromPoint(e.clientX, e.clientY);
                                        let hoveredTile = null;
                                        for (let el of elements) {
                                            const closestTile = el.closest('.tile[data-idx]');
                                            if (closestTile && closestTile !== tileEl) {
                                                hoveredTile = closestTile;
                                                break;
                                            }
                                        }
                                        if (hoveredTile && hoveredTile !== tileEl && hoveredTile.parentNode === tileEl.parentNode) {
                                            const targetIdx = parseInt(hoveredTile.getAttribute('data-idx'));
                                            if (targetIdx !== dragSourceIdx) {
                                                // 1. Update Data Model
                                                const item = localHand.splice(dragSourceIdx, 1)[0];
                                                localHand.splice(targetIdx, 0, item);
                                                
                                                // 2. Localized DOM Swap (Non-destructive)
                                                const parent = tileEl.parentNode;
                                                
                                                if (targetIdx < dragSourceIdx) {
                                                    parent.insertBefore(tileEl, hoveredTile);
                                                } else {
                                                    parent.insertBefore(tileEl, hoveredTile.nextSibling);
                                                }
                                                
                                                // 🚀 CRITICAL FIX: Moving an element in the DOM implicitly drops pointer capture.
                                                // We MUST immediately recapture it so we don't lose the drag events!
                                                try { tileEl.setPointerCapture(e.pointerId); } catch (err) {}
                                                
                                                // 🔊 Play tactile feedback sound
                                                playTileSwapSound();
                                                
                                                // 3. Immediately correct coordinates for THIS frame layout change
                                                tileEl.style.transform = "";
                                                const newRect = tileEl.getBoundingClientRect();
                                                dx = e.clientX - dragStartX - newRect.left;
                                                dy = e.clientY - dragStartY - newRect.top;
                                                tileEl.style.transform = `translate3d(${dx}px, ${dy}px, 0) scale(1.1)`;
                                                
                                                // 4. Sync metadata without re-rendering everything
                                                parent.querySelectorAll('.tile[data-idx]').forEach((t, i) => {
                                                    t.setAttribute('data-idx', i);
                                                });
                                                
                                                dragSourceIdx = targetIdx;
                                                // NOTE: We don't call renderBoard() here to keep the animation buttery smooth
                                            }
                                        }
                                    }
                                });
                            });

                            tileEl.addEventListener('pointerup', (e) => {
                                if (e.pointerId === activePointerId) activePointerId = null;
                                if (dragSourceIdx !== parseInt(tileEl.getAttribute('data-idx'))) return;
                                try { tileEl.releasePointerCapture(e.pointerId); } catch(err) {}
                                
                                if (isDraggingTile) {
                                    isDraggingTile = false;
                                    dragSourceIdx = null;
                                    tileEl.classList.remove('dragging-visual');
                                    tileEl.style.transform = "";
                                    tileEl.style.zIndex = "";
                                    renderBoard();
                                    return;
                                }

                                tileEl.style.pointerEvents = ""; // 🚀 Restore events
                                // --- Click Handling (Logic from original implementation) ---
                                const isTurn = (gameState.current_turn === index && gameState.state !== 'WAITING_ACTION');
                                
                                // 🛡️ Block discard if waiting for Chi/Skip/Hu action
                                if (gameState.state === 'WAITING_ACTION' && gameState.current_turn === index) {
                                    showToast("⚠️ Use CHI, HU, or SKIP first!");
                                    selectedTileIdx = -1;
                                    renderBoard();
                                    return;
                                }

                                 const currentIdx = parseInt(tileEl.getAttribute('data-idx'));
                                 if (selectedTileIdx !== -1 && selectedTileIdx !== currentIdx) {
                                      const item = localHand.splice(selectedTileIdx, 1)[0];
                                      localHand.splice(currentIdx, 0, item);
                                      selectedTileIdx = -1; 
                                      renderBoard();
                                      return;
                                 }

                                 if (selectedTileIdx === currentIdx) {
                                         const myIndex = getMyIndex();
                                         if (myIndex === -1) return;
                                         const serverHand = gameState.players[myIndex].hand;
                                         const serverIdx = serverHand.findIndex(t => t.type === tile.type && t.value === tile.value);
                                         
                                         if (serverIdx !== -1) {
                                             playDblClickSound();
                                             socket.emit('discard', { room: roomID, tile_index: serverIdx });
                                             selectedTileIdx = -1;
                                         } else {
                                             selectedTileIdx = -1;
                                         }
                                     renderBoard();
                                     return;
                                 }
                                 
                                 selectedTileIdx = currentIdx;
                                 renderBoard(); 
                            });

                            tileEl.addEventListener('pointercancel', (e) => {
                                if (e.pointerId === activePointerId) activePointerId = null;
                                if (dragSourceIdx !== parseInt(tileEl.getAttribute('data-idx'))) return;
                                try { tileEl.releasePointerCapture(e.pointerId); } catch(err) {}
                                if (isDraggingTile) {
                                    isDraggingTile = false;
                                    dragSourceIdx = null;
                                    tileEl.classList.remove('dragging-visual');
                                    tileEl.style.transform = "";
                                    tileEl.style.zIndex = "";
                                    renderBoard();
                                }
                            });

                            if (tileIdx === selectedTileIdx) {
                                tileEl.classList.add('popped');
                            }
                        }
                        handEl.appendChild(tileEl);
                    });
                } else {
                    for (let i = 0; i < player.hand_size; i++) {
                        const back = createTileElement({ type: 'back' }, false, pos);
                        handEl.appendChild(back);
                    }
                }
            }
        }

        if (meldsEl) {
            meldsEl.innerHTML = '';
            if (player) {
                player.melds.forEach(word => {
                    const meldWrap = document.createElement('div');
                    meldWrap.className = 'meld-group';
                    for (let char of word) {
                        meldWrap.appendChild(createTileElement({ type: 'letter', value: char }, true, pos));
                    }
                    meldsEl.appendChild(meldWrap);
                });
            }
        }

        const discardEl = document.getElementById(`discard-${pos}`);
        if (discardEl) {
            discardEl.innerHTML = '';
            (gameState.discard_piles[index] || []).forEach(tile => {
                discardEl.appendChild(createTileElement(tile, true));
            });
        }
    }

    renderWall();
    updateActionUI();
}

function renderWall() {
    if (!gameState) return;
    if (gameState.tiles_left === lastWallTilesLeft) return; // 🚀 SKIP if tiles haven't changed
    lastWallTilesLeft = gameState.tiles_left;
    
    const wallSides = ['top', 'right', 'bottom', 'left'];
    const drawOrder = ['left', 'bottom', 'right', 'top'];
    const tilesDrawn = 144 - gameState.tiles_left;
    const stacksDrawn = Math.floor(tilesDrawn / 2);
    const partialStackDraw = tilesDrawn % 2;

    wallSides.forEach((side) => {
        const sideEl = document.getElementById(`wall-${side}`);
        if (!sideEl) return;
        sideEl.innerHTML = '';
        const sDrawIdx = drawOrder.indexOf(side);
        for (let i = 0; i < 18; i++) {
            const stackIdx = sDrawIdx * 18 + i;
            const stackEl = document.createElement('div');
            stackEl.className = 'wall-stack';
            let tilesInStack = 0;
            if (stackIdx > stacksDrawn) tilesInStack = 2;
            else if (stackIdx === stacksDrawn) tilesInStack = (partialStackDraw === 0) ? 0 : 1;
            for (let j = 0; j < tilesInStack; j++) {
                const t = document.createElement('div');
                t.className = 'wall-tile';
                stackEl.appendChild(t);
            }
            sideEl.appendChild(stackEl);
        }
    });
}

function createTileElement(tile, isSmall = false, position = 'bottom') {
    const el = document.createElement('div');
    const isVertical = position === 'left' || position === 'right';
    if (tile.type === 'letter') {
        el.className = `tile ${isSmall ? 'small' : ''} ${isVertical ? 'rotated' : ''}`;
        el.innerText = tile.value;
    } else {
        el.className = `tile tile-back ${isSmall ? 'small' : ''} ${isVertical ? 'rotated' : ''}`;
    }
    return el;
}

function updateActionUI() {
    const container = document.getElementById('action-container');
    const myIndex = getMyIndex();

    container.innerHTML = '';
    let showContainer = false;

    if (myIndex !== -1 && gameState.game_started && !isSpectator) {
        const isMyTurn = (gameState.current_turn === myIndex);
        const isWaitingForMe = (gameState.state === 'WAITING_ACTION' && gameState.current_turn === myIndex);

        // 🎯 Show HU button ONLY when server detects the hand can win
        if (isMyTurn && gameState.can_hu) {
            const huBtn = document.createElement('button');
            huBtn.id = 'btn-hu';
            huBtn.className = 'action-btn hu hu-glow';
            huBtn.innerText = '🀄 HU (WIN)';
            huBtn.onclick = () => {
                if (isDrawing) return;
                showCustomInput(`Enter the words in your hand (separate with spaces):`, (words) => {
                    if (words) socket.emit('action_hu', { room: roomID, words: words });
                });
            };
            container.appendChild(huBtn);
            showContainer = true;
        }

        // Show CHI button only if waiting AND there are actual options
        if (isWaitingForMe) {
            const options = gameState.chi_options[String(myIndex)] || [];
            if (options === true || (Array.isArray(options) && options.length > 0)) {
                const chiBtn = document.createElement('button');
                chiBtn.id = 'btn-chi';
                chiBtn.className = 'action-btn chi';
                chiBtn.innerText = `CHI`; // 🛡️ Hide count
                chiBtn.onclick = () => {
                    showCustomInput(`Enter the word to CHI:`, (word) => {
                        if (word && word.trim()) socket.emit('action_chi', { room: roomID, word: word.trim() });
                    });
                };
                container.appendChild(chiBtn);
            }

            // Always show SKIP during WAITING_ACTION
            const skipBtn = document.createElement('button');
            skipBtn.id = 'btn-skip';
            skipBtn.className = 'action-btn skip';
            skipBtn.innerText = 'SKIP';
            skipBtn.onclick = () => socket.emit('action_skip', { room: roomID });
            container.appendChild(skipBtn);
            showContainer = true;
        }
    }

    if (showContainer) {
        container.classList.remove('hidden');
    } else {
        container.classList.add('hidden');
    }
}

function getMyIndex(stateOverride) { 
    const s = stateOverride || gameState;
    return (s && s.players) ? s.players.findIndex(p => p.sid === socket.id) : -1; 
}

function syncLocalHand(serverHand) {
    if (!serverHand) return; // 🛡️ Safety: Prevent crash if hand data is missing
    if (localHand.length === 0) { localHand = [...serverHand]; return; }
    
    // 1. Consume matches from server hand for tiles ALREADY in local hand
    const serverStrings = serverHand.map(t => JSON.stringify(t));
    localHand = localHand.filter(t => {
        const s = JSON.stringify(t);
        const idx = serverStrings.indexOf(s);
        if (idx !== -1) { 
            serverStrings.splice(idx, 1); 
            return true; 
        }
        return false;
    });
    
    // 2. Add any tiles remaining in serverStrings (newly drawn or missing tiles)
    serverStrings.forEach(s => {
        localHand.push(JSON.parse(s));
    });
}



function showToast(msg) {
    const t = document.getElementById('toast');
    t.innerText = msg; t.classList.remove('hidden');
    setTimeout(() => t.classList.add('hidden'), 3000);
}


function toggleRevealHands() {
    showHands = document.getElementById('reveal-hands-toggle').checked;
    renderBoard();
    showToast(showHands ? "👁️ hands REVEALED" : "🙈 hands HIDDEN");
}

function updateAIInterval(val) {
    if (socket && roomID) {
        socket.emit('update_ai_interval', { room: roomID, interval: val });
        showToast(`🤖 AI Speed: ${val}s`);
    }
}
window.updateAIInterval = updateAIInterval;

function calculateWinProb(player) {
    if (!player) return 0;
    // Heuristic: based on melds and hand size
    const meldScore = (player.melds.length / 4) * 70;
    const handSize = player.hand_size || 0;
    const progressScore = (16 - handSize) * 1.5;
    const liveFactor = Math.sin(Date.now() / 2000) * 2; // Subtle live fluctuation
    let res = Math.min(99, Math.round(meldScore + progressScore + liveFactor + 20));
    if (player.melds && player.melds.length >= 4) return 100;
    return Math.max(10, res);
}



function fireConfetti() {
    if (typeof confetti !== 'function') return;
    const count = 200;
    const defaults = { origin: { y: 0.7 }, zIndex: 30000 };

    function fire(particleRatio, opts) {
        confetti({ ...defaults, ...opts, particleCount: Math.floor(count * particleRatio) });
    }

    fire(0.25, { spread: 26, startVelocity: 55 });
    fire(0.2, { spread: 60 });
    fire(0.35, { spread: 100, decay: 0.91, scalar: 0.8 });
    fire(0.1, { spread: 120, startVelocity: 25, decay: 0.92, scalar: 1.2 });
    fire(0.1, { spread: 120, startVelocity: 45 });
}

function showToast(msg) {
    const t = document.getElementById('toast');
    if (!t) return;
    t.innerText = msg;
    t.classList.remove('hidden');
    setTimeout(() => t.classList.add('hidden'), 3000);
}


function triggerFX(type, targetPos = null) {
    const fxLayer = document.getElementById('fx-layer');
    if (!fxLayer) return;

    const el = document.createElement('div');
    const x = targetPos ? targetPos.x : window.innerWidth / 2;
    const y = targetPos ? targetPos.y : window.innerHeight / 2;
    
    el.style.left = x + 'px';
    el.style.top = y + 'px';



    fxLayer.appendChild(el);
    setTimeout(() => el.remove(), 4000);
}



// showRestrictionWheel removed as restrictions are now disabled

function closeWheel() { document.getElementById('wheel-overlay')?.classList.add('hidden'); }
function toggleRules() { document.getElementById('rules-overlay').classList.toggle('hidden'); }

let currentInputCallback = null;
function showCustomInput(title, callback) {
    document.getElementById('input-title').innerText = title;
    const inputField = document.getElementById('custom-input-field');
    inputField.value = '';
    currentInputCallback = callback;
    document.getElementById('input-overlay').classList.remove('hidden');
    setTimeout(() => inputField.focus(), 100);
}
function hideCustomInput() {
    document.getElementById('input-overlay').classList.add('hidden');
    currentInputCallback = null;
}


document.getElementById('input-confirm-btn')?.addEventListener('click', () => {
    if (currentInputCallback) {
        const val = document.getElementById('custom-input-field').value;
        currentInputCallback(val);
    }
    hideCustomInput();
});

document.getElementById('custom-input-field')?.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') document.getElementById('input-confirm-btn').click();
});

function updateDynamicQR() {
    const qrImgs = document.querySelectorAll('.qr-code-img');
    
    // 🌐 Smart Host Detection:
    // 1. If we are on a real domain (not localhost), use the current browser origin.
    // 2. Otherwise, fallback to the SERVER_LOCAL_IP (useful for LAN exhibition).
    let host = window.location.origin;
    
    const isLocal = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
    if (isLocal && typeof SERVER_LOCAL_IP !== 'undefined' && SERVER_LOCAL_IP && SERVER_LOCAL_IP !== '127.0.0.1') {
        host = `http://${SERVER_LOCAL_IP}:${window.location.port || 5001}`;
    }
    
    const url = `${host}?room=${roomID}`;
    qrImgs.forEach(img => img.src = `https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=${encodeURIComponent(url)}`);
    document.querySelectorAll('.room-id-display').forEach(el => el.innerText = roomID);
}

// --- Socket Listeners ---
socket.on('game_state', (state) => { 
    // 🚀 CRITICAL FIX: Ensure the global gameState is ALWAYS updated
    // But FIRST: protect our hand from being erased by the public broadcast
    const myIdx = getMyIndex(state); // Pass state to allow index lookup before gameState is set
    if (myIdx !== -1 && state.players && state.players[myIdx]) {
        const serverHand = state.players[myIdx].hand;
        if (!serverHand || serverHand.length === 0) {
            // Public broadcast has no hand data - inject our cached hand
            if (myHand && myHand.length > 0) {
                state.players[myIdx].hand = myHand;
            } else if (localHand && localHand.length > 0) {
                state.players[myIdx].hand = [...localHand];
            }
        } else {
            // We received a real hand - update our cache
            myHand = serverHand;
        }
    }

    // 🔄 If turn changes, auto-deselect current tile
    if (gameState && gameState.current_turn !== state.current_turn) {
        selectedTileIdx = -1;
    }

    gameState = state;
    
    // 🔄 Ensure roomID and QR are always in sync
    if (state.room_id) {
        if (roomID !== state.room_id) {
            console.log("Room ID Sync Update:", roomID, "->", state.room_id);
            roomID = state.room_id;
            lastQRRoomID = state.room_id; 
            updateDynamicQR();
            bindStartButtons(); // Re-bind if room changes for safety
        }
    }
    
    renderBoard();
    
    const listEl = document.getElementById('player-list');
    const pCount = state.players.length;

    // 🚀 Update mini status label (Player View)
    const statusMini = document.querySelector('.lobby-status-mini');
    if (statusMini) {
        statusMini.innerText = pCount >= 4 ? "ROOM IS FULL!" : `WAITING FOR PLAYERS...`;
    }

    if (listEl) {
        // Update main screen title (English & Bold)
        const hudTitle = document.querySelector('.hud-status h3');
        if (hudTitle) {
            hudTitle.innerHTML = pCount >= 4 
                ? `<span style="color: var(--neon-blue)">ROOM IS FULL! STARTING...</span>`
                : `WAITING FOR PLAYERS...`;
        }
        
        listEl.innerHTML = state.players.map((p, idx) => {
            const isMe = p.sid === socket.id;
            const isAI = p.sid && p.sid.startsWith('ai_');
            const aiTag = isAI ? `<span class="ai-tag">🤖 AI</span>` : "";
            
            return `
                <div class="hud-player-item ${isMe ? 'is-me' : ''}">
                    <div class="hud-player-main">
                        <span class="player-icon">${isAI ? '🤖' : '👤'}</span> 
                        <span class="player-name-text">${p.name.toUpperCase()} ${isMe ? '(YOU)' : ''} ${aiTag}</span>
                    </div>
                    <div class="hud-player-pos ${POS_CLASSES[idx]}">${POS_NAMES[idx]}</div>
                </div>
            `;
        }).join('');

        // 🚀 Remove visual seat map diamond updates as it was deleted from HTML
    }

    // 🏢 Keep connected devices in Lobby state before game starts
    const menu = document.getElementById('menu-overlay');
    // 🚀 Robust Game State Detection
    const isActuallyInGame = (currentGameMode || (myRole && myRole !== ''));
    
    if (!state.game_started && isActuallyInGame) {
        if (menu) menu.classList.add('hidden');
        
        // 🚀 Host (Spectator) sees fullscreen Lobby HUD, players see table with Start button
        // 🚀 Show the full Lobby HUD for everyone (including players) before game starts
        document.getElementById('waiting-overlay').classList.remove('hidden');
        document.getElementById('table-start-overlay').classList.add('hidden');
        
        // document.getElementById('game-status-panel').classList.add('hidden');
        
        // Player count already updated above for global sync

        // Update display Room ID
        document.querySelectorAll('.room-id-display').forEach(el => el.innerText = roomID);
    } else if (state.game_started && isActuallyInGame) {
        document.getElementById('waiting-overlay').classList.add('hidden');
        document.getElementById('table-start-overlay').classList.add('hidden');
        if (menu) menu.classList.add('hidden');
        // document.getElementById('game-status-panel').classList.remove('hidden');
    }

    // Toggle Start Button Visibility (Now always shown in its respective phase)
    const startBtn = document.getElementById('start-btn');
    if (startBtn) {
        if (!state.game_started) {
            startBtn.classList.remove('hidden');
        } else {
            startBtn.classList.add('hidden');
        }
    }
});

// --- Chat System Logic ---
function toggleChat() {
    const chat = document.getElementById('chat-container');
    const btn = document.getElementById('chat-toggle-btn');
    chat.classList.toggle('collapsed');
    btn.innerText = chat.classList.contains('collapsed') ? '+' : '–';
}

function sendChatMessage() {
    const input = document.getElementById('chat-input');
    const msg = input.value.trim();
    if (msg && roomID) {
        socket.emit('chat_message', { msg, username, room: roomID });
        input.value = '';
    }
}

document.getElementById('chat-input')?.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendChatMessage();
});
document.getElementById('chat-send-btn')?.addEventListener('click', sendChatMessage);

socket.on('chat_message', (data) => {
    const msgList = document.getElementById('chat-messages');
    if (!msgList) return;
    
    const div = document.createElement('div');
    div.className = 'chat-msg';
    const colorClass = data.pos_index !== -1 ? POS_CLASSES[data.pos_index] : '';
    
    div.innerHTML = `
        <span class="chat-user ${colorClass}">${data.username}:</span>
        <span class="chat-text">${data.msg}</span>
    `;
    msgList.appendChild(div);
    msgList.scrollTop = msgList.scrollHeight;
    
    // Auto-expand if collapsed and new message arrives
    const chat = document.getElementById('chat-container');
    if (chat.classList.contains('collapsed')) {
        chat.classList.remove('collapsed');
        document.getElementById('chat-toggle-btn').innerText = '–';
    }
});

socket.on('my_hand', (data) => { 
    if (!data.hand || data.hand.length === 0) return;
    myHand = data.hand; 
    playDrawSound(); 
    
    // Inject into gameState for immediate rendering
    const myIdx = getMyIndex();
    if (myIdx !== -1 && gameState && gameState.players[myIdx]) {
        gameState.players[myIdx].hand = data.hand;
    }
    
    renderBoard(); 
});
socket.on('start_restriction_wheel', (res) => {
    // 🛡️ GLOBAL REMOVAL: Skip the wheel animation per user request
    console.log("Restriction Wheel bypassed. Mode:", res.display);
    // document.getElementById('restriction-mini').innerText = res.display;
    // document.getElementById('game-status-panel').classList.remove('hidden');
    // closeWheel();
});
socket.on('game_over', (data) => {
    const isMe = (data.winner === username);
    const overlay = document.getElementById('result-overlay');
    const titleEl = document.getElementById('winner-title');
    const nameEl = document.getElementById('winner-name');
    
    overlay.classList.remove('hidden');
    
    if (isMe) {
        titleEl.innerText = "YOU WIN!";
        titleEl.classList.add('you-win');
        nameEl.innerText = `Congratulations, ${data.winner}!`;
        fireConfetti();
        showToast(`🏆 ${data.winner.toUpperCase()} WINS!`);
    } else {
        titleEl.innerText = "WINNER!";
        titleEl.classList.remove('you-win');
        nameEl.innerText = `🏆 WINNER: ${data.winner}`;
    }

    const handEl = document.getElementById('winner-hand');
    const meldsEl = document.getElementById('winner-melds');
    if (handEl) {
        handEl.innerHTML = '';
        (data.hand || []).forEach(tile => handEl.appendChild(createTileElement(tile)));
    }
    if (meldsEl) {
        meldsEl.innerHTML = '';
        (data.melds || []).forEach(word => {
            const span = document.createElement('span');
            span.className = 'meld-word';
            span.innerText = word;
            meldsEl.appendChild(span);
        });
    }
    // 🏆 Game Over display logic completed
});
socket.on('message', (data) => showToast(data.msg));
socket.on('error', (data) => showToast("❌ " + data.msg));

socket.on('broadcast_meld_anim', (data) => {
    // 🔊 Play appropriate sound
    if (data.is_hu) {
        if (!gameState || !gameState.is_performance_mode) playHuSound();
        fireConfetti();
    } else {
        playChiSound();
    }

    // ✨ Visual Animation: Show the word and player name
    const fxLayer = document.getElementById('fx-layer');
    if (fxLayer) {
        const el = document.createElement('div');
        el.className = 'meld-anim-overlay' + (data.is_hu ? ' hu-style' : '');
        el.innerHTML = `
            <div class="meld-player-name">${data.player}</div>
            <div class="meld-word">${data.word || (data.is_hu ? 'HU!' : 'CHI!')}</div>
        `;
        
        fxLayer.appendChild(el);
        setTimeout(() => el.remove(), 2500);
    }
});



// Handle Drag End cleanup
document.addEventListener('dragend', () => {
    document.querySelectorAll('.tile').forEach(t => t.classList.remove('dragging-visual', 'dragging'));
});

// Global Safety Net for Pointer Events
document.addEventListener('pointerup', () => {
    activePointerId = null;
    if (isDraggingTile) {
        isDraggingTile = false;
        dragSourceIdx = null;
        document.querySelectorAll('.tile.dragging-visual').forEach(t => {
            t.classList.remove('dragging-visual');
            t.style.transform = "";
            t.style.zIndex = "";
        });
        if (typeof renderBoard === 'function') renderBoard();
    }
});


let hasAutoJoined = false;

function manualQuickJoin(r) {
    try {
        if (!r) return;
        console.log("Quick Join Integration for Room:", r);
        roomID = r;
        
        // 🚀 Integrate Join with Main Menu
        const menuHeader = document.querySelector('#menu-overlay h1');
        if (menuHeader) menuHeader.innerText = `JOIN ROOM: ${r}`;
        
        const hostBtn = document.querySelector('.menu-btn[onclick*="host"]');
        const singleBtn = document.querySelector('.menu-btn[onclick*="startSinglePlayer"]');
        
        if (hostBtn) {
            hostBtn.innerText = `🚀 JOIN GAME (ROOM ${r})`;
            hostBtn.onclick = confirmQuickJoin;
            hostBtn.style.background = 'var(--neon-green)';
            hostBtn.style.color = '#000';
        }
        
        if (singleBtn) {
            singleBtn.innerText = `🚪 RETURN TO MAIN MENU`;
            singleBtn.onclick = () => location.href = '/';
            singleBtn.style.background = 'rgba(255,255,255,0.05)';
            singleBtn.style.color = '#94a3b8';
        }

        window.pendingRoomID = r;
    } catch (e) {
        console.error("ManualQuickJoin Error:", e);
    }
}


function confirmQuickJoin() {
    const r = window.pendingRoomID;
    if (!r) return;

    username = "Player_" + Math.random().toString(36).substr(2, 4).toUpperCase();
    
    myRole = 'player';
    
    // Auto-enable mobile/controller mode
    document.body.classList.add('mobile-mode');
    document.body.classList.add('controller-mode');
    document.body.classList.remove('spectator-mode');
    
    // Transition
    const menu = document.getElementById('menu-overlay');
    if (menu) menu.classList.add('hidden');

    currentGameMode = 'multi';
    document.getElementById('chat-container')?.classList.remove('hidden');
    
    console.log("Emitting Join for:", username, "Room:", r);
    socket.emit('join', { username, room: r, mode: 'multi', role: 'player' });
    updateDynamicQR();
    hasAutoJoined = true;
}

function checkQuickJoin() {
    if (hasAutoJoined) return;
    const params = new URLSearchParams(window.location.search);
    const room = params.get('room');
    if (room) {
        manualQuickJoin(room);
    }
}

function joinRoom() {
    console.log("joinRoom called. Manual join UI is currently disabled.");
}

function switchTheme(t) {
    console.log("switchTheme called with:", t);
}




// 🚀 Initialization Wrapper
const init = () => {
    try {
        window.startSinglePlayer = startSinglePlayer;
        window.showJoin = showJoin;
        window.joinRoom = joinRoom;
        window.toggleRules = toggleRules;
        window.manualQuickJoin = manualQuickJoin;
        window.confirmQuickJoin = confirmQuickJoin;
        window.triggerStart = triggerStart;
        window.switchTheme = switchTheme;

        bindStartButtons();
        checkQuickJoin();
        
        console.log("Mahjong Game Logic Initialized Successfully.");
    } catch (e) {
        console.error("Initialization error:", e);
    }
};

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// Global listeners
socket?.on('connect', () => {
    if (typeof checkQuickJoin === 'function') checkQuickJoin();
});

// 🚀 Merged game_state logic into main handler above

// 🚀 Lightweight Timer Sync Listener
socket?.on('timer_update', (data) => {
    if (!gameState || !gameState.players) return;
    
    // Update local gameState with new timer values without full redraw
    data.players.forEach((pData, idx) => {
        if (gameState.players[idx]) {
            gameState.players[idx].turn_time = pData.turn_time;
            gameState.players[idx].bank_time = pData.bank_time;
        }
    });
    
    gameState.current_turn = data.current_turn;
    
    // Only update the floating timer and active turn class (minimal DOM work)
    updateTimersOnly();
});

function updateTimersOnly() {
    // 🚀 Fast path for updating only timers and turn indicators
    const positions = ['bottom', 'right', 'top', 'left'];
    const myIndex = getMyIndex();
    const effectiveMyIdx = (myIndex !== -1) ? myIndex : gameState.players.findIndex(p => p.name === username);

    for (let index = 0; index < 4; index++) {
        const player = gameState.players[index];
        if (!player) continue;

        let relIdx = (index - (effectiveMyIdx === -1 ? 0 : effectiveMyIdx) + 4) % 4;
        const pos = positions[relIdx];

        // Update active turn visual
        const nameEl = document.getElementById(`name-${pos}`);
        if (nameEl) {
            const isActive = (gameState.current_turn === index);
            if (isActive && !nameEl.classList.contains('active-turn')) {
                nameEl.classList.add('active-turn', 'active-turn-glow');
            } else if (!isActive && nameEl.classList.contains('active-turn')) {
                nameEl.classList.remove('active-turn', 'active-turn-glow');
            }
        }

        // Update floating timer
        const handEl = document.getElementById(`hand-${pos}`);
        if (handEl) {
            let timerEl = handEl.querySelector('.timer-floating');
            const isMyHand = (index === effectiveMyIdx);
            
            if (gameState.current_turn === index && (isMyHand || isSpectator)) {
                if (!timerEl) {
                    timerEl = document.createElement('div');
                    timerEl.className = 'timer-floating';
                    handEl.appendChild(timerEl);
                }
                const timeStr = Math.ceil(player.turn_time > 0 ? player.turn_time : player.bank_time);
                timerEl.innerHTML = `<div class="timer-val">${timeStr}</div>`;
                timerEl.className = `timer-floating ${player.turn_time <= 3 ? 'urgent' : ''}`;
            } else if (timerEl) {
                timerEl.remove();
            }
        }
    }
}






