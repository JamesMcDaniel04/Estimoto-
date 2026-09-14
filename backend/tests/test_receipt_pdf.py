"""Receipt PDFs must remain inert even when actions hide in indirect objects."""
from io import BytesIO
import subprocess
import sys

import pytest
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, TextStringObject


def _check(writer):
    stream = BytesIO()
    writer.write(stream)
    return subprocess.run([sys.executable, '-m', 'estimoto_plus.receipt_pdf'],
                          input=stream.getvalue(), capture_output=True, timeout=8).returncode


def _action(kind='/JavaScript'):
    return DictionaryObject({NameObject('/S'): NameObject(kind),
                             NameObject('/JS'): TextStringObject('app.alert(1)')})


def test_plain_receipt_is_accepted():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    assert _check(writer) == 0


def test_indirect_annotation_action_is_rejected():
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    annotation = DictionaryObject({
        NameObject('/Type'): NameObject('/Annot'),
        NameObject('/Subtype'): NameObject('/Link'),
        NameObject('/Rect'): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(10), NumberObject(10)]),
        NameObject('/A'): writer._add_object(_action()),
    })
    page[NameObject('/Annots')] = ArrayObject([writer._add_object(annotation)])
    assert _check(writer) == 1


@pytest.mark.parametrize('kind', ['/JavaScript', '/Launch', '/GoToR', '/URI'])
def test_outline_bookmark_action_is_rejected_but_plain_bookmark_is_allowed(kind):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    outline = DictionaryObject({NameObject('/Type'): NameObject('/Outlines'), NameObject('/Count'): NumberObject(1)})
    outline_ref = writer._add_object(outline)
    item = DictionaryObject({NameObject('/Title'): TextStringObject('Receipt section'),
                             NameObject('/Parent'): outline_ref,
                             NameObject('/A'): writer._add_object(_action(kind))})
    item_ref = writer._add_object(item)
    outline[NameObject('/First')] = item_ref
    outline[NameObject('/Last')] = item_ref
    writer._root_object[NameObject('/Outlines')] = outline_ref
    assert _check(writer) == 1

    plain = PdfWriter()
    plain.add_blank_page(width=200, height=200)
    plain.add_outline_item('Receipt section', 0)
    assert _check(plain) == 0


def test_nested_name_tree_action_is_rejected():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    nested = DictionaryObject({NameObject('/Names'): ArrayObject([
        TextStringObject('receipt'), writer._add_object(_action()),
    ])})
    writer._root_object[NameObject('/Names')] = DictionaryObject({NameObject('/Dests'): writer._add_object(nested)})
    assert _check(writer) == 1


def test_cyclic_and_oversized_object_graphs_are_bounded():
    from estimoto_plus.receipt_pdf import inert_object_graph
    cycle = ArrayObject()
    cycle.append(cycle)
    assert inert_object_graph(cycle)
    deep = ArrayObject()
    cursor = deep
    for _ in range(50):
        child = ArrayObject()
        cursor.append(child)
        cursor = child
    assert not inert_object_graph(deep)
    assert not inert_object_graph(ArrayObject([NumberObject(0) for _ in range(4097)]))
