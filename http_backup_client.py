#!/usr/bin/env python3
"""
HTTP Backup Client - Sisi Server Backup
=========================================
Berjalan di server backup (tujuan), mengambil file dari source server
melalui protokol HTTP dan menyimpannya secara lokal.

Fitur:
- Initial backup otomatis: backup SEMUA file pada pertama kali dijalankan
- Incremental backup: hanya backup file baru atau yang modified date-nya lebih baru
- Database SQLite ringan untuk melacak status backup (tanpa install)
- Progress display dengan animasi (cocok dipanggil oleh Task Scheduler)
- Retry otomatis jika download gagal
- Multi-thread download concurrent
- Logging ke file dan console
- Hanya menggunakan Python standard library (tanpa pip install)

Penggunaan:
    python http_backup_client.py [path/ke/client_config.ini] [--force-initial]

    --force-initial  : Paksa initial backup ulang meskipun sudah ada DB

Dipanggil oleh Windows Task Scheduler setiap hari.
"""

import os
import sys
import json
import logging
import configparser
import sqlite3
import threading
import time
import itertools
import concurrent.futures
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, quote

VERSION = "1.1.0"
CHUNK_SIZE = 64 * 1024  # 64KB per chunk saat receive
UPDATE_CHECK_URL = "https://github.com/CiggyShiggy/BackupApp/blob/main/version.json?raw=true"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024.0 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.1f} {units[i]}"


def check_for_updates(current_version: str, update_url: str = UPDATE_CHECK_URL) -> dict:
    """
    Cek apakah ada versi baru tersedia.
    
    Returns:
        dict dengan keys:
        - available: bool (True jika ada update)
        - latest_version: str
        - current_version: str
        - changelog: list
        - download_url: str
        - error: str (jika ada error)
    """
    result = {
        "available": False,
        "latest_version": current_version,
        "current_version": current_version,
        "changelog": [],
        "download_url": "",
        "error": ""
    }
    
    try:
        # Download version info
        req = Request(update_url)
        req.add_header("User-Agent", f"HTTPBackupClient/{current_version}")
        
        with urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        
        latest_version = data.get("version", current_version)
        result["latest_version"] = latest_version
        result["changelog"] = data.get("changelog", [])
        result["download_url"] = data.get("download_url", "")
        
        # Compare versions (simple string comparison)
        # Format: "1.1.0" -> [1, 1, 0]
        def parse_version(v):
            try:
                return [int(x) for x in v.split(".")]
            except:
                return [0, 0, 0]
        
        current_parts = parse_version(current_version)
        latest_parts = parse_version(latest_version)
        
        # Check if latest > current
        if latest_parts > current_parts:
            result["available"] = True
        
    except Exception as e:
        result["error"] = str(e)
    
    return result


def display_update_info(update_info: dict):
    """Tampilkan informasi update dengan format yang bagus."""
    if update_info.get("error"):
        print(f"\n⚠️  Tidak dapat memeriksa update: {update_info['error']}")
        return
    
    if not update_info.get("available"):
        print(f"\n✅ Anda menggunakan versi terbaru: v{update_info['current_version']}")
        return
    
    print("\n" + "╔" + "═" * 58 + "╗")
    print("║" + "  UPDATE TERSEDIA!".center(58) + "║")
    print("╠" + "═" * 58 + "╣")
    print(f"║  Versi saat ini  : v{update_info['current_version']}".ljust(59) + "║")
    print(f"║  Versi terbaru   : v{update_info['latest_version']}".ljust(59) + "║")
    print("╠" + "═" * 58 + "╣")
    
    # Tampilkan changelog untuk versi terbaru
    for changelog in update_info.get("changelog", []):
        if changelog["version"] == update_info["latest_version"]:
            print("║  Perubahan:".ljust(59) + "║")
            for change in changelog.get("changes", [])[:5]:  # Max 5 items
                change_text = f"  • {change}"
                if len(change_text) > 56:
                    change_text = change_text[:53] + "..."
                print(f"║  {change_text}".ljust(59) + "║")
            break
    
    print("╠" + "═" * 58 + "╣")
    if update_info.get("download_url"):
        print(f"║  Download: {update_info['download_url'][:44]}".ljust(59) + "║")
    print("╚" + "═" * 58 + "╝")
    print()


def setup_logging(log_file: str) -> logging.Logger:
    logger = logging.getLogger("BackupClient")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    try:
        # Sisipkan tanggal ke nama file: backup_client.log -> backup_client_2026-05-22.log
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = Path(log_file)
        dated_log_file = str(log_path.with_name(f"{log_path.stem}_{today}{log_path.suffix}"))

        log_dir = os.path.dirname(os.path.abspath(dated_log_file))
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(dated_log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as e:
        print(f"[WARN] Tidak dapat membuat log file: {e}")

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


# ---------------------------------------------------------------------------
# Konfigurasi
# ---------------------------------------------------------------------------

class BackupClientConfig:
    """
    Membaca konfigurasi dari client_config.ini.
    Jika belum ada, dibuat otomatis dengan nilai default.
    """

    def __init__(self, config_path: str = "client_config.ini"):
        self.config_path = config_path
        self.config = configparser.ConfigParser()

        # Default values
        self.server_url = ""
        self.auth_token = ""
        self.backup_dir = "D:\\Backup"
        self.log_file = "backup_client.log"
        self.db_file = "backup_state.db"
        self.max_workers = 4
        self.retry_count = 3
        self.retry_delay = 5      # detik antara retry
        self.conn_timeout = 30    # detik connection timeout
        self.read_timeout = 300   # detik read timeout (untuk file besar)
        self.backup_mode = "incremental"  # Mode backup: "incremental" atau "overwrite"

        self._load_config()

    def _load_config(self):
        if not os.path.exists(self.config_path):
            self._create_default_config()

        self.config.read(self.config_path, encoding="utf-8")

        self.server_url   = self.config.get("CLIENT", "ServerUrl",
                                             fallback="").rstrip("/")
        self.auth_token   = self.config.get("CLIENT", "AuthToken",  fallback="")
        self.backup_dir   = self.config.get("CLIENT", "BackupDirectory",
                                             fallback="D:\\Backup")
        self.log_file     = self.config.get("CLIENT", "LogFile",
                                             fallback="backup_client.log")
        self.db_file      = self.config.get("CLIENT", "DatabaseFile",
                                             fallback="backup_state.db")
        self.max_workers  = self.config.getint("CLIENT", "MaxWorkers",  fallback=4)
        self.retry_count  = self.config.getint("CLIENT", "RetryCount",  fallback=3)
        self.retry_delay  = self.config.getint("CLIENT", "RetryDelay",  fallback=5)
        self.conn_timeout = self.config.getint("CLIENT", "ConnectionTimeout",
                                               fallback=30)
        self.read_timeout = self.config.getint("CLIENT", "ReadTimeout", fallback=300)
        self.backup_mode  = self.config.get("CLIENT", "BackupMode", 
                                            fallback="incremental").lower()

    def _create_default_config(self):
        cfg = configparser.ConfigParser()
        cfg["CLIENT"] = {
            "ServerUrl":          "http://192.168.1.100:8765",
            "AuthToken":          "ganti_token_ini_dengan_string_rahasia_minimal_32_karakter",
            "BackupDirectory":    "D:\\Backup",
            "LogFile":            "backup_client.log",
            "DatabaseFile":       "backup_state.db",
            "BackupMode":         "incremental",
            "MaxWorkers":         "4",
            "RetryCount":         "3",
            "RetryDelay":         "5",
            "ConnectionTimeout":  "30",
            "ReadTimeout":        "300",
        }

        with open(self.config_path, "w", encoding="utf-8") as f:
            cfg.write(f)

        print(f"\n[INFO] File konfigurasi default dibuat: {self.config_path}")
        print("[INFO] Harap edit file konfigurasi tersebut lalu jalankan client kembali.")
        print()
        print("  [CLIENT]")
        print("  ServerUrl  = http://IP_SERVER_SUMBER:8765")
        print("  AuthToken  = (sama dengan yang ada di server_config.ini)")
        print("  BackupDirectory = D:\\Backup")
        print("  BackupMode = incremental  (atau 'overwrite' untuk mode lama)")
        print()
        sys.exit(0)


# ---------------------------------------------------------------------------
# Progress Display
# ---------------------------------------------------------------------------

class ProgressDisplay:
    """
    Menampilkan animasi spinner dan progress saat backup berjalan.
    Thread-safe, berjalan di background thread.
    """

    def __init__(self):
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        self._message = ""
        self._stats = {"done": 0, "total": 0, "bytes": 0, "failed": 0}
        self._start_time = None

    def start(self, message: str = "Bekerja"):
        self._running = True
        self._message = message
        self._start_time = time.time()
        self._stats = {"done": 0, "total": 0, "bytes": 0, "failed": 0}
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def update(self, done: int, total: int, bytes_transferred: int, failed: int = 0):
        with self._lock:
            self._stats = {
                "done": done, "total": total,
                "bytes": bytes_transferred, "failed": failed
            }

    def stop(self, final_message: str = ""):
        self._running = False
        if self._thread:
            self._thread.join(timeout=0.5)
        # Bersihkan baris animasi
        print("\r" + " " * 100, end="\r")
        if final_message:
            print(final_message)

    def _animate(self):
        spinner = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
        while self._running:
            with self._lock:
                stats = dict(self._stats)
                msg   = self._message
                start = self._start_time

            elapsed = time.time() - start if start else 0
            spin    = next(spinner)

            if stats["total"] > 0:
                pct  = stats["done"] / stats["total"] * 100
                info = (
                    f"\r{spin} {msg} "
                    f"[{stats['done']}/{stats['total']}] {pct:.0f}% "
                    f"| {_format_size(stats['bytes'])} "
                    f"| {elapsed:.0f}s"
                )
                if stats["failed"] > 0:
                    info += f" | gagal: {stats['failed']}"
            else:
                info = f"\r{spin} {msg}... {elapsed:.0f}s"

            print(info, end="", flush=True)
            time.sleep(0.12)


# ---------------------------------------------------------------------------
# SQLite Database Manager
# ---------------------------------------------------------------------------

class BackupDatabase:
    """
    Mengelola database SQLite untuk melacak status backup setiap file.
    Menggunakan connection per-thread untuk thread safety.
    """

    def __init__(self, db_path: str, logger: logging.Logger):
        self.db_path = db_path
        self.logger = logger
        self._local = threading.local()
        self._init_database()

    def _get_conn(self) -> sqlite3.Connection:
        """Dapatkan connection SQLite untuk thread saat ini."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, timeout=30)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_database(self):
        """Buat tabel jika belum ada."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS backed_files (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                source        TEXT    NOT NULL,
                relative_path TEXT    NOT NULL,
                file_size     INTEGER DEFAULT 0,
                source_mtime  REAL    DEFAULT 0,
                backup_time   TEXT    NOT NULL,
                backup_path   TEXT,
                UNIQUE(source, relative_path)
            );

            CREATE INDEX IF NOT EXISTS idx_backed_files_source
                ON backed_files(source);

            CREATE TABLE IF NOT EXISTS backup_sessions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_type    TEXT NOT NULL,
                start_time      TEXT NOT NULL,
                end_time        TEXT,
                files_backed    INTEGER DEFAULT 0,
                bytes_transferred INTEGER DEFAULT 0,
                files_failed    INTEGER DEFAULT 0,
                status          TEXT DEFAULT 'running'
            );
        """)
        conn.commit()

    def is_initial_backup_needed(self) -> bool:
        """Kembalikan True jika belum ada record backup (belum pernah initial backup)."""
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) AS cnt FROM backed_files").fetchone()
        return row["cnt"] == 0

    def get_backed_mtime(self, source: str, relative_path: str) -> float:
        """
        Dapatkan mtime terakhir yang dibackup untuk file tertentu.
        Kembalikan 0.0 jika file belum pernah dibackup.
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT source_mtime FROM backed_files WHERE source=? AND relative_path=?",
            (source, relative_path)
        ).fetchone()
        return row["source_mtime"] if row else 0.0

    def upsert_file(self, source: str, relative_path: str,
                    file_size: int, source_mtime: float,
                    backup_path: str):
        """Simpan atau update record backup untuk satu file."""
        conn = self._get_conn()
        now = datetime.now().isoformat()
        conn.execute("""
            INSERT INTO backed_files
                (source, relative_path, file_size, source_mtime, backup_time, backup_path)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, relative_path) DO UPDATE SET
                file_size    = excluded.file_size,
                source_mtime = excluded.source_mtime,
                backup_time  = excluded.backup_time,
                backup_path  = excluded.backup_path
        """, (source, relative_path, file_size, source_mtime, now, backup_path))
        conn.commit()

    def start_session(self, session_type: str) -> int:
        """Catat awal sesi backup, kembalikan session id."""
        conn = self._get_conn()
        cur = conn.execute(
            "INSERT INTO backup_sessions (session_type, start_time, status) VALUES (?, ?, 'running')",
            (session_type, datetime.now().isoformat())
        )
        conn.commit()
        return cur.lastrowid

    def end_session(self, session_id: int, files_backed: int,
                    bytes_transferred: int, files_failed: int,
                    status: str = "completed"):
        """Catat akhir sesi backup."""
        conn = self._get_conn()
        conn.execute("""
            UPDATE backup_sessions SET
                end_time          = ?,
                files_backed      = ?,
                bytes_transferred = ?,
                files_failed      = ?,
                status            = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), files_backed,
              bytes_transferred, files_failed, status, session_id))
        conn.commit()

    def get_last_sessions(self, limit: int = 10) -> list:
        """Dapatkan riwayat sesi backup terakhir."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT session_type, start_time, end_time,
                   files_backed, bytes_transferred, files_failed, status
            FROM backup_sessions
            ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# ---------------------------------------------------------------------------
# HTTP Backup Client
# ---------------------------------------------------------------------------

class BackupClient:
    """
    Backup client utama.
    Menghubungi HTTP Backup Server, membandingkan file list dengan
    database SQLite lokal, dan mendownload hanya file yang perlu dibackup.
    """

    def __init__(self, config: BackupClientConfig, logger: logging.Logger,
                 force_initial: bool = False):
        self.config = config
        self.logger = logger
        self.force_initial = force_initial

        # Pastikan backup directory ada
        os.makedirs(config.backup_dir, exist_ok=True)

        # Inisialisasi database SQLite
        self.db = BackupDatabase(config.db_file, logger)

        # Progress display
        self.progress = ProgressDisplay()

    def _make_request(self, endpoint: str, params: dict = None,
                      stream: bool = False):
        """
        Buat HTTP request ke server dengan autentikasi.
        Kembalikan response object atau raise exception.
        """
        url = f"{self.config.server_url}{endpoint}"
        if params:
            url += "?" + urlencode(params)

        req = Request(url)
        if self.config.auth_token:
            req.add_header("X-Auth-Token", self.config.auth_token)

        timeout = (self.config.conn_timeout, self.config.read_timeout) \
            if not stream else self.config.read_timeout

        # urllib tidak mendukung tuple timeout, gunakan conn_timeout saja
        return urlopen(req, timeout=self.config.conn_timeout)

    def check_server_health(self) -> bool:
        """
        Cek apakah server dapat dijangkau.
        Kembalikan True jika OK, False jika tidak bisa connect.
        """
        try:
            resp = self._make_request("/health")
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "ok":
                self.logger.info(
                    f"Server tersambung: v{data.get('version', '?')}, "
                    f"sources: {data.get('sources', [])}"
                )
                return True
            return False
        except Exception as e:
            self.logger.error(f"Tidak dapat menghubungi server: {e}")
            return False

    def get_remote_files(self) -> list:
        """
        Ambil daftar semua file dari server via GET /api/files.
        Kembalikan list dict file metadata atau raise exception.
        """
        self.logger.info("Meminta daftar file dari server...")
        resp = self._make_request("/api/files")
        data = json.loads(resp.read().decode("utf-8"))

        files = data.get("files", [])
        scan_dur = data.get("scan_duration_seconds", 0)
        self.logger.info(
            f"Server mengembalikan {len(files)} file "
            f"(scan server: {scan_dur}s)"
        )
        return files

    def _get_files_to_backup(self, remote_files: list,
                              is_initial: bool) -> list:
        """
        Filter daftar file server: kembalikan hanya yang perlu dibackup.

        Mode initial  : semua file.
        Mode incremental: file baru (belum ada di DB) atau file yang
                          modified date di server lebih baru dari DB.
        """
        if is_initial:
            self.logger.info(
                f"Mode INITIAL BACKUP: semua {len(remote_files)} file akan dibackup."
            )
            return remote_files

        to_backup = []
        for f in remote_files:
            source   = f["source"]
            rel_path = f["relative_path"]
            mtime    = f["mtime"]

            db_mtime = self.db.get_backed_mtime(source, rel_path)

            if db_mtime == 0.0:
                # File belum pernah dibackup
                to_backup.append(f)
            elif mtime > db_mtime + 1:
                # File lebih baru (toleransi 1 detik untuk perbedaan clock)
                to_backup.append(f)

        new_count  = sum(1 for f in to_backup
                         if self.db.get_backed_mtime(f["source"], f["relative_path"]) == 0.0)
        mod_count  = len(to_backup) - new_count

        self.logger.info(
            f"Mode INCREMENTAL: {len(to_backup)} file perlu dibackup "
            f"(baru: {new_count}, berubah: {mod_count}, "
            f"tidak berubah: {len(remote_files) - len(to_backup)})"
        )
        return to_backup

    def _download_file(self, source: str, rel_path: str,
                       mtime: float, size: int,
                       index: int, total: int,
                       backup_folder: str = None) -> tuple:
        """
        Download satu file dari server, simpan ke backup directory.
        Mempunyai mekanisme retry.

        Args:
            backup_folder: Folder tujuan backup (untuk mode incremental dengan timestamp)

        Returns:
            (success: bool, bytes_downloaded: int, dest_path: str, error: str)
        """
        # Tentukan path tujuan di backup directory
        if backup_folder:
            # Mode incremental: gunakan folder dengan timestamp
            dest = Path(backup_folder) / source / rel_path.replace("/", os.sep)
        else:
            # Mode overwrite: langsung ke backup directory
            dest = Path(self.config.backup_dir) / source / rel_path.replace("/", os.sep)
        
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Path temporary saat download (hindari file tidak lengkap)
        dest_tmp = dest.with_suffix(dest.suffix + ".tmp_backup")

        params    = {"source": source, "path": rel_path}
        url       = f"{self.config.server_url}/api/file?" + urlencode(params)
        headers   = {}
        if self.config.auth_token:
            headers["X-Auth-Token"] = self.config.auth_token

        last_error = ""
        for attempt in range(1, self.config.retry_count + 1):
            try:
                req  = Request(url, headers=headers)
                resp = urlopen(req, timeout=self.config.conn_timeout)

                bytes_recv = 0
                with open(dest_tmp, "wb") as f:
                    while True:
                        chunk = resp.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        bytes_recv += len(chunk)

                # Ganti file lama dengan yang baru
                if dest.exists():
                    dest.unlink()
                dest_tmp.rename(dest)

                # Set modified time sesuai source agar konsisten
                try:
                    os.utime(dest, (mtime, mtime))
                except Exception:
                    pass  # Bukan critical error

                self.logger.info(
                    f"  [{index}/{total}] OK: [{source}] {rel_path} "
                    f"({_format_size(bytes_recv)})"
                )
                return True, bytes_recv, str(dest), ""

            except HTTPError as e:
                last_error = f"HTTP {e.code}: {e.reason}"
                break  # HTTP error tidak perlu di-retry (misal 404)
            except (URLError, OSError) as e:
                last_error = str(e)
                if attempt < self.config.retry_count:
                    self.logger.warning(
                        f"  [{index}/{total}] Retry {attempt}/{self.config.retry_count}: "
                        f"[{source}] {rel_path} - {last_error}"
                    )
                    time.sleep(self.config.retry_delay)
            finally:
                # Hapus file temp jika ada
                if dest_tmp.exists():
                    try:
                        dest_tmp.unlink()
                    except Exception:
                        pass

        self.logger.error(
            f"  [{index}/{total}] GAGAL: [{source}] {rel_path} - {last_error}"
        )
        return False, 0, "", last_error

    def _download_worker(self, task: tuple) -> tuple:
        """Worker function untuk thread pool download."""
        index, total, file_info, backup_folder = task
        source   = file_info["source"]
        rel_path = file_info["relative_path"]
        mtime    = file_info["mtime"]
        size     = file_info["size"]

        try:
            success, bytes_dl, dest_path, error = self._download_file(
                source, rel_path, mtime, size, index, total, backup_folder
            )

            if success:
                # Update database di thread ini (koneksi per-thread)
                self.db.upsert_file(source, rel_path, size, mtime, dest_path)

            return success, bytes_dl, error, source, rel_path

        except Exception as exc:
            error_msg = str(exc)
            self.logger.error(
                f"  [{index}/{total}] ERROR tak terduga: [{source}] {rel_path} - {error_msg}"
            )
            return False, 0, error_msg, source, rel_path

    def run_backup(self):
        """
        Entry point utama untuk menjalankan backup.
        Menentukan mode (initial / incremental) dan mendownload file yang diperlukan.
        
        Mode Incremental:
        - Initial backup: Backup semua file ke folder utama (BACKUP_DIR/source_name/)
        - Incremental backup: Hanya backup file yang berubah ke folder dengan timestamp
          (BACKUP_DIR/incremental_YYYYMMDD_HHMMSS/source_name/)
        
        Mode Overwrite:
        - Selalu backup ke folder utama dan overwrite file yang ada
        """
        self.logger.info("=" * 60)
        self.logger.info(f"HTTP BACKUP CLIENT v{VERSION} DIMULAI")
        self.logger.info(f"Server  : {self.config.server_url}")
        self.logger.info(f"Backup  : {self.config.backup_dir}")
        self.logger.info(f"Mode    : {self.config.backup_mode.upper()}")
        self.logger.info(f"Workers : {self.config.max_workers}")
        self.logger.info("=" * 60)

        total_start = time.time()

        # 1. Cek koneksi ke server
        if not self.check_server_health():
            self.logger.error("Backup dibatalkan: server tidak dapat dijangkau.")
            return False

        # 2. Tentukan mode backup
        is_initial = self.force_initial or self.db.is_initial_backup_needed()
        
        # Untuk mode incremental, tentukan folder tujuan
        backup_folder = None
        if self.config.backup_mode == "incremental":
            if is_initial:
                # Initial backup: langsung ke folder utama
                session_type = "initial"
                backup_folder = None
                self.logger.info("Mode INCREMENTAL - Initial backup ke folder utama")
            else:
                # Incremental backup: ke folder dengan timestamp
                session_type = "incremental"
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_folder = os.path.join(self.config.backup_dir, f"incremental_{timestamp}")
                self.logger.info(f"Mode INCREMENTAL - Backup ke folder: incremental_{timestamp}")
        else:
            # Mode overwrite: selalu ke folder utama
            session_type = "overwrite"
            backup_folder = None
            self.logger.info("Mode OVERWRITE - Backup ke folder utama (overwrite)")

        if is_initial and not self.force_initial:
            self.logger.info("Database backup kosong -> menjalankan INITIAL BACKUP.")
        elif self.force_initial:
            self.logger.info("Flag --force-initial -> menjalankan INITIAL BACKUP ulang.")

        # 3. Ambil daftar file dari server
        try:
            remote_files = self.get_remote_files()
        except Exception as e:
            self.logger.error(f"Gagal mengambil daftar file dari server: {e}")
            return False

        if not remote_files:
            self.logger.info("Tidak ada file yang ditemukan di server. Backup selesai.")
            return True

        # 4. Filter file yang perlu dibackup
        files_to_backup = self._get_files_to_backup(remote_files, is_initial)

        if not files_to_backup:
            self.logger.info(
                f"Tidak ada file baru atau yang berubah. "
                f"Total {len(remote_files)} file sudah up-to-date."
            )
            elapsed = time.time() - total_start
            self.logger.info(
                f"Backup selesai dalam {elapsed:.1f}s - tidak ada yang perlu di-download."
            )
            self.logger.info("=" * 60)
            return True

        # 5. Hitung ukuran total yang akan didownload
        total_size_to_dl = sum(f.get("size", 0) for f in files_to_backup)
        total_files = len(files_to_backup)

        print()
        print(f"  Tipe    : {session_type.upper()}")
        print(f"  File    : {total_files} ({_format_size(total_size_to_dl)})")
        print(f"  Workers : {self.config.max_workers} thread concurrent")
        if backup_folder:
            print(f"  Folder  : {os.path.basename(backup_folder)}")
        print()

        # 6. Catat sesi ke database
        session_id = self.db.start_session(session_type)

        # 7. Download dengan thread pool
        tasks = [
            (i + 1, total_files, f, backup_folder)
            for i, f in enumerate(files_to_backup)
        ]

        done_count     = 0
        failed_count   = 0
        total_bytes_dl = 0
        failed_files   = []

        self.progress.start(f"{session_type.capitalize()} backup")

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.config.max_workers
        ) as executor:
            future_map = {
                executor.submit(self._download_worker, task): task
                for task in tasks
            }

            for future in concurrent.futures.as_completed(future_map):
                try:
                    success, bytes_dl, error, src, rel = future.result()
                    if success:
                        done_count     += 1
                        total_bytes_dl += bytes_dl
                    else:
                        failed_count += 1
                        failed_files.append(f"[{src}] {rel}: {error}")
                except Exception as exc:
                    failed_count += 1
                    task = future_map[future]
                    _, _, file_info, _ = task
                    err_str = f"[{file_info['source']}] {file_info['relative_path']}: {exc}"
                    self.logger.error(f"  ERROR tak terduga saat backup: {err_str}")
                    failed_files.append(err_str)

                # Update progress display
                self.progress.update(
                    done_count + failed_count,
                    total_files,
                    total_bytes_dl,
                    failed_count
                )

        # 8. Stop progress dan tampilkan summary
        elapsed = time.time() - total_start
        speed   = total_bytes_dl / elapsed if elapsed > 0 else 0

        self.progress.stop()

        # 9. Tutup sesi di database
        status = "completed" if failed_count == 0 else "completed_with_errors"
        self.db.end_session(session_id, done_count, total_bytes_dl, failed_count, status)

        # 10. Cetak summary
        print()
        print("╔" + "═" * 58 + "╗")
        print(f"║  BACKUP {session_type.upper()} SELESAI".center(60) + "║")
        print("╠" + "═" * 58 + "╣")
        print(f"║  Berhasil    : {done_count}/{total_files} file".ljust(59) + "║")
        print(f"║  Gagal       : {failed_count} file".ljust(59) + "║")
        print(f"║  Total data  : {_format_size(total_bytes_dl)}".ljust(59) + "║")
        print(f"║  Kecepatan   : {_format_size(int(speed))}/s".ljust(59) + "║")
        print(f"║  Waktu       : {elapsed:.1f} detik".ljust(59) + "║")
        if backup_folder:
            folder_display = os.path.basename(backup_folder)[:50]
            print(f"║  Folder      : {folder_display}".ljust(59) + "║")
        else:
            print(f"║  Tujuan      : {self.config.backup_dir[:50]}".ljust(59) + "║")
        print("╚" + "═" * 58 + "╝")
        print()

        self.logger.info(
            f"BACKUP {session_type.upper()} SELESAI: "
            f"{done_count}/{total_files} berhasil, "
            f"{failed_count} gagal, "
            f"{_format_size(total_bytes_dl)}, "
            f"{elapsed:.1f}s"
        )

        if failed_files:
            self.logger.warning(f"File yang gagal dibackup ({failed_count}):")
            for err in failed_files[:10]:
                self.logger.warning(f"  - {err}")
            if len(failed_files) > 10:
                self.logger.warning(f"  ... dan {len(failed_files) - 10} file lainnya")

        self.logger.info("=" * 60)

        return failed_count == 0

    def show_history(self, limit: int = 10):
        """Tampilkan riwayat sesi backup terakhir."""
        sessions = self.db.get_last_sessions(limit)
        print()
        print("╔" + "═" * 80 + "╗")
        print("║  RIWAYAT BACKUP".center(82) + "║")
        print("╠" + "═" * 80 + "╣")
        print(f"║  {'Tipe':<12} {'Mulai':<20} {'Selesai':<20} "
              f"{'File':<8} {'Size':<12} {'Status':<12} ║")
        print("╠" + "═" * 80 + "╣")

        if not sessions:
            print("║  (Belum ada riwayat backup)".ljust(82) + "║")
        else:
            for s in sessions:
                end_str = s["end_time"][:19] if s["end_time"] else "-"
                start_str = s["start_time"][:19] if s["start_time"] else "-"
                size_str = _format_size(s["bytes_transferred"])
                line = (
                    f"  {s['session_type']:<12} {start_str:<20} {end_str:<20} "
                    f"{s['files_backed']:<8} {size_str:<12} {s['status']:<12}"
                )
                print("║" + line.ljust(81) + "║")

        print("╚" + "═" * 80 + "╝")
        print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Parse argumen sederhana
    args = sys.argv[1:]
    force_initial = "--force-initial" in args
    check_update = "--check-update" in args
    args = [a for a in args if not a.startswith("--")]

    # Tampilkan help
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        print("\nArgumen tambahan:")
        print("  --check-update   : Periksa apakah ada versi baru tersedia")
        print("  --force-initial  : Paksa initial backup ulang")
        print("  --history        : Tampilkan riwayat backup")
        sys.exit(0)

    # Check update
    if check_update:
        print()
        print("╔" + "═" * 58 + "╗")
        print("║" + f"  HTTP BACKUP CLIENT  v{VERSION}".center(58) + "║")
        print("╚" + "═" * 58 + "╝")
        print("\n🔍 Memeriksa update...")
        
        update_info = check_for_updates(VERSION)
        display_update_info(update_info)
        sys.exit(0)

    config_path = args[0] if args else "client_config.ini"

    # Load konfigurasi (auto-create & exit jika belum ada)
    config = BackupClientConfig(config_path)

    # Setup logging
    logger = setup_logging(config.log_file)

    # Validasi
    if not config.server_url or config.server_url.startswith("http://192.168.1.100"):
        if config.server_url.startswith("http://192.168.1.100"):
            logger.warning(
                "ServerUrl masih berupa contoh default (192.168.1.100). "
                "Pastikan sudah diedit ke IP server yang benar."
            )

    if not config.server_url:
        logger.error("ServerUrl belum dikonfigurasi di client_config.ini!")
        sys.exit(1)

    # Tampilkan header
    print()
    print("╔" + "═" * 58 + "╗")
    print("║" + f"  HTTP BACKUP CLIENT  v{VERSION}".center(58) + "║")
    print("╠" + "═" * 58 + "╣")
    print(f"║  Server  : {config.server_url[:48]}".ljust(59) + "║")
    print(f"║  Backup  : {config.backup_dir[:48]}".ljust(59) + "║")
    print(f"║  DB      : {config.db_file[:48]}".ljust(59) + "║")
    if force_initial:
        print("║  Mode    : FORCE INITIAL BACKUP".ljust(59) + "║")
    print("╚" + "═" * 58 + "╝")

    # Cek argumen khusus
    if "--history" in sys.argv:
        client = BackupClient(config, logger)
        client.show_history()
        sys.exit(0)

    # Jalankan backup
    client = BackupClient(config, logger, force_initial=force_initial)

    try:
        success = client.run_backup()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n[INFO] Backup dihentikan oleh pengguna.")
        logger.info("Backup dihentikan oleh pengguna (Ctrl+C).")
        sys.exit(2)
    except Exception as e:
        logger.error(f"Error tidak terduga: {e}", exc_info=True)
        sys.exit(1)
    finally:
        client.db.close()


if __name__ == "__main__":
    main()
