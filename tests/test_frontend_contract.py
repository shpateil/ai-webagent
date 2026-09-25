import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
HTML = (ROOT / "static/index.html").read_text()
APP = (ROOT / "static/app.js").read_text()


class FrontendContract(unittest.TestCase):
    def test_model_accordions_start_closed(self):
        ids = [
            "acc-model-body",
            "acc-ordinary-body",
            "acc-cvc-body",
            "acc-cline-body",
        ]
        for id_ in ids:
            self.assertRegex(HTML, rf'id="{id_}"[^>]*\shidden\b')
            self.assertIn(f"['{id_.replace('-body', '')}', '{id_}']", APP)
        self.assertNotIn("acc-power", HTML)
        self.assertNotIn("acc-power", APP)
        self.assertNotIn("acc-exp", HTML)
        self.assertNotIn("acc-free", HTML)

    def test_model_accordions_reset_on_init_and_open(self):
        self.assertIn("function resetSections()", APP)
        self.assertIn("body.hidden = true", APP)
        self.assertIn("body.style.display = 'none'", APP)
        self.assertIn("if (open) resetSections();", APP)
        self.assertIn("function renderProvider(kind)", APP)
        self.assertIn("providerModels[kind].push(m)", APP)
        self.assertIn("head.setAttribute('aria-expanded', 'false')", APP)

    def test_user_file_links_are_checked(self):
        block = APP[APP.index("function attList"):APP.index("function stepNode")]
        self.assertIn("safeUrl(x.url)", block)


if __name__ == "__main__":
    unittest.main()
