# KomikCast REST API — Sanka-format

API JSON untuk **KomikCast** yang meniru bentuk endpoint + response
[Sanka Vollerei](https://www.sankavollerei.web.id/comic/komikindo).
Ganti `komikindo` → `komikcast` di URL, response-nya tetap sama.

```
Sanka    : https://www.sankavollerei.web.id/comic/komikindo/latest/1
Drop-in  : https://komikcast.aoxi.my.id/comic/komikcast/latest/1
```

## URL publik

**https://komikcast.aoxi.my.id/comic/komikcast**

Named Cloudflare tunnel, jadi hostname-nya tetap (tidak berubah tiap
restart seperti quick tunnel). Unit: `komikcast-sanka-tunnel.service`,
config: `named-config.yml` (tunnel `komikcast-sanka`,
`4e301198-bab0-4184-856a-0e5e4e9ce8b4`).

## Endpoint (sama seperti Sanka)

- `GET /comic/komikcast/latest/:page` — komik terbaru
- `GET /comic/komikcast/detail/:slug` — detail, sinopsis, daftar chapter
- `GET /comic/komikcast/chapter/:slug` — isi chapter `{komik}-chapter-{n}`
- `GET /comic/komikcast/library?page=1` — daftar komik + filter
- `GET /comic/komikcast/genres` — semua genre
- `GET /comic/komikcast/search/:query/:page` — cari komik

## Bentuk response (identik Sanka)

```json
{
  "creator": "Sanka Vollerei",
  "success": true,
  "pagination": {"currentPage": 1, "totalPages": 323,
                 "hasNextPage": true, "nextPage": 2},
  "komikList": [
    {"title": "...", "slug": "...", "image": "...", "type": "Manhwa",
     "color": null,
     "chapters": [{"title": "Chapter 9", "slug": "...-chapter-9",
                   "date": "5 menit lalu"}]}
  ],
  "komikPopuler": [
    {"rank": "1", "title": "...", "slug": "...", "author": "...",
     "rating": "9.8", "image": "..."}
  ]
}
```

Detail (`data.detail`, `genres[]`, `firstChapter`, `latestChapter`,
`chapters[]`) dan chapter (`navigation.prev/next`, `allChapterSlug`,
`images[].id/url`) mengikuti Sanka persis.

## Sumber data

Layer ini hanya **membentuk ulang** (reshape) data dari API KomikCast
passthrough lokal di `http://127.0.0.1:8791` (`komikcast-api.service`).
Tidak menyimpan apa pun sendiri.

## Jalankan

```bash
python3 server.py --host 127.0.0.1 --port 8795
```

Service: `komikcast-sanka.service` (+ `komikcast-sanka-tunnel.service`
untuk link publik cloudflared).

```bash
systemctl --user status komikcast-sanka
systemctl --user status komikcast-sanka-tunnel
curl -s https://komikcast.aoxi.my.id/comic/komikcast | head -5
```

## Catatan

- `color` selalu `null`: KomikCast tidak menyimpan penanda Hitam/Putih/Warna
  seperti Komikindo. Struktur tetap sama, nilainya saja yang kosong.
- `komikPopuler` = 10 judul teratas dari `sort=popular` (views) KomikCast.
- Slug antar sumber berbeda: slug Sanka/Komikindo (mis. `one-piece`) tidak
  ada di KomikCast. Selalu pakai slug dari `latest`/`library`/`search`
  API ini sendiri.
- **Chapter desimal didukung** (`blue-lock-chapter-364.2`). KomikCast
  memang punya chapter seperti 364.2 / 268.5.
- **Urutan `chapters`**: terbaru ke terlama, sama seperti Sanka.
  `firstChapter` = chapter paling awal, `latestChapter` = paling baru.
- **Root `/comic/komikcast` sengaja beda** dari Sanka (mereka balas
  `status`/`message`), karena root di sini dipakai sebagai katalog endpoint.
  Route datanya identik.

## Uji

```bash
bash smoke.sh        # 7 endpoint lewat tunnel, cek isi JSON
python3 parity.py    # diff struktur vs Sanka asli, per endpoint
```
