@echo off
REM Batch file untuk menjalankan auto backup via Task Scheduler
REM Ganti path sesuai lokasi file Python Anda

cd /d "C:\BackupApp"
python auto_backup_app.py

REM Optional: Log hasil ke file
echo Backup completed at %date% %time% >> backup_scheduler.log

REM Tunggu 5 detik jika ingin melihat hasil (hilangkan jika tidak perlu)
REM timeout /t 5 /nobreak