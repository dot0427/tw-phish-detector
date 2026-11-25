"""
釣魚郵件偵測工具：Gradio 介面
執行：python3 app.py   → 瀏覽器打開 http://127.0.0.1:7860
需要：pip install gradio requests
"""
import html
import json
import re
from email import policy
from email.parser import BytesParser

import gradio as gr

from rules import check_email, extract_urls
from llm import check_with_llm, MODEL

RULE_WEIGHT, LLM_WEIGHT = 0.4, 0.6   # 綜合分數的權重，可以自己調


# ---------- .eml 解析 ----------
def parse_eml(file):
    if file is None:
        return "", "", "", "", ""
    with open(file, "rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = body_part.get_content() if body_part else ""
    body = re.sub(r"<[^>]+>", " ", body)            # 去掉 HTML 標籤
    body = re.sub(r"\s+\n", "\n", body).strip()
    urls = "\n".join(dict.fromkeys(extract_urls(body)))
    atts = "、".join(p.get_filename() or "" for p in msg.iter_attachments())
    sender = msg.get("From", "")
    m = re.search(r"<([^>]+)>", sender)
    return (m.group(1) if m else sender), msg.get("Subject", ""), body, urls, atts


# ---------- 畫面輸出 ----------
def highlight(text, phrases):
    safe = html.escape(text)
    for p in sorted({p for p in phrases if p and len(p) >= 2}, key=len, reverse=True):
        safe = safe.replace(html.escape(p), f"<mark>{html.escape(p)}</mark>")
    return safe.replace("\n", "<br>")


def verdict_badge(score):
    if score >= 45:
        return "🚨 釣魚", "#d93025"
    if score >= 25:
        return "⚠️ 可疑", "#e37400"
    return "✅ 正常", "#188038"


def analyze(sender, subject, body, urls, attachments, use_llm):
    if not (subject or body):
        return "<p>請先貼上信件內容或上傳 .eml</p>"

    rule = check_email(sender, subject, body, urls, attachments)
    llm = check_with_llm(sender, subject, body, urls, attachments) if use_llm else None

    if llm and "error" not in llm:
        final = round(RULE_WEIGHT * rule["score"] + LLM_WEIGHT * llm["confidence"])
        phrases = llm["suspicious_phrases"]
    else:
        final, phrases = rule["score"], []

    # 規則命中的關鍵字也一起標亮
    for r in rule["reasons"]:
        if "：" in r:
            phrases += re.split(r"[、，]", r.split("：", 1)[1])

    label, color = verdict_badge(final)
    rule_li = "".join(f"<li>{html.escape(x)}</li>" for x in rule["reasons"]) or "<li>沒有命中規則</li>"
    if llm is None:
        llm_block = "<p style='color:#888'>（未啟用 LLM）</p>"
    elif "error" in llm:
        llm_block = f"<p style='color:#d93025'>{html.escape(llm['error'])}</p>"
    else:
        llm_li = "".join(f"<li>{html.escape(x)}</li>" for x in llm["reasons"])
        llm_block = f"<p>判斷機率：<b>{llm['confidence']}</b> / 100</p><ul>{llm_li}</ul>"

    return f"""
<div style="font-family:system-ui;line-height:1.6">
  <div style="display:flex;align-items:center;gap:16px;margin-bottom:12px">
    <div style="font-size:44px;font-weight:800;color:{color}">{final}</div>
    <div><div style="font-size:22px;font-weight:700;color:{color}">{label}</div>
    <div style="color:#888;font-size:13px">綜合風險分數（規則 {int(RULE_WEIGHT*100)}% ＋ LLM {int(LLM_WEIGHT*100)}%）</div></div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
    <div style="border:1px solid #ddd;border-radius:10px;padding:12px">
      <b>第 1 層：規則檢查（{rule['score']} 分）</b><ul>{rule_li}</ul></div>
    <div style="border:1px solid #ddd;border-radius:10px;padding:12px">
      <b>第 2 層：LLM 判斷（{MODEL}）</b>{llm_block}</div>
  </div>
  <div style="border:1px solid #ddd;border-radius:10px;padding:12px;margin-top:12px">
    <b>可疑片段標示</b><p>{highlight(subject + chr(10) + body, phrases)}</p></div>
</div>"""


# ---------- 範例信（從 data.json 讀） ----------
def load_examples():
    try:
        rows = json.load(open("data.json", encoding="utf-8")).values()
        return [[r[4], r[3], r[5], r[6] or "", "", True] for r in rows]
    except Exception:
        return []


with gr.Blocks(title="台灣釣魚郵件偵測器") as demo:
    gr.Markdown("# 🎣 台灣釣魚郵件偵測器\n規則檢查 ＋ 本機 LLM，專門針對台灣在地中文釣魚信")
    with gr.Row():
        with gr.Column(scale=1):
            eml = gr.File(label="上傳 .eml（可選）", file_types=[".eml"])
            sender = gr.Textbox(label="寄件者")
            subject = gr.Textbox(label="主旨")
            body = gr.Textbox(label="內文", lines=10)
            urls = gr.Textbox(label="網址（可去武裝化：hxxps://evil[.]com）", lines=2)
            atts = gr.Textbox(label="附件檔名")
            use_llm = gr.Checkbox(label="啟用 LLM 判斷", value=True)
            btn = gr.Button("開始偵測", variant="primary")
        with gr.Column(scale=1):
            out = gr.HTML()
    eml.change(parse_eml, eml, [sender, subject, body, urls, atts])
    btn.click(analyze, [sender, subject, body, urls, atts, use_llm], out)
    ex = load_examples()
    if ex:
        gr.Examples(ex, [sender, subject, body, urls, atts, use_llm], label="測試信範例")

if __name__ == "__main__":
    demo.launch()
