"""Версия-независимые summary для строковых типов Qt (QString / QByteArray).

Qt5 и Qt6 хранят строки по-разному, поэтому раскладка определяется по
структуре SBValue в рантайме:

  - Qt6: поле d типа QArrayDataPointer<T> (есть поле ptr) — данные по ptr,
    длина в size;
  - Qt5: поле d — указатель на header (QStringData/QByteArrayData) с size и
    offset, данные лежат по адресу d + offset.
"""

from . import common

import lldb


def _string_data(value):
    """Возвращает (data_addr, size) для QString/QByteArray любой версии Qt.

    Диспетчеризация: если у поля d есть дочерний ptr — это Qt6
    QArrayDataPointer; иначе d — указатель на Qt5-header с size/offset.
    """
    d = common.get_child_by_name(common.raw_value(value), "d")
    if not d or not d.IsValid():
        return None, None
    ptr = common.get_child_by_name(d, "ptr")
    if ptr and ptr.IsValid():
        data_addr = common.read_pointer(ptr)
        size = common.read_pointer(common.get_child_by_name(d, "size"))
        return data_addr, size
    d_addr = common.read_pointer(d)
    if not d_addr:
        return None, 0
    dd = d.Dereference()
    if not dd.IsValid():
        return None, None
    size = common.read_pointer(common.get_child_by_name(dd, "size"))
    offset = common.read_signed(common.get_child_by_name(dd, "offset"))
    return d_addr + (offset or 0), size


def format_qstring(valobj, internal_dict):
    """Summary для QString: UTF-16 -> строка."""
    data_addr, size = _string_data(valobj)
    if size is None or size < 0:
        return "<invalid>"
    if size == 0 or not data_addr:
        return '""'
    proc = valobj.GetProcess()
    err = lldb.SBError()
    count = min(int(size) * 2, 1 << 20)
    buf = proc.ReadMemory(data_addr, count, err)
    if not buf or err.Fail():
        return "<unreadable>"
    raw = buf.decode("utf-16-le", errors="replace")
    if len(raw) > 256:
        raw = raw[:256] + "…"
    return repr(raw) if raw else '""'


def format_qbytearray(valobj, internal_dict):
    """Summary для QByteArray: ASCII/hex."""
    data_addr, size = _string_data(valobj)
    if size is None or size < 0:
        return "<invalid>"
    if size == 0 or not data_addr:
        return '""'
    proc = valobj.GetProcess()
    err = lldb.SBError()
    buf = proc.ReadMemory(data_addr, int(size), err)
    if not buf or err.Fail():
        return "<unreadable>"
    try:
        s = buf.decode("ascii", errors="replace")
    except Exception:
        s = repr(buf.hex())
    if len(s) > 128:
        s = s[:128] + "…"
    return repr(s) if s else '""'
