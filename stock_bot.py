"""
Stock Monitor + Auto Buy Bot (Railway ready)
সব সেটিংস Railway এর Variables থেকে আসে। কোডে কিছু বদলাতে হবে না।
"""
import os
import time
import json
from datetime import datetime

import requests

# ================== সেটিংস (Railway Variables) ==================
API_KEY       = os.environ.get("API_KEY", "").strip()
PRODUCT_ID    = os.environ.get("PRODUCT_ID", "").strip()
BASE_URL      = os.environ.get("BASE_URL", "https://codecraftdeveloper.com/api").rstrip("/")
MAX_BUY       = int(os.environ.get("MAX_BUY", "1000"))
COUPON        = os.environ.get("COUPON", "")
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "0.5"))
MODE          = os.environ.get("MODE", "run").lower()          # "run" অথবা "inspect"

TG_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# স্টক ফিল্ডের নাম জানলে STOCK_KEY ভ্যারিয়েবলে দিন, সেটা আগে খোঁজা হবে
STOCK_KEYS = [k for k in [os.environ.get("STOCK_KEY", "").strip().lower()] if k] + [
    "stock", "amount", "quantity", "qty", "so_luong", "soluong",
    "remain", "available", "con_lai", "total"]
# ================================================================

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 StockBot/1.0"})


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


# ---------------- Telegram ----------------
def tg_send(text):
    if not (TG_TOKEN and TG_CHAT_ID):
        return
    try:
        for i in range(0, len(text), 3500):          # Telegram এর 4096 অক্ষরের লিমিট
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                          data={"chat_id": TG_CHAT_ID, "text": text[i:i + 3500]},
                          timeout=10)
    except requests.RequestException as e:
        log(f"Telegram error: {e}")


def tg_send_file(filename, content, caption=""):
    if not (TG_TOKEN and TG_CHAT_ID):
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendDocument",
                      data={"chat_id": TG_CHAT_ID, "caption": caption[:1000]},
                      files={"document": (filename, content.encode("utf-8"))},
                      timeout=20)
    except requests.RequestException as e:
        log(f"Telegram file error: {e}")
        tg_send(caption + "\n\n" + content)        # ফাইল না গেলে টেক্সট হিসেবে পাঠাবে


# ---------------- API ----------------
def find_stock(obj):
    if isinstance(obj, dict):
        for key in STOCK_KEYS:
            for k, v in obj.items():
                if k.lower() == key:
                    try:
                        return int(float(v))
                    except (TypeError, ValueError):
                        pass
        for v in obj.values():
            found = find_stock(v)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_stock(item)
            if found is not None:
                return found
    return None


def get_product():
    r = session.get(f"{BASE_URL}/product.php",
                    params={"api_key": API_KEY, "product": PRODUCT_ID, "id": PRODUCT_ID},
                    timeout=5)
    if r.status_code == 429:
        raise RuntimeError("rate-limited")
    return r.json()


def buy(amount):
    r = session.post(f"{BASE_URL}/buy_product", data={
        "action": "buyProduct",
        "id": PRODUCT_ID,
        "amount": amount,
        "coupon": COUPON,
        "api_key": API_KEY,
    }, timeout=10)
    return r.json()


def handle_success(resp, qty, total):
    items = resp.get("data") or []
    if isinstance(items, str):
        items = [items]
    trans_id = resp.get("trans_id", "")
    content = "\n".join(str(x) for x in items)

    # Railway Logs এ ব্যাকআপ হিসেবে প্রিন্ট
    log(f"✅ কেনা হয়েছে {qty}টা | মোট {total} | trans_id: {trans_id}")
    print("----- DATA START -----\n" + content + "\n----- DATA END -----", flush=True)

    caption = f"✅ কেনা হয়েছে {qty}টা\nমোট: {total}\ntrans_id: {trans_id}"
    tg_send_file(f"order_{trans_id or int(time.time())}.txt", content or "(empty)", caption)


# ---------------- Modes ----------------
def inspect():
    try:
        data = get_product()
        text = json.dumps(data, indent=2, ensure_ascii=False)
    except Exception as e:
        text = f"Error: {e}"
        data = None
    print(text, flush=True)
    stock = find_stock(data) if data else None
    log(f"খুঁজে পাওয়া স্টক: {stock}")
    tg_send(f"🔍 Inspect result (stock={stock}):\n\n{text}")
    # Railway বারবার restart না করে তাই চুপচাপ বসে থাকবে
    while True:
        time.sleep(3600)


def run():
    bought = 0
    errors = 0
    log(f"বট চালু — Product {PRODUCT_ID}, প্রতি {POLL_INTERVAL}s এ চেক, সর্বোচ্চ {MAX_BUY}টা")
    tg_send(f"🤖 বট চালু হয়েছে\nProduct: {PRODUCT_ID}\nচেক: প্রতি {POLL_INTERVAL}s")

    last_heartbeat = time.time()
    while bought < MAX_BUY:
        try:
            stock = find_stock(get_product())
            errors = 0

            if time.time() - last_heartbeat > 600:    # প্রতি ১০ মিনিটে Logs এ জীবিত থাকার সংকেত
                log(f"চলছে... স্টক এখন: {stock} | মোট কেনা: {bought}")
                last_heartbeat = time.time()

            if not stock or stock <= 0:
                time.sleep(POLL_INTERVAL)
                continue

            qty = min(stock, MAX_BUY - bought)
            log(f"🔥 স্টক এসেছে: {stock} → {qty}টা কেনার চেষ্টা...")
            resp = buy(qty)

            if resp.get("status") == "success":
                bought += qty
                handle_success(resp, qty, bought)
            else:
                log(f"❌ ব্যর্থ: {resp.get('msg')}")
                if qty > 1:
                    half = max(1, qty // 2)
                    resp = buy(half)
                    if resp.get("status") == "success":
                        bought += half
                        handle_success(resp, half, bought)
                    else:
                        log(f"❌ আবারও ব্যর্থ: {resp.get('msg')}")
        except RuntimeError:
            log("⚠️ Rate limit — 10s অপেক্ষা")
            time.sleep(10)
        except (requests.RequestException, ValueError) as e:
            errors += 1
            log(f"⚠️ Error: {e}")
            if errors == 20:
                tg_send(f"⚠️ বট টানা ২০ বার error পেয়েছে: {e}")
            time.sleep(min(POLL_INTERVAL * errors, 15))

    log("MAX_BUY পূর্ণ হয়েছে।")
    tg_send(f"🏁 MAX_BUY ({MAX_BUY}) পূর্ণ, বট থেমে গেছে।")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    if not API_KEY or not PRODUCT_ID:
        log("❗ API_KEY আর PRODUCT_ID Railway Variables এ দিন।")
        while True:
            time.sleep(3600)
    inspect() if MODE == "inspect" else run()
