@echo off
REM ============================================================
REM  run_http_backup_server.bat
REM  Jalankan HTTP Backup Server di sisi SERVER SUMBER
REM  Letakkan file ini di folder yang sama dengan http_backup_server.py
REM ============================================================

cd /d "%~dp0"

echo.
echo  Memulai HTTP Backup Server...
echo  Tekan Ctrl+C untuk menghentikan server.
echo.

python http_backup_server.py server_config.ini

REM Jika server berhenti, tampilkan pesan dan tunggu sebelum tutup
echo.
echo  Server telah berhenti.
pause
