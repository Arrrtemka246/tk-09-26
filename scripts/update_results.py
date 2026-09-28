#!/usr/bin/env python3
import io,json,math,re,sys,unicodedata
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/"data"/"results.json"
SOURCE="https://funtiak.serv00.net/YM/"
UA="TeamKulikResults/1.0"

BASE={
"SCM":{
"M":{"50 free":19.90,"100 free":44.84,"200 free":98.61,"400 free":212.25,"800 free":440.46,"1500 free":846.88,"50 back":22.11,"100 back":48.16,"200 back":105.12,"50 breast":24.95,"100 breast":55.28,"200 breast":119.52,"50 fly":21.32,"100 fly":47.68,"200 fly":106.85,"100 medley":49.28,"200 medley":108.88,"400 medley":234.81},
"F":{"50 free":22.83,"100 free":49.93,"200 free":109.36,"400 free":230.25,"800 free":474.00,"1500 free":908.24,"50 back":25.23,"100 back":54.02,"200 back":117.33,"50 breast":28.37,"100 breast":62.36,"200 breast":132.50,"50 fly":23.72,"100 fly":52.71,"200 fly":119.32,"100 medley":55.11,"200 medley":121.63,"400 medley":255.48}},
"LCM":{
"M":{"50 free":20.91,"100 free":46.40,"200 free":102.00,"400 free":219.96,"800 free":452.12,"1500 free":870.67,"50 back":23.55,"100 back":51.60,"200 back":111.92,"50 breast":25.95,"100 breast":56.88,"200 breast":125.48,"50 fly":22.27,"100 fly":49.45,"200 fly":110.34,"200 medley":112.69,"400 medley":242.50},
"F":{"50 free":23.61,"100 free":51.71,"200 free":112.23,"400 free":234.18,"800 free":484.12,"1500 free":920.48,"50 back":26.86,"100 back":57.13,"200 back":123.14,"50 breast":29.16,"100 breast":64.13,"200 breast":137.55,"50 fly":24.43,"100 fly":54.60,"200 fly":121.81,"200 medley":125.70,"400 medley":263.65}}}
KEY={"50 м в/с":"50 free","100 м в/с":"100 free","200 м в/с":"200 free","400 м в/с":"400 free","800 м в/с":"800 free","1500 м в/с":"1500 free","50 м на спине":"50 back","100 м на спине":"100 back","200 м на спине":"200 back","50 м брасс":"50 breast","100 м брасс":"100 breast","200 м брасс":"200 breast","50 м баттерфляй":"50 fly","100 м баттерфляй":"100 fly","200 м баттерфляй":"200 fly","100 м комплекс":"100 medley","200 м комплекс":"200 medley","400 м комплекс":"400 medley"}
WORDS={"free":("вольн","свобод","freestyle","в/с"),"back":("спин","backstroke"),"breast":("брас","breaststroke"),"fly":("баттер","дельфин","butterfly"),"medley":("комплекс","medley","individual medley")}
TIME=re.compile(r"(?<!\d)(?:\d{1,2}:)?\d{1,2}[\.,]\d{2}(?!\d)")
STAT={"DSQ":re.compile(r"\b(?:DSQ|DQ|DISQ|ДИСКВ)\b",re.I),"DNS":re.compile(r"\b(?:DNS|NS|НЕ\s*СТАРТ)\b",re.I),"DNF":re.compile(r"\b(?:DNF|НЕ\s*ФИНИШ)\b",re.I)}

def norm(s):
    return re.sub(r"\s+"," ",unicodedata.normalize("NFKC",s).lower().replace("ё","е")).strip()
def sec(v):
    if not v:return None
    p=v.replace(",",".").split(":")
    try:return float(p[-1])+(float(p[-2])*60 if len(p)>1 else 0)
    except:return None
def points(course,sex,event,result):
    b=BASE.get(course,{}).get(sex,{}).get(KEY.get(event)); t=sec(result)
    return math.floor(1000*(b/t)**3) if b and t else None
def event_line(line,event):
    k=KEY.get(event)
    if not k:return False
    d,stroke=k.split(" ",1); n=norm(line)
    return bool(re.search(rf"(?<!\d){d}\s*(?:м|m)?(?!\d)",n)) and any(w in n for w in WORDS[stroke])
def infer(lines,i,events):
    for r in range(45):
        for j in (i-r,i+r):
            if 0<=j<len(lines):
                for e in events:
                    if event_line(lines[j],e):return e
def name_indices(lines,name):
    p=norm(name).split()
    surname=p[0] if p else ""
    first=p[1] if len(p)>1 else ""
    fp=first[:4]
    vv=[norm(name)]
    if len(p)>1:vv.append(norm(" ".join(p[1:]+p[:1])))
    out=[]
    for i,x in enumerate(lines):
        s=norm(x+" "+(lines[i+1] if i+1<len(lines) else ""))
        exact=any(v in s for v in vv)
        fuzzy=(surname in s and (not fp or fp in s))
        if exact or fuzzy:out.append(i)
    return out
def pdf_kind(url,label,text):
    s=norm(url+" "+label+" "+text[:1500])
    if any(x in s for x in ("resultlist","result list","results","результ")):return "result"
    if any(x in s for x in ("startlist","start list","стартов")):return "start"
    return "unknown"
def fetch_docs():
    s=requests.Session();s.headers["User-Agent"]=UA
    r=s.get(SOURCE,timeout=25);r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser");links=[];seen=set()
    for a in soup.find_all("a",href=True):
        h=a["href"]
        if ".pdf" not in h.lower():continue
        u=urljoin(SOURCE,h)
        if u not in seen:seen.add(u);links.append((u,a.get_text(" ",strip=True)))
    docs=[]
    for u,label in links:
        try:
            rr=s.get(u,timeout=30);rr.raise_for_status()
            reader=PdfReader(io.BytesIO(rr.content))
            text="\\n".join(((p.extract_text(extraction_mode="layout") or "") if hasattr(p,"extract_text") else "") for p in reader.pages)
            if text.strip():
                lines=[x.strip() for x in text.splitlines() if x.strip()]
                docs.append({"url":u,"label":label,"text":text,"lines":lines,"kind":pdf_kind(u,label,text)})
        except Exception as e:print("PDF warning",u,e,file=sys.stderr)
    if not docs:raise RuntimeError("no readable PDFs")
    return docs
def detect_course(docs):
    t=norm(" ".join(d["text"][:3000] for d in docs[:12]))
    a=len(re.findall(r"(?:25\s*(?:m|м)|25-метр|short course|scm)",t))
    b=len(re.findall(r"(?:50\s*(?:m|м)|50-метр|long course|lcm)",t))
    return "SCM" if a>b and a else "LCM" if b>a and b else None
def choose_result(times,seed):
    times=[x.replace(",",".") for x in times]
    if not times:return None
    if seed:
        ss=sec(seed); diff=[x for x in times if ss is None or abs((sec(x) or -999)-ss)>.005]
        if diff:return diff[-1]
    return times[-1]

def main():
    data=json.loads(PATH.read_text(encoding="utf-8"));docs=fetch_docs();changed=False
    course=detect_course(docs)
    if course and data["meet"].get("course")!=course:data["meet"]["course"]=course;changed=True
    events=sorted({s["event"] for a in data["athletes"] for s in a["starts"]},key=len,reverse=True)
    # Enrich every protocol with event/sex/date metadata. This lets us distinguish
    # "result not published yet" from "official result exists, athlete is absent".
    for d in docs:
        head=" ".join(d["lines"][:45])
        hn=norm(head)
        d["event"]=next((e for line in d["lines"][:45] for e in events if event_line(line,e)),None)
        d["sex"]="F" if any(w in hn for w in ("женщин","девочк")) else ("M" if any(w in hn for w in ("мужчин","мальчик")) else None)
        dm=re.search(r"(?<!\\d)([0-3]?\\d)\\.([01]?\\d)\\.(2026)(?!\\d)",head)
        d["date"]=f"{dm.group(3)}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}" if dm else None
    for a in data["athletes"]:
        for x in a["starts"]:
            for d in docs:
                for i in name_indices(d["lines"],a["name"]):
                    if infer(d["lines"],i,events)!=x["event"]:continue
                    row=d["lines"][i]
                    if not TIME.search(row) and i+1<len(d["lines"]): row+=" "+d["lines"][i+1]
                    times=TIME.findall(row);kind=d["kind"]
                    if kind=="unknown":kind="result" if any(rx.search(row) for rx in STAT.values()) else "start"
                    if kind=="start":
                        if times:
                            v=times[-1].replace(",",".")
                            if x.get("seed")!=v:x["seed"]=v;changed=True
                        if x.get("startSource")!=d["url"]:x["startSource"]=d["url"];changed=True
                        continue
                    special=next((k for k,rx in STAT.items() if rx.search(row)),None)
                    if special:
                        if x.get("status")!=special:x["status"]=special;changed=True
                        if x.get("result") is not None:x["result"]=None;x["delta"]=None;x["aqua"]=None;changed=True
                    else:
                        v=choose_result(times,x.get("seed"))
                        if not v:continue
                        if x.get("result")!=v:x["result"]=v;changed=True
                        if x.get("status")!="finished":x["status"]="finished";changed=True\n                        x["note"]=None
                        s0,s1=sec(x.get("seed")),sec(v);de=round(s1-s0,2) if s0 is not None and s1 is not None else None
                        if x.get("delta")!=de:x["delta"]=de;changed=True
                        candidates=[int(n) for n in re.findall(r"(?<!\d)(\d{3,4})(?!\d)",row) if 100<=int(n)<=1100]
                        ap=candidates[-1] if candidates else points(data["meet"].get("course"),a["sex"],x["event"],v)
                        if x.get("aqua")!=ap:x["aqua"]=ap;changed=True
                        m=re.match(r"^\s*(\d{1,2})\.",row);pl=int(m.group(1)) if m else None
                        if pl and x.get("place")!=pl:x["place"]=pl;changed=True
                    if x.get("resultSource")!=d["url"]:x["resultSource"]=d["url"];changed=True
    for a in data["athletes"]:
        for x in a["starts"]:
            if x.get("result") and x.get("aqua") is None:
                ap=points(data["meet"].get("course"),a["sex"],x["event"],x["result"])
                if ap is not None:x["aqua"]=ap;changed=True
            # Never invent DSQ/DNS/DNF. If a final result protocol for the exact
            # event/sex/date is already published but this athlete is absent,
            # show a neutral explicit state instead of "waiting".
            if not x.get("result") and str(x.get("status","")).upper() not in ("DSQ","DNS","DNF"):
                finals=[d for d in docs if d.get("kind")=="result" and d.get("event")==x["event"] and d.get("sex")==a["sex"] and (not d.get("date") or d.get("date")==x["date"])]
                if finals:
                    if x.get("status")!="not_listed":x["status"]="not_listed";changed=True
                    note="Итоговый протокол дистанции опубликован, но спортсмен в нём не найден."
                    if x.get("note")!=note:x["note"]=note;changed=True
                    if x.get("resultSource")!=finals[0]["url"]:x["resultSource"]=finals[0]["url"];changed=True
    if data.pop("sourceWarning",None) is not None:changed=True
    if changed:
        data["lastUpdated"]=datetime.now(timezone.utc).isoformat(timespec="seconds")
        PATH.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("PDFs",len(docs),"changed",changed,"course",data["meet"].get("course"))
if __name__=="__main__":
    try:main()
    except Exception as e:
        print("Source fetch failed:",e,file=sys.stderr)
        raise SystemExit(0)
