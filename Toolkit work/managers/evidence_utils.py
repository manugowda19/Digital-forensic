

import hashlib
import os
import datetime
from Registry import Registry
import pyewf
import pytsk3
import tempfile

SECTOR_SIZE = 512  # 512 bytes per sector
# Optimized buffer sizes for faster reading
READ_BUFFER_SIZE = 1024 * 1024  # 1MB buffer for regular reads
LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10MB - use chunked reading for larger files
CHUNK_SIZE = 8 * 1024 * 1024  # 8MB chunks for large files


# Class to handle EWF images
class EWFImgInfo(pytsk3.Img_Info):
    def __init__(self, ewf_handle):
        self._ewf_handle = ewf_handle
        self._last_offset = -1  # Cache last offset to avoid unnecessary seeks
        super(EWFImgInfo, self).__init__(url="", type=pytsk3.TSK_IMG_TYPE_EXTERNAL)

    def close(self):
        self._ewf_handle.close()

    def read(self, offset, size):
        # Only seek if offset changed (optimization to reduce seek calls)
        if self._last_offset != offset:
            self._ewf_handle.seek(offset)
            self._last_offset = offset
        
        # Use optimized buffer size for large reads
        if size > READ_BUFFER_SIZE:
            # For large reads, read in chunks to avoid memory issues
            data = bytearray()
            remaining = size
            current_offset = offset
            while remaining > 0:
                chunk_size = min(remaining, READ_BUFFER_SIZE)
                self._ewf_handle.seek(current_offset)
                chunk = self._ewf_handle.read(chunk_size)
                if not chunk:
                    break
                data.extend(chunk)
                remaining -= len(chunk)
                current_offset += len(chunk)
            self._last_offset = current_offset
            return bytes(data)
        else:
            data = self._ewf_handle.read(size)
            self._last_offset = offset + len(data) if data else offset
            return data

    def get_size(self):
        return self._ewf_handle.get_media_size()


class ImageHandler:
    def __init__(self, image_path):
        self.image_path = image_path  # Path to the image
        self.img_info = None  # Initialized once
        self.volume_info = None  # Initialized lazily
        self._volume_info_loaded = False  # Track if volume_info has been loaded
        self.fs_info_cache = {}  # Cache for FS_Info objects, keyed by start offset
        self.file_metadata_cache = {}  # Cache for file metadata to avoid re-traversing
        self.directory_cache = {}  # Cache for directory contents

        self.fs_info = None  # Added to check for direct filesystem
        self.is_wiped_image = False  # Indicator if image is wiped

        # Only load basic image info, defer volume_info loading
        self._load_basic_image_info()

    def get_size(self):
        """Returns the size of the disk image."""
        if isinstance(self.img_info, EWFImgInfo):
            return self.img_info.get_size()
        elif isinstance(self.img_info, pytsk3.Img_Info):
            return self.img_info.get_size()
        else:
            raise AttributeError("Unsupported image format for size retrieval.")

    def read(self, offset, size):
        """Reads data from the image starting at `offset` for `size` bytes."""
        if hasattr(self.img_info, 'read'):
            # This will work directly for both EWFImgInfo and pytsk3.Img_Info instances
            return self.img_info.read(offset, size)
        else:
            raise NotImplementedError("The image format does not support direct reading.")

    def get_image_type(self):
        """Determine the type of the image based on its extension."""
        _, extension = os.path.splitext(self.image_path)
        extension = extension.lower()

        ewf = [".e01", ".s01", ".l01", ".ex01"]
        raw = [".raw", ".img", ".dd", ".iso",
               ".ad1", ".001", ".dmg", ".sparse",
               ".sparseimage"]

        if extension in ewf:
            return "ewf"
        elif extension in raw:
            return "raw"
        else:
            raise ValueError(f"Unsupported image type: {extension}")

    def calculate_hashes(self):
        """Calculate the MD5, SHA1, and SHA256 hashes for the image with optimized reading."""
        hash_md5 = hashlib.md5()
        hash_sha1 = hashlib.sha1()
        hash_sha256 = hashlib.sha256()
        size = 0
        stored_md5, stored_sha1 = None, None

        image_type = self.get_image_type()
        if image_type == "ewf":
            filenames = pyewf.glob(self.image_path)
            ewf_handle = pyewf.handle()
            ewf_handle.open(filenames)
            try:
                # Attempt to retrieve the stored hash values
                stored_md5 = ewf_handle.get_hash_value("MD5")
                stored_sha1 = ewf_handle.get_hash_value("SHA1")
            except Exception as e:
                pass  # Silently skip if hash values not available

            # Calculate the hash values by reading the image file with larger buffer
            while True:
                chunk = ewf_handle.read(READ_BUFFER_SIZE)  # Use larger buffer for faster hashing
                if not chunk:
                    break
                hash_md5.update(chunk)
                hash_sha1.update(chunk)
                hash_sha256.update(chunk)
                size += len(chunk)
            ewf_handle.close()
        elif image_type == "raw":
            with open(self.image_path, "rb") as f:
                for chunk in iter(lambda: f.read(READ_BUFFER_SIZE), b""):  # Use larger buffer
                    hash_md5.update(chunk)
                    hash_sha1.update(chunk)
                    hash_sha256.update(chunk)
                    size += len(chunk)

        # Compile the computed and stored hashes in a dictionary
        hashes = {
            'computed_md5': hash_md5.hexdigest(),
            'computed_sha1': hash_sha1.hexdigest(),
            'computed_sha256': hash_sha256.hexdigest(),
            'size': size,
            'path': self.image_path,
            'stored_md5': stored_md5,
            'stored_sha1': stored_sha1
        }

        return hashes

    def _load_basic_image_info(self):
        """Load only basic image info without volume_info for faster initial loading."""
        image_type = self.get_image_type()
        if image_type == "ewf":
            filenames = pyewf.glob(self.image_path)
            ewf_handle = pyewf.handle()
            ewf_handle.open(filenames)
            self.img_info = EWFImgInfo(ewf_handle)
        elif image_type == "raw":
            self.img_info = pytsk3.Img_Info(self.image_path)
        else:
            raise ValueError(f"Unsupported image type: {image_type}")

    def _ensure_volume_info_loaded(self):
        """Lazily load volume_info only when needed."""
        if self._volume_info_loaded:
            return
        
        try:
            self.volume_info = pytsk3.Volume_Info(self.img_info)
        except Exception:
            self.volume_info = None
            # Attempt to detect a filesystem directly if no volume info
            try:
                self.fs_info = pytsk3.FS_Info(self.img_info)
            except Exception:
                self.fs_info = None
                # If no volume info and no filesystem, mark as wiped
                self.is_wiped_image = True
        
        self._volume_info_loaded = True

    def load_image(self):
        """Load the image and retrieve volume and filesystem information (for compatibility)."""
        if not self.img_info:
            self._load_basic_image_info()
        self._ensure_volume_info_loaded()

    def has_filesystem(self, start_offset):
        fs_info = self.get_fs_info(start_offset)
        return fs_info is not None

    def is_wiped(self):
        # Image is considered wiped if no volume info, no filesystem detected
        return self.is_wiped_image

    def get_partitions(self):
        """Retrieve partitions from the loaded image, or indicate unpartitioned space."""
        # Lazy load volume_info only when partitions are requested
        self._ensure_volume_info_loaded()
        
        partitions = []
        if self.volume_info:
            for partition in self.volume_info:
                if not partition.desc:
                    continue
                partitions.append((partition.addr, partition.desc, partition.start, partition.len))
        elif self.is_wiped():
            # For a wiped image with no partitions, return a placeholder for unallocated space
            # This is a simplified representation.
            # total_size = self.get_size()
            # partitions.append((0, "Unallocated Space", 0, total_size // SECTOR_SIZE))
            # don't do nothing
            pass
        return partitions

    def get_fs_info(self, start_offset):
        """Retrieve the FS_Info for a partition, initializing it if necessary."""
        if start_offset not in self.fs_info_cache:
            try:
                fs_info = pytsk3.FS_Info(self.img_info, offset=start_offset * 512)
                self.fs_info_cache[start_offset] = fs_info
            except Exception as e:
                return None
        return self.fs_info_cache[start_offset]

    def get_fs_type(self, start_offset):
        """Retrieve the file system type for a partition (lazy loaded)."""
        try:
            fs_info = self.get_fs_info(start_offset)
            if not fs_info:
                return "N/A"
            
            fs_type = fs_info.info.ftype

            # Map the file system type to its name
            if fs_type == pytsk3.TSK_FS_TYPE_NTFS:
                return "NTFS"
            elif fs_type == pytsk3.TSK_FS_TYPE_FAT12:
                return "FAT12"
            elif fs_type == pytsk3.TSK_FS_TYPE_FAT16:
                return "FAT16"
            elif fs_type == pytsk3.TSK_FS_TYPE_FAT32:
                return "FAT32"
            elif fs_type == pytsk3.TSK_FS_TYPE_EXFAT:
                return "ExFAT"
            elif fs_type == pytsk3.TSK_FS_TYPE_EXT2:
                return "Ext2"
            elif fs_type == pytsk3.TSK_FS_TYPE_EXT3:
                return "Ext3"
            elif fs_type == pytsk3.TSK_FS_TYPE_EXT4:
                return "Ext4"
            elif fs_type == pytsk3.TSK_FS_TYPE_ISO9660:
                return "ISO9660"
            elif fs_type == pytsk3.TSK_FS_TYPE_HFS:
                return "HFS"
            elif fs_type == pytsk3.TSK_FS_TYPE_APFS:
                return "APFS"
            else:
                return "Unknown"
        except Exception:
            return "N/A"

    def check_partition_contents(self, partition_start_offset):
        """Check if a partition has any files or folders."""
        fs = self.get_fs_info(partition_start_offset)
        if fs:
            try:
                root_dir = fs.open_dir(path="/")
                for _ in root_dir:
                    return True
                return False
            except:
                return False
        return False

    def get_directory_contents(self, start_offset, inode_number=None):
        """Optimized directory reading with caching and better error handling."""
        # Check cache first
        cache_key = (start_offset, inode_number)
        if cache_key in self.directory_cache:
            return self.directory_cache[cache_key]
        
        fs = self.get_fs_info(start_offset)
        if fs:
            try:
                directory = fs.open_dir(inode=inode_number) if inode_number else fs.open_dir(path="/")
                entries = []
                
                # Use try-except per entry to skip problematic entries faster
                for entry in directory:
                    try:
                        if entry.info.name.name not in [b".", b".."]:
                            is_directory = False
                            if entry.info.meta and entry.info.meta.type == pytsk3.TSK_FS_META_TYPE_DIR:
                                is_directory = True

                            def safe_datetime(timestamp):
                                if timestamp is None or timestamp == 0:
                                    return "N/A"
                                try:
                                    return datetime.datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S') + " UTC"
                                except Exception:
                                    return "N/A"

                            entries.append({
                                "name": entry.info.name.name.decode('utf-8', errors='ignore') if hasattr(entry.info.name, 'name') else None,
                                "is_directory": is_directory,
                                "inode_number": entry.info.meta.addr if entry.info.meta else None,
                                "size": entry.info.meta.size if entry.info.meta and entry.info.meta.size is not None else 0,
                                "accessed": safe_datetime(entry.info.meta.atime) if hasattr(entry.info.meta, 'atime') else "N/A",
                                "modified": safe_datetime(entry.info.meta.mtime) if hasattr(entry.info.meta, 'mtime') else "N/A",
                                "created": safe_datetime(entry.info.meta.crtime) if hasattr(entry.info.meta, 'crtime') else "N/A",
                                "changed": safe_datetime(entry.info.meta.ctime) if hasattr(entry.info.meta, 'ctime') else "N/A",
                            })
                    except Exception:
                        # Skip problematic entries silently to avoid slowing down
                        continue
                
                # Cache the results
                self.directory_cache[cache_key] = entries
                return entries

            except Exception as e:
                # Log only critical errors, skip others silently
                return []
        return []

    def get_registry_hive(self, fs_info, hive_path):
        """Extract a registry hive from the given filesystem with optimized reading."""
        try:
            registry_file = fs_info.open(hive_path)
            file_size = registry_file.info.meta.size
            
            # Use chunked reading for large registry files
            if file_size > LARGE_FILE_THRESHOLD:
                hive_data = bytearray()
                remaining = file_size
                current_offset = 0
                
                while remaining > 0:
                    chunk_size = min(remaining, CHUNK_SIZE)
                    chunk = registry_file.read_random(current_offset, chunk_size)
                    if not chunk:
                        break
                    hive_data.extend(chunk)
                    remaining -= len(chunk)
                    current_offset += len(chunk)
                
                return bytes(hive_data)
            else:
                # For smaller files, read all at once
                return registry_file.read_random(0, file_size)
        except Exception as e:
            return None

    def get_windows_version(self, start_offset):
        """Get the Windows version from the SOFTWARE registry hive."""
        fs_info = self.get_fs_info(start_offset)
        if not fs_info:
            return None

        # if file system is not ntfs, return unknown OS and exit the function
        if self.get_fs_type(start_offset) != "NTFS":
            return None

        software_hive_data = self.get_registry_hive(fs_info, "/Windows/System32/config/SOFTWARE")

        if not software_hive_data:
            return None

        # Create a temporary file and store the hive data
        temp_hive_path = None
        try:
            with tempfile.NamedTemporaryFile(
                    delete=False) as temp_hive:  # Create a temporary file and store the hive data
                temp_hive.write(software_hive_data)  # Write the hive data to the temporary file
                temp_hive_path = temp_hive.name  # Get the path of the temporary file

            if temp_hive_path:
                reg = Registry.Registry(temp_hive_path)
                key = reg.open("Microsoft\\Windows NT\\CurrentVersion")

                # Helper function to safely get registry values
                def get_reg_value(reg_key, value_name):
                    try:
                        return reg_key.value(value_name).value()
                    except Registry.RegistryValueNotFoundException:
                        return "N/A"

                # Fetching registry values
                product_name = get_reg_value(key, "ProductName")
                current_version = get_reg_value(key, "CurrentVersion")
                current_build = get_reg_value(key, "CurrentBuild")
                registered_owner = get_reg_value(key, "RegisteredOwner")
                csd_version = get_reg_value(key, "CSDVersion")
                product_id = get_reg_value(key, "ProductId")

                os_version = f"{product_name} Version {current_version}\nBuild {current_build} {csd_version}\nOwner: {registered_owner}\nProduct ID: {product_id}"
            else:
                os_version = "Failed to create temporary hive file"

            # Clean up the temporary file
            if temp_hive_path and os.path.exists(temp_hive_path):
                os.remove(temp_hive_path)

            return os_version

        except Exception as e:
            print(f"Error parsing SOFTWARE hive: {e}")
            return "Error in parsing OS version"

    def read_unallocated_space(self, start_offset, end_offset):
        try:
            start_byte_offset = start_offset * SECTOR_SIZE
            end_byte_offset = max(end_offset * SECTOR_SIZE, start_byte_offset + SECTOR_SIZE - 1)
            size_in_bytes = end_byte_offset - start_byte_offset + 1  # Ensuring at least some data is read

            if size_in_bytes <= 0:
                print("Invalid size for unallocated space, adjusting to read at least one sector.")
                size_in_bytes = SECTOR_SIZE  # Adjust to read at least one sector

            unallocated_space = self.img_info.read(start_byte_offset, size_in_bytes)
            if unallocated_space is None or len(unallocated_space) == 0:
                print(f"Failed to read unallocated space from offset {start_byte_offset} to {end_byte_offset}")
                return None

            return unallocated_space
        except Exception as e:
            print(f"Error reading unallocated space: {e}")
            return None

    def open_image(self):
        if self.get_image_type() == "ewf":
            filenames = pyewf.glob(self.image_path)
            ewf_handle = pyewf.handle()
            ewf_handle.open(filenames)
            return EWFImgInfo(ewf_handle)
        else:
            return pytsk3.Img_Info(self.image_path)


    def list_files(self, extensions=None):
        files_list = []

        img_info = self.open_image()
        try:
            volume_info = pytsk3.Volume_Info(img_info)
            for partition in volume_info:
                if partition.flags == pytsk3.TSK_VS_PART_FLAG_ALLOC:
                    self.process_partition(img_info, partition.start * SECTOR_SIZE, files_list, extensions)
        except IOError:
            self.process_partition(img_info, 0, files_list, extensions)

        return files_list

    def process_partition(self, img_info, offset, files_list, extensions):
        try:
            fs_info = pytsk3.FS_Info(img_info, offset=offset)
            self.recursive_file_search(fs_info, fs_info.open_dir(path="/"), "/", files_list, extensions)
        except IOError as e:
            print(f"Unable to open filesystem at offset {offset}: {e}")


    def recursive_file_search(self, fs_info, directory, parent_path, files_list, extensions, search_query=None):
        """Optimized recursive file search with better error handling."""
        for entry in directory:
            try:
                if entry.info.name.name in [b".", b".."]:
                    continue

                file_name = entry.info.name.name.decode("utf-8", errors='ignore')
                file_extension = os.path.splitext(file_name)[1].lower()

                if search_query:
                    # If there's a search query, check if the file name contains the query
                    if search_query.startswith('.'):
                        # If the search query is an extension (e.g., '.jpg')
                        query_matches = file_extension == search_query.lower()
                    else:
                        # If the search query is a file name or part of it
                        query_matches = search_query.lower() in file_name.lower()
                else:
                    # If no search query, handle as before based on extensions
                    query_matches = extensions is None or file_extension in extensions or '' in extensions

                if entry.info.meta and entry.info.meta.type == pytsk3.TSK_FS_META_TYPE_DIR:
                    try:
                        sub_directory = fs_info.open_dir(inode=entry.info.meta.addr)
                        self.recursive_file_search(fs_info, sub_directory, os.path.join(parent_path, file_name), files_list,
                                                   extensions, search_query)
                    except (IOError, Exception):
                        # Skip problematic directories silently to avoid slowing down
                        continue

                elif entry.info.meta and entry.info.meta.type == pytsk3.TSK_FS_META_TYPE_REG and query_matches:
                    file_info = self.get_file_metadata(entry, parent_path)
                    files_list.append(file_info)
            except Exception:
                # Skip problematic entries silently to avoid slowing down
                continue

    def get_file_metadata(self, entry, parent_path):
        def safe_datetime(timestamp):
            if timestamp is None:
                return "N/A"
            try:
                return datetime.datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                return "N/A"

        file_name = entry.info.name.name.decode("utf-8")
        return {
            "name": file_name,
            "path": os.path.join(parent_path, file_name),
            "size": entry.info.meta.size,
            "accessed": safe_datetime(entry.info.meta.atime),
            "modified": safe_datetime(entry.info.meta.mtime),
            "created": safe_datetime(entry.info.meta.crtime) if hasattr(entry.info.meta, 'crtime') else "N/A",
            "changed": safe_datetime(entry.info.meta.ctime),
            "inode_item": str(entry.info.meta.addr),
        }


    def search_files(self, search_query=None):
        files_list = []
        img_info = self.open_image()

        try:
            volume_info = pytsk3.Volume_Info(img_info)
            for partition in volume_info:
                if partition.flags == pytsk3.TSK_VS_PART_FLAG_ALLOC:
                    self.process_partition_search(img_info, partition.start * SECTOR_SIZE, files_list, search_query)
        except IOError:
            # No volume information, attempt to read as a single filesystem
            self.process_partition_search(img_info, 0, files_list, search_query)

        return files_list

    def process_partition_search(self, img_info, offset, files_list, search_query):
        try:
            fs_info = pytsk3.FS_Info(img_info, offset=offset)
            self.recursive_file_search(fs_info, fs_info.open_dir(path="/"), "/", files_list, None, search_query)
        except IOError as e:
            print(f"Unable to open file system for search: {e}")


    def get_file_content(self, inode_number, offset):
        """Optimized file reading with chunked reading for large files."""
        fs = self.get_fs_info(offset)
        if not fs:
            return None, None

        try:
            file_obj = fs.open_meta(inode=inode_number)
            if file_obj.info.meta.size == 0:
                return None, None

            file_size = file_obj.info.meta.size
            metadata = file_obj.info.meta

            # Use chunked reading for large files to avoid memory issues and improve performance
            if file_size > LARGE_FILE_THRESHOLD:
                # Read in chunks for large files
                content = bytearray()
                remaining = file_size
                current_offset = 0
                
                while remaining > 0:
                    chunk_size = min(remaining, CHUNK_SIZE)
                    chunk = file_obj.read_random(current_offset, chunk_size)
                    if not chunk:
                        break
                    content.extend(chunk)
                    remaining -= len(chunk)
                    current_offset += len(chunk)
                
                return bytes(content), metadata
            else:
                # For smaller files, read all at once (faster for small files)
                content = file_obj.read_random(0, file_size)
                return content, metadata

        except Exception as e:
            # Silently skip problematic files to avoid slowing down the process
            return None, None



    def clear_cache(self):
        """Clear all caches to free memory or force refresh."""
        self.directory_cache.clear()
        self.file_metadata_cache.clear()
        # Note: fs_info_cache is kept as it's expensive to recreate

    @staticmethod
    def get_readable_size(size_in_bytes):
        """Convert bytes to a human-readable string (e.g., KB, MB, GB, TB)."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_in_bytes < 1024.0:
                return f"{size_in_bytes:.2f} {unit}"
            size_in_bytes /= 1024.0

