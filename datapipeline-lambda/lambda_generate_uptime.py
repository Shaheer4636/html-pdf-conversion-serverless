# === CONFIG VIA ENV ===
import os
ART_BUCKET     = os.getenv("ART_BUCKET", "change-me")
ART_PREFIX     = os.getenv("ART_PREFIX", "canary/us-east-1/your-prefix")
REPORTS_BUCKET = os.getenv("REPORTS_BUCKET", "change-me")
REPORTS_PREFIX = os.getenv("REPORTS_PREFIX", "uptime")

COMPANY        = os.getenv("COMPANY", "Situs-AMC")
SERVICE        = os.getenv("SERVICE", "Useful App")
CLIENT         = os.getenv("CLIENT", "CitiBank")

ONLY_BROWSER   = os.getenv("ONLY_BROWSER", "ANY")
FAIL_STREAK    = int(os.getenv("FAIL_STREAK", "3"))
TREAT_MISSING  = os.getenv("TREAT_MISSING", "false").lower() == "true"
SLO_TARGET     = os.getenv("SLO_TARGET", "auto")
# ======================

import os, json, re, csv, io, datetime, random
from datetime import timezone, timedelta
from string import Template
from typing import Optional, List, Dict, Any, Tuple
from statistics import median
import boto3

s3 = boto3.client("s3")

def log(m: str) -> None:
    print(m, flush=True)

def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(timezone.utc)

def _first_of_month(y: int, m: int) -> datetime.datetime:
    return datetime.datetime(y, m, 1, tzinfo=timezone.utc)

def _last_of_month(y: int, m: int) -> datetime.datetime:
    return (_first_of_month(y+1,1)-timedelta(seconds=1)) if m==12 else (_first_of_month(y,m+1)-timedelta(seconds=1))

def month_window_utc(now: Optional[datetime.datetime]=None) -> Tuple[datetime.datetime, datetime.datetime]:
    now = now or _now_utc()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, now

def _num_or_null(v: Optional[float]) -> str:
    return "null" if (v is None) else f"{float(v):.3f}"

# Compile path pattern once
PAT_ANY = re.compile(
    r"^%s/(?P<y>\d{4})/(?P<m>\d{2})/(?P<d>\d{2})/(?P<h>\d{2})/(?P<min>\d{2})-(?P<s>\d{2})-(?P<ms>\d{3})(?:/(?P<br>[^/]+))?/(?P<file>[^/]+)$"
    % re.escape(ART_PREFIX.rstrip("/"))
)

# -------------------------- Parsers ---------------------------------
def _status_from_text(txt: str) -> Optional[bool]:
    u = txt.upper()
    if "FAILED" in u or "ERROR" in u or "TIMEOUT" in u: return False
    if "PASSED" in u or "SUCCEEDED" in u or "SUCCESS" in u: return True
    return None

def _parse_z(s: Optional[str]) -> Optional[datetime.datetime]:
    if not s: return None
    s = s.strip()
    if s.endswith("Z"): s = s[:-1] + "+00:00"
    try: return datetime.datetime.fromisoformat(s)
    except Exception: return None

def is_synthetics_json(name: str) -> bool:
    nl = name.lower()
    return nl.startswith("syntheticsreport") and nl.endswith(".json")

def parse_synthetics_json(data: dict, fname: str):
    status = None
    for p in (data.get("status"),
              data.get("overallStatus"),
              (data.get("customerScript") or {}).get("status"),
              (data.get("script") or {}).get("status")):
        if p is not None:
            s = _status_from_text(str(p))
            if s is not None: status = s; break

    dur_ms = None
    for p in ((data.get("customerScript") or {}).get("duration"),
              (data.get("customerScript") or {}).get("durationMs"),
              data.get("durationMs")):
        if isinstance(p,(int,float)): dur_ms = float(p); break

    if dur_ms is None:
        st = _parse_z((data.get("customerScript") or {}).get("startTime")) or _parse_z(data.get("startTime"))
        en = _parse_z((data.get("customerScript") or {}).get("endTime"))   or _parse_z(data.get("endTime"))
        dur_ms = (en-st).total_seconds()*1000.0 if st and en and en>=st else 0.0

    if status is None: status = _status_from_text(fname)
    if status is None: status = True
    return status, dur_ms

def parse_log_text(text: str):
    status = _status_from_text(text)
    dur_ms = 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*ms", text, re.I)
    if m: dur_ms = float(m.group(1))
    else:
        m = re.search(r"(\d+(?:\.\d+)?)\s*s", text, re.I)
        if m: dur_ms = float(m.group(1))*1000.0
    if status is None: status = True
    return status, dur_ms

def parse_har_html(html: str):
    statuses = [int(x) for x in re.findall(r'"status"\s*:\s*(\d{3})', html)]
    status = False if statuses and any(s >= 400 for s in statuses) else True
    times = [float(x) for x in re.findall(r'"time"\s*:\s*([0-9.]+)', html)]
    dur_ms = sum(times)/len(times) if times else 0.0
    return status, dur_ms

# ---------------------- Artifact Scanning ---------------------------
def _list_prefix(prefix: str):
    pag = s3.get_paginator("list_objects_v2")
    for page in pag.paginate(Bucket=ART_BUCKET, Prefix=prefix, PaginationConfig={"PageSize": 1000}):
        for obj in page.get("Contents", []):
            yield obj["Key"]

def _iter_objects_for_month(y: int, mo: int, start: datetime.datetime, end: datetime.datetime):
    ystr = f"{y:04d}"; mstr = f"{mo:02d}"
    prefixes = [f"{ART_PREFIX}/{ystr}/{mstr}/", f"{ART_PREFIX}/{ystr}/"]
    yielded = False
    for p in prefixes:
        for key in _list_prefix(p):
            m = PAT_ANY.match(key)
            if not m: continue
            Y=int(m.group("y")); M=int(m.group("m")); D=int(m.group("d"))
            H=int(m.group("h")); MIN=int(m.group("min"))
            ts = datetime.datetime(Y,M,D,H,MIN,tzinfo=timezone.utc)
            if ts < start or ts > end: continue
            br = m.group("br")
            if ONLY_BROWSER!="ANY":
                if br is None or br.upper()!=ONLY_BROWSER: continue
            yield ts, key, (br.upper() if br else "N/A"), m.group("file")
            yielded=True
        if yielded: return
    # fallback: exact day/hour walk
    days = (_last_of_month(y, mo) - _first_of_month(y, mo)).days + 1
    for d in range(1, days+1):
        dd=f"{d:02d}"
        for h in range(0,24):
            hh=f"{h:02d}"
            p=f"{ART_PREFIX}/{ystr}/{mstr}/{dd}/{hh}/"
            for key in _list_prefix(p):
                m = PAT_ANY.match(key)
                if not m: continue
                Y=int(m.group("y")); M=int(m.group("m")); D=int(m.group("d"))
                H=int(m.group("h")); MIN=int(m.group("min"))
                ts = datetime.datetime(Y,M,D,H,MIN,tzinfo=timezone.utc)
                if ts < start or ts > end: continue
                br = m.group("br")
                if ONLY_BROWSER!="ANY":
                    if br is None or br.upper()!=ONLY_BROWSER: continue
                yield ts, key, (br.upper() if br else "N/A"), m.group("file")

def scan_window(y: int, mo: int, start: datetime.datetime, end: datetime.datetime):
    per_min_flags={}; per_min_ms={}; sampled=[]
    for minute_dt, key, _browser, fname in _iter_objects_for_month(y, mo, start, end):
        sampled.append(key)
        try:
            body = s3.get_object(Bucket=ART_BUCKET, Key=key)["Body"].read()
        except Exception as e:
            log(f"[warn] get_object failed {key}: {type(e).__name__}"); continue
        name=fname.lower(); succ=None; ms=0.0
        try:
            if is_synthetics_json(fname):
                succ, ms = parse_synthetics_json(json.loads(body.decode("utf-8",errors="ignore")), fname)
            elif name.endswith("-log.txt"):
                succ, ms = parse_log_text(body.decode("utf-8",errors="ignore"))
            elif name == "httprequestsreport.json":
                data=json.loads(body.decode("utf-8",errors="ignore"))
                codes=[(r.get("response") or {}).get("statusCode") for r in (data.get("requests") or [])]
                codes=[c for c in codes if isinstance(c,int)]
                succ = False if any(c>=400 for c in codes) else True
            elif name.endswith("results.har.html"):
                succ, ms = parse_har_html(body.decode("utf-8",errors="ignore"))
            else:
                continue
        except Exception as e:
            log(f"[warn] parse failed {key}: {type(e).__name__}"); continue
        if succ is None: continue
        per_min_flags.setdefault(minute_dt,[]).append(bool(succ))
        if ms: per_min_ms.setdefault(minute_dt,[]).append(float(ms))
    agg_ok = {t: all(flags) for t,flags in per_min_flags.items()}
    agg_ms = {t: (sum(v)/len(v) if v else 0.0) for t,v in per_min_ms.items()}
    if TREAT_MISSING:
        cur=start.replace(second=0,microsecond=0); endr=end.replace(second=0,microsecond=0)
        while cur<=endr:
            if cur not in agg_ok: agg_ok[cur]=False; agg_ms.setdefault(cur,0.0)
            cur += timedelta(minutes=1)
    return agg_ok, agg_ms, sampled[:250]

# -------------------------- Reductions ------------------------------
def hourly_reduce(agg_ok: Dict[datetime.datetime,bool], agg_ms: Dict[datetime.datetime,float]):
    buckets={}
    for t, ok in agg_ok.items():
        hr=t.replace(minute=0,second=0,microsecond=0)
        buckets.setdefault(hr,[]).append((ok,agg_ms.get(t,0.0)))
    out=[]
    for hr, rows in sorted(buckets.items()):
        ok_pct=(sum(1 for ok,_ in rows if ok)/len(rows))*100.0 if rows else 0.0
        ms_avg=(sum(ms for _,ms in rows)/len(rows)) if rows else 0.0
        out.append({"hour":hr,"success_avg":ok_pct,"response_ms_avg":ms_avg})
    return out

def month_cumulative(agg_ok: Dict[datetime.datetime,bool], agg_ms: Dict[datetime.datetime,float]):
    per_day={}
    for t, ok in agg_ok.items():
        d=t.date()
        per_day.setdefault(d,{"up":0,"tot":0,"ms_sum":0.0,"ms_ct":0})
        per_day[d]["up"] += 1 if ok else 0
        per_day[d]["tot"]+= 1
        ms=agg_ms.get(t,0.0)
        if ms: per_day[d]["ms_sum"]+=ms; per_day[d]["ms_ct"]+=1
    series=[]; cu=ct=0; cms=cct=0
    for d in sorted(per_day.keys()):
        cu += per_day[d]["up"]; ct += per_day[d]["tot"]
        cms += per_day[d]["ms_sum"]; cct += per_day[d]["ms_ct"]
        avail=(cu/ct)*100.0 if ct else 0.0
        resp=(cms/cct)/1000.0 if cct else 0.0
        series.append({"day": d.strftime("%Y-%m-%d"), "avail": avail, "resp_s": resp})
    return series

def detect_incidents(agg_ok: Dict[datetime.datetime,bool]):
    mins=sorted(agg_ok.keys()); inc=[]; streak=0; start=None
    for m in mins:
        if not agg_ok[m]:
            streak+=1; start = start or m
        else:
            if streak>=FAIL_STREAK: inc.append({"start":start,"end":m-timedelta(minutes=1),"duration_minutes":streak})
            streak=0; start=None
    if streak>=FAIL_STREAK and mins:
        inc.append({"start":start,"end":mins[-1],"duration_minutes":streak})
    return inc

# ---------------------- YTD helpers ---------------------------------
def _csv_rows_from_s3_safe(key: str) -> Optional[List[Dict[str,str]]]:
    try:
        head = s3.head_object(Bucket=REPORTS_BUCKET, Key=key)
        if head.get("ContentLength", 0) > 10 * 1024 * 1024:
            return None
        body = s3.get_object(Bucket=REPORTS_BUCKET, Key=key)["Body"].read().decode("utf-8")
    except Exception:
        return None
    return list(csv.DictReader(io.StringIO(body)))

def _month_label(y: int, m: int) -> str:
    return datetime.datetime(y, m, 1, tzinfo=timezone.utc).strftime("%B %Y")

def _read_month_summary_from_csv(y: int, m: int) -> Optional[Dict[str,float]]:
    base = f"{REPORTS_PREFIX}/{y}/{m:02d}/"
    rows = _csv_rows_from_s3_safe(f"{base}uptime-hour.csv")
    if rows is None:
        rows = _csv_rows_from_s3_safe(f"{base}uptime-minute.csv")
    if not rows:
        return None
    try:
        avgs=[float(r["availability_pct"]) for r in rows if (r.get("availability_pct") or "").strip()!=""]
        rsps=[float(r.get("avg_response_sec") or 0.0) for r in rows]
        if not avgs:
            return None
        return {"availability": sum(avgs)/len(avgs), "resp_s": (sum(rsps)/len(rsps) if rsps else 0.0)}
    except Exception:
        return None

def summarize_month_from_artifacts_quick(y: int, m: int, sample_limit: int=400) -> Optional[Dict[str,float]]:
    prefix = f"{ART_PREFIX}/{y:04d}/{m:02d}/"
    passed = failed = 0
    sample = []
    seen = 0

    token = None
    while True:
        if token:
            resp = s3.list_objects_v2(Bucket=ART_BUCKET, Prefix=prefix, ContinuationToken=token, MaxKeys=1000)
        else:
            resp = s3.list_objects_v2(Bucket=ART_BUCKET, Prefix=prefix, MaxKeys=1000)
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            mobj = PAT_ANY.match(key)
            if not mobj:
                continue
            br = mobj.group("br")
            if ONLY_BROWSER != "ANY":
                if br is None or br.upper() != ONLY_BROWSER:
                    continue
            fname = mobj.group("file").lower()
            if fname.startswith("syntheticsreport-") and fname.endswith(".json"):
                seen += 1
                if "-passed" in fname:
                    passed += 1
                elif "-failed" in fname:
                    failed += 1
                if len(sample) < sample_limit:
                    sample.append(key)
                else:
                    j = random.randint(1, seen)
                    if j <= sample_limit:
                        sample[random.randint(0, sample_limit-1)] = key
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break

    total = passed + failed
    if total == 0:
        return None

    dur_ms_vals = []
    for k in sample:
        try:
            body = s3.get_object(Bucket=ART_BUCKET, Key=k)["Body"].read()
            data = json.loads(body.decode("utf-8", errors="ignore"))
            _, dur_ms = parse_synthetics_json(data, k.rsplit("/", 1)[-1])
            if isinstance(dur_ms, (int, float)):
                dur_ms_vals.append(float(dur_ms))
        except Exception:
            continue

    resp_s = (sum(dur_ms_vals) / len(dur_ms_vals) / 1000.0) if dur_ms_vals else 0.0
    availability = (passed / total) * 100.0
    return {"availability": availability, "resp_s": resp_s}

def build_year_summary_ytd(current_avail: float, current_resp_s: float):
    now = _now_utc()
    y = now.year
    months = list(range(1, now.month + 1))

    chart, table, csvout = [], [], []
    for m in months:
        if m == now.month:
            avail, resp = current_avail, current_resp_s
        else:
            s = _read_month_summary_from_csv(y, m) or summarize_month_from_artifacts_quick(y, m)
            if s:
                avail, resp = s["availability"], s["resp_s"]
            else:
                avail, resp = None, None

        chart.append({"month": f"{y}-{m:02d}", "availability": avail, "resp_s": resp})
        table.append({"label": _month_label(y, m), "availability": avail, "resp_s": resp})
        csvout.append({
            "month": f"{y}-{m:02d}",
            "availability_pct": "" if avail is None else f"{avail:.3f}",
            "avg_response_sec": "" if resp is None else f"{resp:.3f}",
        })
    return chart, table, csvout

def compute_slo_auto(now: datetime.datetime, lookback_months: int = 3) -> float:
    vals = []
    y = now.year; m = now.month
    for i in range(1, lookback_months+1):
        pm = m - i; py = y
        if pm <= 0: pm += 12; py -= 1
        s = _read_month_summary_from_csv(py, pm)
        if not s:
            s = summarize_month_from_artifacts_quick(py, pm)
        if s and isinstance(s.get("availability"), (int,float)):
            vals.append(float(s["availability"]))
    if len(vals) >= 1:
        return float(f"{median(vals):.3f}")
    return 99.9

# --------------------------- HTML -----------------------------------
def render_html(meta, minute_rows, hour_rows, month_cum_rows_padded, per_canary,
                year_chart_rows, year_table_rows, incidents, generated_at):

    min_js = ",\n      ".join("[new Date('{}Z'), {:.3f}]".format(r["ts"], r["avail"]) for r in minute_rows)
    hr_js  = ",\n      ".join("[new Date('{}Z'), {:.3f}]".format(r["hour"], r["avail"]) for r in hour_rows)
    mc_js  = ",\n      ".join("['{}', {}]".format(r["day"], _num_or_null(r["avail"])) for r in month_cum_rows_padded)
    year_js = ",\n      ".join("['{}', {}]".format(r["month"], _num_or_null(r["availability"])) for r in year_chart_rows)
    per_js = ",\n      ".join("['{}', {:.3f}]".format(p["name"], p["pct"]) for p in per_canary)

    table_rows_html = "".join(
        "<tr><td>{}</td><td align='right'>{}</td></tr>".format(
            row["label"],
            ("{:.3f}%".format(row["availability"]) if row["availability"] is not None else "—")
        ) for row in year_table_rows
    )

    incidents_rows = "".join(
        f"<tr><td>{i['start'].strftime('%Y-%m-%d %H:%M')}</td>"
        f"<td>{i['end'].strftime('%Y-%m-%d %H:%M')}</td>"
        f"<td style='text-align:right'>{i['duration_minutes']}</td></tr>"
        for i in incidents
    )

    page = Template(r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>$title</title>
  <script src="https://www.gstatic.com/charts/loader.js"></script>
  <style>
    :root{ --brand:#0f4cbd; --ink:#111; --muted:#555; --bg:#f4f6fa; --line:#e5eaf5; --bar:#eef2fb;
           --page-w:248mm; --page-h:297mm; --page-margin:4mm; }
    @page{ size: 248mm 297mm; margin: var(--page-margin); }
    html,body{ height:100% } body{ margin:0; font-family:Segoe UI, Roboto, Arial, sans-serif; color:var(--ink); background:var(--bg); -webkit-print-color-adjust:exact; print-color-adjust:exact }
    .page{ width:var(--page-w); min-height:var(--page-h); margin:16px auto; background:#fff; box-shadow:0 2px 12px rgba(0,0,0,.08); display:flex }
    .sheet{ padding:10mm; display:flex; flex-direction:column; width:100% }
    @media print{ body{background:#fff; margin:0} .page{ break-after:page; margin:0; width:auto; min-height:auto; box-shadow:none } }
    h1{ margin:0 0 6mm; font-size:22pt; font-weight:900 } h2{ margin:0 0 4mm; font-size:13pt; font-weight:800 } .subline{ font-size:12pt; font-weight:700; color:#1d2a44 }
    .muted{ color:#6b7280 } .tbl{ width:100%; border-collapse:collapse } .tbl th,.tbl td{ padding:3mm 4mm; border-bottom:1px solid var(--line) } .tbl th{ background:#f3f6fc; text-align:left }
    .logo-wordmark{ font-weight:900; font-size:34pt; line-height:1; letter-spacing:.5px; margin-bottom:8mm; display:inline-flex; align-items:baseline }
    .logo-primary{ background:linear-gradient(90deg,#0f4cbd,#3b82f6); -webkit-background-clip:text; background-clip:text; color:transparent; -webkit-text-fill-color:transparent }
    .logo-hyph{ color:#8da2c1; font-weight:800; margin:0 6px; transform:translateY(-2px) }
    .logo-badge{ background:#0f1c3f; color:#fff; padding:4px 10px; border-radius:10px; font-weight:900; letter-spacing:1px; font-size:.8em; border:1px solid #0b1530; text-transform:uppercase }
    @media print{ .logo-primary{ -webkit-text-fill-color:initial; color:#0f4cbd; background:none } }
    .cards{ display:grid; grid-template-columns:repeat(3,1fr); gap:6mm; margin:6mm 0 } .card{ border:1px solid var(--line); border-radius:12px; padding:6mm; box-shadow:0 2px 6px #0001 }
    .kpi{ color:#fff; border-color:transparent; box-shadow:0 4px 14px rgba(0,0,0,.10) } .kpi .muted{ color:rgba(255,255,255,.92); letter-spacing:.6px } .kpi .kval{ color:#fff; font-size:20pt; font-weight:900; white-space:nowrap; overflow:hidden; text-overflow:ellipsis }
    .kpi-availability{ background:linear-gradient(135deg, rgba(16,185,129,.7), rgba(5,150,105,.7)) }
    .kpi-downtime{     background:linear-gradient(135deg, rgba(251,191,36,.7), rgba(217,119,6,.7)) }
    .kpi-incidents{    background:linear-gradient(135deg, rgba(239,68,68,.7), rgba(185,28,28,.7)) }
    .charts-2{ display:grid; grid-template-columns:1fr 1fr; gap:6mm; margin-top:6mm } .chart{ height:95mm }
    .footer{ margin-top:auto; border-top:1px solid var(--line); padding-top:4mm; text-align:center; font-size:8.8pt; color:#4b5565 }
    .disc-title{ font-size:9pt; font-weight:800; margin-top:3mm } .disc-text{ font-size:8.6pt; color:#4b5565; line-height:1.6 }

    /* CHANGE: Make only Page 3 (report page) titles/text that use .muted render as dark black */
    #page-report .muted{ color:#111; font-weight:800 }
  </style>
</head>
<body>

  <!-- PAGE 1 — DISCLAIMERS -->
  <div class="page">
    <div class="sheet">
      <div class="logo-wordmark" role="img" aria-label="Situs-AMC">
        <span class="logo-primary">Situs</span><span class="logo-hyph">-</span><span class="logo-badge">AMC</span>
      </div>
      <h1>Disclaimers</h1>
      <div>
        <div class="disc-title">General</div>
        <div class="disc-text">This report is provided by $company for information purposes only. By accessing it, you agree to the terms herein.</div>
        <div class="disc-title">Confidentiality, Distribution or Presentation</div>
        <div class="disc-text">This document is confidential and may not be reproduced or shared without prior written consent.</div>
        <div class="disc-title">Forward-Looking Statements</div>
        <div class="disc-text">Forward-looking statements are based on current assumptions and subject to risks and uncertainties; actual outcomes may differ.</div>
        <div class="disc-title">Past Performance</div>
        <div class="disc-text">Past performance is not indicative of future results.</div>
        <div class="disc-title">No Reliance, No Update, and Use of Information</div>
        <div class="disc-text">Information is provided as-is, may be based on third-party inputs, and may be updated without notice.</div>
        <div class="disc-title">No Advice</div>
        <div class="disc-text">Nothing herein constitutes legal, financial, investment, accounting, or tax advice.</div>
        <div class="disc-title">Current Data</div>
        <div class="disc-text">Unless noted otherwise, the data presented is as of the date of this report.</div>
        <div class="disc-title">Logos, Trademarks, and Copyrights</div>
        <div class="disc-text">All trademarks and logos are the property of their respective owners.</div>
        <div class="disc-title">Financial Services and Markets</div>
        <div class="disc-text">Nothing in this report constitutes a financial promotion for the purposes of applicable financial services laws.</div>
        <div class="disc-title">Scope and Definitions</div>
        <div class="disc-text">“Availability” refers to the percentage of monitored intervals during which all critical checks succeed. Outages are measured at minute granularity unless specified otherwise.</div>
        <div class="disc-title">Methodology</div>
        <div class="disc-text">Checks are executed on a schedule and aggregated into hourly, daily, and month-to-date views. Missing intervals may be treated as failures or ignored based on the policy stated in this report.</div>
        <div class="disc-title">Data Quality & Gaps</div>
        <div class="disc-text">Measurements may be influenced by third-party networks, DNS, CDN edges, regional connectivity, or temporary provider throttling.</div>
        <div class="disc-title">Third-Party Dependencies</div>
        <div class="disc-text">Service performance may depend on external vendors (cloud providers, auth, messaging, storage). Incidents at those vendors can impact availability without direct control by $company.</div>
        <div class="disc-title">Security & Access</div>
        <div class="disc-text">Credentials and sensitive URLs are omitted. This document should not be shared beyond authorized recipients.</div>
        <div class="disc-title">Use Restrictions</div>
        <div class="disc-text">This report is intended for operational oversight and is not a substitute for contractual SLAs or legal advice.</div>
      </div>
      <div class="footer">Confidential &amp; Proprietary — © $year $company. All rights reserved. Provided “as-is” without warranties; not legal, tax, or investment advice.</div>
    </div>
  </div>

  <!-- PAGE 2 — EXECUTIVE SUMMARY -->
  <div class="page" id="page-exec">
    <div class="sheet">
      <div class="logo-wordmark" role="img" aria-label="Situs-AMC">
        <span class="logo-primary">Situs</span><span class="logo-hyph">-</span><span class="logo-badge">AMC</span>
      </div>
      <h1>Executive Summary — $service ($month_name $year)</h1>
      <div class="subline">$company • Client: $client • SLO: $slo% • Source: $source • Generated: $generated_at</div>

      <section class="cards kpi-row" aria-label="Key performance indicators">
        <article class="card kpi kpi-availability"><div class="muted">OVERALL AVAILABILITY</div><div class="kval">$availability%</div></article>
        <article class="card kpi kpi-downtime"><div class="muted">TOTAL DOWNTIME</div><div class="kval">$downtime_min min</div></article>
        <article class="card kpi kpi-incidents"><div class="muted">INCIDENTS</div><div class="kval">$incidents</div></article>
      </section>

      <!-- CHANGE: replace bullet list with a single concise paragraph summary -->
      <section class="summary" aria-label="Highlights">
        <h2>Highlights</h2>
        <p id="summary_para" class="muted" style="margin:0 0 6mm 0"></p>
      </section>

      <div class="footer">Confidential &amp; Proprietary — © $year $company. All rights reserved.</div>
    </div>
  </div>

  <!-- PAGE 3 — REPORT -->
  <div class="page" id="page-report">
    <div class="sheet">
      <div class="logo-wordmark" role="img" aria-label="Situs-AMC">
        <span class="logo-primary">Situs</span><span class="logo-hyph">-</span><span class="logo-badge">AMC</span>
      </div>
      <h1>$service Monthly Uptime — $month_name $year</h1>
      <div class="subline">$company • Client: $client • SLO: $slo% • Source: $source • Generated: $generated_at</div>

      <!-- CHANGE: removed the three KPI cards from Page 3 -->
      <!-- (intentionally left blank) -->

      <div class="charts-2">
        <div class="card"><div class="muted" style="font-weight:700; margin-bottom:2mm">A) Minute-by-minute (MTD)</div><div class="chart" id="m_chart"></div></div>
        <div class="card"><div class="muted" style="font-weight:700; margin-bottom:2mm">B) Hourly trend (MTD)</div><div class="chart" id="h_chart"></div></div>
      </div>

      <div class="charts-2">
        <div class="card"><div class="muted" style="font-weight:700; margin-bottom:2mm">C) Month-to-date by day</div><div class="chart" id="mc_chart"></div></div>
        <div class="card"><div class="muted" style="font-weight:700; margin-bottom:2mm">D) Year-to-date</div><div class="chart" id="y_chart"></div></div>
      </div>

      <div class="card" style="margin-top:6mm">
        <div class="muted" style="font-weight:700; margin-bottom:2mm">Per-canary availability (this month)</div>
        <div id="p_chart" style="height:70mm"></div>
      </div>

      <div class="card" style="margin-top:6mm">
        <div class="muted" style="font-weight:700; margin-bottom:2mm">Year-to-date table</div>
        <table class="tbl">
          <tr><th>Month</th><th align="right">Availability</th></tr>
          $table_rows_html
        </table>
      </div>

      <div class="card" style="margin-top:6mm">
        <div class="muted" style="font-weight:700; margin-bottom:2mm">Incidents (≥ $fail_streak consecutive failed minutes)</div>
        <table class="tbl">
          <tr><th>Start (UTC)</th><th>End (UTC)</th><th style="text-align:right">Minutes</th></tr>
          $incidents_rows
        </table>
        <div class="muted" style="margin-top:2mm">Missing minutes are $missing_policy.</div>
      </div>

      <div class="footer">Confidential &amp; Proprietary — © $year $company. All rights reserved.</div>
    </div>
  </div>

  <script>
    google.charts.load('current', {packages:['corechart']});
    google.charts.setOnLoadCallback(function(){
      var lineOpts = {legend:{position:'bottom'}, vAxis:{title:'%'}};
      function lineDT(id, rows){ var dt=new google.visualization.DataTable(); dt.addColumn('datetime','Time'); dt.addColumn('number','Availability %'); dt.addRows(rows); new google.visualization.LineChart(document.getElementById(id)).draw(dt, lineOpts); }
      function lineStr(id, rows, xlabel){ var dt=new google.visualization.DataTable(); dt.addColumn('string',xlabel); dt.addColumn('number','Availability %'); dt.addRows(rows); new google.visualization.LineChart(document.getElementById(id)).draw(dt, lineOpts); }
      lineDT('m_chart', [$min_js]); lineDT('h_chart', [$hr_js]); lineStr('mc_chart', [$mc_js], 'Day'); lineStr('y_chart', [$year_js], 'Month');
      var p=new google.visualization.DataTable(); p.addColumn('string','Canary'); p.addColumn('number','Availability %'); p.addRows([$per_js]); new google.visualization.ColumnChart(document.getElementById('p_chart')).draw(p,{legend:{position:'none'}});
      var av=parseFloat('$availability'); if(isNaN(av)) av=99.9; var slo=parseFloat('$slo'); if(isNaN(slo)) slo=99.9; var inc=parseInt('$incidents')||0; var down=parseInt('$downtime_min')||0;

      // CHANGE: Build a single concise paragraph for Page 2 (4–5 short lines when wrapped)
      var para=document.getElementById('summary_para');
      if(para){
        var parts=[
          'Availability: '+av.toFixed(3)+'%.',
          'Downtime: '+down+' minute(s) across '+inc+' incident(s).',
          'SLO target: '+slo.toFixed(3)+'%.',
          'Status: '+(av>=slo?'SLO MET':'SLO NOT MET')+'.',
          'Generated: $generated_at from $source.'
        ];
        para.textContent = parts.join(' ');
      }
    });
  </script>
</body>
</html>
""")

    html = page.substitute(
        title=f"{meta['service']} Monthly Uptime — {meta['month_name']} {meta['year']}",
        company=meta["company"],
        client=meta["client"],
        service=meta["service"],
        month_name=meta["month_name"],
        year=meta["year"],
        slo=f"{meta['slo']:.3f}",
        source=("artifact" if ONLY_BROWSER=="ANY" else ONLY_BROWSER),
        generated_at=generated_at,
        availability=f"{meta['availability']:.3f}",
        downtime_min=meta["downtime_min"],
        incidents=meta["incidents"],
        min_js=min_js, hr_js=hr_js, mc_js=mc_js, year_js=year_js, per_js=per_js,
        table_rows_html=table_rows_html,
        fail_streak=FAIL_STREAK,
        missing_policy=("treated as failures" if TREAT_MISSING else "ignored"),
        incidents_rows=incidents_rows
    )
    return html

# --------------------------- S3 helpers ------------------------------
def _put_csv(bucket: str, key: str, rows: List[Dict[str, Any]], cols: List[str]) -> None:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    s3.put_object(Bucket=bucket, Key=key, Body=out.getvalue().encode("utf-8"), ContentType="text/csv; charset=utf-8")

# --------------------------- Handler --------------------------------
def handler(event, context):
    now = _now_utc()
    start_m, end_m = month_window_utc(now)
    y = start_m.year; mo = start_m.month

    # Scan current month (MTD)
    agg_ok, agg_ms, _sampled = scan_window(y, mo, start_m, end_m)
    observed = sorted(agg_ok.keys()); total_obs=len(observed)
    log(f"[info] observed minutes this month: {total_obs}")
    up_obs=sum(1 for t in observed if agg_ok[t])
    availability=(up_obs/total_obs)*100.0 if total_obs else 0.0
    incidents=detect_incidents(agg_ok)
    downtime_min=sum(i["duration_minutes"] for i in incidents)

    base=f"{REPORTS_PREFIX}/{y}/{mo:02d}/"

    # Minute CSV (MTD)
    minute_rows=[{"ts": t.strftime("%Y-%m-%d %H:%M"), "avail": 100.0 if agg_ok[t] else 0.0, "resp_s": (agg_ms.get(t,0.0)/1000.0)} for t in observed]
    _put_csv(REPORTS_BUCKET, f"{base}uptime-minute.csv",
             [{"timestamp_utc": r["ts"], "availability_pct": f"{r['avail']:.3f}", "avg_response_sec": f"{r['resp_s']:.3f}"} for r in minute_rows],
             ["timestamp_utc","availability_pct","avg_response_sec"])

    # Hour CSV (MTD)
    hour_rows=hourly_reduce(agg_ok, agg_ms)
    _put_csv(REPORTS_BUCKET, f"{base}uptime-hour.csv",
             [{"hour_utc": r["hour"].strftime("%Y-%m-%d %H:%M"),
               "availability_pct": f"{(r['success_avg'] or 0.0):.3f}",
               "avg_response_sec": f"{((r['response_ms_avg'] or 0.0)/1000.0):.3f}"} for r in hour_rows],
             ["hour_utc","availability_pct","avg_response_sec"])

    # Month-to-date cumulative CSV (daily)
    mc_rows = month_cumulative(agg_ok, agg_ms)
    # pad missing days for the page chart/table
    mc_rows_padded = []
    have = {r["day"]: r for r in mc_rows}
    cur = start_m.date().replace(day=1)
    stop = end_m.date()
    while cur <= stop:
        key = cur.strftime("%Y-%m-%d")
        mc_rows_padded.append(have.get(key, {"day": key, "avail": None, "resp_s": None}))
        cur += timedelta(days=1)

    _put_csv(REPORTS_BUCKET, f"{base}uptime-month-cumulative.csv",
             [{"day_utc": r["day"],
               "cumulative_availability_pct": "" if r["avail"] is None else f"{r['avail']:.3f}",
               "cumulative_avg_response_sec": "" if r["resp_s"] is None else f"{r['resp_s']:.3f}"} for r in mc_rows_padded],
             ["day_utc","cumulative_availability_pct","cumulative_avg_response_sec"])

    # SLO (auto or fixed)
    slo_val = float(SLO_TARGET) if isinstance(SLO_TARGET, (int,float)) or (isinstance(SLO_TARGET,str) and SLO_TARGET.replace('.','',1).isdigit()) else compute_slo_auto(now)

    # YTD summary
    try:
        year_chart_rows, year_table_rows, year_csv = build_year_summary_ytd(
            availability,
            0.0,  # we no longer chart response; keep CSV schema
        )
        _put_csv(REPORTS_BUCKET, f"{REPORTS_PREFIX}/{y}/uptime-year-summary.csv",
                 year_csv, ["month","availability_pct","avg_response_sec"])
    except Exception as e:
        log(f"[warn] YTD summary skipped: {type(e).__name__}")
        year_chart_rows, year_table_rows = [], []

    # Render HTML (3 pages)
    meta=dict(
        company=COMPANY, client=CLIENT, service=SERVICE,
        year=str(y), month_name=start_m.strftime("%B"), slo=slo_val,
        availability=availability, downtime_min=downtime_min,
        incidents=len(incidents)
    )

    html = render_html(
        meta,
        minute_rows,
        [{"hour": r["hour"].strftime("%Y-%m-%d %H:%M"), "avail": (r["success_avg"] or 0.0)} for r in hour_rows],
        [{"day": r["day"], "avail": r["avail"]} for r in mc_rows_padded],
        [{"name": ART_PREFIX.split('/')[-1] if ART_PREFIX else 'artifacts', "pct": availability}],
        year_chart_rows,
        year_table_rows,
        incidents,
        generated_at=now.strftime("%Y-%m-%d %H:%M UTC")
    )

    html_key = f"{base}uptime-report.html"
    s3.put_object(
        Bucket=REPORTS_BUCKET,
        Key=html_key,
        Body=html.encode("utf-8"),
        ContentType="text/html; charset=utf-8"
    )

    return {
        "status":"ok",
        "artifacts": {"bucket": ART_BUCKET, "prefix": ART_PREFIX},
        "reports": {"bucket": REPORTS_BUCKET, "prefix": REPORTS_PREFIX},
        "result": {"bucket": REPORTS_BUCKET, "key": html_key},
        "html": f"s3://{REPORTS_BUCKET}/{html_key}"
    }
