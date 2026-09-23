"""
find_coords.py -- Bantu cari koordinat pixel buat isi region.txt.

Cara pakai:
    python find_coords.py

Jalanin, terus arahin mouse ke pojok KIRI-ATAS area section "normal"
(misal pas di ujung kiri-atas box "Fight"-nya normal), catet X,Y yang
muncul. Lanjut arahin ke pojok KANAN-BAWAH area yang sama, catet lagi.

Lebar (width)  = X_kanan_bawah - X_kiri_atas
Tinggi (height) = Y_kanan_bawah - Y_kiri_atas

Baru isi file region.txt dengan format:
    X_kiri_atas,Y_kiri_atas,Lebar,Tinggi

Tekan Ctrl+C buat berhenti.
"""

import time
import pyautogui

print("Gerakin mouse ke titik yang mau dicek posisinya.")
print("Ctrl+C buat berhenti.\n")

try:
    while True:
        x, y = pyautogui.position()
        print(f"X={x:5d}  Y={y:5d}", end="\r")
        time.sleep(0.15)
except KeyboardInterrupt:
    print("\nBerhenti.")