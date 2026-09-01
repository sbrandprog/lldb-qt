"""Форматтер и синтетик для QVariant."""

import lldb
import struct

from . import common

# Qt5: d.type — 30-битный id QMetaType::Type (стабильная enum-карта).
_QT5_TYPE_NAMES = {
    1: "bool",
    2: "int",
    3: "uint",
    4: "qlonglong",
    5: "qulonglong",
    6: "double",
    7: "QChar",
    8: "QMap<QString, QVariant>",
    9: "QList<QVariant>",
    10: "QString",
    11: "QStringList",
    12: "QByteArray",
    13: "QBitArray",
    14: "QDate",
    15: "QTime",
    16: "QDateTime",
    17: "QUrl",
    18: "QLocale",
    19: "QRect",
    20: "QRectF",
    21: "QSize",
    22: "QSizeF",
    23: "QLine",
    24: "QLineF",
    25: "QPoint",
    26: "QPointF",
    28: "QHash<QString, QVariant>",
    30: "QUuid",
    32: "long",
    33: "short",
    34: "char",
    35: "ulong",
    36: "ushort",
    37: "uchar",
    38: "float",
    40: "signed char",
    49: "QByteArrayList",
}

# Скаляры: (struct-код, размер, тип) для чтения прямо из памяти.
_SCALAR_FORMAT = {
    "bool": ("?", 1, "bool"),
    "char": ("b", 1, "int"),
    "signed char": ("b", 1, "int"),
    "uchar": ("B", 1, "int"),
    "unsigned char": ("B", 1, "int"),
    "short": ("h", 2, "int"),
    "ushort": ("H", 2, "int"),
    "unsigned short": ("H", 2, "int"),
    "int": ("i", 4, "int"),
    "uint": ("I", 4, "int"),
    "unsigned int": ("I", 4, "int"),
    "long": ("q", 8, "int"),
    "ulong": ("Q", 8, "int"),
    "unsigned long": ("Q", 8, "int"),
    "long long": ("q", 8, "int"),
    "qlonglong": ("q", 8, "int"),
    "qulonglong": ("Q", 8, "int"),
    "unsigned long long": ("Q", 8, "int"),
    "float": ("f", 4, "float"),
    "double": ("d", 8, "float"),
    "qreal": ("d", 8, "float"),
}


def _scalar_layout(type_name, code, size, target):
    """Уточняет struct-код и размер скаляра по реальному типу в target.

    Разрядность long зависит от ABI (4 байта на ILP32/Windows, 8 на LP64);
    остальные типы фиксированы таблицей. Если тип в target не найден,
    возвращаются табличные значения.
    """
    if type_name in ("long", "ulong", "unsigned long"):
        t = target.FindFirstType(type_name) if target is not None else None
        n = t.GetByteSize() if t is not None and t.IsValid() else size
        if type_name == "long":
            return ("l" if n == 4 else "q"), n
        return ("L" if n == 4 else "Q"), n
    return code, size


def _format_scalar(type_name, addr, target, proc):
    """Форматирует скалярное значение по адресу addr (str или None)."""
    fmt = _SCALAR_FORMAT.get(type_name)
    if fmt is None or not addr or proc is None:
        return None
    code, size, kind = fmt
    code, size = _scalar_layout(type_name, code, size, target)
    order = "<"
    if target is not None and target.GetByteOrder() == lldb.eByteOrderBig:
        order = ">"
    err = lldb.SBError()
    buf = proc.ReadMemory(addr, size, err)
    if not buf or err.Fail():
        return None
    val = struct.unpack(order + code, buf)[0]
    if kind == "bool":
        return "true" if val else "false"
    if kind == "float":
        return repr(float(val))
    return str(val)


def _value_of(target, addr, type_name, name="value"):
    """Создаёт SBValue типа type_name по адресу addr (или None)."""
    if not addr or not type_name:
        return None
    t = target.FindFirstType(type_name)
    if t is None or not t.IsValid():
        return None
    return target.CreateValueFromAddress(name, lldb.SBAddress(addr, target), t)


def _format_qt_value(type_name, addr, valobj):
    """Форматирует Qt-тип/контейнер, переиспользуя зарегистрированные summary."""
    v = _value_of(valobj.GetTarget(), addr, type_name)
    if v is None or not v.IsValid():
        return None
    s = v.GetSummary()
    if s:
        return s
    return v.GetValue()


def _qt5_storage(d):
    """Адрес хранимого значения для Qt5 QVariant::Private."""
    data = common.get_child_by_name(d, "data")
    if data is None or not data.IsValid():
        return None
    is_shared = common.get_child_by_name(d, "is_shared")
    if is_shared and is_shared.IsValid() and is_shared.GetValueAsUnsigned():
        shared = common.get_child_by_name(data, "shared")
        if shared and shared.IsValid():
            sh = shared.Dereference()
            if sh and sh.IsValid():
                return common.read_pointer(common.get_child_by_name(sh, "ptr"))
        return None
    return data.GetLoadAddress()


def _qt6_storage(d):
    """Адрес хранимого значения для Qt6 QVariant::Private."""
    data = common.get_child_by_name(d, "data")
    if data is None or not data.IsValid():
        return None
    is_shared = common.get_child_by_name(d, "is_shared")
    if is_shared and is_shared.IsValid() and is_shared.GetValueAsUnsigned():
        shared = common.get_child_by_name(data, "shared")
        if shared and shared.IsValid():
            sh = shared.Dereference()
            if sh and sh.IsValid():
                base = common.read_pointer(shared)
                off = common.read_signed(common.get_child_by_name(sh, "offset"))
                if base is None or off is None:
                    return None
                return base + off
        return None
    return data.GetLoadAddress()


def _qt5_type_name(valobj, tid):
    """Имя типа Qt5 по id: статическая таблица + динамический fallback.

    Для кастомных/шаблонных типов (id >= User) имя берётся из метатип-реестра
    через вызов QMetaType::typeName(id) в целевом процессе; при неудаче (нет
    процесса/символов) возвращаем None.
    """
    name = _QT5_TYPE_NAMES.get(tid)
    if name is not None:
        return name
    if not tid:
        return None
    try:
        v = valobj.EvaluateExpression(f"QMetaType::typeName({tid})")
        if v is not None and v.IsValid():
            ptr = v.GetValueAsUnsigned()
            if ptr:
                return common.read_cstring(valobj.GetProcess(), ptr)
    except Exception:
        pass
    return None


def _variant_info(valobj):
    """Возвращает (is_null, type_name, storage_addr) для QVariant (или None).

    Диспетчеризация раскладки:
      - Qt6: d.packedType — указатель на QtPrivate::QMetaTypeInterface,
        сдвинутый на 2 бита; имя типа читается из поля name (offset 24);
      - Qt5: d.type — 30-битный id QMetaType::Type, имя по таблице.
    """
    raw = common.raw_value(valobj)
    if raw is None or not raw.IsValid():
        return None
    d = common.get_child_by_name(raw, "d")
    if d is None or not d.IsValid():
        return None
    is_null = common.get_child_by_name(d, "is_null")
    if is_null and is_null.IsValid() and is_null.GetValueAsUnsigned():
        return True, None, None
    packed = common.get_child_by_name(d, "packedType")
    if packed and packed.IsValid():
        iface = packed.GetValueAsUnsigned() << 2
        proc = valobj.GetProcess()
        type_name = None
        if iface and proc:
            err = lldb.SBError()
            name_addr = proc.ReadPointerFromMemory(iface + 24, err)
            if err.Success() and name_addr:
                type_name = common.read_cstring(proc, name_addr)
        return False, type_name, _qt6_storage(d)
    type_id = common.get_child_by_name(d, "type")
    tid = type_id.GetValueAsUnsigned() if type_id and type_id.IsValid() else None
    type_name = _qt5_type_name(valobj, tid)
    return False, type_name, _qt5_storage(d)


def format_qvariant(valobj, internal_dict):
    """Summary для QVariant: "<null>" либо "тип значение".

    Qt5 и Qt6 определяются по наличию поля packedType (Qt6) / type (Qt5).
    Скаляры читаются напрямую из памяти, Qt-типы и контейнеры форматируются
    через уже зарегистрированные summary.
    """
    info = _variant_info(valobj)
    if info is None:
        return "<invalid>"
    is_null, type_name, storage = info
    if is_null:
        return "<null>"
    value = None
    if type_name and storage:
        value = _format_scalar(type_name, storage, valobj.GetTarget(), valobj.GetProcess())
        if value is None:
            value = _format_qt_value(type_name, storage, valobj)
    if value is None:
        return f"<variant {type_name}>" if type_name else "<variant>"
    return f"{type_name} {value}"


class QVariantSynthetic:
    """Synthetic для QVariant: один ребёнок value — вложенное значение.

    Ребёнок создаётся как SBValue вложенного типа по адресу хранилища, поэтому
    lldb применяет к нему зарегистрированные форматтеры (символы QString,
    элементы QList и т.п.).
    """

    def __init__(self, value, internal_dict):
        self.value = value
        self.internal_dict = internal_dict
        self._child = None
        self.update()

    def update(self):
        info = _variant_info(self.value)
        self._child = None
        if info is not None:
            is_null, type_name, storage = info
            if not is_null and type_name and storage:
                self._child = _value_of(self.value.GetTarget(), storage, type_name)
        return False

    def has_children(self):
        return self._child is not None

    def num_children(self):
        return 1 if self._child is not None else 0

    def get_child_index(self, name):
        return 0 if name == "value" and self._child is not None else None

    def get_child_at_index(self, index):
        return self._child if index == 0 and self._child is not None else None
