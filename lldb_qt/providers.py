"""Базовые synthetic-провайдеры для контейнеров Qt.

Synthetic-провайдеры дают lldb возможность раскрывать контейнер как набор
дочерних элементов с именами [i] и значениями.
"""

import lldb


def build_values(target, items):
    """Строит list[(имя, SBValue)] из итератора пар (addr, SBType).

    Имена [0]..[n-1] назначаются только успешно созданным значениям;
    элементы с пустым адресом или невалидным типом пропускаются.
    """
    values = []
    i = 0
    for addr, typ in items:
        if not addr or typ is None or not typ.IsValid():
            continue
        val = target.CreateValueFromAddress(f"[{i}]", lldb.SBAddress(addr, target), typ)
        if val is not None and val.IsValid():
            values.append((f"[{i}]", val))
            i += 1
    return values


class SyntheticBase:
    """Общий интерфейс synthetic children lldb.

    Реализует интерфейс, который lldb вызывает через duck typing:
      __init__, update, has_children, num_children,
      get_child_index, get_child_at_index.

    Требование к подклассу: реализовать _build_values() -> list[(имя, SBValue)].
    Кэш self.values и интерфейсные методы наследуются.
    """

    def __init__(self, value, internal_dict):
        self.value = value
        self.internal_dict = internal_dict
        self.values = self._build_values()

    def _build_values(self):
        raise NotImplementedError

    def update(self):
        self.values = self._build_values()
        return False

    def has_children(self):
        return len(self.values) > 0

    def num_children(self):
        return len(self.values)

    def get_child_index(self, name):
        for i, (child_name, _) in enumerate(self.values):
            if child_name == name:
                return i
        return None

    def get_child_at_index(self, index):
        if index < 0 or index >= len(self.values):
            return None
        return self.values[index][1]


class ListSynthetic(SyntheticBase):
    """Провайдер synthetic children для контейнеров с произвольным доступом.

    Подклассы обязаны предоставить:
      - count() -> int
      - item_at(index) -> SBValue | None
    """

    def count(self):
        raise NotImplementedError

    def item_at(self, index):
        raise NotImplementedError

    def _build_values(self):
        try:
            return [(f"[{i}]", self.item_at(i)) for i in range(self.count())]
        except Exception:
            return []


class IterSynthetic(SyntheticBase):
    """Провайдер synthetic children для контейнеров без произвольного доступа.

    Подклассы обязаны предоставить:
      - build_values() -> list[(имя, SBValue)]  (материализация за один проход)
    """

    def build_values(self):
        raise NotImplementedError

    def _build_values(self):
        try:
            return self.build_values()
        except Exception:
            return []
