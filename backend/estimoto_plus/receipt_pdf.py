"""Bounded subprocess parser for private receipt PDFs; never executes content."""
import sys
import resource
from io import BytesIO


_ACTIVE_KEYS = frozenset({
    "/OpenAction", "/AA", "/AcroForm", "/XFA",
    "/JS", "/JavaScript", "/EmbeddedFiles", "/EF", "/AF",
    "/RichMedia", "/Perms", "/Collection",
})
# Page annotations are walked like any other object: passive markup and
# /Link annotations pass, while widgets, attachments, media and every
# action other than the two below are rejected by the checks in the walk.
_LINK_SCHEMES = ("http://", "https://", "mailto:", "tel:")


def _inert_action(action) -> bool:
    """Allow only an internal page jump or a plain web/mail/phone link.

    The app rasterizes receipts, so links are never followed there; the
    scheme allowlist keeps the file safe for whatever opens it next.
    """
    from pypdf.generic import DictionaryObject, TextStringObject

    if not isinstance(action, DictionaryObject):
        return False
    kind = str(action.get("/S"))
    keys = {str(k) for k in action}
    if kind == "/GoTo":
        return not keys - {"/S", "/D", "/Type"}
    if kind == "/URI":
        target = action.get("/URI")
        target = target.get_object() if hasattr(target, "get_object") else target
        return (not keys - {"/S", "/URI", "/Type", "/IsMap"}
                and isinstance(target, (TextStringObject, str))
                and str(target).lower().startswith(_LINK_SCHEMES))
    return False
_ACTIVE_ACTIONS = frozenset({
    "/JavaScript", "/Launch", "/GoToR", "/GoToE", "/URI",
    "/SubmitForm", "/ImportData", "/Rendition", "/RichMediaExecute",
    "/Movie", "/Sound", "/Hide", "/SetOCGState", "/ResetForm",
})
_ACTIVE_TYPES = frozenset({"/Action", "/Filespec", "/EmbeddedFile"})
_ACTIVE_SUBTYPES = frozenset({
    "/Widget", "/FileAttachment", "/RichMedia", "/Movie", "/Sound", "/3D", "/Screen",
})


def inert_object_graph(root):
    """Inspect reachable PDF object metadata without decoding content streams.

    Indirect page trees and outline parent links are cyclic. Bounds apply to
    both the number of resolved objects and nesting, independently of pypdf's
    subprocess CPU, address-space and input-byte limits.
    """
    from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject

    pending = [(root, 0)]
    indirect_seen = set()
    direct_seen = set()
    inspected = 0
    while pending:
        obj, depth = pending.pop()
        if depth > 48:
            return False
        if isinstance(obj, IndirectObject):
            key = (obj.idnum, obj.generation)
            if key in indirect_seen:
                continue
            indirect_seen.add(key)
            pending.append((obj.get_object(), depth + 1))
            continue
        if not isinstance(obj, (DictionaryObject, ArrayObject)):
            continue
        marker = id(obj)
        if marker in direct_seen:
            continue
        direct_seen.add(marker)
        inspected += 1
        if inspected > 12000 or len(obj) > 4096:
            return False
        if isinstance(obj, DictionaryObject):
            for key, value in obj.items():
                label = str(key)
                if label == "/A":
                    # A receipt needs at most a bookmark page jump or a web
                    # link. Chained actions and malformed targets are
                    # rejected, and the validated action is not walked
                    # again so its /S value is judged here only.
                    action = value.get_object() if isinstance(value, IndirectObject) else value
                    if not _inert_action(action):
                        return False
                    continue
                if label in _ACTIVE_KEYS or (
                    label == "/S" and str(value) in _ACTIVE_ACTIONS
                ) or (label == "/Type" and str(value) in _ACTIVE_TYPES) or (
                    label == "/Subtype" and str(value) in _ACTIVE_SUBTYPES
                ):
                    return False
                pending.append((value, depth + 1))
        else:
            pending.extend((value, depth + 1) for value in obj)
    return True


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    if sys.platform == "linux":
        # Two parser slots share the 1 GB service with raster decoding/API work.
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    from pypdf import PdfReader
    data = sys.stdin.buffer.read(10 * 1024 * 1024 + 1)
    if not data.startswith(b"%PDF-") or len(data) > 10 * 1024 * 1024:
        return 1
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 50:
            return 1
        if not inert_object_graph(reader.trailer):
            return 1
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
