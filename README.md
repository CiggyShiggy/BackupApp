# HTTP Backup System

Sistem backup file otomatis berbasis HTTP yang berjalan di jaringan lokal. File dari **server sumber** diambil oleh **server backup** secara terjadwal menggunakan protokol HTTP dengan autentikasi token.

Mendukung dua mode server sumber: **Python** (standalone) dan **PHP/Apache** (drop-in ke web server yang sudah ada).

---

## Fitur

- **Mode Incremental Backup (BARU!)** — backup awal ke folder utama, backup berikutnya hanya file yang berubah ke folder dengan timestamp
  - 📖 **[Quick Start Guide](QUICK_START_INCREMENTAL.md)** - Mulai dalam 5 menit!
  - 📖 **[Panduan Lengkap](INCREMENTAL_BACKUP_GUIDE.md)** - Dokumentasi detail
- **Initial backup otomatis** — pertama kali dijalankan, semua file didownload
- **Incremental tracking** — hanya file baru atau yang berubah yang didownload
- **Multi-thread download** — concurrent download untuk mempercepat proses
- **SQLite tracking** — melacak status setiap file tanpa database eksternal
- **Retry otomatis** — download diulang otomatis jika gagal
- **Zero dependency** — hanya menggunakan Python standard library (tidak perlu `pip install`)
- **Windows Task Scheduler** — script installer sudah tersedia
- **Keamanan** — autentikasi token, proteksi path traversal, `.htaccess` untuk PHP edition

---

## Arsitektur

```
[Server Sumber]                    [Server Backup]
  File Data ──► HTTP Backup   ────►  http_backup_client.py
                Server                      │
                (Python atau PHP)           ▼
                                     D:\Backup\
                                     backup_state.db  (SQLite)
```

---

## Struktur File

```
backup/
├── http_backup_server.py          # Server sumber — Python Edition
├── http_backup_client.py          # Client backup (incremental)
├── backup_server.php              # Server sumber — PHP/Apache Edition
├── server_config.ini              # Konfigurasi server Python
├── backup_server_config.ini       # Konfigurasi server PHP
├── client_config.ini              # Konfigurasi client backup
├── .htaccess                      # Routing & proteksi file untuk Apache
├── run_http_backup_server.bat     # Jalankan server Python (Windows)
├── run_http_backup_client.bat     # Jalankan client backup (Windows)
└── install_http_backup_scheduler.bat  # Install Windows Task Scheduler
```

---

## Persyaratan

| Komponen | Kebutuhan |
|---|---|
| Python | 3.6+ (standard library only) |
| PHP Edition | PHP 7.2+, Apache dengan `mod_rewrite` aktif |
| OS | Windows / Linux |

---

## Cara Penggunaan

### 1. Setup Server Sumber (Python Edition)

Jalankan sekali untuk membuat konfigurasi default:

```bash
python http_backup_server.py
```

Edit `server_config.ini` yang terbuat:

```ini
[SERVER]
Host = 0.0.0.0
Port = 8765
AuthToken = isi_dengan_token_rahasia_minimal_32_karakter
SourceDirectories = Data=D:\Data;Documents=D:\Documents

[FILTERS]
ExcludeExtensions = .tmp;.bak;.log
ExcludeFolders = temp;cache;node_modules
```

Jalankan server:

```bash
python http_backup_server.py server_config.ini
# atau di Windows:
run_http_backup_server.bat
```

### 2. Setup Server Sumber (PHP/Apache Edition)

1. Copy `backup_server.php`, `backup_server_config.ini`, dan `.htaccess` ke subfolder di web root Apache (contoh: `C:\Apache24\htdocs\backup\`)
2. Edit `backup_server_config.ini` — isi `AuthToken` dan `SourceDirectories`
3. Pastikan `mod_rewrite` aktif di Apache

### 3. Setup Client Backup

Jalankan sekali untuk membuat konfigurasi default:

```bash
python http_backup_client.py
```

Edit `client_config.ini`:

```ini
[CLIENT]
ServerUrl = http://192.168.1.100:8765        # Python Edition
; ServerUrl = http://192.168.1.100/backup    # PHP Edition
AuthToken = isi_dengan_token_yang_sama_dengan_server
BackupDirectory = D:\Backup
BackupMode = incremental                     # incremental (default) atau overwrite
MaxWorkers = 4
```

Jalankan backup:

```bash
python http_backup_client.py client_config.ini
```

### 4. Jadwalkan Backup Otomatis (Windows)

Jalankan sebagai Administrator:

```
install_http_backup_scheduler.bat
```

Ini akan membuat task `HttpBackup_Daily` yang berjalan setiap hari pukul 02:00.

---

## Perintah Berguna

```bash
# Backup manual (auto-detect initial/incremental)
python http_backup_client.py client_config.ini

# Force initial backup ulang (re-download semua file)
python http_backup_client.py client_config.ini --force-initial

# Lihat riwayat sesi backup
python http_backup_client.py client_config.ini --history

# Check update (periksa versi baru)
python http_backup_client.py --check-update

# Cek status task scheduler
schtasks /query /tn "HttpBackup_Daily"

# Test koneksi server (tanpa autentikasi)
curl http://IP_SERVER:8765/health

# Test dengan token
curl -H "X-Auth-Token: TOKEN_ANDA" http://IP_SERVER:8765/api/files
```

### Script PowerShell (Mode Incremental)

```powershell
# Restore file terbaru
.\restore_file.ps1 -FileName "Data\dokumen\laporan.xlsx" -RestoreTo "C:\Restore"

# Lihat history versi file
.\restore_file.ps1 -FileName "Data\dokumen\laporan.xlsx" -ShowHistory

# Cleanup folder incremental lama (preview)
.\cleanup_old_backups.ps1 -DaysToKeep 30 -DryRun

# Cleanup folder incremental lama (hapus)
.\cleanup_old_backups.ps1 -DaysToKeep 30
```

---

## API Endpoints

| Method | Endpoint | Auth | Deskripsi |
|---|---|---|---|
| GET | `/health` | Tidak | Status server |
| GET | `/api/files` | Ya | Daftar semua file + metadata |
| GET | `/api/file?source=X&path=Y` | Ya | Download file |

---

## Cara Kerja Backup

### Mode Incremental (DEFAULT - Direkomendasikan)

**Initial Backup** (pertama kali / `--force-initial`):
- Semua file dari semua source directory didownload ke folder utama
- Setiap file dicatat di SQLite (path, mtime, size)
- Struktur: `D:\Backup\NamaSumber\path\file.ext`

**Incremental Backup** (setiap hari berikutnya):
- Client meminta daftar file + metadata dari server
- File dibandingkan dengan database lokal:
  - Belum ada di DB → download (file baru)
  - `mtime` server lebih baru → download (file berubah)
  - `mtime` sama → skip (sudah up-to-date)
- File yang berubah disimpan ke folder dengan timestamp
- Struktur: `D:\Backup\incremental_YYYYMMDD_HHMMSS\NamaSumber\path\file.ext`

**Keuntungan Mode Incremental:**
- ✅ Hemat storage (hanya simpan file yang berubah)
- ✅ Hemat bandwidth (hanya download file yang berubah)
- ✅ Backup lebih cepat
- ✅ History tracking (mudah lihat file mana yang berubah dan kapan)
- ✅ Recovery fleksibel (bisa restore dari versi tertentu)

**Contoh struktur folder:**

```
D:\Backup\
├── Data\                              # Initial backup
│   ├── laporan\
│   │   └── jan.xlsx
│   └── project\
│       └── data.csv
├── incremental_20260512_143025\       # Backup 12 Mei 2026, 14:30:25
│   └── Data\
│       └── laporan\
│           └── jan.xlsx               # jan.xlsx berubah
├── incremental_20260513_020015\       # Backup 13 Mei 2026, 02:00:15
│   └── Data\
│       └── project\
│           └── data.csv               # data.csv berubah
└── backup_state.db                    # Database tracking
```

### Mode Overwrite (Mode Lama)

Set `BackupMode = overwrite` di `client_config.ini` untuk menggunakan mode lama:
- Semua file selalu dibackup ke folder utama
- File yang sudah ada akan di-overwrite
- Tidak ada folder timestamp

**Struktur folder hasil backup (mode overwrite):**

```
D:\Backup\
├── Data\
│   ├── laporan\
│   │   └── jan.xlsx
│   └── project\
│       └── data.csv
└── Documents\
    └── surat\
        └── memo.docx
```

📖 **Panduan lengkap mode incremental**: Lihat [INCREMENTAL_BACKUP_GUIDE.md](INCREMENTAL_BACKUP_GUIDE.md)

---

## Keamanan

- Gunakan `AuthToken` minimal 32 karakter acak
- Generate token: `python -c "import secrets; print(secrets.token_hex(32))"`
- Gunakan HTTPS untuk jaringan yang tidak trusted
- File `.ini`, `.log`, `.db` dilindungi `.htaccess` dari akses browser
- Untuk keamanan maksimal, pindahkan `backup_server_config.ini` ke luar web root

---

## Troubleshooting

| Masalah | Solusi |
|---|---|
| `404 Not Found` di `/health` | Aktifkan `mod_rewrite`, pastikan `.htaccess` ada |
| `401 Unauthorized` | Pastikan `AuthToken` di client dan server sama persis |
| `403 Forbidden` | Cek izin folder, pastikan Apache bisa membaca source directory |
| Backup lambat | Naikkan `MaxWorkers` di `client_config.ini` |
| Timeout file besar | Naikkan `ReadTimeout` di `client_config.ini` |
| `backup_state.db` korup | Hapus file DB, jalankan ulang (akan jadi initial backup) |

Log tersedia di:
- Server sumber: `backup_server.log`
- Client backup: `backup_client.log`
