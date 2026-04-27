@echo off
REM ============================================================
REM  install_http_backup_scheduler.bat
REM  Setup Windows Task Scheduler untuk HTTP Backup Client
REM  Jalankan sebagai ADMINISTRATOR di SERVER BACKUP
REM ============================================================

echo.
echo  ============================================================
echo   Setup HTTP Backup Scheduler
echo   Jalankan file ini sebagai Administrator!
echo  ============================================================
echo.

REM Cek apakah dijalankan sebagai admin
net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  [ERROR] Script ini harus dijalankan sebagai Administrator!
    echo  Klik kanan file .bat ini lalu pilih "Run as administrator"
    echo.
    pause
    exit /b 1
)

REM ---- Konfigurasi ----
REM Ganti path di bawah sesuai lokasi instalasi Anda
set BACKUP_APP_DIR=C:\BackupApp
set BATCH_FILE=%BACKUP_APP_DIR%\run_http_backup_client.bat

echo  Direktori aplikasi: %BACKUP_APP_DIR%
echo  Batch file        : %BATCH_FILE%
echo.

REM Cek apakah batch file ada
if not exist "%BATCH_FILE%" (
    echo  [ERROR] File tidak ditemukan: %BATCH_FILE%
    echo  Pastikan path BACKUP_APP_DIR sudah benar di script ini.
    echo.
    pause
    exit /b 1
)

REM ---- Hapus task lama jika ada ----
echo  Menghapus task lama (jika ada)...
schtasks /delete /tn "HttpBackup_Daily" /f >nul 2>&1

REM ---- Buat task backup harian pukul 02:00 ----
echo  Membuat task backup harian pukul 02:00...
schtasks /create /tn "HttpBackup_Daily" /tr "%BATCH_FILE%" /sc daily /st 02:00 /f /rl highest

if %ERRORLEVEL% equ 0 (
    echo  [OK] Task "HttpBackup_Daily" berhasil dibuat.
) else (
    echo  [ERROR] Gagal membuat task scheduler!
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo   Scheduler berhasil dikonfigurasi!
echo  ============================================================
echo.
echo   Task yang dibuat:
echo     - HttpBackup_Daily: setiap hari pukul 02:00
echo.
echo   Backup pertama kali dijalankan akan otomatis menjadi
echo   INITIAL BACKUP (backup semua file).
echo   Setelah itu setiap hari hanya file baru/berubah yang
echo   akan dibackup (INCREMENTAL).
echo.
echo   Untuk melihat task: buka Task Scheduler
echo   Untuk test manual : jalankan run_http_backup_client.bat
echo   Untuk force initial backup ulang:
echo     python http_backup_client.py client_config.ini --force-initial
echo.
pause
