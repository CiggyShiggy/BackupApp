#!/usr/bin/env python3
"""
Auto Backup Application
Aplikasi backup otomatis yang dipanggil oleh Windows Task Scheduler
"""

import os
import sys
import shutil
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Set, List
import configparser
import concurrent.futures
import threading
import asyncio
import aiofiles
import time
import itertools

class ScanningProgress:
    """
    Class untuk menampilkan animasi dan progress scanning
    """
    def __init__(self, logger=None):
        self.logger = logger
        self.is_running = False
        self.thread = None
        self.current_dir = ""
        self.files_scanned = 0
        self.total_size = 0
        self.start_time = None
        
    def start_animation(self, message="Scanning"):
        """Start animasi scanning"""
        self.is_running = True
        self.start_time = time.time()
        self.files_scanned = 0
        self.total_size = 0
        
        def animate():
            spinner = itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])
            while self.is_running:
                elapsed = time.time() - self.start_time
                size_str = self._format_size(self.total_size)
                
                # Progress message dengan animasi
                progress_msg = f"\r{next(spinner)} {message}... "
                progress_msg += f"📁 {self.current_dir} "
                progress_msg += f"📄 {self.files_scanned} files "
                progress_msg += f"💾 {size_str} "
                progress_msg += f"⏱️ {elapsed:.1f}s"
                
                # Truncate jika terlalu panjang
                if len(progress_msg) > 120:
                    dir_part = self.current_dir
                    if len(dir_part) > 40:
                        dir_part = "..." + dir_part[-37:]
                    progress_msg = f"\r{next(spinner)} {message}... "
                    progress_msg += f"📁 {dir_part} "
                    progress_msg += f"📄 {self.files_scanned} files "
                    progress_msg += f"💾 {size_str} "
                    progress_msg += f"⏱️ {elapsed:.1f}s"
                
                print(progress_msg, end='', flush=True)
                time.sleep(0.1)
        
        self.thread = threading.Thread(target=animate, daemon=True)
        self.thread.start()
    
    def update_progress(self, current_dir, files_count, total_size):
        """Update progress information"""
        self.current_dir = os.path.basename(current_dir) if current_dir else ""
        self.files_scanned = files_count
        self.total_size = total_size
    
    def stop_animation(self):
        """Stop animasi dan tampilkan summary"""
        if self.is_running:
            self.is_running = False
            if self.thread:
                self.thread.join(timeout=0.5)
            
            # Clear line dan tampilkan final result
            print('\r' + ' ' * 120, end='\r')
            elapsed = time.time() - self.start_time if self.start_time else 0
            size_str = self._format_size(self.total_size)
            print(f"✅ Scanning completed: {self.files_scanned} files, {size_str} in {elapsed:.1f}s")
            
            if self.logger:
                self.logger.info(f"Scanning completed: {self.files_scanned} files, {size_str} in {elapsed:.1f}s")
    
    def _format_size(self, size_bytes):
        """Format ukuran file"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        size = float(size_bytes)
        
        while size >= 1024.0 and i < len(size_names) - 1:
            size /= 1024.0
            i += 1
        
        return f"{size:.1f} {size_names[i]}"


class ConcurrentProgress:
    """Class untuk menampilkan animasi progress untuk concurrent operations"""
    
    def __init__(self, max_workers: int, logger=None):
        self.max_workers = max_workers
        self.logger = logger
        self.stop_event = threading.Event()
        self.animation_thread = None
        self.active_files = {}  # {thread_id: (filename, progress, start_time)}
        self.completed_count = 0
        self.total_files = 0
        self.total_bytes_processed = 0
        self.start_time = time.time()
        self.spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        self.spinner_index = 0
        self.lock = threading.Lock()
        
    def start_animation(self, total_files: int):
        """Start the concurrent progress animation"""
        self.total_files = total_files
        self.start_time = time.time()
        self.stop_event.clear()
        self.animation_thread = threading.Thread(target=self._animate)
        self.animation_thread.daemon = True
        self.animation_thread.start()
        
    def update_file_progress(self, thread_id: str, filename: str, progress: float, bytes_processed: int):
        """Update progress for a specific file"""
        with self.lock:
            self.active_files[thread_id] = {
                'filename': filename,
                'progress': progress,
                'bytes_processed': bytes_processed,
                'start_time': time.time()
            }
    
    def complete_file(self, thread_id: str, bytes_processed: int):
        """Mark a file as completed"""
        with self.lock:
            if thread_id in self.active_files:
                del self.active_files[thread_id]
            self.completed_count += 1
            self.total_bytes_processed += bytes_processed
            
    def _animate(self):
        """Animation loop for concurrent progress"""
        while not self.stop_event.is_set():
            with self.lock:
                # Clear multiple lines
                print("\033[2K", end="")  # Clear current line
                for i in range(self.max_workers + 3):  # +3 for header lines
                    print("\033[1A\033[2K", end="")
                
                elapsed = time.time() - self.start_time
                spinner = self.spinner_chars[self.spinner_index % len(self.spinner_chars)]
                
                # Header line
                progress_percent = (self.completed_count / self.total_files * 100) if self.total_files > 0 else 0
                print(f"{spinner} 🚀 Concurrent Operations [{self.completed_count}/{self.total_files}] {progress_percent:.1f}% • {self._format_size(self.total_bytes_processed)} • ⏱️ {elapsed:.1f}s")
                print("┌" + "─" * 78 + "┐")
                
                # Show active operations
                active_slots = list(self.active_files.items())[:self.max_workers]
                for i in range(self.max_workers):
                    if i < len(active_slots):
                        thread_id, file_info = active_slots[i]
                        filename = file_info['filename']
                        progress = file_info['progress']
                        bytes_proc = file_info['bytes_processed']
                        
                        # Truncate filename if too long
                        display_name = filename[-40:] if len(filename) > 40 else filename
                        progress_bar = "█" * int(progress * 20) + "░" * (20 - int(progress * 20))
                        
                        print(f"│ 🔄 {display_name:<40} │{progress_bar}│ {self._format_size(bytes_proc):<8} │")
                    else:
                        print(f"│ 💤 {'Waiting for next file...':<40} │{'░' * 20}│ {'idle':<8} │")
                
                print("└" + "─" * 78 + "┘")
                
            self.spinner_index += 1
            time.sleep(0.2)  # Slightly slower for better readability
    
    def stop_animation(self):
        """Stop the animation"""
        if self.animation_thread and self.animation_thread.is_alive():
            self.stop_event.set()
            self.animation_thread.join(timeout=1.0)
        
        # Final status
        elapsed = time.time() - self.start_time
        print(f"\n🎉 Concurrent processing completed!")
        print(f"📊 Results: {self.completed_count}/{self.total_files} files • {self._format_size(self.total_bytes_processed)} • ⏱️ {elapsed:.1f}s")
        
        if self.logger:
            self.logger.info(f"Concurrent processing completed: {self.completed_count}/{self.total_files} files, {self._format_size(self.total_bytes_processed)}, {elapsed:.1f}s")
        
    def _format_size(self, size_bytes: int) -> str:
        """Format file size"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        size = float(size_bytes)
        
        while size >= 1024.0 and i < len(size_names) - 1:
            size /= 1024.0
            i += 1
        
        return f"{size:.1f} {size_names[i]}"


class AutoBackup:
    def __init__(self, config_path: str = "backup.ini"):
        """
        Inisialisasi - mirip seperti constructor di Delphi
        """
        self.config_path = config_path
        self.config = configparser.ConfigParser()
        
        # Properties - mirip dengan private fields di Delphi
        self.source_dirs = []
        self.backup_dir = ""
        self.file_database = {}
        self.log_file = ""
        
        # Load konfigurasi
        self._load_config()
        self._setup_logging()
    
    def _load_config(self):
        """
        Load konfigurasi dari file INI - mirip ReadIniFile di Delphi
        """
        try:
            if not os.path.exists(self.config_path):
                self._create_default_config()
            
            self.config.read(self.config_path, encoding='utf-8')
            
            # Baca pengaturan backup
            self.backup_dir = self.config.get('BACKUP', 'BackupDirectory', fallback='C:\\Backup')
            self.log_file = self.config.get('BACKUP', 'LogFile', fallback='backup.log')
            
            # Baca daftar direktori sumber
            source_list = self.config.get('BACKUP', 'SourceDirectories', fallback='')
            if source_list:
                self.source_dirs = [s.strip() for s in source_list.split(';') if s.strip()]
            
            print(f"Loaded config: {len(self.source_dirs)} source directories")
            
        except Exception as e:
            print(f"Error loading config: {e}")
            sys.exit(1)
    
    def _create_default_config(self):
        """
        Buat file konfigurasi default - mirip dengan CreateDefaultSettings di Delphi
        """
        self.config['BACKUP'] = {
            'BackupDirectory': 'C:\\Backup',
            'SourceDirectories': 'C:\\Documents;C:\\Projects',
            'LogFile': 'backup.log',
            'KeepBackupDays': '30'
        }
        
        self.config['FILTERS'] = {
            'ExcludeExtensions': '.tmp;.bak;.log',
            'ExcludeFolders': 'temp;cache;node_modules'
        }
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self.config.write(f)
        
        print(f"Created default config file: {self.config_path}")
        print("Please edit the configuration file and run again.")
        sys.exit(0)
    
    def _setup_logging(self):
        """
        Setup logging system
        """
        log_path = Path(self.backup_dir) / self.log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_path, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('AutoBackup')
    
    def _format_file_size(self, size_bytes: int) -> str:
        """
        Format ukuran file - mirip FormatFileSize function di Delphi
        """
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        size = float(size_bytes)
        
        while size >= 1024.0 and i < len(size_names) - 1:
            size /= 1024.0
            i += 1
        
        return f"{size:.1f} {size_names[i]}"
    
    async def _copy_and_hash_file_async(self, source_file: Path, dest_file: Path, file_index: int, total_files: int, progress_tracker=None) -> tuple:
        """
        Async copy file dengan hash calculation, animated progress dan per file tracking
        Returns: (success: bool, bytes_processed: int, file_hash: str, error_msg: str)
        """
        thread_id = f"async_{file_index}"
        
        try:
            # Buat direktori jika belum ada
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            
            file_size = source_file.stat().st_size
            bytes_processed = 0
            start_time = time.time()
            
            # Update progress tracker - starting file
            if progress_tracker:
                progress_tracker.update_file_progress(thread_id, source_file.name, 0.0, 0)
            
            # Hash MD5 calculator
            hash_md5 = hashlib.md5()
            
            # Async file copy dengan hash calculation
            async with aiofiles.open(source_file, 'rb') as src:
                async with aiofiles.open(dest_file, 'wb') as dst:
                    chunk_size = 64 * 1024  # 64KB chunks
                    while True:
                        chunk = await src.read(chunk_size)
                        if not chunk:
                            break
                        await dst.write(chunk)
                        hash_md5.update(chunk)
                        bytes_processed += len(chunk)
                        
                        # Update progress
                        if progress_tracker and file_size > 0:
                            progress = bytes_processed / file_size
                            progress_tracker.update_file_progress(thread_id, source_file.name, progress, bytes_processed)
            
            # Copy metadata
            shutil.copystat(source_file, dest_file)
            
            end_time = time.time()
            copy_time = end_time - start_time
            file_hash = hash_md5.hexdigest()
            
            # Complete file progress
            if progress_tracker:
                progress_tracker.complete_file(thread_id, bytes_processed)
            
            # Log per file progress dengan detail
            if copy_time > 0:
                speed = bytes_processed / copy_time
                self.logger.info(f"[{file_index}/{total_files}] {source_file.name}")
                self.logger.info(f"  ✓ {self._format_file_size(bytes_processed)} processed in {copy_time:.2f}s")
                self.logger.info(f"  ⚡ Speed: {self._format_file_size(speed)}/s")
                self.logger.info(f"  🔐 Hash: {file_hash[:16]}...")
            else:
                self.logger.info(f"[{file_index}/{total_files}] {source_file.name}")
                self.logger.info(f"  ✓ {self._format_file_size(bytes_processed)} processed instantly")
                self.logger.info(f"  🔐 Hash: {file_hash[:16]}...")
            
            return True, bytes_processed, file_hash, ""
            
        except Exception as e:
            error_msg = f"Error processing {source_file}: {e}"
            
            # Complete with error
            if progress_tracker:
                progress_tracker.complete_file(thread_id, 0)
            
            self.logger.error(f"[{file_index}/{total_files}] {source_file.name}")
            self.logger.error(f"  ✗ Error: {error_msg}")
            return False, 0, "", error_msg
    
    def _copy_file_with_progress_sync(self, source_file: Path, dest_file: Path, file_index: int, total_files: int) -> tuple:
        """
        Synchronous copy file dengan progress per file (fallback method)
        Returns: (success: bool, bytes_processed: int, file_hash: str, error_msg: str)
        """
        try:
            # Buat direktori jika belum ada
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            
            file_size = source_file.stat().st_size
            bytes_processed = 0
            start_time = time.time()
            
            # Hash MD5 calculator
            hash_md5 = hashlib.md5()
            
            # Synchronous file copy dengan hash calculation
            with open(source_file, 'rb') as src, open(dest_file, 'wb') as dst:
                chunk_size = 64 * 1024  # 64KB chunks
                while True:
                    chunk = src.read(chunk_size)
                    if not chunk:
                        break
                    dst.write(chunk)
                    hash_md5.update(chunk)
                    bytes_processed += len(chunk)
            
            # Copy metadata
            shutil.copystat(source_file, dest_file)
            
            end_time = time.time()
            copy_time = end_time - start_time
            file_hash = hash_md5.hexdigest()
            
            # Log per file progress
            if copy_time > 0:
                speed = bytes_processed / copy_time
                self.logger.info(f"[{file_index}/{total_files}] {source_file.name}")
                self.logger.info(f"  ✓ {self._format_file_size(bytes_processed)} processed in {copy_time:.2f}s")
                self.logger.info(f"  ⚡ Speed: {self._format_file_size(speed)}/s")
                self.logger.info(f"  🔐 Hash: {file_hash[:16]}...")
            else:
                self.logger.info(f"[{file_index}/{total_files}] {source_file.name}")
                self.logger.info(f"  ✓ {self._format_file_size(bytes_processed)} processed instantly")
                self.logger.info(f"  🔐 Hash: {file_hash[:16]}...")
            
            return True, bytes_processed, file_hash, ""
            
        except Exception as e:
            error_msg = f"Error processing {source_file}: {e}"
            self.logger.error(f"[{file_index}/{total_files}] {source_file.name}")
            self.logger.error(f"  ✗ Error: {error_msg}")
            return False, 0, "", error_msg
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """
        Hitung MD5 hash file - mirip dengan function CalculateFileHash di Delphi
        """
        try:
            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                # Baca dalam chunk untuk file besar
                while chunk := f.read(8192):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            self.logger.error(f"Error calculating hash for {file_path}: {e}")
            return ""
    
    def _load_file_database(self) -> Dict:
        """
        Load database file hash - mirip LoadFileDatabase di Delphi
        """
        db_file = Path(self.backup_dir) / "file_database.json"
        
        if db_file.exists():
            try:
                with open(db_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"Error loading file database: {e}")
        
        return {}
    
    def _save_file_database(self, database: Dict):
        """
        Simpan database file hash - mirip SaveFileDatabase di Delphi
        """
        db_file = Path(self.backup_dir) / "file_database.json"
        
        try:
            with open(db_file, 'w', encoding='utf-8') as f:
                json.dump(database, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Error saving file database: {e}")
    
    def _should_exclude_file(self, file_path: str) -> bool:
        """
        Cek apakah file harus dikecualikan - mirip ShouldExcludeFile di Delphi
        """
        # Ekstraksi ekstensi file
        ext = os.path.splitext(file_path)[1].lower()
        
        # Daftar ekstensi yang dikecualikan
        exclude_exts = self.config.get('FILTERS', 'ExcludeExtensions', fallback='').split(';')
        exclude_exts = [e.strip().lower() for e in exclude_exts if e.strip()]
        
        if ext in exclude_exts:
            return True
        
        # Cek folder yang dikecualikan
        exclude_folders = self.config.get('FILTERS', 'ExcludeFolders', fallback='').split(';')
        exclude_folders = [f.strip().lower() for f in exclude_folders if f.strip()]
        
        path_parts = [p.lower() for p in Path(file_path).parts]
        for exclude_folder in exclude_folders:
            if exclude_folder in path_parts:
                return True
        
        return False
    
    def _scan_directory(self, source_dir: str, progress_tracker: ScanningProgress = None) -> Dict[str, Dict]:
        """
        Scan direktori untuk mendapatkan daftar file - mirip ScanDirectory di Delphi
        Dengan progress tracking dan animasi
        """
        files_info = {}
        source_path = Path(source_dir)
        
        if not source_path.exists():
            self.logger.warning(f"Source directory not found: {source_dir}")
            return files_info
        
        file_count = 0
        total_size = 0
        
        try:
            # Update progress tracker
            if progress_tracker:
                progress_tracker.update_progress(source_dir, file_count, total_size)
            
            for file_path in source_path.rglob('*'):
                if file_path.is_file():
                    str_path = str(file_path)
                    
                    # Skip file yang dikecualikan
                    if self._should_exclude_file(str_path):
                        continue
                    
                    # Dapatkan info file
                    stat = file_path.stat()
                    relative_path = str(file_path.relative_to(source_path))
                    file_size = stat.st_size
                    
                    files_info[str_path] = {
                        'relative_path': relative_path,
                        'size': file_size,
                        'mtime': stat.st_mtime,
                        'hash': self._calculate_file_hash(str_path)
                    }
                    
                    file_count += 1
                    total_size += file_size
                    
                    # Update progress setiap 50 files untuk performance
                    if progress_tracker and file_count % 50 == 0:
                        progress_tracker.update_progress(source_dir, file_count, total_size)
                    
        except Exception as e:
            self.logger.error(f"Error scanning {source_dir}: {e}")
        
        # Final update
        if progress_tracker:
            progress_tracker.update_progress(source_dir, file_count, total_size)
        
        self.logger.info(f"  📂 {os.path.basename(source_dir)}: {file_count} files, {self._format_file_size(total_size)}")
        
        return files_info
    
    def _get_changed_files(self, current_files: Dict, old_database: Dict) -> List[str]:
        """
        Dapatkan daftar file yang berubah - mirip GetChangedFiles di Delphi
        """
        changed_files = []
        
        for file_path, file_info in current_files.items():
            # File baru
            if file_path not in old_database:
                changed_files.append(file_path)
                continue
            
            # File berubah (cek hash)
            old_hash = old_database[file_path].get('hash', '')
            new_hash = file_info.get('hash', '')
            
            if old_hash != new_hash:
                changed_files.append(file_path)
        
        return changed_files
    
    async def _copy_files_async(self, files_to_copy: List[str], current_files: Dict, max_workers: int = 4) -> tuple:
        """
        Async copy files dengan concurrent processing, animated progress dan per file tracking
        Returns: (copied_count: int, total_bytes_processed: int, updated_database: Dict)
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_folder = Path(self.backup_dir) / f"auto_backup_{timestamp}"
        
        # Calculate total size of files to copy
        total_size_to_copy = 0
        for file_path in files_to_copy:
            file_info = current_files.get(file_path, {})
            total_size_to_copy += file_info.get('size', 0)
        
        self.logger.info(f"📁 Backup destination: {backup_folder}")
        self.logger.info(f"📊 Total size to backup: {self._format_file_size(total_size_to_copy)}")
        self.logger.info(f"🚀 Using {max_workers} concurrent operations")
        self.logger.info("=" * 70)
        
        # Prepare files untuk async processing
        files_to_process = []
        for file_path in files_to_copy:
            file_info = current_files[file_path]
            relative_path = file_info['relative_path']
            backup_file = backup_folder / relative_path
            files_to_process.append((Path(file_path), backup_file))
        
        # Start concurrent progress animation
        progress_tracker = ConcurrentProgress(max_workers, self.logger)
        progress_tracker.start_animation(len(files_to_process))
        
        try:
            # Semaphore untuk membatasi concurrent operations
            semaphore = asyncio.Semaphore(max_workers)
            
            async def process_with_semaphore(source_file, dest_file, index):
                async with semaphore:
                    return await self._copy_and_hash_file_async(
                        source_file, dest_file, index + 1, len(files_to_process), progress_tracker
                    )
            
            # Execute semua tasks secara concurrent
            tasks = [
                process_with_semaphore(source_file, dest_file, i)
                for i, (source_file, dest_file) in enumerate(files_to_process)
            ]
            
            # Wait for all tasks to complete
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
        finally:
            # Stop animation
            progress_tracker.stop_animation()
        
        # Process results
        copied_count = 0
        total_bytes_processed = 0
        failed_files = []
        updated_database = current_files.copy()
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                source_file, _ = files_to_process[i]
                failed_files.append((str(source_file), str(result)))
                self.logger.error(f"Exception for {source_file.name}: {result}")
            else:
                success, bytes_processed, file_hash, error_msg = result
                if success:
                    copied_count += 1
                    total_bytes_processed += bytes_processed
                    
                    # Update database dengan hash baru
                    source_file, _ = files_to_process[i]
                    file_path = str(source_file)
                    if file_path in updated_database:
                        updated_database[file_path]['hash'] = file_hash
                else:
                    source_file, _ = files_to_process[i]
                    failed_files.append((str(source_file), error_msg))
        
        # Summary
        self.logger.info("=" * 70)
        self.logger.info(f"📈 Copy Summary:")
        self.logger.info(f"  • Files processed: {copied_count}/{len(files_to_process)}")
        self.logger.info(f"  • Total bytes: {self._format_file_size(total_bytes_processed)}")
        self.logger.info(f"  • Concurrent ops: {max_workers}")
        
        if failed_files:
            self.logger.warning(f"  • Failed files: {len(failed_files)}")
            for file_path, error in failed_files[:3]:  # Show max 3 errors
                self.logger.warning(f"    ✗ {Path(file_path).name}: {error}")
            if len(failed_files) > 3:
                self.logger.warning(f"    ... and {len(failed_files) - 3} more failures")
        
        return copied_count, total_bytes_processed, updated_database
    
    def _copy_files_sync(self, files_to_copy: List[str], current_files: Dict, max_workers: int = 4) -> tuple:
        """
        Synchronous copy files dengan threading dan progress per file (fallback method)
        Returns: (copied_count: int, total_bytes_processed: int, updated_database: Dict)
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_folder = Path(self.backup_dir) / f"auto_backup_{timestamp}"
        
        # Calculate total size
        total_size_to_copy = 0
        for file_path in files_to_copy:
            file_info = current_files.get(file_path, {})
            total_size_to_copy += file_info.get('size', 0)
        
        self.logger.info(f"📁 Backup destination: {backup_folder}")
        self.logger.info(f"📊 Total size to backup: {self._format_file_size(total_size_to_copy)}")
        self.logger.info(f"🔄 Using {max_workers} threads (sync mode)")
        self.logger.info("-" * 70)
        
        copied_count = 0
        total_bytes_processed = 0
        failed_files = []
        updated_database = current_files.copy()
        
        # Prepare files untuk threading
        files_to_process = []
        for file_path in files_to_copy:
            file_info = current_files[file_path]
            relative_path = file_info['relative_path']
            backup_file = backup_folder / relative_path
            files_to_process.append((Path(file_path), backup_file))
        
        # Process dengan ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit semua tasks
            future_to_file = {
                executor.submit(
                    self._copy_file_with_progress_sync, 
                    source_file, 
                    dest_file, 
                    i + 1, 
                    len(files_to_process)
                ): (source_file, dest_file) 
                for i, (source_file, dest_file) in enumerate(files_to_process)
            }
            
            # Process hasil
            for future in concurrent.futures.as_completed(future_to_file):
                source_file, dest_file = future_to_file[future]
                try:
                    success, bytes_processed, file_hash, error_msg = future.result()
                    if success:
                        copied_count += 1
                        total_bytes_processed += bytes_processed
                        
                        # Update database
                        file_path = str(source_file)
                        if file_path in updated_database:
                            updated_database[file_path]['hash'] = file_hash
                    else:
                        failed_files.append((str(source_file), error_msg))
                except Exception as e:
                    error_msg = f"Thread exception: {e}"
                    failed_files.append((str(source_file), error_msg))
                    self.logger.error(f"Thread error for {source_file.name}: {error_msg}")
        
        # Summary
        self.logger.info("-" * 70)
        self.logger.info(f"Copy completed: {copied_count}/{len(files_to_process)} files")
        self.logger.info(f"Total bytes processed: {self._format_file_size(total_bytes_processed)}")
        
        if failed_files:
            self.logger.warning(f"Failed files: {len(failed_files)}")
            for file_path, error in failed_files[:3]:
                self.logger.warning(f"  ✗ {Path(file_path).name}: {error}")
            if len(failed_files) > 3:
                self.logger.warning(f"  ... and {len(failed_files) - 3} more failures")
        
        return copied_count, total_bytes_processed, updated_database
    
    def run_backup(self):
        """
        Jalankan proses backup - mirip procedure RunBackup di Delphi
        """
        self.logger.info("=" * 50)
        self.logger.info("AUTO BACKUP STARTED")
        self.logger.info("=" * 50)
        
        # Load database file terakhir
        old_database = self._load_file_database()
        
        # Jika tidak ada database, berarti belum pernah initial backup
        if not old_database:
            self.logger.info("No previous backup database found.")
            self.logger.info("Please run INITIAL BACKUP first using manual_backup.py")
            self.logger.info("Auto backup only handles incremental changes.")
            return
        
        current_files = {}
        
        # Scan semua direktori sumber untuk file saat ini
        print("\n🔍 Starting file system scan...")
        progress_tracker = ScanningProgress(self.logger)
        progress_tracker.start_animation("Scanning directories")
        
        total_scanned_size = 0
        total_scanned_files = 0
        
        for source_dir in self.source_dirs:
            self.logger.info(f"📁 Scanning: {source_dir}")
            dir_files = self._scan_directory(source_dir, progress_tracker)
            current_files.update(dir_files)
            
            # Calculate total size of scanned files
            for file_info in dir_files.values():
                total_scanned_size += file_info.get('size', 0)
                total_scanned_files += 1
                
            # Update global progress
            progress_tracker.update_progress(source_dir, total_scanned_files, total_scanned_size)
        
        # Stop animation dan tampilkan summary
        progress_tracker.stop_animation()
        
        if not current_files:
            self.logger.warning("No files found to scan")
            return
        
        self.logger.info(f"📊 Scan Summary: {len(current_files)} files, Total size: {self._format_file_size(total_scanned_size)}")
        print(f"📊 Scan Summary: {len(current_files)} files, {self._format_file_size(total_scanned_size)}")
        
        # Cari HANYA file yang berubah atau baru
        print("\n🔍 Analyzing changes...")
        changed_files = self._get_changed_files(current_files, old_database)
        
        if not changed_files:
            self.logger.info("✓ No changes detected - backup not needed")
            self.logger.info(f"Scanned {len(current_files)} files, all unchanged")
            return
        
        # Kategorikan perubahan dan hitung ukuran
        new_files = []
        modified_files = []
        new_files_size = 0
        modified_files_size = 0
        
        for file_path in changed_files:
            file_size = current_files[file_path].get('size', 0)
            if file_path not in old_database:
                new_files.append(file_path)
                new_files_size += file_size
            else:
                modified_files.append(file_path)
                modified_files_size += file_size
        
        # Log statistik perubahan dengan informasi bytes
        self.logger.info(f"🔍 CHANGES DETECTED:")
        self.logger.info(f"  • New files: {len(new_files)} ({self._format_file_size(new_files_size)})")
        self.logger.info(f"  • Modified files: {len(modified_files)} ({self._format_file_size(modified_files_size)})")
        self.logger.info(f"  • Total to backup: {len(changed_files)} files ({self._format_file_size(new_files_size + modified_files_size)})")
        self.logger.info(f"  • Unchanged files: {len(current_files) - len(changed_files)} files")
        
        # Determine number of concurrent operations
        max_workers = min(4, max(1, len(changed_files) // 10))  # Auto-scale based on file count
        if len(changed_files) < 5:
            max_workers = 1  # Use single thread for small batches
        
        self.logger.info(f"🚀 Performance mode: {max_workers} concurrent operations")
        
        # Copy files dengan async processing
        try:
            copied_count, total_bytes_processed, updated_database = asyncio.run(
                self._copy_files_async(changed_files, current_files, max_workers)
            )
        except Exception as e:
            self.logger.warning(f"Async processing failed: {e}")
            self.logger.info("Falling back to synchronous processing...")
            copied_count, total_bytes_processed, updated_database = self._copy_files_sync(
                changed_files, current_files, max_workers
            )
        
        # Update database dengan file terbaru (gunakan updated database dari copy operation)
        self._save_file_database(updated_database)
        
        self.logger.info(f"🎉 INCREMENTAL BACKUP COMPLETED")
        self.logger.info(f"📊 Performance Summary:")
        self.logger.info(f"  • Files processed: {copied_count}/{len(changed_files)}")
        self.logger.info(f"  • Total data: {self._format_file_size(total_bytes_processed)}")
        self.logger.info(f"  • Concurrent ops: {max_workers}")
        self.logger.info(f"  • Efficiency: {len(changed_files)} files backed up (vs {len(current_files)} total files)")
        backup_efficiency = (len(changed_files) / len(current_files)) * 100 if len(current_files) > 0 else 0
        self.logger.info(f"  • Space efficiency: {backup_efficiency:.1f}% of total data backed up")
        self.logger.info("=" * 70)


def main():
    """
    Main procedure - mirip begin..end di Pascal
    """
    try:
        print("Auto Backup Application")
        print("=" * 30)
        
        # Buat instance backup
        backup = AutoBackup()
        
        # Jalankan backup
        backup.run_backup()
        
        print("Backup process completed successfully")
        
    except KeyboardInterrupt:
        print("\nBackup cancelled by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()