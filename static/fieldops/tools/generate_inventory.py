"""Generate js/inventory.js from the Reliance source workbook.

Source: Inventory Details_LP TAT & Costing.xlsx
  · 'Inventory Details' → 3,568 lines / 3,957 units across 622 sites
  · 'Sheet6'            → site-level TAT & costing (Value of Shipment, QC/Packing/
                          Pickup/FOV/Total charges, weight, TAT, Executed By)
Output is a compact model (sites + article catalogue + lines) that the app
expands into individual asset records at first load.
"""
import sys, json, re, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xlsx import WB

SRC = '/Users/mac/Downloads/Inventory Details_LP TAT & Costing.xlsx'
OUT = '/Users/mac/Downloads/Reliance inspection/js/inventory.js'

wb = WB(SRC)
sheets = dict(wb.sheets)

# ---------- costing / TAT by site ----------
r6 = list(wb.rows(sheets['Sheet6']))
h6 = r6[2]
c6 = {h6[k]: k for k in h6}
def g6(r, n):
    k = c6.get(n)
    return (r.get(k) or '').strip() if k else ''
def num(v):
    try:
        return round(float(v), 2)
    except Exception:
        return 0

cost = {}
for r in r6[3:]:
    name = g6(r, 'Site Description')
    if not name or name == 'Grand Total':
        continue
    cost[name] = {
        'qty':        int(num(g6(r, 'Sum of Stock Quantity'))),
        'shipment':   num(g6(r, 'Value of Shipment')),
        'qc_ch':      num(g6(r, 'QC Charges')),
        'pack_ch':    num(g6(r, 'Packing Charges')),
        'qcpack_ch':  num(g6(r, 'QC & Packing Charges')),
        'weight':     num(g6(r, 'Weight')),
        'pickup_ch':  num(g6(r, 'Pickup Charges')),
        'fov_ch':     num(g6(r, 'FOV Charges')),
        'total_ch':   num(g6(r, 'Total Charges')),
        'post_ch':    num(g6(r, 'QC/Packing/Freight Charges post confirmation')),
        'tat':        g6(r, 'Tat Days'),
        'tat_after':  g6(r, 'Tat Days after halting & confirmation'),
        'exec_by':    g6(r, 'Executed By') or 'Unassigned',
    }

# ---------- inventory lines ----------
rows = list(wb.rows(sheets['Inventory Details']))
hdr = rows[1]
cols = {hdr[k]: k for k in hdr}
def g(r, n):
    k = cols.get(n)
    return (r.get(k) or '').strip() if k else ''

# ---------- article description parser (Apple SKUs) ----------
def parse_article(desc, family):
    """Apple SKU string → structured spec.

    MBA-15/MRYR3HNA/M3/8c/10cGPU/8/256/ST  → MacBook Air 15" M3, 8 GB, 256 GB
    Mac mini MU9D3HN/A M4/10C10G/16/256SSD → Mac mini M4, 16 GB, 256 GB
    Apple Studio Display MK0U3HNA/27/Stand → Studio Display 27" (monitor)
    """
    d = desc.upper().replace('MAC MINI', 'MACMINI').replace('MAC STUDIO', 'MACSTUDIO')

    # ---- product line ----
    if 'STUDIO DISPLAY' in d or d.startswith('ASD-') or ('DISPLAY' in d and 'MK0' in d):
        base, kind = 'Studio Display', 'display'
    elif 'MACPRO' in d.replace(' ', ''):
        base, kind = 'Mac Pro', 'desktop'
    elif d.startswith('MACMINI') or 'MACMINI' in d:
        base, kind = 'Mac mini', 'desktop'
    elif 'MACSTUDIO' in d:
        base, kind = 'Mac Studio', 'desktop'
    elif d.startswith('MBA'):
        base, kind = 'MacBook Air', 'laptop'
    elif d.startswith('MBP'):
        base, kind = 'MacBook Pro', 'laptop'
    elif 'IMAC' in d:
        base, kind = 'iMac', 'desktop'
    elif family == 'DESKTOP':
        base, kind = 'Mac', 'desktop'
    else:
        base, kind = 'MacBook', 'laptop'

    # ---- screen size ----
    size = ''
    sm = (re.match(r'^(?:MBA|MBP|IMAC)[- ]?(\d{2})', d) or
          re.search(r'IMAC\s*Z\d+[- ](\d{2})', d) or
          re.search(r'[- ](21\.5|23\.8|24|27)(?=/|\s|$)', d) or
          re.search(r'\b(13|14|15|16|24|27)\b(?=/|\s|$)', d))
    if sm:
        size = sm.group(1)
    if kind == 'display' and not size:
        size = '27'
    if base in ('Mac mini', 'Mac Studio', 'Mac Pro'):
        size = ''
    if kind == 'display':
        size = size if size in ('27', '24') else '27'

    # ---- chip (M1/M2/M3/M4 + Pro / Max) ----
    chip = ''
    cm = re.search(r'\bM([1-4])(P|M|\s?PRO|\s?MAX)?\b', d.replace('-', ' '))
    if cm:
        chip = 'M' + cm.group(1)
        suf = (cm.group(2) or '').strip()
        if suf in ('P', 'PRO'):
            chip += ' Pro'
        elif suf in ('M', 'MAX'):
            chip += ' Max'
    elif re.search(r'\bI[357]\b', d):
        chip = re.search(r'\b(I[357])\b', d).group(1).replace('I', 'i')

    # ---- RAM / storage (displays have neither) ----
    #  …/8/256/SL   → 8 GB RAM, 256 GB SSD
    #  …/36/1T/SB   → 36 GB RAM, 1 TB SSD
    #  …/8/1TF/4G   → 8 GB RAM, 1 TB SSD (4G is the GPU)
    ram = storage = ''
    if kind != 'display':
        toks = [t.strip() for t in re.split(r'[/ ]', desc) if t.strip()]
        RAM_SIZES = {'4', '8', '16', '18', '24', '32', '36', '48', '64', '96', '128'}
        storage_i = -1
        for i, t in enumerate(toks):
            m = re.fullmatch(r'(\d{1,2})\s*(T|TB|TF)', t, re.I)          # 1T / 2TB / 1TF
            if m:
                storage, storage_i = m.group(1) + ' TB', i
                break
        STORAGE_SIZES = {'128', '256', '500', '512', '1000', '1024', '2000', '2048', '4000'}
        if not storage:
            for i, t in enumerate(toks):
                m = re.fullmatch(r'(\d{3,4})\s*(GB|SSD)?', t, re.I)       # 128 … 2000
                if m and m.group(1) in STORAGE_SIZES:                     # avoid model numbers
                    storage, storage_i = m.group(1) + ' GB', i
                    break
        for i, t in enumerate(toks):
            m = re.fullmatch(r'(\d{1,3})\s*(GB)?', t, re.I)
            if not m or i == storage_i:
                continue
            if m.group(1) in RAM_SIZES and (storage_i < 0 or i < storage_i):
                ram = m.group(1) + ' GB'
        if ram and not storage:
            pass
        elif storage and not ram:
            for t in toks:
                if re.fullmatch(r'\d{1,3}', t) and t in RAM_SIZES:
                    ram = t + ' GB'
                    break

    label = base + (' ' + size + '"' if size else '') + (' ' + chip if chip else '')
    return {
        'model': label.strip(),
        'size': (size + '"') if size else '',
        'chip': chip,
        'ram': ram,
        'storage': storage,
        'kind': kind
    }

sites = {}          # description -> record
site_order = []
catalog = {}        # article no + desc -> index
cat_list = []
lines = []

for r in rows[2:]:
    desc_site = g(r, 'Site Description')
    if not desc_site:
        continue
    qty = int(num(g(r, 'Stock Quantity')) or 0)
    if qty <= 0:
        continue

    if desc_site not in sites:
        c = cost.get(desc_site, {})
        sites[desc_site] = {
            'code': g(r, 'Site'),
            'codes': [g(r, 'Site')],
            'format': g(r, 'Format'),
            'state': g(r, 'State'),
            'city': g(r, 'City'),
            'zone': g(r, 'Zone'),
            'site': desc_site,
            'qty': 0,
            'exec_by': c.get('exec_by', 'Unassigned'),
            'tat': c.get('tat', ''),
            'tat_after': c.get('tat_after', ''),
            'shipment': c.get('shipment', 0),
            'qc_ch': c.get('qc_ch', 0),
            'pack_ch': c.get('pack_ch', 0),
            'weight': c.get('weight', 0),
            'pickup_ch': c.get('pickup_ch', 0),
            'fov_ch': c.get('fov_ch', 0),
            'total_ch': c.get('total_ch', 0),
            'post_ch': c.get('post_ch', 0),
        }
        site_order.append(desc_site)
    s = sites[desc_site]
    if g(r, 'Site') not in s['codes']:
        s['codes'].append(g(r, 'Site'))
    s['qty'] += qty

    art = g(r, 'Article')
    adesc = g(r, 'Article Description')
    family = g(r, 'MH Family')
    key = art + '|' + adesc
    if key not in catalog:
        spec = parse_article(adesc, family)
        catalog[key] = len(cat_list)
        cat_list.append({
            'article': art,
            'desc': adesc,
            'family': family,
            'cls': g(r, 'MH Class'),
            'brick': g(r, 'MH Brick'),
            'cat': ('tft' if spec['kind'] == 'display'
                    else 'desktop' if family == 'DESKTOP' else 'laptop'),
            'make': 'Apple',
            'model': spec['model'],
            'size': spec['size'],
            'chip': spec['chip'],
            'ram': spec['ram'],
            'storage': spec['storage'],
            'rrp': int(num(g(r, 'RRP [U]'))),
            'mrp': int(num(g(r, 'MRP [U]'))),
        })
    lines.append([
        site_order.index(desc_site) if False else None,  # placeholder, fixed below
        catalog[key], qty, g(r, 'Storage Location'), g(r, 'Inventory Type')
    ])
    lines[-1][0] = site_order.index(desc_site)

site_list = [sites[n] for n in site_order]

total_units = sum(l[2] for l in lines)
print('sites: %d   catalogue: %d   lines: %d   units: %d' % (len(site_list), len(cat_list), len(lines), total_units))
print('exec split:', {k: sum(1 for s in site_list if s['exec_by'] == k) for k in set(s['exec_by'] for s in site_list)})

import hashlib
fingerprint = hashlib.sha1(json.dumps(
    [site_list, cat_list, lines], sort_keys=True, separators=(',', ':')
).encode('utf-8')).hexdigest()[:10]

payload = {
    'source': 'Inventory Details_LP TAT & Costing.xlsx',
    'build': fingerprint,
    'units': total_units,
    'sites': site_list,
    'catalog': cat_list,
    'lines': lines,
}

js = ('/* ============================================================\n'
      '   Reliance Asset FieldOps — Source inventory master\n'
      '   Generated from: Inventory Details_LP TAT & Costing.xlsx\n'
      '   %d locations · %d article SKUs · %d units\n'
      '   Compact model; expanded into asset records by RA.data.seed().\n'
      '   ============================================================ */\n'
      'window.RA = window.RA || {};\n'
      'RA.inventory = %s;\n') % (len(site_list), len(cat_list), total_units,
                                 json.dumps(payload, separators=(',', ':'), ensure_ascii=False))

with open(OUT, 'w') as f:
    f.write(js)
print('wrote %s  (%.0f KB)  build=%s' % (OUT, os.path.getsize(OUT) / 1024, fingerprint))
print('sample site:', json.dumps(site_list[0], ensure_ascii=False))
print('sample catalog:', json.dumps(cat_list[:3], ensure_ascii=False))
