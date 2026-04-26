# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright
import time
import json
from collections import Counter
import random

with open('static/words.json', 'r', encoding='utf-8') as f:
    WORDS = json.load(f)
valid_words = [w for w in WORDS if len(w) >= 3 and len(w) <= 6]

def find_combination(hand, max_missing=1):
    hand_counts = Counter(hand)
    for _ in range(200000):
        random.shuffle(valid_words)
        current_counts = Counter()
        words = []
        missing = 0
        for w in valid_words:
            w_counts = Counter(w)
            temp_counts = current_counts + w_counts
            temp_missing = sum(max(0, temp_counts[c] - hand_counts[c]) for c in temp_counts)
            
            if temp_missing <= max_missing:
                current_counts = temp_counts
                words.append(w)
                missing = temp_missing
                
                used_all = True
                for c in hand_counts:
                    if current_counts[c] < hand_counts[c]:
                        used_all = False
                        break
                
                if used_all and missing == 1:
                    return words
    return None

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto('http://localhost:5001')
    
    page.click('.menu-btn:nth-child(2)') # Second button is Single Player
    time.sleep(3)
    
    tiles = page.query_selector_all('#hand-bottom .tile .tile-letter')
    hand = [t.inner_text().lower() for t in tiles if t.inner_text().strip()]
    print("Hand:", hand)
    
    res = find_combination(hand)
    print("Found Combination:", res)
    
    if res:
        # Click the button with onclick containing 'reserve'
        page.evaluate('document.querySelector(".action-btn.hu").click()')
        time.sleep(1)
        
        page.fill('#custom-input-field', " ".join(res))
        page.click('#input-confirm-btn')
        time.sleep(1)
        
        toast = page.query_selector('#toast')
        print("Toast msg:", toast.inner_text() if toast else "No toast")
        page.screenshot(path='hu_reservation_test.png')
    
    browser.close()
