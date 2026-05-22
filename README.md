# 🀄 English Mahjong（英文字母麻將）

以麻將的回合制機制為骨架、英文詞彙拼組為核心的多人即時連線遊戲。玩家抽取並打出字母牌，搶先將手牌全部組合成合法英文單字者獲勝。

---

## 目錄

- [專案簡介](#專案簡介)
- [功能特色](#功能特色)
- [系統架構](#系統架構)
- [核心處理流程](#核心處理流程)
- [遊戲玩法](#遊戲玩法)
- [電腦對手系統](#電腦對手系統)
- [線上遊玩](#線上遊玩)
- [專案結構](#專案結構)

---

## 專案簡介

English Mahjong 以英文 26 個字母取代傳統麻將牌。字母張數依照英語實際字元出現頻率分配（如 E ×17、T ×12、A ×11），每位玩家每局發得 **16 張牌**，輪流進行摸牌與出牌，目標是將手上所有牌拼成一組合法的英文字典詞彙。

支援三種遊戲模式：

- **單人模式** — 一名玩家對抗三隻電腦模擬對手
- **多人模式** — 最多四名玩家共用一個房間
- **旁觀者 / Host 模式** — 全牌面公開的唯讀視角，適合投影展示或主持

---

## 功能特色

| 功能 | 說明 |
|---|---|
| 🎮 **即時多人連線** | 透過 Socket.IO WebSocket 同步所有客戶端的遊戲狀態 |
| 🤖 **電腦對手** | 四段難度，以詞彙量抽樣作為難度基準 |
| 📺 **旁觀者模式** | Host / TV 端可見所有玩家手牌，適合解說或投影 |
| 🈁 **吃牌（CHI）** | 截取上家出牌，與手牌組成合法英文單字 |
| 🏆 **胡牌（HU）** | 手動輸入獲勝單字組合，由伺服器驗證後宣告勝利 |
| 🔒 **資訊隱藏** | 其他玩家的手牌內容與吃牌選項不會傳送至對手客戶端 |

---

## 系統架構

```mermaid
graph TD
    subgraph Client["瀏覽器（客戶端）"]
        HTML["HTML + Vanilla CSS"]
        JS["game.js"]
        SIOc["Socket.IO Client 4.x"]
    end

    subgraph Server["Flask 後端  server.py"]
        SIOd["Flask-SocketIO\nWebSocket 處理"]
        Game["EnglishMahjongGame\n遊戲狀態與規則引擎"]
        BOT["電腦對手引擎\n遞迴詞彙分割演算法"]
        Data["words.json\nword_frequencies.json"]
    end

    SIOc -- WebSocket --> SIOd
    SIOd --> Game
    Game --> BOT
    BOT --> Data
```

### 後端

| 元件 | 技術 |
|---|---|
| Web 框架 | Flask |
| 即時通訊 | Flask-SocketIO（WebSocket） |
| 非同步事件循環 | Eventlet |
| 執行環境 | Python 3.10+ |

### 前端

| 元件 | 技術 |
|---|---|
| 遊戲邏輯與畫面渲染 | Vanilla JavaScript（`game.js`） |
| 即時事件 | Socket.IO Client 4.x |
| 勝利動畫 | canvas-confetti |
| 字型 | Google Fonts（Inter、Orbitron、Outfit） |

---

## 核心處理流程（Process）

為確保即時多人對戰遊戲的流暢度與公平性，系統將核心邏輯（吃牌、胡牌、AI 決策、狀態更新）集中於後端，並透過 WebSocket 連線同步至前端。以下是系統的核心決策與資料處理流程：

```mermaid
flowchart TD
    %% Define Styles
    classDef startEnd fill:#f9f,stroke:#333,stroke-width:2px;
    classDef process fill:#e1f5fe,stroke:#0288d1,stroke-width:2px,color:#000;
    classDef branch fill:#fff9c4,stroke:#fbc02d,stroke-width:2px,color:#000;
    classDef merge fill:#e8f5e9,stroke:#388e3c,stroke-width:2px,color:#000;
    
    Start([玩家打出字母牌]) --> Prep[更新遊戲狀態並暫存出牌 last_discard]
    Prep --> Decision1{檢查玩家反應}
    
    Decision1 -->|所有人| HuCheck[胡牌快取檢查: 判定是否可榮和 Ron]
    Decision1 -->|僅限下家| ChiCheck[吃牌檢查: 計算可吃牌組成之單字]
    
    HuCheck --> Merge1[合流：進入 WAITING_ACTION 狀態]
    ChiCheck --> Merge1
    
    Merge1 --> ActionDecision{根據玩家動作分支}
    
    ActionDecision -->|宣告吃牌 CHI| ChiProcess[吃牌處理]
    ActionDecision -->|宣告胡牌 HU| HuProcess[胡牌驗證與求解]
    ActionDecision -->|跳過 / 超時 SKIP| SkipProcess[跳過處理]
    
    %% Chi branch
    subgraph ChiBranch [吃牌處理程序]
        ChiProcess --> ChiV[字典驗證: 是否為合法單字]
        ChiV --> ChiD[扣除手牌字母，將單字移至副露 Melds]
        ChiD --> ChiT[轉為該吃牌玩家回合，狀態設為 NORMAL]
    end
    
    %% Hu branch
    subgraph HuBranch [胡牌驗證與求解程序]
        HuProcess --> HuSplit{驗證來源}
        HuSplit -->|玩家手動輸入| HuManual["正規表達式提取單字<br/>比對 30 萬筆 words.json 字典"]
        HuSplit -->|電腦對手 / 快取| HuAI["AI 遞迴回溯法求解器<br/>AI_find_hu_partition"]
        
        HuAI --> HuAIEngine["字元與長度雙重索引檢索<br/>難度字彙抽樣與記憶化剪枝"]
        
        HuManual --> HuMerge[合流：檢查手牌字母及萬用牌是否完美匹配且無剩餘]
        HuAIEngine --> HuMerge
        
        HuMerge --> HuVerifyResult{驗證結果}
        HuVerifyResult -->|成功| HuWin["宣告遊戲結束 game_over<br/>播放 canvas-confetti 勝利動畫"]
        HuVerifyResult -->|失敗| HuFail[駁回胡牌，恢復遊戲]
    end
    
    %% Skip branch
    subgraph SkipBranch [跳過/超時處理程序]
        SkipProcess --> SkipClear[清除 last_discard 出牌快取]
        SkipClear --> SkipDraw[該玩家摸牌並更新 can_hu 快取]
        SkipDraw --> SkipNext[輪到下一順位玩家，狀態設為 NORMAL]
    end
    
    ChiT --> Merge2[合流：廣播最新遊戲狀態]
    HuWin --> EndGame([遊戲結束])
    HuFail --> SkipNext
    SkipNext --> Merge2
    
    Merge2 --> ClientRender[前端 game.js 接收 WebSocket 事件並渲染畫面]
    
    %% Apply styles
    class Start,EndGame startEnd;
    class Prep,ChiV,ChiD,ChiT,HuManual,HuAIEngine,HuMerge,SkipClear,SkipDraw,SkipNext,ClientRender process;
    class Decision1,ActionDecision,HuSplit,HuVerifyResult branch;
    class Merge1,Merge2,HuFail,HuWin merge;
```

---

## 遊戲玩法

### 牌組設計

字母數量依英語字元使用頻率分配：

| 頻率等級 | 字母 |
|---|---|
| 高頻（≥8 張） | E ×17、T ×12、O ×10、A ×11、I ×9、N ×9、S ×8、H ×8、R ×8 |
| 低頻（1 張） | J、K、Q、X、Z |

每位玩家開局持有 **16 張牌**。

### 回合流程

```mermaid
flowchart LR
    A([🎴 摸牌]) --> B([🃏 打出一張牌])
    B --> C{其他玩家決定}
    C -- 宣告 CHI --> D([🔀 吃牌處理])
    C -- 宣告 HU --> E([🏆 胡牌驗證])
    C -- SKIP --> F([➡️ 下一回合])
    D --> F
    E -- 驗證通過 --> G([🎉 遊戲結束])
    E -- 驗證失敗 --> F
```

1. **摸牌**：當前玩家從牌堆頂端抽一張牌。
2. **出牌**：選擇一張手牌打出（點兩下確認，防止誤觸）。
3. **反應**：下一順序玩家可宣告 **吃牌（CHI）**；任何玩家可宣告 **胡牌（HU）**。
4. **胡牌驗證**：遊戲暫停，宣告者需手動輸入獲勝單字組合，手牌中所有字母必須全部使用。

### 遊戲狀態機

```mermaid
stateDiagram-v2
    [*] --> WAITING
    WAITING --> NORMAL : 遊戲開始
    NORMAL --> WAITING_ACTION : 玩家出牌
    WAITING_ACTION --> NORMAL : 動作完成（CHI / SKIP）
    WAITING_ACTION --> PAUSED_FOR_HU : 玩家宣告 HU
    PAUSED_FOR_HU --> NORMAL : 胡牌驗證失敗
    PAUSED_FOR_HU --> [*] : 胡牌驗證通過（遊戲結束）
```

---

## 電腦對手系統

### 難度等級

| 難度 | 詞彙量（佔總字庫比例） | 胡牌觸發機率 | 吃牌策略 |
|---|---|---|---|
| Beginner | 1% | 5% | 偏好短單字 |
| Intermediate | 5% | 15% | 隨機選擇 |
| Advanced | 10% | 35% | 偏好長單字 |
| Ultimate | 20% | 75% | 偏好長單字 |

### 核心演算法：遞迴詞彙分割

電腦對手的胡牌判斷使用**遞迴回溯法（Recursive Backtracking）搭配記憶化（Memoisation）**：

1. 取手牌第一個字母。
2. 透過預建的字元／長度雙重索引，查詢所有包含該字母的候選單字。
3. 依難度對候選詞進行詞彙量過濾（從字庫隨機抽樣）。
4. 若手牌字母足夠組成某候選詞，扣除使用的字母後遞迴處理剩餘手牌。
5. 基底情況：所有字母耗盡 → 胡牌成立；否則回溯嘗試下一候選詞。

---

## 線上遊玩

本專案已部署至雲端，無需本機安裝即可直接遊玩：

👉 **[立即遊玩 English Mahjong](https://english-mahjohn.onrender.com/)**

---

## 專案結構

```
majan/
├── server.py                  # 後端核心：Flask、SocketIO、遊戲引擎、電腦對手
├── requirements.txt           # Python 依賴套件清單
├── build.py                   # 建置工具腳本
├── filter_proper_nouns.py     # 字典前處理：過濾專有名詞
├── solve.py                   # 獨立胡牌求解器（測試用）
├── test_hu.py                 # 胡牌邏輯單元測試
│
├── templates/
│   └── index.html             # Jinja2 HTML 進入點
│
└── static/
    ├── css/
    │   └── style.css          # 全域樣式（深色主題、動畫效果）
    ├── js/
    │   └── game.js            # 客戶端遊戲邏輯與 Socket.IO 整合
    ├── words.json             # 英文字典（約 30 萬筆詞彙）
    └── word_frequencies.json  # 詞頻排序清單（供電腦對手難度設定使用）
```
