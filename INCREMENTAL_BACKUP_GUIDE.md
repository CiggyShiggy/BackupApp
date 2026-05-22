# Panduan Mode Incremental Backup

## Quick Start

### 1. Setup (Pertama Kali)

Edit `client_config.ini`:
```ini
[CLIENT]
ServerUrl = http://192.168.1.100:8765
AuthToken = your_secret_token_here
BackupDirectory = D:\Backup
BackupMode = incremental  # Default, tidak perlu ubah
```

### 2. Jalankan Initial Backup

```bash
python http_backup_client.py
```

Semua file akan dibackup ke: `D:\Backup\NamaSumber\`

### 3. Jalankan Incremental Backup

Tunggu beberapa file berubah, lalu jalankan lagi:

```bash
python http_backup_client.py
```

File yang berubah akan dibackup ke: `D:\Backup\incremental_20260512_143025\`

---

## Deskripsi

Mode **Incremental Backup** membackup file yang berubah ke folder terpisah berdasarkan tanggal dan jam, menghemat storage dan bandwidth hingga 95%+.

## Cara Kerja

### Initial Backup (Pertama Kali)
- Semua file dibackup ke folder utama
- Database SQLite mencatat: path, size, modified time
- Struktur: `D:\Backup\NamaSumber\path\file.ext`

### Incremental Backup (Berikutnya)
- Hanya file yang berubah (modified time berbeda) yang dibackup
- Disimpan ke folder timestamp: `D:\Backup\incremental_YYYYMMDD_HHMMSS\`
- Database diupdate dengan info terbaru

### Contoh Timeline

```
10 Mei 2026 - Initial Backup
D:\Backup\Data\dokumen\laporan.xlsx (v1)

12 Mei 2026, 14:30 - Incremental (laporan.xlsx berubah)
D:\Backup\incremental_20260512_143025\Data\dokumen\laporan.xlsx (v2)

13 Mei 2026, 02:00 - Incremental (data.csv berubah)
D:\Backup\incremental_20260513_020015\Data\project\data.csv (v2)
```

---

## Konfigurasi

Edit `client_config.ini`:

```ini
[CLIENT]
BackupMode = incremental   # Default (direkomendasikan)
# BackupMode = overwrite   # Mode lama (selalu overwrite)
```

---

## Restore File

### Script PowerShell (Mudah)

```powershell
# Restore versi terbaru
.\restore_file.ps1 -FileName "Data\dokumen\laporan.xlsx" -RestoreTo "C:\Restore"

# Lihat history semua versi
.\restore_file.ps1 -FileName "Data\dokumen\laporan.xlsx" -ShowHistory

# Restore dari tanggal tertentu
.\restore_file.ps1 -FileName "Data\dokumen\laporan.xlsx" -RestoreFromDate "20260512"
```

### Manual

1. Cari file di folder incremental terbaru (timestamp paling baru)
2. Jika tidak ada, ambil dari folder utama
3. Copy file ke lokasi restore

---

## Cleanup Folder Lama

```powershell
# Preview (dry run)
.\cleanup_old_backups.ps1 -DaysToKeep 30 -DryRun

# Hapus folder > 30 hari
.\cleanup_old_backups.ps1 -DaysToKeep 30

# Hapus tanpa konfirmasi (untuk automasi)
.\cleanup_old_backups.ps1 -DaysToKeep 30 -Force
```

---

## Check Update

Periksa apakah ada versi baru:

```bash
python http_backup_client.py --check-update
```

Output:
```
╔══════════════════════════════════════════════════════════╗
║  UPDATE TERSEDIA!                                        ║
╠══════════════════════════════════════════════════════════╣
║  Versi saat ini  : v1.0.0                                ║
║  Versi terbaru   : v1.1.0                                ║
╠══════════════════════════════════════════════════════════╣
║  Perubahan:                                              ║
║  • Tambah mode incremental backup (default)              ║
║  • Backup file yang berubah ke folder timestamp          ║
╚══════════════════════════════════════════════════════════╝
```

---

## Keuntungan Mode Incremental

| Aspek | Penghematan |
|-------|-------------|
| Storage | Hingga 95%+ |
| Bandwidth | Hingga 99%+ |
| Waktu Backup | Hingga 99%+ |
| History | ✅ Ada (per tanggal) |
| Recovery | ✅ Multi versi |

**Contoh:** 1000 file (10 GB), hanya 10 file berubah per hari
- Mode Overwrite: 10 GB per backup
- Mode Incremental: 100 MB per backup (setelah initial)
- **Penghematan: 9.9 GB (99%)**

---

## Troubleshooting

### Backup selalu initial meskipun sudah pernah backup
**Penyebab:** File `backup_state.db` terhapus atau corrupt  
**Solusi:** Biarkan aplikasi membuat database baru

### File tidak terdeteksi berubah padahal sudah dimodifikasi
**Penyebab:** Modified date file tidak berubah  
**Solusi:** Gunakan `--force-initial` untuk backup ulang semua file

### Folder incremental terlalu banyak
**Solusi:** Gunakan script cleanup:
```powershell
.\cleanup_old_backups.ps1 -DaysToKeep 30
```

---

## FAQ

**Q: Apakah mode incremental menghapus file lama?**  
A: Tidak. File di folder utama tetap ada. File yang berubah disimpan ke folder incremental baru.

**Q: Bagaimana cara kembali ke mode overwrite?**  
A: Edit `client_config.ini`, ubah `BackupMode = overwrite`

**Q: Apakah bisa backup manual dengan mode incremental?**  
A: Ya, cukup jalankan `python http_backup_client.py` kapan saja

**Q: Berapa lama database menyimpan history?**  
A: Database menyimpan semua history backup. Tidak ada auto-cleanup.

**Q: Apakah mode incremental kompatibel dengan Task Scheduler?**  
A: Ya, 100% kompatibel. Gunakan seperti biasa.

---

## Migrasi dari Mode Overwrite

1. Backup folder `D:\Backup` yang ada (opsional)
2. Edit `client_config.ini`, set `BackupMode = incremental`
3. Jalankan backup seperti biasa
4. Aplikasi akan otomatis detect sebagai initial backup jika database kosong

---

**Mode incremental sekarang menjadi DEFAULT untuk semua instalasi baru.**
