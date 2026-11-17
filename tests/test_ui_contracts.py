import pathlib
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

import jinja2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import hotops
from i18n import LocalizedHTML

ROOT = pathlib.Path(__file__).resolve().parents[1]


class BatchResourceScopeTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "labs": {
                "alpha": {
                    "title": "Alpha Lab",
                    "gpu": "gpu-0",
                    "prefix": "lh-alpha-",
                    "users": [
                        {"name": "alice", "container": "lh-alpha-alice"},
                        {"name": "bob", "container": "lh-alpha-bob"},
                    ],
                }
            },
            "write_labs": ["alpha"],
            "write_gpus": ["gpu-0"],
        }

    def test_protected_lab_rejected_before_any_inspection(self):
        self.cfg["write_labs"] = []
        with (
            patch.object(hotops, "cfg", return_value=self.cfg),
            patch.object(hotops, "authorize") as auth,
            patch.object(hotops, "run") as run,
        ):
            with self.assertRaises(PermissionError):
                hotops.dispatch(
                    dict(action="resources", lab="alpha", confirm="alpha", scope="all", cpu=4, ram=16)
                )
            auth.assert_not_called()
            run.assert_not_called()

    def test_batch_shrink_without_ack_rejected_before_docker_calls(self):
        meminfo = "MemTotal:       268435456 kB\n"
        o_ok = {
            "Id": "1" * 64,
            "State": {"Running": True, "StartedAt": "t1"},
            "HostConfig": {"Memory": 8 * 1073741824, "NanoCpus": 2000000000},
        }
        o_shrink = {
            "Id": "2" * 64,
            "State": {"Running": True, "StartedAt": "t2"},
            "HostConfig": {"Memory": 32 * 1073741824, "NanoCpus": 4000000000},
        }

        def fake_auth(req):
            o = o_ok if req["user"] == "alice" else o_shrink
            return (
                self.cfg,
                self.cfg["labs"]["alpha"],
                next(u for u in self.cfg["labs"]["alpha"]["users"] if u["name"] == req["user"]),
                o,
            )

        with (
            patch.object(hotops, "cfg", return_value=self.cfg),
            patch.object(pathlib.Path, "read_text", return_value=meminfo),
            patch.object(hotops.os, "cpu_count", return_value=64),
            patch.object(hotops, "authorize", side_effect=fake_auth),
            patch.object(hotops, "run") as run,
        ):
            with self.assertRaises(ValueError):
                hotops.dispatch(
                    dict(
                        action="resources",
                        lab="alpha",
                        confirm="alpha",
                        scope="all",
                        cpu="4",
                        ram="16",
                    )
                )
            run.assert_not_called()

    def test_batch_updates_every_unique_container(self):
        meminfo = "MemTotal:       268435456 kB\n"
        o_a = {
            "Id": "1" * 64,
            "State": {"Running": True, "StartedAt": "t1"},
            "HostConfig": {"Memory": 8 * 1073741824, "NanoCpus": 2000000000},
        }
        o_b = {
            "Id": "2" * 64,
            "State": {"Running": True, "StartedAt": "t2"},
            "HostConfig": {"Memory": 8 * 1073741824, "NanoCpus": 2000000000},
        }
        seen = []

        def fake_auth(req):
            o = o_a if req["user"] == "alice" else o_b
            return (
                self.cfg,
                self.cfg["labs"]["alpha"],
                next(u for u in self.cfg["labs"]["alpha"]["users"] if u["name"] == req["user"]),
                o,
            )

        def fake_apply(req, c, s, u, o, cpu, ram):
            seen.append((u["name"], cpu, ram))
            return {"message": "CPU·메모리 한도를 적용했습니다."}

        with (
            patch.object(hotops, "cfg", return_value=self.cfg),
            patch.object(pathlib.Path, "read_text", return_value=meminfo),
            patch.object(hotops.os, "cpu_count", return_value=64),
            patch.object(hotops, "authorize", side_effect=fake_auth),
            patch.object(hotops, "_apply_container_resources", side_effect=fake_apply),
        ):
            res = hotops.dispatch(
                dict(
                    action="resources",
                    lab="alpha",
                    confirm="alpha",
                    scope="all",
                    cpu="4",
                    ram="16",
                )
            )
            self.assertEqual(
                res["message"], "연구실 전체 계정의 CPU·메모리 한도를 적용했습니다."
            )
            self.assertEqual(seen, [("alice", 4.0, 16), ("bob", 4.0, 16)])


class TemplateAndAssetContractTests(unittest.TestCase):
    def test_templates_csp_clean_and_no_unicode_box_slop(self):
        env = jinja2.Environment()
        banned_glyphs = re.compile(r"[◫◉▤▧▦▥▣♙▰◷]")
        inline_script_re = re.compile(r"<script\b(?![^>]*\bsrc=)", re.IGNORECASE)
        inline_style_attr = re.compile(r"""\sstyle\s*=\s*["']""", re.IGNORECASE)
        style_tag_re = re.compile(r"<style\b", re.IGNORECASE)

        for path in sorted((ROOT / "app/templates").glob("*.html")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(template=path.name):
                env.parse(text)
                self.assertIsNone(style_tag_re.search(text), f"Inline <style> in {path.name}")
                self.assertIsNone(inline_style_attr.search(text), f"Inline style= attribute in {path.name}")
                self.assertIsNone(inline_script_re.search(text), f"Inline <script> in {path.name}")
                self.assertIsNone(banned_glyphs.search(text), f"Legacy Unicode glyph in {path.name}")

    def test_svg_assets_are_pure_vector_xml(self):
        for svg in sorted((ROOT / "app/static/models").glob("*.svg")):
            with self.subTest(svg=svg.name):
                tree = ET.fromstring(svg.read_text(encoding="utf-8"))
                self.assertTrue(tree.tag.endswith("svg"))
                raster_images = [
                    elem for elem in tree.iter() if elem.tag.endswith("image")
                ]
                self.assertEqual(raster_images, [], f"Raster <image> found in {svg.name}")

    def test_localized_html_translates_new_navigation_and_attributes(self):
        sample = (
            '<html lang="ko">'
            '<nav aria-label="주 메뉴"><a href="/"><span>서버 현황</span></a></nav>'
            '<input type="search" placeholder="ID · 이름 · 포트 검색"/>'
            '<button>화면 도움말</button>'
            '<svg viewBox="0 0 20 20"><path d="M0 0"/><rect x="1" y="1" width="4" height="4"/></svg>'
            "</html>"
        )
        parser = LocalizedHTML("en")
        parser.feed(sample)
        rendered = "".join(parser.parts)
        self.assertIn('lang="en"', rendered)
        self.assertIn('aria-label="Primary navigation"', rendered)
        self.assertIn("Server status", rendered)
        self.assertIn('placeholder="Search ID · name · port"', rendered)
        self.assertIn("Screen guide", rendered)
        self.assertEqual(rendered.count("/>"), 3)
