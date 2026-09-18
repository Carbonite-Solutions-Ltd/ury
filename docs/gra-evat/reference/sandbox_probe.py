"""Sandbox probe harness for GRA E-VAT staging.

Usage:  EVAT_REF=CXX000000YY-006 python3 -c "from sandbox_probe import *; call(...)"
Every call is appended to $EVAT_PROBE_LOG (default sandbox-probes.jsonl).
The keys below are GRA's PUBLIC staging keys, copied from the official docs.
NEVER put production keys in this file or anywhere in git.
"""
import json, time, urllib.request, urllib.error, datetime, sys
import os
KEYS = {
    "CXX000000YY-001": "Z60gftKe9sei3xOZhvvDa0StkVILKR3j5MBM9ygi1zg=",
    "CXX000000YY-006": "xbPeYDaPFG7bqnNO7WThWRDrBhKggz+ls/6rV38zyA1iqe7dPg8Pc2EElmrUq+2v",
    "CXX000000YY-007": "49BvCVhgjRxx3kbE4hiCLZrq8VKjKpKt0zfW1pJg9wClpcXOttM6cV83UtitMAx3",
    "CXX000000YY-008": "Yqu34/kLbewAY1NCH3lKjUEaZFFNtoxpiLzKGI8JrcdrUmxO9ud8dZO2Nx/mQPAE",
}
REF = os.environ.get("EVAT_REF", "CXX000000YY-001")
KEY = KEYS[REF]
HOST = "https://vsdcstaging.vat-gh.com/vsdc/api/v1/taxpayer/" + REF
LOG = os.environ.get("EVAT_PROBE_LOG", "sandbox-probes.jsonl")
RUN = datetime.datetime.now().strftime("%y%m%d%H%M%S")

def call(label, path, body, expect=None):
    req = urllib.request.Request(f"{HOST}/{path}", data=json.dumps(body).encode(),
        headers={"security_key": KEY, "Content-Type": "application/json"}, method="POST")
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            code, raw = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read().decode()
    dt = round(time.time() - t, 2)
    try: resp = json.loads(raw)
    except Exception: resp = raw
    if isinstance(resp, dict) and resp.get("response"):
        m = resp["response"]["message"]
        short = f"OK {m['flag']} rec={m['ysdcrecnum']} items={m['ysdcitems']}"
    elif isinstance(resp, dict):
        short = f"{resp.get('code')} {resp.get('message')}"
    else:
        short = str(resp)[:120]
    verdict = "" if expect is None else ("  ✔ as expected" if expect in short else f"  ✘ expected {expect}")
    print(f"[{code} {dt:>4}s] {label:<58} -> {short}{verdict}")
    with open(LOG, "a") as f:
        f.write(json.dumps({"label": label, "path": path, "request": body, "http": code,
                            "seconds": dt, "response": resp}) + "\n")
    time.sleep(1.3)   # stay far below the 50 req/min ceiling
    return code, resp

def item(code, desc, qty, price, a, b, d=0, e=0, cat="", disc=0, exc=0):
    return {"itemCode": code, "itemCategory": cat, "expireDate": "", "description": desc,
            "quantity": qty, "levyAmountA": a, "levyAmountB": b, "levyAmountD": d,
            "levyAmountE": e, "discountAmount": disc, "exciseAmount": exc,
            "batchCode": "", "unitPrice": price}

def inv(num, items, total_amount, vat, levy, calc="INCLUSIVE", flag="INVOICE", ref="",
        date="2026-09-17", disc_type="GENERAL", disc=0, tin="C0000000000",
        name="Ama Ghana (Cash Customer)", excise=0):
    return {"currency": "GHS", "exchangeRate": 1.0, "invoiceNumber": num,
            "totalLevy": levy, "userName": "URY Probe", "flag": flag,
            "calculationType": calc, "totalVat": vat, "transactionDate": date,
            "totalAmount": total_amount, "totalExciseAmount": excise,
            "businessPartnerName": name, "businessPartnerTin": tin,
            "saleType": "NORMAL", "discountType": disc_type, "discountAmount": disc,
            "reference": ref, "groupReferenceId": "", "purchaseOrderReference": "",
            "items": items}
