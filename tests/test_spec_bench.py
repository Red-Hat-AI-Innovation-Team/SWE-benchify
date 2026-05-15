"""Tests for spec_bench — Docker spec generation benchmark (Phase 1.1a)."""

import pytest

from swebenchify.spec_bench import (
    BenchmarkResult,
    FieldScore,
    SpecScore,
    benchmark_specs,
    compare_install_cmd,
    compare_pip_packages,
    compare_pre_install,
    compare_python_version,
    compare_test_cmd,
    env_spec_to_bench_dict,
    extract_test_runner,
    load_ground_truth,
    normalize_install_cmd,
    normalize_pip_packages,
    normalize_python_version,
    normalize_test_cmd,
    score_spec,
)
from swebenchify.models import EnvironmentSpec


class TestNormalizePythonVersion:
    def test_major_minor(self):
        assert normalize_python_version("3.11") == "3.11"

    def test_major_minor_patch(self):
        assert normalize_python_version("3.11.4") == "3.11"

    def test_single_digit(self):
        assert normalize_python_version("3") == "3"

    def test_none(self):
        assert normalize_python_version(None) is None

    def test_whitespace(self):
        assert normalize_python_version("  3.9  ") == "3.9"


class TestNormalizeInstallCmd:
    def test_normalizes_pip(self):
        assert normalize_install_cmd("pip install -e .") == "python -m pip install -e ."

    def test_already_normalized(self):
        assert normalize_install_cmd("python -m pip install -e .") == "python -m pip install -e ."

    def test_collapses_whitespace(self):
        assert normalize_install_cmd("python -m  pip   install  -e  .") == "python -m pip install -e ."

    def test_none(self):
        assert normalize_install_cmd(None) is None


class TestNormalizeTestCmd:
    def test_basic(self):
        assert normalize_test_cmd("pytest -rA") == "pytest -rA"

    def test_whitespace(self):
        assert normalize_test_cmd("pytest   -rA   --tb=no") == "pytest -rA --tb=no"

    def test_none(self):
        assert normalize_test_cmd(None) is None


class TestExtractTestRunner:
    def test_pytest(self):
        assert extract_test_runner("pytest -rA --tb=no") == "pytest"

    def test_python_m_pytest(self):
        assert extract_test_runner("python -m pytest tests/ -x") == "pytest"

    def test_tox(self):
        assert extract_test_runner("tox --current-env -epy39 -v --") == "tox"

    def test_none(self):
        assert extract_test_runner(None) is None


class TestNormalizePipPackages:
    def test_basic(self):
        pkgs = ["setuptools==70.0.0", "Werkzeug==2.3.7", "Jinja2==3.0.1"]
        names = normalize_pip_packages(pkgs)
        assert names == {"setuptools", "werkzeug", "jinja2"}

    def test_hyphens_underscores(self):
        pkgs = ["my-package==1.0", "my_other_package>=2.0"]
        names = normalize_pip_packages(pkgs)
        assert names == {"my_package", "my_other_package"}

    def test_empty(self):
        assert normalize_pip_packages(None) == set()
        assert normalize_pip_packages([]) == set()


class TestComparePythonVersion:
    def test_exact_match(self):
        result = compare_python_version("3.11", "3.11")
        assert result.match is True

    def test_patch_stripped(self):
        result = compare_python_version("3.11.4", "3.11")
        assert result.match is True

    def test_mismatch(self):
        result = compare_python_version("3.10", "3.11")
        assert result.match is False

    def test_both_none(self):
        result = compare_python_version(None, None)
        assert result.match is True


class TestCompareInstallCmd:
    def test_exact_match(self):
        result = compare_install_cmd("python -m pip install -e .", "python -m pip install -e .")
        assert result.match is True

    def test_functional_match_editable(self):
        result = compare_install_cmd(
            "pip install -e '.[dev]'",
            "python -m pip install -e .",
        )
        assert result.match is True

    def test_editable_vs_non_editable(self):
        result = compare_install_cmd(
            "python -m pip install .",
            "python -m pip install -e .",
        )
        assert result.match is True

    def test_pip_vs_non_pip(self):
        result = compare_install_cmd(
            "make install",
            "python -m pip install -e .",
        )
        assert result.match is False

    def test_both_none(self):
        result = compare_install_cmd(None, None)
        assert result.match is True


class TestCompareTestCmd:
    def test_same_runner(self):
        result = compare_test_cmd("pytest -rA", "pytest --no-header -rA --tb=no -p no:cacheprovider")
        assert result.match is True

    def test_python_m_pytest_vs_pytest(self):
        result = compare_test_cmd("python -m pytest tests/ -x", "pytest -rA")
        assert result.match is True

    def test_different_runners(self):
        result = compare_test_cmd("tox -e py39", "pytest -rA")
        assert result.match is False


class TestComparePipPackages:
    def test_full_overlap(self):
        gen = ["setuptools==70.0.0", "Werkzeug==2.3.7", "Jinja2==3.1.2"]
        exp = ["setuptools==70.0.0", "Werkzeug==2.3.7", "Jinja2==3.0.1"]
        result = compare_pip_packages(gen, exp)
        assert result.match is True

    def test_partial_overlap_above_threshold(self):
        gen = ["setuptools==70.0.0", "Werkzeug==2.3.7", "Jinja2==3.1.2", "click==8.0.1"]
        exp = ["setuptools==70.0.0", "Werkzeug==2.3.7", "Jinja2==3.0.1", "itsdangerous==2.1.2", "click==8.0.1"]
        result = compare_pip_packages(gen, exp)
        assert result.match is True

    def test_below_threshold(self):
        gen = ["setuptools==70.0.0"]
        exp = ["setuptools==70.0.0", "Werkzeug==2.3.7", "Jinja2==3.0.1", "itsdangerous==2.1.2", "click==8.0.1", "MarkupSafe==2.1.3"]
        result = compare_pip_packages(gen, exp)
        assert result.match is False

    def test_both_empty(self):
        result = compare_pip_packages(None, None)
        assert result.match is True

    def test_no_expected(self):
        result = compare_pip_packages(["pytest"], None)
        assert result.match is True


class TestComparePreInstall:
    def test_both_empty(self):
        result = compare_pre_install(None, None)
        assert result.match is True

    def test_same_commands(self):
        cmds = ["apt-get install -y libfoo"]
        result = compare_pre_install(cmds, cmds)
        assert result.match is True

    def test_different_commands(self):
        result = compare_pre_install(["cmd1"], ["cmd2"])
        assert result.match is False


class TestScoreSpec:
    def test_perfect_score(self):
        spec = {
            "python": "3.11",
            "install": "python -m pip install -e .",
            "test_cmd": "pytest -rA",
            "pip_packages": ["setuptools==70.0.0"],
            "pre_install": [],
        }
        result = score_spec(spec, spec, "pallets/flask", "2.3")
        assert result.overall == 1.0
        assert result.matched_fields == result.total_fields

    def test_partial_match(self):
        generated = {
            "language_version": "3.10",
            "install_cmd": "python -m pip install -e .",
            "test_cmd": "pytest tests/",
        }
        expected = {
            "python": "3.11",
            "install": "python -m pip install -e .",
            "test_cmd": "pytest -rA",
        }
        result = score_spec(generated, expected, "pallets/flask", "2.3")
        assert result.overall > 0.0
        assert result.overall < 1.0

    def test_flask_like_comparison(self):
        generated = {
            "language_version": "3.11",
            "install_cmd": "pip install -e '.[async,dotenv]' -r requirements/tests.txt",
            "test_cmd": "python -m pytest tests/ -x --tb=short -q",
        }
        expected = {
            "python": "3.11",
            "install": "python -m pip install -e .",
            "test_cmd": "pytest -rA",
            "pip_packages": [
                "setuptools==70.0.0",
                "click==8.1.3",
                "itsdangerous==2.1.2",
                "Jinja2==3.1.2",
                "MarkupSafe==2.1.1",
                "Werkzeug==2.3.7",
            ],
        }
        result = score_spec(generated, expected, "pallets/flask", "2.3")
        assert result.repo == "pallets/flask"
        assert result.version == "2.3"
        python_score = next(f for f in result.field_scores if f.field == "python")
        assert python_score.match is True
        test_score = next(f for f in result.field_scores if f.field == "test_cmd")
        assert test_score.match is True


class TestBenchmarkSpecs:
    def test_basic_benchmark(self):
        ground_truth = {
            "2.0": {"python": "3.9", "install": "python -m pip install -e .", "test_cmd": "pytest -rA"},
            "2.1": {"python": "3.10", "install": "python -m pip install -e .", "test_cmd": "pytest -rA"},
        }
        generated = {
            "2.0": {"python": "3.9", "install": "python -m pip install -e .", "test_cmd": "pytest -rA"},
            "2.1": {"python": "3.9", "install": "python -m pip install -e .", "test_cmd": "pytest -rA"},
        }
        result = benchmark_specs(generated, "pallets/flask", ground_truth=ground_truth)
        assert len(result.scores) == 2
        assert result.scores[0].overall == 1.0
        assert result.scores[1].overall < 1.0

    def test_missing_version_skipped(self):
        ground_truth = {
            "2.0": {"python": "3.9", "install": "pip install -e .", "test_cmd": "pytest -rA"},
            "2.1": {"python": "3.10", "install": "pip install -e .", "test_cmd": "pytest -rA"},
        }
        generated = {
            "2.0": {"python": "3.9", "install": "pip install -e .", "test_cmd": "pytest -rA"},
        }
        result = benchmark_specs(generated, "pallets/flask", ground_truth=ground_truth)
        assert len(result.scores) == 1

    def test_empty_ground_truth(self):
        result = benchmark_specs({}, "unknown/repo", ground_truth={})
        assert result.overall_score == 0.0

    def test_field_match_rates(self):
        ground_truth = {
            "1.0": {"python": "3.9", "install": "pip install .", "test_cmd": "pytest"},
            "2.0": {"python": "3.9", "install": "pip install .", "test_cmd": "pytest"},
        }
        generated = {
            "1.0": {"python": "3.9", "install": "pip install .", "test_cmd": "pytest"},
            "2.0": {"python": "3.10", "install": "pip install .", "test_cmd": "pytest"},
        }
        result = benchmark_specs(generated, "test/repo", ground_truth=ground_truth)
        rates = result.field_match_rates
        assert rates["python"] == 0.5
        assert rates["test_cmd"] == 1.0


class TestBenchmarkResultSummary:
    def test_summary_format(self):
        result = BenchmarkResult(scores=[
            SpecScore(
                repo="pallets/flask",
                version="2.3",
                field_scores=[FieldScore("python", True, "3.11", "3.11", "3.11")],
                overall=1.0,
            )
        ])
        summary = result.summary()
        assert "pallets/flask" in summary
        assert "100%" in summary


class TestEnvSpecToBenchDict:
    def test_converts_dataclass(self):
        spec = EnvironmentSpec(
            language="python",
            language_version="3.11",
            package_manager="pip",
            install_cmd="pip install -e .",
            test_cmd="pytest tests/",
        )
        d = env_spec_to_bench_dict(spec)
        assert d["python"] == "3.11"
        assert d["install"] == "pip install -e ."
        assert d["test_cmd"] == "pytest tests/"

    def test_passthrough_dict(self):
        d = {"python": "3.9", "install": "pip install ."}
        assert env_spec_to_bench_dict(d) is d

    def test_rejects_other_types(self):
        with pytest.raises(TypeError):
            env_spec_to_bench_dict("not a spec")


class TestLoadGroundTruth:
    def test_loads_flask(self):
        truth = load_ground_truth("pallets/flask")
        if truth:
            assert "2.0" in truth
            assert "python" in truth["2.0"]
            assert truth["2.0"]["python"] == "3.9"

    def test_unknown_repo(self):
        truth = load_ground_truth("nonexistent/repo")
        assert truth == {}
