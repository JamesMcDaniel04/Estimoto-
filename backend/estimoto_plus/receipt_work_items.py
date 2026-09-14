"""Conservative local extraction of billed service sections and invoice rows.

Keep receipt wording. Never invent repairs from findings/recommendations and
never sum item amounts into the recorded cost (the invoice total owns that).
"""
from decimal import Decimal
import re

MONEY = r'(?:\$\s*)?((?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})(?![\d.,])'
AMOUNT = re.compile(MONEY)
SECTION = re.compile(r'^\s*(\d{1,3})[.)]?\s+([A-Za-z][^$]{3,180}?)\s*$')
END = re.compile(r'^\s*(?:terms(?:\s+of\s+service)?|conditions|warranty|inspection\s+(?:results|findings)|recommended\s+(?:services|repairs|work)|declined\s+(?:services|repairs|work)|deferred\s+(?:services|repairs|work))\b', re.I)
SUMMARY = re.compile(r'^(?:(?:grand|sub|invoice|labor|parts?|fees?|sales)?\s*total|subtotal|tax|sales tax|balance|amount (?:due|paid)|payment|paid\b|change\b|discount|shop supplies|materials|consumables|invoice\s*#|page\s+\d|phone\b|tel\b|fax\b)', re.I)
RIGHT_SUMMARY = re.compile(r'\s{2,}(?:SUBTOTAL|Labor|Parts|Fees|Sublets?):?\s*\$.*$',re.I)
HEADERS = re.compile(r'^(?:LABOR|LABOUR|PARTS|DESCRIPTION|SERVICES|WORK PERFORMED|ITEM|QTY|QUANTITY)\b',re.I)


def clean(value, limit=180):
    return re.sub(r'\s+', ' ', ''.join(' ' if c.isspace() else c for c in value if c.isprintable() or c.isspace())).strip()[:limit]


def cents(value):
    result = int(Decimal(value.replace(',', '')) * 100)
    return result if 0 <= result <= 100_000_000 else None


def parse_work_items(text, confidences=None):
    if len(text) > 200_000:
        return {'work_items': [], 'items_status': 'needs_review', 'items_version': 1}
    lines = text.splitlines()
    # Numbered service sections are common in shop-management invoices. Only
    # accept them when the document actually identifies a service section.
    service_start = next((i for i,l in enumerate(lines) if re.fullmatch(r'\s*(?:SERVICES|WORK PERFORMED|REPAIRS PERFORMED)\s*', l,re.I)), None)
    items = []
    current = None
    mode = None
    uncertain = False
    def confidence(i):
        nonlocal uncertain
        if confidences is not None and (i >= len(confidences) or confidences[i] < 85):
            uncertain = True
    if service_start is not None:
        for i in range(service_start+1,len(lines)):
            line=lines[i]
            if END.match(line): break
            heading=SECTION.match(line)
            if heading:
                title=clean(heading[2])
                if re.search(r'\b(?:recommended|declined|deferred|not performed)\b',title,re.I):
                    current=None; mode=None; continue
                current={'title':title,'tasks':[],'parts':[]}
                items.append(current); mode=None; confidence(i)
                if len(items)>=40: break
                continue
            if current is None: continue
            subtotal=re.search(r'\bSUBTOTAL\s*:?\s*'+MONEY,line,re.I)
            if subtotal: current['amount_cents']=cents(subtotal[1]); confidence(i)
            label=RIGHT_SUMMARY.sub('',line).strip()
            if not label or SUMMARY.match(label): continue
            if re.match(r'^LABOU?R\s*$',label,re.I): mode='tasks'; continue
            if re.match(r'^PARTS\b',label,re.I): mode='parts'; continue
            # Repeated page headers have large left margins; receipt service
            # text is indented near its section number. Do not retain contacts.
            if len(line)-len(line.lstrip())>24 or re.search(r'@|https?://|\b(?:Invoice\s*#|Page \d|AM|PM)\b',label,re.I): continue
            if re.search(r'\b(?:recommended|declined|deferred|not performed|warranty)\b',label,re.I): continue
            if mode == 'tasks':
                label=clean(label)
                if label != current['title'] and label not in current['tasks'] and len(current['tasks'])<16:
                    current['tasks'].append(label); confidence(i)
            elif mode == 'parts':
                # Keep descriptions, discard part-number/quantity/price columns.
                description=clean(re.split(r'\s{2,}',label)[0])
                if AMOUNT.search(label):
                    if description and len(current['parts'])<24:
                        current['parts'].append(description); confidence(i)
                elif current['parts'] and len(description)<70:
                    current['parts'][-1]=clean(current['parts'][-1]+' '+description)
    if not items:
        # Flat digital/photo receipts: a description followed by a billed
        # amount. No interpretation of paragraphs or diagnostic findings.
        for i,line in enumerate(lines):
            if END.match(line): break
            label=clean(line)
            if not label or SUMMARY.match(label) or re.search(r'@|https?://|\b(?:recommended|declined|deferred|not performed)\b',label,re.I): continue
            matches=list(AMOUNT.finditer(label))
            if not matches or matches[-1].end()!=len(label): continue
            description=label[:matches[0].start()].strip(' .:$-')
            description=re.sub(r'\s+\d+(?:\.\d+)?\s*(?:x|ea|hrs?)?$', '',description,flags=re.I)
            if len(description)<4 or not re.search(r'[A-Za-z]{3}',description) or re.search(r'\d{5}|\+?\d[\d ()-]{8,}',description): continue
            item={'title':description[:180],'tasks':[],'parts':[],'amount_cents':cents(matches[-1][1])}
            if item not in items: items.append(item); confidence(i)
            if len(items)>=40: break
    # Bound expanded invoice details as well as raw text; preserve the total
    # even if an unusually large invoice has more detail than can be shown.
    import json
    while items and len(json.dumps(items).encode()) > 48_000:
        items.pop(); uncertain = True
    # Amounts in other currencies are not labelled as USD by the app.
    if re.search(r'\b(?:CAD|AUD|NZD|EUR|GBP|JPY|MXN|CHF)\b|[€£¥]',text,re.I):
        for item in items: item.pop('amount_cents',None)
    return {'work_items':items,'items_status':('needs_review' if uncertain else 'ready') if items else 'not_found','items_version':1}
