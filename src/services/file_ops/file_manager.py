"""File Operations — read | write | download_via_curl | upload_via_curl | extract_zip | list"""
import base64, os, subprocess, zipfile
from typing import Any, Dict, List
from src.core.config import FILES_DIR


class FileManager:
    def __init__(self, workspace_id: str):
        self.dir = os.path.join(FILES_DIR, workspace_id)
        os.makedirs(self.dir, exist_ok=True)

    async def execute(self, action: str, args: Dict) -> Any:
        return await {"read": self._read, "write": self._write, "download_via_curl": self._download,
                      "upload_via_curl": self._upload, "extract_zip": self._extract, "list": self._list}[action](args)

    async def _read(self, a):
        with open(os.path.join(self.dir, a["filename"]), "r", errors="replace") as f:
            f.seek(a.get("offset_chars",0)); c = f.read(a.get("max_chars",50000))
        return {"content": c, "truncated": len(c) == a.get("max_chars",50000)}

    async def _write(self, a):
        p = os.path.join(self.dir, a["filename"])
        if a.get("encoding") == "base64":
            with open(p, "wb") as f: f.write(base64.b64decode(a["content"]))
        else:
            with open(p, "w") as f: f.write(a["content"])
        return {"filename": a["filename"], "status": "written"}

    async def _download(self, a):
        p = os.path.join(self.dir, a["filename"])
        subprocess.run(f'curl -o "{p}" {a.get("curl_args","")} "{a["url"]}"', shell=True, check=True, timeout=120)
        return {"filename": a["filename"], "status": "downloaded"}

    async def _upload(self, a):
        p = os.path.join(self.dir, a["filename"])
        r = subprocess.run(f'curl {a.get("curl_args","")} -F "file=@{p}" "{a["url"]}"', shell=True, capture_output=True, timeout=120)
        return {"status": "uploaded", "response": r.stdout.decode()}

    async def _extract(self, a):
        p = os.path.join(self.dir, a["filename"])
        with zipfile.ZipFile(p) as z: z.extractall(self.dir); return {"extracted": z.namelist()}

    async def _list(self, a): return os.listdir(self.dir)
