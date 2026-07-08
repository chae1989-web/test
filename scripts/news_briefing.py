#!/usr/bin/env python3
"""Daily SKTI industry news briefing: collect -> score -> write insight -> email (auto-send).

Requires env vars:
  EXA_API_KEY          Exa search API key
  ANTHROPIC_API_KEY    Claude API key (classification + insight writing)
  GMAIL_ADDRESS        Sender Gmail address
  GMAIL_APP_PASSWORD   Gmail app password (SMTP)
  MAIL_TO              Recipient address (default: bbd.chae@sk.com)
  ANTHROPIC_MODEL      Optional model override (default: claude-sonnet-5)
"""

import json
import os
import re
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import requests
from anthropic import Anthropic

KST = ZoneInfo("Asia/Seoul")
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
EXA_API_URL = "https://api.exa.ai/search"

SUBSIDIARY = "SKTI(SK온 트레이딩인터내셔널)"

SEARCH_QUERIES = [
    "원유 트레이딩 정제마진 유조선 운임",
    "배터리 광물 리튬 니켈 코발트 메탈 트레이딩",
    "ADNOC Aramco Vitol Trafigura Glencore 원유 뉴스",
    "SK에너지 GS칼텍스 에쓰오일 정유 뉴스",
    "OPEC+ WTI 두바이유 브렌트유 유가",
    "Albemarle Ganfeng Lithium 화유코발트 CATL 배터리 소재",
]
SUPPLEMENTAL_QUERY = "원유 정유 배터리 광물 트레이딩 에너지 자원 뉴스"

CATEGORIES = [
    "유가/원유 시장",
    "정유·석유제품",
    "배터리 광물/메탈 트레이딩",
    "에너지·자원 정책/제재",
    "해운/물류(운임, 벙커링)",
    "경쟁 트레이더·SK온 연계 동향",
]
CATEGORY_COLORS = {
    CATEGORIES[0]: "#2563eb",
    CATEGORIES[1]: "#7c3aed",
    CATEGORIES[2]: "#059669",
    CATEGORIES[3]: "#dc2626",
    CATEGORIES[4]: "#0891b2",
    CATEGORIES[5]: "#d97706",
}
MAX_ARTICLES = 15
MIN_ARTICLES = 8


def get_time_window() -> tuple[datetime, datetime]:
    now_kst = datetime.now(KST)
    end = now_kst.replace(hour=9, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=1)
    return start, end


def _exa_search(api_key: str, query: str, start: datetime, end: datetime, num_results: int) -> list[dict]:
    resp = requests.post(
        EXA_API_URL,
        headers={"x-api-key": api_key, "content-type": "application/json"},
        json={
            "query": query,
            "numResults": num_results,
            "startPublishedDate": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endPublishedDate": end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "type": "neural",
            "contents": {"text": {"maxCharacters": 600}},
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def _within_window(raw: dict, start: datetime, end: datetime) -> datetime | None:
    pub = raw.get("publishedDate")
    if not pub:
        return None
    try:
        pub_dt = datetime.fromisoformat(pub.replace("Z", "+00:00")).astimezone(KST)
    except ValueError:
        return None
    return pub_dt if start <= pub_dt < end else None


def search_news(start: datetime, end: datetime) -> list[dict]:
    api_key = os.environ["EXA_API_KEY"]
    seen: dict[str, dict] = {}

    for query in SEARCH_QUERIES:
        for raw in _exa_search(api_key, query, start, end, num_results=10):
            url = raw.get("url")
            if not url or url in seen:
                continue
            pub_dt = _within_window(raw, start, end)
            if pub_dt is None:
                continue
            raw["_published_kst"] = pub_dt
            seen[url] = raw

    if len(seen) < MIN_ARTICLES:
        for raw in _exa_search(api_key, SUPPLEMENTAL_QUERY, start, end, num_results=25):
            url = raw.get("url")
            if not url or url in seen:
                continue
            pub_dt = _within_window(raw, start, end)
            if pub_dt is None:
                continue
            raw["_published_kst"] = pub_dt
            seen[url] = raw

    articles = sorted(seen.values(), key=lambda a: a["_published_kst"], reverse=True)
    return articles[:MAX_ARTICLES]


def _extract_json(text: str):
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    payload = match.group(1) if match else text
    return json.loads(payload.strip())


def classify_and_score(client: Anthropic, articles: list[dict]) -> list[dict]:
    items = [
        {
            "idx": i,
            "title": a.get("title", ""),
            "url": a.get("url", ""),
            "published_kst": a["_published_kst"].strftime("%Y-%m-%d %H:%M"),
            "snippet": (a.get("text") or "")[:500],
        }
        for i, a in enumerate(articles)
    ]
    prompt = f"""당신은 {SUBSIDIARY}의 산업 뉴스 분석가입니다.
아래 기사 목록 각각에 대해 다음 6개 카테고리 중 하나를 부여하고, 산업 전반 영향력·{SUBSIDIARY} 관련성·시장/정책 파급력을
종합한 impact_score(1~10 정수)를 매기고, 15자 내외의 한국어 한 줄 요약(summary)을 작성하세요.

카테고리: {json.dumps(CATEGORIES, ensure_ascii=False)}

기사 목록:
{json.dumps(items, ensure_ascii=False, indent=2)}

반드시 아래 JSON 배열 형식으로만 응답하세요 (다른 설명 텍스트 금지):
[{{"idx": 0, "category": "...", "impact_score": 7, "summary": "..."}}, ...]
"""
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_json(resp.content[0].text)


def write_insight(client: Anthropic, top_article: dict) -> str:
    prompt = f"""당신은 {SUBSIDIARY}의 산업 분석가입니다. 아래 기사를 바탕으로 600~700단어 분량의
한국어 인사이트를 작성하세요.

기사 제목: {top_article.get('title', '')}
기사 URL: {top_article.get('url', '')}
기사 요약/본문 일부: {(top_article.get('text') or '')[:1500]}

반드시 아래 4개 소제목을 '## ' 마크다운 헤더 형식으로 포함하세요:
## 배경
## 핵심 내용
## 산업 영향
## {SUBSIDIARY} 관점에서의 시사점

수치, 핵심 키워드, 중요 판단은 **굵게** 표시하세요. 마크다운 텍스트로만 응답하세요.
"""
    resp = client.messages.create(
        model=MODEL,
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


def _markdown_to_html(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    lines = text.strip().splitlines()
    html_parts = []
    paragraph: list[str] = []

    def flush():
        if paragraph:
            html_parts.append(f"<p style='margin:0 0 14px;line-height:1.7;color:#1f2937;'>{' '.join(paragraph)}</p>")
            paragraph.clear()

    for line in lines:
        line = line.strip()
        if not line:
            flush()
            continue
        if line.startswith("## "):
            flush()
            html_parts.append(
                f"<h3 style='margin:20px 0 8px;font-size:16px;color:#0f172a;'>{line[3:].strip()}</h3>"
            )
        else:
            paragraph.append(line)
    flush()
    return "\n".join(html_parts)


def _impact_dot(score: int) -> str:
    color = "#dc2626" if score >= 8 else "#d97706" if score >= 5 else "#16a34a"
    return f"<span style='display:inline-block;width:9px;height:9px;border-radius:50%;background:{color};margin-right:6px;'></span>"


def render_html(articles: list[dict], insight_md: str, top_article: dict, date_str: str) -> str:
    insight_html = _markdown_to_html(insight_md)

    rows = []
    for a in articles:
        category = a.get("category", CATEGORIES[0])
        color = CATEGORY_COLORS.get(category, "#64748b")
        score = a.get("impact_score", 0)
        rows.append(f"""
        <tr>
          <td style="padding:10px 8px;border-bottom:1px solid #e5e7eb;white-space:nowrap;">
            {_impact_dot(score)}<span style="font-size:13px;color:#374151;">{score}</span>
          </td>
          <td style="padding:10px 8px;border-bottom:1px solid #e5e7eb;">
            <span style="display:inline-block;padding:2px 8px;border-radius:10px;background:{color}1a;color:{color};font-size:11px;font-weight:600;">{category}</span>
          </td>
          <td style="padding:10px 8px;border-bottom:1px solid #e5e7eb;">
            <a href="{a.get('url', '#')}" style="color:#0f172a;text-decoration:none;font-size:13px;font-weight:500;">{a.get('title', '')}</a><br/>
            <span style="color:#6b7280;font-size:11px;">{a.get('summary', '')} · {a['_published_kst'].strftime('%m/%d %H:%M')}</span>
          </td>
        </tr>""")

    return f"""
<div style="max-width:680px;margin:0 auto;font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;background:#f8fafc;padding:24px 16px;">
  <div style="background:#0f172a;border-radius:12px 12px 0 0;padding:20px 24px;">
    <div style="color:#93c5fd;font-size:12px;font-weight:600;letter-spacing:.06em;">AI MORNING BRIEF</div>
    <div style="color:#ffffff;font-size:20px;font-weight:700;margin-top:4px;">{date_str} 원유·정유·배터리 광물 트레이딩 동향</div>
  </div>

  <div style="background:#ffffff;padding:24px;">
    <div style="border:1px solid #e5e7eb;border-radius:10px;padding:18px 20px;margin-bottom:24px;">
      <div style="font-size:11px;font-weight:700;color:#2563eb;letter-spacing:.05em;margin-bottom:6px;">TOP STORY</div>
      <a href="{top_article.get('url', '#')}" style="color:#0f172a;font-size:16px;font-weight:700;text-decoration:none;">{top_article.get('title', '')}</a>
      <div style="margin-top:12px;">{insight_html}</div>
    </div>

    <div style="font-size:13px;font-weight:700;color:#0f172a;margin-bottom:8px;">전체 기사 ({len(articles)}건, 중요도순)</div>
    <table style="width:100%;border-collapse:collapse;">
      {''.join(rows)}
    </table>
  </div>

  <div style="background:#f1f5f9;border-radius:0 0 12px 12px;padding:16px 24px;color:#94a3b8;font-size:11px;">
    이 메일은 {SUBSIDIARY} 대상 자동 생성된 뉴스 브리핑입니다.
  </div>
</div>
"""


def send_email(subject: str, html_body: str, to_addr: str) -> None:
    sender = os.environ["GMAIL_ADDRESS"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_addr
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, os.environ["GMAIL_APP_PASSWORD"])
        server.send_message(msg)


def main() -> None:
    start, end = get_time_window()
    articles = search_news(start, end)
    if not articles:
        print(f"수집 기간({start} ~ {end}) 내 기사를 찾지 못했습니다.", file=sys.stderr)
        sys.exit(1)

    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    scored = classify_and_score(client, articles)
    for item in scored:
        idx = item["idx"]
        articles[idx]["category"] = item.get("category", CATEGORIES[0])
        articles[idx]["impact_score"] = int(item.get("impact_score", 0))
        articles[idx]["summary"] = item.get("summary", "")

    articles = [a for a in articles if "impact_score" in a]
    articles.sort(key=lambda a: a["impact_score"], reverse=True)
    if not articles:
        print("분류/스코어링 결과가 비어 있습니다.", file=sys.stderr)
        sys.exit(1)

    top_article = articles[0]
    insight_md = write_insight(client, top_article)

    date_str = end.strftime("%Y-%m-%d")
    subject = f"[AI Morning Brief] {date_str} 원유·정유·배터리 광물 트레이딩 핵심 동향"
    html = render_html(articles, insight_md, top_article, date_str)

    to_addr = os.environ.get("MAIL_TO", "bbd.chae@sk.com")

    try:
        send_email(subject, html, to_addr)
        print(f"발송 완료: {to_addr} ({len(articles)}건 수록)")
    except Exception as exc:  # noqa: BLE001
        print(f"메일 발송 실패: {exc}", file=sys.stderr)
        print("---- HTML 본문 (수동 발송용) ----", file=sys.stderr)
        print(html, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
