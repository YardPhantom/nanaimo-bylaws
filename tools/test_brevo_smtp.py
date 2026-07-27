#!/usr/bin/env python3
from email.message import EmailMessage
from pathlib import Path
import os,smtplib,ssl,sys
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1]; load_dotenv(ROOT/'runtime'/'subscription.env')
recipient=(sys.argv[1] if len(sys.argv)>1 else os.environ.get('SMTP_TEST_RECIPIENT','')).strip()
if not recipient: raise SystemExit('Usage: python tools\\test_brevo_smtp.py you@example.com')
msg=EmailMessage(); msg['From']=os.environ['SMTP_FROM']; msg['To']=recipient; msg['Subject']='Nanaimo Bylaw Tracker Brevo test'; msg.set_content('Brevo SMTP is configured correctly for Nanaimo Bylaw Tracker.')
with smtplib.SMTP(os.environ.get('SMTP_HOST','smtp-relay.brevo.com'),int(os.environ.get('SMTP_PORT','587')),timeout=30) as c:
 c.ehlo(); c.starttls(context=ssl.create_default_context()); c.ehlo(); c.login(os.environ['SMTP_USERNAME'],os.environ['SMTP_PASSWORD']); c.send_message(msg)
print(f'Test email sent to {recipient}.')
