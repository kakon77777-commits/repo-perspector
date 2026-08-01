# Security Notes

- 工具只讀取檔案、Git metadata 與 manifest；不執行被分析 Repository 的程式碼、安裝腳本、測試或建置命令。
- Python AST 解析不會 import 被分析模組。
- Git clone 與 ZIP 解壓仍涉及外部內容；不可信 Repository 建議放在隔離環境處理。
- MCP Server 是唯讀接口，只載入指定的 `architecture.json`。
- STDIO MCP 模式保留 stdout 給 JSON-RPC frame，日誌輸出至 stderr。
- SARIF、HTML 與 JSON 報告可能含檔案路徑、函式名稱、import 行摘錄與架構證據；公開前應檢查是否洩漏私人程式碼或內部結構。
- `.perspector.yml/.json` 只作為資料解析，不執行任意程式碼。
- 下載 GitHub Repository 時，工具不會自動使用 Repository 內的 credentials 或 secrets。
