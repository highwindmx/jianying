"""MinerU OCR 客户端：上传截图 → 轮询结果 → 下载 zip → 提取 Markdown 文本。

API 文档: https://mineru.net/apiManage  (v4 batch 接口)
"""
from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import requests
from PyQt6.QtCore import QThread, pyqtSignal

from jianying import config


class MineruWorker(QThread):
    finished_text = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, image_path: Path, parent=None):
        super().__init__(parent)
        self._path = Path(image_path)

    def run(self) -> None:
        try:
            text = self._ocr()
            self.finished_text.emit(text)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))

    def _ocr(self) -> str:
        token = config.MINERU_API_TOKEN
        base = config.MINERU_API_BASE.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"}

        # 1) 申请上传链接
        r = requests.post(
            f"{base}/file-urls/batch",
            headers=headers,
            json={
                "enable_ocr": True,
                "files": [{"name": self._path.name, "is_ocr": True}],
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"MinerU 下单失败: {data.get('msg')}")
        batch_id = data["data"]["batch_id"]
        upload_url = data["data"]["file_urls"][0]

        # 2) PUT 上传
        put = requests.put(upload_url, data=self._path.read_bytes(), timeout=120)
        put.raise_for_status()

        # 3) 轮询结果（最多 120s）
        result_url = None
        for _ in range(40):
            time.sleep(3)
            r = requests.get(
                f"{base}/extract-results/batch/{batch_id}",
                headers=headers, timeout=30,
            )
            r.raise_for_status()
            j = r.json()
            if j.get("code") != 0:
                raise RuntimeError(f"MinerU 轮询失败: {j.get('msg')}")
            item = j["data"]["extract_result"][0]
            state = item.get("state")
            if state == "done":
                result_url = item.get("full_zip_url")
                break
            if state == "failed":
                raise RuntimeError(f"MinerU 解析失败: {item.get('err_msg')}")

        if not result_url:
            raise RuntimeError("OCR 超时（>120s），请稍后重试")

        # 4) 下载 zip，提取 .md
        zr = requests.get(result_url, timeout=120)
        zr.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(zr.content)) as zf:
            mds = [n for n in zf.namelist() if n.endswith(".md")]
            if not mds:
                raise RuntimeError("结果包内未找到 Markdown")
            return zf.read(mds[0]).decode("utf-8", errors="replace")
