import json
from collections import Counter
import random

with open('static/words.json', 'r', encoding='utf-8') as f:
    WORDS = json.load(f)

hand = list('SIJKSDDABIEBALUE'.lower())

# Limit to shorter words to make it easier to find a match
valid_words = [w for w in WORDS if len(w) >= 3 and len(w) <= 6]

# We need words that can be made from hand + 1 extra letter
def find_combination(hand, max_missing=1):
    hand_counts = Counter(hand)
    for _ in range(100000):
        random.shuffle(valid_words)
        current_counts = Counter()
        words = []
        missing = 0
        for w in valid_words:
            w_counts = Counter(w)
            # check if w can be added
            temp_counts = current_counts + w_counts
            temp_missing = sum(max(0, temp_counts[c] - hand_counts[c]) for c in temp_counts)
            
            if temp_missing <= max_missing:
                # Add word
                current_counts = temp_counts
                words.append(w)
                missing = temp_missing
                
                # Check if we used all hand letters
                used_all = True
                for c in hand_counts:
                    if current_counts[c] < hand_counts[c]:
                        used_all = False
                        break
                
                if used_all and missing == 1:
                    return words
    return None

res = find_combination(hand)
print('RESULT:', res)
