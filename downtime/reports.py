import json
import math


def report(db, date='', shift='', filters=None):
    filters = filters or {}
    for key in ('min_downtime', 'max_downtime', 'min_availability', 'max_availability', 'min_logs', 'min_board_feet'):
        if filters.get(key) not in (None, ''):
            value = float(filters[key])
            if not math.isfinite(value) or value < 0 or ('availability' in key and value > 100):
                raise ValueError('Invalid metric filter.')
    documents = [dict(r) for r in db.execute('SELECT * FROM documents ORDER BY shift_date, shift, kind')]
    shifts, causes = {}, {}
    for doc in documents:
        if (date and doc['shift_date'] != date) or (shift and doc['shift'] != shift):
            continue
        key = (doc['site'], doc['shift_date'], doc['shift'], doc['start_time'])
        item = shifts.setdefault(key, dict(site=key[0], date=key[1], shift=key[2], start_time=key[3], downtime=None, production=None, sources=[]))
        payload = json.loads(doc['payload'])
        item[doc['kind']] = payload
        item['sources'].append(dict(id=doc['id'], filename=doc['filename'], kind=doc['kind'], report_date=doc['report_date']))
    items = list(shifts.values())
    matching = []
    for item in items:
        if (filters.get('from') and item['date'] < filters['from']) or (filters.get('to') and item['date'] > filters['to']):
            continue
        downtime = item['downtime'] or {}
        production = (item['production'] or {}).get('numeric', {})
        values = dict(downtime=downtime.get('downtime_minutes'),
                      availability=100 * downtime['uptime_minutes'] / downtime['shift_minutes'] if downtime.get('shift_minutes', 0) > 0 else None,
                      logs=production.get('Total Logs'), board_feet=production.get('Total Brd Footage'))
        if any(values[key] is None or (bound == 'min' and values[key] < float(value)) or (bound == 'max' and values[key] > float(value))
               for key in values for bound in ('min', 'max')
               if (value := filters.get(f'{bound}_{key}')) not in (None, '')):
            continue
        matching.append(item)
    match_total = len(items)
    items = matching
    for item in items:
        for row in (item['downtime'] or {}).get('rows', []):
            group = (row['area'], row['category'], row['cause'])
            total = causes.setdefault(group, dict(area=group[0], category=group[1], cause=group[2], minutes=0, occurrences=0))
            total['minutes'] += row['minutes']
            total['occurrences'] += row['occurrences']
    total_down = sum(s['downtime']['downtime_minutes'] for s in items if s['downtime'])
    total_shift = sum(s['downtime']['shift_minutes'] for s in items if s['downtime'])
    return dict(shifts=items, match_total=match_total, causes=sorted(causes.values(), key=lambda r: -r['minutes']),
                totals=dict(downtime_minutes=total_down, shift_minutes=total_shift,
                            availability_percent=100 * (total_shift-total_down)/total_shift if total_shift else None),
                dates=sorted(set(d['shift_date'] for d in documents)),
                documents=[{k: d[k] for k in ('id','filename','kind','shift_date','shift','report_date','imported_at')} for d in documents])
