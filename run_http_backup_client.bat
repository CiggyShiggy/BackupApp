@echo off
REM ============================================================
REM  run_http_backup_client.bat
REM  Jalankan HTTP Backup Client (incremental setiap hari)
REM  Dipanggil oleh Windows Task Scheduler di SERVER BACKUP
REM  Letakkan file ini di folder yang sama dengan http_backup_client.py
REM ============================================================

cd /d "%~dp0"

python http_backup_client.py client_config.ini

REM Catat waktu eksekusi ke log scheduler
echo [%date% %time%] Backup client selesai. Exit code: %ERRORLEVEL% >> backup_scheduler.log
