#!/usr/bin/env python3
"""
KomikCast REST API -- Sanka-format (drop-in for Sanka's /comic/komikindo).

Serves the same endpoint paths and JSON response shapes as
https://www.sankavollerei.web.id/comic/komikindo/... but sourced from
KomikCast (komikcast.info). Point your frontend here and only change
`komikindo` -> `komikcast` in the URL.

Data source: the local KomikCast passthrough API at LOCAL (the existing
komikcast-api.service on :8791). This layer only reshapes.

    python3 server.py [--port 8795] [--host 127.0.0.1]
"""
import argparse
import datetime
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0.0"
CREATOR = "Sanka Vollerei"          # same value as the reference API so a
                                    # drop-in swap keeps exactly identical JSON
LOCAL = "http://127.0.0.1:8791"     # KomikCast passthrough backbone
TIMEOUT = 90

HEADERS = {"Accept": "application/json, text/plain, */*"}


class ApiError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


# ------------------------------------------------------------------ upstream

def local_get(path, params=None):
    """GET the local KomikCast API; raise ApiError on non-200."""
    url = LOCAL + path
    if params:
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        if clean:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(clean)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, "backend %s -> HTTP %d" % (path, e.code))
    except Exception as e:
        raise ApiError(502, "backend %s tidak bisa dihubungi: %s" % (path, e))


def local_data(path, params=None):
    """Call LOCAL and return its `data` payload; 404 if it signals failure."""
    j = local_get(path, params)
    if not isinstance(j, dict):
        raise ApiError(404, "backend %s kosong (tidak ada)" % path)
    if j.get("ok") is False:
        msg = (j.get("error") or {}).get("message") if isinstance(j.get("error"), dict) else None
        raise ApiError(404, msg or "resource tidak ada di backend")
    return j.get("data")


# ------------------------------------------------------------------- helpers

def rel_time(iso):
    """ISO timestamp -> Indonesian relative string (seperti format Sanka)."""
    if not iso:
        return None
    raw = iso
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(raw)
    except Exception:
        return None
    tz = dt.tzinfo or datetime.timezone.utc
    now = datetime.datetime.now(tz)
    sec = max(0, int((now - dt).total_seconds()))
    minutes = sec // 60
    if minutes < 1:
        return "baru saja"
    if minutes < 60:
        return "%d menit lalu" % minutes
    hours = minutes // 60
    if hours < 24:
        return "%d jam lalu" % hours
    days = hours // 24
    if days < 30:
        return "%d hari lalu" % days
    months = days // 30
    if months < 12:
        return "%d bulan lalu" % months
    years = months // 12
    return "%d tahun lalu" % years


def rating_str(v):
    """KomikCast rating (None/ganda) -> string Sanka (fallback '0')."""
    if v is None:
        return "0"
    return str(v).rstrip(".0") if isinstance(v, float) else str(v)


def num_str(v):
    """Nomor chapter -> string tanpa ekor '.0'.

    364   -> '364'
    364.2 -> '364.2'
    """
    if v is None:
        return None
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v)


def chapter_slug(manga_slug, number):
    """Full chapter slug yang dikenali route /comic/komikcast/chapter/<slug>."""
    n = num_str(number)
    if not n:
        return None
    return "%s-chapter-%s" % (manga_slug, n)


def chapter_slug_of(manga_slug, chapter):
    if not chapter:
        return None
    return chapter_slug(manga_slug, chapter.get("chapter_number"))


def parse_chapter_slug(slug):
    """'{manga}-chapter-{n}' -> (manga_slug, n). None jika tidak cocok.

    `n` boleh desimal: KomikCast memakai chapter seperti '364.2'.
    """
    m = re.match(r"^(.*)-chapter-(\d+(?:\.\d+)?)$", slug)
    if not m:
        return None
    return m.group(1), m.group(2)


def list_item(it, with_color=True):
    """Item komikcast -> bentuk item di komikList Sanka (library/search)."""
    out = {
        "title": it.get("title"),
        "rating": rating_str(it.get("rating")),
        "slug": it.get("slug"),
        "image": it.get("poster"),
        "type": it.get("type"),
    }
    if with_color:
        out["color"] = None
    return out


def popular_item(it, rank):
    """Item komikcast -> bentuk item komikPopuler Sanka (rank, author)."""
    return {
        "rank": str(rank),
        "title": it.get("title"),
        "slug": it.get("slug"),
        "author": it.get("author") or (it.get("last_chapter") or {}).get("title"),
        "rating": rating_str(it.get("rating")),
        "image": it.get("poster"),
    }


def komik_populer():
    """Top 10 dari upstream (sort=popular) -> selalu dirutekan ke sini."""
    dd = local_data("/api/manga", {"per_page": 10, "page": 1, "sort": "popular"})
    got = dd.get("mangas") or []
    return [popular_item(it, i + 1) for i, it in enumerate(got[:10])]


def latest_item(it):
    """Item komikcast -> bentuk item latest Sanka (punya chapters[])."""
    lc = it.get("last_chapter") or {}
    chapters = []
    if lc and lc.get("title"):
        chapters.append({
            "title": lc.get("title"),
            "slug": chapter_slug(it.get("slug"), lc.get("chapter_number")),
            "date": rel_time(lc.get("updated_at") or lc.get("created_at")),
        })
    return {
        "title": it.get("title"),
        "slug": it.get("slug"),
        "image": it.get("poster"),
        "type": it.get("type"),
        "color": None,
        "chapters": chapters,
    }


def pagination(pg, page):
    has_next = bool(pg.get("hasNextPage", False))
    return {
        "currentPage": page,
        "totalPages": pg.get("lastPage"),
        "hasNextPage": has_next,
        "nextPage": (page + 1) if has_next else None,
    }


# --------------------------------------------------------------- bank root

def h_root(env):
    return {
        "creator": CREATOR,
        "success": True,
        "name": "KomikCast REST API (Sanka-format)",
        "version": VERSION,
        "base": LOCAL,
        "note": "Drop-in untuk /comic/komikindo Sanka: ganti komikindo -> "
                "komikcast di URL, response tetap sama.",
        "endpoints": ENDPOINTS,
    }


# ------------------------------------------------------------------ routes

def h_latest(env):
    page = int_arg(env, "page", minimum=1)
    dd = local_data("/api/manga", {
        "per_page": 24, "page": page, "sort": "latest_update"})
    pg = pagination(dd["_pagination"], page)
    return {"creator": CREATOR, "success": True, "pagination": pg,
            "komikList": [latest_item(i) for i in (dd.get("mangas") or [])],
            "komikPopuler": komik_populer()}


def h_detail(env):
    slug = env["vars"]["slug"]
    dd = local_data("/api/manga/" + urllib.parse.quote(slug))
    m = dd.get("manga") or {}
    chapters = m.get("chapters") or []
    # Upstream sudah newest-first (sama seperti Sanka), jadi JANGAN dibalik:
    # Sanka juga mengirim chapters[] dari terbaru ke terlama.
    chlist = [{
        "title": c.get("title"),
        "slug": chapter_slug(slug, c.get("chapter_number")),
        "releaseTime": rel_time(c.get("created_at")),
    } for c in chapters]
    latest = chlist[0] if chlist else None      # terbaru
    first = chlist[-1] if chlist else None      # paling awal
    genres = [{"name": g.get("name"), "slug": "/genres/" + str(g.get("slug", ""))}
              for g in (m.get("genres") or [])]
    # relatedMangas (bentuknya sama seperti Sanka similarManga)
    def rel_image(r):
        p = r.get("poster")
        if not p:
            return None
        return p if p.startswith("http") else ("http://127.0.0.1:8791" + p)

    similar = [{
        "title": r.get("title"),
        "slug": r.get("slug"),
        "image": rel_image(r),
        "description": (r.get("synopsis") or "")[:200],
    } for r in (dd.get("relatedMangas") or [])]
    data = {
        "id": str(m.get("id")),
        "title": m.get("title"),
        "image": m.get("poster"),
        "rating": rating_str(m.get("rating")),
        "votes": str(dd.get("totalRaters") or m.get("ratings_count") or 0) + " Orang",
        "detail": {
            "alternativeTitle": None,
            "status": m.get("status"),
            "author": m.get("author"),
            "illustrator": m.get("artist"),
            "type": m.get("type"),
            "theme": None,
        },
        "genres": genres,
        "description": m.get("synopsis"),
        "firstChapter": {"title": first["title"], "slug": first["slug"]} if first else None,
        "latestChapter": {"title": latest["title"], "slug": latest["slug"]} if latest else None,
        "chapters": chlist,
        "spoilerImages": [],
        "similarManga": similar,
    }
    return {"creator": CREATOR, "success": True, "data": data}


def h_chapter(env):
    parsed = parse_chapter_slug(env["vars"]["slug"])
    if not parsed:
        raise ApiError(404, "slug harus berbentuk {komik}-chapter-{n}")
    manga_slug, num = parsed
    dd = local_data("/api/manga/%s/chapter/%s"
                    % (urllib.parse.quote(manga_slug), urllib.parse.quote(num)))
    ch = dd.get("chapter") or {}
    ordered = dd.get("imageUrls") or []
    images = [{"id": i + 1, "url": u} for i, u in enumerate(ordered)]
    prev = chapter_slug_of(manga_slug, dd.get("prev"))
    nxt = chapter_slug_of(manga_slug, dd.get("next"))

    # thumbnail + komikInfo: Sanka menyertakannya di /chapter, jadi ambil
    # dari detail komik yang sama. `komikInfo.chapters` = 5 chapter terbaru
    # (tanpa releaseTime), sama seperti Sanka.
    info, chapters, poster_url = {}, [], None
    try:
        det = local_data("/api/manga/" + urllib.parse.quote(manga_slug))
        m = det.get("manga") or {}
        poster = m.get("poster")
        if poster and not poster.startswith("http"):
            poster = "http://127.0.0.1:8791" + poster
        poster_url = poster
        info = {
            "title": "Komik %s Indo" % (m.get("title") or manga_slug),
            "description": m.get("synopsis"),
        }
        # upstream sudah newest-first; Sanka juga begitu -> cukup ambil 5 teratas
        recent = (m.get("chapters") or [])[:5]
        chapters = [{
            "title": c.get("title"),
            "slug": chapter_slug(manga_slug, c.get("chapter_number")),
        } for c in recent]
    except ApiError:
        pass
    info["chapters"] = chapters

    data = {
        "id": str(ch.get("id")),
        "title": ch.get("title") or ("%s Chapter %s" % (manga_slug, num)),
        "navigation": {"prev": prev, "next": nxt},
        "allChapterSlug": manga_slug,
        "images": images,
        "thumbnail": {"url": poster_url, "title": info.get("title")},
        "komikInfo": info,
    }
    return {"creator": CREATOR, "success": True, "data": data}


def h_library(env):
    page = int_arg(env, "page", default=1, minimum=1)
    q = (env["query"].get("q") or env["query"].get("m") or "").strip()
    keys = ("q", "m", "genre", "type", "status", "orderby", "sort")
    filters = {k: v for k, v in env["query"].items() if k in keys}
    filters.pop("page", None)

    if q:
        dd = local_data("/api/search", {
            "q": q, "category": "manga", "page": page, "per_page": 24})
        items = [i for i in (dd.get("results") or []) if i.get("category") == "manga"]
        pg = dd.get("_pagination") or {}
    else:
        lp = {"per_page": 24, "page": page}
        for k in ("genre", "type", "status"):
            if env["query"].get(k):
                lp[k] = env["query"][k]
        orderby = env["query"].get("orderby") or env["query"].get("sort")
        if orderby:
            lp["sort"] = {"update": "latest_update", "popular": "popular",
                          "title": "title", "rating": "rating"}.get(orderby, orderby)
        dd = local_data("/api/manga", lp)
        items = dd.get("mangas") or []
        pg = dd.get("_pagination") or {}

    return {"creator": CREATOR, "success": True,
            "pagination": pagination(pg, page),
            "filters": filters,
            "komikList": [list_item(i) for i in items],
            "komikPopuler": komik_populer()}


def h_genres(env):
    genres = local_data("/api/genres")
    out = [{"name": g.get("name"), "value": g.get("slug")}
           for g in (genres.get("genres") or [])]
    return {"creator": CREATOR, "success": True, "genres": out}


def h_search(env):
    query = urllib.parse.unquote(env["vars"]["query"]).strip()
    page = int_arg(env, "page", minimum=1)
    dd = local_data("/api/search", {
        "q": query, "category": "manga", "page": page, "per_page": 24})
    items = [i for i in (dd.get("results") or []) if i.get("category") == "manga"]
    pg = dd.get("_pagination") or {}
    has_next = bool(pg.get("hasNextPage", False))
    return {"creator": CREATOR, "success": True, "query": query,
            "pagination": {"currentPage": page, "hasNextPage": has_next,
                           "nextPage": (page + 1) if has_next else None},
            "komikList": [list_item(i, with_color=False) for i in items]}


# --------------------------------------------------------------------- arg

def int_arg(env, name, default=None, minimum=None):
    raw = env["vars"].get(name)
    if raw is None:
        raw = env["query"].get(name)
    if raw is None or raw == "":
        if default is None and minimum is not None:
            raise ApiError(400, "parameter %r wajib diisi" % name)
        return default
    if not re.fullmatch(r"-?\d+", raw):
        raise ApiError(400, "parameter %r harus angka, dapat %r" % (name, raw))
    v = int(raw)
    if minimum is not None and v < minimum:
        raise ApiError(400, "parameter %r minimal %d" % (name, minimum))
    return v


ENDPOINTS = [
    {"method": "GET", "path": "/comic/komikcast",
     "desc": "Katalog endpoint (identik dengan /)"},
    {"method": "GET", "path": "/comic/komikcast/latest/:page",
     "desc": "Komik terbaru (KomikCast), format sama /comic/komikindo/latest/:page"},
    {"method": "GET", "path": "/comic/komikcast/detail/:slug",
     "desc": "Info detail, sinopsis, daftar chapter"},
    {"method": "GET", "path": "/comic/komikcast/chapter/:slug",
     "desc": "Isi chapter {komik}-chapter-{n}"},
    {"method": "GET", "path": "/comic/komikcast/library?page=1",
     "desc": "Daftar komik + filter genre/type/status/orderby/q"},
    {"method": "GET", "path": "/comic/komikcast/genres",
     "desc": "Semua genre"},
    {"method": "GET", "path": "/comic/komikcast/search/:query/:page",
     "desc": "Cari komik berdasarkan judul"},
]

ROUTES = [
    r"^/$",
    r"^/comic/komikcast$",
    r"^/comic/komikcast/latest/(?P<page>\d+)$",
    r"^/comic/komikcast/detail/(?P<slug>[^/]+)$",
    r"^/comic/komikcast/chapter/(?P<slug>[^/]+)$",
    r"^/comic/komikcast/library$",
    r"^/comic/komikcast/genres$",
    r"^/comic/komikcast/search/(?P<query>[^/]+)/(?P<page>\d+)$",
]
HANDLERS = [h_root, h_root, h_latest, h_detail, h_chapter, h_library,
            h_genres, h_search]
COMPILED = [(re.compile(p), fn) for p, fn in zip(ROUTES, HANDLERS)]


# ------------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "KomikCastSanka/" + VERSION

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))
        sys.stderr.flush()

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        t0 = time.time()
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        q = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
        env = {"query": {k: v[0] for k, v in q.items()}, "vars": {}}
        fn, m = None, None
        for rx, handler in COMPILED:
            m = rx.match(path)
            if m:
                fn = handler
                break
        if fn is None:
            self._send(404, {"creator": CREATOR, "success": False, "error": {
                "code": 404,
                "message": "route %r tidak ada. lihat GET /comic/komikcast" % path}})
            return
        env["vars"] = m.groupdict()
        try:
            data = fn(env)
            self._send(200, data)
        except ApiError as e:
            self._send(e.code, {"creator": CREATOR, "success": False,
                                "error": {"code": e.code, "message": e.message}})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"creator": CREATOR, "success": False,
                             "error": {"code": 500, "message": "%s: %s" % (
                                 type(e).__name__, e)}})


def main():
    ap = argparse.ArgumentParser(description="KomikCast API (Sanka-format)")
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8795")))
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    print("KomikCast Sanka-format API %s di http://%s:%d" % (VERSION, a.host, a.port),
          flush=True)
    print("data backbone: %s" % LOCAL, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nberhenti.", flush=True)


if __name__ == "__main__":
    main()