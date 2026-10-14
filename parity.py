#!/usr/bin/env python3
"""Diff bentuk JSON API ini vs Sanka asli (/comic/komikindo).

Membandingkan struktur, nama key, dan tipe secara rekursif untuk tiap
endpoint. Tujuannya: kalau ada yang beda, kelihatan sebelum user nemu.

    python3 parity.py                 # Sanka asli vs tunnel publik
    python3 parity.py --ours http://127.0.0.1:8795/comic/komikcast
"""
import argparse
import json
import subprocess
import sys

SANKA = "https://www.sankavollerei.web.id/comic/komikindo"
DOH = "https://cloudflare-dns.com/dns-query"


def get(url, t=180):
    out = subprocess.run(["curl", "-s", "-m", str(t), "--doh-url", DOH, url],
                         capture_output=True, text=True).stdout
    try:
        return json.loads(out)
    except Exception as e:
        return {"__parse_error__": str(e), "__raw__": out[:160]}


def shape(o):
    if isinstance(o, dict):
        return {k: shape(v) for k, v in o.items()}
    if isinstance(o, list):
        return ["list", shape(o[0])] if o else "list[]"
    if o is None:
        return "null"
    return type(o).__name__


def keydiff(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            sub = f"{path}.{k}" if path else k
            if k not in a:
                out.append(f"    KITA LEBIH : {sub}")
            elif k not in b:
                out.append(f"    SANKA SAJA : {sub}")
            else:
                out.extend(keydiff(a[k], b[k], sub))
    elif isinstance(a, list) and isinstance(b, list) and len(a) == 2 and len(b) == 2:
        out.extend(keydiff(a[1], b[1], path + "[]"))
    return out


def cmp(label, sanka_url, ours_url):
    s, o = get(sanka_url), get(ours_url)
    diff = keydiff(shape(s), shape(o))
    print(f"[{'BEDA' if diff else 'SAMA'}] {label}")
    for line in diff:
        print(line)
    return not diff


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", default="https://komikcast.aoxi.my.id/comic/komikcast")
    a = ap.parse_args()
    S, O = SANKA, a.ours.rstrip("/")
    ok = 0
    total = 0

    def run(label, sp, op):
        nonlocal ok, total
        total += 1
        ok += 1 if cmp(label, S + sp, O + op) else 0

    run("root", "", "")
    run("latest/1", "/latest/1", "/latest/1")
    run("genres", "/genres", "/genres")
    run("library?page=1", "/library?page=1", "/library?page=1")
    run("search/naruto/1", "/search/naruto/1", "/search/naruto/1")

    # slug beda antar sumber: ambil dari latest masing-masing
    ss = (get(S + "/latest/1").get("komikList") or [{}])[0].get("slug")
    os_ = (get(O + "/latest/1").get("komikList") or [{}])[0].get("slug")
    run(f"detail (sanka={ss} kita={os_})", f"/detail/{ss}", f"/detail/{os_}")

    sd = (get(f"{S}/detail/{ss}").get("data") or {}).get("latestChapter") or {}
    od = (get(f"{O}/detail/{os_}").get("data") or {}).get("latestChapter") or {}
    run(f"chapter (sanka={sd.get('slug')} kita={od.get('slug')})",
        f"/chapter/{sd.get('slug')}", f"/chapter/{od.get('slug')}")

    print(f"\n{ok}/{total} endpoint identik dengan Sanka")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
