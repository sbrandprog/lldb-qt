"""Форматтеры для структур Qt5.

Qt5 использует классическую раскладку:
  - QString:      QStringData *d      (header: ref,size,alloc,capacity,offset)
  - QByteArray:   QByteArrayData *d   (аналогично)
  - QVector<T>:   QVectorData *d      (header: ref,size,alloc,offset + массив T)
  - QList<T>:     QListData::Data *d  (header + массив слотов по sizeof(void*)).
                  Раскладка элементов зависит от QTypeInfo<T>:
                    - movable-типы (QString, int, ...): T лежит инлайн в слоте;
                    - большие/static-типы: слот — указатель на T в heap.
    Классы layout: ArrayCompatible / InlineWithPadding / Indirect.
  - QStringList:  фактически QList<QString>

QDate/QTime/геометрия — из общего модуля misc (структуры те же, что в Qt6,
только поля Qt5 — прямые int, без обёрток m_i).
"""

from . import common, misc
from .providers import ListSynthetic

import lldb

# ---------------------------------------------------------------------------
# Строки: QString / QByteArray (через header + offset)
# ---------------------------------------------------------------------------


def _data_offset_string(value):
    """Возвращает (data_addr, size) для QString/QByteArray Qt5.

    d — QStringData*/QByteArrayData*; данные лежат на d + offset
    (offset может быть отрицательным для статических строк).
    """
    d = common.get_child_by_name(common.raw_value(value), "d")
    if not d or not d.IsValid():
        return None, None
    d_addr = d.GetValueAsUnsigned()
    if not d_addr:
        return None, 0
    dd = d.Dereference()
    if not dd.IsValid():
        return None, None
    size = common.get_child_by_name(dd, "size")
    offset = common.get_child_by_name(dd, "offset")
    size_v = common.read_pointer(size) if size else 0
    offset_v = common.read_pointer(offset) if offset else 0
    if size_v is None:
        size_v = 0
    if offset_v is None:
        offset_v = 0
    return d_addr + offset_v, size_v


def format_qstring(valobj, internal_dict):
    """Summary для QString (Qt5): UTF-16 -> строка."""
    data_addr, size = _data_offset_string(valobj)
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
    """Summary для QByteArray (Qt5): ASCII/hex."""
    data_addr, size = _data_offset_string(valobj)
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


# ---------------------------------------------------------------------------
# QList<T> / QStringList (Qt5): массив указателей на T
# ---------------------------------------------------------------------------


def _qlist_data(value):
    """Находит QListData::Data для QList<T>/QStringList Qt5.

    Возвращает (data_obj, begin, end) либо (None, 0, 0).
    QList<T> через union { p = QListData; d = QListData::Data* }.
    """
    raw = common.raw_value(value)
    # Переходим к QList<T>: у QStringList это первый ребёнок
    ql = raw
    if not ql or not ql.IsValid():
        return None, 0, 0
    tname = ql.GetTypeName()
    if "StringList" in tname:
        ql = ql.GetChildAtIndex(0)
    if not ql or not ql.IsValid():
        return None, 0, 0
    # Ищем union (у QList он один) и в нём поле d (Data*)
    d_ptr = None
    for i in range(ql.GetNumChildren()):
        c = ql.GetChildAtIndex(i)
        dn = c.GetName() or ""
        if dn == "d" or "union" in c.GetTypeName():
            d_ptr = _find_deep(c, "d")
            if d_ptr:
                break
    if d_ptr is None:
        d_ptr = common.get_child_by_name(ql, "d")
    if d_ptr is None or not d_ptr.IsValid():
        return None, 0, 0
    dd = d_ptr.Dereference()
    if not dd.IsValid():
        return None, 0, 0
    begin = common.get_child_by_name(dd, "begin")
    end = common.get_child_by_name(dd, "end")
    b = common.read_pointer(begin) if begin else 0
    e = common.read_pointer(end) if end else 0
    return dd, b or 0, e or 0


def _find_deep(v, name, depth=0):
    """Рекурсивно ищет дочерний SBValue по имени на небольшой глубине."""
    if v is None or not v.IsValid():
        return None
    c = v.GetChildMemberWithName(name)
    if c and c.IsValid():
        return c
    if depth >= 3:
        return None
    for i in range(v.GetNumChildren()):
        r = _find_deep(v.GetChildAtIndex(i), name, depth + 1)
        if r is not None:
            return r
    return None


def _element_type(value):
    """Определяет тип элемента контейнера Qt5.

    GetTemplateArgumentType срабатывает для QList<T>/QVector<T>, но не для
    QStringList (typedef на QList<QString>); для него берём QString.
    """
    t = value.GetType().GetTemplateArgumentType(0)
    if t and t.IsValid():
        return t
    name = value.GetTypeName()
    if "StringList" in name:
        return value.GetTarget().FindFirstType("QString")
    return t


_QT_MOVABLE_TYPES = frozenset(
    {
        "QBrush",
        "QBitArray",
        "QByteArray",
        "QCustomTypeInfo",
        "QChar",
        "QDate",
        "QDateTime",
        "QFileInfo",
        "QFixed",
        "QFixedPoint",
        "QFixedSize",
        "QHashDummyValue",
        "QIcon",
        "QImage",
        "QLine",
        "QLineF",
        "QLatin1Char",
        "QLocale",
        "QMatrix",
        "QModelIndex",
        "QPoint",
        "QPointF",
        "QPen",
        "QPersistentModelIndex",
        "QResourceRoot",
        "QRect",
        "QRectF",
        "QRegExp",
        "QSize",
        "QSizeF",
        "QString",
        "QTime",
        "QTextBlock",
        "QUrl",
        "QVariant",
        "QXmlStreamAttribute",
        "QXmlStreamNamespaceDeclaration",
        "QXmlStreamNotationDeclaration",
        "QXmlStreamEntityDeclaration",
    }
)


def is_movable_type(elem_type):
    """Приближает QTypeInfo<T>::isMovable для выбора раскладки QList Qt5.

    Точное условие IndirectLayout — isLarge || isStatic, но эти compile-time
    данные недоступны из отладчика. Повторяем эвристику Qt Creator:
    инлайн-хранение для pointer/integral/float и известных перемещаемых
    типов Qt; всё остальное (обычные struct, большие типы) — по указателю.
    """
    if elem_type is None or not elem_type.IsValid():
        return False
    flags = elem_type.GetTypeFlags()
    if flags & (lldb.eTypeIsInteger | lldb.eTypeIsFloat | lldb.eTypeIsPointer):
        return True
    name = (elem_type.GetName() or "").split("::")[-1]
    return name in _QT_MOVABLE_TYPES


class QStringListSynthetic(ListSynthetic):
    """Synthetic для QList<T>/QStringList Qt5."""

    def _qlist(self):
        return _qlist_data(common.raw_value(self.value))

    def count(self):
        _, b, e = self._qlist()
        n = e - b
        return n if n >= 0 else 0

    def item_at(self, index):
        data_obj, b, _ = self._qlist()
        if data_obj is None:
            return None
        array = common.get_child_by_name(data_obj, "array")
        if not array or not array.IsValid():
            return None
        data_addr = array.GetLoadAddress()
        if not data_addr:
            return None
        elem_type = _element_type(self.value)
        if not elem_type or not elem_type.IsValid():
            return None
        target = self.value.GetTarget()
        step = target.addr_size  # размер слота void* в QListData::Data
        slot_addr = data_addr + (b + index) * step
        if elem_type.GetByteSize() <= step and is_movable_type(elem_type):
            # ArrayCompatibleLayout / InlineWithPaddingLayout: T хранится
            # инлайн в слоте array[begin + i] (со страйдом sizeof(void*)).
            elem_addr = slot_addr
        else:
            # IndirectLayout (isLarge || isStatic): слот — указатель на T.
            err = lldb.SBError()
            elem_addr = target.GetProcess().ReadPointerFromMemory(slot_addr, err)
            if err.Fail() or not elem_addr:
                return None
        sbaddr = lldb.SBAddress(elem_addr, target)
        return target.CreateValueFromAddress(f"[{index}]", sbaddr, elem_type)


def _summary_qstring_list(valobj, internal_dict):
    """Summary для QList<T>/QStringList Qt5."""
    try:
        synth = QStringListSynthetic(valobj, internal_dict)
        n = synth.count()
        if n == 0:
            return "[]"
        items = []
        for i in range(min(n, 8)):
            v = synth.item_at(i)
            if v is None:
                items.append("?")
                continue
            s = v.GetSummary()
            if not s:
                s = v.GetValue() or "?"
            items.append(s or "?")
        tail = "…" if n > 8 else ""
        return "size=" + str(n) + " [" + ", ".join(items) + tail + "]"
    except Exception:
        return "<unreadable>"


# ---------------------------------------------------------------------------
# QVector<T> (Qt5): массив T напрямую по offset
# ---------------------------------------------------------------------------


class QVectorSynthetic(ListSynthetic):
    """Synthetic для QVector<T> Qt5 (данные копиями по offset)."""

    def _vec(self):
        d = common.get_child_by_name(common.raw_value(self.value), "d")
        if not d or not d.IsValid():
            return None, 0
        d_addr = d.GetValueAsUnsigned()
        dd = d.Dereference()
        if not dd.IsValid():
            return None, 0
        size = common.get_child_by_name(dd, "size")
        offset = common.get_child_by_name(dd, "offset")
        size_v = common.read_pointer(size) if size else 0
        offset_v = common.read_pointer(offset) if offset else 0
        data_addr = d_addr + (offset_v or 0)
        return data_addr, size_v or 0

    def count(self):
        _, n = self._vec()
        return n if n and n > 0 else 0

    def item_at(self, index):
        data_addr, _ = self._vec()
        if not data_addr:
            return None
        elem_type = self.value.GetType().GetTemplateArgumentType(0)
        if not elem_type or not elem_type.IsValid():
            return None
        size = elem_type.GetByteSize()
        target = self.value.GetTarget()
        addr = data_addr + index * size
        return target.CreateValueFromAddress(f"[{index}]", lldb.SBAddress(addr, target), elem_type)


def _summary_qvector(valobj, internal_dict):
    """Summary для QVector<T> Qt5."""
    try:
        synth = QVectorSynthetic(valobj, internal_dict)
        n = synth.count()
        if n == 0:
            return "[]"
        items = []
        for i in range(min(n, 8)):
            v = synth.item_at(i)
            if v is None:
                items.append("?")
                continue
            s = v.GetSummary()
            if not s:
                s = v.GetValue() or "?"
            items.append(s or "?")
        tail = "…" if n > 8 else ""
        return "size=" + str(n) + " [" + ", ".join(items) + tail + "]"
    except Exception:
        return "<unreadable>"


# ---------------------------------------------------------------------------
# Регистрация
# ---------------------------------------------------------------------------


def register(debugger, internal_dict, rs, rh):
    m = __name__  # "qt_formatters.qt5"
    rs(debugger, ["QString"], f"{m}.format_qstring")
    rs(debugger, ["QByteArray"], f"{m}.format_qbytearray")

    # QList<T> / QStringList
    rh(debugger, ["(QList<.*>|QStringList)$"], f"{m}.QStringListSynthetic")
    rs(debugger, ["(QList<.*>|QStringList)$"], f"{m}._summary_qstring_list", expand=True)

    # QVector<T>
    rh(debugger, ["QVector<.*>$"], f"{m}.QVectorSynthetic")
    rs(debugger, ["QVector<.*>$"], f"{m}._summary_qvector", expand=True)

    # Дата / время / геометрия (общие форматтеры)
    mm = misc.__name__
    rs(debugger, ["QDate"], f"{mm}.format_qdate")
    rs(debugger, ["QTime"], f"{mm}.format_qtime")
    rs(debugger, ["QSize"], f"{mm}.format_qsize")
    rs(debugger, ["QPoint"], f"{mm}.format_qpoint")
    rs(debugger, ["QRect"], f"{mm}.format_qrect")
    rs(debugger, ["QLine"], f"{mm}.format_qline")
