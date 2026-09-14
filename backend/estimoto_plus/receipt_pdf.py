"""Bounded subprocess parser for private receipt PDFs; never executes content."""
import sys
import resource
from io import BytesIO


_ACTIVE_KEYS = frozenset({
    "/OpenAction", "/AA", "/Annots", "/AcroForm", "/XFA",
    "/JS", "/JavaScript", "/EmbeddedFiles", "/EF", "/AF",
    "/RichMedia", "/Perms", "/Collection",
})
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
                    # The only action a flattened receipt needs is an
                    # internal page jump from a bookmark. Reject all other
                    # action kinds, chained actions and malformed targets.
                    action = value.get_object() if isinstance(value, IndirectObject) else value
                    if (not isinstance(action, DictionaryObject) or
                            str(action.get("/S")) != "/GoTo" or
                            {str(k) for k in action} - {"/S", "/D", "/Type"}):
                        return False
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
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
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
