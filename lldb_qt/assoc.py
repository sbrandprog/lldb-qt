"""Версия-независимые summary для ассоциативных контейнеров."""

from . import common


def format_qhash(valobj, internal_dict):
    """Summary для QHash<K,V>: size=N (элементы не раскрываются).

    В Qt5 и Qt6 QHash хранит указатель d на header с полем size, поэтому
    форматтер одинаков для обеих версий. find_deep находит d и в базовом
    классе (QMultiHash Qt5 наследует QHash).
    """
    d = common.find_deep(common.raw_value(valobj), "d")
    if not d:
        return "<invalid>"
    dd = d.Dereference()
    size = None
    if dd and dd.IsValid():
        s = common.get_child_by_name(dd, "size")
        if s and s.IsValid():
            size = s.GetValueAsUnsigned()
    if size is None:
        return "size=0"
    return f"size={size}"


def format_qmultihash(valobj, internal_dict):
    """Summary для QMultiHash<K,V>.

    Qt6: отдельный класс с полем m_size (реальное число пар) — d->size здесь
    не то же самое. Qt5: QMultiHash наследует QHash, размер в d->size.
    """
    raw = common.raw_value(valobj)
    m_size = common.get_child_by_name(raw, "m_size")
    if m_size and m_size.IsValid():
        return f"size={m_size.GetValueAsUnsigned()}"
    return format_qhash(valobj, internal_dict)


def format_qmap(valobj, internal_dict):
    """Summary для QMap<K,V>.

    В Qt5 d — QMapData* (header с полем size). В Qt6 QMap построен поверх
    std::map; размер читается из _M_node_count красно-чёрного дерева.
    Диспетчеризация: пробуем Qt5-раскладку (d.Dereference().size), иначе
    ищем _M_node_count. find_deep находит d и в базовом классе (QMultiMap Qt5).
    """
    d = common.find_deep(common.raw_value(valobj), "d")
    if not d:
        return "<invalid>"
    # Qt5: d — указатель на QMapData с size
    dd = d.Dereference()
    if dd and dd.IsValid():
        s = common.get_child_by_name(dd, "size")
        if s and s.IsValid():
            return f"size={s.GetValueAsUnsigned()}"
    # Qt6: обход std::map / std::multimap
    nc = common.find_deep(d, "_M_node_count")
    if nc and nc.IsValid():
        return f"size={nc.GetValueAsUnsigned()}"
    return "<unavailable>"


def format_qmultimap(valobj, internal_dict):
    """Summary для QMultiMap<K,V>.

    Раскладка повторяет QMap (Qt5 — базовый QMap с d->size, Qt6 — std::multimap
    с _M_node_count), поэтому просто делегируем в format_qmap.
    """
    return format_qmap(valobj, internal_dict)
