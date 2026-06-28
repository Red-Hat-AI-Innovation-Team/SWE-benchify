"""Rust language support conformance tests.

These tests verify that all Rust-specific components work together correctly:
parser -> normaliser -> F2P computation, hunk classification, Docker image generation,
and registry round-trips.
"""


class TestRustParseToF2pPipeline:
    """Test the full pipeline from raw cargo test output to F2P list."""

    def test_parse_and_normalize_passing(self):
        """Parse passing cargo test output and normalize."""
        from swebenchify.parsers import RustTestParser, normalize_rust_f2p

        output = '''
running 3 tests
test utils::tests::test_parse_url ... ok
test config::tests::test_default ... ok
test config::tests::test_custom ... ok

test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out
'''
        parser = RustTestParser()
        result = parser.parse(output)
        assert result['compiled'] is True
        assert len(result['tests']) == 3
        # All passed, so F2P should be empty if this is the post-fix run
        failed = [k for k, v in result['tests'].items() if v == 'failed']
        assert normalize_rust_f2p(failed) == []

    def test_parse_and_normalize_failing(self):
        """Parse failing cargo test output and extract F2P candidates."""
        from swebenchify.parsers import RustTestParser, normalize_rust_f2p

        output = '''
running 4 tests
test utils::tests::test_parse_url ... FAILED
test config::tests::test_default ... ok
test config::tests::test_custom ... ok
test utils::tests::test_validate ... FAILED

test result: FAILED. 2 passed; 2 failed; 0 ignored; 0 measured; 0 filtered out
'''
        parser = RustTestParser()
        result = parser.parse(output)
        assert result['compiled'] is True
        failed = [k for k, v in result['tests'].items() if v == 'failed']
        f2p = normalize_rust_f2p(failed)
        assert len(f2p) == 2
        assert 'utils::tests::test_parse_url' in f2p
        assert 'utils::tests::test_validate' in f2p

    def test_compile_error_short_circuits(self):
        """Compile errors should result in compiled=False, no tests."""
        from swebenchify.parsers import RustTestParser

        output = '''
   Compiling my-crate v0.1.0
error[E0425]: cannot find value  in this scope
  --> src/lib.rs:10:5
   |
10 |     foo
   |     ^^^ not found in this scope
'''
        parser = RustTestParser()
        result = parser.parse(output)
        assert result['compiled'] is False
        assert len(result['tests']) == 0


class TestRustHunkClassification:
    """Test that Rust files are correctly classified as test or gold."""

    def test_integration_test_file_is_test(self):
        from swebenchify.extractor import is_test_file
        assert is_test_file('tests/test_proxy.rs') is True

    def test_source_file_is_not_test(self):
        from swebenchify.extractor import is_test_file
        assert is_test_file('src/proxy.rs') is False

    def test_lib_rs_is_not_test(self):
        """Inline mod tests {} in lib.rs is source code, not a test file."""
        from swebenchify.extractor import is_test_file
        assert is_test_file('src/lib.rs') is False

    def test_split_patch_rust_diff(self):
        """A diff with both src/ and tests/ changes splits correctly."""
        import textwrap
        from swebenchify.extractor import split_patch

        diff = textwrap.dedent("""\
            diff --git a/src/proxy.rs b/src/proxy.rs
            --- a/src/proxy.rs
            +++ b/src/proxy.rs
            @@ -10,2 +10,4 @@
             fn handle_request() {
            +    // fixed the bug
            +    validate_input();
             }
            diff --git a/tests/test_proxy.rs b/tests/test_proxy.rs
            --- a/tests/test_proxy.rs
            +++ b/tests/test_proxy.rs
            @@ -0,0 +1,4 @@
            +#[test]
            +fn test_handle_request() {
            +    assert!(handle_request().is_ok());
            +}
        """)
        gold, test = split_patch(diff)
        assert gold is not None
        assert test is not None
        assert 'src/proxy.rs' in gold
        assert 'tests/test_proxy.rs' in test
        assert 'src/proxy.rs' not in test
        assert 'tests/test_proxy.rs' not in gold


class TestRustDockerfileVariants:
    """Test Dockerfile generation via the Rust backend."""

    def test_minimal_spec(self):
        from swebenchify.backends import get_backend
        from swebenchify.models import RustEnvironmentSpec

        backend = get_backend('rust')
        spec = RustEnvironmentSpec(rust_version='1.84')
        dockerfile = backend.make_dockerfile('owner/repo', 'abc123', spec)
        assert 'FROM rust:1.84-slim' in dockerfile

    def test_no_version_uses_latest(self):
        from swebenchify.backends import get_backend
        from swebenchify.models import RustEnvironmentSpec

        backend = get_backend('rust')
        spec = RustEnvironmentSpec()  # no rust_version
        dockerfile = backend.make_dockerfile('owner/repo', 'abc123', spec)
        assert 'rust:latest' in dockerfile

    def test_with_system_deps(self):
        from swebenchify.backends import get_backend
        from swebenchify.models import RustEnvironmentSpec

        backend = get_backend('rust')
        spec = RustEnvironmentSpec(
            rust_version='1.84',
            system_dependencies=['clang', 'cmake', 'libssl-dev']
        )
        dockerfile = backend.make_dockerfile('owner/repo', 'abc123', spec)
        assert 'clang' in dockerfile
        assert 'cmake' in dockerfile
        assert 'libssl-dev' in dockerfile


class TestRustRegistryRoundTrip:
    """Test registry persistence across reloads."""

    def test_register_reload_get(self, tmp_path):
        from swebenchify.models import RustEnvironmentSpec, compute_rust_env_spec_hash
        from swebenchify.rust_registry import RustSpecRegistry

        spec = RustEnvironmentSpec(
            rust_version='1.84',
            test_cmd='cargo test --workspace',
            workspace_mode='workspace',
        )
        spec.env_spec_hash = compute_rust_env_spec_hash(spec)

        # Register
        reg1 = RustSpecRegistry(tmp_path)
        version = reg1.register('cloudflare/pingora', 'abc123', spec)
        assert version.startswith('1.84-')

        # Reload
        reg2 = RustSpecRegistry(tmp_path)
        assert reg2.get_version(spec.env_spec_hash) == version
        assert reg2.get_era_commit(spec.env_spec_hash) == 'abc123'

    def test_multiple_specs_persist(self, tmp_path):
        from swebenchify.models import RustEnvironmentSpec, compute_rust_env_spec_hash
        from swebenchify.rust_registry import RustSpecRegistry

        spec1 = RustEnvironmentSpec(rust_version='1.80', test_cmd='cargo test')
        spec1.env_spec_hash = compute_rust_env_spec_hash(spec1)

        spec2 = RustEnvironmentSpec(rust_version='1.84', test_cmd='make test')
        spec2.env_spec_hash = compute_rust_env_spec_hash(spec2)

        reg = RustSpecRegistry(tmp_path)
        v1 = reg.register('repo/a', 'aaa', spec1)
        v2 = reg.register('repo/b', 'bbb', spec2)
        assert v1 != v2

        # Reload and verify both
        reg2 = RustSpecRegistry(tmp_path)
        assert reg2.get_version(spec1.env_spec_hash) == v1
        assert reg2.get_version(spec2.env_spec_hash) == v2


class TestRustParserProtocolConformance:
    """Verify RustTestParser satisfies the TestLogParser protocol."""

    def test_has_parse_method(self):
        from swebenchify.parsers import RustTestParser
        parser = RustTestParser()
        assert hasattr(parser, 'parse')
        assert callable(parser.parse)

    def test_returns_parse_result(self):
        from swebenchify.parsers import RustTestParser
        parser = RustTestParser()
        result = parser.parse('')
        assert 'tests' in result
        assert 'compiled' in result

    def test_same_signature_as_go(self):
        """Both parsers accept str and return ParseResult."""
        from swebenchify.parsers import GoJSONParser, RustTestParser
        go_parser = GoJSONParser()
        rust_parser = RustTestParser()

        go_result = go_parser.parse('')
        rust_result = rust_parser.parse('')

        assert set(go_result.keys()) == set(rust_result.keys())
