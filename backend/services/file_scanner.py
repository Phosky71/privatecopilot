import os

IGNORE_DIRS = {".git", "node_modules", "venv", "dist", "build", "__pycache__", "chroma_db"}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".tar",
    ".gz", ".exe", ".dll", ".so", ".dylib", ".sqlite", ".db", ".pyc", ".woff",
    ".woff2", ".ttf", ".eot", ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".bin",
    ".dat", ".class", ".jar", ".war", ".o", ".a", ".lib",
}

DEFAULT_MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB


class FileScanner:
    @staticmethod
    def scan_directory(directory: str, max_size_bytes: int = DEFAULT_MAX_FILE_SIZE) -> list[str]:
        file_paths = []
        for root, dirs, files in os.walk(directory):
            # Modify dirs in-place to skip ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]

            for file in files:
                # Skip hidden files or lock files
                if file.startswith('.') or file.endswith('.lock'):
                    continue

                ext = os.path.splitext(file)[1].lower()
                if ext in BINARY_EXTENSIONS:
                    continue

                full_path = os.path.join(root, file)

                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    continue
                if size > max_size_bytes:
                    continue

                # Quick binary check: read a small chunk and look for null bytes.
                try:
                    with open(full_path, "rb") as f:
                        chunk = f.read(8192)
                    if b"\x00" in chunk:
                        continue
                except OSError:
                    continue

                file_paths.append(full_path)
        return file_paths
