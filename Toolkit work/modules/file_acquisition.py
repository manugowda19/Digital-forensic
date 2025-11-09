"""
File Acquisition Module
Handles acquisition of disk images from digital devices (USB drives, external drives, etc.)
and conversion of disk images to E01 format
"""

import os
import platform
import subprocess
import hashlib
import threading
from datetime import datetime
from PySide6.QtCore import QThread, Signal, QObject
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, 
                               QPushButton, QProgressBar, QTextEdit, QFileDialog, 
                               QMessageBox, QGroupBox, QFormLayout, QLineEdit, QCheckBox)


class DeviceAcquisitionThread(QThread):
    """Thread for performing disk acquisition without blocking UI."""
    progress = Signal(int)  # Progress percentage
    status = Signal(str)  # Status message
    finished = Signal(bool, str)  # Success status and message
    hash_progress = Signal(str)  # Hash calculation progress
    
    def __init__(self, device_path, output_path, format_type, calculate_hash=True, block_size=1024*1024):
        super().__init__()
        self.device_path = device_path
        self.output_path = output_path
        self.format_type = format_type  # 'raw' or 'ewf'
        self.calculate_hash = calculate_hash
        self.block_size = block_size
        self.cancelled = False
        
    def cancel(self):
        """Cancel the acquisition process."""
        self.cancelled = True
        
    def run(self):
        """Run the acquisition process."""
        try:
            if self.format_type == 'raw':
                self._acquire_raw()
            elif self.format_type == 'ewf':
                self._acquire_ewf()
            else:
                self.finished.emit(False, f"Unsupported format: {self.format_type}")
                return
                
            # Calculate hash if requested
            if self.calculate_hash and not self.cancelled:
                self._calculate_hashes()
                
            if not self.cancelled:
                self.finished.emit(True, f"Acquisition completed successfully: {self.output_path}")
        except Exception as e:
            self.finished.emit(False, f"Acquisition failed: {str(e)}")
    
    def _acquire_raw(self):
        """Acquire disk image in raw format (.dd)."""
        system = platform.system()
        
        # Get device size (try but don't fail if we can't determine it)
        device_size = self._get_device_size()
        if device_size > 0:
            self.status.emit(f"Device size: {self._format_size(device_size)}")
        else:
            self.status.emit("Warning: Could not determine device size. Will read until end of device.")
            device_size = 0  # Will be determined during acquisition
        
        self.status.emit(f"Starting raw acquisition from {self.device_path}...")
        
        if system == 'Linux':
            self._acquire_raw_linux(device_size)
        elif system == 'Windows':
            self._acquire_raw_windows(device_size)
        elif system == 'Darwin':  # macOS
            self._acquire_raw_macos(device_size)
        else:
            raise Exception(f"Unsupported operating system: {system}")
    
    def _acquire_raw_linux(self, device_size):
        """Acquire raw image on Linux using dd."""
        bytes_read = 0
        last_progress = 0
        progress_counter = 0
        
        # Validate output path before starting
        if os.path.isdir(self.output_path):
            raise Exception(f"Output path is a directory, not a file: {self.output_path}\nPlease specify a file path.")
        
        # Ensure parent directory exists
        parent_dir = os.path.dirname(self.output_path)
        if parent_dir and not os.path.exists(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except Exception as e:
                raise Exception(f"Failed to create parent directory {parent_dir}: {e}")
        
        try:
            # Use dd to copy device to file
            # Note: May require sudo for raw device access
            cmd = ['dd', f'if={self.device_path}', f'of={self.output_path}', 
                   f'bs={self.block_size}', 'status=progress', 'conv=noerror,sync']
            
            # Check if we can read the device without sudo first
            needs_sudo = False
            try:
                test_fd = os.open(self.device_path, os.O_RDONLY)
                os.close(test_fd)
            except PermissionError:
                needs_sudo = True
            except Exception:
                pass  # Try without sudo first
            
            if needs_sudo:
                # Try to use pkexec (GUI sudo prompt) or sudo
                # Check if pkexec is available (common on Linux desktop)
                if subprocess.run(['which', 'pkexec'], capture_output=True).returncode == 0:
                    cmd = ['pkexec'] + cmd
                    self.status.emit("Using pkexec to request administrator privileges...")
                elif subprocess.run(['which', 'gksudo'], capture_output=True).returncode == 0:
                    cmd = ['gksudo'] + cmd
                    self.status.emit("Using gksudo to request administrator privileges...")
                else:
                    # Try sudo (will prompt in terminal if available)
                    cmd = ['sudo'] + cmd
                    self.status.emit("Using sudo (you may be prompted for password in terminal)...")
            else:
                self.status.emit("Starting acquisition...")
            
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                                      stderr=subprocess.STDOUT, 
                                      universal_newlines=True, bufsize=1)
            
            for line in process.stdout:
                if self.cancelled:
                    process.terminate()
                    if os.path.exists(self.output_path):
                        os.remove(self.output_path)
                    raise Exception("Acquisition cancelled by user")
                
                # Parse dd progress output
                if 'bytes' in line.lower() or 'copied' in line.lower():
                    try:
                        # Extract bytes from dd output (format: "1234567 bytes (1.2 MB, 1.1 MiB) copied")
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if part == 'bytes' and i > 0:
                                bytes_read = int(parts[i-1].replace(',', ''))
                                break
                        
                        if device_size > 0:
                            progress = int((bytes_read / device_size) * 100)
                            self.progress.emit(min(progress, 100))
                            self.status.emit(f"Acquiring... {self._format_size(bytes_read)} / {self._format_size(device_size)} ({progress}%)")
                        else:
                            # If we don't know device size, just show bytes read
                            # Estimate progress based on file size growth
                            if os.path.exists(self.output_path):
                                file_size = os.path.getsize(self.output_path)
                                if file_size > bytes_read:
                                    bytes_read = file_size
                            
                            # Show incremental progress
                            if bytes_read > 0:
                                # Update progress every 1% of estimated size (if we had one)
                                # Otherwise just show bytes
                                self.status.emit(f"Acquiring... {self._format_size(bytes_read)}")
                                # Increment progress slowly to show activity
                                if bytes_read > last_progress + (10 * 1024 * 1024):  # Every 10MB
                                    last_progress = bytes_read
                                    # Increment progress by 1% up to 99% (will be set to 100% when done)
                                    progress_counter = min(progress_counter + 1, 99)
                                    self.progress.emit(progress_counter)
                    except Exception as e:
                        # Continue even if parsing fails
                        self.status.emit(f"Progress: {line.strip()}")
            
            process.wait()
            if process.returncode != 0:
                error_msg = f"dd command failed with return code {process.returncode}"
                # Check if it's a permission error
                if process.returncode == 1:
                    error_msg = (
                        "Acquisition failed: Permission denied.\n\n"
                        "Raw device access requires root/administrator privileges.\n\n"
                        "Options:\n"
                        "1. Run the application with sudo: sudo python3 main.py\n"
                        "2. Run dd manually in terminal:\n"
                        f"   sudo dd if={self.device_path} of={self.output_path} bs={self.block_size} status=progress conv=noerror,sync\n"
                        "3. Add your user to disk group (Linux):\n"
                        "   sudo usermod -aG disk $USER\n"
                        "   (then logout and login again)\n\n"
                        "Note: Running with sudo is the most secure option for forensic acquisition."
                    )
                raise Exception(error_msg)
            
            # Final progress update
            if os.path.exists(self.output_path):
                final_size = os.path.getsize(self.output_path)
                self.status.emit(f"Acquisition complete. Final size: {self._format_size(final_size)}")
                self.progress.emit(100)
                
        except Exception as e:
            if os.path.exists(self.output_path):
                os.remove(self.output_path)
            raise
    
    def _acquire_raw_windows(self, device_size):
        """Acquire raw image on Windows."""
        # Windows requires admin privileges and special tools
        # Using dd for Windows or Win32DiskImager
        bytes_read = 0
        
        try:
            # Try using dd for Windows if available
            cmd = ['dd', f'if={self.device_path}', f'of={self.output_path}', 
                   f'bs={self.block_size}', 'status=progress', 'conv=noerror,sync']
            
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                                      stderr=subprocess.STDOUT, 
                                      universal_newlines=True, bufsize=1)
            
            for line in process.stdout:
                if self.cancelled:
                    process.terminate()
                    if os.path.exists(self.output_path):
                        os.remove(self.output_path)
                    raise Exception("Acquisition cancelled by user")
                
                # Parse progress
                if 'bytes' in line.lower():
                    try:
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if part == 'bytes' and i > 0:
                                bytes_read = int(parts[i-1].replace(',', ''))
                                break
                        
                        progress = int((bytes_read / device_size) * 100) if device_size > 0 else 0
                        self.progress.emit(min(progress, 100))
                        self.status.emit(f"Acquiring... {self._format_size(bytes_read)} / {self._format_size(device_size)}")
                    except:
                        pass
            
            process.wait()
            if process.returncode != 0:
                raise Exception(f"Acquisition command failed with return code {process.returncode}")
        except FileNotFoundError:
            raise Exception("dd command not found. Please install dd for Windows or use Win32DiskImager.")
        except Exception as e:
            if os.path.exists(self.output_path):
                os.remove(self.output_path)
            raise
    
    def _acquire_raw_macos(self, device_size):
        """Acquire raw image on macOS using dd."""
        bytes_read = 0
        
        try:
            cmd = ['dd', f'if={self.device_path}', f'of={self.output_path}', 
                   f'bs={self.block_size}', 'status=progress', 'conv=noerror,sync']
            
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                                      stderr=subprocess.STDOUT, 
                                      universal_newlines=True, bufsize=1)
            
            for line in process.stdout:
                if self.cancelled:
                    process.terminate()
                    if os.path.exists(self.output_path):
                        os.remove(self.output_path)
                    raise Exception("Acquisition cancelled by user")
                
                # Parse dd progress
                if 'bytes' in line.lower():
                    try:
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if part == 'bytes' and i > 0:
                                bytes_read = int(parts[i-1].replace(',', ''))
                                break
                        
                        progress = int((bytes_read / device_size) * 100) if device_size > 0 else 0
                        self.progress.emit(min(progress, 100))
                        self.status.emit(f"Acquiring... {self._format_size(bytes_read)} / {self._format_size(device_size)}")
                    except:
                        pass
            
            process.wait()
            if process.returncode != 0:
                raise Exception(f"dd command failed with return code {process.returncode}")
        except Exception as e:
            if os.path.exists(self.output_path):
                os.remove(self.output_path)
            raise
    
    def _acquire_ewf(self):
        """Acquire disk image in EWF format (.e01) using ewfacquire."""
        # Validate output path before starting
        if os.path.isdir(self.output_path):
            raise Exception(f"Output path is a directory, not a file: {self.output_path}\nPlease specify a file path.")
        
        # Ensure parent directory exists
        parent_dir = os.path.dirname(self.output_path)
        if parent_dir and not os.path.exists(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except Exception as e:
                raise Exception(f"Failed to create parent directory {parent_dir}: {e}")
        
        try:
            # Check if ewfacquire is available
            subprocess.run(['ewfacquire', '--version'], 
                          capture_output=True, check=True, timeout=5)
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise Exception("ewfacquire not found. Please install libewf-tools: sudo apt install libewf-tools")
        
        device_size = self._get_device_size()
        if device_size > 0:
            self.status.emit(f"Device size: {self._format_size(device_size)}")
        else:
            self.status.emit("Warning: Could not determine device size. ewfacquire will determine it automatically.")
        
        self.status.emit(f"Starting EWF acquisition from {self.device_path}...")
        
        # Use ewfacquire to create EWF image
        cmd = ['ewfacquire', '-t', self.output_path.replace('.e01', ''), 
               self.device_path]
        
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                                      stderr=subprocess.STDOUT, 
                                      universal_newlines=True, bufsize=1)
            
            for line in process.stdout:
                if self.cancelled:
                    process.terminate()
                    # Clean up partial EWF files
                    base_path = self.output_path.replace('.e01', '')
                    for ext in ['.e01', '.e02', '.e03']:
                        if os.path.exists(base_path + ext):
                            os.remove(base_path + ext)
                    raise Exception("Acquisition cancelled by user")
                
                # Parse ewfacquire progress
                if '%' in line:
                    try:
                        # Extract percentage from line like "Progress: 45%"
                        percent_str = line.split('%')[0].split()[-1]
                        progress = int(float(percent_str))
                        self.progress.emit(progress)
                        self.status.emit(f"Acquiring EWF image... {progress}%")
                    except:
                        pass
            
            process.wait()
            if process.returncode != 0:
                raise Exception(f"ewfacquire failed with return code {process.returncode}")
        except Exception as e:
            # Clean up partial files
            base_path = self.output_path.replace('.e01', '')
            for ext in ['.e01', '.e02', '.e03']:
                if os.path.exists(base_path + ext):
                    os.remove(base_path + ext)
            raise
    
    def _get_device_size(self):
        """Get the size of the device in bytes."""
        system = platform.system()
        
        try:
            if system == 'Linux':
                # Method 1: Try blockdev (requires root, but most accurate)
                try:
                    result = subprocess.run(['blockdev', '--getsize64', self.device_path],
                                          capture_output=True, text=True, check=True, timeout=5)
                    size = result.stdout.strip()
                    if size and size.isdigit():
                        return int(size)
                except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
                    self.status.emit(f"blockdev failed (may need sudo): {e}")
                
                # Method 2: Try reading from /sys/block (no root needed for most info)
                try:
                    device_name = os.path.basename(self.device_path)
                    size_file = f"/sys/block/{device_name}/size"
                    if os.path.exists(size_file):
                        with open(size_file, 'r') as f:
                            sectors = int(f.read().strip())
                            # Sector size is typically 512 bytes
                            return sectors * 512
                except (ValueError, IOError, OSError) as e:
                    self.status.emit(f"Reading /sys/block failed: {e}")
                
                # Method 3: Try lsblk to get size
                try:
                    device_name = os.path.basename(self.device_path)
                    result = subprocess.run(['lsblk', '-b', '-d', '-n', '-o', 'SIZE', self.device_path],
                                          capture_output=True, text=True, check=True, timeout=5)
                    size = result.stdout.strip()
                    if size and size.isdigit():
                        return int(size)
                except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
                    self.status.emit(f"lsblk failed: {e}")
                
                # Method 4: Try fdisk -l (requires root but gives good info)
                try:
                    result = subprocess.run(['fdisk', '-l', self.device_path],
                                          capture_output=True, text=True, check=True, timeout=5)
                    for line in result.stdout.split('\n'):
                        if 'Disk' in line and 'bytes' in line:
                            # Extract size from line like "Disk /dev/sdb: 15.0 GiB, 16106127360 bytes"
                            parts = line.split(',')
                            for part in parts:
                                if 'bytes' in part:
                                    size_str = part.split()[0]
                                    return int(size_str)
                except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                    pass  # fdisk usually requires root
                
            elif system == 'Windows':
                # Use wmic to get disk size
                try:
                    # Extract disk number from device path (e.g., \\.\PhysicalDrive0)
                    disk_num = self.device_path.replace('\\\\.\\PhysicalDrive', '')
                    result = subprocess.run(['wmic', 'diskdrive', 'where', 
                                           f'index={disk_num}', 'get', 'size'],
                                          capture_output=True, text=True, check=True, timeout=5)
                    lines = result.stdout.strip().split('\n')
                    for line in lines:
                        line = line.strip()
                        if line and line.isdigit():
                            return int(line)
                except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
                    self.status.emit(f"wmic failed: {e}")
                    
            elif system == 'Darwin':  # macOS
                # Use diskutil to get disk size
                try:
                    # Extract disk identifier (e.g., /dev/disk2 -> disk2)
                    disk_id = os.path.basename(self.device_path)
                    result = subprocess.run(['diskutil', 'info', disk_id],
                                          capture_output=True, text=True, check=True, timeout=5)
                    for line in result.stdout.split('\n'):
                        if 'Disk Size:' in line or 'Total Size:' in line:
                            # Parse size (format: "Disk Size: 16.0 GB (16000000000 Bytes)")
                            parts = line.split('(')
                            if len(parts) > 1:
                                size_str = parts[1].split()[0]
                                return int(size_str)
                except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
                    self.status.emit(f"diskutil failed: {e}")
                    
        except Exception as e:
            self.status.emit(f"Unexpected error getting device size: {e}")
        
        return 0
    
    def _calculate_hashes(self):
        """Calculate MD5, SHA1, and SHA256 hashes of the acquired image."""
        if not os.path.exists(self.output_path):
            return
        
        self.status.emit("Calculating hashes...")
        
        md5_hash = hashlib.md5()
        sha1_hash = hashlib.sha1()
        sha256_hash = hashlib.sha256()
        
        file_size = os.path.getsize(self.output_path)
        bytes_read = 0
        
        with open(self.output_path, 'rb') as f:
            while True:
                if self.cancelled:
                    return
                
                chunk = f.read(self.block_size)
                if not chunk:
                    break
                
                md5_hash.update(chunk)
                sha1_hash.update(chunk)
                sha256_hash.update(chunk)
                
                bytes_read += len(chunk)
                hash_progress = int((bytes_read / file_size) * 100) if file_size > 0 else 0
                self.hash_progress.emit(f"Calculating hashes... {hash_progress}%")
        
        md5_hex = md5_hash.hexdigest()
        sha1_hex = sha1_hash.hexdigest()
        sha256_hex = sha256_hash.hexdigest()
        
        # Save hashes to a file
        hash_file = self.output_path + '.hash'
        with open(hash_file, 'w') as f:
            f.write(f"MD5: {md5_hex}\n")
            f.write(f"SHA1: {sha1_hex}\n")
            f.write(f"SHA256: {sha256_hex}\n")
            f.write(f"File: {os.path.basename(self.output_path)}\n")
            f.write(f"Date: {datetime.now().isoformat()}\n")
        
        self.status.emit(f"Hashes calculated and saved to {hash_file}")
        self.hash_progress.emit(f"MD5: {md5_hex}\nSHA1: {sha1_hex}\nSHA256: {sha256_hex}")
    
    def _format_size(self, size_bytes):
        """Format size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"


class DeviceDetector:
    """Detects connected digital devices."""
    
    @staticmethod
    def detect_devices():
        """Detect all connected storage devices."""
        system = platform.system()
        
        if system == 'Linux':
            return DeviceDetector._detect_linux()
        elif system == 'Windows':
            return DeviceDetector._detect_windows()
        elif system == 'Darwin':  # macOS
            return DeviceDetector._detect_macos()
        else:
            return []
    
    @staticmethod
    def _detect_linux():
        """Detect devices on Linux using lsblk."""
        devices = []
        
        try:
            # Use lsblk to list block devices
            result = subprocess.run(['lsblk', '-d', '-n', '-o', 'NAME,SIZE,TYPE,MODEL'],
                                  capture_output=True, text=True, check=True)
            
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                
                parts = line.split()
                if len(parts) >= 3:
                    name = parts[0]
                    size = parts[1] if len(parts) > 1 else "Unknown"
                    device_type = parts[2] if len(parts) > 2 else "Unknown"
                    model = ' '.join(parts[3:]) if len(parts) > 3 else "Unknown"
                    
                    # Only include disk devices (not partitions)
                    if device_type == 'disk':
                        device_path = f"/dev/{name}"
                        devices.append({
                            'path': device_path,
                            'name': name,
                            'size': size,
                            'type': device_type,
                            'model': model,
                            'display': f"{name} - {model} ({size})"
                        })
        except Exception as e:
            print(f"Error detecting Linux devices: {e}")
        
        return devices
    
    @staticmethod
    def _detect_windows():
        """Detect devices on Windows using wmic."""
        devices = []
        
        try:
            # Use wmic to list disk drives
            result = subprocess.run(['wmic', 'diskdrive', 'get', 
                                   'index,size,model,interfaceType'],
                                  capture_output=True, text=True, check=True)
            
            lines = result.stdout.strip().split('\n')[1:]  # Skip header
            for line in lines:
                if not line.strip():
                    continue
                
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        index = parts[0]
                        size = parts[1] if len(parts) > 1 else "0"
                        model = ' '.join(parts[2:-1]) if len(parts) > 2 else "Unknown"
                        interface = parts[-1] if len(parts) > 1 else "Unknown"
                        
                        device_path = f"\\\\.\\PhysicalDrive{index}"
                        size_gb = int(size) / (1024**3) if size.isdigit() else 0
                        
                        devices.append({
                            'path': device_path,
                            'name': f"PhysicalDrive{index}",
                            'size': f"{size_gb:.2f} GB" if size_gb > 0 else "Unknown",
                            'type': interface,
                            'model': model,
                            'display': f"PhysicalDrive{index} - {model} ({size_gb:.2f} GB)"
                        })
                    except (ValueError, IndexError):
                        continue
        except Exception as e:
            print(f"Error detecting Windows devices: {e}")
        
        return devices
    
    @staticmethod
    def _detect_macos():
        """Detect devices on macOS using diskutil."""
        devices = []
        
        try:
            # Use diskutil to list disks
            result = subprocess.run(['diskutil', 'list', '-plist'],
                                  capture_output=True, text=True, check=True)
            
            # Parse plist output (simplified - in production, use plistlib)
            # For now, use diskutil list for simpler parsing
            result = subprocess.run(['diskutil', 'list'],
                                  capture_output=True, text=True, check=True)
            
            current_disk = None
            for line in result.stdout.split('\n'):
                if '/dev/disk' in line and 'external' in line.lower():
                    # Extract disk identifier
                    parts = line.split()
                    for part in parts:
                        if '/dev/disk' in part:
                            disk_id = part.split('/')[-1]
                            current_disk = disk_id
                            break
                elif current_disk and ('GB' in line or 'TB' in line or 'MB' in line):
                    # Extract size
                    size_parts = line.split()
                    size = "Unknown"
                    for part in size_parts:
                        if 'GB' in part or 'TB' in part or 'MB' in part:
                            size = part
                            break
                    
                    device_path = f"/dev/{current_disk}"
                    devices.append({
                        'path': device_path,
                        'name': current_disk,
                        'size': size,
                        'type': 'disk',
                        'model': 'External Disk',
                        'display': f"{current_disk} - External Disk ({size})"
                    })
                    current_disk = None
        except Exception as e:
            print(f"Error detecting macOS devices: {e}")
        
        return devices


class FileAcquisitionDialog(QDialog):
    """Dialog for file acquisition from digital devices."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("File Acquisition - Digital Device")
        self.setMinimumSize(600, 500)
        
        self.acquisition_thread = None
        self.devices = []
        
        self.init_ui()
        self.refresh_devices()
    
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()
        
        # Device selection group
        device_group = QGroupBox("Select Digital Device")
        device_layout = QVBoxLayout()
        
        device_form = QFormLayout()
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(400)
        refresh_btn = QPushButton("Refresh Devices")
        refresh_btn.clicked.connect(self.refresh_devices)
        
        device_form.addRow("Device:", self.device_combo)
        device_layout.addLayout(device_form)
        device_layout.addWidget(refresh_btn)
        device_group.setLayout(device_layout)
        layout.addWidget(device_group)
        
        # Output settings group
        output_group = QGroupBox("Output Settings")
        output_layout = QFormLayout()
        
        self.output_path_edit = QLineEdit()
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_output_path)
        
        output_path_layout = QHBoxLayout()
        output_path_layout.addWidget(self.output_path_edit)
        output_path_layout.addWidget(browse_btn)
        
        self.format_combo = QComboBox()
        self.format_combo.addItems(["Raw Image (.dd)", "EWF Image (.e01)"])
        
        self.hash_checkbox = QCheckBox("Calculate MD5, SHA1, SHA256 hashes")
        self.hash_checkbox.setChecked(True)
        
        output_layout.addRow("Output Path:", output_path_layout)
        output_layout.addRow("Format:", self.format_combo)
        output_layout.addRow("", self.hash_checkbox)
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)
        
        # Progress group
        progress_group = QGroupBox("Acquisition Progress")
        progress_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(150)
        
        progress_layout.addWidget(QLabel("Progress:"))
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(QLabel("Status:"))
        progress_layout.addWidget(self.status_text)
        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Acquisition")
        self.start_btn.clicked.connect(self.start_acquisition)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_acquisition)
        self.cancel_btn.setEnabled(False)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.cancel_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.close_btn)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def refresh_devices(self):
        """Refresh the list of connected devices."""
        self.status_text.append("Scanning for connected devices...")
        self.devices = DeviceDetector.detect_devices()
        
        self.device_combo.clear()
        if self.devices:
            for device in self.devices:
                self.device_combo.addItem(device['display'], device)
            self.status_text.append(f"Found {len(self.devices)} device(s)")
        else:
            self.device_combo.addItem("No devices found")
            self.status_text.append("No devices found. Please connect a digital device.")
    
    def browse_output_path(self):
        """Browse for output file path."""
        format_index = self.format_combo.currentIndex()
        if format_index == 0:  # Raw
            ext_filter = "Raw Image Files (*.dd);;All Files (*)"
            default_ext = ".dd"
            default_name = "acquisition.dd"
        else:  # EWF
            ext_filter = "EWF Image Files (*.e01);;All Files (*)"
            default_ext = ".e01"
            default_name = "acquisition.e01"
        
        # Get current directory or use Desktop as default
        current_path = self.output_path_edit.text().strip()
        if current_path:
            default_dir = os.path.dirname(current_path) if os.path.dirname(current_path) else os.path.expanduser("~/Desktop")
        else:
            default_dir = os.path.expanduser("~/Desktop")
        
        # Ensure default_dir exists
        if not os.path.exists(default_dir):
            default_dir = os.path.expanduser("~")
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Acquisition As", 
            os.path.join(default_dir, default_name),
            ext_filter
        )
        
        if file_path:
            # Normalize the path
            file_path = os.path.normpath(file_path)
            
            # Ensure it has the correct extension
            if not file_path.endswith(default_ext):
                file_path += default_ext
            
            # Validate it's not a directory
            if os.path.isdir(file_path):
                QMessageBox.warning(
                    self, "Invalid Path",
                    f"The selected path is a directory. Please select a file path.\n\n"
                    f"Using: {file_path}{default_ext}"
                )
                file_path = os.path.join(file_path, default_name)
            
            self.output_path_edit.setText(file_path)
    
    def start_acquisition(self):
        """Start the acquisition process."""
        if not self.devices or self.device_combo.currentIndex() < 0:
            QMessageBox.warning(self, "No Device", "Please select a device to acquire.")
            return
        
        output_path = self.output_path_edit.text().strip()
        if not output_path:
            QMessageBox.warning(self, "No Output Path", "Please specify an output file path.")
            return
        
        # Normalize the path
        output_path = os.path.normpath(output_path)
        
        # Expand user path if it starts with ~
        if output_path.startswith('~'):
            output_path = os.path.expanduser(output_path)
        
        # Resolve relative paths
        if not os.path.isabs(output_path):
            output_path = os.path.abspath(output_path)
        
        # Check if output path is a directory (before adding extension)
        if os.path.isdir(output_path):
            QMessageBox.warning(
                self, "Invalid Output Path", 
                f"The specified path is a directory, not a file:\n{output_path}\n\n"
                f"Please specify a file path (e.g., {output_path}/acquisition.dd)"
            )
            return
        
        # Ensure the output path has the correct extension
        format_index = self.format_combo.currentIndex()
        if format_index == 0:  # Raw
            if not output_path.endswith('.dd'):
                output_path += '.dd'
        else:  # EWF
            if not output_path.endswith('.e01'):
                output_path += '.e01'
        
        # Check again if output path is a directory (after adding extension)
        if os.path.isdir(output_path):
            QMessageBox.warning(
                self, "Invalid Output Path", 
                f"The specified path is a directory, not a file:\n{output_path}\n\n"
                f"Please specify a file path."
            )
            return
        
        # Create parent directory if it doesn't exist
        parent_dir = os.path.dirname(output_path)
        if parent_dir and not os.path.exists(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(
                    self, "Error Creating Directory",
                    f"Failed to create output directory:\n{parent_dir}\n\nError: {e}"
                )
                return
        
        # Final validation: ensure output path is not a directory and parent exists
        if os.path.isdir(output_path):
            QMessageBox.warning(
                self, "Invalid Output Path", 
                f"The specified path is a directory, not a file:\n{output_path}\n\n"
                f"Please specify a file path."
            )
            return
        
        # Check if output file already exists
        if os.path.exists(output_path):
            reply = QMessageBox.question(
                self, "File Exists", 
                f"The file {output_path} already exists. Overwrite?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        # Get selected device
        device = self.device_combo.currentData()
        if not device:
            QMessageBox.warning(self, "Invalid Device", "Please select a valid device.")
            return
        
        # Get format
        format_index = self.format_combo.currentIndex()
        format_type = 'raw' if format_index == 0 else 'ewf'
        
        # Update the output path edit with the validated path
        self.output_path_edit.setText(output_path)
        
        # Confirm before starting
        reply = QMessageBox.warning(
            self, "Confirm Acquisition",
            f"WARNING: This will acquire data from {device['display']}.\n\n"
            f"Output: {output_path}\n"
            f"Format: {format_type.upper()}\n\n"
            f"This process may take a long time depending on device size.\n\n"
            f"Continue?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.No:
            return
        
        # Disable start button, enable cancel button
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_text.clear()
        
        # Start acquisition thread
        calculate_hash = self.hash_checkbox.isChecked()
        self.acquisition_thread = DeviceAcquisitionThread(
            device['path'], output_path, format_type, calculate_hash
        )
        self.acquisition_thread.progress.connect(self.progress_bar.setValue)
        self.acquisition_thread.status.connect(self.status_text.append)
        self.acquisition_thread.hash_progress.connect(self.status_text.append)
        self.acquisition_thread.finished.connect(self.acquisition_finished)
        self.acquisition_thread.start()
    
    def cancel_acquisition(self):
        """Cancel the ongoing acquisition."""
        if self.acquisition_thread and self.acquisition_thread.isRunning():
            reply = QMessageBox.question(
                self, "Cancel Acquisition",
                "Are you sure you want to cancel the acquisition?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.acquisition_thread.cancel()
                self.status_text.append("Acquisition cancelled by user...")
    
    def acquisition_finished(self, success, message):
        """Handle acquisition completion."""
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        
        if success:
            QMessageBox.information(self, "Acquisition Complete", message)
        else:
            QMessageBox.critical(self, "Acquisition Failed", message)
        
        self.status_text.append(message)


class ImageToE01ConversionThread(QThread):
    """Thread for converting disk images to E01 format without blocking UI."""
    progress = Signal(int)  # Progress percentage
    status = Signal(str)  # Status message
    finished = Signal(bool, str)  # Success status and message
    hash_progress = Signal(str)  # Hash calculation progress
    
    def __init__(self, input_path, output_path, calculate_hash=True, block_size=1024*1024):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.calculate_hash = calculate_hash
        self.block_size = block_size
        self.cancelled = False
        
    def cancel(self):
        """Cancel the conversion process."""
        self.cancelled = True
        
    def run(self):
        """Run the conversion process."""
        try:
            self._convert_to_e01()
            
            # Calculate hash if requested
            if self.calculate_hash and not self.cancelled:
                self._calculate_hashes()
                
            if not self.cancelled:
                self.finished.emit(True, f"Conversion completed successfully: {self.output_path}")
        except Exception as e:
            self.finished.emit(False, f"Conversion failed: {str(e)}")
    
    def _convert_to_e01(self):
        """Convert disk image to E01 format using ewfacquire."""
        # Validate input path
        if not os.path.exists(self.input_path):
            raise Exception(f"Input file does not exist: {self.input_path}")
        
        if not os.path.isfile(self.input_path):
            raise Exception(f"Input path is not a file: {self.input_path}")
        
        # Validate output path
        if os.path.isdir(self.output_path):
            raise Exception(f"Output path is a directory, not a file: {self.output_path}\nPlease specify a file path.")
        
        # Ensure parent directory exists
        parent_dir = os.path.dirname(self.output_path)
        if parent_dir and not os.path.exists(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except Exception as e:
                raise Exception(f"Failed to create parent directory {parent_dir}: {e}")
        
        # Check if ewfacquire is available
        try:
            subprocess.run(['ewfacquire', '--version'], 
                          capture_output=True, check=True, timeout=5)
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise Exception("ewfacquire not found. Please install libewf-tools: sudo apt install libewf-tools")
        
        # Get input file size
        input_size = os.path.getsize(self.input_path)
        if input_size == 0:
            raise Exception("Input file is empty")
        
        self.status.emit(f"Input file size: {self._format_size(input_size)}")
        self.status.emit(f"Starting conversion to E01 format...")
        
        # Prepare output path (remove .e01 extension as ewfacquire adds it)
        base_output_path = self.output_path
        if base_output_path.endswith('.e01'):
            base_output_path = base_output_path[:-4]
        
        # Use ewfacquire to convert image to EWF format
        # -t: target file (without extension)
        # -f: format (ewf)
        # -c: compression level (best)
        cmd = ['ewfacquire', '-t', base_output_path, '-f', 'ewf', '-c', 'best', self.input_path]
        
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, 
                                      stderr=subprocess.STDOUT, 
                                      universal_newlines=True, bufsize=1)
            
            bytes_processed = 0
            for line in process.stdout:
                if self.cancelled:
                    process.terminate()
                    # Clean up partial EWF files
                    base_path = base_output_path
                    for ext in ['.e01', '.e02', '.e03', '.e04', '.e05']:
                        if os.path.exists(base_path + ext):
                            os.remove(base_path + ext)
                    raise Exception("Conversion cancelled by user")
                
                # Parse ewfacquire progress
                if '%' in line:
                    try:
                        # Extract percentage from line like "Progress: 45%"
                        percent_str = line.split('%')[0].split()[-1]
                        progress = int(float(percent_str))
                        self.progress.emit(progress)
                        self.status.emit(f"Converting to E01... {progress}%")
                    except:
                        pass
                elif 'bytes' in line.lower() or 'copied' in line.lower():
                    # Try to extract bytes processed
                    try:
                        parts = line.split()
                        for i, part in enumerate(parts):
                            if part == 'bytes' and i > 0:
                                bytes_processed = int(parts[i-1].replace(',', ''))
                                if input_size > 0:
                                    progress = int((bytes_processed / input_size) * 100)
                                    self.progress.emit(min(progress, 100))
                                    self.status.emit(f"Converting... {self._format_size(bytes_processed)} / {self._format_size(input_size)} ({progress}%)")
                                break
                    except:
                        pass
            
            process.wait()
            if process.returncode != 0:
                raise Exception(f"ewfacquire failed with return code {process.returncode}")
            
            # Final progress update
            self.progress.emit(100)
            self.status.emit(f"Conversion complete. Output: {base_output_path}.e01")
            
        except Exception as e:
            # Clean up partial files
            base_path = base_output_path
            for ext in ['.e01', '.e02', '.e03', '.e04', '.e05']:
                if os.path.exists(base_path + ext):
                    os.remove(base_path + ext)
            raise
    
    def _calculate_hashes(self):
        """Calculate MD5, SHA1, and SHA256 hashes of the converted image."""
        # For E01 files, we need to check all segments
        base_path = self.output_path
        if base_path.endswith('.e01'):
            base_path = base_path[:-4]
        
        # Find all E01 segments
        e01_files = []
        segment_num = 1
        while True:
            segment_path = f"{base_path}.e{segment_num:02d}"
            if os.path.exists(segment_path):
                e01_files.append(segment_path)
                segment_num += 1
            else:
                break
        
        if not e01_files:
            # Fallback to original output path
            e01_files = [self.output_path] if os.path.exists(self.output_path) else []
        
        if not e01_files:
            self.status.emit("Warning: Could not find E01 files for hash calculation")
            return
        
        self.status.emit("Calculating hashes...")
        
        md5_hash = hashlib.md5()
        sha1_hash = hashlib.sha1()
        sha256_hash = hashlib.sha256()
        
        total_size = sum(os.path.getsize(f) for f in e01_files)
        bytes_read = 0
        
        for e01_file in e01_files:
            with open(e01_file, 'rb') as f:
                while True:
                    if self.cancelled:
                        return
                    
                    chunk = f.read(self.block_size)
                    if not chunk:
                        break
                    
                    md5_hash.update(chunk)
                    sha1_hash.update(chunk)
                    sha256_hash.update(chunk)
                    
                    bytes_read += len(chunk)
                    hash_progress = int((bytes_read / total_size) * 100) if total_size > 0 else 0
                    self.hash_progress.emit(f"Calculating hashes... {hash_progress}%")
        
        md5_hex = md5_hash.hexdigest()
        sha1_hex = sha1_hash.hexdigest()
        sha256_hex = sha256_hash.hexdigest()
        
        # Save hashes to a file
        hash_file = base_path + '.hash'
        with open(hash_file, 'w') as f:
            f.write(f"MD5: {md5_hex}\n")
            f.write(f"SHA1: {sha1_hex}\n")
            f.write(f"SHA256: {sha256_hex}\n")
            f.write(f"File: {os.path.basename(base_path)}.e01\n")
            f.write(f"Date: {datetime.now().isoformat()}\n")
        
        self.status.emit(f"Hashes calculated and saved to {hash_file}")
        self.hash_progress.emit(f"MD5: {md5_hex}\nSHA1: {sha1_hex}\nSHA256: {sha256_hex}")
    
    def _format_size(self, size_bytes):
        """Format size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"


class ImageToE01ConversionDialog(QDialog):
    """Dialog for converting disk images to E01 format."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Convert Disk Image to E01")
        self.setMinimumSize(600, 500)
        
        self.conversion_thread = None
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout()
        
        # Input file selection group
        input_group = QGroupBox("Select Input Disk Image")
        input_layout = QFormLayout()
        
        self.input_path_edit = QLineEdit()
        browse_input_btn = QPushButton("Browse...")
        browse_input_btn.clicked.connect(self.browse_input_file)
        
        input_path_layout = QHBoxLayout()
        input_path_layout.addWidget(self.input_path_edit)
        input_path_layout.addWidget(browse_input_btn)
        
        input_layout.addRow("Input File:", input_path_layout)
        input_group.setLayout(input_layout)
        layout.addWidget(input_group)
        
        # Output settings group
        output_group = QGroupBox("Output Settings")
        output_layout = QFormLayout()
        
        self.output_path_edit = QLineEdit()
        browse_output_btn = QPushButton("Browse...")
        browse_output_btn.clicked.connect(self.browse_output_path)
        
        output_path_layout = QHBoxLayout()
        output_path_layout.addWidget(self.output_path_edit)
        output_path_layout.addWidget(browse_output_btn)
        
        self.hash_checkbox = QCheckBox("Calculate MD5, SHA1, SHA256 hashes")
        self.hash_checkbox.setChecked(True)
        
        output_layout.addRow("Output Path:", output_path_layout)
        output_layout.addRow("", self.hash_checkbox)
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)
        
        # Progress group
        progress_group = QGroupBox("Conversion Progress")
        progress_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(150)
        
        progress_layout.addWidget(QLabel("Progress:"))
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(QLabel("Status:"))
        progress_layout.addWidget(self.status_text)
        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Conversion")
        self.start_btn.clicked.connect(self.start_conversion)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_conversion)
        self.cancel_btn.setEnabled(False)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(self.cancel_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.close_btn)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def browse_input_file(self):
        """Browse for input disk image file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Disk Image File", 
            os.path.expanduser("~"),
            "Disk Image Files (*.dd *.raw *.img);;All Files (*)"
        )
        
        if file_path:
            self.input_path_edit.setText(file_path)
            # Auto-suggest output path
            if not self.output_path_edit.text():
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                output_dir = os.path.dirname(file_path)
                suggested_path = os.path.join(output_dir, base_name + ".e01")
                self.output_path_edit.setText(suggested_path)
    
    def browse_output_path(self):
        """Browse for output E01 file path."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save E01 Image As", 
            os.path.expanduser("~/Desktop"),
            "EWF Image Files (*.e01);;All Files (*)"
        )
        
        if file_path:
            # Ensure it has .e01 extension
            if not file_path.endswith('.e01'):
                file_path += '.e01'
            self.output_path_edit.setText(file_path)
    
    def start_conversion(self):
        """Start the conversion process."""
        input_path = self.input_path_edit.text().strip()
        if not input_path:
            QMessageBox.warning(self, "No Input File", "Please select an input disk image file.")
            return
        
        if not os.path.exists(input_path):
            QMessageBox.warning(self, "File Not Found", f"The input file does not exist:\n{input_path}")
            return
        
        if not os.path.isfile(input_path):
            QMessageBox.warning(self, "Invalid Input", f"The input path is not a file:\n{input_path}")
            return
        
        output_path = self.output_path_edit.text().strip()
        if not output_path:
            QMessageBox.warning(self, "No Output Path", "Please specify an output file path.")
            return
        
        # Normalize the path
        output_path = os.path.normpath(output_path)
        
        # Expand user path if it starts with ~
        if output_path.startswith('~'):
            output_path = os.path.expanduser(output_path)
        
        # Resolve relative paths
        if not os.path.isabs(output_path):
            output_path = os.path.abspath(output_path)
        
        # Check if output path is a directory
        if os.path.isdir(output_path):
            QMessageBox.warning(
                self, "Invalid Output Path", 
                f"The specified path is a directory, not a file:\n{output_path}\n\n"
                f"Please specify a file path (e.g., {output_path}/image.e01)"
            )
            return
        
        # Ensure the output path has .e01 extension
        if not output_path.endswith('.e01'):
            output_path += '.e01'
        
        # Create parent directory if it doesn't exist
        parent_dir = os.path.dirname(output_path)
        if parent_dir and not os.path.exists(parent_dir):
            try:
                os.makedirs(parent_dir, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(
                    self, "Error Creating Directory",
                    f"Failed to create output directory:\n{parent_dir}\n\nError: {e}"
                )
                return
        
        # Check if output file already exists
        base_output_path = output_path[:-4] if output_path.endswith('.e01') else output_path
        if os.path.exists(base_output_path + '.e01'):
            reply = QMessageBox.question(
                self, "File Exists", 
                f"The file {base_output_path}.e01 already exists. Overwrite?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        # Update the output path edit with the validated path
        self.output_path_edit.setText(output_path)
        
        # Get input file size for confirmation
        input_size = os.path.getsize(input_path)
        input_size_str = self._format_size(input_size)
        
        # Confirm before starting
        reply = QMessageBox.warning(
            self, "Confirm Conversion",
            f"Convert disk image to E01 format?\n\n"
            f"Input: {os.path.basename(input_path)} ({input_size_str})\n"
            f"Output: {os.path.basename(output_path)}\n\n"
            f"This process may take a long time depending on file size.\n\n"
            f"Continue?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.No:
            return
        
        # Disable start button, enable cancel button
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_text.clear()
        
        # Start conversion thread
        calculate_hash = self.hash_checkbox.isChecked()
        self.conversion_thread = ImageToE01ConversionThread(
            input_path, output_path, calculate_hash
        )
        self.conversion_thread.progress.connect(self.progress_bar.setValue)
        self.conversion_thread.status.connect(self.status_text.append)
        self.conversion_thread.hash_progress.connect(self.status_text.append)
        self.conversion_thread.finished.connect(self.conversion_finished)
        self.conversion_thread.start()
    
    def cancel_conversion(self):
        """Cancel the ongoing conversion."""
        if self.conversion_thread and self.conversion_thread.isRunning():
            reply = QMessageBox.question(
                self, "Cancel Conversion",
                "Are you sure you want to cancel the conversion?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.conversion_thread.cancel()
                self.status_text.append("Conversion cancelled by user...")
    
    def conversion_finished(self, success, message):
        """Handle conversion completion."""
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        
        if success:
            QMessageBox.information(self, "Conversion Complete", message)
        else:
            QMessageBox.critical(self, "Conversion Failed", message)
        
        self.status_text.append(message)
    
    def _format_size(self, size_bytes):
        """Format size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"

