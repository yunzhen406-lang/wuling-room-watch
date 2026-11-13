#!/usr/bin/env python3
"""武陵國民賓館空房偵測器

查詢 https://whotel.wuling-farm.com.tw/whotel/ 在指定日期區間內是否有空房，
有新空房時寄 email 通知。只使用 Python 標準函式庫。

環境變數:
  START_DATE   要監看的第一晚 (預設 2027-02-13)
  END_DATE     要監看的最後一晚 (預設 2027-03-01)
  SMTP_USER    寄件 Gmail 帳號
  SMTP_PASS    Gmail 應用程式密碼 (App Password)
  MAIL_TO      收件者 (可用逗號分隔多個；預設同 SMTP_USER)
  SMTP_HOST    預設 smtp.gmail.com
  SMTP_PORT    預設 465
  STATE_FILE   記錄上次已通知內容的檔案 (預設 state.json)

用法:
  python3 check_rooms.py              # 查詢，有新空房就寄信
  python3 check_rooms.py --dry-run    # 只印出結果，不寄信
  python3 check_rooms.py --test-email # 寄一封測試信
"""

import datetime as dt
import html
import http.cookiejar
import json
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.request
from email.mime.text import MIMEText
from email.header import Header

BASE = "https://whotel.wuling-farm.com.tw/whotel/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
DELAY = 1.2  # 網站會擋太快的點擊，每個請求間隔一下


def ssl_context():
    ctx = ssl.create_default_context()
    # macOS 的 python.org 版 Python 預設沒有憑證，改用系統內建的 CA 檔
    if sys.platform == "darwin" and os.path.exists("/etc/ssl/cert.pem"):
        ctx.load_verify_locations("/etc/ssl/cert.pem")
    return ctx


def env_date(name, default):
    return dt.date.fromisoformat(os.environ.get(name) or default)


START = env_date("START_DATE", "2027-02-13")
END = env_date("END_DATE", "2027-03-01")


class Site:
    def __init__(self):
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            urllib.request.HTTPSHandler(context=ssl_context()))
        self.opener.addheaders = [("User-Agent", UA),
                                  ("Referer", BASE),
                                  ("Accept-Language", "zh-TW,zh;q=0.9")]

    def get(self, path, as_json=True):
        last = None
        for attempt in range(3):
            try:
                with self.opener.open(BASE + path, timeout=30) as r:
                    body = r.read().decode("utf-8", "replace")
                time.sleep(DELAY)
                return json.loads(body) if as_json else body
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"讀取 {path} 失敗: {last}")


def parse_month(h):
    m = re.search(r"民國(\d+)年(\d+)月", h)
    if not m:
        raise RuntimeError("看不懂行事曆頁面 (找不到月份)")
    return (int(m.group(1)) + 1911, int(m.group(2)))


def parse_days(h):
    """回傳 {日: 剩餘數量}；只包含可以點選的日子。"""
    days = {}
    for d, cell, cnt in re.findall(
            r"id='select_day(\d+)'>(.*?)</div><div><font[^>]*>\((.*?)\)</font>", h):
        if "calendar_day" in cell and cnt.isdigit():
            days[int(d)] = int(cnt)
    return days


def parse_rooms(h):
    """回傳 [(房型, 剩餘間數, 價格)]，只列出還有空房的。"""
    rooms = []
    for block in h.split("class='tt32'")[1:]:
        name = re.search(r"<font color='blue'>([^<]+)</font>", block)
        left = re.search(r"尚餘(\d+)間", block)
        price = re.search(r"NT\s*([\d,]+)", block)
        if name and left and int(left.group(1)) > 0:
            rooms.append((html.unescape(name.group(1)).strip(),
                          int(left.group(1)),
                          price.group(1) if price else "?"))
    return rooms


def months_needed():
    out, y, m = [], START.year, START.month
    while (y, m) <= (END.year, END.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def check():
    """回傳 (available, notes)
    available: {"YYYY-MM-DD": [(房型, 剩餘, 價格), ...]}
    notes: 狀態說明文字 list
    """
    site = Site()
    site.get("", as_json=False)
    cal = site.get("func_select.php?func=1")
    cur = parse_month(cal)

    available, notes = {}, []
    for target in months_needed():
        steps = 0
        while cur < target:
            cal = site.get("func_select.php?func=3")
            cur = parse_month(cal)
            steps += 1
            if steps > 24:
                raise RuntimeError("翻不到目標月份")
        if cur != target:
            raise RuntimeError(f"月份錯位: 目前 {cur}, 目標 {target}")

        y, m = target
        if "未開放訂房" in cal:
            notes.append(f"{y}年{m}月：尚未開放訂房")
            continue

        days = parse_days(cal)
        in_range = {d: c for d, c in days.items()
                    if START <= dt.date(y, m, d) <= END}
        if not in_range:
            notes.append(f"{y}年{m}月：區間內沒有可選的日期")
            continue
        notes.append(f"{y}年{m}月：" + " ".join(
            f"{d}日({c})" for d, c in sorted(in_range.items())))

        for d, c in sorted(in_range.items()):
            if c <= 0:
                continue
            page = site.get(f"change_date.php?number={d:02d}")
            rooms = parse_rooms(page)
            if not rooms:  # 行事曆有數字但房型頁抓不到細節，仍然通知
                rooms = [("(行事曆顯示有空房，請上網站確認)", c, "?")]
            available[dt.date(y, m, d).isoformat()] = rooms
    return available, notes


WEEK = "一二三四五六日"


def fmt(available):
    lines = []
    for day in sorted(available):
        d = dt.date.fromisoformat(day)
        lines.append(f"■ {d.month}/{d.day} (週{WEEK[d.weekday()]}) 入住")
        for name, left, price in available[day]:
            lines.append(f"    - {name}：剩 {left} 間，NT {price} 起")
    return "\n".join(lines)


def send_mail(subject, body):
    user = os.environ.get("SMTP_USER")
    pw = os.environ.get("SMTP_PASS")
    to = os.environ.get("MAIL_TO") or user
    if not (user and pw and to):
        print("⚠️  沒有設定 SMTP_USER / SMTP_PASS，略過寄信")
        return False
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    recipients = [a.strip() for a in to.split(",") if a.strip()]
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = user
    msg["To"] = ", ".join(recipients)
    with smtplib.SMTP_SSL(host, port, context=ssl_context(),
                          timeout=30) as s:
        s.login(user, pw.replace(" ", ""))
        s.sendmail(user, recipients, msg.as_string())
    print(f"📧 已寄信給 {len(recipients)} 位收件者")
    return True


def load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(path, state):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def main():
    args = set(sys.argv[1:])
    if "--test-email" in args:
        ok = send_mail("[武陵空房偵測] 測試信",
                       "這是一封測試信，代表 email 設定成功。\n"
                       f"監看區間：{START} ~ {END}（入住日）")
        sys.exit(0 if ok else 1)

    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    print(f"[{now:%Y-%m-%d %H:%M}] 監看 {START} ~ {END}")
    available, notes = check()
    for n in notes:
        print("  " + n)

    if not available:
        print("❌ 目前沒有空房")
    else:
        print("✅ 有空房！\n" + fmt(available))

    if "--dry-run" in args:
        return

    state_path = os.environ.get("STATE_FILE", "state.json")
    state = load_state(state_path)
    seen = set(state.get("seen", []))
    current = {f"{day}|{name}" for day, rooms in available.items()
               for name, _, _ in rooms}
    new = current - seen

    if new:
        new_days = sorted({k.split("|")[0] for k in new})
        subject = "[武陵空房] " + "、".join(
            f"{dt.date.fromisoformat(x).month}/{dt.date.fromisoformat(x).day}"
            for x in new_days) + " 有空房！"
        body = ("武陵國民賓館出現新的空房：\n\n" + fmt(available) +
                f"\n\n快去訂房：{BASE}\n\n"
                f"(查詢時間 {now:%Y-%m-%d %H:%M} 台灣時間；"
                "同一天同一房型只會通知一次，直到它被訂走後再出現)")
        send_mail(subject, body)
    else:
        print("沒有新的空房，不寄信")

    # 只記住「目前還在」的空房：被訂走後若再釋出會再通知一次
    save_state(state_path, {"seen": sorted(current),
                            "checked_at": now.isoformat()})


if __name__ == "__main__":
    main()
