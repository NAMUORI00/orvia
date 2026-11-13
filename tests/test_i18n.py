import pathlib, sys, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
from i18n import LocalizedHTML, TRANSLATIONS


class LanguageTests(unittest.TestCase):
    def test_svg_preserves_self_closing_paths_and_viewbox(self):
        s = '<html lang="ko"><svg viewBox="0 0 10 10"><path d="M0 0"/><path d="M1 1"/></svg><h1>환경 안내서</h1></html>'
        p = LocalizedHTML("en")
        p.feed(s)
        r = "".join(p.parts)
        self.assertIn("viewBox=", r)
        self.assertEqual(r.count("/>"), 2)
        self.assertIn("Environment sheet", r)

    def test_wrapped_paragraph_is_translated(self):
        from i18n import translate

        source = "사용자를 선택하면 해당 계정의 사용 추이를 표시합니다.\n 프로세스 이름은 최대 5분 간격으로 갱신합니다."
        self.assertIn("Select an account", translate(source, "en"))
        self.assertNotIn("프로세스", translate(source, "en"))

    def test_language_return_stays_on_site(self):
        from i18n import return_path

        self.assertEqual(
            return_path("/monitor?hours=24", "localhost"), "/monitor?hours=24"
        )
        for target in [
            "https://outside.example/monitor",
            "//outside.example/",
            "/%5coutside.example",
            "javascript:alert(1)",
        ]:
            self.assertEqual(return_path(target, "localhost"), "/")

    def test_translation_keys_match(self):
        self.assertEqual(set(TRANSLATIONS["ko"]), set(TRANSLATIONS["en"]))


if __name__ == "__main__":
    unittest.main()
