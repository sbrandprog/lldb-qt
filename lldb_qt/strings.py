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


def format_qchar(valobj, internal_dict):
    """Summary для QChar: одиночный символ UTF-16.

    Для символов вне BMP (например, эмодзи) QChar хранит половину суррогатной
    пары, поэтому такой элемент отображается как одиночный surrogate.
    """
    ucs = common.get_child_by_name(common.raw_value(valobj), "ucs")
    if not ucs or not ucs.IsValid():
        return "<invalid>"
    c = ucs.GetValueAsUnsigned()
    return repr(chr(c))


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


class StringSynthetic:
    """Synthetic для QString / QByteArray: символы как дочерние элементы.

    QString раскладывается в элементы QChar (UTF-16, по 2 байта),
    QByteArray — в элементы char (по 1 байту). Раскладка данных берётся из
    _string_data(), поэтому провайдер работает для Qt5 и Qt6.

    Реализует duck-typed интерфейс synthetic children lldb напрямую
    (update, has_children, num_children, get_child_index, get_child_at_index).
    Дочерние элементы не материализуются заранее: для длинных строк это создало
    бы по одному SBValue на символ, поэтому доступ к ним ленивый.
    """

    def __init__(self, value, internal_dict):
        self.value = value
        self.internal_dict = internal_dict

    def _elem(self):
        """Возвращает (SBType, размер) элемента по имени типа строки."""
        raw = common.raw_value(self.value)
        if raw is None or not raw.IsValid():
            return None, 0
        name = raw.GetTypeName() or ""
        target = self.value.GetTarget()
        if "ByteArray" in name:
            return target.FindFirstType("char"), 1
        return target.FindFirstType("QChar"), 2

    def count(self):
        _, size = _string_data(self.value)
        return size if size and size > 0 else 0

    def item_at(self, index):
        data_addr, size = _string_data(self.value)
        if data_addr is None or index < 0 or index >= (size or 0):
            return None
        elem_type, elem_size = self._elem()
        if elem_type is None or not elem_type.IsValid() or not elem_size:
            return None
        target = self.value.GetTarget()
        addr = data_addr + index * elem_size
        return target.CreateValueFromAddress(f"[{index}]", lldb.SBAddress(addr, target), elem_type)

    def update(self):
        return False

    def has_children(self):
        return self.count() > 0

    def num_children(self):
        return self.count()

    def get_child_index(self, name):
        if name and name.startswith("[") and name.endswith("]"):
            try:
                index = int(name[1:-1])
            except ValueError:
                return None
            return index if 0 <= index < self.count() else None
        return None

    def get_child_at_index(self, index):
        if index < 0 or index >= self.count():
            return None
        return self.item_at(index)
