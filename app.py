import os
import io
import base64
from datetime import datetime, date
from flask import Flask, request, jsonify
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white
from reportlab.lib.units import mm

app = Flask(__name__)

API_KEY = os.environ.get("EP_API_KEY", "")

C_BLACK = HexColor('#0a0a0a')
C_WHITE = white
C_BRONZE = HexColor('#8B6914')
C_BRONZE_LT = HexColor('#C4973A')
C_AMBER = HexColor('#D97706')
C_AMBER_DK = HexColor('#92400E')
C_RED = HexColor('#B91C1C')
C_GREY_MID = HexColor('#444444')
C_GREY_LIGHT = HexColor('#888888')
C_GREY_RULE = HexColor('#cccccc')
C_ROW_ALT = HexColor('#f7f7f7')
C_DIVIDER = HexColor('#e0e0e0')
C_OVERDUE_BG = HexColor('#fff5ee')

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
CONTENT_W = PAGE_W - 2 * MARGIN
FC1, FC2, FC3, FC4, FC5 = 0.36, 0.16, 0.19, 0.12, 0.17
ROW_H = 16

STAGE_LABELS = {
    '2808130027': 'Quote To Do',
    '2808130028': 'Quote Sent',
    '2808130029': 'Follow Up W1',
    '2808130030': 'Follow Up W2',
    '2808130031': 'Follow Up W3',
    '2808130032': 'Follow Up W4',
    '2808130033': 'Gone Dark',
    '2808130034': 'Re-Engage',
    '2808130035': 'Closed Won',
    '2808130036': 'Closed Lost',
    '2808122856': 'Parked',
}


def fmt_ccy(v):
    try:
        return f"${float(v):,.0f}"
    except Exception:
        return "$0"


def parse_due(t):
    if not t:
        return None
    r = t.get('hs_timestamp') or t.get('hs_due_date') or ''
    if not r:
        return None
    try:
        return datetime.fromisoformat(r.replace('Z', '+00:00')).date()
    except Exception:
        try:
            return datetime.strptime(r[:10], '%Y-%m-%d').date()
        except Exception:
            return None


def deal_status(deal, task, today):
    stage = deal.get('stage', '')
    if stage == '2808122856':
        if task and (task.get('hs_task_status') or '').upper() != 'COMPLETED':
            due = parse_due(task)
            if due and due < today:
                d = (today - due).days
                col = C_RED if d >= 8 else (C_AMBER_DK if d >= 4 else C_AMBER)
                return 'OVERDUE', f'{d}d late', col, 0
        if not task or (task.get('hs_task_status') or '').upper() == 'COMPLETED':
            return 'PARKED', 'no action needed', C_GREY_LIGHT, 4
        due = parse_due(task)
        if not due:
            return 'PARKED', 'no task date', C_GREY_LIGHT, 4
        diff = (due - today).days
        if diff <= 0:
            return 'PARKED', 'check in due', C_GREY_MID, 4
        return 'PARKED', f'check in +{diff}d', C_GREY_LIGHT, 4
    if not task:
        return 'NO TASK', 'schedule a follow-up', C_GREY_MID, 1
    if (task.get('hs_task_status') or '').upper() == 'COMPLETED':
        return 'NO TASK', 'completed - schedule next', C_GREY_MID, 1
    due = parse_due(task)
    if not due:
        return 'NO TASK', 'no due date set', C_GREY_MID, 1
    diff = (due - today).days
    if diff < 0:
        d = abs(diff)
        col = C_RED if d >= 8 else (C_AMBER_DK if d >= 4 else C_AMBER)
        return 'OVERDUE', f'{d}d late', col, 0
    if diff == 0:
        return 'TODAY', 'due today', C_BRONZE, 1
    if diff <= 7:
        return 'THIS WEEK', f'due in {diff}d', C_GREY_MID, 2
    return 'SCHEDULED', f'+{diff}d', C_GREY_LIGHT, 3


def _draw_rep(cv, rep, today, rds):
    m, cw, h = MARGIN, CONTENT_W, PAGE_H
    deals = rep.get('deals', [])
    tbyd = rep.get('tasks_by_deal', {})
    fn = rep['name'].split()[0].upper()
    od = [d for d in deals if d.get('stage') not in ('2808130035', '2808130036')]
    ann = []
    for d in od:
        t = tbyd.get(d['id'])
        lbl, sub, col, pri = deal_status(d, t, today)
        amt = float(d.get('amount') or 0)
        due = parse_due(t)
        dl = (today - due).days if due and due < today else 0
        pk = d.get('stage') == '2808122856'
        ann.append(dict(deal=d, task=t, lbl=lbl, sub=sub, col=col, pri=pri,
                        amount=amt, days_late=dl, parked=pk))
    ann.sort(key=lambda x: (1 if x['parked'] else 0, x['pri'], -x['amount'], -x['days_late']))
    ov = sum(1 for a in ann if a['lbl'] == 'OVERDUE' and not a['parked'])
    td = sum(1 for a in ann if a['lbl'] == 'TODAY' and not a['parked'])
    nt = sum(1 for a in ann if a['lbl'] == 'NO TASK' and not a['parked'])
    pv = sum(a['amount'] for a in ann)
    pr = [a for a in ann if a['lbl'] in ('OVERDUE', 'NO TASK', 'TODAY') and not a['parked']]
    pl = [a for a in ann if a['lbl'] in ('THIS WEEK', 'SCHEDULED') and not a['parked']]
    pkr = [a for a in ann if a['parked']]

    HH = 40 * mm
    cv.setFillColor(C_BLACK); cv.rect(0, h - HH, PAGE_W, HH, fill=1, stroke=0)
    cv.setFillColor(C_BRONZE); cv.rect(0, h - HH, 5, HH, fill=1, stroke=0)
    cv.setFillColor(C_WHITE); cv.setFont('Helvetica-Bold', 30); cv.drawString(m, h - 20*mm, fn)
    nw = cv.stringWidth(fn, 'Helvetica-Bold', 30)
    cv.setFillColor(C_BRONZE_LT); cv.setFont('Helvetica-Bold', 11); cv.drawString(m + nw + 8, h - 17*mm, 'WEEKLY SALES FOCUS')
    cv.setFillColor(HexColor('#999999')); cv.setFont('Helvetica', 8.5); cv.drawString(m, h - 27*mm, rds)

    kpis = [(str(len(od)), 'OPEN DEALS'), (fmt_ccy(pv), 'PIPELINE VALUE'),
            (str(ov), 'OVERDUE'), (str(td), 'DUE TODAY'), (str(nt), 'NO TASK')]
    kw = cw / len(kpis); ky = h - 37*mm
    for i, (v, l) in enumerate(kpis):
        x = m + i * kw
        cv.setFillColor(C_BRONZE_LT if i in (2, 4) else C_WHITE); cv.setFont('Helvetica-Bold', 14); cv.drawString(x, ky + 4, v)
        cv.setFillColor(HexColor('#999999')); cv.setFont('Helvetica', 6); cv.drawString(x, ky - 3, l)

    y = h - HH - 5*mm
    C1, C2, C3, C4, C5 = cw*FC1, cw*FC2, cw*FC3, cw*FC4, cw*FC5

    def sl(title, sub, bronze=False):
        nonlocal y
        cv.setFillColor(C_BRONZE if bronze else C_GREY_RULE); cv.rect(m, y - 1, 3, 11, fill=1, stroke=0)
        cv.setFillColor(C_BLACK if bronze else C_GREY_MID); cv.setFont('Helvetica-Bold', 7.5); cv.drawString(m + 7, y + 3, title)
        if sub:
            tw = cv.stringWidth(title, 'Helvetica-Bold', 7.5)
            cv.setFillColor(C_GREY_LIGHT); cv.setFont('Helvetica', 6.5); cv.drawString(m + 7 + tw + 5, y + 3, sub)
        y -= 13

    def ch():
        nonlocal y
        cv.setFillColor(C_BLACK); cv.rect(m, y - 1, cw, 11, fill=1, stroke=0)
        cv.setFillColor(C_WHITE); cv.setFont('Helvetica-Bold', 6)
        cv.drawString(m + 10, y + 3, 'DEAL'); cv.drawString(m + C1 + 3, y + 3, 'STAGE')
        cv.drawString(m + C1 + C2 + 3, y + 3, 'TASK STATUS')
        cv.drawRightString(m + C1 + C2 + C3 + C4 - 3, y + 3, 'VALUE')
        lbl = 'UPDATED CLAUDE EP SALES'; lw = cv.stringWidth(lbl, 'Helvetica-Bold', 5.5)
        cv.setFont('Helvetica-Bold', 5.5); cv.drawString(m + C1 + C2 + C3 + C4 + C5/2 - lw/2, y + 3, lbl)
        y -= 12

    def dr(a, idx, priority=False):
        nonlocal y
        if priority and a['lbl'] == 'OVERDUE':
            cv.setFillColor(C_OVERDUE_BG)
        elif idx % 2 == 0:
            cv.setFillColor(C_WHITE)
        else:
            cv.setFillColor(C_ROW_ALT)
        cv.rect(m, y - ROW_H + 5, cw, ROW_H, fill=1, stroke=0)
        if a['amount'] >= 5000:
            cv.setFillColor(C_BRONZE); cv.circle(m + 5, y - 1, 2.5, fill=1, stroke=0)
        cv.setFillColor(C_BLACK); cv.setFont('Helvetica-Bold', 7); cv.drawString(m + 10, y + 1, a['deal'].get('name', '')[:42])
        cv.setFillColor(C_GREY_MID); cv.setFont('Helvetica', 6.5); cv.drawString(m + C1 + 3, y + 1, STAGE_LABELS.get(a['deal'].get('stage', ''), ''))
        cv.setFillColor(a['col']); cv.setFont('Helvetica-Bold', 6.5); cv.drawString(m + C1 + C2 + 3, y + 1, a['lbl'])
        if a['sub']:
            cv.setFillColor(C_GREY_LIGHT); cv.setFont('Helvetica', 6); cv.drawString(m + C1 + C2 + 3, y - 6, a['sub'])
        cv.setFillColor(C_BLACK); cv.setFont('Helvetica-Bold', 7); cv.drawRightString(m + C1 + C2 + C3 + C4 - 3, y + 1, fmt_ccy(a['amount']))
        bx = m + C1 + C2 + C3 + C4 + C5/2 - 4; by = y - 4
        cv.setStrokeColor(HexColor('#aaaaaa')); cv.setLineWidth(0.6); cv.rect(bx, by, 8, 8, fill=0, stroke=1)
        cv.setStrokeColor(C_DIVIDER); cv.setLineWidth(0.3); cv.line(m, y - ROW_H + 5, m + cw, y - ROW_H + 5)
        y -= ROW_H

    if pr:
        sl('PRIORITY ACTIONS', 'overdue + no task + due today  -  action these first', bronze=True); ch()
        for i, a in enumerate(pr): dr(a, i, priority=True)
        y -= 5
    if pl:
        sl('PIPELINE', 'this week + scheduled'); ch()
        for i, a in enumerate(pl): dr(a, i)
        y -= 5
    if pkr:
        sl('PARKED', 'long lead or on hold'); ch()
        for i, a in enumerate(pkr): dr(a, i)
        y -= 5

    iy = 22 * mm; bh = 17 * mm
    cv.setFillColor(HexColor('#fafaf7')); cv.rect(m, iy, cw, bh, fill=1, stroke=0)
    cv.setStrokeColor(C_BRONZE); cv.setLineWidth(0.8); cv.rect(m, iy, cw, bh, fill=0, stroke=1)
    cv.setFillColor(C_BRONZE); cv.rect(m, iy, 4, bh, fill=1, stroke=0)
    cv.setFillColor(C_BLACK); cv.setFont('Helvetica-Bold', 7.5); cv.drawString(m + 10, iy + bh - 5.5*mm, 'HOW TO USE THIS SHEET')
    sl2 = ['1.  Print this page.', '2.  Work top to bottom - Priority Actions first.', '3.  For each deal: call, email or action as required.']
    sr2 = ['4.  Open Claude EP Sales Hub and update the deal stage or notes.', '5.  Tick the checkbox on this sheet once done.', '6.  All rows ticked = week complete. Well done.']
    cm2 = m + cw / 2
    for i, s in enumerate(sl2):
        cv.setFillColor(C_GREY_MID); cv.setFont('Helvetica', 6.8); cv.drawString(m + 10, iy + bh - 9.5*mm - i*8, s)
    for i, s in enumerate(sr2):
        cv.setFillColor(C_GREY_MID); cv.setFont('Helvetica', 6.8); cv.drawString(cm2 + 4, iy + bh - 9.5*mm - i*8, s)

    cv.setFillColor(C_GREY_LIGHT); cv.setFont('Helvetica', 6)
    cv.drawString(m, 5*mm, f'Entry Point Weekly Sales Focus  |  {rds}  |  Confidential')
    cv.drawRightString(m + cw, 5*mm, rep['name'])
    cv.showPage()


def generate_pdf_b64(data):
    rds = data.get('report_date', datetime.now().strftime('%d %b %Y'))
    today = date.today()
    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    cv.setTitle('EP Weekly Sales Focus')
    for rep in data['reps']:
        _draw_rep(cv, rep, today, rds)
    cv.save()
    return base64.b64encode(buf.getvalue()).decode('utf-8')


@app.route('/', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "ep-pdf-service"})


@app.route('/generate-pdf', methods=['POST'])
def generate_pdf_endpoint():
    provided_key = request.headers.get('X-API-Key', '')
    if not API_KEY or provided_key != API_KEY:
        return jsonify({"error": "unauthorized"}), 401
    try:
        data = request.get_json(force=True)
        if not data or 'reps' not in data:
            return jsonify({"error": "invalid payload, missing 'reps'"}), 400
        pdf_b64 = generate_pdf_b64(data)
        return jsonify({"pdf_base64": pdf_b64})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8000)))
