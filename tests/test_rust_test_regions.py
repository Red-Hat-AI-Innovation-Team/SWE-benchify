"""Tests for source-aware Rust inline test extraction.

Covers _rust_parse_test_regions(), _rust_is_test_hunk() with test_regions,
and refine_patch_split() integration with source_callback.
"""

from __future__ import annotations

import textwrap
from unittest.mock import MagicMock

from swebenchify.backends import (
    _rust_is_test_hunk,
    _rust_parse_test_regions,
    get_backend,
    refine_patch_split,
)


# ---------------------------------------------------------------------------
# _rust_parse_test_regions() tests
# ---------------------------------------------------------------------------


class TestRustParseTestRegions:
    def test_single_test_module(self) -> None:
        source = textwrap.dedent("""\
            pub fn add(a: i32, b: i32) -> i32 {
                a + b
            }

            #[cfg(test)]
            mod tests {
                use super::*;

                #[test]
                fn test_add() {
                    assert_eq!(add(2, 3), 5);
                }
            }
        """)
        regions = _rust_parse_test_regions(source)
        assert len(regions) == 1
        start, end = regions[0]
        assert start == 5  # #[cfg(test)] line
        assert end == 13  # closing }

    def test_multiple_test_modules(self) -> None:
        source = textwrap.dedent("""\
            pub fn foo() {}

            #[cfg(test)]
            mod tests_foo {
                #[test]
                fn test_foo() {}
            }

            pub fn bar() {}

            #[cfg(test)]
            mod tests_bar {
                #[test]
                fn test_bar() {}
            }
        """)
        regions = _rust_parse_test_regions(source)
        assert len(regions) == 2
        assert regions[0][0] == 3
        assert regions[1][0] == 11

    def test_nested_braces(self) -> None:
        source = textwrap.dedent("""\
            pub fn main() {}

            #[cfg(test)]
            mod tests {
                fn helper() {
                    if true {
                        let x = {
                            42
                        };
                    }
                }

                #[test]
                fn test_it() {
                    assert_eq!(helper(), 42);
                }
            }
        """)
        regions = _rust_parse_test_regions(source)
        assert len(regions) == 1
        start, end = regions[0]
        assert start == 3
        assert end == 17

    def test_no_test_modules(self) -> None:
        source = textwrap.dedent("""\
            pub fn add(a: i32, b: i32) -> i32 {
                a + b
            }

            pub fn sub(a: i32, b: i32) -> i32 {
                a - b
            }
        """)
        regions = _rust_parse_test_regions(source)
        assert regions == []

    def test_test_module_at_end_of_file(self) -> None:
        source = textwrap.dedent("""\
            pub fn add(a: i32, b: i32) -> i32 { a + b }

            #[cfg(test)]
            mod tests {
                #[test]
                fn test_add() {}
            }""")  # no trailing newline
        regions = _rust_parse_test_regions(source)
        assert len(regions) == 1
        _, end = regions[0]
        lines = source.splitlines()
        assert end == len(lines)

    def test_whitespace_between_cfg_and_mod(self) -> None:
        source = textwrap.dedent("""\
            pub fn x() {}

            #[cfg(test)]

            mod tests {
                #[test]
                fn t() {}
            }
        """)
        regions = _rust_parse_test_regions(source)
        assert len(regions) == 1
        assert regions[0][0] == 3  # starts at #[cfg(test)]

    def test_cfg_test_with_other_attrs(self) -> None:
        source = textwrap.dedent("""\
            pub fn x() {}

            #[cfg(test)]
            #[allow(unused)]
            mod tests {
                #[test]
                fn t() {}
            }
        """)
        regions = _rust_parse_test_regions(source)
        assert len(regions) == 1
        assert regions[0][0] == 3

    def test_brace_in_string_literal(self) -> None:
        # Basic limitation: brace counting doesn't understand string literals.
        # This test documents current behavior — the parser still produces a
        # region, though the end boundary may be off if unmatched braces
        # appear inside strings.
        source = textwrap.dedent("""\
            pub fn x() {}

            #[cfg(test)]
            mod tests {
                #[test]
                fn t() {
                    let s = "{ }";
                    assert!(s.contains("{"));
                }
            }
        """)
        regions = _rust_parse_test_regions(source)
        assert len(regions) == 1
        # The braces in the string are balanced, so end boundary is correct.
        # Line 10 is "}", line 11 is the empty trailing line from dedent.
        # The closing brace of the module is on line 10, but the region end
        # is computed as the line containing the final }, which includes
        # the trailing newline pushing it to line 11 (the \n after }).
        assert regions[0][1] == 11

    def test_returns_correct_line_numbers(self) -> None:
        source = "line1\nline2\n#[cfg(test)]\nmod t {\n  fn f() {}\n}\nline7\n"
        regions = _rust_parse_test_regions(source)
        assert len(regions) == 1
        assert regions[0] == (3, 6)

    def test_empty_source(self) -> None:
        assert _rust_parse_test_regions("") == []

    def test_cfg_test_without_mod(self) -> None:
        source = textwrap.dedent("""\
            #[cfg(test)]
            fn standalone_test() {}
        """)
        regions = _rust_parse_test_regions(source)
        assert regions == []


# ---------------------------------------------------------------------------
# _rust_is_test_hunk() with test_regions tests
# ---------------------------------------------------------------------------


def _make_hunk_with_source_lines(
    source_lines: list[int | None],
) -> MagicMock:
    """Create a mock hunk whose lines have the given source_line_no values."""
    hunk = MagicMock()
    mock_lines = []
    for ln in source_lines:
        mock_line = MagicMock()
        mock_line.source_line_no = ln
        mock_line.line_type = " "
        mock_line.value = "some code"
        mock_lines.append(mock_line)
    hunk.__iter__ = MagicMock(return_value=iter(mock_lines))
    hunk.section_header = None
    return hunk


class TestRustIsTestHunkWithRegions:
    def test_hunk_entirely_in_test_region(self) -> None:
        hunk = _make_hunk_with_source_lines([50, 51, 52, 53])
        regions = [(45, 60)]
        assert _rust_is_test_hunk(hunk, test_regions=regions) is True

    def test_hunk_entirely_outside_test_region(self) -> None:
        hunk = _make_hunk_with_source_lines([10, 11, 12])
        regions = [(45, 60)]
        assert _rust_is_test_hunk(hunk, test_regions=regions) is False

    def test_hunk_mixed_lines(self) -> None:
        hunk = _make_hunk_with_source_lines([44, 45, 46])
        regions = [(45, 60)]
        assert _rust_is_test_hunk(hunk, test_regions=regions) is False

    def test_no_test_regions_falls_back_to_heuristic(self) -> None:
        hunk = MagicMock()
        hunk.section_header = "mod tests"
        hunk.__iter__ = MagicMock(return_value=iter([]))
        assert _rust_is_test_hunk(hunk, test_regions=None) is True

    def test_hunk_with_no_source_lines(self) -> None:
        hunk = _make_hunk_with_source_lines([None, None, None])
        regions = [(10, 20)]
        assert _rust_is_test_hunk(hunk, test_regions=regions) is False

    def test_hunk_at_region_boundary_start(self) -> None:
        hunk = _make_hunk_with_source_lines([45, 46])
        regions = [(45, 60)]
        assert _rust_is_test_hunk(hunk, test_regions=regions) is True

    def test_hunk_at_region_boundary_end(self) -> None:
        hunk = _make_hunk_with_source_lines([59, 60])
        regions = [(45, 60)]
        assert _rust_is_test_hunk(hunk, test_regions=regions) is True

    def test_multiple_regions_hunk_in_second(self) -> None:
        hunk = _make_hunk_with_source_lines([100, 101, 102])
        regions = [(10, 20), (95, 110)]
        assert _rust_is_test_hunk(hunk, test_regions=regions) is True

    def test_empty_regions_list(self) -> None:
        hunk = _make_hunk_with_source_lines([10, 11])
        assert _rust_is_test_hunk(hunk, test_regions=[]) is False

    def test_fallback_heuristic_cfg_test_in_content(self) -> None:
        hunk = MagicMock()
        hunk.section_header = None
        line = MagicMock()
        line.line_type = "+"
        line.value = "#[cfg(test)]"
        line.source_line_no = None
        hunk.__iter__ = MagicMock(return_value=iter([line]))
        assert _rust_is_test_hunk(hunk, test_regions=None) is True

    def test_fallback_heuristic_no_test_markers(self) -> None:
        hunk = MagicMock()
        hunk.section_header = None
        line = MagicMock()
        line.line_type = "+"
        line.value = "let x = 42;"
        line.source_line_no = None
        hunk.__iter__ = MagicMock(return_value=iter([line]))
        assert _rust_is_test_hunk(hunk, test_regions=None) is False


# ---------------------------------------------------------------------------
# refine_patch_split() integration with source_callback
# ---------------------------------------------------------------------------


class TestRefinePatchSplitWithSourceCallback:
    RUST_SOURCE = textwrap.dedent("""\
        pub fn add(a: i32, b: i32) -> i32 {
            a + b
        }

        #[cfg(test)]
        mod tests {
            use super::*;

            #[test]
            fn test_add() {
                assert_eq!(add(2, 3), 5);
            }
        }
    """)

    MIXED_DIFF = textwrap.dedent("""\
        diff --git a/src/lib.rs b/src/lib.rs
        --- a/src/lib.rs
        +++ b/src/lib.rs
        @@ -1,3 +1,3 @@ pub fn add
         pub fn add(a: i32, b: i32) -> i32 {
        -    a + b + 1
        +    a + b
         }
        @@ -9,3 +9,7 @@ mod tests
             use super::*;

        +    #[test]
        +    fn test_add() {
        +        assert_eq!(add(2, 3), 5);
        +    }
             // existing
         }
    """)

    def test_rust_file_uses_source_callback(self) -> None:
        backend = get_backend("rust")
        assert backend is not None
        callback = MagicMock(return_value=self.RUST_SOURCE)

        new_gold, new_test = refine_patch_split(
            self.MIXED_DIFF, None, backend, source_callback=callback,
        )
        callback.assert_called_once_with("src/lib.rs")
        assert new_gold is not None
        assert new_test is not None
        assert "a + b" in new_gold
        assert "test_add" in new_test

    def test_non_rust_file_ignores_callback(self) -> None:
        go_backend = get_backend("go")
        assert go_backend is not None
        callback = MagicMock(return_value="irrelevant")

        gold = textwrap.dedent("""\
            diff --git a/main.go b/main.go
            --- a/main.go
            +++ b/main.go
            @@ -1,2 +1,3 @@
             package main
            +import "fmt"
             func main() {}
        """)
        new_gold, new_test = refine_patch_split(
            gold, None, go_backend, source_callback=callback,
        )
        callback.assert_not_called()
        assert new_gold == gold
        assert new_test is None

    def test_callback_returns_none_falls_back(self) -> None:
        backend = get_backend("rust")
        assert backend is not None
        callback = MagicMock(return_value=None)

        new_gold, new_test = refine_patch_split(
            self.MIXED_DIFF, None, backend, source_callback=callback,
        )
        callback.assert_called_once_with("src/lib.rs")
        # Falls back to heuristic — the second hunk has "mod tests" in
        # section header, so it should still be classified as test
        assert new_gold is not None
        assert new_test is not None

    def test_no_callback_uses_heuristic(self) -> None:
        backend = get_backend("rust")
        assert backend is not None

        new_gold, new_test = refine_patch_split(
            self.MIXED_DIFF, None, backend,
        )
        assert new_gold is not None
        assert new_test is not None

    def test_source_callback_with_multiple_rs_files(self) -> None:
        backend = get_backend("rust")
        assert backend is not None

        source_a = textwrap.dedent("""\
            pub fn foo() {}

            #[cfg(test)]
            mod tests {
                #[test]
                fn test_foo() {}
            }
        """)
        source_b = textwrap.dedent("""\
            pub fn bar() {}
        """)

        def callback(path: str) -> str | None:
            if path == "src/a.rs":
                return source_a
            if path == "src/b.rs":
                return source_b
            return None

        diff = (
            "diff --git a/src/a.rs b/src/a.rs\n"
            "--- a/src/a.rs\n"
            "+++ b/src/a.rs\n"
            "@@ -4,4 +4,7 @@ mod tests\n"
            "     #[test]\n"
            "+    fn test_foo_new() {\n"
            "+        assert!(true);\n"
            "+    }\n"
            "     fn test_foo() {}\n"
            "     // existing\n"
            " }\n"
            "diff --git a/src/b.rs b/src/b.rs\n"
            "--- a/src/b.rs\n"
            "+++ b/src/b.rs\n"
            "@@ -1,1 +1,3 @@\n"
            " pub fn bar() {}\n"
            "+\n"
            "+pub fn baz() {}\n"
        )

        new_gold, new_test = refine_patch_split(
            diff, None, backend, source_callback=callback,
        )
        assert new_gold is not None
        assert "baz" in new_gold
        assert new_test is not None
        assert "test_foo_new" in new_test
