"""Build a credential-free release from committed source plus optional offline wheels."""

import argparse, hashlib, json, pathlib, subprocess, tempfile, zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", default="dist")
    args = parser.parse_args()
    root = pathlib.Path(__file__).resolve().parents[1]
    out = pathlib.Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    with tempfile.TemporaryDirectory() as temp:
        source = pathlib.Path(temp) / "source.zip"
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "archive",
                "--format=zip",
                "HEAD",
                "-o",
                str(source),
            ],
            check=True,
        )
        with zipfile.ZipFile(source) as z:
            files = {n: z.read(n) for n in z.namelist() if not n.endswith("/")}
    for wheel in (root / "wheels").glob("*.whl"):
        files["wheels/" + wheel.name] = wheel.read_bytes()
    files["build.json"] = json.dumps(
        {"version": args.version, "commit": commit}, indent=2
    ).encode()
    manifest = {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}
    files["manifest.json"] = json.dumps(manifest, indent=2).encode()
    archive = out / ("Orvia-" + args.version + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert all(
            hashlib.sha256(z.read(n)).hexdigest() == h for n, h in manifest.items()
        )
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".sha256").write_text(checksum + "  " + archive.name + "\n")
    print(archive)


if __name__ == "__main__":
    main()
