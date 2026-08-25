"""Базовые synthetic-провайдеры для контейнеров Qt.

Synthetic-провайдеры дают lldb возможность раскрывать контейнер как набор
дочерних элементов с именами [i] и значениями.
"""

import lldb
from lldb.formatters.synth import PythonObjectSyntheticChildProvider


class ListSynthetic(PythonObjectSyntheticChildProvider):
    """Провайдер для последовательных контейнеров (QList/QVector и пр.).

    Описывает API, который обязаны предоставить подклассы:
      - count() -> int
      - item_at(index) -> SBValue (или значение для gen_child)
    """

    def __init__(self, value, internal_dict):
        super().__init__(value, internal_dict)

    def count(self):
        raise NotImplementedError

    def item_at(self, index):
        raise NotImplementedError

    def _build_values(self):  # type: () -> list
        try:
            return [(f"[{i}]", self.item_at(i)) for i in range(self.count())]
        except Exception:
            return []

    def make_children(self):  # type: (...) -> list  # noqa: F811
        return self._build_values()

    def num_children(self):
        return len(self._build_values())

    def update(self):
        pass

    def get_child_index(self, name):
        try:
            if name.startswith("[") and name.endswith("]"):
                return int(name[1:-1])
        except ValueError:
            pass
        return super().get_child_index(name)
