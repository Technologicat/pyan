"""Invariants for the documentation itself.

The README carries a hand-maintained table of contents, and nothing about
adding a heading prompts anyone to update it — so it drifts silently, and a
reader only finds out by clicking a link that goes nowhere.
"""

import os
import re

README = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")

# A list item that is nothing but a link to an anchor in this same document.
TOC_ENTRY = re.compile(r"^\s*- \[.*\]\(#([^)]+)\)\s*$")
ANCHOR_LINK = re.compile(r"\[[^\]]*\]\(#([^)]+)\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")


def read_readme():
    with open(README, encoding="utf-8") as f:
        return f.read().splitlines()


def slugify(title):
    """GitHub's heading-anchor rule: lowercase, drop punctuation, spaces to hyphens."""
    return re.sub(r"[^\w\s-]", "", title.strip().lower()).replace(" ", "-")


def heading_anchors(lines):
    """Every heading's anchor, in document order, with GitHub's duplicate suffixes.

    Lines inside fenced code blocks are skipped: the shell examples are full of
    ``# comment`` lines that would otherwise read as top-level headings.
    """
    anchors = []
    counts = {}
    in_fence = False
    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING.match(line)
        if not match:
            continue
        base = slugify(match.group(2))
        seen = counts.get(base, 0)
        counts[base] = seen + 1
        anchors.append(base if seen == 0 else f"{base}-{seen}")
    return anchors


def toc_anchors(lines):
    """The targets listed in the table of contents.

    The TOC is the first run of consecutive link-only list items, so an anchor
    link written anywhere else in the document is not mistaken for one.
    """
    block = []
    for line in lines:
        match = TOC_ENTRY.match(line)
        if match:
            block.append(match.group(1))
        elif block:
            break
    return block


def dangling_links(lines):
    """Anchor links anywhere in the prose that point at no heading."""
    headings = set(heading_anchors(lines))
    found = []
    in_fence = False
    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        found.extend(a for a in ANCHOR_LINK.findall(line) if a not in headings)
    return found


def toc_problems(lines):
    """Every way the table of contents can disagree with the headings."""
    headings = heading_anchors(lines)
    toc = toc_anchors(lines)
    problems = []
    if not toc:
        problems.append("no table of contents found")
    problems += [f"TOC entry points at no heading: {a}" for a in toc if a not in headings]
    problems += [f"heading missing from TOC: {a}" for a in headings if a not in toc]
    if toc != [a for a in headings if a in toc]:
        problems.append("TOC is not in document order")
    return problems


def test_readme_table_of_contents_agrees_with_its_headings():
    assert toc_problems(read_readme()) == []


def test_readme_anchor_links_all_resolve():
    """Cross-references in the prose, not only the TOC."""
    assert dangling_links(read_readme()) == []


# --- the checker itself, against documents broken on purpose -----------------
#
# A test that only ever sees a correct README cannot show that it would notice
# an incorrect one.

GOOD = """\
- [Alpha](#alpha)
- [Beta](#beta)

# Alpha

# Beta
""".splitlines()


def test_checker_accepts_a_consistent_document():
    assert toc_problems(GOOD) == []


def test_checker_notices_a_heading_absent_from_the_toc():
    lines = [line for line in GOOD if line != "- [Beta](#beta)"]
    assert any("heading missing from TOC" in p for p in toc_problems(lines))


def test_checker_notices_a_toc_entry_with_no_heading():
    lines = GOOD + ["", "Stray: [Gamma](#gamma)"]
    lines.insert(2, "- [Gamma](#gamma)")
    assert any("points at no heading" in p for p in toc_problems(lines))


def test_checker_notices_a_toc_out_of_order():
    lines = ["- [Beta](#beta)", "- [Alpha](#alpha)", "", "# Alpha", "", "# Beta"]
    assert "TOC is not in document order" in toc_problems(lines)


def test_checker_notices_a_dangling_prose_link():
    assert dangling_links(GOOD + ["", "See [Delta](#delta) for more."]) == ["delta"]


def test_checker_ignores_shell_comments_in_fenced_blocks():
    lines = GOOD + ["", "```bash", "# Generate DOT, then render it", "```"]
    assert toc_problems(lines) == []
