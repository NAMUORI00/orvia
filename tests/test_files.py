import os, pathlib, sys, tempfile, unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import filebrowser as f


@unittest.skipUnless(os.name == "posix", "Linux descriptor boundaries")
class Files(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.config = patch.object(
            f.hotops,
            "cfg",
            return_value={"labs": {"test": {"storage": str(self.root)}}},
        )
        self.config.start()
        self.mount = patch.object(f.os.path, "ismount", return_value=True)
        self.mount.start()

    def tearDown(self):
        self.mount.stop()
        self.config.stop()
        self.tmp.cleanup()

    def read(self, path=""):
        return f.inspect({"lab": "test", "path": path})

    def test_text_and_directory(self):
        (self.root / "file.txt").write_text("hello <script>")
        self.assertEqual(self.read()["entries"][0]["name"], "file.txt")
        self.assertEqual(self.read("file.txt")["text"], "hello <script>")

    def test_escape_and_hidden(self):
        for p in [
            "../etc/passwd",
            "/etc/passwd",
            ".admin/shadow",
            "x/../y",
            "x\\y",
            "lost+found",
        ]:
            with self.assertRaises(ValueError):
                self.read(p)

    def test_symlinks_and_hardlinks(self):
        (self.root / "link").symlink_to("/etc/passwd")
        with self.assertRaises(ValueError):
            self.read("link")
        (self.root / "a").write_text("secret")
        os.link(self.root / "a", self.root / "b")
        with self.assertRaises(ValueError):
            self.read("b")
        self.assertEqual(self.read()["entries"], [])

    def test_binary_and_large(self):
        for content in [b"\x00", b"x" * (f.LIMIT + 1), b"\xff"]:
            (self.root / "data").write_bytes(content)
            with self.assertRaises(ValueError):
                self.read("data")

    def test_missing_mount_or_lab(self):
        with patch.object(f.os.path, "ismount", return_value=False):
            with self.assertRaises(ValueError):
                self.read()
        with self.assertRaises(PermissionError):
            f.inspect({"lab": "other"})

    def test_special_file(self):
        os.mkfifo(self.root / "pipe")
        with self.assertRaises(ValueError):
            self.read("pipe")
