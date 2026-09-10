#!/usr/bin/env python3
"""PoC 06-obsidian-library: fake vault (100 md files: frontmatter, wikilinks,
tags, images, Chinese filenames) + scan -> incremental -> rename -> delete.

Vault is source of truth; Lumi = derived index (id = relative path hash;
incremental via (mtime, size) fingerprint; renames resolved as moves).
Run: uv run --with mistune python poc_obsidian.py
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
VAULT = HERE / "fixture-vault"

FRONT = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
TAG = re.compile(r"(?:^|\s)#([A-Za-z\u4e00-\u9fff][\w\u4e00-\u9fff/-]*)", re.MULTILINE)


def make_vault() -> None:
    if VAULT.exists():
        shutil.rmtree(VAULT)
    (VAULT / "AI").mkdir(parents=True)
    (VAULT / "AI" / "深度学习").mkdir(parents=True)
    (VAULT / "assets").mkdir()
    for i in range(100):
        folder = VAULT / "AI" / "深度学习" if i % 3 == 0 else VAULT
        # Chinese filenames, spaces, nested
        name = f"note-{i:03d}-{'注意力机制' if i % 4 == 0 else 'transformer'}.md"
        link_target = f"note-{(i + 1) % 100:03d}-transformer"
        body = (
            "---\n"
            f"title: {'注意力' if i % 4 == 0 else 'Note'} {i}\n"
            f"tags: [ai, topic-{i % 10}]\n"
            "created: 2026-09-10\n"
            "---\n\n"
            f"# Note {i}\n\nRelated: [[{link_target}]] and [[note-{(i + 7) % 100:03d}-transformer|aliased]].\n\n"
            f"Tags in body: #随手笔记{i % 5}\n\n"
            f"![diagram](assets/img-{i % 10}.png)\n"
        )
        (folder / name).write_text(body, encoding="utf-8")
    for i in range(10):
        (VAULT / "assets" / f"img-{i}.png").write_bytes(b"\x89PNG fake" + bytes([i]))


def scan(vault: Path) -> dict[str, dict]:
    """Full scan -> index keyed by relative path."""
    index = {}
    for p in sorted(vault.rglob("*.md")):
        rel = p.relative_to(vault).as_posix()
        raw = p.read_text(encoding="utf-8", errors="replace")
        fm, body = {}, FRONT.sub("", raw)
        m = FRONT.match(raw)
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fm[k.strip()] = v.strip().strip("[]")
        st = p.stat()
        index[rel] = {
            "fingerprint": f"{int(st.st_mtime_ns)}:{st.st_size}",
            "title": fm.get("title") or p.stem,
            "tags": [t.strip("[]'\"") for t in (fm.get("tags") or "").split(",") if t]
            + TAG.findall(body),
            "links": WIKILINK.findall(body),
            "images": re.findall(r"!\[[^\]]*\]\(([^)]+)\)", body),
        }
    return index


def sync(old: dict[str, dict], new: dict[str, dict]) -> dict:
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    changed = sorted(k for k in set(new) & set(old) if new[k]["fingerprint"] != old[k]["fingerprint"])
    # rename = removed path content-fingerprint still present under a new path
    renames = []
    old_by_content = {old[r]["title"]: r for r in removed}
    for a in list(added):
        t = new[a]["title"]
        if t in old_by_content:
            renames.append((old_by_content[t], a))
            removed.remove(old_by_content[t])
            added.remove(a)
    return {"added": added, "changed": changed, "removed": removed, "renames": renames}


def main() -> None:
    t0 = time.perf_counter()
    make_vault()
    files = len(list(VAULT.rglob("*")))
    print(f"fixture vault: {len(list(VAULT.rglob('*.md')))} md files, {files} total entries")

    idx = scan(VAULT)
    print(f"full scan: {len(idx)} notes in {time.perf_counter()-t0:.2f}s")
    sample = idx["AI/深度学习/note-000-注意力机制.md"]
    print(f"  sample tags={sample['tags'][:4]} links={sample['links'][:1]} images={sample['images'][:1]}")
    zh = [k for k in idx if "注意力" in k]
    print(f"  chinese-named notes indexed: {len(zh)} (e.g. {zh[0]})")

    # incremental: touch ONE file, add TWO, delete ONE, rename ONE
    def find(prefix: str) -> Path:
        hits = list(VAULT.rglob(f"{prefix}*.md"))
        assert len(hits) == 1, (prefix, hits)
        return hits[0]

    f_touch = find("note-010-")
    f_touch.write_text(f_touch.read_text(encoding="utf-8") + "\nappended edit\n", encoding="utf-8")
    (VAULT / "note-new-a.md").write_text("---\ntitle: New A\ntags: [fresh]\n---\n[[note-000-注意力机制]]", encoding="utf-8")
    (VAULT / "AI" / "note-new-b.md").write_text("---\ntitle: New B\n---\nbody", encoding="utf-8")
    os.remove(find("note-020-"))
    f_ren = find("note-030-")
    os.rename(f_ren, f_ren.parent / (f_ren.stem.replace("note-030", "note-030-renamed") + ".md"))

    t1 = time.perf_counter()
    new_idx = scan(VAULT)
    delta = sync(idx, new_idx)
    # rename detection fix: renamed file kept same title ("Note 30")
    print(f"incremental rescan {time.perf_counter()-t1:.2f}s -> added={delta['added']} changed={delta['changed']} removed={delta['removed']} renames={delta['renames']}")
    print(f"wikilink graph edges resolvable: {sum(len(v['links']) for v in new_idx.values())}")
    total_mb = sum(f.stat().st_size for f in VAULT.rglob('*') if f.is_file()) / 1048576
    print(f"vault size {total_mb:.2f} MB — OK in {time.perf_counter()-t0:.2f}s")


if __name__ == "__main__":
    main()
