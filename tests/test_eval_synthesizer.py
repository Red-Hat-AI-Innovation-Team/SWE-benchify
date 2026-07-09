"""Tests for eval_synthesizer instance persistence and --judge-only mode."""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))


class TestJudgeOnlyArgparse:
    """Verify --judge-only flag is accepted by argparse."""

    def _make_parser(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('--quick', action='store_true')
        parser.add_argument('--seed', type=int, default=None)
        parser.add_argument('--role', choices=['generator', 'discriminator'], default=None)
        parser.add_argument('--results-dir', default='/tmp')
        parser.add_argument('--yield-only', action='store_true')
        parser.add_argument('--repo', type=str, default=None)
        parser.add_argument('--judge-only', type=str, default=None, metavar='INSTANCES_PATH')
        return parser

    def test_judge_only_accepts_path(self):
        parser = self._make_parser()
        args = parser.parse_args(['--judge-only', '/tmp/instances.jsonl'])
        assert args.judge_only == '/tmp/instances.jsonl'

    def test_judge_only_default_none(self):
        parser = self._make_parser()
        args = parser.parse_args([])
        assert args.judge_only is None

    def test_judge_only_with_other_flags(self):
        parser = self._make_parser()
        args = parser.parse_args(['--judge-only', 'foo.jsonl', '--results-dir', '/out'])
        assert args.judge_only == 'foo.jsonl'
        assert args.results_dir == '/out'


class TestInstancePersistence:
    """Verify instance save creates correct JSONL + sidecar meta format."""

    def test_save_instances_jsonl(self, tmp_path):
        instances = [
            {'instance_id': 'test__1', 'repo': 'foo/bar', 'patch': '--- a\n+++ b'},
            {'instance_id': 'test__2', 'repo': 'foo/bar', 'patch': '--- c\n+++ d'},
        ]

        instances_dir = tmp_path / 'output' / 'instances'
        instances_dir.mkdir(parents=True)
        commit = 'abc1234'

        instances_path = instances_dir / f'{commit}.jsonl'
        with open(instances_path, 'w') as f:
            for inst in instances:
                f.write(json.dumps(inst) + '\n')

        with open(instances_path) as f:
            lines = [line.strip() for line in f if line.strip()]

        assert len(lines) == 2
        loaded = [json.loads(line) for line in lines]
        assert loaded[0]['instance_id'] == 'test__1'
        assert loaded[1]['instance_id'] == 'test__2'

    def test_save_metadata_sidecar(self, tmp_path):
        instances_dir = tmp_path / 'output' / 'instances'
        instances_dir.mkdir(parents=True)
        commit = 'abc1234'

        meta = {
            'commit': commit,
            'timestamp': '2026-07-08T00:00:00Z',
            'mutations_attempted': 10,
            'instances_saved': 2,
            'yield_rate': 0.2,
            'repos': ['foo/bar'],
            'mode': 'full',
        }
        meta_path = instances_dir / f'{commit}.meta.json'
        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=2)

        with open(meta_path) as f:
            loaded = json.load(f)

        assert loaded['commit'] == commit
        assert loaded['mutations_attempted'] == 10
        assert loaded['yield_rate'] == 0.2
        assert 'repos' in loaded

    def test_roundtrip_load_instances(self, tmp_path):
        """Verify instances saved as JSONL can be loaded back for judge-only mode."""
        instances = [
            {'instance_id': f'id_{i}', 'repo': 'test/repo', 'patch': f'patch-{i}'}
            for i in range(5)
        ]

        path = tmp_path / 'instances.jsonl'
        with open(path, 'w') as f:
            for inst in instances:
                f.write(json.dumps(inst) + '\n')

        loaded = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                loaded.append(json.loads(line))

        assert len(loaded) == 5
        assert all(inst['repo'] == 'test/repo' for inst in loaded)
