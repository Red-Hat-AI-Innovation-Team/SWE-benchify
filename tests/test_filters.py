"""Tests for swebenchify.filters -- quality filtering (Stage 5)."""

from __future__ import annotations

import json
from typing import Any

from swebenchify.config import FilterConfig
from swebenchify.filters import (
    apply_filters,
    check_import_attribute_error,
    check_new_symbol_in_tests,
    extract_new_symbols,
    get_filter_reasons,
)
from swebenchify.models import TaskInstance


def _make_instance(**overrides: Any) -> TaskInstance:
    """Build a TaskInstance with sensible defaults that pass all filters."""
    defaults: dict[str, Any] = {
        "repo": "owner/repo",
        "instance_id": "owner__repo-1",
        "base_commit": "abc123",
        "patch": "\n".join(
            [
                "diff --git a/foo.py b/foo.py",
                "--- a/foo.py",
                "+++ b/foo.py",
                "@@ -1 +1 @@",
                "-old",
                "+new",
            ]
        ),
        "test_patch": "diff --git a/test_foo.py b/test_foo.py",
        "problem_statement": (
            "This is a sufficiently long problem statement that contains "
            "enough words to pass the minimum word count filter applied by "
            "the quality filtering stage of the pipeline and it also needs "
            "to have a few more words added to ensure it reaches the forty "
            "word threshold required by the default filter configuration"
        ),
        "hints_text": "",
        "created_at": "2024-01-01T00:00:00Z",
        "version": "1.0",
        "FAIL_TO_PASS": json.dumps(["test_foo"]),
        "PASS_TO_PASS": json.dumps(["test_bar"]),
    }
    defaults.update(overrides)
    return TaskInstance(**defaults)


class TestGetFilterReasons:
    """Tests for individual filter rules via get_filter_reasons."""

    def test_passing_instance_has_no_reasons(self) -> None:
        inst = _make_instance()
        config = FilterConfig()
        reasons = get_filter_reasons(inst, config)
        assert reasons == []

    def test_short_problem_statement(self) -> None:
        inst = _make_instance(problem_statement="Too short")
        config = FilterConfig(min_problem_statement_words=40)
        reasons = get_filter_reasons(inst, config)
        assert any("too short" in r for r in reasons)

    def test_problem_statement_at_exact_threshold(self) -> None:
        words = " ".join(["word"] * 40)
        inst = _make_instance(problem_statement=words)
        config = FilterConfig(min_problem_statement_words=40)
        reasons = get_filter_reasons(inst, config)
        assert not any("too short" in r for r in reasons)

    def test_urls_in_problem_statement(self) -> None:
        inst = _make_instance(
            problem_statement="Check this https://example.com for details " * 5
        )
        config = FilterConfig()
        reasons = get_filter_reasons(inst, config)
        assert any("URLs" in r for r in reasons)

    def test_urls_allowed_when_disabled(self) -> None:
        inst = _make_instance(
            problem_statement="Check this https://example.com for details " * 5
        )
        config = FilterConfig(no_urls_in_problem=False)
        reasons = get_filter_reasons(inst, config)
        assert not any("URLs" in r for r in reasons)

    def test_shas_in_problem_statement(self) -> None:
        inst = _make_instance(
            problem_statement="After commit abcdef1 the test broke and now "
            "we need to fix this regression in the code base soon "
            "or users will be affected"
        )
        config = FilterConfig()
        reasons = get_filter_reasons(inst, config)
        assert any("SHAs" in r for r in reasons)

    def test_shas_allowed_when_disabled(self) -> None:
        inst = _make_instance(
            problem_statement="After commit abcdef1 the test broke and now "
            "we need to fix this regression in the code base soon "
            "or users will be affected"
        )
        config = FilterConfig(no_shas_in_problem=False)
        reasons = get_filter_reasons(inst, config)
        assert not any("SHAs" in r for r in reasons)

    def test_patch_too_large(self) -> None:
        large_patch = "\n".join([f"line {i}" for i in range(600)])
        inst = _make_instance(patch=large_patch)
        config = FilterConfig(max_patch_lines=500)
        reasons = get_filter_reasons(inst, config)
        assert any("too large" in r for r in reasons)

    def test_patch_at_exact_limit(self) -> None:
        patch = "\n".join([f"line {i}" for i in range(500)])
        inst = _make_instance(patch=patch)
        config = FilterConfig(max_patch_lines=500)
        reasons = get_filter_reasons(inst, config)
        assert not any("too large" in r for r in reasons)

    def test_empty_patch(self) -> None:
        inst = _make_instance(patch="")
        config = FilterConfig()
        reasons = get_filter_reasons(inst, config)
        assert any("patch too small" in r for r in reasons)

    def test_no_fail_to_pass(self) -> None:
        inst = _make_instance(FAIL_TO_PASS=json.dumps([]))
        config = FilterConfig()
        reasons = get_filter_reasons(inst, config)
        assert any("no FAIL_TO_PASS" in r for r in reasons)

    def test_invalid_fail_to_pass_json(self) -> None:
        inst = _make_instance(FAIL_TO_PASS="not valid json")
        config = FilterConfig()
        reasons = get_filter_reasons(inst, config)
        assert any("invalid FAIL_TO_PASS JSON" in r for r in reasons)

    def test_multiple_reasons(self) -> None:
        inst = _make_instance(
            problem_statement="short",
            patch="",
            FAIL_TO_PASS=json.dumps([]),
        )
        config = FilterConfig()
        reasons = get_filter_reasons(inst, config)
        assert len(reasons) >= 3

    def test_min_patch_lines_configurable(self) -> None:
        """Patch with 3 lines should fail if min_patch_lines=5."""
        inst = _make_instance(patch="line1\nline2\nline3")
        config = FilterConfig(min_patch_lines=5)
        reasons = get_filter_reasons(inst, config)
        assert any("patch too small" in r for r in reasons)

    def test_min_patch_lines_passes_at_threshold(self) -> None:
        inst = _make_instance(patch="line1\nline2\nline3")
        config = FilterConfig(min_patch_lines=3)
        reasons = get_filter_reasons(inst, config)
        assert not any("patch too small" in r for r in reasons)

    def test_min_fail_to_pass_configurable(self) -> None:
        """With min_fail_to_pass=2 and only 1 test, should be filtered."""
        inst = _make_instance(FAIL_TO_PASS=json.dumps(["test_one"]))
        config = FilterConfig(min_fail_to_pass=2)
        reasons = get_filter_reasons(inst, config)
        assert any("no FAIL_TO_PASS" in r for r in reasons)

    def test_min_fail_to_pass_passes_at_threshold(self) -> None:
        inst = _make_instance(FAIL_TO_PASS=json.dumps(["t1", "t2"]))
        config = FilterConfig(min_fail_to_pass=2)
        reasons = get_filter_reasons(inst, config)
        assert not any("no FAIL_TO_PASS" in r for r in reasons)

    def test_image_only_problem_statement_filtered(self) -> None:
        """Problem statement with only image markdown should be filtered."""
        inst = _make_instance(
            problem_statement="![screenshot](https://example.com/img.png)",
        )
        config = FilterConfig(
            min_problem_statement_words=1,
            no_image_only_problem=True,
        )
        reasons = get_filter_reasons(inst, config)
        assert any("image markdown" in r for r in reasons)

    def test_image_only_allowed_when_disabled(self) -> None:
        inst = _make_instance(
            problem_statement="![screenshot](https://example.com/img.png)",
        )
        config = FilterConfig(
            min_problem_statement_words=1,
            no_urls_in_problem=False,
            no_image_only_problem=False,
        )
        reasons = get_filter_reasons(inst, config)
        assert not any("image markdown" in r for r in reasons)

    def test_image_plus_text_not_filtered(self) -> None:
        """Problem statement with image AND text should not be filtered."""
        inst = _make_instance(
            problem_statement=(
                "![img](https://example.com/img.png) This is a real "
                "problem description with enough words to pass the "
                "minimum word count filter applied by quality filtering"
            ),
        )
        config = FilterConfig(
            no_urls_in_problem=False,
            no_image_only_problem=True,
        )
        reasons = get_filter_reasons(inst, config)
        assert not any("image markdown" in r for r in reasons)


class TestApplyFilters:
    """Tests for apply_filters with a mix of instances."""

    def test_all_pass(self) -> None:
        instances = [_make_instance(instance_id=f"owner__repo-{i}") for i in range(5)]
        config = FilterConfig()
        filtered = apply_filters(instances, config)
        assert len(filtered) == 5

    def test_some_filtered(self) -> None:
        good = _make_instance(instance_id="owner__repo-1")
        bad = _make_instance(
            instance_id="owner__repo-2",
            problem_statement="too short",
        )
        config = FilterConfig()
        filtered = apply_filters([good, bad], config)
        assert len(filtered) == 1
        assert filtered[0].instance_id == "owner__repo-1"

    def test_all_filtered(self) -> None:
        instances = [
            _make_instance(instance_id=f"owner__repo-{i}", patch="")
            for i in range(3)
        ]
        config = FilterConfig()
        filtered = apply_filters(instances, config)
        assert len(filtered) == 0

    def test_empty_input(self) -> None:
        config = FilterConfig()
        filtered = apply_filters([], config)
        assert filtered == []

    def test_custom_config_overrides(self) -> None:
        inst = _make_instance(
            problem_statement="short stmt",
        )
        # With low threshold, it should pass
        config = FilterConfig(min_problem_statement_words=2)
        filtered = apply_filters([inst], config)
        assert len(filtered) == 1

        # With default threshold, it should fail
        config = FilterConfig(min_problem_statement_words=40)
        filtered = apply_filters([inst], config)
        assert len(filtered) == 0


class TestCheckImportAttributeError:
    """Tests for the ImportError/AttributeError pre-solution log filter."""

    def test_clean_log(self) -> None:
        log = "PASSED test_foo\nFAILED test_bar - AssertionError"
        assert check_import_attribute_error(log) is None

    def test_import_error(self) -> None:
        log = "FAILED test_foo - ImportError: No module named 'missing'"
        result = check_import_attribute_error(log)
        assert result is not None
        assert "ImportError" in result

    def test_attribute_error(self) -> None:
        log = "FAILED test_bar - AttributeError: 'Foo' has no attribute 'bar'"
        result = check_import_attribute_error(log)
        assert result is not None
        assert "AttributeError" in result

    def test_empty_log(self) -> None:
        assert check_import_attribute_error("") is None

    def test_none_log(self) -> None:
        assert check_import_attribute_error(None) is None

    def test_both_errors(self) -> None:
        log = "ImportError: x\nAttributeError: y"
        result = check_import_attribute_error(log)
        assert result is not None


class TestExtractNewSymbols:
    """Tests for extracting newly-defined symbols from gold patches."""

    def test_new_function(self) -> None:
        patch = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1 +1,3 @@\n"
            " existing_line\n"
            "+def new_helper():\n"
            "+    pass\n"
        )
        assert extract_new_symbols(patch) == {"new_helper"}

    def test_new_class(self) -> None:
        patch = (
            "+class NewWidget:\n"
            "+    pass\n"
        )
        assert extract_new_symbols(patch) == {"NewWidget"}

    def test_modified_function_not_new(self) -> None:
        patch = (
            " def existing_func():\n"
            "-    return old\n"
            "+    return new\n"
        )
        assert extract_new_symbols(patch) == set()

    def test_modified_signature_not_new(self) -> None:
        """A function whose signature changed appears in both - and + lines."""
        patch = (
            "-    def process(self, data):\n"
            "-        return old_logic(data)\n"
            "+    def process(self, data, strict=False):\n"
            "+        return new_logic(data, strict)\n"
        )
        assert extract_new_symbols(patch) == set()

    def test_removed_function_not_new(self) -> None:
        patch = (
            "-def removed_func():\n"
            "-    pass\n"
        )
        assert extract_new_symbols(patch) == set()

    def test_async_def(self) -> None:
        patch = "+    async def new_handler(self):\n+        pass\n"
        assert extract_new_symbols(patch) == {"new_handler"}

    def test_modified_async_def_not_new(self) -> None:
        patch = (
            "-    async def handler(self):\n"
            "+    async def handler(self, timeout=None):\n"
        )
        assert extract_new_symbols(patch) == set()

    def test_multiple_new_symbols(self) -> None:
        patch = (
            "+def func_a():\n"
            "+    pass\n"
            "+class ClassB:\n"
            "+    pass\n"
        )
        symbols = extract_new_symbols(patch)
        assert symbols == {"func_a", "ClassB"}

    def test_empty_patch(self) -> None:
        assert extract_new_symbols("") == set()

    def test_none_patch(self) -> None:
        assert extract_new_symbols(None) == set()

    def test_indented_new_def(self) -> None:
        patch = "+    def inner_method(self):\n"
        assert extract_new_symbols(patch) == {"inner_method"}


class TestCheckNewSymbolInTests:
    """Tests for the newly-created function/class exclusion filter."""

    def test_test_references_new_symbol(self) -> None:
        patch = "+def patch_vary_header():\n+    pass\n"
        f2p = json.dumps(["tests/test_basic.py::test_patch_vary_header"])
        result = check_new_symbol_in_tests(patch, f2p)
        assert result is not None
        assert "patch_vary_header" in result

    def test_test_does_not_reference_new_symbol(self) -> None:
        patch = "+def helper_internal():\n+    pass\n"
        f2p = json.dumps(["tests/test_basic.py::test_session_vary_cookie"])
        result = check_new_symbol_in_tests(patch, f2p)
        assert result is None

    def test_short_symbol_no_false_positive(self) -> None:
        """A short symbol like 'get' should not match 'test_get_request'."""
        patch = "+def get():\n+    pass\n"
        f2p = json.dumps(["tests/test_api.py::test_get_request"])
        result = check_new_symbol_in_tests(patch, f2p)
        assert result is None

    def test_parametrized_test_still_matches(self) -> None:
        """Parametrized tests like test_foo[param] should match symbol foo."""
        patch = "+def new_handler():\n+    pass\n"
        f2p = json.dumps(["tests/test.py::test_new_handler[gzip]"])
        result = check_new_symbol_in_tests(patch, f2p)
        assert result is not None
        assert "new_handler" in result

    def test_no_new_symbols(self) -> None:
        patch = " def existing():\n-    old\n+    new\n"
        f2p = json.dumps(["tests/test.py::test_existing"])
        result = check_new_symbol_in_tests(patch, f2p)
        assert result is None

    def test_invalid_f2p_json(self) -> None:
        patch = "+def new_func():\n"
        result = check_new_symbol_in_tests(patch, "not json")
        assert result is None

    def test_empty_f2p(self) -> None:
        patch = "+def new_func():\n"
        result = check_new_symbol_in_tests(patch, "[]")
        assert result is None

    def test_filter_integration_enabled(self) -> None:
        """Instance with test referencing new symbol should be filtered."""
        inst = _make_instance(
            patch="+def brand_new_thing():\n+    pass\n",
            FAIL_TO_PASS=json.dumps(["tests/test.py::test_brand_new_thing"]),
        )
        config = FilterConfig(no_new_symbol_tests=True)
        reasons = get_filter_reasons(inst, config)
        assert any("newly-created symbol" in r for r in reasons)

    def test_filter_integration_disabled(self) -> None:
        """With filter disabled, new symbol references are allowed."""
        inst = _make_instance(
            patch="+def brand_new_thing():\n+    pass\n",
            FAIL_TO_PASS=json.dumps(["tests/test.py::test_brand_new_thing"]),
        )
        config = FilterConfig(no_new_symbol_tests=False)
        reasons = get_filter_reasons(inst, config)
        assert not any("newly-created symbol" in r for r in reasons)


# ---------------------------------------------------------------------------
# Go-specific filters
# ---------------------------------------------------------------------------

class TestExtractNewGoSymbols:
    """Tests for extract_new_go_symbols."""

    def test_new_exported_func(self) -> None:
        from swebenchify.filters import extract_new_go_symbols

        patch = "+func NewClient(addr string) *Client {\n"
        assert "NewClient" in extract_new_go_symbols(patch)

    def test_new_exported_type(self) -> None:
        from swebenchify.filters import extract_new_go_symbols

        patch = "+type Config struct {\n"
        assert "Config" in extract_new_go_symbols(patch)

    def test_unexported_func_not_included(self) -> None:
        from swebenchify.filters import extract_new_go_symbols

        patch = "+func newInternal() *X {\n"
        assert extract_new_go_symbols(patch) == set()

    def test_renamed_func_not_new(self) -> None:
        from swebenchify.filters import extract_new_go_symbols

        patch = "-func OldName() {}\n+func OldName() {}\n"
        assert "OldName" not in extract_new_go_symbols(patch)

    def test_method_receiver_func(self) -> None:
        from swebenchify.filters import extract_new_go_symbols

        patch = "+func (c *Client) NewMethod() {}\n"
        assert "NewMethod" in extract_new_go_symbols(patch)

    def test_empty_patch(self) -> None:
        from swebenchify.filters import extract_new_go_symbols

        assert extract_new_go_symbols("") == set()

    def test_none_patch(self) -> None:
        from swebenchify.filters import extract_new_go_symbols

        assert extract_new_go_symbols(None) == set()


class TestCheckGoIntroducedSymbol:
    """Tests for check_go_introduced_symbol."""

    def test_filters_when_test_references_new_symbol(self) -> None:
        from swebenchify.filters import check_go_introduced_symbol

        patch = "+func NewFoo(x int) *Foo {\n"
        f2p = json.dumps(["github.com/foo/bar.TestNewFoo"])
        result = check_go_introduced_symbol(patch, f2p)
        assert result is not None
        assert "NewFoo" in result

    def test_passes_when_no_new_symbols(self) -> None:
        from swebenchify.filters import check_go_introduced_symbol

        patch = "+// just a comment\n"
        f2p = json.dumps(["github.com/foo/bar.TestSomething"])
        assert check_go_introduced_symbol(patch, f2p) is None

    def test_passes_when_test_does_not_reference_symbol(self) -> None:
        from swebenchify.filters import check_go_introduced_symbol

        patch = "+func NewFoo() {}\n"
        f2p = json.dumps(["github.com/foo/bar.TestExisting"])
        assert check_go_introduced_symbol(patch, f2p) is None

    def test_filters_new_type_referenced_in_test(self) -> None:
        from swebenchify.filters import check_go_introduced_symbol

        patch = "+type Config struct {\n"
        f2p = json.dumps(["github.com/foo.TestConfig"])
        result = check_go_introduced_symbol(patch, f2p)
        assert result is not None

    def test_none_patch(self) -> None:
        from swebenchify.filters import check_go_introduced_symbol

        assert check_go_introduced_symbol(None, json.dumps(["TestFoo"])) is None


class TestApplyGoFilters:
    """Tests for apply_go_filters and get_go_filter_reasons."""

    def test_clean_instance_passes(self) -> None:
        from swebenchify.filters import apply_go_filters
        from swebenchify.models import ValidationResult

        inst = _make_instance()
        vr = ValidationResult(status="valid", compiled=True, FAIL_TO_PASS=["test_foo"])
        result = apply_go_filters([inst], FilterConfig(), {"owner__repo-1": vr})
        assert len(result) == 1

    def test_compiled_false_is_filtered(self) -> None:
        from swebenchify.filters import get_go_filter_reasons
        from swebenchify.models import ValidationResult

        inst = _make_instance()
        vr = ValidationResult(status="invalid", compiled=False)
        reasons = get_go_filter_reasons(inst, FilterConfig(), validation_result=vr)
        assert any("compiled" in r for r in reasons)

    def test_go_introduced_symbol_filtered(self) -> None:
        from swebenchify.filters import get_go_filter_reasons

        inst = _make_instance(
            patch="+func NewHandler() http.Handler {\n",
            FAIL_TO_PASS=json.dumps(["pkg.TestNewHandler"]),
        )
        reasons = get_go_filter_reasons(inst, FilterConfig())
        assert any("NewHandler" in r for r in reasons)

    def test_no_validation_result_skips_compiled_check(self) -> None:
        from swebenchify.filters import get_go_filter_reasons

        inst = _make_instance()
        reasons = get_go_filter_reasons(inst, FilterConfig(), validation_result=None)
        assert not any("compiled" in r for r in reasons)

    def test_standard_filters_also_applied(self) -> None:
        from swebenchify.filters import get_go_filter_reasons

        inst = _make_instance(problem_statement="Too short")
        reasons = get_go_filter_reasons(inst, FilterConfig(min_problem_statement_words=40))
        assert any("too short" in r for r in reasons)
