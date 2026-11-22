import os
import platform

from core.logging_config import logger
from fastapi import APIRouter, HTTPException

router = APIRouter()

@router.get("/list")
def list_fs(path: str = ""):
    try:
        items = []
        # Handle root / drives
        if path == "" or path == "/":
            if platform.system() == "Windows":
                import string
                drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
                for d in drives:
                    items.append({"name": d, "path": d.replace("\\", "/"), "is_dir": True})
                return {"path": "", "items": items}
            else:
                path = "/"
                
        if not os.path.exists(path):
            raise HTTPException(status_code=404, detail="Path not found")
            
        if not os.path.isdir(path):
            raise HTTPException(status_code=400, detail="Path is not a directory")
            
        for name in os.listdir(path):
            try:
                full_path = os.path.join(path, name)
                is_dir = os.path.isdir(full_path)
                items.append({
                    "name": name,
                    "path": full_path.replace("\\", "/"),
                    "is_dir": is_dir
                })
            except PermissionError as e:
                logger.warning("Permission denied listing %s: %s", full_path, e)
            except OSError as e:
                logger.warning("OS error listing %s: %s", full_path, e)
                
        # Sort directories first, then alphabetically
        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        return {"path": path.replace("\\", "/"), "items": items}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))
