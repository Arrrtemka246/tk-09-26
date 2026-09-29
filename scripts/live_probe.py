#!/usr/bin/env python3
import io, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

from update_results import TIME, STAT, name_indices, sec, points

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"/"results.json"
SOURCE="https://funtiak.serv00.net/YM/"
TZ=ZoneInfo("Europe/Moscow")
UA="TeamKulikLiveProbe/2.0"
EVENT_NO=re.compile(r"StartList_(\d+)\.pdf",re.I)
RESULT_NO=re.compile(r"ResultList_(\d+)\.pdf",re.I)

def result_row(lines, athlete_name):
    idxs=name_indices(lines, athlete_name)
    if not idxs:
        return None
    # Result rows are normally one physical line. Prefer a line that contains
    # either a result time or an explicit race status.
    for i in idxs:
        row=lines[i]
        if TIME.search(row) or any(rx.search(row) for rx in STAT.values()):
            return row
        if i+1 < len(lines):
            joined=row+" "+lines[i+1]
            if TIME.search(joined) or any(rx.search(joined) for rx in STAT.values()):
                return joined
    return lines[idxs[0]]

def read_pdf(content):
    reader=PdfReader(io.BytesIO(content))
    text="\n".join((p.extract_text(extraction_mode="layout") or "") for p in reader.pages)
    return [x.strip() for x in text.splitlines() if x.strip()]

def event_number(start):
    m=EVENT_NO.search(start.get("startSource") or "")
    return int(m.group(1)) if m else None

def parse_index(session):
    r=session.get(SOURCE,timeout=8)
    r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    found={}
    for a in soup.find_all("a",href=True):
        m=RESULT_NO.search(a["href"])
        if m:
            n=int(m.group(1))
            found[n]=urljoin(SOURCE,a["href"])
    return found

def main():
    data=json.loads(DATA.read_text(encoding="utf-8"))
    now=datetime.now(TZ)
    today=now.date().isoformat()
    session=requests.Session()
    session.headers["User-Agent"]=UA

    pending=[]
    for athlete in data["athletes"]:
        for start in athlete["starts"]:
            if start.get("date")!=today:
                continue
            if start.get("result"):
                continue
            if str(start.get("status","")).upper() in ("DSQ","DNS","DNF"):
                continue
            n=event_number(start)
            if n:
                pending.append((n,athlete,start))

    if not pending:
        print("LIVE pending=0")
        print("SLEEP=300")
        return

    try:
        published=parse_index(session)
    except Exception as e:
        print("Index probe warning:",e,file=sys.stderr)
        print("SLEEP=30")
        return

    latest=max(published) if published else 0
    unique=sorted({n for n,_,_ in pending})
    changed=False
    fetched={}

    # Only touch target result PDFs. If the exact event is already linked, fetch it.
    # Also try the next target after the latest published event because the file can
    # become reachable a few seconds before the index page is refreshed.
    candidate=set(n for n in unique if n in published)
    future=[n for n in unique if n>latest]
    if future:
        candidate.add(min(future))

    for n in sorted(candidate):
        url=published.get(n, urljoin(SOURCE,f"ResultList_{n}.pdf"))
        try:
            r=session.get(url,timeout=10)
            if r.status_code!=200 or not r.content.startswith(b"%PDF"):
                continue
            fetched[n]=(url,read_pdf(r.content))
        except Exception as e:
            print(f"Result {n} probe warning:",e,file=sys.stderr)

    for n,athlete,start in pending:
        if n not in fetched:
            continue
        url,lines=fetched[n]
        row=result_row(lines,athlete["name"])
        if row is None:
            if start.get("status")!="not_listed":
                start["status"]="not_listed"; changed=True
            note="Итоговый протокол дистанции опубликован, но спортсмен в нём не найден."
            if start.get("note")!=note:
                start["note"]=note; changed=True
            if start.get("resultSource")!=url:
                start["resultSource"]=url; changed=True
            continue

        special=next((k for k,rx in STAT.items() if rx.search(row)),None)
        if special:
            if start.get("status")!=special:
                start["status"]=special; changed=True
            if start.get("result") is not None:
                start["result"]=None; changed=True
            if start.get("delta") is not None:
                start["delta"]=None; changed=True
            if start.get("aqua") is not None:
                start["aqua"]=None; changed=True
            start["note"]=None
            if start.get("resultSource")!=url:
                start["resultSource"]=url; changed=True
            continue

        times=[x.replace(",",".") for x in TIME.findall(row)]
        if not times:
            continue
        result=times[-1]
        # DOB also matches the loose time regexp; the actual result is the last
        # time-like token in Splash result rows.
        if start.get("result")!=result:
            start["result"]=result; changed=True
        if start.get("status")!="finished":
            start["status"]="finished"; changed=True
        if start.get("note") is not None:
            start["note"]=None; changed=True

        s0,s1=sec(start.get("seed")),sec(result)
        delta=round(s1-s0,2) if s0 is not None and s1 is not None else None
        if start.get("delta")!=delta:
            start["delta"]=delta; changed=True

        m=re.match(r"^\s*(\d{1,2})\.",row)
        place=int(m.group(1)) if m else None
        if place is not None and start.get("place")!=place:
            start["place"]=place; changed=True

        candidates=[int(x) for x in re.findall(r"(?<!\d)(\d{3,4})(?!\d)",row) if 100<=int(x)<=1100]
        aqua=candidates[-1] if candidates else points(data["meet"].get("course"),athlete["sex"],start["event"],result)
        if aqua is not None and start.get("aqua")!=aqua:
            start["aqua"]=aqua; changed=True

        if start.get("resultSource")!=url:
            start["resultSource"]=url; changed=True

    if data["meet"].get("latestOfficialResultNo")!=latest:
        data["meet"]["latestOfficialResultNo"]=latest
        changed=True
    data["meet"]["liveProbeAt"]=datetime.now(timezone.utc).isoformat(timespec="seconds")

    if changed:
        data["lastUpdated"]=datetime.now(timezone.utc).isoformat(timespec="seconds")
        DATA.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    remaining=[n for n,a,s in pending if not s.get("result") and str(s.get("status","")).upper() not in ("DSQ","DNS","DNF")]
    next_no=min(remaining) if remaining else None
    if next_no is None:
        sleep=300
    else:
        gap=next_no-latest
        # Near the team's next event we poll aggressively; farther away we back off.
        sleep=15 if gap<=1 else 25 if gap<=3 else 60

    print(f"LIVE today={today} latest={latest} targets={unique} changed={changed}")
    print(f"SLEEP={sleep}")

if __name__=="__main__":
    main()
