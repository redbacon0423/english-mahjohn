try:
    import eventlet # type: ignore
    eventlet.monkey_patch()
    _async_mode = 'eventlet'
except ImportError:
    _async_mode = 'threading'

import os
import json
import random
import socket
import re
from collections import Counter
from typing import Any
from flask import Flask, render_template, send_from_directory, request # type: ignore
from flask_socketio import SocketIO, join_room # type: ignore
try:
    from google import genai # type: ignore
except ImportError:
    genai = None
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'majan_secret!'
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable static file caching

socketio = SocketIO(app, cors_allowed_origins="*", async_mode=_async_mode)

@app.after_request
def add_no_cache(response):
    """Force browser to never cache any file."""
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


games: dict[str, 'EnglishMahjongGame'] = {}
GLOBAL_DEBUG = False  # 🚀 Set to False for Exhibition/Production

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
if gemini_api_key and genai is not None:
    try:
        gemini_client = genai.Client(api_key=gemini_api_key)
        print("✅ Gemini API configured successfully.")
    except Exception as e:
        print(f"Failed to configure Gemini: {e}")

# 🧠 Theme validation cache
THEME_CACHE: dict[str, bool] = {}
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

def get_local_ip():
    # 🚀 ONLY use Render URL if specifically in a Render environment
    if os.environ.get('RENDER'):
        return "english-mahjohn.onrender.com"
        
    try:
        # Try to get the IP used for external traffic
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"

LOCAL_IP = get_local_ip()
print(f" * Server running on LAN: http://{LOCAL_IP}:5001")


# ==========================================
# 🎲 Random Restriction System
# ==========================================
# 🎨 Exclude rare letters to increase game flow
COMMON_LETTERS = "ABCDEFGHIJKLMNOPRSTUVW" # Exclude Q, X, Z, J, Y



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
        self.saved_state = None
        self.hu_declaring_player = None

    def set_dictionary(self, dictionary: list[str]):
        if getattr(self, 'word_index', None): 
            return # 🚀 ANTI-STALL: Skip 300k word iteration if already built
            
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
                'turn_time': 20.0,
                'can_hu': False  # 🚀 Performance Cache
            })
            # Log player join
            dprint(f"DEBUG: [GAME] Player {name} joined.")
            return True
        return False

    def start_game(self):
        if len(self.players) < 2: return False
        self.init_deck()
        
        self.discard_piles = [[] for _ in range(len(self.players))]
        self.last_discard = None
        self.current_chi_options = {}
        self.saved_state = None
        self.hu_declaring_player = None
        
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
        
        # 🚀 Initial Hu cache update
        for i in range(len(self.players)):
            self.update_hu_cache(i)
            
        return True

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
        
        # 🚀 Update Hu cache for ALL OTHER players (Ron/Hu on discard check)
        for i in range(len(self.players)):
            if i != player_index:
                self.update_hu_cache(i)
        
        return True




    def next_turn(self):
        self.current_turn = (self.current_turn + 1) % len(self.players)
        self.current_chi_options = {}
        dprint(f"DEBUG: [NEXT_TURN] Now Player {self.current_turn}'s turn. State: {self.state}")
        last_t = self.last_discard.get('tile') if self.last_discard else None
        discarder_idx = self.last_discard.get('player_index') if self.last_discard else None
        
        found_action = False
        
        if last_t and discarder_idx is not None:
            # 🗄️ Standard Mahjong Rules: 
            # 1. Any player can Hu (Ron) on any discard.
            # 2. Only the next player (LEFT) can Chi.
            
            # Check for Hu in turn order starting from the next player
            
            for i in range(1, len(self.players)):
                check_idx = (int(discarder_idx) + i) % len(self.players)
                check_p = self.players[check_idx]

                # Check for Hu (Ron)
                hand = check_p.get('hand', [])
                hand_letters = [t.get('value', '').lower() for t in hand if isinstance(t, dict) and t.get('type') == 'letter']
                hand_items_count = len([t for t in hand if isinstance(t, dict) and t.get('type') == 'item'])
                
                # Temporarily add the discard to check for Hu
                if last_t.get('type') == 'letter':
                    hand_letters.append(last_t.get('value', '').lower())
                
                # For AI, we need to know their vocabulary for this "check"
                # (Ideally we'd use a consistent vocabulary, but for detection we check if ANY Hu is possible)
                # 🎯 Ron/Hu Detection: Use the high-performance cache we just updated in discard()
                can_hu = check_p.get('can_hu', False)

                # Check for Chi (Only for the LEFT player)
                is_next_player = (i == 1)
                chi_options = []
                if is_next_player:
                    chi_options = self.calculate_chi_options(check_idx, last_t)
                
                if can_hu or chi_options:
                    self.state = 'WAITING_ACTION'
                    self.current_turn = check_idx
                    self.current_chi_options[check_idx] = chi_options
                    found_action = True
                    dprint(f"DEBUG: [NEXT_TURN] Waiting for action from player {check_idx}. Hu={can_hu}, Chi={len(chi_options)}")
                    break # Prioritize the first player who can act in turn order
        
        if not found_action:
            # 🛡️ Handle Penalty Turns
            loops = 0
            while self.players[self.current_turn].get('penalty_turns', 0) > 0 and loops < len(self.players):
                self.players[self.current_turn]['penalty_turns'] -= 1
                penalized_player_name = self.players[self.current_turn].get('name', 'Unknown')
                dprint(f"DEBUG: [NEXT_TURN] Player {self.current_turn} skipped due to penalty.")
                # We need to emit via socketio, but self doesn't have it directly. Luckily socketio is global in server.py
                socketio.emit('message', {'msg': f"🚫 {penalized_player_name} is suspended for this turn!"}, room=getattr(self, 'room_id', ''))
                self.current_turn = (self.current_turn + 1) % len(self.players)
                loops += 1

            # Normal: draw tile for the naturally next player
            self.state = 'NORMAL'
            new_tile = self.draw_tile()
            if new_tile:
                self.players[self.current_turn]['hand'].append(new_tile)
                self.update_hu_cache(self.current_turn) # 🚀 Cache update
                dprint(f"DEBUG: [NEXT_TURN] Player {self.current_turn} drew {new_tile.get('value')}. State=NORMAL")
            else:
                print("DEBUG: [NEXT_TURN] Deck empty! Game over.")
                socketio.emit('game_over', {'winner': 'Nobody (Draw)', 'melds': [], 'hand': []}, room=self.room_id)
                self.game_started = False
                if getattr(self, 'demo_mode', False):
                    socketio.start_background_task(schedule_demo_restart, self.room_id)
                return
        
        # ⏲️ Reset turn timer for the acting player
        for p in self.players:
            p['turn_time'] = 20.0




    def skip_action(self, player_index):
        if getattr(self, 'state', 'NORMAL') == 'WAITING_ACTION' and self.current_turn == player_index:
            dprint(f"DEBUG: Player {player_index} ({self.players[player_index]['name']}) skipped action.")
            self.state = 'NORMAL'
            self.current_chi_options = {}
            # 🔑 KEY FIX: Clear last_discard BEFORE calling next_turn().
            self.last_discard = None
            
            # 🚀 Update Hu cache for everyone (Ron no longer possible)
            for i in range(len(self.players)):
                self.update_hu_cache(i)
            
            # Draw a tile for the skipping player (it's now their draw turn)
            new_tile = self.draw_tile()
            if new_tile:
                self.players[player_index]['hand'].append(new_tile)
                self.update_hu_cache(player_index) # 🚀 Cache update
                dprint(f"DEBUG: [SKIP] Player {player_index} drew tile after skipping: {new_tile.get('value')}")
            else:
                # 🃏 Deck empty after skip
                dprint("DEBUG: [SKIP] Deck empty! Game over.")
                socketio.emit('game_over', {'winner': 'Nobody (Draw)', 'melds': [], 'hand': []}, room=self.room_id)
                self.game_started = False
                if getattr(self, 'demo_mode', False):
                    socketio.start_background_task(schedule_demo_restart, self.room_id)
            
            # Reset turn timers
            for p in self.players:
                p['turn_time'] = 20.0
            return True

        return False

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
        
        # 🚀 Update Hu cache for everyone (Ron no longer possible)
        for i in range(len(self.players)):
            self.update_hu_cache(i)

        self.current_turn = player_index 
        self.state = 'NORMAL' 
        self.current_chi_options = {}
        # 🚀 Cache update after Chi
        self.update_hu_cache(player_index)
        return True, ""

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
        current_state = getattr(self, 'state', 'NORMAL')
        prev_state = getattr(self, 'saved_state', current_state)
        
        if (current_state == 'WAITING_ACTION' or prev_state == 'WAITING_ACTION') and self.last_discard:
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

    def update_hu_cache(self, player_index):
        """🚀 Performance: Update the can_hu status for a specific player."""
        try:
            player = self.players[player_index]
            hand = player.get('hand', [])
            
            # 🛡️ Loophole Fix: If player has NO tiles in hand, they cannot Ron.
            if not hand:
                player['can_hu'] = False
                return
            
            letters = [t.get('value', '').lower() for t in hand if isinstance(t, dict) and t.get('type') == 'letter']
            items_count = len([t for t in hand if isinstance(t, dict) and t.get('type') == 'item'])
            
            # 🎯 In WAITING_ACTION, include the discarded tile (Ron/discard Hu)
            if getattr(self, 'state', 'NORMAL') == 'WAITING_ACTION' and self.last_discard:
                if self.last_discard.get('player_index') != player_index:
                    tile = self.last_discard.get('tile', {})
                    if isinstance(tile, dict):
                        if tile.get('type') == 'letter':
                            letters.append(tile.get('value', '').lower())
                        elif tile.get('type') == 'item':
                            items_count += 1
            
            if len(letters) < 2:
                player['can_hu'] = False
                return
            
            # 🚀 Simplified Hu Cache (Hint only, no complex detection)
            # We keep it False by default to avoid server-side lag.
            # Users can always manually click the HU button.
            player['can_hu'] = False
        except Exception as e:
            dprint(f"DEBUG: [UPDATE_HU_CACHE] Error: {e}")
            player['can_hu'] = False

    def AI_find_hu_partition(self, letters, items_count, current_melds=None, memo=None, vocab_limit=1000, is_nightmare=False, known_words=None, call_cap=1000):
        if memo is None: memo = {'__calls__': 0}
        
        # 🚀 ANTI-STALL: Yield to eventlet to avoid freezing other players/timer
        memo['__calls__'] += 1
        if memo['__calls__'] % 10 == 0:
            socketio.sleep(0)
            
        hand_key = "".join(sorted(letters)) + f":{items_count}"
        if hand_key in memo: return memo[hand_key]
        
        # 🚀 ANTI-STALL: Fast return for impossible small hands
        target_len = len(letters) + items_count
        if target_len > 0 and target_len < 2:
            memo[hand_key] = None
            return None

        # 🛡️ Anti-Lock: Cap max recursion to prevent hanging (call_cap configurable per mode)
        if memo['__calls__'] > call_cap:
            return None
            
        # 0. Base Case: Hand empty
        if target_len == 0:
            return current_melds or []

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
                
                random.shuffle(candidates)
                
                # 🚀 ANTI-STALL: Cap horizontal search width to prevent massive loops freezing the server
                candidates = candidates[:30]
                
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
                        res = self.AI_find_hu_partition(new_hand, items_count - needed_wildcards, (current_melds or []) + [word.upper()], memo, vocab_limit=vocab_limit, is_nightmare=is_nightmare, known_words=known_words, call_cap=call_cap)
                        if res is not None:
                            memo[hand_key] = res
                            return res
        else:
            # Only wildcards left (extremely rare)
            for length in range(min(10, target_len), 1, -1):
                if length not in self.round_word_index_by_len: continue
                
                candidates = list(self.round_word_index_by_len[length])
                if known_words is not None:
                    candidates = [w for w in candidates if w.lower() in known_words]
                else:
                    candidates = [w for w in candidates if WORD_RANK.get(w.lower(), 999999) < vocab_limit]
                random.shuffle(candidates)
                
                # 🚀 ANTI-STALL: Cap horizontal search width to prevent massive loops freezing the server
                candidates = candidates[:30]
                
                for word in candidates:
                    if self.validate_word(word, fast_check=True):
                        res = self.AI_find_hu_partition([], items_count - length, (current_melds or []) + [word.upper()], memo, vocab_limit=vocab_limit, is_nightmare=is_nightmare, known_words=known_words, call_cap=call_cap)
                        if res is not None:
                            memo[hand_key] = res
                            return res

        memo[hand_key] = None
        return None

 

    def register_wrong_move(self, player_index):
        if 0 <= player_index < len(self.players):
            self.players[player_index]['penalty_turns'] = self.players[player_index].get('penalty_turns', 0) + 1


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

@socketio.on('reorder_hand')
def on_reorder_hand(data):
    """🔄 Sync player's local hand order to the server for spectators."""
    game = find_game_by_sid(request.sid)
    if game:
        player_index = next((i for i, p in enumerate(game.players) if p.get('sid') == request.sid), None)
        if player_index is not None:
            new_hand = data.get('hand', [])
            # 🛡️ Security Check: Ensure tile counts match (by value), only order changed
            def hand_sig(h):
                return sorted((t.get('type',''), t.get('value','')) for t in h if isinstance(t, dict))
            if hand_sig(game.players[player_index]['hand']) == hand_sig(new_hand):
                game.players[player_index]['hand'] = new_hand
                # 📡 Broadcast to everyone so they see the new order
                broadcast_game_state(game)

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
                'easy': max(1, int(total_words * 0.01)),      # 1%
                'normal': max(1, int(total_words * 0.05)),    # 5%
                'hard': max(1, int(total_words * 0.10)),      # 10%
                'nightmare': max(1, int(total_words * 0.20))  # 20%
            }
            vocab_limit = limit_map.get(difficulty, limit_map['normal'])
            
            # 🚀 Check if AIs already exist (in case of reconnect)
            ai_exists = any(p.get('sid', '').startswith('ai_') for p in game.players)
            if not ai_exists:
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
                        'turn_time': 20.0,
                        'can_hu': False # 🚀 Cache
                    })
                # 🎡 Autostart single-player immediately as requested by user
                initialize_game_start(game)
            else:
                # 🚀 Reconnected, just send game state
                broadcast_game_state(game)
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
            'vocab_limit': int(len(WORDS) * 0.05), # 5% for normal
            'bank_time': 60.0,
            'turn_time': 20.0,
            'can_hu': False # 🚀 Cache
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
                'vocab_limit': int(len(WORDS) * 0.05),
                'bank_time': 60.0,
                'turn_time': 20.0,
                'can_hu': False
            })

    if game.start_game():
        game.timer_paused = True # Pause timer for wheel animation
        if not game.timer_active:
            game.timer_active = True
            socketio.start_background_task(run_game_timer_loop, game.room_id)
        
        socketio.emit('message', {'msg': 'Game Started! Rule: FREE MODE'}, room=game.room_id)
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
    # 🚀 Bug Fix #1: Always build word index so AI can find hu partitions
    game.set_dictionary(WORDS)
    # 🚀 Bug Fix #2: Preserve slider-set interval; only default to 1.5 on first launch
    if not hasattr(game, 'ai_interval') or game.ai_interval == 5.0:
        game.ai_interval = 1.5  # Fast default for Performance Mode
    sid_to_room[request.sid] = room_id
    
    # 🚀 Check if AIs already exist (in case of reconnect)
    ai_exists = any(p.get('sid', '').startswith('ai_demo_') for p in game.players)
    if not ai_exists:
        # Clear existing players and add 4 AI
        game.players = []
        # 🚀 Bug Fix #4: Reset discard_piles properly for demo mode
        game.discard_piles = []
        
        ai_names = ["AI East", "AI South", "AI West", "AI North"]
        total_words = len(WORDS)
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
                'difficulty': 'normal', 
                'vocab_limit': int(total_words * 0.015), # 1.5% for demo/performance (lowered to extend game)
                'bank_time': 0.0, # Disable bank time jump in Demo
                'turn_time': 20.0
            })
        print(f"DEBUG: [DEMO] Performance mode initialized in room {room_id}. ai_interval={game.ai_interval}s. Autostarting...")
        game.is_performance_mode = True
    else:
        # Reconnected, just send game state
        broadcast_game_state(game)
    
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
            # 🚀 Bug Fix: If human discards their last tile, they win automatically
            player = game.players[player_index]
            if len(player.get('hand', [])) == 0:
                winning_words = player.get('melds', [])
                game.game_started = False
                socketio.emit('broadcast_meld_anim', {'word': " ".join(winning_words), 'player': player.get('name', 'Player'), 'is_hu': True}, room=game.room_id)
                socketio.emit('game_over', {'winner': player.get('name', 'Player'), 'melds': winning_words, 'hand': []}, room=game.room_id)
                socketio.emit('message', {'msg': f'🎉 {player.get("name", "Player")} wins by discarding their last tile!'}, room=game.room_id)
                if getattr(game, 'demo_mode', False):
                    socketio.start_background_task(schedule_demo_restart, game.room_id)
                return

            game.next_turn()
            broadcast_game_state(game)  # broadcast AFTER next_turn so chi_options + WAITING_ACTION is included
            trigger_turn(game)
        else:
            socketio.emit('error', {'msg': f'Cannot play this card! (Index: {tile_index})'}, room=request.sid)
            socketio.emit('game_state', get_game_state(game, request.sid), room=request.sid)

def schedule_demo_restart(room_id):
    """🤖 Auto-restart for Performance Mode after a delay."""
    socketio.sleep(4) # Faster restart for Performance Mode
    game = games.get(room_id)
    if game and getattr(game, 'demo_mode', False):
        print(f"DEBUG: [DEMO] Auto-restarting game in room {room_id}...")
        # 🚀 Bug Fix #1: Rebuild word index on every restart so AI can Hu
        game.set_dictionary(WORDS)
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

@socketio.on('declare_hu')
def on_declare_hu(data=None):
    game = find_game_by_sid(request.sid)
    if not game or not game.game_started: return
    player_index = next((i for i, p in enumerate(game.players) if p.get('sid') == request.sid), None)
    if player_index is None: return

    if getattr(game, 'state', 'NORMAL') != 'PAUSED_FOR_HU':
        game.saved_state = getattr(game, 'state', 'NORMAL')
        game.state = 'PAUSED_FOR_HU'
        game.hu_declaring_player = player_index
        broadcast_game_state(game)

@socketio.on('submit_hu')
def on_submit_hu(data=None):
    game = find_game_by_sid(request.sid)
    if not game or not game.game_started: return
    player_index = next((i for i, p in enumerate(game.players) if p.get('sid') == request.sid), None)
    if player_index is None: return

    if getattr(game, 'state', 'NORMAL') != 'PAUSED_FOR_HU' or game.hu_declaring_player != player_index:
        return

    words_str = str(data.get('words', '')).strip() if data else ''
    
    # Empty/cancel or failed hu -> penalize
    if not words_str:
        success = False
        words = []
    else:
        success, words = game.verify_manual_hu(player_index, words_str)

    player = game.players[player_index]

    if success:
        winning_words = player.get('melds', []) + [w.upper() for w in words]
        game.game_started = False
        socketio.emit('broadcast_meld_anim', {'word': ' '.join(winning_words), 'player': player.get('name'), 'is_hu': True}, room=game.room_id)
        socketio.emit('game_over', {'winner': player.get('name'), 'melds': winning_words, 'hand': []}, room=game.room_id)
        socketio.emit('message', {'msg': f'🎉 {player.get("name")} HU! ({" ".join(winning_words)})'}, room=game.room_id)
        if getattr(game, 'demo_mode', False):
            socketio.start_background_task(schedule_demo_restart, game.room_id)
    else:
        # Failure! Penalty: 1 turn. Safely restore saved state.
        prev_state = getattr(game, 'saved_state', None) or 'NORMAL'
        game.state = prev_state
        game.hu_declaring_player = None
        game.register_wrong_move(player_index)
        fail_msg = '🚨 胡牌失敗！暫停一回合行動。' if words_str else '❌ 取消胡牌。暫停一回合行動。'
        socketio.emit('error', {'msg': fail_msg}, room=request.sid)
        socketio.emit('message', {'msg': f'{fail_msg.split("。")[0]} ({player.get("name")})'}, room=game.room_id)
        broadcast_game_state(game)
        trigger_turn(game)

# ==========================================
# 🤖 AI Logic & Anti-Lock (Background task version)
# ==========================================
def trigger_turn(game):
    """Turn Progression Scheduler"""
    if not getattr(game, 'game_started', False): return
    # 🚀 Bug Fix #5: Don't trigger any AI when game is paused for Hu declaration
    if getattr(game, 'state', 'NORMAL') == 'PAUSED_FOR_HU': return
    
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
        delay = getattr(game, 'ai_interval', 1.5)
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
        is_demo = getattr(game, 'demo_mode', False)

        # ⚡ Pre-decide whether to attempt Hu check (avoids unnecessary CPU work)
        hu_chance = 0.001 if is_demo else {'easy': 0.05, 'normal': 0.15, 'hard': 0.35, 'nightmare': 0.75}.get(difficulty, 0.15)
        will_check_hu = random.random() < hu_chance

        # 🧠 Vocabulary Limit — smaller in demo mode for speed
        total_words_count = len(WORDS)
        if is_demo:
            vocab_limit = max(1, int(total_words_count * 0.015))  # ⚡ Fixed 1.5% in demo
        else:
            limit_map = {
                'easy':      max(1, int(total_words_count * 0.01)),
                'normal':    max(1, int(total_words_count * 0.05)),
                'hard':      max(1, int(total_words_count * 0.08)),
                'nightmare': max(1, int(total_words_count * 0.15)),
            }
            vocab_limit = limit_map.get(difficulty, limit_map['normal'])

        # 🎲 Build AI known words ONLY if we'll actually do Hu check
        if will_check_hu:
            try:
                ai_known_words = set(random.sample(WORDS, min(vocab_limit, len(WORDS))))
            except ValueError:
                ai_known_words = set(WORDS)
        else:
            ai_known_words = None

        hand = player.get('hand', [])
        
        # Define available letter indices (pre-defined to prevent NameError)
        letter_indices = [i for i, t in enumerate(hand) if isinstance(t, dict) and t.get('type') == 'letter']
        
        # 0. AI Auto-Hu detection (Win priority)
        hand_letters = [t.get('value', '').lower() for t in hand if isinstance(t, dict) and t.get('type') == 'letter']
        hand_items_count = len([t for t in hand if isinstance(t, dict) and t.get('type') == 'item'])
        
        # 🛡️ Check for Hu (Winning) on another player's discard
        is_waiting_chi = (getattr(game, 'state', 'NORMAL') == 'WAITING_ACTION' and game.current_turn == ai_index)
        if is_waiting_chi and game.last_discard and game.last_discard.get('player_index') != ai_index:
            tile = game.last_discard.get('tile', {})
            if tile.get('type') == 'letter':
                hand_letters.append(tile.get('value', '').lower())
        
        # ⚡ Hu check: only if pre-decided AND hand is large enough
        hu_set = None
        target_size = len(hand_letters) + hand_items_count
        
        if len(player.get('hand', [])) == 0 and player.get('melds'):
            # 🚀 Fix: If AI ate all hand tiles, it MUST Hu instantly!
            hu_set = []
        elif will_check_hu and target_size >= 2 and ai_known_words:
            is_nightmare = (difficulty == 'nightmare')
            # ⚡ Demo mode: low recursion cap to avoid blocking eventlet loop
            call_cap = 80 if is_demo else 400
            hu_set = game.AI_find_hu_partition(
                hand_letters, hand_items_count,
                vocab_limit=vocab_limit, is_nightmare=is_nightmare,
                known_words=ai_known_words, call_cap=call_cap
            )
        
        if hu_set is not None:
            winning_words = player.get('melds', []) + hu_set
            
            # 🚀 If Hu on discard, remove from discard pile
            if is_waiting_chi and game.last_discard:
                target_p_idx = game.last_discard.get('player_index')
                if target_p_idx is not None and game.discard_piles[target_p_idx]:
                    game.discard_piles[target_p_idx].pop()
                game.last_discard = None
            
            # Clear waiting action state
            game.state = 'NORMAL'

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
            # 🚀 Demo Mode: Increase Chi probability to make performance more dynamic
            if getattr(game, 'demo_mode', False):
                chi_skip_prob = 0.35 # 65% chance to Chi
            else:
                chi_skip_prob = {'easy': 0.85, 'normal': 0.65, 'hard': 0.55, 'nightmare': 0.525}.get(difficulty, 0.65)
            
            should_chi = random.random() > chi_skip_prob
            
            if options and should_chi:
                # 🤖 AI intelligently chooses words
                is_nightmare = (player.get('difficulty') == 'nightmare')
                valid_options = options
                
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
                        
                    success, _ = game.perform_chi(ai_index, chosen_word)
                    if success:
                        # 🚀 Foolproof Mechanism: If AI hand is empty after Chi, trigger HU automatically
                        if len(player.get('hand', [])) == 0:
                            winning_words = player.get('melds', [])
                            game.game_started = False
                            socketio.emit('broadcast_meld_anim', {'word': " ".join(winning_words), 'player': player.get('name', 'AI'), 'is_hu': True}, room=game.room_id)
                            socketio.emit('game_over', {'winner': player.get('name', 'AI'), 'melds': winning_words, 'hand': []}, room=game.room_id)
                            socketio.emit('message', {'msg': f'🎉 {player.get("name", "AI")} wins with automatic HU after CHI!'}, room=game.room_id)
                            if getattr(game, 'demo_mode', False):
                                socketio.start_background_task(schedule_demo_restart, game.room_id)
                            return
                            
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
                
                # 🚀 Bug Fix: If AI discards their last tile, they win automatically
                if len(player.get('hand', [])) == 0:
                    winning_words = player.get('melds', [])
                    game.game_started = False
                    socketio.emit('broadcast_meld_anim', {'word': " ".join(winning_words), 'player': player.get('name', 'AI'), 'is_hu': True}, room=game.room_id)
                    socketio.emit('game_over', {'winner': player.get('name', 'AI'), 'melds': winning_words, 'hand': []}, room=game.room_id)
                    socketio.emit('message', {'msg': f'🎉 {player.get("name", "AI")} wins by discarding their last tile!'}, room=game.room_id)
                    if getattr(game, 'demo_mode', False):
                        socketio.start_background_task(schedule_demo_restart, game.room_id)
                    return
                
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
        'can_hu': False,  # 🎯 HU detection flag
        'hu_declaring_player': getattr(game, 'hu_declaring_player', None)
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
                
                # 🎯 HU Detection: Use cached value (Performance!)
                state['can_hu'] = p.get('can_hu', False)
            
        state['players'].append(player_info)
    return state


def _check_can_hu(game, player_index):
    """🎯 Performance: Return cached Hu status."""
    if player_index < 0 or player_index >= len(game.players):
        return False
    return game.players[player_index].get('can_hu', False)



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
            
            # 🚀 Update Hu cache for cheat
            player_index = next((i for i, p in enumerate(game.players) if p.get('sid') == request.sid), None)
            if player_index is not None:
                game.update_hu_cache(player_index)
                
            broadcast_game_state(game)
            socketio.emit('message', {'msg': f'HINT: Manual Hu cheat activated.'}, room=request.sid)

            player_index = next((i for i, p in enumerate(game.players) if p.get('sid') == request.sid), None)
            if player_index is not None:
                socketio.start_background_task(process_ai_action, game, player_index)



@socketio.on('update_ai_interval')
def on_update_ai_interval(data):
    room_id = data.get('room') or sid_to_room.get(request.sid)
    game = games.get(room_id) if room_id else None
    
    if game:
        val = data.get('interval', 5.0)
        try:
            game.ai_interval = float(val)
            print(f"DEBUG: [AI_INTERVAL] Updated in room {game.room_id} to {game.ai_interval}s")
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
        socketio.sleep(0.1) # High resolution for smooth countdown
        game = games.get(room_id)
        if not game or not getattr(game, 'game_started', False): break
        if getattr(game, 'timer_paused', False): continue
        
        active_idx = game.current_turn
        player = game.players[active_idx]
        
        # 🚀 AI Timeout Override: Force timeout after their configured interval
        ai_timeout_forced = False
        if player.get('sid', '').startswith('ai_'):
            # turn_time counts DOWN from 20. Timeout when it drops below (20 - ai_interval - 0.5).
            threshold = 20.0 - getattr(game, 'ai_interval', 1.5) - 0.5
            if player.get('turn_time', 20.0) <= threshold:
                ai_timeout_forced = True

        if player['turn_time'] > 0 and not ai_timeout_forced:
            player['turn_time'] -= 0.1
        elif player['bank_time'] > 0 and not ai_timeout_forced:
            player['bank_time'] -= 0.1
        else:
            # ⏰ Time out! Force action immediately
            dprint(f"DEBUG: [TIMER] Player {active_idx} timed out! is_AI={player.get('sid','').startswith('ai_')}, state={game.state}")
            
            if game.state == 'WAITING_ACTION':
                game.skip_action(active_idx)
                # After skip_action, next_turn logic already ran inside skip_action
                # Reset timers for all players
                for p in game.players:
                    p['turn_time'] = 20.0
                broadcast_game_state(game)
                # Only trigger AI if next player is AI (avoid duplicate tasks)
                next_player = game.players[game.current_turn]
                if next_player.get('sid', '').startswith('ai_'):
                    socketio.start_background_task(process_ai_action, game, game.current_turn)
                continue

            else:
                # NORMAL state: force discard
                hand = player.get('hand', [])
                if hand:
                    letter_indices = [i for i, t in enumerate(hand) if isinstance(t, dict) and t.get('type') == 'letter']
                    discard_idx = random.choice(letter_indices) if letter_indices else 0
                    game.discard(active_idx, discard_idx)
                else:
                    pass  # empty hand, just fall through to next_turn

                game.next_turn()

                # Reset timers for all players
                for p in game.players:
                    p['turn_time'] = 20.0

                broadcast_game_state(game)

                # ⚠️ CRITICAL: Do NOT call trigger_turn() here for AI —
                # that would spawn a new background task that races with any existing one.
                # Instead, directly spawn one clean task for the next player if they are AI.
                next_player = game.players[game.current_turn]
                if next_player.get('sid', '').startswith('ai_'):
                    socketio.start_background_task(process_ai_action, game, game.current_turn)
                else:
                    # Human's turn: just broadcast state (timer will count down for them)
                    socketio.emit('turn_update', {
                        'current_turn': game.current_turn,
                        'player_sid': next_player.get('sid', ''),
                        'state': getattr(game, 'state', 'NORMAL')
                    }, room=room_id)
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


@socketio.on('auto_play_move')
def on_auto_play(data=None):
    game = find_game_by_sid(request.sid)
    if game:
        player_index = next((i for i, p in enumerate(game.players) if p.get('sid') == request.sid), None)
        if player_index is not None:
            # For human players, ensure they have a default difficulty/vocab for the AI logic
            p = game.players[player_index]
            if 'difficulty' not in p: p['difficulty'] = 'hard'
            if 'vocab_limit' not in p: p['vocab_limit'] = 999999
            
            print(f'DEBUG: [AUTO_PLAY] Triggering AI logic for Human Player {player_index}')
            socketio.start_background_task(process_ai_action, game, player_index)

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
