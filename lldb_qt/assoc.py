"""Версия-независимые summary для ассоциативных контейнеров."""

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
