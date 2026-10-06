# Panduan Pockie Ninja Auto-Clicker

Panduan ini ngejelasin cara pakai, atur, dan benerin masalah di alat auto-clicker yang udah kita bikin. Ditulis santai, gak pake istilah teknis yang ribet.

---

## Daftar Isi

1. [Apa Ini dan Cara Kerjanya](#1-apa-ini-dan-cara-kerjanya)
2. [Instalasi](#2-instalasi)
3. [Struktur Folder](#3-struktur-folder)
4. [Cara Kasih Nama File Template](#4-cara-kasih-nama-file-template)
5. [config.json — Biar Nama File Bisa Pendek](#5-configjson--biar-nama-file-bisa-pendek)
6. [Nge-scope ke Satu Area (Section)](#6-nge-scope-ke-satu-area-section)
7. [Beda-beda Ikon/Tombol Tapi Mirip (Saturasi)](#7-beda-beda-ikontombol-tapi-mirip-saturasi)
8. [Ganti-ganti Map (maps/)](#8-ganti-ganti-map-maps)
9. [Semua Hotkey](#9-semua-hotkey)
10. [Tool Bantuan](#10-tool-bantuan)
11. [Troubleshooting](#11-troubleshooting)
12. [Tips Biar Awet](#12-tips-biar-awet)

---

## 1. Apa Ini dan Cara Kerjanya

Alat ini nyari gambar (screenshot tombol/ikon/boss yang lo kasih) di layar, dan kalau ketemu, otomatis diklik. Bedanya sama macro biasa yang pake waktu (delay tetap), alat ini **reaktif** — dia terus-terusan ngescan layar tiap 0.15 detik, jadi begitu sesuatu muncul, langsung diklik, gak perlu nunggu delay yang gak pasti.

File utamanya:

- `auto_clicker_opencv.py` — program utamanya
- `find_coords.py` — bantu cari koordinat pixel di layar
- `check_saturation.py` — bantu cari angka saturasi (kepake buat bedain ikon aktif vs nonaktif)
- `requirements.txt` — daftar library yang perlu di-install

---

## 2. Instalasi

```
pip install -r requirements.txt
```

Jalanin program:

```
python auto_clicker_opencv.py
```

---

## 3. Struktur Folder

Paling simpel, taro semua screenshot di folder `templates/`:

```
templates/
    01_stage_banner_click.png
    02_close_button_click.png
```

Kalau butuh ngelompokin beberapa template jadi satu "section" (misal biar gak ketuker sama tombol yang mirip di tempat lain), bikin subfolder:

```
templates/
    01_stage_banner_click.png
    tailed_beast_normal/
        region.txt
        03_fight_button_click.png
```

Lihat [bagian 6](#6-nge-scope-ke-satu-area-section) buat penjelasan lengkap soal section.

---

## 4. Cara Kasih Nama File Template

Format nama file (semua bagian dalam `[ ]` itu opsional):

```
<prioritas>_<nama>[@confidence][_click|_noclick][_satNN][_predelayNN][_delayNN].png
```

| Bagian | Fungsi | Contoh |
| --- | --- | --- |
| `<prioritas>` | Angka urutan pengecekan. Makin kecil, makin duluan dicek/diklik. | `01_`, `02_` |
| `<nama>` | Cuma buat label di log konsol, bebas mau nulis apa | `fight_button` |
| `@confidence` | Seberapa mirip gambarnya harus cocok (0-1). Default `0.85` | `@0.9` |
| `_click` | (default) diklik kalau ketemu | — |
| `_noclick` | cuma dideteksi, gak diklik — buat checkpoint atau anchor section | `_noclick` |
| `_satNN` | minimal saturasi warna (0-255) biar diklik — buat bedain ikon aktif vs abu-abu/disabled | `_sat40` |
| `_predelayNN` | tunggu NN milidetik SEBELUM klik, terus cek ulang masih ada apa enggak | `_predelay500` |
| `_delayNN` | tunggu NN milidetik SETELAH diklik, sebelum boleh klik lagi | `_delay800` |

**Contoh lengkap:**

```
03_fight_button_click_sat40_predelay500_delay800.png
```

Artinya: prioritas 3, diklik, minimal saturasi 40, tunggu 500ms sebelum klik (cek ulang dulu), tunggu 800ms setelah klik sebelum boleh klik lagi.

---

## 5. Config File — Biar Nama File Bisa Pendek

Daripada nulis semua pengaturan di nama file (jadi panjang & ribet), bisa taro di file config JSON. Ada **2 tingkat**, ditumpuk dari yang paling umum sampai paling spesifik — yang belakang menang kalau ada bentrok:

1. **Tag di nama file** (lihat [bagian 4](#4-cara-kasih-nama-file-template))
2. **`global_config.json`** — ditaro di ROOT project (sejajar sama `auto_clicker_opencv.py`, `templates/`, `maps/`). Berlaku ke **SEMUA map/profile** sekaligus.
3. **`config.json`** — ditaro di root tiap profile (`templates/config.json`, atau `maps/<nama_map>/config.json`). Cuma berlaku buat map itu doang, tapi **nimpa** apa pun yang diset di `global_config.json` buat map tersebut.

Jadi kalau mau 1 setting berlaku di semua map, taro di `global_config.json`. Kalau ada 1 map yang butuh pengecualian, cukup tambahin `config.json` khusus map itu — map lain yang gak punya `config.json` sendiri tetap ikut aturan global.

### Format-nya (sama buat kedua file)

```json
{
  "_defaults": { "confidence": 0.88, "min_saturation": 40 },
  "close_button.png": { "priority": 2, "delay_ms": 800 },
  "tailed_beast_normal/fight_button.png": {
    "priority": 3,
    "min_saturation": 60,
    "pre_delay_ms": 500
  }
}
```

- `"_defaults"` berlaku buat semua template dalam cakupannya (semua map untuk `global_config.json`; 1 map doang untuk `config.json`-nya map itu), kecuali ada entry spesifik yang nimpa.
- Key selain `_defaults` adalah **path relatif** dari root profile-nya, pake `/` walaupun di Windows.
- Khusus di `global_config.json`, kalau mau nargetin 1 file spesifik di 1 map tertentu (bukan lewat `_defaults`), kasih prefix nama map-nya: `"nama_map/tailed_beast_normal/fight_button.png": { ... }`. Di mode 1-map (`templates/` doang, gak pakai `maps/`), gak perlu prefix.
- Setting yang dikenal: `confidence` (float), `click` (true/false), `min_saturation` (int), `pre_delay_ms` (int), `delay_ms` (int), `priority` (int).
- Kalau sebagian setting gak diset di config manapun, otomatis jatuh ke tag nama file; kalau itu juga gak ada, pakai default bawaan program.

### Contoh Konkret

Mau saturasi minimal 40 berlaku di semua map, tapi map `tailed_beast` butuh 60 karena ikonnya beda:

**`global_config.json`** (di root project):

```json
{ "_defaults": { "min_saturation": 40, "confidence": 0.88 } }
```

**`maps/tailed_beast/config.json`**:

```json
{ "_defaults": { "min_saturation": 60 } }
```

Hasilnya: map `tailed_beast` pakai saturasi 60 (confidence tetap ikut global 0.88 karena gak ditimpa), map-map lain tetap pakai saturasi 40 dari global.

### Struktur Folder Lengkap

```
auto_clicker_opencv.py
global_config.json
templates/                       <- dipakai kalau gak ada folder maps/
    config.json
    close_button.png
    tailed_beast_normal/
        region.txt
        fight_button.png

maps/                            <- opsional, buat multi-map (lihat bagian 8)
    tailed_beast/
        config.json
        tailed_beast_normal/
            region.txt
            fight_button.png
    map_lain/
        (gak perlu config.json kalau cukup pakai yang global)
```

---

## 6. Nge-scope ke Satu Area (Section)

Masalah yang sering kejadian: ada tombol yang keliatannya SAMA PERSIS tapi muncul di beberapa tempat berbeda di layar (misal tombol "Fight" di 3 section level berbeda: Rampage, Hard, Normal). Kalau cuma pakai 1 template buat tombol itu, program bakal nemu/klik yang PERTAMA ketemu (biasanya yang paling atas), bukan yang lo maksud.

Solusinya: taro gambar section + tombolnya dalam **1 subfolder** yang sama, supaya tombolnya cuma dicari DI DALAM area section itu doang. Ada 2 cara:

### A. Pakai gambar anchor (`_noclick`)

Cocok kalau tampilan section-nya gak berubah-ubah.

```
templates/
    battle_icons/
        03_row_anchor_noclick.png      <- ini anchornya
        04_active_icon_click_sat40.png <- cuma dicari DI DALAM box anchor ini
```

File `_noclick` dengan prioritas paling kecil di folder itu otomatis jadi anchor. Kalau anchornya gak ketemu di layar, template lain di folder itu dilewatin (gak dicari sama sekali siklus itu).

### B. Pakai `region.txt` (koordinat tetap)

Cocok kalau POSISI section-nya di layar selalu sama, tapi ISI-nya (angka, teks) suka berubah — misal section yang nampilin Level/Honor/Damage yang berubah seiring progress akun. Gambar anchor bakal "basi" (gak ke-detect lagi) begitu angkanya beda, tapi koordinat tetap gak kepengaruh.

```
templates/
    tailed_beast_normal/
        region.txt                   <- isi: x,y,lebar,tinggi
        fight_button_click.png       <- cuma dicari di dalam kotak koordinat ini
```

Cara dapetin koordinatnya: pakai `find_coords.py` (lihat [bagian 10](#10-tool-bantuan)).

**Penting:** ukuran kotak di `region.txt` HARUS lebih besar dari ukuran gambar template yang dicari di dalamnya. Kalau kekecilan/pas-pasan, nanti kena warning "search area smaller than template image" dan template itu dilewatin.

---

## 7. Beda-beda Ikon/Tombol Tapi Mirip (Saturasi)

Kasus khusus: ikon yang sama persis bentuknya, tapi yang satu berwarna (aktif/enabled) dan yang lain abu-abu/pudar (nonaktif/disabled). Deteksi gambar biasa gak bisa bedain ini karena bentuknya sama — makanya ditambahin pengecekan warna (saturasi).

Pakai tag `_satNN` (atau `"min_saturation"` di config.json). Cara kerjanya:

1. Program nyari SEMUA tempat yang bentuknya cocok (baik yang berwarna maupun abu-abu).
2. Tiap tempat dihitung rata-rata saturasi warnanya (0 = abu-abu total, 255 = sangat berwarna).
3. Yang rata-ratanya **≥ NN** dianggap valid.
4. Kalau ada beberapa yang lolos, yang saturasinya paling tinggi yang diklik.

**Cara nyari angka NN yang pas:** pakai `check_saturation.py` (lihat [bagian 10](#10-tool-bantuan)) buat ngukur saturasi beneran dari ikon aktif vs nonaktif, lalu ambil angka di tengah-tengahnya.

---

## 8. Ganti-ganti Map (`maps/`)

Kalau punya banyak set template buat map/layar yang berbeda-beda, bisa dikelompokin per map pakai folder `maps/`:

```
maps/
    map_hutan/
        01_stage_banner_click.png
        tailed_beast_normal/
            region.txt
            fight_button_click.png
    map_gurun/
        01_stage_banner_click.png
        ...
```

Tiap subfolder di `maps/` adalah 1 "map" yang isinya persis sama strukturnya kayak `templates/` biasa (boleh ada section, config.json, dll di dalamnya masing-masing).

- **F5** = pindah ke map sebelumnya
- **F6** = pindah ke map berikutnya

Pas pindah map, template lama langsung di-reset dan yang baru dimuat otomatis — gak perlu restart program.

> Kalau folder `maps/` gak ada/kosong, program otomatis pakai `templates/` biasa kayak sebelumnya. Jadi kalau cuma 1 map, gak perlu bikin folder `maps/` sama sekali.

---

## 9. Semua Hotkey

| Tombol | Fungsi |
| --- | --- |
| **F5** | Pindah ke map sebelumnya (kalau pakai `maps/`) |
| **F6** | Pindah ke map berikutnya (kalau pakai `maps/`) |
| **F7** | Reload template sekarang juga (gak perlu nunggu auto-reload) |
| **F8** | Pause / lanjut lagi |
| **F9** | Keluar dari program |
| Mouse ke pojok layar | Emergency stop (failsafe bawaan PyAutoGUI) |

Selain itu, folder `templates/` (atau map yang aktif) otomatis di-scan ulang tiap beberapa detik (`RELOAD_INTERVAL`), jadi nambah/hapus/ganti file bisa langsung ketauan tanpa restart.

---

## 10. Tool Bantuan

### `find_coords.py` — cari koordinat pixel

```
python find_coords.py
```

Jalanin, terus gerakin mouse ke titik yang mau dicek — posisi X,Y keprint terus-terusan. Pencet `Ctrl+C` buat berhenti. Dipake buat ngisi `region.txt`: ambil titik pojok kiri-atas dan kanan-bawah area yang mau di-scope, hitung:

```
lebar  = X_kanan_bawah - X_kiri_atas
tinggi = Y_kanan_bawah - Y_kiri_atas
```

### `check_saturation.py` — cari angka saturasi

```
python check_saturation.py ikon_aktif.png ikon_nonaktif.png
```

Atau langsung dari layar:

```
python check_saturation.py --screen X Y LEBAR TINGGI
```

Ngeprint rata-rata saturasi tiap gambar/area, plus saran angka `_satNN` yang pas (di tengah-tengah dua angka yang dites).

---

## 11. Troubleshooting

| Masalah | Penyebab | Solusi |
| --- | --- | --- |
| Selalu klik tombol/ikon yang "pertama" (paling atas/kiri) padahal maksudnya yang lain | Semua kandidat yang bentuknya mirip dianggap sama-sama cocok, dan program ambil yang pertama ketemu pas nge-scan | Pakai [scoping section](#6-nge-scope-ke-satu-area-section) biar dibatasin ke 1 area doang |
| Klik ikon yang keliatannya "disabled"/abu-abu, bukan yang aktif | Deteksi gambar gak peka warna, cuma peka bentuk | Pakai [`_satNN`](#7-beda-beda-ikontombol-tapi-mirip-saturasi) |
| Error `needle dimension(s) exceed the haystack` | `region.txt` lebih kecil dari ukuran gambar template | Lebarin angka di `region.txt`, pastikan lebih besar dari ukuran file gambarnya |
| Template gak ke-detect padahal udah bener posisinya | Game ditampilkan di ukuran/zoom beda dari pas screenshot diambil | Program udah otomatis coba beberapa skala ukuran (`SCALES`); kalau bedanya ekstrim, tambahin skala baru di konstanta `SCALES` dalam `auto_clicker_opencv.py` |
| Section dengan angka yang berubah-ubah (level, honor, dll) jadi gak ke-detect lagi setelah beberapa waktu | Anchor gambar "basi" karena kontennya berubah | Ganti ke [`region.txt`](#6-nge-scope-ke-satu-area-section) (posisi tetap, gak peduli konten berubah) |

---

## 12. Tips Biar Awet

- **Crop template seketat mungkin** — jangan ikut-ikutan ambil elemen tetangga (tombol/ikon lain) dalam satu gambar, nanti malah gagal cocok atau salah target.
- Buat section dengan konten yang suka berubah (angka, stat, progress), **pakai `region.txt`**, bukan gambar anchor.
- Kalau ada ikon kembar yang beda cuma warnanya, **selalu pakai `_satNN`** dan tes dulu angkanya pakai `check_saturation.py` — jangan nebak.
- Kasih margin ekstra di `region.txt`, jangan pas-pasan sama ukuran tombolnya, biar ada ruang toleransi kalau geser dikit.
- Makin banyak isi `SCALES`, makin akurat soal resolusi tapi makin lambat tiap siklus scan — sesuaikan sama kebutuhan.
