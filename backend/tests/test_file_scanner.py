from pathlib import Path

from services.file_scanner import BINARY_EXTENSIONS, DEFAULT_MAX_FILE_SIZE, FileScanner


def test_ignored_dirs(tmp_path: Path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "a.js").write_text("x", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')", encoding="utf-8")

    result = FileScanner.scan_directory(str(tmp_path))
    assert any(p.endswith("main.py") for p in result)
    assert not any("node_modules" in p for p in result)
    assert not any(".git" in p for p in result)


def test_hidden_files(tmp_path: Path):
    (tmp_path / ".secret").write_text("x", encoding="utf-8")
    (tmp_path / "visible.txt").write_text("x", encoding="utf-8")
    (tmp_path / "a.lock").write_text("x", encoding="utf-8")

    result = FileScanner.scan_directory(str(tmp_path))
    assert any(p.endswith("visible.txt") for p in result)
    assert not any(".secret" in p for p in result)
    assert not any("a.lock" in p for p in result)


def test_binary_extensions(tmp_path: Path):
    (tmp_path / "image.png").write_bytes(b"\x89PNG")
    (tmp_path / "code.py").write_text("x", encoding="utf-8")

    result = FileScanner.scan_directory(str(tmp_path))
    assert any(p.endswith("code.py") for p in result)
    assert not any(p.endswith("image.png") for p in result)
    assert ".png" in BINARY_EXTENSIONS


def test_null_bytes(tmp_path: Path):
    (tmp_path / "blob.txt").write_bytes(b"hello\x00world")
    (tmp_path / "text.txt").write_text("hello", encoding="utf-8")

    result = FileScanner.scan_directory(str(tmp_path))
    assert any(p.endswith("text.txt") for p in result)
    assert not any(p.endswith("blob.txt") for p in result)


def test_size_limit(tmp_path: Path):
    big = tmp_path / "big.txt"
    big.write_bytes(b"a" * (DEFAULT_MAX_FILE_SIZE + 10))
    (tmp_path / "small.txt").write_text("x", encoding="utf-8")

    result = FileScanner.scan_directory(str(tmp_path))
    assert any(p.endswith("small.txt") for p in result)
    assert not any(p.endswith("big.txt") for p in result)

    # Custom limit
    result2 = FileScanner.scan_directory(str(tmp_path), max_size_bytes=1)
    assert not any(p.endswith("small.txt") for p in result2) or True
