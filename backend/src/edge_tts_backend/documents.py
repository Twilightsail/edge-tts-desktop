import io
import zipfile

from defusedxml import ElementTree

MAX_UPLOAD = 8 * 1024 * 1024
MAX_TEXT = 2_000_000


def read_document(name: str, data: bytes) -> dict:
    suffix = name.lower().rsplit(".", 1)[-1]
    if len(data) > MAX_UPLOAD:
        raise ValueError("文件超过 8 MB")
    if suffix == "docx":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if (
                len(archive.infolist()) > 3000
                or sum(i.file_size for i in archive.infolist()) > 64 * 1024 * 1024
            ):
                raise ValueError("DOCX 解压体积过大")
            info = archive.getinfo("word/document.xml")
            if info.file_size > 16 * 1024 * 1024:
                raise ValueError("DOCX 正文过大")
            root = ElementTree.fromstring(archive.read(info))
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = []
        for paragraph in root.iter(ns + "p"):
            content = []
            for node in paragraph.iter():
                if node.tag == ns + "t":
                    content.append(node.text or "")
                elif node.tag == ns + "tab":
                    content.append("\t")
                elif node.tag in (ns + "br", ns + "cr"):
                    content.append("\n")
            if "".join(content).strip():
                paragraphs.append("".join(content))
        text, encoding = "\n\n".join(paragraphs), "DOCX"
    elif suffix in ("txt", "md"):
        encodings = (
            ["utf-16"] if data.startswith((b"\xff\xfe", b"\xfe\xff")) else ["utf-8-sig", "gb18030"]
        )
        for encoding in encodings:
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("无法识别文件编码，请转换为 UTF-8 或 GBK")
        if "\x00" in text:
            raise ValueError("文件含二进制内容")
    else:
        raise ValueError("仅支持 TXT、Markdown 和 DOCX 文件")
    if not text.strip():
        raise ValueError("文档没有可读取的正文")
    if len(text) > MAX_TEXT:
        raise ValueError("正文超过 200 万字符，请拆分文档")
    return {
        "name": name,
        "text": text.replace("\r\n", "\n"),
        "encoding": encoding,
        "characters": len(text),
        "requires_split": len(text) > 100_000,
    }
