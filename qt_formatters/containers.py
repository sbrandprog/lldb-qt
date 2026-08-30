"""Версия-независимые synthetic-провайдеры для контейнеров Qt.

QList / QVector / QStringList раскладываются в Qt5 и Qt6 по-разному, поэтому
провайдер определяет фактическую раскладку по структуре SBValue в рантайме:

  - Qt6: поле d типа QArrayDataPointer<T> (содержит ptr/size) — сплошной массив T;
  - Qt5 QVector<T>: d — QVectorData* (header с size/offset) — сплошной массив T;
  - Qt5 QList<T>: union { p = QListData; d = QListData::Data* } с begin/end/array;
    раскладка элементов зависит от QTypeInfo<T>:
      - movable/малые типы лежат инлайн в слоте sizeof(void*);
      - большие/static типы — слот хранит указатель на T в heap.
"""

from . import common
from .providers import ListSynthetic

import lldb

# ---------------------------------------------------------------------------
# Вспомогательное: тип элемента
# ---------------------------------------------------------------------------


def _element_type(value):
    """Определяет тип элемента контейнера.

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


# ---------------------------------------------------------------------------
# Вспомогательное: поиск поля d
# ---------------------------------------------------------------------------


def _find_d(raw):
    """Находит поле d контейнера (с учётом union в QList Qt5)."""
    d = common.get_child_by_name(raw, "d")
    if d and d.IsValid():
        return d
    for i in range(raw.GetNumChildren()):
        c = raw.GetChildAtIndex(i)
        if c is None or not c.IsValid():
            continue
        if c.GetName() == "d":
            return c
        if "union" in (c.GetTypeName() or ""):
            dd = common.find_deep(c, "d")
            if dd is not None:
                return dd
    return None


# ---------------------------------------------------------------------------
# Единый synthetic-провайдер
# ---------------------------------------------------------------------------


class QListSynthetic(ListSynthetic):
    """Synthetic для QList<T> / QVector<T> / QStringList (Qt5 + Qt6)."""

    def _layout(self):
        """Определяет раскладку контейнера.

        Возвращает (kind, data_addr, size, elem_type, extra) либо
        (None, None, 0, None, None). kind: "contiguous" | "qt5_list".
        """
        raw = common.raw_value(self.value)
        if raw is None or not raw.IsValid():
            return None, None, 0, None, None
        elem_type = _element_type(raw)
        d = _find_d(raw)
        if d is None:
            # Qt5 QStringList: реальная структура в базовом классе QList (child[0])
            if "StringList" in (raw.GetTypeName() or ""):
                child = raw.GetChildAtIndex(0)
                if child and child.IsValid():
                    d = _find_d(child)
        if d is None or not d.IsValid():
            return None, None, 0, elem_type, None
        # Qt6 QArrayDataPointer<T>: есть поле ptr
        ptr = common.get_child_by_name(d, "ptr")
        if ptr and ptr.IsValid():
            data_addr = common.read_pointer(ptr)
            size = common.read_pointer(common.get_child_by_name(d, "size"))
            return "contiguous", data_addr, size or 0, elem_type, None
        # Qt5: d — указатель на header
        dd = d.Dereference()
        if dd is None or not dd.IsValid():
            return None, None, 0, elem_type, None
        begin = common.get_child_by_name(dd, "begin")
        end = common.get_child_by_name(dd, "end")
        if begin and end:
            # Qt5 QList<T>: QListData::Data (begin/end/array)
            b = common.read_pointer(begin) or 0
            e = common.read_pointer(end) or 0
            return "qt5_list", dd, e - b, elem_type, None
        size = common.get_child_by_name(dd, "size")
        offset = common.get_child_by_name(dd, "offset")
        # Qt5 QVector<T>: QVectorData (size/offset) — сплошной массив T
        data_addr = d.GetValueAsUnsigned() + (common.read_pointer(offset) or 0)
        size_v = common.read_pointer(size) or 0
        return "contiguous", data_addr, size_v, elem_type, None

    def count(self):
        kind, _, size, _, _ = self._layout()
        if kind is None:
            return 0
        if kind == "qt5_list":
            return size if size >= 0 else 0
        return size if size and size > 0 else 0

    def item_at(self, index):
        kind, data, size, elem_type, _ = self._layout()
        if kind is None or elem_type is None or not elem_type.IsValid():
            return None
        target = self.value.GetTarget()
        if kind == "contiguous":
            if data is None:
                return None
            elem_size = elem_type.GetByteSize()
            if not elem_size:
                return None
            addr = data + index * elem_size
            return target.CreateValueFromAddress(
                f"[{index}]", lldb.SBAddress(addr, target), elem_type
            )
        # qt5_list: data — QListData::Data, элементы в слотах sizeof(void*)
        array = common.get_child_by_name(data, "array")
        if not array or not array.IsValid():
            return None
        array_addr = array.GetLoadAddress()
        if not array_addr:
            return None
        begin = common.get_child_by_name(data, "begin")
        b = common.read_pointer(begin) if begin else 0
        step = target.addr_size
        slot_addr = array_addr + (b + index) * step
        if elem_type.GetByteSize() <= step and is_movable_type(elem_type):
            elem_addr = slot_addr
        else:
            err = lldb.SBError()
            elem_addr = target.GetProcess().ReadPointerFromMemory(slot_addr, err)
            if err.Fail() or not elem_addr:
                return None
        return target.CreateValueFromAddress(
            f"[{index}]", lldb.SBAddress(elem_addr, target), elem_type
        )


def _summary_qlist(valobj, internal_dict):
    """Summary для QList<T> / QVector<T> / QStringList."""
    try:
        synth = QListSynthetic(valobj, internal_dict)
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
