# Antigravity IDE Legacy Conversation Migrator

[English](#english) | [繁體中文](#繁體中文)

---

<a id="english"></a>
## 🌐 English

This tool automatically migrates legacy Antigravity conversation histories (`.pb` Protobuf files) into the new SQLite database format (`.db`) used by the Antigravity IDE. It solves the issue where users lose their chat history after upgrading to the new IDE architecture.

### 💮 Background & Core Issue

With the architectural upgrade to Antigravity IDE, the underlying storage mechanism changed:
1. **Legacy Mechanism**: Chat trajectories were serialized in Protobuf format and stored as binary (`.pb`) files in the `conversations/` directory, featuring encryption and a custom structure.
2. **New Mechanism**: The system transitioned to a relational SQLite database (`.db`) architecture. The IDE UI relies on scanning `.db` files in the `conversations/` directory to render the sidebar history.
3. **The Obstacle**: The new IDE lacks an out-of-the-box auto-migration mechanism for `.pb` to `.db`, leaving legacy chat histories (e.g., from `antigravity-backup/conversations`) unreadable.

### 🔍 Principle & Breakthrough

Although the new IDE does not read `.pb` files directly, reverse engineering the built-in **Language Server** revealed a breakthrough:

1. **Hidden gRPC Streaming Interface**: The Language Server maintains backward compatibility logic. By sending a gRPC request to `/exa.language_server_pb.LanguageServerService/StreamAgentStateUpdates` with a conversation UUID, the server automatically uses its internal key to decrypt the `.pb` file and returns the full trajectory as a Protobuf stream.
2. **Raw Protobuf Parsing**: Lacking official `.proto` definitions, we implemented a custom raw Protobuf decoder to capture and separate key nodes from the stream (e.g., `gemini_coder.Step`, `Generator Metadata`, `Executor Metadata`, `Trajectory Metadata`).
3. **Rebuilding the SQLite Schema**: We dynamically reconstruct the exact 7 tables (e.g., `trajectory_meta`, `steps`) and indices required by the new `.db` structure. The parsed binary payloads are written into the database, seamlessly matching the new IDE's reading logic.
4. **Bypassing RESOURCE_EXHAUSTED Limit**: For large `.pb` files, we override the gRPC `max_receive_message_length` parameter to 100MB, completely resolving migration failures caused by oversized payloads.

### 🛠️ Preparation

1. **Python Environment**: Python 3.8 or higher is required.
2. **Install Dependencies**: Install `grpcio` and `protobuf` via pip:
   ```bash
   pip install -r requirements.txt
   ```
3. **Ensure Antigravity IDE is Running**:
   **【CRITICAL】** The Antigravity IDE must be OPEN while running this script. The script relies on the background Language Server to invoke the decryption algorithm and gRPC service.

### 🚀 How to Use

1. Launch Antigravity IDE.
2. Open a command prompt or terminal and run the script:
   ```bash
   python migrate_legacy_conversations.py
   ```
3. The script will automatically detect the current IDE port and CSRF Token, locate your backup folders, and perform the conversion.
4. Once completed, your legacy conversations will instantly appear in the IDE sidebar.

---

<a id="繁體中文"></a>
## 💮 繁體中文

此工具用於將舊版 Antigravity 的歷史對話紀錄（`.pb` Protobuf 檔案）一鍵自動移轉為新版 Antigravity IDE 專用的 SQLite 資料庫（`.db`），解決因架構升級導致歷史對話紀錄消失的問題。

### 💮 背景與核心問題分析

隨著 Antigravity 升級至新版 IDE 架構，底層儲存機制發生了重大變化：
1. **舊版機制**：所有對話軌跡使用 Protobuf 格式序列化並以二進位（`.pb`）檔案儲存於 `conversations/` 目錄中，且具備加密與特製結構。
2. **新版機制**：全面重構為 SQLite 關聯式資料庫架構（`.db`）。IDE 介面依賴掃描 `conversations/`目錄下的 `.db` 檔案來渲染側邊欄的歷史紀錄。
3. **發生障礙**：新版 IDE 並不具備開箱即用的「`.pb` 轉 `.db`」自動遷移機制，導致用戶原本存於 `antigravity-backup/conversations` 或是舊目錄的 `.pb` 歷史對話紀錄無法在 IDE 介面上顯示。

### 🔍 原理解析與突破

雖然新版 IDE 表面上不讀取 `.pb`，但我們透過深入分析新版 IDE 內建的 **Language Server**（語言伺服器二進位執行檔）後，發現以下突破點：

1. **隱藏的 gRPC 串流介面**：Language Server 仍保留了向後相容的解析邏輯。當透過本機 gRPC 發送 `/exa.language_server_pb.LanguageServerService/StreamAgentStateUpdates` 請求時，只要傳入對話的 UUID，Language Server 就會自動使用內部的金鑰對該 `.pb` 檔案進行解密，並將整份對話的歷史軌跡以 Protobuf 串流格式即時回傳。
2. **位元流還原（Raw Protobuf Parsing）**：由於外部環境缺乏官方的 `.proto` 定義檔，本專案實作了一套客製化的 Protobuf 位元流解碼器，成功捕捉並分離出串流中的關鍵節點（如 `gemini_coder.Step`、生成器與執行器元數據等）。
3. **重建 SQLite Schema**：對照新版 IDE 所使用的 `.db` 結構，我們透過 Python 自行建立完全吻合的 7 張資料表與必要的檢索索引。接著，將解析後的二進位 Payload 分別對應寫入資料庫中，完美還原了新版 IDE 的讀取邏輯。
4. **迴避資源耗盡（RESOURCE_EXHAUSTED）限制**：針對長篇對話所產生的大型 `.pb` 檔案，透過複寫 gRPC 的 `max_receive_message_length` 參數放大至 100MB，徹底解決因 Payload 過大而造成的移轉失敗。

### 🛠️ 事前準備

1. **Python 環境**：需安裝 Python 3.8 或以上版本。
2. **安裝必要套件**：請安裝 `grpcio` 與 `protobuf`。
   您可以透過以下指令安裝：
   ```bash
   pip install -r requirements.txt
   ```
3. **確認 Antigravity IDE 處於啟動狀態**：
   **【非常重要】** 在執行本腳本的過程中，Antigravity IDE 必須是開啟的！因為本腳本需要藉由本機背景正在運行的 Language Server 來調用解密演算法與 gRPC 服務。

### 🚀 如何使用

1. 啟動 Antigravity IDE。
2. 開啟命令提示字元或終端機，執行腳本：
   ```bash
   python migrate_legacy_conversations.py
   ```
3. 腳本會自動偵測目前的 IDE 連接埠與 CSRF Token，並開始進行轉換。
4. 轉換完成後，IDE 側邊欄將立刻顯示您所有的歷史對話紀錄。

---
*Created by Hanamiya Setsuri (花宮雪理) for Annelics-Senpai.*
