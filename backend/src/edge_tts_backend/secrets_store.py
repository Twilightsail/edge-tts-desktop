"""Azure 凭据的本机加密保存。

Windows 上使用 DPAPI（CryptProtectData，当前用户范围）：密文只能由同一个 Windows 用户解开，
数据库文件被复制到别处也无法还原。其他系统没有等价的内置机制，只做 base64 编码并在文档中说明。
密钥永远不会出现在日志、接口响应或任务数据里；对外只提供末 4 位提示。
"""

import base64
import ctypes
import os
import re
from ctypes import wintypes

_ENTROPY = b"edge-tts-desktop/azure-key/v1"
_CACHE_KEY = "azure"

KEY_PATTERN = re.compile(r"^[A-Za-z0-9]{16,128}$")
REGION_PATTERN = re.compile(r"^[a-z0-9]{3,30}$")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _dpapi(protect: bool, data: bytes) -> bytes:
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    function.restype = wintypes.BOOL
    function.argtypes = [
        ctypes.POINTER(_Blob),
        wintypes.LPCWSTR if protect else ctypes.c_void_p,
        ctypes.POINTER(_Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_Blob),
    ]
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    source, keep_source = _blob(data)
    entropy, keep_entropy = _blob(_ENTROPY)
    output = _Blob()
    args = [ctypes.byref(source), "EdgeTTSDesktop" if protect else None, ctypes.byref(entropy)]
    if not function(*args, None, None, 0, ctypes.byref(output)):
        raise OSError("DPAPI 调用失败")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)
        del keep_source, keep_entropy


def protect(text: str) -> str:
    raw = text.encode("utf-8")
    if os.name == "nt":
        return "dpapi:" + base64.b64encode(_dpapi(True, raw)).decode("ascii")
    return "plain:" + base64.b64encode(raw).decode("ascii")


def unprotect(token: str) -> str:
    scheme, _, payload = token.partition(":")
    raw = base64.b64decode(payload)
    if scheme == "dpapi":
        if os.name != "nt":
            raise OSError("该密钥由 Windows 加密，无法在当前系统读取")
        return _dpapi(False, raw).decode("utf-8")
    if scheme == "plain":
        return raw.decode("utf-8")
    raise ValueError("未知的密钥保存格式")


class AzureCredentials:
    """读写 Azure 区域与密钥；存放在应用数据库的 settings 表（密钥为密文）。"""

    def __init__(self, store):
        self.store = store

    def get(self) -> tuple[str, str] | None:
        """返回 (区域, 密钥)；未配置或无法解密（如换了 Windows 用户）时返回 None。"""
        saved = self.store.get_cache(_CACHE_KEY)
        if not saved or not saved.get("key"):
            return None
        try:
            return saved["region"], unprotect(saved["key"])
        except (OSError, ValueError):
            return None

    def info(self) -> dict:
        saved = self.store.get_cache(_CACHE_KEY) or {}
        credentials = self.get()
        return {
            "configured": credentials is not None,
            "region": saved.get("region", "eastus"),
            "key_hint": f"····{credentials[1][-4:]}" if credentials else "",
        }

    def save(self, region: str, key: str | None):
        """key 为 None 表示沿用已保存的密钥，只更新区域。"""
        if key is None:
            current = self.get()
            if current is None:
                raise ValueError("请填写 Azure 密钥")
            key = current[1]
        self.store.put_cache(_CACHE_KEY, {"region": region, "key": protect(key)})

    def clear(self):
        self.store.put_cache(_CACHE_KEY, None)
