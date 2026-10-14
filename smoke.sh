#!/usr/bin/env bash
# Smoke test semua endpoint KomikCast Sanka API.
#   ./smoke.sh                     # lewat tunnel publik
#   BASE=http://127.0.0.1:8795 ./smoke.sh
#
# Catatan: /library memakan waktu ~1 menit (upstream KomikCast lambat),
# timeout di bawah sudah dilebihkan.
set -u
B=${BASE:-https://komikcast.aoxi.my.id}
pass=0; fail=0

# Resolver lokal (202.182.48.243) bisa lambat/NXDOMAIN untuk hostname baru
# walau record globalnya sudah live. Kalau begitu, lewati resolver lokal
# dengan DoH, jangan ubah apa pun di sisi tunnel.
EXTRA=""
HOST=$(printf '%s' "$B" | sed -E 's#https?://([^/:]+).*#\1#')
if ! getent hosts "$HOST" >/dev/null 2>&1; then
  EXTRA="--doh-url https://cloudflare-dns.com/dns-query"
  echo "note: $HOST belum resolve di resolver lokal, pakai DoH"
fi

chk() { # chk <label> <path> <grep-pattern>
  local code body
  body=$(curl -s -m 180 $EXTRA -w '\n%{http_code}' "$B$2")
  code=$(printf '%s' "$body" | tail -1)
  body=$(printf '%s' "$body" | head -n -1)
  if [ "$code" = "200" ] && printf '%s' "$body" | grep -q "$3"; then
    echo "PASS  $1  (HTTP $code)"; pass=$((pass+1))
  else
    echo "FAIL  $1  (HTTP $code)"; fail=$((fail+1))
  fi
}

chk "root"        "/comic/komikcast"                '"creator": "Sanka Vollerei"'
chk "latest/1"    "/comic/komikcast/latest/1"       '"komikList"'
chk "detail"      "/comic/komikcast/detail/empyreal-cabinet" '"firstChapter"'
chk "chapter"     "/comic/komikcast/chapter/empyreal-cabinet-chapter-9" '"allChapterSlug"'
chk "library"     "/comic/komikcast/library?page=1" '"filters"'
chk "genres"      "/comic/komikcast/genres"         '"genres"'
chk "search"      "/comic/komikcast/search/naruto/1" '"query": "naruto"'

echo "---"
echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
