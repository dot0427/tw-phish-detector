"""
實驗 A：消融實驗（Ablation Study）
問題：規則、LLM、不同合併方式，各自表現如何？few-shot 有沒有幫助？

執行：python3 evaluate.py            （第一次會呼叫 LLM，比較久；結果會快取）
     python3 evaluate.py --no-llm   （只跑規則，快速檢查用）
輸出：results/ablation_detail.csv（每封信的分數）
     results/ablation_summary.csv（各方法的偵測率／誤判率）

名詞小抄
- 消融實驗：把系統的某個部分拿掉，看表現掉多少，藉此知道每個部分的貢獻
- 偵測率（Recall）：釣魚信中被抓到的比例 = TP / (TP + FN)
- 誤判率（False Positive Rate）：正常信中被誤判成釣魚的比例 = FP / (FP + TN)
- TP 抓對的釣魚、FN 漏掉的釣魚、FP 冤枉的正常信、TN 放行的正常信
"""
import csv
import hashlib
import json
import os
import re
import sys

from rules import check_email
from llm import check_with_llm, MODEL

CACHE_FILE = "results/llm_cache.json"
os.makedirs("results", exist_ok=True)


# ---------- 共用工具 ----------
def load_emails(path="data.json"):
    rows = json.load(open(path, encoding="utf-8")).values()
    emails = []
    for r in rows:
        id_, label, cat, subj, sender, body, url = r[:7]
        att = "、".join(re.findall(r"[\w\s一-鿿]+\.(?:pdf|docx|zip|rar|exe|html)", body or ""))
        emails.append(dict(id=id_, label=label, cat=cat, subject=subj or "", sender=sender or "",
                           body=body or "", urls=url or "", att=att))
    return emails


def _load_cache():
    try:
        return json.load(open(CACHE_FILE, encoding="utf-8"))
    except Exception:
        return {}


_cache = _load_cache()


def llm_score(e, few_shot=False):
    """回傳 LLM 的釣魚機率（0–100），失敗回傳 None。同一封信＋同一設定只會問一次。"""
    key_src = json.dumps([MODEL, few_shot, e["sender"], e["subject"], e["body"], e["urls"], e["att"]],
                         ensure_ascii=False)
    key = hashlib.sha1(key_src.encode()).hexdigest()
    if key not in _cache:
        res = check_with_llm(e["sender"], e["subject"], e["body"], e["urls"], e["att"], few_shot=few_shot)
        if "error" in res:
            print("  ⚠️", e["id"], res["error"])
            return None
        _cache[key] = res
        json.dump(_cache, open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return _cache[key]["confidence"]


# ---------- 合併策略 ----------
STRATEGIES = {
    "只用規則":   lambda r, l: r >= 40,
    "只用 LLM":   lambda r, l: l >= 50,
    "加權平均":   lambda r, l: 0.4 * r + 0.6 * l >= 45,
    "取最大值":   lambda r, l: max(r, l) >= 45,
    "信心優先":   lambda r, l: r >= 70 or l >= 70 or 0.4 * r + 0.6 * l >= 45,
}
# 信心優先：任一層「非常有把握」就直接判釣魚，否則才看平均 → 避免弱的一層拖垮強的一層


def metrics(preds, labels):
    tp = sum(p and l for p, l in zip(preds, labels))
    fn = sum((not p) and l for p, l in zip(preds, labels))
    fp = sum(p and (not l) for p, l in zip(preds, labels))
    tn = sum((not p) and (not l) for p, l in zip(preds, labels))
    rec = tp / (tp + fn) if tp + fn else 0
    fpr = fp / (fp + tn) if fp + tn else 0
    acc = (tp + tn) / len(labels) if labels else 0
    return dict(TP=tp, FN=fn, FP=fp, TN=tn, 偵測率=rec, 誤判率=fpr, 準確率=acc)


def main():
    use_llm = "--no-llm" not in sys.argv
    emails = load_emails()
    labels = [e["label"] == "釣魚" for e in emails]

    detail = []
    for e in emails:
        r = check_email(e["sender"], e["subject"], e["body"], e["urls"], e["att"])["score"]
        row = dict(id=e["id"], 標籤=e["label"], 類別=e["cat"], 規則=r)
        if use_llm:
            print(f"判斷中 {e['id']} …")
            row["LLM_zero"] = llm_score(e, few_shot=False)
            row["LLM_few"] = llm_score(e, few_shot=True)
        detail.append(row)

    with open("results/ablation_detail.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(detail[0].keys()))
        w.writeheader(); w.writerows(detail)

    summary = []
    prompt_modes = [("zero-shot", "LLM_zero"), ("few-shot", "LLM_few")] if use_llm else [("—", None)]
    for name, fn in STRATEGIES.items():
        for mode, col in prompt_modes:
            if name == "只用規則" and mode == "few-shot":
                continue  # 規則不受提示詞影響
            if col is None and name != "只用規則":
                continue
            preds = []
            for d in detail:
                l = d.get(col) if col else 0
                l = 0 if l is None else l
                preds.append(fn(d["規則"], l))
            m = metrics(preds, labels)
            summary.append(dict(方法=name, 提示詞=mode if name != "只用規則" else "—", **m))

    with open("results/ablation_summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader(); w.writerows(summary)

    print(f"\n{'方法':<8}{'提示詞':<11}{'偵測率':>7}{'誤判率':>7}{'準確率':>7}   TP FN FP TN")
    for s in summary:
        print(f"{s['方法']:<8}{s['提示詞']:<11}{s['偵測率']:>7.0%}{s['誤判率']:>7.0%}{s['準確率']:>7.0%}"
              f"   {s['TP']:>2} {s['FN']:>2} {s['FP']:>2} {s['TN']:>2}")
    print("\n結果已存到 results/ 資料夾")


if __name__ == "__main__":
    main()
