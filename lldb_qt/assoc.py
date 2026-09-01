"""Версия-независимые summary для ассоциативных контейнеров и QVariant."""

from . import common


def format_qhash(valobj, internal_dict):
    """Summary для QHash<K,V>: size=N (элементы не раскрываются).

    В Qt5 и Qt6 QHash хранит указатель d на header с полем size, поэтому
    форматтер одинаков для обеих версий.
    """
    d = common.get_child_by_name(common.raw_value(valobj), "d")
    if not d:
        return "<invalid>"
    dd = d.Dereference()
    size = None
    if dd and dd.IsValid():
        s = common.get_child_by_name(dd, "size")
        if s and s.IsValid():
            size = s.GetValueAsUnsigned()
    if size is None:
        return "<unavailable>"
    return f"size={size}"


def format_qmap(valobj, internal_dict):
    """Summary для QMap<K,V>.

    В Qt5 d — QMapData* (header с полем size). В Qt6 QMap построен поверх
    std::map; размер читается из _M_node_count красно-чёрного дерева.
    Диспетчеризация: пробуем Qt5-раскладку (d.Dereference().size), иначе
    ищем _M_node_count.
    """
    d = common.get_child_by_name(common.raw_value(valobj), "d")
    if not d:
        return "<invalid>"
    # Qt5: d — указатель на QMapData с size
    dd = d.Dereference()
    if dd and dd.IsValid():
        s = common.get_child_by_name(dd, "size")
        if s and s.IsValid():
            return f"size={s.GetValueAsUnsigned()}"
    # Qt6: обход std::map
    nc = common.find_deep(d, "_M_node_count")
    if nc and nc.IsValid():
        return f"size={nc.GetValueAsUnsigned()}"
    return "<unavailable>"


def format_qvariant(valobj, internal_dict):
    """Summary для QVariant (базовый).

    Qt5 и Qt6 хранят флаг is_null в поле d.is_null (bitfield), поэтому
    показываем только null/не-null состояние. Детальный разбор значений —
    см. TODO.
    """
    d = common.get_child_by_name(common.raw_value(valobj), "d")
    if not d:
        return "<invalid>"
    is_null = common.get_child_by_name(d, "is_null")
    if is_null and is_null.IsValid() and is_null.GetValueAsUnsigned():
        return "<null>"
    return "<variant>"
