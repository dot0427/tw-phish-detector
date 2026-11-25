"""
實驗 B：繞過測試（對抗式測試，Adversarial Testing）
問題：如果詐騙集團知道我們的規則，稍微改寫信件，偵測器還抓得到嗎？

做法：把資料集裡的「釣魚信」套上幾種改寫手法，再交給規則和 LLM 判斷。
只改寫已去武裝化的現有樣本，網址都是假的，不會產生能用的詐騙信。

執行：python3 attack.py              （預設 LLM 用 zero-shot）
     python3 attack.py --few-shot   （改用 few-shot）
     python3 attack.py --no-llm   （只測規則）
輸出：results/attack_summary.csv
"""
import csv
import re
import sys

from rules import check_email
from evaluate import load_emails, llm_score

FULLWIDTH = str.maketrans("@0123456789", "＠０１２３４５６７８９")


def evade_line(e):
    """把 LINE 換成台灣常見的替代寫法"""
    t = lambda s: re.sub(r"LINE|line", "賴", s)
    return {**e, "body": t(e["body"]), "subject": t(e["subject"])}


def evade_fullwidth(e):
    """@ 和數字改成全形，躲過半形的正規表示式"""
    return {**e, "body": e["body"].translate(FULLWIDTH)}


def evade_installment(e):
    """不寫「×12／12 期」，改用口語說法"""
    t = lambda s: re.sub(r"[×xX*]\s*12|共\s*12\s*期|12\s*期", "，每月固定扣款，為期一年", s)
    return {**e, "body": t(e["body"])}


def evade_urgency(e):
    """拿掉急迫字眼，語氣改得很客氣"""
    words = ["立即", "立刻", "盡快", "24 小時內", "24小時內", "48 小時內", "48小時內", "今日", "逾期",
             "強制執行", "刑事告訴", "停用"]
    b = e["body"]
    for w in words:
        b = b.replace(w, "")
    return {**e, "body": b + "\n如有任何問題，歡迎您有空時與我們聯繫，祝您順心。"}


def evade_no_link(e):
    """不放連結（改叫收件人「掃描附件 QR Code」），讓網址規則無從檢查"""
    return {**e, "urls": "", "body": re.sub(r"h[tx]{2}ps?://\S+", "", e["body"]) + "\n請掃描附件中的 QR Code 完成驗證。"}


def evade_all(e):
    for f in (evade_line, evade_fullwidth, evade_installment, evade_urgency, evade_no_link):
        e = f(e)
    return e


ATTACKS = {
    "原始信件": lambda e: e,
    "LINE→賴": evade_line,
    "全形字元": evade_fullwidth,
    "不寫×12": evade_installment,
    "拿掉急迫字眼": evade_urgency,
    "不放連結": evade_no_link,
    "全部一起": evade_all,
}


def main():
    use_llm = "--no-llm" not in sys.argv
    few = "--few-shot" in sys.argv
    out = "results/attack_summary_fewshot.csv" if few else "results/attack_summary.csv"
    phish = [e for e in load_emails() if e["label"] == "釣魚"]
    n = len(phish)
    rows = []
    for name, attack in ATTACKS.items():
        hit_r = hit_l = hit_c = 0
        for e in phish:
            v = attack(dict(e))
            r = check_email(v["sender"], v["subject"], v["body"], v["urls"], v["att"])["score"]
            hit_r += r >= 40
            if use_llm:
                print(f"{name}｜{e['id']} …")
                l = llm_score(v, few_shot=few) or 0
                hit_l += l >= 50
                hit_c += (r >= 70 or l >= 70 or 0.4 * r + 0.6 * l >= 45)
        row = {"改寫手法": name, "規則抓到": f"{hit_r}/{n}"}
        if use_llm:
            row.update({"LLM 抓到": f"{hit_l}/{n}", "合併（信心優先）抓到": f"{hit_c}/{n}"})
        rows.append(row)

    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print()
    for r in rows:
        print("  ".join(f"{k}：{v}" for k, v in r.items()))
    print(f"\n結果已存到 {out}")


if __name__ == "__main__":
    main()
