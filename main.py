"""
Entry point utama.
Jalankan dengan: python main.py
Untuk test kirim 1 signal langsung tanpa nunggu jadwal: python main.py --test
"""

import sys
from scheduler import start, run_signal_job

if __name__ == "__main__":
    if "--test" in sys.argv:
        run_signal_job()
    else:
        start()
