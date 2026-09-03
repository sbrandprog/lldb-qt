"""Общая инфраструктура для lldb-форматтеров Qt.

Содержит низкоуровневые хелперы для безопасного чтения памяти через SBValue
и общие обёртки для регистрации summary/synthetic провайдеров.
"""

import lldb


def raw_value(value):
    """Возвращает 'сырое' SBValue, минуя synthetic-обёртку.

    Когда применяется synthetic-провайдер, self.value в summary/провайдере
    уже обёрнут в synthetic-структуру, и GetChildMemberWithName ищет среди
    synthetic-детей, а не реальных полей. Чтобы прочитать настоящие поля
    контейнера, нужно запросить non-synthetic значение.
    """
    if value is None or not value.IsValid():
        return value
    try:
        return value.GetNonSyntheticValue()
    except Exception:
        return value


def get_child_by_name(value, name):
    """Находит дочерний SBValue по имени поля (с учётом базовых классов).

    lldb может не показывать поле прямо в GetChildMemberWithName, если оно
    спрятано за базовым классом шаблонов; пробуем разные стратегии.
    """
    if not value.IsValid():
        return None
    child = value.GetChildMemberWithName(name)
    if child and child.IsValid():
        return child
    return None


def read_pointer(value):
    """Читает значение указателя/целочисленного поля из SBValue.

    Возвращает int (адрес или число) или None при неудаче.
    """
    if value is None or not value.IsValid():
        return None
    return value.GetValueAsUnsigned()


def read_signed(value):
    """Читает знаковое целочисленное поле из SBValue (int или None).

    Нужно для полей со знаком (например, offset в Qt5-заголовке строки может
    быть отрицательным); GetValueAsUnsigned исказил бы отрицательное значение.
    """
    if value is None or not value.IsValid():
        return None
    return value.GetValueAsSigned()


def read_int_at(ptr_value, offset, size=8, signed=True):
    """Читает целое заданного размера из памяти по адресу ptr+offset.

    Нужно для opaque-типов (например, QDateTimePrivate), которые lldb не может
    разыменовать напрямую через Dereference(). Возвращает int или None.
    """
    if ptr_value is None or not ptr_value.IsValid():
        return None
    addr = ptr_value.GetValueAsUnsigned()
    if not addr:
        return None
    target = ptr_value.GetTarget()
    if target is None:
        return None
    if size == 4:
        typ = target.FindFirstType("int")
    elif size == 8:
        typ = target.FindFirstType("long long")
    else:
        return None
    if typ is None or not typ.IsValid():
        return None
    proc = ptr_value.GetProcess()
    if proc is None:
        return None
    err = lldb.SBError()
    buf = proc.ReadMemory(addr + offset, size, err)
    if err.Fail() or buf is None or len(buf) < size:
        return None
    val = ptr_value.CreateValueFromAddress("field", addr + offset, typ)
    if val is None or not val.IsValid():
        return None
    return val.GetValueAsSigned() if signed else val.GetValueAsUnsigned()


def read_cstring(proc, addr, max_len=256):
    """Читает NUL-терминированную C-строку из памяти процесса.

    Возвращает str или None при неудаче.
    """
    if proc is None or not addr:
        return None
    try:
        err = lldb.SBError()
        return proc.ReadCStringFromMemory(addr, max_len, err)
    except Exception:
        return None


def item_summary(value):
    """Короткое строковое представление SBValue (summary или значение).

    Используется summary-функциями контейнеров для единообразного отображения
    элементов: приоритет у summary, иначе сырое значение, иначе "?".
    """
    if value is None or not value.IsValid():
        return "?"
    s = value.GetSummary()
    if not s:
        s = value.GetValue() or "?"
    return s or "?"


def find_deep(v, name, depth=0, max_depth=8):
    """Рекурсивно ищет дочерний SBValue по имени на ограниченной глубине."""
    if v is None or not v.IsValid():
        return None
    c = v.GetChildMemberWithName(name)
    if c and c.IsValid():
        return c
    if depth >= max_depth:
        return None
    for i in range(v.GetNumChildren()):
        r = find_deep(v.GetChildAtIndex(i), name, depth + 1, max_depth)
        if r is not None:
            return r
    return None


def get_template_arg_type(value_type):
    """Возвращает SBType первого шаблонного аргумента (для QList<T> и т.п.)."""
    return value_type.GetTemplateArgumentType(0)
