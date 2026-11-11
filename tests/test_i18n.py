"""Every T("…") string in the code has a translation with the same
placeholders and markup in every catalog under hostkeep/locale/."""
import ast
import glob
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACEHOLDER = re.compile(r"\{[^{}]*\}")
TAG = re.compile(r"</?\w+")
# ids that are stored untranslated and translated only when shown
DISPLAY_IDS = ["Пустой", "Сервер по ключу", "Через бастион (ProxyJump)", "Подсеть / wildcard", "По паролю",
               "Туннель к БД (LocalForward)", "Нестабильная сеть (keepalive)", "Мультиплексирование",
               "Старый сервер (ssh-rsa)", "туннель", "команда", "сессия", "⚙ Общие правила (*, Match)", "Без группы"]


def source_strings():
    keys = set(DISPLAY_IDS)
    for path in glob.glob(os.path.join(ROOT, "hostkeep", "*.py")):
        tree = ast.parse(open(path, encoding="utf-8").read())
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "T" and n.args \
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                keys.add(n.args[0].value)
    return keys


class Catalogs(unittest.TestCase):
    def test_catalogs_are_complete_and_consistent(self):
        keys = source_strings()
        self.assertGreater(len(keys), 300)
        for path in glob.glob(os.path.join(ROOT, "hostkeep", "locale", "*.json")):
            with self.subTest(catalog=os.path.basename(path)):
                cat = json.load(open(path, encoding="utf-8"))
                missing = sorted(k for k in keys if not cat.get(k))
                self.assertEqual(missing, [], "untranslated strings")
                for k, v in cat.items():
                    self.assertEqual(sorted(PLACEHOLDER.findall(k)), sorted(PLACEHOLDER.findall(v)), k)
                    self.assertEqual(sorted(TAG.findall(k)), sorted(TAG.findall(v)), k)


if __name__ == "__main__":
    unittest.main()
