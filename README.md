# 武陵國民賓館空房偵測

每 5 分鐘查詢 [武陵國民賓館訂房系統](https://whotel.wuling-farm.com.tw/whotel/)，
2027/2/4 ~ 2027/3/1 任一晚出現空房就寄 email 通知。

- 同一天、同一房型只通知一次；被訂走後再釋出會再通知。
- 要改日期：編輯 `.github/workflows/check.yml` 裡的 `START_DATE` / `END_DATE`。

## 設定 (Settings → Secrets and variables → Actions)

| Secret | 內容 |
|---|---|
| `SMTP_USER` | 寄件的 Gmail 帳號 |
| `SMTP_PASS` | Gmail 應用程式密碼 (https://myaccount.google.com/apppasswords) |
| `MAIL_TO`   | 收件者 email，可用逗號分隔多個 |

設定好後到 Actions → 武陵空房偵測 → Run workflow，勾選「寄一封測試信」確認能收到信。

## 本機執行

```bash
python3 check_rooms.py --dry-run
```
