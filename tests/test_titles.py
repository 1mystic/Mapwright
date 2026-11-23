from mapwright import noise, titles


def test_prompt_is_cleaned_not_echoed():
    t = titles.derive_title("Hey, can you please add a multiply function to `calc.py`? Also update docs.", [{"path": "calc.py", "kind": "modified"}])
    assert t.startswith("add a multiply function") and len(t) <= 61 and "docs" not in t


def test_filler_urls_paths_fences_stripped():
    p = "now please fix the login redirect see https://example.com/x and src/auth/login.ts\n```\nlots of code\n```"
    t = titles.prompt_title(p)
    assert t is None or (t.startswith("fix the login redirect") and "http" not in t and "src/" not in t)


def test_long_or_pasted_prompt_uses_changes():
    changes = [{"path": f"apps/web/src/f{i}.ts", "kind": "modified"} for i in range(2)] + [
        {"path": f"apps/web/src/n{i}.ts", "kind": "added"} for i in range(3)]
    assert titles.derive_title("word " * 200, changes) == "Update 5 files in apps/web (+3 new)"
    pasted = "error:\n" + "\n".join(f"  at line {i}" for i in range(20))
    assert titles.derive_title(pasted, changes).startswith("Update 5 files")


def test_trivial_prompt_falls_back():
    assert titles.derive_title("ok", [{"path": "calc.py", "kind": "added"}]) == "Add calc.py"
    assert titles.derive_title("", [{"path": "a/b.py", "kind": "modified"}], ["parse_cfg"]) == "Update b.py: parse_cfg"


def test_cap_at_word_boundary():
    t = titles.derive_title("implement the new streaming exporter for the reporting pipeline with backpressure handling",
                            [{"path": "x.py", "kind": "added"}])
    assert len(t) <= 61 and t.endswith("…") and not t[:-1].endswith(" ")


def test_noise_classifier():
    for p in ["package-lock.json", "web/pnpm-lock.yaml", "Cargo.lock", "uv.lock", "static/app.min.js", "dist/app.js", "a/b.js.map",
              "bank/shards/part-0001.json", ".claude/settings.local.json", "x/__pycache__/m.pyc"]:
        assert noise.classify(p), p
    for p in ["src/app.py", "docs/guide.md", "package.json", "lib/builder.ts"]:
        assert noise.classify(p) is None, p
    assert noise.classify("data/big.json", 5000) == "data" and noise.classify("data/big.json", 10) is None
    assert noise.classify("gen/out.txt", None, lambda p: p.startswith("gen/")) == "ignored"
    real, noisy = noise.split([{"path": "a.py", "kind": "added"}, {"path": "yarn.lock", "kind": "modified"}])
    assert [c["path"] for c in real] == ["a.py"] and noisy[0]["noise"] == "lockfile"


def test_injected_harness_text_never_becomes_a_title():
    from mapwright.titles import prompt_title
    assert prompt_title('<agent-message from="a6b79">[Subagent hand-back] Both features are built</agent-message>') is None
    assert prompt_title("[SYSTEM NOTIFICATION - NOT USER INPUT] task finished") is None
    assert prompt_title('<pasted_content id="9df6">the link carries your local token\nerror: Broken pipe</pasted_content>') is None
    t = prompt_title('<pasted_content id="1">some log\nlines</pasted_content> fix the dropdown alignment in the header')
    assert t and "pasted" not in t.lower() and "dropdown" in t.lower()
    assert prompt_title('<ide_opened_file>The user opened web/index.html</ide_opened_file> add a theme toggle') .lower().startswith("add a theme toggle")
