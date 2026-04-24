import os
import json
import random
import socket
import re
from collections import Counter
from typing import List, Dict, Any, Optional
from flask import Flask, render_template, send_from_directory, request # type: ignore
from flask_socketio import SocketIO, join_room, leave_room # type: ignore
from google import genai # type: ignore

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'majan_secret!'
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable static file caching

# 💡 Auto-detect async mode: Use eventlet on Render (production), threading for local dev
def _detect_async_mode():
    try:
        import eventlet
        eventlet.monkey_patch()
        print("✅ Using eventlet async mode (production)")
        return 'eventlet'
    except ImportError:
        print("ℹ️ Using threading async mode (local dev)")
        return 'threading'

_async_mode = _detect_async_mode()
socketio = SocketIO(app, cors_allowed_origins="*", async_mode=_async_mode)

@app.after_request
def add_no_cache(response):
    """Force browser to never cache any file."""
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


games: dict[str, 'EnglishMahjongGame'] = {}
GLOBAL_DEBUG = False # 🚀 Set to False for Exhibition/Production to boost performance

def dprint(*args, **kwargs):
    if GLOBAL_DEBUG:
        print(*args, **kwargs)

# 🛡️ Secure API Key Loading
# ==========================================
# 🚀 Render/Cloud Priority: Check environment variable first
gemini_api_key = os.environ.get('GEMINI_API_KEY')

if not gemini_api_key:
    # 🏠 Local Fallback: Check local files
    api_key_path = 'gemini_key.txt'
    if not os.path.exists(api_key_path):
        api_key_path = r'c:\Users\otto1\Desktop\蝷曉?\big cili\gemini_key.txt'
    
    if os.path.exists(api_key_path):
        try:
            with open(api_key_path, 'r', encoding='utf-8') as f:
                gemini_api_key = f.read().strip()
        except Exception as e:
            print(f"Failed to read local Gemini key: {e}")

gemini_client = None
if gemini_api_key:
    try:
        gemini_client = genai.Client(api_key=gemini_api_key)
        print("✅ Gemini API configured successfully.")
    except Exception as e:
        print(f"Failed to configure Gemini: {e}")

# 🧠 Theme validation cache & Data
THEME_CACHE: Dict[str, bool] = {}
# ==========================================
# 📚 Load Dictionary
# ==========================================
WORDS = []
words_path = os.path.join('static', 'words.json')
if os.path.exists(words_path):
    with open(words_path, 'r', encoding='utf-8') as f:
        WORDS = json.load(f)

# 📈 AI Vocabulary Difficulty System
WORD_FREQUENCIES = []
WORD_RANK = {}
freq_path = os.path.join('static', 'word_frequencies.json')
if os.path.exists(freq_path):
    with open(freq_path, 'r', encoding='utf-8') as f:
        WORD_FREQUENCIES = json.load(f)
        WORD_RANK = {word.lower(): i for i, word in enumerate(WORD_FREQUENCIES)}

THEMES = []

def get_local_ip():
    try:
        # Try to get the IP used for external traffic
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        # Fallback to hostname-based detection
        try:
            return socket.gethostbyname(socket.gethostname())
        except:
            return "127.0.0.1"

LOCAL_IP = get_local_ip()
print(f" * Server running on LAN: http://{LOCAL_IP}:5001")


# ==========================================
# 🎲 Random Restriction System
# ==========================================
# 🎨 Exclude rare letters to increase game flow
COMMON_LETTERS = "ABCDEFGHIJKLMNOPRSTUVW" # Exclude Q, X, Z, J, Y

def generate_random_restriction():
    # 🛡️ GLOBAL REMOVAL: All categorical and structural restrictions are deleted.
    return {
        'display': 'FREE MODE',
        'rule': 'free'
    }



# ==========================================
# 🎮 Core Game Logic (EnglishMahjongGame)
# ==========================================
class EnglishMahjongGame:
    def __init__(self):
        self.TILE_DISTRIBUTION = {
            'A': 11, 'B': 2, 'C': 4, 'D': 6, 'E': 17, 'F': 3, 'G': 3, 'H': 8,
            'I': 9, 'J': 1, 'K': 1, 'L': 5, 'M': 3, 'N': 9, 'O': 10, 'P': 2,
            'Q': 1, 'R': 8, 'S': 8, 'T': 12, 'U': 4, 'V': 1, 'W': 3, 'X': 1,
            'Y': 3, 'Z': 1
        }
        self.deck: list[dict[str, Any]] = []
        self.round_word_index = {}
        self.round_word_index_by_len = {}
        self.restriction = None
        self.init_deck()
        self.game_started = False
        self.timer_active = False
        self.timer_paused = False
        self.players: list[dict[str, Any]] = [] 
        self.spectators: set[str] = set() 
        self.discard_piles = [[] for _ in range(4)] 
        self.last_discard = None
        self.current_turn = 0
        self.state = 'WAITING'
        self.demo_mode = False 
        self.ai_interval = 5.0 
        self.current_chi_options = {} # 🚀 Fix: Initialize to prevent crash in lobby

    def set_dictionary(self, dictionary: list[str]):
        self.dictionary = set(dictionary)
        self.word_index = {}
        self.word_index_by_len = {}
        for word in dictionary:
            word = word.lower()
            w_len = len(word)
            
            # --- Index by Length ---
            if w_len not in self.word_index_by_len:
                self.word_index_by_len[w_len] = []
            self.word_index_by_len[w_len].append(word)
            
            # --- Index by Character ---
            unique_chars = set(word)
            for char in unique_chars:
                if char not in self.word_index:
                    self.word_index[char] = {}
                if w_len not in self.word_index[char]:
                    self.word_index[char][w_len] = []
                self.word_index[char][w_len].append(word)


    def init_deck(self):
        self.deck = []
        for letter, count in self.TILE_DISTRIBUTION.items():
            for _ in range(count):
                self.deck.append({'type': 'letter', 'value': letter})
        random.shuffle(self.deck)

    def add_player(self, sid, name, vocab_limit=None):
        # 🔄 Reconnection mechanism: Update SID if player name already exists (and is NOT an AI)
        for p in self.players:
            if p.get('name') == name and not p.get('sid', '').startswith('ai_'):
                p['sid'] = sid
                dprint(f"DEBUG: [GAME] Player {name} reconnected with new sid: {sid}")
                return True

        if len(self.players) < 4:
            self.players.append({
                'sid': sid,
                'name': name,
                'hand': [],
                'melds': [], 
                'vocab_limit': vocab_limit or 999999,
                'bank_time': 60.0,
                'turn_time': 20.0
            })
            # Log player join
            dprint(f"DEBUG: [GAME] Player {name} joined.")
            return True
        return False

    def start_game(self):
        if len(self.players) < 2: return False
        self.init_deck()
        self.prune_dictionary_for_round()
        
        self.discard_piles = [[] for _ in range(len(self.players))]
        self.last_discard = None
        self.current_chi_options = {}
        
        for p in self.players:
            p['hand'] = []
            p['melds'] = []
            p['bank_time'] = 60.0
            p['turn_time'] = 20.0
            for _ in range(16):
                t = self.draw_tile()
                if t: p['hand'].append(t)
            
        self.game_started = True
        self.current_turn = random.randint(0, len(self.players) - 1)
        self.state = 'NORMAL'
        return True

    def prune_dictionary_for_round(self):
        """Pre-filter dictionary at round start to speed up lookups"""
        self.round_word_index = {}
        self.round_word_index_by_len = {}
        
        if not self.restriction:
            self.round_word_index = self.word_index
            self.round_word_index_by_len = self.word_index_by_len
            return

        # ⚡ Strategy: Iterate only once through the full index
        # We use characters as keys to build the round-specific index
        for char, lengths_dict in self.word_index.items():
            for w_len, words in lengths_dict.items():
                filtered = [w for w in words if self.validate_word(w, fast_check=True)]
                if filtered:
                    if char not in self.round_word_index: self.round_word_index[char] = {}
                    if w_len not in self.round_word_index[char]: self.round_word_index[char][w_len] = []
                    self.round_word_index[char][w_len].extend(filtered)
                    
                    if w_len not in self.round_word_index_by_len: self.round_word_index_by_len[w_len] = []
                    # We use a set here to avoid duplicates if a word is added for multiple characters
                    # (Wait, actually we can just use the unique words in word_index_by_len)

        # Build round_word_index_by_len properly from unique words
        for w_len, words in self.word_index_by_len.items():
            filtered = [w for w in words if self.validate_word(w, fast_check=True)]
            if filtered:
                self.round_word_index_by_len[w_len] = filtered

        count = sum(len(v) for v in self.round_word_index_by_len.values())
        dprint(f"DEBUG: [PRUNE] Round dictionary pruned to {count} words.")

    def draw_tile(self):
        return self.deck.pop(0) if self.deck else None

    def discard(self, player_index, tile_index):
        if self.current_turn != player_index: return False
        player = self.players[player_index]
        hand = player.get('hand', [])
        try: tile_index = int(tile_index)
        except: return False
        if tile_index < 0 or tile_index >= len(hand): return False
        tile = hand.pop(tile_index)
        self.last_discard = {'tile': tile, 'player_index': player_index}
        self.discard_piles[player_index].append(tile)
        return True

    def next_turn(self):
        self.current_turn = (self.current_turn + 1) % len(self.players)
        self.current_chi_options = {}
        dprint(f"DEBUG: [NEXT_TURN] Now Player {self.current_turn}'s turn. State: {self.state}")

        dprint(f"DEBUG: [NEXT_TURN] Now Player {self.current_turn}'s turn. State: {self.state}")

        # 🔍 Check ALL human players for chi opportunities
        last_t = self.last_discard.get('tile') if self.last_discard else None # type: ignore
        discarder_idx = self.last_discard.get('player_index') if self.last_discard else None # type: ignore
        found_chi = False
        
        dprint(f"DEBUG: [NEXT_TURN] current_turn={self.current_turn}, last_discard={self.last_discard}, last_t={last_t}")
        
        if last_t and discarder_idx is not None:
            # 🗄️ Standard Mahjong Rules: Only "Chi" from the LEFT player (the next player)
            check_idx = (int(discarder_idx) + 1) % len(self.players)
            check_p = self.players[check_idx]
            
            # 🚀 Calculate Chi options for the next player
            options = self.calculate_chi_options(check_idx, last_t)
            dprint(f"DEBUG: [NEXT_TURN] Checking Chi for LEFT player {check_idx} ({check_p.get('name')}): options={options}")
            
            # 🚀 NEXT-PLAYER HU CHECK:
            # For human players, enter WAITING_ACTION if:
            #   (a) they have Chi options, OR
            #   (b) their hand has 16 tiles (could be Hu with this discard)
            # For AI players, only enter WAITING_ACTION if they have Chi options.
            is_human_next = not check_p.get('sid', '').startswith('ai_')
            hand_size = len(check_p.get('hand', []))
            could_hu = is_human_next and (hand_size == 16)
            
            if options or could_hu:
                self.current_chi_options[check_idx] = options
                self.state = 'WAITING_ACTION'
                self.current_turn = check_idx
                found_chi = True
                dprint(f"DEBUG: [NEXT_TURN] Waiting for action from player {check_idx} (human={is_human_next}). chi_options={len(options)}")
        
        if not found_chi:
            # Normal: draw tile for the next player
            self.state = 'NORMAL'
            new_tile = self.draw_tile()
            if new_tile:
                self.players[self.current_turn]['hand'].append(new_tile)
                dprint(f"DEBUG: [NEXT_TURN] Player {self.current_turn} drew {new_tile.get('value')}. State=NORMAL")
            else:
                print("DEBUG: [NEXT_TURN] Deck empty! Game over.")
                socketio.emit('game_over', {'winner': 'Nobody (Draw)', 'melds': [], 'hand': []}, room=self.room_id)
                self.game_started = False
                if getattr(self, 'demo_mode', False):
                    socketio.start_background_task(schedule_demo_restart, self.room_id)
                return
        
        # ⏲️ Reset turn timer for the new acting player
        for p in self.players:
            p['turn_time'] = 20.0




    def skip_action(self, player_index):
        if getattr(self, 'state', 'NORMAL') == 'WAITING_ACTION' and self.current_turn == player_index:
            dprint(f"DEBUG: Player {player_index} ({self.players[player_index]['name']}) skipped action.")
            self.state = 'NORMAL'
            self.current_chi_options = {}
            # 🔑 KEY FIX: Clear last_discard BEFORE calling next_turn().
            # Without this, next_turn() sees the same discard and re-enters
            # WAITING_ACTION for the same player → infinite skip loop.
            self.last_discard = None
            # Draw a tile for the skipping player (it's now their draw turn)
            new_tile = self.draw_tile()
            if new_tile:
                self.players[player_index]['hand'].append(new_tile)
                dprint(f"DEBUG: [SKIP] Player {player_index} drew tile after skipping: {new_tile.get('value')}")
            # Reset turn timers
            for p in self.players:
                p['turn_time'] = 20.0
            return True

        return False

    def validate_word(self, word, fast_check=False):
        # 🛡️ GLOBAL REMOVAL: Always return True to allow any word in dictionary
        return True

    def calculate_chi_options(self, player_index, last_tile):
        player = self.players[player_index]
        hand_letters = [t['value'].lower() for t in player['hand'] if t['type'] == 'letter']
        target_char = last_tile.get('value', '').lower()
        
        hand_counts = {}
        for c in hand_letters:
            hand_counts[c] = hand_counts.get(c, 0) + 1
            
        options = []
        max_len = len(hand_letters) + 1
        
        dprint(f"DEBUG: [CALC_CHI] player={player_index} hand={hand_letters} target='{target_char}' word_index_has_target={target_char in self.word_index}")
        
        # Use full index (no pruning)
        if target_char in self.word_index:
            char_dict = self.word_index[target_char]
            for w_len in range(2, max_len + 1):
                if w_len in char_dict:
                    for word in char_dict[w_len]: 
                        temp_counts = hand_counts.copy()
                        temp_counts[target_char] = temp_counts.get(target_char, 0) + 1
                        
                        possible = True
                        for char in word:
                            if temp_counts.get(char, 0) > 0:
                                temp_counts[char] -= 1
                            else:
                                possible = False
                                break
                        
                        if possible:
                            # 🚀 在大範圍搜尋時使用 fast_check，避免卡死
                            if self.validate_word(word, fast_check=True):
                                options.append(str(word).upper())
                            
        # 🚀 Sort by frequency before capping so common words always appear
        result = list(set(options))
        result.sort(key=lambda w: WORD_RANK.get(w.lower(), 999999))
        result = result[:50]
        dprint(f"DEBUG: [CALC_CHI] options found: {len(result)}")
        return result


    def get_chi_options(self, player_index):
        return self.current_chi_options.get(player_index, [])

    def perform_chi(self, player_index, word):
        if not word or not self.last_discard: return False, "No word or no discard."
        last_tile = self.last_discard.get('tile', {}) # type: ignore
        if not isinstance(last_tile, dict) or last_tile.get('type') != 'letter': return False, "Invalid discard tile."
        
        word = str(word).lower()
        if word not in self.dictionary: return False, f"'{word.upper()}' is not in the dictionary."
        
        # 🛡️ Final Restriction Check
        if not self.validate_word(word):
            dprint(f"DEBUG: [CHI_DENIED] Word '{word}' doesn't match restriction.")
            return False, f"'{word.upper()}' does not match the current rule."
            
        last_char = last_tile.get('value', '').lower()
        if last_char not in word: return False, f"The word must contain the discarded tile '{last_char.upper()}'!"
        
        player = self.players[player_index]
        hand = player.get('hand', [])
        hand_letters = [t.get('value', '').lower() for t in hand if isinstance(t, dict) and t.get('type') == 'letter']
        
        word_letters = list(word)
        try: word_letters.remove(last_char)
        except ValueError: return False, f"Missing discarded tile '{last_char.upper()}' in logic."
            
        h_counts = Counter(hand_letters)
        w_counts = Counter(word_letters)
        
        for char, count in w_counts.items():
            if h_counts[char] < count: return False, f"You don't have enough '{char.upper()}' tiles in your hand!"
        
        for char in word_letters:
            for i, t in enumerate(hand):
                if isinstance(t, dict) and t.get('type') == 'letter' and t.get('value', '').lower() == char:
                    hand.pop(i)
                    break
        
        player.setdefault('melds', []).append(word.upper())
        
        target_p_idx = self.last_discard.get('player_index') # type: ignore
        if target_p_idx is not None and target_p_idx < len(self.discard_piles) and self.discard_piles[target_p_idx]:
            self.discard_piles[target_p_idx].pop() 
            
        self.last_discard = None
        self.current_turn = player_index 
        self.state = 'NORMAL' 
        self.current_chi_options = {}
        return True

    def verify_manual_hu(self, player_index, words_str):
        player = self.players[player_index]
        hand = player.get('hand', [])
        
        # 🚀 Fix: Extract words from input
        words = re.findall(r'[a-zA-Z]+', str(words_str).lower())
        
        # 🛡️ Loophole Fix: If player has NO tiles in hand, they MUST have melds to win.
        # This handles the "pure meld" win case.
        if not words:
            if not hand and player.get('melds'):
                return True, []
            return False, "No English words found in hand input."

        letters = [t.get('value', '').lower() for t in hand if isinstance(t, dict) and t.get('type') == 'letter']
        items = [t for t in hand if isinstance(t, dict) and t.get('type') == 'item']
        wildcard_count = len(items)

        is_discard_hu = False
        if getattr(self, 'state', 'NORMAL') == 'WAITING_ACTION' and self.last_discard:
            if self.last_discard.get('player_index') != player_index: # type: ignore
                tile = self.last_discard.get('tile', {}) # type: ignore
                if isinstance(tile, dict):
                    if tile.get('type') == 'letter':
                        letters.append(tile.get('value', '').lower())
                        is_discard_hu = True
                    elif tile.get('type') == 'item':
                        wildcard_count += 1
                        is_discard_hu = True

        hand_counts: Counter[str] = Counter(letters)
        claimed_counts: Counter[str] = Counter()

        for w in words:
            if w not in self.dictionary:
                return False, f"'{w.upper()}' is not in the dictionary."
            if not self.validate_word(w):
                return False, f"'{w.upper()}' does not match the current restriction ({self.restriction.get('display', '??')})."
            claimed_counts.update(w)

        for char, count in claimed_counts.items():
            if hand_counts[char] < count:
                return False, f"Insufficient letters to form '{char.upper()}'."
        
        total_claimed_len = sum(claimed_counts.values())
        total_hand_len = len(letters)
        
        if total_claimed_len != total_hand_len:
            return False, "You must use all letters in your hand to win."

        if is_discard_hu:
            target_p = self.last_discard.get('player_index')
            if target_p is not None and self.discard_piles[target_p]:
                self.discard_piles[target_p].pop()
            self.last_discard = None

        return True, words

    def AI_find_hu_partition(self, letters, items_count, current_melds=None, memo=None, vocab_limit=999999, is_nightmare=False, known_words=None):
        """
        Recursively find if the hand can be fully decomposed into words matching the restriction.
        Optimization: Use "Target character search" (Exact Cover Branch) to reduce search space.
        """
        if memo is None: memo = {}
        
        # 0. Base Case: Hand empty
        if not letters and items_count == 0:
            return current_melds or []
        
        # 1. Check Cache (Simplify hand state to string)
        hand_key = "".join(sorted(letters)) + f":{items_count}"
        if hand_key in memo: return memo[hand_key]
        
        target_len = len(letters)
        if target_len < 2: 
            memo[hand_key] = None
            return None 

        # 2. Core Logic: If hand has letters, we MUST use one of them (e.g., the first one)
        if letters:
            target_char = letters[0]
            
            # Find all words containing this letter from dict cache
            if target_char not in self.round_word_index:
                memo[hand_key] = None
                return None
                
            char_dict = self.round_word_index[target_char]
            
            # Try from longest words first (Greedy)
            lengths = sorted(char_dict.keys(), reverse=True)
            for length in lengths:
                if length > target_len: continue
                
                candidates = list(char_dict[length])
                # 🧠 AI Difficulty Filter: Only use words AI "knows"
                if known_words is not None:
                    candidates = [w for w in candidates if w.lower() in known_words]
                else:
                    candidates = [w for w in candidates if WORD_RANK.get(w.lower(), 999999) < vocab_limit]
                
                # 🌙 Nightmare Mode Extra Filter: Exclude proper nouns
                # (Already filtered globally from dictionary)
                
                random.shuffle(candidates)
                
                for word in candidates:
                    if not self.validate_word(word, fast_check=True): continue
                    
                    # Check if letters are enough (considering wildcards)
                    word_counts = Counter(word)
                    hand_counts = Counter(letters)
                    needed_wildcards = 0
                    possible = True
                    
                    for char, count in word_counts.items():
                        if hand_counts[char] < count:
                            needed_wildcards += (count - hand_counts[char])
                        if needed_wildcards > items_count:
                            possible = False
                            break
                    
                    if possible:
                        # Deduct used tiles, calc remaining hand
                        new_hand = []
                        temp_counts = hand_counts.copy()
                        for char, count in word_counts.items():
                            used_from_hand = min(count, temp_counts[char])
                            temp_counts[char] -= used_from_hand
                        
                        for char, count in temp_counts.items():
                            new_hand.extend([char] * count)
                            
                        # Recursively check remaining
                        res = self.AI_find_hu_partition(new_hand, items_count - needed_wildcards, (current_melds or []) + [word.upper()], memo, vocab_limit=vocab_limit)
                        if res is not None:
                            memo[hand_key] = res
                            return res
        else:
            # Only wildcards left (extremely rare)
            # Try any word matching restriction from length 2 to target_len
            for length in range(min(10, target_len), 1, -1):
                if length not in self.round_word_index_by_len: continue
                
                candidates = list(self.round_word_index_by_len[length])
                if known_words is not None:
                    candidates = [w for w in candidates if w.lower() in known_words]
                else:
                    candidates = [w for w in candidates if WORD_RANK.get(w.lower(), 999999) < vocab_limit]
                random.shuffle(candidates)
                for word in candidates:
                    if self.validate_word(word, fast_check=True):
                        res = self.AI_find_hu_partition([], items_count - length, (current_melds or []) + [word.upper()], memo, vocab_limit=vocab_limit)
                        if res is not None:
                            memo[hand_key] = res
                            return res

        memo[hand_key] = None
        return None

 

    def register_wrong_move(self, player_index):
        self.players[player_index]['penalty_turns'] = 1


# ==========================================
# 🌐 Flask Routes & SocketIO Events
# ==========================================
sid_to_room = {}  # 🚀 Added global mapping for spectator/player tracking

def find_game_by_sid(sid):
    room_id = sid_to_room.get(sid)
    return games.get(room_id) if room_id else None

@app.route('/')
def index():
    return render_template('index.html', local_ip=LOCAL_IP)

@app.route('/<path:path>')
def static_proxy(path):
    return send_from_directory('static', path)

@socketio.on('join')
def on_join(data=None):
    data = data or {}
    room_id = str(data.get('room', 'default'))
    username = str(data.get('username', 'Anonymous'))
    mode = str(data.get('mode', 'multi'))
    difficulty = data.get('difficulty', 'normal') 
    role = data.get('role', 'player') # 🚀 Fix: Define missing role variable
    
    join_room(room_id)
    if room_id not in games:
        games[room_id] = EnglishMahjongGame()
        games[room_id].set_dictionary(WORDS)
        games[room_id].room_id = room_id
    
    game = games[room_id]
    sid_to_room[request.sid] = room_id  # 🚀 Always register SID to room
    
    if role == 'spectator':
        # 📺 Marked as spectator, not added to players list but SID recorded for sync
        game.spectators.add(request.sid)
        socketio.emit('message', {'msg': 'Host Connected'}, room=room_id)
        broadcast_game_state(game)
        return

    if game.add_player(request.sid, username):
        if mode == 'single':
            # Create AI players with dynamic percentage-based difficulty
            # Easy: 0.05%, Normal: 0.1%, Hard: 0.15%, Nightmare: 0.2%
            total_words = len(WORDS)
            limit_map = {
                'easy': max(1, int(total_words * 0.00025)),      
                'normal': max(1, int(total_words * 0.00050)),    
                'hard': max(1, int(total_words * 0.00075)),      
                'nightmare': max(1, int(total_words * 0.00100))  
            }
            vocab_limit = limit_map.get(difficulty, limit_map['normal'])
            
            for i in range(1, 4):
                game.players.append({
                    'name': f"AI {['Right', 'Top', 'Left'][i-1]}", 
                    'sid': f"ai_{i}", 
                    'hand': [], 
                    'melds': [], 
                    'items': [],  # 🚀 Added missing items list
                    'hand_size': 0, 
                    'wrong_moves': 0,
                    'protected_turns': 0,
                    'penalty_turns': 0,
                    'difficulty': difficulty,
                    'vocab_limit': vocab_limit,
                    'bank_time': 60.0,
                    'turn_time': 20.0
                })
            # 🎡 Autostart single-player immediately as requested by user
            initialize_game_start(game)
            return
        else:
            # 🌐 Multiplayer Logic
            socketio.emit('message', {'msg': f'{username} joined the room.'}, room=room_id)
        
        # 📢 Always broadcast state after someone joins to update player counts
        broadcast_game_state(game)
        
        # 🚀 Auto-start: Launch immediately when 4 players are gathered
        if len(game.players) >= 4:
            print(f"DEBUG: [LOBBY] Room {room_id} is full (4 players). Auto-starting...")
            initialize_game_start(game)
    else:
        socketio.emit('error', {'msg': 'Room is full.'}, room=request.sid)

@socketio.on('add_ai')
def on_add_ai(data=None):
    game = find_game_by_sid(request.sid)
    if not game: return
    
    num_players = len(game.players)
    if num_players < 4:
        ai_names = ["AI Right", "AI Top", "AI Left"]
        idx = num_players
        game.players.append({
            'name': ai_names[idx-1] if idx-1 < len(ai_names) else f"AI {idx}", 
            'sid': f"ai_multi_{idx}", 
            'hand': [], 
            'melds': [], 
            'hand_size': 0, 
            'wrong_moves': 0,
            'protected_turns': 0,
            'penalty_turns': 0,
            'difficulty': 'normal',
            'vocab_limit': int(len(WORDS) * 0.0005), # 🚀 Sync with halved 0.05% for normal
            'bank_time': 60.0,
            'turn_time': 20.0
        })
        print(f"DEBUG: [LOBBY] Added AI to room {game.room_id}. Total: {len(game.players)}")
        broadcast_game_state(game)
    else:
        socketio.emit('error', {'msg': 'Room is already full.'}, room=request.sid)

def initialize_game_start(game):
    """🧠 Core logic to fully initialize and start a game match."""
    if not game: return False
    
    # 🚀 Auto-fill: If less than 4 players, generate AI to fill spots
    num_players = len(game.players)
    if num_players < 4:
        print(f"DEBUG: [START] Filling {4 - num_players} seats with AI...")
        ai_names = ["AI Right", "AI Top", "AI Left"]
        for i in range(num_players, 4):
            game.players.append({
                'name': ai_names[i-1] if i-1 < len(ai_names) else f"AI {i}", 
                'sid': f"ai_multi_{i}", 
                'hand': [], 
                'melds': [], 
                'hand_size': 0, 
                'wrong_moves': 0, 
                'protected_turns': 0, 
                'penalty_turns': 0,
                'difficulty': 'normal',
                'vocab_limit': int(len(WORDS) * 0.0005), # 🚀 Sync with halved 0.05% for normal
                'bank_time': 60.0,
                'turn_time': 20.0
            })

    # Select game restriction
    if getattr(game, 'game_started', False):
        print(f"DEBUG: [START] Game in room {game.room_id} already started. Skipping initialization.")
        return False

    restriction = generate_random_restriction()
    if game.start_game():
        game.timer_paused = True # Pause timer for wheel animation
        if not game.timer_active:
            game.timer_active = True
            socketio.start_background_task(run_game_timer_loop, game.room_id)
        
        socketio.emit('start_restriction_wheel', restriction, room=game.room_id)
        socketio.emit('message', {'msg': f'Game Started! Rule: {restriction["display"]}'}, room=game.room_id)
        broadcast_game_state(game) 
        
        # Start timer and starting player draw instantly
        def instant_start():
            start_p = game.current_turn
            if len(game.players[start_p]['hand']) == 16:
                t = game.draw_tile()
                if t:
                    game.players[start_p]['hand'].append(t)
                    socketio.emit('message', {'msg': f'{game.players[start_p]["name"]} drew the first tile.'}, room=game.room_id)
            game.timer_paused = False
            broadcast_game_state(game)
            
        socketio.start_background_task(instant_start)
        trigger_turn(game)
        return True
    return False

@socketio.on('start_game')
def on_start(data=None):
    request_room = data.get('room') if data else None
    print(f"DEBUG: [START] Received start_game from {request.sid} (Payload Room: {request_room})")
    
    # 🚀 Robust Lookup: Try SID first, then payload room ID
    game = find_game_by_sid(request.sid)
    if not game and request_room:
        game = games.get(str(request_room))
        if game:
            print(f"DEBUG: [START] Recovered game via payload room {request_room}")
            # Re-register SID to room for future stability
            sid_to_room[request.sid] = str(request_room)

    if game:
        if getattr(game, 'game_started', False):
            print(f"DEBUG: [START] Game {game.room_id} already running.")
            broadcast_game_state(game)
            return

        print(f"DEBUG: [START] Game found for room {game.room_id}. Initializing...")
        initialize_game_start(game)
    else:
        print(f"DEBUG: [START] CRITICAL - No game found for sid {request.sid} or room {request_room}")
        socketio.emit('error', {'msg': 'Failed to start game: Room not found. Please try refreshing.'}, room=request.sid)

@socketio.on('start_demo_mode')
def on_start_demo(data=None):
    """🤖 Performance Mode: 4 AI players play automatically in a loop."""
    room_id = str(data.get('room', 'demo_room')) if data else 'demo_room'
    join_room(room_id)
    
    if room_id not in games:
        games[room_id] = EnglishMahjongGame()
        games[room_id].set_dictionary(WORDS)
        games[room_id].room_id = room_id
    
    game = games[room_id]
    game.demo_mode = True
    sid_to_room[request.sid] = room_id
    
    # Clear existing players and add 4 AI
    game.players = []
    ai_names = ["AI East", "AI South", "AI West", "AI North"]
    total_words = len(WORDS)
    vocab_limit = int(total_words * 0.00025) # Halved skill for Demo

    for i in range(4):
        game.players.append({
            'name': ai_names[i], 
            'sid': f"ai_demo_{room_id}_{i}", 
            'hand': [], 
            'melds': [], 
            'items': [], 
            'hand_size': 0, 
            'wrong_moves': 0,
            'protected_turns': 0, 
            'penalty_turns': 0,
            'difficulty': 'easy', # Set to easy to make AI 'dumber'
            'vocab_limit': vocab_limit, 
            'bank_time': 60.0,
            'turn_time': 20.0
        })

    print(f"DEBUG: [DEMO] Performance mode initialized in room {room_id}. Autostarting...")
    game.is_performance_mode = True
    
    game.spectators.add(request.sid)
    initialize_game_start(game)



# Discard Action Handler
@socketio.on('discard')
@socketio.on('play_card')
def on_discard(data=None):
    game = find_game_by_sid(request.sid)
    if not game: return
    
    player_index = next((i for i, p in enumerate(game.players) if p.get('sid') == request.sid), None)
    if player_index is None: return

    # 🛡️ During WAITING_ACTION, the player must use CHI/SKIP/HU buttons.
    # Attempting to discard during this phase is invalid; reject gracefully
    # without force-skipping their turn.
    if getattr(game, 'state', 'NORMAL') == 'WAITING_ACTION':
        if game.current_turn == player_index:
            socketio.emit('error', {'msg': "⚠️ Use CHI, HU, or SKIP first!"}, room=request.sid)
            socketio.emit('game_state', get_game_state(game, request.sid), room=request.sid)
        return

    if game.current_turn != player_index:
        socketio.emit('error', {'msg': "❌ Not your turn!"}, room=request.sid)
        return

    tile_index = None
    if isinstance(data, dict):
        for key in ['tile_index', 'tileIndex', 'index', 'card_index']:
            val = data.get(key)
            if val is not None:
                tile_index = val
                break
    else:
        try: tile_index = int(data)
        except: pass

    if tile_index is not None:
        success = game.discard(player_index, tile_index)
        if success:
            game.next_turn()
            broadcast_game_state(game)  # broadcast AFTER next_turn so chi_options + WAITING_ACTION is included
            trigger_turn(game)
        else:
            socketio.emit('error', {'msg': f'Cannot play this card! (Index: {tile_index})'}, room=request.sid)
            socketio.emit('game_state', get_game_state(game, request.sid), room=request.sid)

def schedule_demo_restart(room_id):
    """🤖 Auto-restart for Performance Mode after a delay."""
    socketio.sleep(10) # Wait 10s to show results
    game = games.get(room_id)
    if game and getattr(game, 'demo_mode', False):
        print(f"DEBUG: [DEMO] Auto-restarting game in room {room_id}...")
        initialize_game_start(game)


@socketio.on('action_chi')
def on_chi(data=None):
    data = data or {}
    word = str(data.get('word', ''))
    game = find_game_by_sid(request.sid)
    if game:
        player_index = next((i for i, p in enumerate(game.players) if p.get('sid') == request.sid), None)
        if player_index is not None:
            res = game.perform_chi(player_index, word)
            success, err_msg = res if isinstance(res, tuple) else (res, "Unknown validation error")
            
            if success:
                player = game.players[player_index]
                player_name = player.get('name')
                
                # 🚀 Foolproof Mechanism: If hand is empty after Chi, trigger HU automatically
                if len(player.get('hand', [])) == 0:
                    winning_words = player.get('melds', [])
                    game.game_started = False
                    socketio.emit('broadcast_meld_anim', {'word': " ".join(winning_words), 'player': player_name, 'is_hu': True}, room=game.room_id)
                    socketio.emit('game_over', {'winner': player_name, 'melds': winning_words, 'hand': []}, room=game.room_id)
                    socketio.emit('message', {'msg': f'🎉 {player_name} wins with automatic HU after CHI!'}, room=game.room_id)
                    if getattr(game, 'demo_mode', False):
                        socketio.start_background_task(schedule_demo_restart, game.room_id)
                else:
                    socketio.emit('broadcast_meld_anim', {'word': word.upper(), 'player': player_name, 'is_hu': False}, room=game.room_id)
                    broadcast_game_state(game)
                    trigger_turn(game)
            else:
                game.register_wrong_move(player_index)
                game.skip_action(player_index)
                socketio.emit('error', {'msg': f'CHI Failed ({word.upper()}): {err_msg} Turn skipped!'}, room=request.sid) # type: ignore
                broadcast_game_state(game)
                trigger_turn(game)

@socketio.on('action_skip')
def on_skip(data=None):
    game = find_game_by_sid(request.sid)
    if game:
        player_index = next((i for i, p in enumerate(game.players) if p.get('sid') == request.sid), None)
        if player_index is not None:
            if game.skip_action(player_index):
                broadcast_game_state(game)
                trigger_turn(game)

@socketio.on('action_hu')
def on_hu(data=None):
    data = data or {}
    words_str = str(data.get('words', ''))
    
    game = find_game_by_sid(request.sid)
    if game:
        player_index = next((i for i, p in enumerate(game.players) if p.get('sid') == request.sid), None)
        if player_index is not None:
            words = re.findall(r'[a-zA-Z]+', words_str.lower())
            
            # Verify all words against restriction
            invalid_words = [w.upper() for w in words if not game.validate_word(w)]
            if invalid_words:
                game.register_wrong_move(player_index)
                res_display = game.restriction.get('display', '??') if game.restriction else '??'
                socketio.emit('error', {'msg': f"Words {invalid_words} do not match the current rule ({res_display})! Penalized."}, room=request.sid)
                broadcast_game_state(game)
                return


            res = game.verify_manual_hu(player_index, words_str)
            success, result_data = res if isinstance(res, tuple) else (res, [])

            if success:
                player = game.players[player_index]
                winning_words = player.get('melds', []) + [w.upper() for w in result_data]
                
                # 🚀 FIX: Mark game as ended so the timer loop stops
                game.game_started = False
                socketio.emit('broadcast_meld_anim', {'word': " ".join(winning_words), 'player': player.get('name'), 'is_hu': True}, room=game.room_id)
                socketio.emit('game_over', {'winner': player.get('name'), 'melds': winning_words, 'hand': []}, room=game.room_id)
                socketio.emit('message', {'msg': f'{player.get("name")} HAS WON (HU)!'}, room=game.room_id)
                
                if getattr(game, 'demo_mode', False):
                    socketio.start_background_task(schedule_demo_restart, game.room_id)
            else:
                game.register_wrong_move(player_index)
                err_msg = result_data if isinstance(result_data, str) else "Invalid Hu!"
                socketio.emit('error', {'msg': f'Wrong Hu! {err_msg} Penalized (Turn Skipped!).'}, room=request.sid)
                
                # 🚀 Enforce TURN SKIP: Advance turn ONLY if it's the player's own draw turn
                # If they failed a Ron (on discard), they just lose the chance to Hu, but the turn continues normally
                if getattr(game, 'state', 'NORMAL') != 'WAITING_ACTION':
                    game.next_turn()
                else:
                    # If it was WAITING_ACTION, simply force a skip for the current player
                    game.skip_action(player_index)
                
                broadcast_game_state(game)
                trigger_turn(game)

# ==========================================
# 🤖 AI Logic & Anti-Lock (Background task version)
# ==========================================
def trigger_turn(game):
    """Turn Progression Scheduler"""
    if not getattr(game, 'game_started', False): return
    
    current_player = game.players[game.current_turn]
    dprint(f"DEBUG: [TRIGGER] Turn={game.current_turn}, Player={current_player.get('name')}, State={game.state}")
    
    # If waiting for human chi action, broadcast the chi state immediately
    if game.state == 'WAITING_ACTION' and not current_player.get('sid', '').startswith('ai_'):
        broadcast_game_state(game)
        return  # Human must act, don't trigger AI
    
    # Update current turn info to all clients
    socketio.emit('turn_update', {
        'current_turn': game.current_turn,
        'player_sid': current_player.get('sid', ''),
        'state': getattr(game, 'state', 'NORMAL')
    }, room=game.room_id)
    
    # 🤖 Automated AI Flow
    if current_player.get('sid', '').startswith('ai_'):
        dprint(f"DEBUG: [TRIGGER] Starting AI task for Player {game.current_turn} (SID: {current_player.get('sid')})")
        socketio.start_background_task(process_ai_action, game, game.current_turn)
        dprint(f"DEBUG: [TRIGGER] Task started for Player {game.current_turn}")
    else:
        dprint(f"DEBUG: [TRIGGER] Waiting for Human Player {game.current_turn} (SID: {current_player.get('sid')})")

def process_ai_action(game, ai_index):
    """
    🧠 AI Thinking Logic:
    1. Judge Hu (Winning) first
    2. If WAITING_ACTION (Chi), decide whether to Chi
    3. If NORMAL state, decide whether to use items, then discard a card
    """
    try:
        # Base AI thinking delay
        player = game.players[ai_index]
        difficulty = player.get('difficulty', 'normal')
        
        # 🚀 Use custom interval if set, otherwise fallback to difficulty-based delay
        delay = getattr(game, 'ai_interval', 5.0)
        socketio.sleep(delay)
        
        if not getattr(game, 'game_started', False): return
        if game.current_turn != ai_index: return
        
        player = game.players[ai_index]
        if not player.get('hand'):
            dprint(f"DEBUG: [AI_ERROR] Player {ai_index} has no hand! Skipping turn.")
            game.next_turn()
            broadcast_game_state(game)
            trigger_turn(game)
            return
        difficulty = player.get('difficulty', 'normal')
        
        # 🧠 Consistent Vocabulary Limit across ALL modes based on difficulty (0.05% - 0.2% of the FULL dictionary)
        total_words_count = len(WORDS)
        limit_map = {
            'easy': max(1, int(total_words_count * 0.00025)),      
            'normal': max(1, int(total_words_count * 0.00050)),    
            'hard': max(1, int(total_words_count * 0.00075)),      
            'nightmare': max(1, int(total_words_count * 0.00100))  
        }
        vocab_limit = limit_map.get(difficulty, limit_map['normal'])
        
        # 🎲 Build AI known words by randomly sampling from the FULL dictionary every time it acts
        # This implements the user's "Random Draw" (Option B) logic.
        try:
            ai_known_words = set(random.sample(WORDS, vocab_limit))
        except ValueError:
            # Fallback if vocab_limit is somehow larger than WORDS
            ai_known_words = set(WORDS)

        hand = player.get('hand', [])
        
        # Define available letter indices (pre-defined to prevent NameError)
        letter_indices = [i for i, t in enumerate(hand) if isinstance(t, dict) and t.get('type') == 'letter']
        
        # 0. AI Auto-Hu detection (Win priority)
        hand_letters = [t.get('value', '').lower() for t in player.get('hand', []) if isinstance(t, dict) and t.get('type') == 'letter']
        hand_items_count = len([t for t in player.get('hand', []) if isinstance(t, dict) and t.get('type') == 'item'])
        
        # 🛡️ Check for Hu (Winning) on another player's discard
        is_waiting_chi = (getattr(game, 'state', 'NORMAL') == 'WAITING_ACTION' and game.current_turn == ai_index)
        if is_waiting_chi and game.last_discard and game.last_discard.get('player_index') != ai_index:
            tile = game.last_discard.get('tile', {})
            if tile.get('type') == 'letter':
                hand_letters.append(tile.get('value', '').lower())
        
        # 🧪 Execute Hu partition analysis
        is_nightmare = (player.get('difficulty') == 'nightmare')
        hu_set = game.AI_find_hu_partition(hand_letters, 0, vocab_limit=vocab_limit, is_nightmare=is_nightmare, known_words=ai_known_words)
        if hu_set:
            winning_words = player.get('melds', []) + hu_set
            
            # 🚀 If Hu on discard, remove from discard pile
            if is_waiting_chi and game.last_discard:
                target_p_idx = game.last_discard.get('player_index')
                if target_p_idx is not None and game.discard_piles[target_p_idx]:
                    game.discard_piles[target_p_idx].pop()
                game.last_discard = None

            socketio.emit('broadcast_meld_anim', {'word': " ".join(winning_words), 'player': player.get('name', 'AI'), 'is_hu': True}, room=game.room_id)
            socketio.emit('game_over', {'winner': player.get('name', 'AI'), 'melds': winning_words, 'hand': []}, room=game.room_id)
            socketio.emit('message', {'msg': f'🎉 {player.get("name", "AI")} HAS WON (HU)!'}, room=game.room_id)
            game.game_started = False
            if getattr(game, 'demo_mode', False):
                socketio.start_background_task(schedule_demo_restart, game.room_id)
            return

        # 1. Handle WAITING_ACTION (Chi Decision)
        if getattr(game, 'state', 'NORMAL') == 'WAITING_ACTION':
            options = game.get_chi_options(ai_index)
            
            # 🎲 Difficulty determines whether to Chi (Action probability halved)
            chi_skip_prob = {'easy': 0.85, 'normal': 0.65, 'hard': 0.55, 'nightmare': 0.525}.get(difficulty, 0.65)
            should_chi = random.random() > chi_skip_prob
            
            if options and should_chi:
                # 🤖 AI intelligently chooses words matching restriction (using fast_check to avoid deep thinking)
                is_nightmare = (player.get('difficulty') == 'nightmare')
                valid_options = [w for w in options if game.validate_word(w, fast_check=True) and (w.lower() in ai_known_words)]
                
                # 🌙 Nightmare Mode Filter: Exclude proper nouns
                # (Already filtered globally from dictionary)
                
                if valid_options:
                    # 🧠 Strategy based on difficulty
                    strategy = {'easy': 'short', 'normal': 'random', 'hard': 'long', 'nightmare': 'long'}.get(difficulty, 'random')
                    if strategy == 'long':
                        chosen_word = max(valid_options, key=len)
                    elif strategy == 'short':
                        chosen_word = min(valid_options, key=len)
                    else:
                        chosen_word = random.choice(valid_options)
                        
                    if game.perform_chi(ai_index, chosen_word):
                        socketio.emit('broadcast_meld_anim', {'word': str(chosen_word).upper(), 'player': player.get('name', 'AI'), 'is_hu': False}, room=game.room_id)
                        broadcast_game_state(game)
                        trigger_turn(game)
                        return
                
            dprint(f"DEBUG: [AI_SKIP] Player {ai_index} ({player.get('name')}) skipping.")
            game.skip_action(ai_index)
            broadcast_game_state(game)
            trigger_turn(game)
            return

        # 2. Handle NORMAL (Items and Play)
        if getattr(game, 'state', 'NORMAL') == 'NORMAL':

            
            if not player.get('hand'):
                dprint(f"DEBUG: [AI_ERROR] Player {ai_index} has no hand! Advancing.")
                game.next_turn()
                broadcast_game_state(game)
                trigger_turn(game)
                return

            # AI Discard
            if not letter_indices:
                tile_idx = 0
            else:
                if difficulty in ['hard', 'nightmare']:
                    # 🧠 High Difficulty AI: Prioritize discarding rare/hard letters
                    counts = Counter([str(t.get('value', '')) for t in hand if isinstance(t, dict) and t.get('type') == 'letter'])
                    least_common = counts.most_common()[-1][0] if counts else None
                    
                    rare_letters = "QXZJKV" 
                    hand_rare = [i for i in letter_indices if hand[i].get('value', '') in rare_letters]
                    if hand_rare:
                        tile_idx = random.choice(hand_rare)
                    else:
                        tile_idx = next((i for i, t in enumerate(hand) if isinstance(t, dict) and t.get('type') == 'letter' and t.get('value') == least_common), random.choice(letter_indices))
                else:
                    # 🎮 Low Difficulty AI: Hesitant to discard letters
                    rare_letters = "QXZJKV"
                    common_indices = [i for i in letter_indices if hand[i].get('value', '') not in rare_letters]
                    if common_indices and random.random() < 0.35:
                        tile_idx = random.choice(common_indices)
                    else:
                        tile_idx = random.choice(letter_indices)

            tile_val = str(hand[tile_idx].get('value', '?'))
            dprint(f"DEBUG: [AI_DISCARD] Player {ai_index} ({difficulty}) discarding index {tile_idx} ({tile_val})")
            if game.discard(ai_index, tile_idx):
                socketio.emit('message', {'msg': f'🤖 {player.get("name", "AI")} discarded {tile_val}'}, room=game.room_id)
                game.next_turn()
                broadcast_game_state(game)
                trigger_turn(game)
            else:
                game.next_turn()
                broadcast_game_state(game)
                trigger_turn(game)

    except Exception as e:
        print(f"CRITICAL: [AI_TASK_ERROR] {e}")
        import traceback
        traceback.print_exc()
        try:
            game.state = 'NORMAL'
            game.next_turn()
            broadcast_game_state(game)
            trigger_turn(game)
        except: pass

# ==========================================
# 📊 Game State & Broadcasting
# ==========================================

def get_game_state(game, sid, include_hands=None):
    # 📺 Determine if requester is a real spectator (not in players list)
    # 🚀 SECURITY FIX: "PUBLIC_VIEW" is NOT a spectator, it's the room-wide broadcast ID
    is_real_player = any(p.get('sid') == sid for p in game.players)
    is_spectator = not is_real_player and sid != "PUBLIC_VIEW" and sid in game.spectators
    
    state: dict[str, Any] = {
        'players': [],
        'discard_piles': getattr(game, 'discard_piles', [[] for _ in range(4)]),
        'last_discard': game.last_discard,
        'current_turn': game.current_turn,
        'game_started': game.game_started,
        'tiles_left': len(game.deck),
        'chi_options': {}, 
        'state': getattr(game, 'state', 'NORMAL'),
        'my_hand': [],
        'is_spectator': is_spectator,
        'is_performance_mode': getattr(game, 'is_performance_mode', False), # 🚀 Sync flag to frontend
        'room_id': getattr(game, 'room_id', 'unknown'),
        'can_hu': False  # 🎯 HU detection flag
    }
    
    for i, p in enumerate(game.players):
        if not p.get('sid', '').startswith('ai_'):
            # 🛡️ Chi-Hiding: Only send boolean status to humans, not the actual words.
            state['chi_options'][i] = len(game.get_chi_options(i)) > 0

    for i, p in enumerate(game.players):
        player_info: dict[str, Any] = {
            'name': p.get('name', 'Unknown'),
            'melds': p.get('melds', []),
            'hand_size': len(p.get('hand', [])),
            'sid': p.get('sid', ''),
            'turn_time': p.get('turn_time', 0),
            'bank_time': p.get('bank_time', 0),
            'is_turn': game.current_turn == i
        }
        
        # 🛡️ Core Logic: Send hand info if requested explicitly, if SID matches, or if it's a real spectator
        should_see_hand = False
        if (include_hands is not None and i in include_hands):
            should_see_hand = True
        elif p.get('sid') == sid:
            should_see_hand = True
        elif is_spectator: # Only real spectators (TV Mode) see hands
            should_see_hand = True
            
        if should_see_hand:
            player_info['hand'] = p.get('hand', []) # type: ignore
            # 🛡️ Chi-Hiding: Mask options in detailed player info too
            player_info['chi_options'] = len(game.get_chi_options(i)) > 0
            if p.get('sid') == sid:
                state['my_hand'] = p.get('hand', [])
                
                # 🎯 HU Detection: Check if this player's hand can win
                if game.game_started and game.current_turn == i:
                    state['can_hu'] = _check_can_hu(game, i)
            
        state['players'].append(player_info)
    return state


def _check_can_hu(game, player_index):
    """🎯 Check if a player's hand can be fully decomposed into valid words."""
    try:
        player = game.players[player_index]
        hand = player.get('hand', [])
        
        # No tiles = can't hu (unless pure meld win)
        if not hand:
            return bool(player.get('melds'))
        
        letters = [t.get('value', '').lower() for t in hand if isinstance(t, dict) and t.get('type') == 'letter']
        items_count = len([t for t in hand if isinstance(t, dict) and t.get('type') == 'item'])
        
        # 🎯 In WAITING_ACTION, include the discarded tile (Ron/discard Hu)
        if getattr(game, 'state', 'NORMAL') == 'WAITING_ACTION' and game.last_discard:
            if game.last_discard.get('player_index') != player_index:
                tile = game.last_discard.get('tile', {})
                if isinstance(tile, dict):
                    if tile.get('type') == 'letter':
                        letters.append(tile.get('value', '').lower())
                    elif tile.get('type') == 'item':
                        items_count += 1
        
        if len(letters) < 2:
            return False
        
        # Use AI_find_hu_partition with full dictionary (no vocab limit)
        result = game.AI_find_hu_partition(letters, items_count, vocab_limit=999999)
        return result is not None
    except Exception as e:
        dprint(f"DEBUG: [CAN_HU] Error checking hu for player {player_index}: {e}")
        return False



def broadcast_game_state(game):
    """
    🚀 HIGH-PERFORMANCE BROADCASTING
    Separates public state (room-wide) from private data (player hands)
    """
    # 1. Sync PRIVATE data with all active human players FIRST
    # These contain the player's own hand
    for p in game.players:
        sid = p.get('sid', '')
        if sid and not sid.startswith('ai_'):
            # Send full state WITH their specific hand
            socketio.emit('game_state', get_game_state(game, sid), room=sid)
            # Extra redundancy for hand-only sync
            socketio.emit('my_hand', {'hand': p.get('hand', [])}, room=sid)

    # 2. Broadcast PUBLIC state to everyone in the room (O(1) emission)
    # This state now guaranteed has NO hands (sid="PUBLIC_VIEW" is not a spectator)
    public_state = get_game_state(game, "PUBLIC_VIEW")
    socketio.emit('game_state', public_state, room=game.room_id)
    
    # 3. Sync with all spectators (Host/TV Rooms) who need ALL hands visible
    for spec_sid in list(game.spectators):
        # Spectators get EVERYTHING (include_hands=all)
        all_indices = list(range(len(game.players)))
        socketio.emit('game_state', get_game_state(game, spec_sid, include_hands=all_indices), room=spec_sid)

@socketio.on('get_my_hand')
def on_get_hand(data=None):
    game = find_game_by_sid(request.sid)
    if game:
        player = next((p for p in game.players if p.get('sid') == request.sid), None)
        if player:
            socketio.emit('my_hand', {'hand': player.get('hand', [])}, room=request.sid)

@socketio.on('cheat_hu')
def on_cheat_hu(data=None):
    game = find_game_by_sid(request.sid)
    if game:
        player = next((p for p in game.players if p.get('sid') == request.sid), None)
        if player:
            # 🚀 Cheat Hu: Simply fill the hand with valid letters
            player['hand'] = []
            winning_words = ["APPLE", "BANANA", "CHERRY", "DRAGON"]
            for word in winning_words:
                for char in word:
                    player['hand'].append({'type': 'letter', 'value': char.upper()})
            
            while len(player['hand']) < 16:
                player['hand'].append({'type': 'letter', 'value': 'A'}) 
            
            player['hand'] = player['hand'][:16]
            player['melds'] = []
            broadcast_game_state(game)
            socketio.emit('message', {'msg': f'HINT: Manual Hu cheat activated.'}, room=request.sid)

            player_index = next((i for i, p in enumerate(game.players) if p.get('sid') == request.sid), None)
            if player_index is not None:
                socketio.start_background_task(process_ai_action, game, player_index)



@socketio.on('update_ai_interval')
def on_update_ai_interval(data):
    game = find_game_by_sid(request.sid)
    if game:
        val = data.get('interval', 5.0)
        try:
            game.ai_interval = float(val)
            dprint(f"DEBUG: [AI_INTERVAL] Updated in room {game.room_id} to {game.ai_interval}s")
            socketio.emit('message', {'msg': f'AI Speed set to {game.ai_interval}s'}, room=game.room_id)
        except: pass

@socketio.on('chat_message')
def on_chat_message(data):
    game = find_game_by_sid(request.sid)
    if not game: return
    
    msg = data.get('msg', '').strip()
    if not msg: return
    
    player_index = next((i for i, p in enumerate(game.players) if p.get('sid') == request.sid), -1)
    username = data.get('username', 'Unknown')
    
    socketio.emit('chat_message', {
        'username': username,
        'msg': msg,
        'pos_index': player_index
    }, room=game.room_id)

@socketio.on('disconnect')
def on_disconnect():
    if request.sid in sid_to_room:
        room_id = sid_to_room[request.sid]
        if room_id in games:
            game = games[room_id]
            if request.sid in game.spectators:
                game.spectators.remove(request.sid)
        del sid_to_room[request.sid]

def run_game_timer_loop(room_id):
    """
    🕒 Main game timer loop
    """
    while True:
        socketio.sleep(1)
        game = games.get(room_id)
        if not game or not getattr(game, 'game_started', False): break
        if getattr(game, 'timer_paused', False): continue
        
        active_idx = game.current_turn
        player = game.players[active_idx]
        
        if player['turn_time'] > 0:
            player['turn_time'] -= 1.0
        elif player['bank_time'] > 0:
            player['bank_time'] -= 1.0
        else:
            # ⏰ Time out! Force a random discard
            dprint(f"DEBUG: [TIMER] Player {active_idx} timed out! Auto-discarding.")
            if game.state == 'WAITING_ACTION':
                game.skip_action(active_idx)
            else:
                # Discard random letter tile
                hand = player.get('hand', [])
                if hand:
                    letter_indices = [i for i, t in enumerate(hand) if t.get('type') == 'letter']
                    discard_idx = random.choice(letter_indices) if letter_indices else 0
                    game.discard(active_idx, discard_idx)
                    game.next_turn()
            
            # ⏲️ Reset turn timer for next player after timeout
            for p in game.players:
                p['turn_time'] = 20.0
            
            trigger_turn(game)
            broadcast_game_state(game)
            # 🚀 FIX: Do NOT 'return' here, otherwise the timer loop dies forever!
            continue

        # 🚀 LIGHTWEIGHT TIMER SYNC (Avoids heavy full-state broadcast every second)
        timer_data = {
            'current_turn': game.current_turn,
            'players': [{'turn_time': p['turn_time'], 'bank_time': p['bank_time']} for p in game.players]
        }
        socketio.emit('timer_update', timer_data, room=room_id)
    
    # 🚀 FIX: Reset timer_active when loop breaks so the next game can start the timer
    game = games.get(room_id)
    if game:
        game.timer_active = False
        dprint(f"DEBUG: [TIMER] Loop ended for room {room_id}. timer_active reset to False.")

def is_port_in_use(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    
    if port == 5001 and is_port_in_use(port):
        print(f"\n[!! WARNING] Port {port} is already in use!")
        print(f"Another server may already be running. Close the old terminal or kill the Python process.")
        print(f"--------------------------------------------------\n")
    
    try:
        print(f" * Starting server on port {port}...")
        socketio.run(app, debug=False, port=port, host='0.0.0.0', allow_unsafe_werkzeug=True)
    except Exception as e:
        print(f"\n[ERROR] Server failed to start: {e}")