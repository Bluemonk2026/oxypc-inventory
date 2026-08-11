import zipfile, re, html, sys
from xml.etree import ElementTree as ET
NS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
class WB:
    def __init__(self,path):
        self.z=zipfile.ZipFile(path)
        self.shared=self._shared()
        self.sheets=self._sheets()
    def _shared(self):
        out=[]
        try: root=ET.fromstring(self.z.read('xl/sharedStrings.xml'))
        except KeyError: return out
        for si in root:
            out.append(''.join(t.text or '' for t in si.iter(NS+'t')))
        return out
    def _sheets(self):
        wb=ET.fromstring(self.z.read('xl/workbook.xml'))
        rels=ET.fromstring(self.z.read('xl/_rels/workbook.xml.rels'))
        rmap={r.get('Id'):r.get('Target') for r in rels}
        out=[]
        for s in wb.iter(NS+'sheet'):
            rid=s.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            tgt=rmap.get(rid,'')
            if not tgt.startswith('/'): tgt='xl/'+tgt.lstrip('/')
            out.append((s.get('name'), tgt.replace('xl/xl/','xl/')))
        return out
    def rows(self,target):
        root=ET.fromstring(self.z.read(target))
        for row in root.iter(NS+'row'):
            cells={}
            for c in row.iter(NS+'c'):
                ref=c.get('r'); col=re.match(r'[A-Z]+',ref).group(0)
                t=c.get('t'); v=c.find(NS+'v'); isn=c.find(NS+'is')
                if t=='s' and v is not None: val=self.shared[int(v.text)]
                elif t=='inlineStr' and isn is not None: val=''.join(x.text or '' for x in isn.iter(NS+'t'))
                elif v is not None: val=v.text
                else: val=''
                cells[col]=val
            yield cells
def colidx(c):
    n=0
    for ch in c: n=n*26+ord(ch)-64
    return n-1
