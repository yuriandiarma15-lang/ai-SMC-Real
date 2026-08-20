# XAU AI Signal Bot (SMC + Twelve Data)

Bot Telegram yang mengirim signal trading XAUUSD otomatis setiap jam,
berbasis analisa **Smart Money Concept (SMC)** di candle M5 (12 candle = 1 H1)
dengan timing entry presisi dari candle M1.

## Cara Kerja

1. Setiap H1 close, bot ambil **12+ candle M5 terakhir** dari Twelve Data.
2. Dianalisa pakai SMC: struktur (BOS/CHoCH), Order Block, Fair Value Gap, liquidity sweep.
3. Bot cari **zona OB/FVG terdekat** searah bias. Entry SELALU mengacu ke harga zona ini
   (bukan didekatkan ke harga H1 close) — kalau zona itu jauh dari harga sekarang, bot
   otomatis menyarankan **pending order** (Buy/Sell Limit atau Buy/Sell Stop, tergantung
   posisi zona relatif ke harga sekarang), bukan market order.
4. Kalau pending order **belum kesentuh harga dalam 20 menit** (`PENDING_ORDER_TIMEOUT_MINUTES`
   di `config.py`), bot otomatis kirim notifikasi **signal dibatalkan/skip** ke Telegram —
   user tidak perlu entry lagi dan tinggal tunggu signal H1 berikutnya.
5. Signal dikirim ke Telegram: arah, jenis order, entry, SL 50 pip, TP1 70 pip, TP2 150 pip,
   probabilitas, catatan sesi trading (Asia/London/New York), dan alasan.
6. Terjadwal otomatis **setiap jam :00 WIB**, 07:00 – 02:00 dini hari, **Senin – Jumat**
   (Sabtu siang & Minggu libur karena pasar tutup).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# lalu isi .env:
#   TELEGRAM_BOT_TOKEN  -> dari @BotFather
#   TELEGRAM_CHAT_ID    -> chat ID pribadi kamu (bot kirim signal langsung ke DM kamu,
#                           bukan ke grup/channel). Cara dapatkan chat ID: chat bot kamu
#                           dulu di Telegram (kirim pesan apa saja / /start), lalu buka
#                           https://api.telegram.org/bot<TOKEN>/getUpdates di browser,
#                           cari nilai "chat":{"id": ...} di hasilnya
#   TWELVEDATA_API_KEY  -> dari akun Twelve Data kamu
```

Test kirim 1 signal langsung (tanpa nunggu jadwal jam):

```bash
python main.py --test
```

Jalankan bot dengan scheduler aktif (produksi):

```bash
python main.py
```

## Deploy ke Railway

Repo ini sudah termasuk `Procfile` (`worker: python main.py`), tinggal:
1. Push ke GitHub.
2. Connect repo di Railway → pilih **Worker**, bukan Web Service (bot ini tidak buka port HTTP).
3. Isi environment variables di Railway (sama seperti isi `.env`).
4. Deploy — bot akan jalan terus dan kirim signal sesuai jadwal.

## Asumsi Penting yang Perlu Kamu Cek

- **1 pip XAUUSD = 0.1** di harga (konvensi HFM/Exness/VALETAX/FXGT).
  Kalau broker langgananmu beda konvensi, ubah `PIP_VALUE` di `config.py` —
  semua perhitungan SL/TP otomatis menyesuaikan.
- **Jadwal mengikuti jam buka pasar XAUUSD**: aktif Senin 07:00 s/d Sabtu
  02:00 dini hari WIB (sesi Jumat malam nyambung ke Sabtu dini hari), lalu
  **libur total Sabtu siang–Minggu** karena pasar tutup. Kalau ada penyesuaian,
  tinggal ubah `DOW_MAIN` / `DOW_EXTENDED` di `config.py`.
- Skor probabilitas (35–95%) dihitung dari jumlah **confluence** SMC yang
  terpenuhi (BOS/CHoCH + Order Block + FVG + liquidity sweep) — ini heuristik,
  bukan backtest statistik. Kalau mau probabilitas berbasis winrate historis,
  perlu tambahan modul backtesting terpisah (bisa saya buatkan kalau perlu).

## Struktur File

| File | Fungsi |
|---|---|
| `config.py` | Semua parameter (API key, pip, SL/TP, jadwal) |
| `twelvedata_client.py` | Ambil data candle dari Twelve Data |
| `smc_analyzer.py` | Logic SMC: struktur, order block, FVG, liquidity |
| `signal_generator.py` | Gabung SMC + M1 entry + SL/TP → jadi teks signal |
| `pending_order_monitor.py` | Cek status pending order 20 menit kemudian, auto-skip kalau belum kesentuh |
| `telegram_sender.py` | Kirim pesan ke Telegram |
| `scheduler.py` | Jadwal jam kirim signal |
| `main.py` | Entry point |
