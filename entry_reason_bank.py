"""
entry_reason_bank.py

Stok "alasan entry" dan "catatan tambahan" yang dipakai di pesan
signal Telegram, supaya tidak monoton / keulang-ulang tiap sinyal
keluar.

Kenapa bukan list 5000 kalimat statis?
---------------------------------------
5000 baris kalimat yang ditulis manual satu-satu pasti akan banyak
yang mirip / terasa "template" begitu dibaca berkali-kali, dan
susah dirawat (mau nambah/ubah nada bahasa harus edit ratusan baris).

Sebagai gantinya, modul ini pakai pendekatan KOMBINATORIAL:
tiap kalimat disusun dari beberapa "slot" (potongan kalimat) yang
digabung. Dengan slot A x slot B x slot C, jumlah kombinasi unik
naik secara perkalian -> jauh lebih dari 5000 variasi, tapi tetap
enak dibaca karena tiap potongan ditulis dengan hati-hati supaya
nyambung secara bahasa & tetap konsisten dengan logika SMC.

Kategori yang tersedia:
- BULLISH + zona sudah kejemput (market entry)
- BULLISH + zona belum kejemput (pending order)
- BEARISH + zona sudah kejemput (market entry)
- BEARISH + zona belum kejemput (pending order)
- Catatan tambahan per sesi trading (Asia/London/New York/dst)

Cara pakai:
    from entry_reason_bank import get_entry_reason, get_session_extra_note

    reason = get_entry_reason(
        bias="bullish",
        zone_type="Order Block",
        is_pending=False,
        touched=True,
        seed="2026-08-21T10:35-Order Block-bullish",  # opsional, biar konsisten per sinyal
    )
"""

import hashlib
import random
from typing import Optional


# =========================================================
# SLOT: BULLISH — ZONA SUDAH KEJEMPUT (MARKET ENTRY)
# =========================================================

_BULLISH_TOUCHED_A = [
    "Harga sempat masuk ke {zone} sebelum kembali bergerak naik",
    "{zone} sudah diretest oleh harga beberapa candle terakhir",
    "Candle M1 terakhir sempat menyentuh area {zone} lalu memantul naik",
    "Harga baru saja menguji ulang {zone} dan langsung ditolak ke atas",
    "{zone} sudah dilewati harga, menandakan area ini sudah dikonfirmasi",
    "Wick candle terakhir sempat masuk ke {zone} sebelum harga melanjutkan naik",
    "Harga sudah melakukan mitigasi terhadap {zone} pada pergerakan sebelumnya",
    "Retest ke {zone} sudah terjadi dan direspons positif oleh buyer",
    "{zone} bukan lagi target tunggu, karena harga sudah sempat berada di sana",
    "Pergerakan harga menunjukkan {zone} sudah tersentuh sebelum reversal naik",
    "Reaksi cepat terlihat begitu harga menyentuh {zone} pada sesi berjalan",
    "{zone} sudah teruji, harga tidak menembus lebih dalam dari area tersebut",
    "Harga sempat berada tepat di {zone} sebelum menunjukkan momentum naik",
    "Percobaan turun ke {zone} gagal berlanjut dan harga berbalik naik",
    "{zone} sudah aktif tersentuh, sehingga tidak perlu menunggu retest kedua",
]

_BULLISH_TOUCHED_B = [
    "menandakan buyer masih aktif menyerap likuiditas di area tersebut",
    "mengindikasikan minat beli institusional belum hilang dari zona ini",
    "menunjukkan tekanan jual di area itu sudah mulai kehabisan tenaga",
    "memberi sinyal bahwa order beli besar kemungkinan sudah terisi di sana",
    "mengonfirmasi validitas struktur bullish yang terbentuk di timeframe M5",
    "menjadi tanda bahwa zona demand tersebut masih dihormati oleh market",
    "sejalan dengan struktur higher low yang terbentuk di M5",
    "memperkuat bias bullish yang sudah terlihat dari struktur sebelumnya",
    "menunjukkan reaksi harga konsisten dengan karakter order block yang valid",
    "menandakan smart money sudah mengambil posisi di area tersebut",
    "menjadi konfirmasi tambahan bahwa arah naik masih relevan untuk saat ini",
    "menguatkan probabilitas kelanjutan momentum ke arah bullish",
    "sejalan dengan konsep mitigasi order block, di mana zona ini sudah menjalankan fungsinya",
    "menandakan area ini sudah dimitigasi dan mendukung kelanjutan displacement ke atas",
    "menunjukkan tanda-tanda bahwa likuiditas di bawah harga sudah tersapu sebelum harga naik",
    "sesuai dengan konsep discount zone yang biasanya jadi area akumulasi buyer",
]

_BULLISH_TOUCHED_C = [
    "sehingga entry market lebih masuk akal daripada menunggu retest kedua",
    "sehingga momentum bullish berpeluang berlanjut tanpa perlu pending order",
    "sehingga menunggu harga turun lagi ke area yang sama berisiko ketinggalan momentum",
    "sehingga entry langsung di harga sekarang dianggap lebih efisien",
    "sehingga pending order ke zona yang sama sudah kurang relevan",
    "sehingga keputusan market entry lebih sesuai dengan kondisi harga saat ini",
    "sehingga probabilitas kelanjutan naik dianggap cukup untuk entry langsung",
    "sehingga tidak perlu menunggu harga kembali ke level yang sudah dilewati",
    "sehingga eksekusi cepat dianggap lebih menguntungkan daripada menunggu lagi",
    "sehingga peluang entry di harga lebih baik sudah lewat, market entry jadi pilihan realistis",
]


# =========================================================
# SLOT: BULLISH — ZONA BELUM KEJEMPUT (PENDING ORDER)
# =========================================================

_BULLISH_PENDING_A = [
    "{zone} masih berada di bawah harga saat ini dan belum pernah disentuh",
    "Harga belum pernah kembali ke {zone} sejak zona ini terbentuk",
    "{zone} masih murni / fresh, belum ada candle M1 yang menyentuhnya",
    "Area {zone} masih menunggu kunjungan pertama dari harga",
    "Belum ada retest ke {zone} sejauh ini pada data candle terakhir",
    "{zone} masih dalam kondisi belum teruji sejak terbentuk di M5",
    "Harga masih berjarak dari {zone} dan belum pernah mendekatinya",
    "{zone} terlihat masih valid karena belum ada mitigasi sama sekali",
    "Sejak terbentuk, {zone} belum pernah dilewati harga sama sekali",
    "{zone} masih menjadi area yang murni menunggu kunjungan pertama",
    "Struktur M5 menunjukkan {zone} belum tersentuh oleh pergerakan terakhir",
    "{zone} tercatat masih dalam kondisi original, belum ada wick yang masuk ke sana",
]

_BULLISH_PENDING_B = [
    "yang membuka peluang reaksi kuat kalau harga benar-benar turun ke sana",
    "yang secara teori SMC berpeluang memicu reaksi naik saat pertama kali disentuh",
    "yang biasanya memberi respons lebih tajam dibanding zona yang sudah pernah diuji",
    "yang menjadikan area ini kandidat entry dengan potensi reaksi maksimal",
    "yang berarti reaksi harga di sana masih sepenuhnya belum teruji",
    "yang membuat risk:reward berpotensi lebih baik dibanding entry di harga sekarang",
    "yang menjadikan zona ini kandidat kuat untuk reaksi pertama yang tajam",
    "yang membuat potensi pantulan harga di sana masih terjaga penuh",
    "yang menandakan order buyer di area tersebut kemungkinan belum banyak terisi",
    "yang membuat entry di zona ini berpotensi memberi jarak SL lebih efisien",
]

_BULLISH_PENDING_C = [
    "sehingga pending Buy Limit digunakan untuk menunggu harga turun ke area tersebut",
    "sehingga strategi menunggu retest lebih sesuai dibanding entry market sekarang",
    "sehingga order ditempatkan di zona tersebut, bukan mengejar harga saat ini",
    "sehingga entry ditunda sampai harga benar-benar mendekati area optimal",
    "sehingga disiplin menunggu harga ke zona lebih diutamakan daripada entry terburu-buru",
    "sehingga pending order dipasang di zona tersebut sambil menunggu konfirmasi harga",
    "sehingga kesabaran menunggu retest dianggap lebih menguntungkan secara risk:reward",
    "sehingga posisi baru dibuka begitu harga benar-benar mencapai area tersebut",
]


# =========================================================
# SLOT: BEARISH — ZONA SUDAH KEJEMPUT (MARKET ENTRY)
# =========================================================

_BEARISH_TOUCHED_A = [
    "Harga sempat naik ke {zone} sebelum kembali bergerak turun",
    "{zone} sudah diretest oleh harga beberapa candle terakhir",
    "Candle M1 terakhir sempat menyentuh area {zone} lalu berbalik turun",
    "Harga baru saja menguji ulang {zone} dan langsung ditolak ke bawah",
    "{zone} sudah dilewati harga, menandakan area ini sudah dikonfirmasi",
    "Wick candle terakhir sempat masuk ke {zone} sebelum harga melanjutkan turun",
    "Harga sudah melakukan mitigasi terhadap {zone} pada pergerakan sebelumnya",
    "Retest ke {zone} sudah terjadi dan direspons negatif oleh market",
    "{zone} bukan lagi target tunggu, karena harga sudah sempat berada di sana",
    "Pergerakan harga menunjukkan {zone} sudah tersentuh sebelum reversal turun",
    "Reaksi cepat terlihat begitu harga menyentuh {zone} pada sesi berjalan",
    "{zone} sudah teruji, harga tidak menembus lebih tinggi dari area tersebut",
    "Harga sempat berada tepat di {zone} sebelum menunjukkan momentum turun",
    "Percobaan naik ke {zone} gagal berlanjut dan harga berbalik turun",
    "{zone} sudah aktif tersentuh, sehingga tidak perlu menunggu retest kedua",
]

_BEARISH_TOUCHED_B = [
    "menandakan seller masih aktif menyerap likuiditas di area tersebut",
    "mengindikasikan minat jual institusional belum hilang dari zona ini",
    "menunjukkan tekanan beli di area itu sudah mulai kehabisan tenaga",
    "memberi sinyal bahwa order jual besar kemungkinan sudah terisi di sana",
    "mengonfirmasi validitas struktur bearish yang terbentuk di timeframe M5",
    "menjadi tanda bahwa zona supply tersebut masih dihormati oleh market",
    "sejalan dengan struktur lower high yang terbentuk di M5",
    "memperkuat bias bearish yang sudah terlihat dari struktur sebelumnya",
    "menunjukkan reaksi harga konsisten dengan karakter order block yang valid",
    "menandakan smart money sudah mengambil posisi di area tersebut",
    "menjadi konfirmasi tambahan bahwa arah turun masih relevan untuk saat ini",
    "menguatkan probabilitas kelanjutan momentum ke arah bearish",
    "sejalan dengan konsep mitigasi order block, di mana zona ini sudah menjalankan fungsinya",
    "menandakan area ini sudah dimitigasi dan mendukung kelanjutan displacement ke bawah",
    "menunjukkan tanda-tanda bahwa likuiditas di atas harga sudah tersapu sebelum harga turun",
    "sesuai dengan konsep premium zone yang biasanya jadi area distribusi seller",
]

_BEARISH_TOUCHED_C = [
    "sehingga entry market lebih masuk akal daripada menunggu retest kedua",
    "sehingga momentum bearish berpeluang berlanjut tanpa perlu pending order",
    "sehingga menunggu harga naik lagi ke area yang sama berisiko ketinggalan momentum",
    "sehingga entry langsung di harga sekarang dianggap lebih efisien",
    "sehingga pending order ke zona yang sama sudah kurang relevan",
    "sehingga keputusan market entry lebih sesuai dengan kondisi harga saat ini",
    "sehingga probabilitas kelanjutan turun dianggap cukup untuk entry langsung",
    "sehingga tidak perlu menunggu harga kembali ke level yang sudah dilewati",
    "sehingga eksekusi cepat dianggap lebih menguntungkan daripada menunggu lagi",
    "sehingga peluang entry di harga lebih baik sudah lewat, market entry jadi pilihan realistis",
]


# =========================================================
# SLOT: BEARISH — ZONA BELUM KEJEMPUT (PENDING ORDER)
# =========================================================

_BEARISH_PENDING_A = [
    "{zone} masih berada di atas harga saat ini dan belum pernah disentuh",
    "Harga belum pernah kembali ke {zone} sejak zona ini terbentuk",
    "{zone} masih murni / fresh, belum ada candle M1 yang menyentuhnya",
    "Area {zone} masih menunggu kunjungan pertama dari harga",
    "Belum ada retest ke {zone} sejauh ini pada data candle terakhir",
    "{zone} masih dalam kondisi belum teruji sejak terbentuk di M5",
    "Harga masih berjarak dari {zone} dan belum pernah mendekatinya",
    "{zone} terlihat masih valid karena belum ada mitigasi sama sekali",
    "Sejak terbentuk, {zone} belum pernah dilewati harga sama sekali",
    "{zone} masih menjadi area yang murni menunggu kunjungan pertama",
    "Struktur M5 menunjukkan {zone} belum tersentuh oleh pergerakan terakhir",
    "{zone} tercatat masih dalam kondisi original, belum ada wick yang masuk ke sana",
]

_BEARISH_PENDING_B = [
    "yang membuka peluang reaksi kuat kalau harga benar-benar naik ke sana",
    "yang secara teori SMC berpeluang memicu reaksi turun saat pertama kali disentuh",
    "yang biasanya memberi respons lebih tajam dibanding zona yang sudah pernah diuji",
    "yang menjadikan area ini kandidat entry dengan potensi reaksi maksimal",
    "yang berarti reaksi harga di sana masih sepenuhnya belum teruji",
    "yang membuat risk:reward berpotensi lebih baik dibanding entry di harga sekarang",
    "yang menjadikan zona ini kandidat kuat untuk reaksi pertama yang tajam",
    "yang membuat potensi pantulan harga di sana masih terjaga penuh",
    "yang menandakan order seller di area tersebut kemungkinan belum banyak terisi",
    "yang membuat entry di zona ini berpotensi memberi jarak SL lebih efisien",
]

_BEARISH_PENDING_C = [
    "sehingga pending Sell Limit digunakan untuk menunggu harga naik ke area tersebut",
    "sehingga strategi menunggu retest lebih sesuai dibanding entry market sekarang",
    "sehingga order ditempatkan di zona tersebut, bukan mengejar harga saat ini",
    "sehingga entry ditunda sampai harga benar-benar mendekati area optimal",
    "sehingga disiplin menunggu harga ke zona lebih diutamakan daripada entry terburu-buru",
    "sehingga pending order dipasang di zona tersebut sambil menunggu konfirmasi harga",
    "sehingga kesabaran menunggu retest dianggap lebih menguntungkan secara risk:reward",
    "sehingga posisi baru dibuka begitu harga benar-benar mencapai area tersebut",
]


# =========================================================
# SLOT: FVG PARTIAL FILL — KHUSUS FVG, BEDA DARI OB
#
# Ini kategori penting: FVG yang baru terisi SEBAGIAN masih
# berfungsi sebagai magnet -> harga berpotensi balik lagi untuk
# menutup sisa gap sebelum benar-benar melanjutkan trend. Beda
# dengan Order Block yang begitu diretest biasanya dianggap
# selesai. Reason di kategori ini SELALU menyertakan warning ini,
# supaya client entry paham risiko spesifiknya, bukan cuma
# "sudah kejemput jadi market" tanpa konteks.
# =========================================================

_FVG_PARTIAL_BULLISH_A = [
    "Harga baru masuk sebagian ke Fair Value Gap ini, belum menembus seluruh area gap",
    "Sebagian dari Fair Value Gap sudah tersentuh, namun sisi bawahnya belum terisi penuh",
    "Wick candle terakhir baru mencicipi ujung atas gap, belum benar-benar mengisi seluruh ruang kosong",
    "Fair Value Gap ini baru terisi separuh, masih menyisakan ruang kosong di bagian bawah",
    "Harga sempat masuk ke gap tapi close masih bertahan di atas batas bawahnya",
    "Baru sebagian kecil dari imbalance ini yang sudah direspons oleh harga",
    "Gap ini menunjukkan pengisian parsial, candle belum close menembus seluruh rentang harga",
    "Harga menyentuh zona gap namun belum ada candle yang benar-benar menutupnya secara penuh",
    "Sisi atas Fair Value Gap sudah dikunjungi harga, sisi bawah masih kosong dan belum teruji",
    "Baru terjadi retracement kecil ke dalam gap, ruang kosong di bawahnya masih ada",
]

_FVG_PARTIAL_BULLISH_B = [
    "yang berarti sisa ruang kosong di bawah masih berpotensi menarik harga kembali sebelum lanjut naik",
    "yang menandakan gap ini belum sepenuhnya termitigasi dan masih bisa jadi target harga berikutnya",
    "yang membuat kemungkinan pullback singkat ke sisa gap tetap perlu diwaspadai",
    "yang menjadikan zona ini masih setengah aktif, bukan area yang sudah selesai fungsinya",
    "sesuai karakter FVG yang cenderung diisi bertahap, bukan sekali kunjungan langsung penuh",
    "yang berarti likuiditas di sisa gap tersebut masih menjadi daya tarik bagi pergerakan berikutnya",
]

_FVG_PARTIAL_BULLISH_C = [
    "sehingga entry market tetap diambil mengikuti momentum naik, namun disarankan waspada potensi harga balik sebentar ke sisa gap sebelum melanjutkan",
    "sehingga entry tetap dilakukan, tapi pertimbangkan mengamankan sebagian profit lebih awal karena ada risiko retracement susulan",
    "sehingga posisi tetap dibuka mengikuti bias utama, dengan kewaspadaan ekstra terhadap kemungkinan harga sempat turun lagi ke gap",
    "sehingga entry market diambil, namun manajemen risiko perlu lebih ketat karena gap belum sepenuhnya tertutup",
]

_FVG_PARTIAL_BEARISH_A = [
    "Harga baru masuk sebagian ke Fair Value Gap ini, belum menembus seluruh area gap",
    "Sebagian dari Fair Value Gap sudah tersentuh, namun sisi atasnya belum terisi penuh",
    "Wick candle terakhir baru mencicipi ujung bawah gap, belum benar-benar mengisi seluruh ruang kosong",
    "Fair Value Gap ini baru terisi separuh, masih menyisakan ruang kosong di bagian atas",
    "Harga sempat masuk ke gap tapi close masih bertahan di bawah batas atasnya",
    "Baru sebagian kecil dari imbalance ini yang sudah direspons oleh harga",
    "Gap ini menunjukkan pengisian parsial, candle belum close menembus seluruh rentang harga",
    "Harga menyentuh zona gap namun belum ada candle yang benar-benar menutupnya secara penuh",
    "Sisi bawah Fair Value Gap sudah dikunjungi harga, sisi atas masih kosong dan belum teruji",
    "Baru terjadi retracement kecil ke dalam gap, ruang kosong di atasnya masih ada",
]

_FVG_PARTIAL_BEARISH_B = [
    "yang berarti sisa ruang kosong di atas masih berpotensi menarik harga kembali sebelum lanjut turun",
    "yang menandakan gap ini belum sepenuhnya termitigasi dan masih bisa jadi target harga berikutnya",
    "yang membuat kemungkinan pullback singkat ke sisa gap tetap perlu diwaspadai",
    "yang menjadikan zona ini masih setengah aktif, bukan area yang sudah selesai fungsinya",
    "sesuai karakter FVG yang cenderung diisi bertahap, bukan sekali kunjungan langsung penuh",
    "yang berarti likuiditas di sisa gap tersebut masih menjadi daya tarik bagi pergerakan berikutnya",
]

_FVG_PARTIAL_BEARISH_C = [
    "sehingga entry market tetap diambil mengikuti momentum turun, namun disarankan waspada potensi harga balik sebentar ke sisa gap sebelum melanjutkan",
    "sehingga entry tetap dilakukan, tapi pertimbangkan mengamankan sebagian profit lebih awal karena ada risiko retracement susulan",
    "sehingga posisi tetap dibuka mengikuti bias utama, dengan kewaspadaan ekstra terhadap kemungkinan harga sempat naik lagi ke gap",
    "sehingga entry market diambil, namun manajemen risiko perlu lebih ketat karena gap belum sepenuhnya tertutup",
]


# =========================================================
# SLOT: CATATAN TAMBAHAN SESI
# =========================================================

_SESSION_NOTE_A = [
    "Volume transaksi cenderung meningkat pada jam-jam ini",
    "Pergerakan harga biasanya lebih terarah pada sesi ini",
    "Volatilitas cenderung naik seiring bertambahnya partisipan market",
    "Spread biasanya sedikit lebih stabil dibanding sesi sepi",
    "Pergerakan harga bisa lebih cepat dari biasanya pada jam ini",
    "Likuiditas pasar cenderung lebih tebal pada rentang waktu ini",
]

_SESSION_NOTE_B = [
    "sehingga tetap disiplin pada level SL dan TP yang sudah ditentukan",
    "sehingga penting untuk tidak menambah posisi di luar rencana awal",
    "sehingga manajemen risiko tetap harus jadi prioritas utama",
    "sehingga hindari entry tambahan di luar sinyal yang sudah diberikan",
    "sehingga pastikan ukuran lot tetap sesuai dengan toleransi risiko",
    "sehingga jangan tergoda mengejar harga kalau sinyal belum tersentuh",
]


# =========================================================
# GENERATOR
# =========================================================

def _rng_for(seed: Optional[str]) -> random.Random:
    """
    Kalau seed diberikan -> hasil kombinasi konsisten untuk seed
    yang sama (misal: 1 sinyal yang sama tidak berubah teksnya
    kalau dipanggil ulang). Kalau tidak ada seed -> random murni.
    """

    if seed is None:
        return random.Random()

    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def get_entry_reason(
    bias: str,
    zone_type: str,
    is_pending: bool,
    fill_status: str = "untouched",
    seed: Optional[str] = None,
) -> str:
    """
    Hasilkan 1 kalimat alasan entry, dipilih dari kombinasi
    ribuan variasi berdasarkan bias + status zona.

    bias        : "bullish" / "bearish"
    zone_type   : "Order Block" / "Fair Value Gap"
    is_pending  : True kalau order-nya pending, False kalau market
    fill_status : "untouched" / "partial" / "full"
                  "partial" HANYA relevan untuk Fair Value Gap
                  (Order Block tidak punya partial fill secara SMC)
    seed        : opsional, biar hasil konsisten untuk sinyal yang sama
    """

    rng = _rng_for(seed)

    is_fvg_partial = (
        zone_type == "Fair Value Gap" and fill_status == "partial"
    )

    if bias == "bullish":
        if is_fvg_partial:
            a, b, c = (
                rng.choice(_FVG_PARTIAL_BULLISH_A),
                rng.choice(_FVG_PARTIAL_BULLISH_B),
                rng.choice(_FVG_PARTIAL_BULLISH_C),
            )
        elif not is_pending:
            a, b, c = (
                rng.choice(_BULLISH_TOUCHED_A),
                rng.choice(_BULLISH_TOUCHED_B),
                rng.choice(_BULLISH_TOUCHED_C),
            )
        else:
            a, b, c = (
                rng.choice(_BULLISH_PENDING_A),
                rng.choice(_BULLISH_PENDING_B),
                rng.choice(_BULLISH_PENDING_C),
            )
    else:
        if is_fvg_partial:
            a, b, c = (
                rng.choice(_FVG_PARTIAL_BEARISH_A),
                rng.choice(_FVG_PARTIAL_BEARISH_B),
                rng.choice(_FVG_PARTIAL_BEARISH_C),
            )
        elif not is_pending:
            a, b, c = (
                rng.choice(_BEARISH_TOUCHED_A),
                rng.choice(_BEARISH_TOUCHED_B),
                rng.choice(_BEARISH_TOUCHED_C),
            )
        else:
            a, b, c = (
                rng.choice(_BEARISH_PENDING_A),
                rng.choice(_BEARISH_PENDING_B),
                rng.choice(_BEARISH_PENDING_C),
            )

    sentence = f"{a}, {b}, {c}."
    return sentence.format(zone=zone_type)


def get_session_extra_note(
    session_name: str,
    seed: Optional[str] = None,
) -> str:
    """
    Hasilkan 1 kalimat tambahan untuk catatan sesi (opsional,
    ditempel setelah catatan sesi utama dari config.py).
    """

    rng = _rng_for(seed)

    a = rng.choice(_SESSION_NOTE_A)
    b = rng.choice(_SESSION_NOTE_B)

    return f"{a}, {b}"


# =========================================================
# INFO JUMLAH KOMBINASI (untuk verifikasi / debug)
# =========================================================

def total_combinations() -> dict:
    """
    Hitung berapa total kombinasi unik yang tersedia per kategori.
    Berguna untuk verifikasi bahwa stok kata jauh di atas 5000.
    """

    combos = {
        "bullish_touched": len(_BULLISH_TOUCHED_A)
        * len(_BULLISH_TOUCHED_B)
        * len(_BULLISH_TOUCHED_C),
        "bullish_pending": len(_BULLISH_PENDING_A)
        * len(_BULLISH_PENDING_B)
        * len(_BULLISH_PENDING_C),
        "bearish_touched": len(_BEARISH_TOUCHED_A)
        * len(_BEARISH_TOUCHED_B)
        * len(_BEARISH_TOUCHED_C),
        "bearish_pending": len(_BEARISH_PENDING_A)
        * len(_BEARISH_PENDING_B)
        * len(_BEARISH_PENDING_C),
        "fvg_partial_bullish": len(_FVG_PARTIAL_BULLISH_A)
        * len(_FVG_PARTIAL_BULLISH_B)
        * len(_FVG_PARTIAL_BULLISH_C),
        "fvg_partial_bearish": len(_FVG_PARTIAL_BEARISH_A)
        * len(_FVG_PARTIAL_BEARISH_B)
        * len(_FVG_PARTIAL_BEARISH_C),
        "session_note": len(_SESSION_NOTE_A) * len(_SESSION_NOTE_B),
    }

    combos["total_entry_reason"] = (
        combos["bullish_touched"]
        + combos["bullish_pending"]
        + combos["bearish_touched"]
        + combos["bearish_pending"]
        + combos["fvg_partial_bullish"]
        + combos["fvg_partial_bearish"]
    )

    return combos


if __name__ == "__main__":
    import json

    print(json.dumps(total_combinations(), indent=2))
