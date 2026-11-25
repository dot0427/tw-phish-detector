"""
第 1 層：規則式釣魚郵件偵測（台灣在地化版）
用法：
    from rules import check_email
    result = check_email(sender, subject, body, urls)
    print(result["score"], result["verdict"], result["reasons"])
"""
import re
from urllib.parse import urlparse

# ---------- 名詞小抄 ----------
# defang（去武裝化）：把 https://evil.com 寫成 hxxps://evil[.]com，避免誤點
# TLD（頂級網域）：網址最後一段，例如 .com、.tw、.icu
# 編輯距離（Levenshtein distance）：把 A 字串改成 B 最少要改幾個字，用來抓 sh0pee 這種仿冒

# ---------- 名單 ----------
# 台灣常見機構的官方網域（之後可以自己擴充）
OFFICIAL_DOMAINS = {
    "shopee": "shopee.tw",
    "post": "post.gov.tw",
    "niu": "niu.edu.tw",
    "line": "line.me",
    "microsoft": "microsoft.com",
    "google": "google.com",
    "github": "github.com",
    "etax": "etax.nat.gov.tw",
    "1shop": "1shop.tw",
}
FREE_MAIL = {"gmail.com", "yahoo.com", "yahoo.com.tw", "yahoo.co.jp",
             "hotmail.com", "outlook.com", "icloud.com", "qq.com", "163.com"}
RISKY_TLDS = {"icu", "xyz", "top", "club", "online", "site", "buzz", "cn", "ru", "shop", "vip"}
RISKY_EXT = (".zip", ".rar", ".7z", ".exe", ".scr", ".js", ".html", ".htm", ".docm", ".xlsm", ".iso")

URGENCY = ["立即", "立刻", "盡快", "24 小時", "24小時", "48 小時", "48小時", "今日", "逾期", "停用",
           "暫停", "凍結", "強制執行", "刑事告訴", "未授權", "若非本人", "未曾下訂",
           "urgent", "immediately", "within 24 hours", "expire", "suspend", "permanently"]
MONEY = ["扣款", "分期", "退款", "刷卡", "信用卡", "金融卡", "銀行帳戶", "繳納", "罰鍰", "滯納金",
         "運費", "重新配送費", "refund", "payment", "credit card"]
CREDENTIAL = ["登入", "驗證", "更新密碼", "帳號", "密碼", "雙重認證", "verify", "password", "login", "sign in"]
GOV_WORDS = ["財政部", "國稅局", "納稅", "稅務", "監理", "法院", "地檢署", "警察局", "政府", "罰鍰"]
GENERIC_GREETING = ["親愛的客戶", "先生/小姐", "dear customer", "dear costumer", "親愛的用戶"]

# 只出現在簡體、繁體不會用的常見字（台灣信件夾雜這些 = 可疑）
SIMPLIFIED_ONLY = set("华礼务订单号码请账户费运输联发货时间该这们为让过还选择网络开关门问题业产东乐书买卖钱银")

LINE_ID = re.compile(r"(LINE|line|賴)\s*(ID)?\s*[:：]?\s*@?[A-Za-z0-9_]{5,}|@[a-z0-9]{6,9}\b")
INSTALLMENT = re.compile(r"[×xX*]\s*12|共\s*12\s*期|12\s*期")


# ---------- 工具函式 ----------
def refang(text: str) -> str:
    """把去武裝的網址還原，方便解析（只在程式裡用，不會去連線）"""
    return (text or "").replace("hxxp", "http").replace("[.]", ".")


def extract_urls(text: str):
    return re.findall(r"https?://[^\s（）()<>\"']+", refang(text))


def domain_of(url_or_mail: str) -> str:
    s = url_or_mail.strip().lower()
    if "@" in s and "://" not in s:
        return s.split("@")[-1]
    return (urlparse(s).hostname or "").removeprefix("www.")


def edit_distance(a: str, b: str) -> int:
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, dp[0] = dp[0], i
        for j, cb in enumerate(b, 1):
            prev, dp[j] = dp[j], min(dp[j] + 1, dp[j - 1] + 1, prev + (ca != cb))
    return dp[-1]


def normalize_homoglyph(s: str) -> str:
    """把常見的偽裝字元換回來：0→o、1→l、rn→m"""
    return s.replace("0", "o").replace("1", "l").replace("rn", "m")


def is_official(domain: str) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in OFFICIAL_DOMAINS.values())


def lookalike(domain: str):
    """網域裡出現品牌字（或仿冒字）但不是官方網域 → 回傳被仿冒的品牌"""
    if is_official(domain):
        return None
    # 用 - 取代 . 的仿冒：niu-edu-tw.test 還原後會包含 niu.edu.tw
    dotted = domain.replace("-", ".")
    for brand, official in OFFICIAL_DOMAINS.items():
        if official in dotted:
            return brand
    norm = normalize_homoglyph(domain)
    for token in re.split(r"[.\-]", norm):
        for brand in OFFICIAL_DOMAINS:
            if len(brand) >= 4 and (token == brand or edit_distance(token, brand) == 1):
                return brand
    if "line" in norm.split(".")[0]:
        return "line"
    return None


# ---------- 主程式 ----------
def check_email(sender: str, subject: str, body: str, urls: str = "", attachments: str = ""):
    reasons = []  # (分數, 說明)
    text = f"{subject}\n{body}"
    low = text.lower()
    s_dom = domain_of(sender or "")

    # 1. 寄件者
    if s_dom in FREE_MAIL:
        reasons.append((15, f"用免費信箱寄信（{s_dom}），卻自稱商家／機構"))
    if s_dom.endswith(".jp") and re.search(r"[一-鿿]", text):
        reasons.append((10, "寄件網域在日本，內容卻是台灣中文商家"))
    brand = lookalike(s_dom)
    if brand:
        reasons.append((25, f"寄件網域疑似仿冒「{brand}」（{s_dom}）"))
    if any(w in text for w in GOV_WORDS) and not s_dom.endswith(".gov.tw"):
        reasons.append((20, "自稱政府／法務單位，但寄件者不是 .gov.tw"))

    # 2. 網址
    all_urls = extract_urls(urls) + extract_urls(body)
    for u in dict.fromkeys(all_urls):
        d = domain_of(u)
        if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", d):
            reasons.append((25, f"網址直接用 IP（{d}）"))
            continue
        b = lookalike(d)
        if b:
            reasons.append((25, f"連結網域疑似仿冒「{b}」（{d}）"))
        tld = d.rsplit(".", 1)[-1]
        if tld in RISKY_TLDS:
            reasons.append((15, f"連結使用高風險網域結尾 .{tld}"))
        if u.lower().split("?")[0].endswith(RISKY_EXT):
            reasons.append((20, "連結直接下載壓縮檔／執行檔"))
        if s_dom and d and not is_official(d) and d != s_dom and not d.endswith(s_dom):
            reasons.append((5, f"連結網域（{d}）和寄件網域（{s_dom}）不同"))

    # 3. 內容話術
    hits = [w for w in URGENCY if w.lower() in low]
    if hits:
        reasons.append((min(10 + 5 * len(hits), 25), f"急迫／恐嚇話術：{'、'.join(hits[:4])}"))
    hits = [w for w in MONEY if w.lower() in low]
    if hits:
        reasons.append((10, f"涉及金錢：{'、'.join(hits[:4])}"))
    hits = [w for w in CREDENTIAL if w.lower() in low]
    if hits and all_urls:
        reasons.append((10, f"要求點連結登入／驗證：{'、'.join(hits[:3])}"))
    if LINE_ID.search(text):
        reasons.append((25, "引導加 LINE 處理（正規客服很少這樣做）"))
    if INSTALLMENT.search(text):
        reasons.append((15, "出現 ×12／12 期分期扣款（解除分期詐騙常見）"))
    if any(g in low for g in GENERIC_GREETING):
        reasons.append((5, "通用稱呼，沒有叫你的名字"))
    simp = sorted({c for c in text if c in SIMPLIFIED_ONLY})
    if simp and len(re.findall(r"[一-鿿]", text)) > 20:
        reasons.append((15, f"繁體信件夾雜簡體字：{''.join(simp)}"))

    # 4. 附件
    if any(a.strip().lower().endswith(RISKY_EXT) for a in re.split(r"[、,，]", attachments or "")):
        reasons.append((20, "附件是壓縮檔／可執行檔"))

    # 5. 白名單：寄件者和所有連結都是官方網域 → 降分
    if is_official(s_dom) and all(is_official(domain_of(u)) for u in all_urls):
        reasons.append((-30, f"寄件者與連結都是官方網域（{s_dom}）"))

    score = max(min(sum(p for p, _ in reasons), 100), 0)
    verdict = "釣魚" if score >= 40 else ("可疑" if score >= 20 else "正常")
    return {"score": score, "verdict": verdict,
            "reasons": [r for _, r in sorted(reasons, reverse=True)]}
