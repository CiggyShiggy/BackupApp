#!/usr/bin/env python3
"""
Manual Backup Application
Aplikasi backup manual dengan interface command line yang user-friendly
"""

import os
import sys
import shutil
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List
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
    def __init__(self):
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
    
    def __init__(self, max_workers: int):
        self.max_workers = max_workers
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


class ManualBackup:
    def __init__(self, config_path: str = "backup.ini"):
        """
        Constructor - mirip dengan Create di Delphi
        """
        self.config_path = config_path
        self.config = configparser.ConfigParser()
        
        # Properties
        self.source_dirs = []
        self.backup_dir = ""
        
        # Load konfigurasi jika ada
        self._load_config_if_exists()
    
    def _load_config_if_exists(self):
        """
        Load konfigurasi jika file ada
        """
        if os.path.exists(self.config_path):
            try:
                self.config.read(self.config_path, encoding='utf-8')
                self.backup_dir = self.config.get('BACKUP', 'BackupDirectory', fallback='')
                source_list = self.config.get('BACKUP', 'SourceDirectories', fallback='')
                if source_list:
                    self.source_dirs = [s.strip() for s in source_list.split(';') if s.strip()]
            except Exception as e:
                print(f"Warning: Error reading config file: {e}")
    
    def _clear_screen(self):
        """
        Clear screen - mirip ClrScr di Pascal
        """
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def _wait_for_key(self):
        """
        Wait for key press - mirip ReadKey di Pascal
        """
        input("\nPress Enter to continue...")
    
    def _show_header(self):
        """
        Tampilkan header aplikasi - mirip WriteHeader procedure di Pascal
        """
        print("╔" + "═" * 48 + "╗")
        print("║" + " MANUAL BACKUP APPLICATION ".center(48) + "║")
        print("║" + f" Version 1.0 - {datetime.now().strftime('%Y-%m-%d')} ".center(48) + "║")
        print("╚" + "═" * 48 + "╝")
        print()
    
    def _show_main_menu(self):
        """
        Tampilkan menu utama - mirip ShowMainMenu procedure di Pascal
        """
        print("┌─ MAIN MENU ─────────────────────────────────┐")
        print("│ 1. Initial Backup (First Time - Full)      │")
        print("│ 2. Quick Backup (Full - All Files)         │")
        print("│ 3. Smart Backup (Incremental - Changes)    │")
        print("│ 4. Custom Backup (Choose Folders)          │")
        print("│ 5. View Backup History                     │")
        print("│ 6. Cleanup Old Backups                    │")
        print("│ 7. Settings                                │")
        print("│ 0. Exit                                    │")
        print("└─────────────────────────────────────────────┘")
    
    def _input_directory(self, prompt: str) -> str:
        """
        Input direktori dengan validasi - mirip InputDirectory function di Delphi
        """
        while True:
            dir_path = input(f"{prompt}: ").strip()
            
            if not dir_path:
                print("Directory path cannot be empty!")
                continue
            
            if os.path.exists(dir_path) and os.path.isdir(dir_path):
                return dir_path
            else:
                print(f"Directory '{dir_path}' does not exist!")
                retry = input("Try again? (y/n): ").lower()
                if retry != 'y':
                    return ""
    
    def _calculate_folder_size(self, folder_path: str, show_progress: bool = False) -> tuple:
        """
        Hitung ukuran folder - mirip CalculateFolderSize function di Delphi
        Returns: (total_size, file_count)
        """
        total_size = 0
        file_count = 0
        
        # Setup progress animation jika diminta
        progress_tracker = None
        if show_progress:
            progress_tracker = ScanningProgress()
            progress_tracker.start_animation("Calculating folder size")
        
        try:
            for dirpath, dirnames, filenames in os.walk(folder_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    try:
                        file_size = os.path.getsize(filepath)
                        total_size += file_size
                        file_count += 1
                        
                        # Update progress setiap 100 files untuk performance
                        if progress_tracker and file_count % 100 == 0:
                            progress_tracker.update_progress(dirpath, file_count, total_size)
                            
                    except (OSError, FileNotFoundError):
                        continue
        except Exception:
            pass
        finally:
            if progress_tracker:
                progress_tracker.update_progress(folder_path, file_count, total_size)
                progress_tracker.stop_animation()
        
        return total_size, file_count
    
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
    
    def _copy_file_with_progress(self, source_file: Path, dest_file: Path, file_index: int, total_files: int) -> tuple:
        """
        Copy single file dengan progress per file - dengan multithreading support
        Returns: (success: bool, bytes_copied: int, error_msg: str)
        """
        try:
            # Buat direktori jika belum ada
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Dapatkan ukuran file
            file_size = source_file.stat().st_size
            
            # Copy file dengan progress tracking
            bytes_copied = 0
            start_time = time.time()
            
            with open(source_file, 'rb') as src, open(dest_file, 'wb') as dst:
                # Copy dalam chunk untuk file besar
                chunk_size = 64 * 1024  # 64KB chunks
                while True:
                    chunk = src.read(chunk_size)
                    if not chunk:
                        break
                    dst.write(chunk)
                    bytes_copied += len(chunk)
            
            # Copy metadata
            shutil.copystat(source_file, dest_file)
            
            end_time = time.time()
            copy_time = end_time - start_time
            
            # Log individual file progress
            if copy_time > 0:
                speed = bytes_copied / copy_time  # bytes per second
                print(f"[{file_index}/{total_files}] {source_file.name}")
                print(f"  ✓ {self._format_file_size(bytes_copied)} copied in {copy_time:.2f}s")
                print(f"  ⚡ Speed: {self._format_file_size(speed)}/s")
            else:
                print(f"[{file_index}/{total_files}] {source_file.name}")
                print(f"  ✓ {self._format_file_size(bytes_copied)} copied instantly")
            
            return True, bytes_copied, ""
            
        except Exception as e:
            error_msg = f"Error copying {source_file}: {e}"
            print(f"[{file_index}/{total_files}] {source_file.name}")
            print(f"  ✗ Error: {error_msg}")
            return False, 0, error_msg
    
    def _copy_folder_with_threading(self, source: str, destination: str, max_workers: int = 4) -> int:
        """
        Copy folder dengan multithreading dan progress per file
        """
        copied_count = 0
        total_bytes_processed = 0
        failed_files = []
        
        # Hitung total file untuk progress
        total_size, total_files = self._calculate_folder_size(source)
        
        print(f"\nCopying from: {source}")
        print(f"To: {destination}")
        print(f"Total files: {total_files}, Size: {self._format_file_size(total_size)}")
        print(f"Using {max_workers} threads for parallel processing")
        print("-" * 70)
        
        source_path = Path(source)
        dest_path = Path(destination)
        
        # Kumpulkan semua file yang akan di-copy
        files_to_copy = []
        for file_path in source_path.rglob('*'):
            if file_path.is_file():
                relative_path = file_path.relative_to(source_path)
                dest_file = dest_path / relative_path
                files_to_copy.append((file_path, dest_file))
        
        # Process dengan ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit semua tasks
            future_to_file = {
                executor.submit(
                    self._copy_file_with_progress, 
                    source_file, 
                    dest_file, 
                    i + 1, 
                    len(files_to_copy)
                ): (source_file, dest_file) 
                for i, (source_file, dest_file) in enumerate(files_to_copy)
            }
            
            # Process hasil
            for future in concurrent.futures.as_completed(future_to_file):
                source_file, dest_file = future_to_file[future]
                try:
                    success, bytes_copied, error_msg = future.result()
                    if success:
                        copied_count += 1
                        total_bytes_processed += bytes_copied
                    else:
                        failed_files.append((str(source_file), error_msg))
                except Exception as e:
                    error_msg = f"Thread exception: {e}"
                    failed_files.append((str(source_file), error_msg))
                    print(f"  ✗ Thread error for {source_file.name}: {error_msg}")
        
        # Summary
        print("-" * 70)
        print(f"Copy completed: {copied_count}/{len(files_to_copy)} files")
        print(f"Total bytes processed: {self._format_file_size(total_bytes_processed)}")
        
        if failed_files:
            print(f"Failed files: {len(failed_files)}")
            for file_path, error in failed_files[:5]:  # Show max 5 errors
                print(f"  ✗ {Path(file_path).name}: {error}")
            if len(failed_files) > 5:
                print(f"  ... and {len(failed_files) - 5} more failures")
        
        return copied_count
    
    async def _copy_and_hash_file_async(self, source_file: Path, dest_file: Path, source_dir: str, file_index: int, total_files: int, progress_tracker=None) -> tuple:
        """
        Async copy file dan hitung hash sekaligus untuk initial backup
        Returns: (success: bool, file_info: dict, bytes_processed: int, error_msg: str)
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
            
            # Relative path untuk database
            source_path = Path(source_dir)
            relative_path = source_file.relative_to(source_path)
            
            # File info untuk database
            file_info = {
                'relative_path': str(relative_path),
                'hash': file_hash,
                'source_dir': source_dir
            }
            
            # Complete file progress
            if progress_tracker:
                progress_tracker.complete_file(thread_id, bytes_processed)
            
            # Log sederhana untuk backup compatibility
            if copy_time > 0:
                speed = bytes_processed / copy_time
                print(f"[{file_index}/{total_files}] {source_file.name}")
                print(f"  ✓ {self._format_file_size(bytes_processed)} processed in {copy_time:.2f}s")
                print(f"  ⚡ Speed: {self._format_file_size(speed)}/s")
                print(f"  🔐 Hash: {file_hash[:16]}...")
            else:
                print(f"[{file_index}/{total_files}] {source_file.name}")
                print(f"  ✓ {self._format_file_size(bytes_processed)} processed instantly")
                print(f"  🔐 Hash: {file_hash[:16]}...")
            
            return True, file_info, bytes_processed, ""
            
        except Exception as e:
            error_msg = f"Error processing {source_file}: {e}"
            
            # Complete with error
            if progress_tracker:
                progress_tracker.complete_file(thread_id, 0)
            
            print(f"[{file_index}/{total_files}] {source_file.name}")
            print(f"  ✗ Error: {error_msg}")
            return False, {}, 0, error_msg
    
    async def _initial_backup_async_processing(self, source_dir: str, backup_folder: Path, max_workers: int = 4) -> tuple:
        """
        Async processing untuk initial backup dengan concurrent file operations dan animated progress
        Returns: (copied_count: int, total_bytes: int, current_files: dict)
        """
        print(f"\nProcessing: {source_dir} (Async mode with {max_workers} concurrent operations)")
        
        source_path = Path(source_dir)
        folder_name = source_path.name
        dest_folder = backup_folder / folder_name
        
        # Kumpulkan semua file yang akan diproses
        files_to_process = []
        for file_path in source_path.rglob('*'):
            if file_path.is_file():
                relative_path = file_path.relative_to(source_path)
                dest_file = dest_folder / relative_path
                files_to_process.append((file_path, dest_file))
        
        print(f"Found {len(files_to_process)} files to process")
        
        # Start concurrent progress animation
        progress_tracker = ConcurrentProgress(max_workers)
        progress_tracker.start_animation(len(files_to_process))
        
        try:
            # Semaphore untuk membatasi concurrent operations
            semaphore = asyncio.Semaphore(max_workers)
            
            async def process_with_semaphore(source_file, dest_file, index):
                async with semaphore:
                    return await self._copy_and_hash_file_async(
                        source_file, dest_file, source_dir, index + 1, len(files_to_process), progress_tracker
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
        current_files = {}
        failed_files = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                source_file, _ = files_to_process[i]
                failed_files.append((str(source_file), str(result)))
            else:
                success, file_info, bytes_processed, error_msg = result
                if success:
                    copied_count += 1
                    total_bytes_processed += bytes_processed
                    source_file, _ = files_to_process[i]
                    current_files[str(source_file)] = file_info
                else:
                    source_file, _ = files_to_process[i]
                    failed_files.append((str(source_file), error_msg))
        
        # Summary untuk direktori ini
        print("-" * 70)
        print(f"Directory completed: {copied_count}/{len(files_to_process)} files")
        print(f"Bytes processed: {self._format_file_size(total_bytes_processed)}")
        
        if failed_files:
            print(f"Failed files: {len(failed_files)}")
            for file_path, error in failed_files[:3]:  # Show max 3 errors
                print(f"  ✗ {Path(file_path).name}: {error}")
            if len(failed_files) > 3:
                print(f"  ... and {len(failed_files) - 3} more failures")
        
        return copied_count, total_bytes_processed, current_files
    
    def _copy_folder_with_progress(self, source: str, destination: str) -> int:
        """
        Copy folder dengan progress - wrapper untuk threading version
        """
        return self._copy_folder_with_threading(source, destination, max_workers=4)
    
    def initial_backup(self):
        """
        Initial backup - first time full backup - mirip procedure InitialBackup
        """
        self._clear_screen()
        self._show_header()
        print("┌─ INITIAL BACKUP (FIRST TIME) ───────────────┐")
        print("│ Complete backup for first-time setup       │")
        print("│ This creates a baseline for Smart Backups  │")
        print("└─────────────────────────────────────────────┘")
        print()
        
        # Cek apakah ada konfigurasi
        if not self.source_dirs:
            print("No source directories configured!")
            print("Please configure source directories first in Settings.")
            self._wait_for_key()
            return
        
        if not self.backup_dir:
            print("No backup directory configured!")
            print("Please configure backup directory first in Settings.")
            self._wait_for_key()
            return
        
        # Cek apakah sudah ada backup sebelumnya
        db_file = Path(self.backup_dir) / "file_database.json"
        if db_file.exists():
            print("⚠️  Previous backup database found!")
            print("   It looks like you already did an initial backup.")
            print("   Use 'Smart Backup' for incremental backups.")
            print("   Use 'Quick Backup' if you want a new full backup.")
            print()
            overwrite = input("Continue with initial backup anyway? (y/n): ").lower()
            if overwrite != 'y':
                return
        
        # Tampilkan ringkasan dengan progress animation
        print("\n🔍 Calculating backup size...")
        print("Source directories:")
        total_size = 0
        total_files = 0
        
        for i, source_dir in enumerate(self.source_dirs, 1):
            print(f"\n📁 Analyzing directory {i}/{len(self.source_dirs)}: {source_dir}")
            size, count = self._calculate_folder_size(source_dir, show_progress=True)
            total_size += size
            total_files += count
            print(f"  ✅ {source_dir}")
            print(f"     📄 Files: {count}, 💾 Size: {self._format_file_size(size)}")
        
        print(f"\n📊 BACKUP SUMMARY:")
        print(f"  🎯 Backup destination: {self.backup_dir}")
        print(f"  📄 Total files to backup: {total_files}")
        print(f"  💾 Total size: {self._format_file_size(total_size)}")
        print(f"  📁 Source directories: {len(self.source_dirs)}")
        
        # Konfirmasi
        confirm = input("\n❓ Proceed with INITIAL backup? (y/n): ").lower()
        if confirm != 'y':
            return
        
        # Mulai backup
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_folder = Path(self.backup_dir) / f"initial_backup_{timestamp}"
        
        print(f"\nCreating initial backup with async processing...")
        print(f"Backup location: {backup_folder}")
        print(f"Performance mode: Concurrent file operations enabled")
        print("=" * 70)
        
        total_copied = 0
        total_bytes_processed = 0
        all_current_files = {}
        
        # Ask user for concurrent operations preference
        try:
            max_workers = input("\nNumber of concurrent operations (1-8, default=4): ").strip()
            if not max_workers:
                max_workers = 4
            else:
                max_workers = max(1, min(8, int(max_workers)))
        except ValueError:
            max_workers = 4
        
        print(f"Using {max_workers} concurrent operations")
        
        # Process each directory with async
        async def process_all_directories():
            tasks = []
            for source_dir in self.source_dirs:
                task = self._initial_backup_async_processing(source_dir, backup_folder, max_workers)
                tasks.append(task)
            
            # Process directories sequentially to avoid overwhelming the system
            for i, task in enumerate(tasks):
                print(f"\n📁 Processing directory {i+1}/{len(self.source_dirs)}")
                copied_count, bytes_processed, current_files = await task
                nonlocal total_copied, total_bytes_processed
                total_copied += copied_count
                total_bytes_processed += bytes_processed
                all_current_files.update(current_files)
        
        # Run async processing
        try:
            asyncio.run(process_all_directories())
        except Exception as e:
            print(f"Error during async processing: {e}")
            print("Falling back to sequential processing...")
            # Fallback to original method if async fails
            return self._initial_backup_fallback(backup_folder, total_files, total_size)
        
        # Simpan database untuk smart backup selanjutnya
        db_file = Path(self.backup_dir) / "file_database.json"
        try:
            with open(db_file, 'w', encoding='utf-8') as f:
                json.dump(all_current_files, f, indent=2, ensure_ascii=False)
            print(f"\n💾 Database saved: {len(all_current_files)} files indexed")
        except Exception as e:
            print(f"Warning: Could not save database: {e}")
        
        print(f"\n🎉 Initial backup completed successfully!")
        print(f"📊 Performance Summary:")
        print(f"  • Files processed: {total_copied}")
        print(f"  • Total data: {self._format_file_size(total_bytes_processed)}")
        print(f"  • Concurrent operations: {max_workers}")
        print(f"  • Backup location: {backup_folder}")
        print(f"  • Database created for future smart backups")
        
        self._wait_for_key()
    
    def _initial_backup_fallback(self, backup_folder: Path, total_files: int, total_size: int) -> None:
        """
        Fallback method untuk initial backup jika async gagal
        """
        print("Using sequential processing mode...")
        
        total_copied = 0
        total_bytes_processed = 0
        current_files = {}
        
        # Backup setiap direktori secara sequential
        for source_dir in self.source_dirs:
            folder_name = Path(source_dir).name
            dest_folder = backup_folder / folder_name
            
            print(f"\nProcessing: {source_dir}")
            
            # Copy dengan tracking untuk database
            source_path = Path(source_dir)
            file_index = 0
            
            for file_path in source_path.rglob('*'):
                if file_path.is_file():
                    try:
                        file_index += 1
                        # Hitung path relatif
                        relative_path = file_path.relative_to(source_path)
                        dest_file = dest_folder / relative_path
                        
                        # Buat direktori jika belum ada
                        dest_file.parent.mkdir(parents=True, exist_ok=True)
                        
                        # Dapatkan ukuran file sebelum copy
                        file_size = os.path.getsize(file_path)
                        start_time = time.time()
                        
                        # Copy file
                        shutil.copy2(file_path, dest_file)
                        total_copied += 1
                        total_bytes_processed += file_size
                        
                        end_time = time.time()
                        copy_time = end_time - start_time
                        
                        # Hitung hash untuk database
                        hash_md5 = hashlib.md5()
                        with open(file_path, "rb") as f:
                            while chunk := f.read(8192):
                                hash_md5.update(chunk)
                        file_hash = hash_md5.hexdigest()
                        
                        # Simpan ke database
                        current_files[str(file_path)] = {
                            'relative_path': str(relative_path),
                            'hash': file_hash,
                            'source_dir': source_dir
                        }
                        
                        # Progress per file
                        if copy_time > 0:
                            speed = file_size / copy_time
                            print(f"[{file_index}] {file_path.name}")
                            print(f"  ✓ {self._format_file_size(file_size)} in {copy_time:.2f}s")
                            print(f"  ⚡ Speed: {self._format_file_size(speed)}/s")
                        else:
                            print(f"[{file_index}] {file_path.name}")
                            print(f"  ✓ {self._format_file_size(file_size)} processed")
                    
                    except Exception as e:
                        print(f"[{file_index}] Error: {e}")
        
        # Save database
        db_file = Path(self.backup_dir) / "file_database.json"
        try:
            with open(db_file, 'w', encoding='utf-8') as f:
                json.dump(current_files, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Could not save database: {e}")
    
    
    def quick_backup(self):
        """
        Quick backup - full backup semua folder - mirip procedure QuickBackup
        """
        self._clear_screen()
        self._show_header()
        print("┌─ QUICK BACKUP (FULL) ───────────────────────┐")
        print("│ Full backup of ALL files (not recommended) │")
        print("│ Use 'Initial Backup' for first time       │")
        print("│ Use 'Smart Backup' for regular backups    │")
        print("└─────────────────────────────────────────────┘")
        print()
        
        # Warning
        print("⚠️  NOTE: This creates a complete copy of all files.")
        print("   If you already did Initial Backup, use Smart Backup instead!")
        print()
        
        # Cek apakah ada konfigurasi
        if not self.source_dirs:
            print("No source directories configured!")
            print("Please configure source directories first in Settings.")
            self._wait_for_key()
            return
        
        if not self.backup_dir:
            print("No backup directory configured!")
            print("Please configure backup directory first in Settings.")
            self._wait_for_key()
            return
        
        # Tampilkan ringkasan
        print("Source directories:")
        for i, source_dir in enumerate(self.source_dirs, 1):
            size, count = self._calculate_folder_size(source_dir)
            print(f"  {i}. {source_dir}")
            print(f"     Files: {count}, Size: {self._format_file_size(size)}")
        
        print(f"\nBackup destination: {self.backup_dir}")
        
        # Konfirmasi
        confirm = input("\nProceed with FULL backup? (y/n): ").lower()
        if confirm != 'y':
            return
        
        # Mulai backup
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_folder = Path(self.backup_dir) / f"full_backup_{timestamp}"
        
        total_copied = 0
        total_bytes_copied = 0
        
        for source_dir in self.source_dirs:
            folder_name = Path(source_dir).name
            dest_folder = backup_folder / folder_name
            
            # Calculate size before copying
            source_size, _ = self._calculate_folder_size(source_dir)
            total_bytes_copied += source_size
            
            copied = self._copy_folder_with_progress(source_dir, str(dest_folder))
            total_copied += copied
        
        print(f"\n✓ Full backup completed successfully!")
        print(f"Total files copied: {total_copied}")
        print(f"Total bytes processed: {self._format_file_size(total_bytes_copied)}")
        print(f"Backup location: {backup_folder}")
        
        self._wait_for_key()
    
    def custom_backup(self):
        """
        Custom backup - pilih folder manual - mirip procedure CustomBackup
        """
        self._clear_screen()
        self._show_header()
        print("┌─ CUSTOM BACKUP ─────────────────────────────┐")
        print("│ Choose specific folders to backup          │")
        print("└─────────────────────────────────────────────┘")
        print()
        
        # Input direktori sumber
        source_dirs = []
        
        print("Enter source directories (empty to finish):")
        while True:
            source = self._input_directory(f"Source directory #{len(source_dirs)+1}")
            if not source:
                break
            source_dirs.append(source)
        
        if not source_dirs:
            print("No source directories selected!")
            self._wait_for_key()
            return
        
        # Input direktori backup
        backup_dir = self._input_directory("Backup directory")
        if not backup_dir:
            return
        
        # Tampilkan ringkasan
        print(f"\n┌─ BACKUP SUMMARY ─────────────────────────────┐")
        for i, source_dir in enumerate(source_dirs, 1):
            size, count = self._calculate_folder_size(source_dir)
            print(f"│ {i}. {Path(source_dir).name}")
            print(f"│    Path: {source_dir}")
            print(f"│    Files: {count}, Size: {self._format_file_size(size)}")
        print(f"│ Destination: {backup_dir}")
        print("└───────────────────────────────────────────────┘")
        
        # Konfirmasi
        confirm = input("\nProceed with backup? (y/n): ").lower()
        if confirm != 'y':
            return
        
        # Mulai backup
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_folder = Path(backup_dir) / f"custom_backup_{timestamp}"
        
        total_copied = 0
        total_bytes_copied = 0
        
        for source_dir in source_dirs:
            folder_name = Path(source_dir).name
            dest_folder = backup_folder / folder_name
            
            # Calculate size before copying
            source_size, _ = self._calculate_folder_size(source_dir)
            total_bytes_copied += source_size
            
            copied = self._copy_folder_with_progress(source_dir, str(dest_folder))
            total_copied += copied
        
        print(f"\n✓ Custom backup completed successfully!")
        print(f"Total files copied: {total_copied}")
        print(f"Total bytes processed: {self._format_file_size(total_bytes_copied)}")
        print(f"Backup location: {backup_folder}")
        
        self._wait_for_key()
    
    def view_backup_history(self):
        """
        Lihat riwayat backup - mirip procedure ViewBackupHistory
        """
        self._clear_screen()
        self._show_header()
        print("┌─ BACKUP HISTORY ────────────────────────────┐")
        print("└─────────────────────────────────────────────┘")
        print()
        
        if not self.backup_dir or not os.path.exists(self.backup_dir):
            print("No backup directory configured or directory not found!")
            self._wait_for_key()
            return
        
        # Scan folder backup
        backup_folders = []
        backup_path = Path(self.backup_dir)
        
        for item in backup_path.iterdir():
            if item.is_dir() and ('backup_' in item.name):
                stat = item.stat()
                size, count = self._calculate_folder_size(str(item))
                backup_folders.append({
                    'name': item.name,
                    'path': str(item),
                    'created': datetime.fromtimestamp(stat.st_ctime),
                    'size': size,
                    'file_count': count
                })
        
        # Sort berdasarkan tanggal terbaru
        backup_folders.sort(key=lambda x: x['created'], reverse=True)
        
        if not backup_folders:
            print("No backup history found!")
        else:
            print(f"Found {len(backup_folders)} backup(s):")
            print()
            for i, backup in enumerate(backup_folders, 1):
                print(f"{i}. {backup['name']}")
                print(f"   Created: {backup['created'].strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"   Files: {backup['file_count']}, Size: {self._format_file_size(backup['size'])}")
                print(f"   Path: {backup['path']}")
                print()
        
        self._wait_for_key()
    
    def settings_menu(self):
        """
        Menu pengaturan - mirip procedure SettingsMenu
        """
        while True:
            self._clear_screen()
            self._show_header()
            print("┌─ SETTINGS ──────────────────────────────────┐")
            print("│ 1. Set Backup Directory                    │")
            print("│ 2. Manage Source Directories              │")
            print("│ 3. View Current Settings                   │")
            print("│ 0. Back to Main Menu                      │")
            print("└─────────────────────────────────────────────┘")
            
            choice = input("\nEnter your choice: ").strip()
            
            if choice == '1':
                self._set_backup_directory()
            elif choice == '2':
                self._manage_source_directories()
            elif choice == '3':
                self._view_current_settings()
            elif choice == '0':
                break
            else:
                print("Invalid choice!")
                self._wait_for_key()
    
    def _set_backup_directory(self):
        """
        Set direktori backup - mirip procedure SetBackupDirectory
        """
        print("\n┌─ SET BACKUP DIRECTORY ──────────────────────┐")
        
        if self.backup_dir:
            print(f"Current backup directory: {self.backup_dir}")
        
        new_dir = self._input_directory("New backup directory")
        if new_dir:
            self.backup_dir = new_dir
            self._save_config()
            print(f"✓ Backup directory set to: {new_dir}")
        
        self._wait_for_key()
    
    def _manage_source_directories(self):
        """
        Kelola direktori sumber - mirip procedure ManageSourceDirectories
        """
        while True:
            print("\n┌─ MANAGE SOURCE DIRECTORIES ─────────────────┐")
            print("│ 1. Add Directory                           │")
            print("│ 2. Remove Directory                       │")
            print("│ 3. List Directories                       │")
            print("│ 0. Back                                   │")
            print("└─────────────────────────────────────────────┘")
            
            choice = input("\nEnter your choice: ").strip()
            
            if choice == '1':
                self._add_source_directory()
            elif choice == '2':
                self._remove_source_directory()
            elif choice == '3':
                self._list_source_directories()
            elif choice == '0':
                break
            else:
                print("Invalid choice!")
    
    def _add_source_directory(self):
        """
        Tambah direktori sumber
        """
        new_dir = self._input_directory("Add source directory")
        if new_dir and new_dir not in self.source_dirs:
            self.source_dirs.append(new_dir)
            self._save_config()
            print(f"✓ Added: {new_dir}")
        elif new_dir in self.source_dirs:
            print("Directory already exists in the list!")
        
        self._wait_for_key()
    
    def _remove_source_directory(self):
        """
        Hapus direktori sumber
        """
        if not self.source_dirs:
            print("No source directories configured!")
            self._wait_for_key()
            return
        
        print("\nCurrent source directories:")
        for i, dir_path in enumerate(self.source_dirs, 1):
            print(f"  {i}. {dir_path}")
        
        try:
            index = int(input("\nEnter number to remove (0 to cancel): ")) - 1
            if 0 <= index < len(self.source_dirs):
                removed = self.source_dirs.pop(index)
                self._save_config()
                print(f"✓ Removed: {removed}")
            elif index != -1:
                print("Invalid number!")
        except ValueError:
            print("Invalid input!")
        
        self._wait_for_key()
    
    def _list_source_directories(self):
        """
        Tampilkan daftar direktori sumber
        """
        if not self.source_dirs:
            print("No source directories configured!")
        else:
            print(f"\nConfigured source directories ({len(self.source_dirs)}):")
            for i, dir_path in enumerate(self.source_dirs, 1):
                size, count = self._calculate_folder_size(dir_path) if os.path.exists(dir_path) else (0, 0)
                status = "✓" if os.path.exists(dir_path) else "✗"
                print(f"  {i}. {status} {dir_path}")
                if os.path.exists(dir_path):
                    print(f"      Files: {count}, Size: {self._format_file_size(size)}")
                else:
                    print(f"      Directory not found!")
        
        self._wait_for_key()
    
    def _view_current_settings(self):
        """
        Tampilkan pengaturan saat ini - mirip procedure ViewCurrentSettings
        """
        print("\n┌─ CURRENT SETTINGS ──────────────────────────┐")
        print(f"│ Backup Directory: {self.backup_dir or 'Not set'}")
        print(f"│ Source Directories: {len(self.source_dirs)}")
        print("└─────────────────────────────────────────────┘")
        
        if self.source_dirs:
            print("\nSource directories:")
            for i, dir_path in enumerate(self.source_dirs, 1):
                status = "✓" if os.path.exists(dir_path) else "✗"
                print(f"  {i}. {status} {dir_path}")
        
        self._wait_for_key()
    
    def cleanup_old_backups(self):
        """
        Cleanup backup lama - mirip procedure CleanupOldBackups
        """
        self._clear_screen()
        self._show_header()
        print("┌─ CLEANUP OLD BACKUPS ───────────────────────┐")
        print("│ Remove old backup folders to save space    │")
        print("└─────────────────────────────────────────────┘")
        print()
        
        if not self.backup_dir or not os.path.exists(self.backup_dir):
            print("No backup directory configured or directory not found!")
            self._wait_for_key()
            return
        
        # Input berapa hari backup yang mau disimpan
        while True:
            try:
                keep_days = input("Keep backups for how many days? (default: 30): ").strip()
                if not keep_days:
                    keep_days = 30
                else:
                    keep_days = int(keep_days)
                
                if keep_days < 1:
                    print("Days must be at least 1!")
                    continue
                break
            except ValueError:
                print("Please enter a valid number!")
        
        # Scan folder backup dan kategorikan
        backup_path = Path(self.backup_dir)
        current_time = datetime.now()
        cutoff_days = keep_days
        
        old_folders = []
        recent_folders = []
        total_old_size = 0
        
        for item in backup_path.iterdir():
            if item.is_dir() and ('backup_' in item.name):
                # Hitung umur folder
                created_time = datetime.fromtimestamp(item.stat().st_ctime)
                age_days = (current_time - created_time).days
                
                # Hitung ukuran folder
                size, count = self._calculate_folder_size(str(item))
                
                folder_info = {
                    'name': item.name,
                    'path': str(item),
                    'created': created_time,
                    'age_days': age_days,
                    'size': size,
                    'file_count': count
                }
                
                if age_days > cutoff_days:
                    old_folders.append(folder_info)
                    total_old_size += size
                else:
                    recent_folders.append(folder_info)
        
        # Tampilkan hasil scan
        print(f"Scan Results:")
        print(f"  Keep backups newer than {keep_days} days")
        print(f"  Recent backups: {len(recent_folders)} folders")
        print(f"  Old backups: {len(old_folders)} folders")
        
        if not old_folders:
            print("  No old backups found to cleanup!")
            self._wait_for_key()
            return
        
        print(f"  Total space to free: {self._format_file_size(total_old_size)}")
        print()
        
        # Tampilkan daftar yang akan dihapus
        print("Folders to be deleted:")
        for folder in sorted(old_folders, key=lambda x: x['created']):
            print(f"  • {folder['name']}")
            print(f"    Created: {folder['created'].strftime('%Y-%m-%d %H:%M')}")
            print(f"    Age: {folder['age_days']} days")
            print(f"    Size: {self._format_file_size(folder['size'])}")
            print()
        
        # Konfirmasi
        confirm = input(f"Delete {len(old_folders)} old backup folders? (y/n): ").lower()
        if confirm != 'y':
            print("Cleanup cancelled.")
            self._wait_for_key()
            return
        
        # Proses penghapusan
        deleted_count = 0
        freed_space = 0
        
        print("\nDeleting old backups...")
        for folder in old_folders:
            try:
                folder_path = Path(folder['path'])
                folder_size = folder['size']
                
                shutil.rmtree(folder_path)
                deleted_count += 1
                freed_space += folder_size
                
                print(f"✓ Deleted: {folder['name']}")
                
            except Exception as e:
                print(f"✗ Error deleting {folder['name']}: {e}")
        
        # Tampilkan hasil
        print(f"\n┌─ CLEANUP COMPLETED ─────────────────────────┐")
        print(f"│ Deleted folders: {deleted_count}/{len(old_folders)}")
        print(f"│ Space freed: {self._format_file_size(freed_space)}")
        print(f"│ Remaining backups: {len(recent_folders)}")
        print("└─────────────────────────────────────────────┘")
        
        self._wait_for_key()
    
    def _save_config(self):
        """
        Simpan konfigurasi - mirip SaveConfig procedure di Delphi
        """
        try:
            if 'BACKUP' not in self.config.sections():
                self.config.add_section('BACKUP')
            
            self.config.set('BACKUP', 'BackupDirectory', self.backup_dir)
            self.config.set('BACKUP', 'SourceDirectories', ';'.join(self.source_dirs))
            self.config.set('BACKUP', 'LogFile', 'backup.log')
            self.config.set('BACKUP', 'KeepBackupDays', '30')
            
            if 'FILTERS' not in self.config.sections():
                self.config.add_section('FILTERS')
                self.config.set('FILTERS', 'ExcludeExtensions', '.tmp;.bak;.log')
                self.config.set('FILTERS', 'ExcludeFolders', 'temp;cache;node_modules')
            
            with open(self.config_path, 'w', encoding='utf-8') as f:
                self.config.write(f)
                
        except Exception as e:
            print(f"Error saving config: {e}")
    
    def smart_backup(self):
        """
        Smart backup - incremental backup - mirip procedure SmartBackup
        """
        self._clear_screen()
        self._show_header()
        print("┌─ SMART BACKUP (INCREMENTAL) ────────────────┐")
        print("│ Only backup new or modified files          │")
        print("└─────────────────────────────────────────────┘")
        print()
        
        # Cek konfigurasi
        if not self.source_dirs or not self.backup_dir:
            print("Please configure source and backup directories first!")
            self._wait_for_key()
            return
        
        # Load database file sebelumnya
        db_file = Path(self.backup_dir) / "file_database.json"
        old_database = {}
        
        if db_file.exists():
            try:
                with open(db_file, 'r', encoding='utf-8') as f:
                    old_database = json.load(f)
                print(f"Loaded database with {len(old_database)} file records")
            except Exception as e:
                print(f"Warning: Could not load database: {e}")
        else:
            print("No previous backup database found - will perform full backup")
        
        # Scan file saat ini dan cari perubahan
        print("\n🔍 Scanning for changes...")
        progress_tracker = ScanningProgress()
        progress_tracker.start_animation("Scanning and analyzing files")
        
        current_files = {}
        changed_files = []
        total_files_scanned = 0
        total_size_scanned = 0
        
        for source_dir in self.source_dirs:
            print(f"\n📁 Scanning: {source_dir}")
            dir_files_scanned = 0
            dir_size_scanned = 0
            
            # Scan direktori
            for file_path in Path(source_dir).rglob('*'):
                if file_path.is_file():
                    str_path = str(file_path)
                    
                    # Hitung hash file
                    try:
                        file_size = os.path.getsize(str_path)
                        dir_files_scanned += 1
                        dir_size_scanned += file_size
                        total_files_scanned += 1
                        total_size_scanned += file_size
                        
                        # Update progress setiap 50 files
                        if total_files_scanned % 50 == 0:
                            progress_tracker.update_progress(source_dir, total_files_scanned, total_size_scanned)
                        
                        hash_md5 = hashlib.md5()
                        with open(str_path, "rb") as f:
                            while chunk := f.read(8192):
                                hash_md5.update(chunk)
                        file_hash = hash_md5.hexdigest()
                        
                        # Simpan info file
                        relative_path = str(file_path.relative_to(Path(source_dir)))
                        current_files[str_path] = {
                            'relative_path': relative_path,
                            'hash': file_hash,
                            'source_dir': source_dir
                        }
                        
                        # Cek apakah file berubah
                        if str_path not in old_database or old_database[str_path].get('hash') != file_hash:
                            changed_files.append(str_path)
                            
                    except Exception as e:
                        print(f"Error processing {str_path}: {e}")
            
            # Update final progress untuk direktori ini
            progress_tracker.update_progress(source_dir, total_files_scanned, total_size_scanned)
        
        # Stop animation
        progress_tracker.stop_animation()
        
        # Tampilkan hasil scan
        print(f"\nScan complete:")
        print(f"  Total files: {len(current_files)}")
        print(f"  Changed files: {len(changed_files)}")
        
        if not changed_files:
            print("No changes detected - backup not needed!")
            self._wait_for_key()
            return
        
        # Konfirmasi backup
        confirm = input(f"\nBackup {len(changed_files)} changed files? (y/n): ").lower()
        if confirm != 'y':
            return
        
        # Mulai backup
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_folder = Path(self.backup_dir) / f"smart_backup_{timestamp}"
        
        print(f"\nBacking up to: {backup_folder}")
        print("-" * 50)
        
        copied_count = 0
        total_bytes_processed = 0
        
        # Calculate total size of changed files first
        total_changed_size = 0
        for file_path in changed_files:
            try:
                total_changed_size += os.path.getsize(file_path)
            except (OSError, FileNotFoundError):
                continue
        
        print(f"Total size to backup: {self._format_file_size(total_changed_size)}")
        print("-" * 50)
        
        for file_path in changed_files:
            try:
                file_info = current_files[file_path]
                source_name = Path(file_info['source_dir']).name
                relative_path = file_info['relative_path']
                
                # Get file size before copying
                file_size = os.path.getsize(file_path)
                
                # Tentukan lokasi backup
                dest_file = backup_folder / source_name / relative_path
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                
                # Copy file
                shutil.copy2(file_path, dest_file)
                copied_count += 1
                total_bytes_processed += file_size
                
                if copied_count % 10 == 0 or copied_count <= 10:
                    bytes_progress = (total_bytes_processed / total_changed_size) * 100 if total_changed_size > 0 else 0
                    print(f"Copied: {copied_count}/{len(changed_files)} - {relative_path}")
                    print(f"  Bytes: {self._format_file_size(total_bytes_processed)}/{self._format_file_size(total_changed_size)} ({bytes_progress:.1f}%)")
                    print(f"  File size: {self._format_file_size(file_size)}")
                    
            except Exception as e:
                print(f"Error copying {file_path}: {e}")
        
        # Update database
        try:
            with open(db_file, 'w', encoding='utf-8') as f:
                json.dump(current_files, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Could not save database: {e}")
        
        print(f"\n✓ Smart backup completed successfully!")
        print(f"Files copied: {copied_count}/{len(changed_files)}")
        print(f"Total bytes processed: {self._format_file_size(total_bytes_processed)}")
        print(f"Backup location: {backup_folder}")
        
        self._wait_for_key()
    
    def run(self):
        """
        Main program loop - mirip Main program di Pascal
        """
        while True:
            self._clear_screen()
            self._show_header()
            self._show_main_menu()
            
            choice = input("\nEnter your choice: ").strip()
            
            if choice == '1':
                self.initial_backup()
            elif choice == '2':
                self.quick_backup()
            elif choice == '3':
                self.smart_backup()
            elif choice == '4':
                self.custom_backup()
            elif choice == '5':
                self.view_backup_history()
            elif choice == '6':
                self.cleanup_old_backups()
            elif choice == '7':
                self.settings_menu()
            elif choice == '0':
                print("\nThank you for using Manual Backup Application!")
                break
            else:
                print("Invalid choice! Please try again.")
                self._wait_for_key()


def main():
    """
    Entry point - mirip begin..end program utama di Pascal
    """
    try:
        app = ManualBackup()
        app.run()
    except KeyboardInterrupt:
        print("\n\nProgram interrupted by user. Goodbye!")
    except Exception as e:
        print(f"Fatal error: {e}")
        input("Press Enter to exit...")
        sys.exit(1)


if __name__ == "__main__":
    main()