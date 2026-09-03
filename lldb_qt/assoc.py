"""Версия-независимые summary для ассоциативных контейнеров."""

from itertools import islice

from . import common
from . import hash as hash_mod
from .providers import IterSynthetic, build_values


def format_qhash(valobj, internal_dict):
    """Summary для QHash<K,V>: size=N [(k: v), ...].

    Пары ключ/значение читаются через общий обход hash.iter_hash_nodes
    (Qt5 — buckets/связанные списки, Qt6 — spans). Порядок не детерминирован.
    """
    try:
        size = hash_mod.hash_size(valobj)
        if size is None:
            return "<invalid>"
        if size == 0:
            return "[]"
        items = []
        for node in islice(hash_mod.iter_hash_nodes(valobj), 8):
            k = node.GetChildMemberWithName("key")
            v = node.GetChildMemberWithName("value")
            items.append(f"({common.item_summary(k)}: {common.item_summary(v)})")
        tail = "…" if size > 8 else ""
        return "size=" + str(size) + " [" + ", ".join(items) + tail + "]"
    except Exception:
        return "<unreadable>"


def format_qmultihash(valobj, internal_dict):
    """Summary для QMultiHash<K,V>: size=N (элементы не раскрываются).

    Qt6: отдельный класс с полем m_size (реальное число пар) — d->size здесь
    не то же самое. Qt5: QMultiHash наследует QHash, размер в d->size.
    """
    raw = common.raw_value(valobj)
    m_size = common.get_child_by_name(raw, "m_size")
    if m_size and m_size.IsValid():
        return f"size={m_size.GetValueAsUnsigned()}"
    d = common.find_deep(raw, "d")
    if not d:
        return "<invalid>"
    dd = d.Dereference()
    if dd and dd.IsValid():
        s = common.get_child_by_name(dd, "size")
        if s and s.IsValid():
            return f"size={s.GetValueAsUnsigned()}"
    return "<unavailable>"


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


class QHashSynthetic(IterSynthetic):
    """Synthetic для QHash<K,V>: записи (key/value) как дочерние [i].

    Как и встроенные форматтеры std::map/std::unordered_map, каждый ребёнок —
    это узел-запись, внутри которого видны и ключ, и значение (поля key/value;
    в Qt5 у узла есть также служебные next/h). Реализует контракт
    IterSynthetic: build_values() -> list[(имя, SBValue)].
    """

    def build_values(self):
        return build_values(
            self.value.GetTarget(),
            ((node.GetLoadAddress(), node.GetType()) for node in hash_mod.iter_hash_nodes(self.value)),
        )
