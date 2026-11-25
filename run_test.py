import json, re
from rules import check_email
rows = json.load(open("data.json", encoding="utf-8"))
ok = 0
for r in rows.values():
    id_, label, cat, subj, sender, body, url = r
    att = "、".join(re.findall(r"[\w\s]+\.(?:pdf|docx|zip)", body))
    res = check_email(sender, subj, body, url or "", att)
    pred = "釣魚" if res["verdict"] != "正常" else "正常"
    hit = pred == label; ok += hit
    print(f"{'✅' if hit else '❌'} {id_} [{label}] → {res['verdict']} ({res['score']})")
    for x in res["reasons"][:4]: print("     ·", x)
print(f"\n正確 {ok}/{len(rows)}")
