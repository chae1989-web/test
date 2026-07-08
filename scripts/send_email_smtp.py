#!/usr/bin/env python3
"""Send an HTML email via Gmail SMTP, retrying with exponential backoff.

Env vars:
  GMAIL_ADDRESS             Sender Gmail address
  GMAIL_APP_PASSWORD        Gmail app password (SMTP)
  MAIL_TO                   Recipient address (default: bbd.chae@sk.com)
  SMTP_MAX_RETRIES          Max send attempts (default: 3)
  SMTP_RETRY_BASE_SECONDS   Base backoff seconds, doubled each retry (default: 2)

Usage:
  send_email_smtp.py --subject-file /tmp/briefing_subject.txt --body-file /tmp/briefing_body.html
  send_email_smtp.py --subject "..." --body-file /tmp/briefing_body.html
"""

import argparse
import os
import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

DEFAULT_TO = "bbd.chae@sk.com"


def send_email_with_retry(
    subject: str,
    html_body: str,
    to_addr: str,
    max_retries: int = 3,
    backoff_base: float = 2.0,
) -> None:
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_addr
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
                server.starttls()
                server.login(sender, password)
                server.send_message(msg)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"[send_email_smtp] attempt {attempt}/{max_retries} failed: {exc}", file=sys.stderr)
            if attempt < max_retries:
                delay = backoff_base * (2 ** (attempt - 1))
                print(f"[send_email_smtp] retrying in {delay:.0f}s...", file=sys.stderr)
                time.sleep(delay)

    raise RuntimeError(f"SMTP 발송 실패 (총 {max_retries}회 시도) — 마지막 에러: {last_error}") from last_error


def main() -> None:
    parser = argparse.ArgumentParser(description="Send an HTML email via Gmail SMTP with retries.")
    parser.add_argument("--subject", help="Email subject text (overrides --subject-file)")
    parser.add_argument("--subject-file", default="/tmp/briefing_subject.txt")
    parser.add_argument("--body-file", default="/tmp/briefing_body.html")
    parser.add_argument("--to", default=os.environ.get("MAIL_TO", DEFAULT_TO))
    parser.add_argument("--max-retries", type=int, default=int(os.environ.get("SMTP_MAX_RETRIES", 3)))
    parser.add_argument(
        "--backoff-base", type=float, default=float(os.environ.get("SMTP_RETRY_BASE_SECONDS", 2))
    )
    args = parser.parse_args()

    if args.subject:
        subject = args.subject
    else:
        with open(args.subject_file, encoding="utf-8") as f:
            subject = f.read().strip()

    with open(args.body_file, encoding="utf-8") as f:
        html_body = f.read()

    try:
        send_email_with_retry(subject, html_body, args.to, args.max_retries, args.backoff_base)
    except Exception as exc:  # noqa: BLE001
        print(f"SMTP 발송 실패 — 환경 변수 확인 필요: {exc}", file=sys.stderr)
        print("---- HTML 본문 (수동 발송용) ----", file=sys.stderr)
        print(html_body, file=sys.stderr)
        sys.exit(1)

    print(f"SENT: {args.to}")


if __name__ == "__main__":
    main()
