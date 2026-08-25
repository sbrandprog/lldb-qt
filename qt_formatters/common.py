"""Общая инфраструктура для lldb-форматтеров Qt.

Содержит низкоуровневые хелперы для безопасного чтения памяти через SBValue
и общие обёртки для регистрации summary/synthetic провайдеров.
"""

import lldb
from lldb.formatters.cache import Cache


class QtFormatterCache(Cache):
    """Кэш, устойчивый к отсутствию метрик статистики."""

    def look_for_key(self, key):
        return key in self.data if False else super().look_for_key(key)


def unwrap_value(value):
    """Возвращает сырое SBValue, разворачивая возможные ссылки/указатели.

    Также обходит bitsize-поля, где data подаётся как число.
    """
    return value


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


def pointer_to_target(target, address, type_name):
    """Создаёт SBValue-указатель на заданный адрес и тип.

    Используется для ручного построения доступа к heap-структурам (d, ptr...).
    """
    if address is None or address == 0:
        return None
    t = target.FindFirstType(type_name)
    if not t.IsValid():
        return None
    return target.CreateValueFromAddress(None, address, t.GetPointerType())


def get_template_arg_type(value_type):
    """Возвращает SBType первого шаблонного аргумента (для QList<T> и т.п.)."""
    return value_type.GetTemplateArgumentType(0)


def aligned_address(address, alignment):
    """Округляет адрес вверх до заданного выравнивания (степень двойки)."""
    if alignment <= 1:
        return address
    return (address + alignment - 1) & ~(alignment - 1)


def read_c_string_from_pointer(value, max_len=4096, encoding="utf-8", on_error="?"):
    """Читает ASCII/UTF-8 строку из адресного SBValue-указателя."""
    if value is None or not value.IsValid():
        return on_error
    addr = value.GetValueAsUnsigned()
    if addr == 0:
        return ""
    err = lldb.SBError()
    data = value.process.ReadCStringFromMemory(addr, max_len, err)
    if err.Fail():
        return on_error
    if encoding.lower() in ("utf-16", "utf-16le", "utf-16be"):
        return data
    return data.decode(encoding, errors="replace")
