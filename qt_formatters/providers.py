"""Базовые synthetic-провайдеры для контейнеров Qt.

Synthetic-провайдеры дают lldb возможность раскрывать контейнер как набор
дочерних элементов с именами [i] и значениями.
"""


class ListSynthetic:
    """Провайдер synthetic children для последовательных контейнеров.

    Реализует интерфейс, который lldb вызывает через duck typing:
      __init__, update, has_children, num_children,
      get_child_index, get_child_at_index.

    Подклассы обязаны предоставить:
      - count() -> int
      - item_at(index) -> SBValue | None

    Состояние: self.values — список (имя, SBValue). Строится в __init__ и
    перестраивается в update().
    """

    def __init__(self, value, internal_dict):
        self.value = value
        self.internal_dict = internal_dict
        self.values = self._build_values()

    def count(self):
        raise NotImplementedError

    def item_at(self, index):
        raise NotImplementedError

    def _build_values(self):
        try:
            return [(f"[{i}]", self.item_at(i)) for i in range(self.count())]
        except Exception:
            return []

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
