#!/usr/bin/env python3
"""Send Nanaimo Bylaw Tracker alerts from Firestore through Brevo SMTP."""
from __future__ import annotations
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib,json,os,smtplib,ssl
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import auth, credentials, firestore

ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'runtime'/'subscription.env', override=False)
SITE_URL=os.environ.get('PUBLIC_SITE_URL','').rstrip('/')
if not SITE_URL or not SITE_URL.lower().startswith(('https://','http://')):
    raise RuntimeError('PUBLIC_SITE_URL must be set to the deployed site URL before sending subscription email.')
CHANGE_LOG=ROOT/'data'/'change-log.json'; COUNCIL_ITEMS=ROOT/'data'/'council-items.json'
TZ=ZoneInfo(os.environ.get('SUBSCRIPTION_TIMEZONE','America/Vancouver'))

def load(path,default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError,json.JSONDecodeError):return default

def init_firebase():
    account=os.environ.get('FIREBASE_SERVICE_ACCOUNT','').strip()
    if not account: raise RuntimeError('FIREBASE_SERVICE_ACCOUNT is required')
    path=Path(account)
    if not path.is_absolute(): path=ROOT/path
    if not path.exists(): raise RuntimeError(f'Firebase service account not found: {path}')
    if not firebase_admin._apps: firebase_admin.initialize_app(credentials.Certificate(path))
    return firestore.client()

def smtp_send(recipient,subject,text,html):
    host=os.environ.get('SMTP_HOST','smtp-relay.brevo.com'); port=int(os.environ.get('SMTP_PORT','587'))
    username=os.environ['SMTP_USERNAME']; password=os.environ['SMTP_PASSWORD']; sender=os.environ['SMTP_FROM']
    msg=EmailMessage(); msg['From']=sender; msg['To']=recipient; msg['Subject']=subject; msg.set_content(text); msg.add_alternative(html,subtype='html')
    context=ssl.create_default_context()
    with smtplib.SMTP(host,port,timeout=30) as client:
        client.ehlo(); client.starttls(context=context); client.ehlo(); client.login(username,password); client.send_message(msg)

def events():
    out=[]; log=load(CHANGE_LOG,{})
    for item in log.get('events',[])[:100]:
        status=str(item.get('status') or item.get('change_type') or '').lower()
        typ='repealed' if ('repeal' in status or 'replace' in status) else 'consolidated' if 'consolidat' in status else 'amended' if ('amend' in status or status=='changed') else 'new'
        num=str(item.get('number') or '')
        out.append({'key':str(item.get('id') or f"bylaw:{item.get('date')}:{num}"),'type':typ,'category':item.get('category') or '', 'title':item.get('title') or f'Bylaw {num}','url':f"{SITE_URL}/bylaws/detail.html?number={num}"})
    council=load(COUNCIL_ITEMS,{})
    for item in (council if isinstance(council,list) else council.get('items',[]))[:100]:
        action=str(item.get('action') or '').lower(); typ='repealed' if ('repeal' in action or 'replace' in action) else 'consolidated' if 'consolidat' in action else 'amended' if ('amend' in action or 'reading' in action) else 'new'
        out.append({'key':f"council:{item.get('id')}",'type':typ,'category':item.get('category') or '', 'title':item.get('title') or item.get('summary') or 'Council bylaw item','url':item.get('bylaw_detail_url') or item.get('local_pdf_url') or item.get('meeting_url') or f'{SITE_URL}/council/'})
    return list({e['key']:e for e in out}.values())

def delivery_key(frequency, matched):
    now=datetime.now(TZ)
    if frequency=='daily': return 'daily:'+now.strftime('%Y-%m-%d')
    if frequency=='weekly': return 'weekly:'+now.strftime('%G-W%V')
    return 'immediate:'+hashlib.sha256('|'.join(sorted(e['key'] for e in matched)).encode()).hexdigest()[:24]

def due(frequency):
    now=datetime.now(TZ)
    if frequency=='daily': return now.hour>=int(os.environ.get('DAILY_SEND_HOUR_LOCAL','8'))
    if frequency=='weekly': return now.weekday()==int(os.environ.get('WEEKLY_SEND_WEEKDAY','0')) and now.hour>=int(os.environ.get('WEEKLY_SEND_HOUR_LOCAL','8'))
    return True

def normalized_email(value):
    return str(value or '').strip().lower()

def email_state_id(email):
    return hashlib.sha256(normalized_email(email).encode('utf-8')).hexdigest()

def main():
    db=init_firebase(); all_events=events()
    if not all_events: print('No collected changes to send.'); return

    # Group every due subscription by normalized recipient address. This guarantees that
    # duplicate Firebase records or repeated signups for one email produce one message.
    grouped={}
    ignored_duplicates=0
    for snap in db.collection_group('subscriptions').stream():
        if snap.id!='email': continue
        settings=snap.to_dict() or {}
        if not settings.get('active'): continue
        frequency=settings.get('frequency','daily')
        if not due(frequency): continue
        uid=snap.reference.parent.parent.id
        user=auth.get_user(uid)
        recipient=normalized_email(user.email or settings.get('recipientEmail'))
        if not recipient: continue
        types=set(settings.get('changeTypes') or [])
        categories=set(settings.get('categories') or [])
        matched=[e for e in all_events if e['type'] in types and (not categories or not e['category'] or e['category'] in categories)]
        if not matched: continue
        bucket=grouped.setdefault(recipient, {'events':{}, 'frequencies':set(), 'uids':set()})
        before=len(bucket['uids'])
        bucket['uids'].add(uid)
        if before: ignored_duplicates+=1
        bucket['frequencies'].add(frequency)
        for event in matched: bucket['events'][event['key']]=event

    sent=0; skipped=0
    for recipient,bucket in grouped.items():
        matched=list(bucket['events'].values())
        frequencies=sorted(bucket['frequencies'])
        scope='+'.join(frequencies)
        key=scope+':'+hashlib.sha256('|'.join(sorted(e['key'] for e in matched)).encode()).hexdigest()[:24]
        state_ref=db.collection('subscriptionEmailDeliveries').document(email_state_id(recipient))
        state=state_ref.get().to_dict() or {}
        if state.get('lastKey')==key:
            skipped+=1; continue
        rows=''.join(f'<li><a href="{e["url"]}">{e["title"]}</a></li>' for e in matched[:25])
        text='Nanaimo Bylaw Tracker updates\n\n'+'\n'.join(f'- {e["title"]}\n  {e["url"]}' for e in matched[:25])+f'\n\nManage preferences: {SITE_URL}/account.html\n'
        html=f'<h1>Nanaimo Bylaw Tracker updates</h1><ul>{rows}</ul><p><a href="{SITE_URL}/account.html">Manage email preferences</a></p><p>Hesh co. — Nanaimo Bylaw Tracker</p>'
        smtp_send(recipient,f'Nanaimo bylaw updates ({len(matched)})',text,html)
        state_ref.set({
            'lastKey':key,
            'lastSentAt':firestore.SERVER_TIMESTAMP,
            'itemCount':len(matched),
            'frequencies':frequencies,
            'accountCount':len(bucket['uids']),
            'recipientEmailHash':email_state_id(recipient)
        })
        sent+=1
    print(f'Sent {sent} Brevo deliveries; skipped {skipped} repeat deliveries; merged {ignored_duplicates} duplicate account subscriptions.')

if __name__=='__main__': main()
