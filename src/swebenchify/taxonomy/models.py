from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaxonomyQuestion:
    id: str           # e.g. 'q01'
    text: str         # the binary question text
    category: str     # F1, F2, F3, or F4
    weight: float = 1.0


@dataclass
class TaxonomyEvaluation:
    question_id: str
    answer: bool
    confidence: float = 1.0
    evidence: str = ''


@dataclass
class TaxonomyClassification:
    change_id: str
    framework_level: str   # F0, F1, F2, F3, F4
    level_confidence: float = 0.0
    evaluations: list[TaxonomyEvaluation] = field(default_factory=list)
    reasoning: str = ''


TAXONOMY_QUESTIONS: list[TaxonomyQuestion] = [
    # F1: Local Knowledge Addition
    TaxonomyQuestion(id='q01', text='Does this change introduce new named constants, configuration keys, or feature flags?', category='F1'),
    TaxonomyQuestion(id='q02', text='Does this change add new API endpoints, CLI commands, or user-facing entry points?', category='F1'),
    TaxonomyQuestion(id='q03', text='Does this change add new error codes, status values, or enumeration members?', category='F1'),
    TaxonomyQuestion(id='q04', text='Does this change introduce domain-specific terminology or concepts in code or documentation?', category='F1'),
    TaxonomyQuestion(id='q05', text='Does this change add data schemas, database migrations, or data model fields?', category='F1'),
    # F2: Pattern or Invariant Encoding
    TaxonomyQuestion(id='q06', text='Does this change establish a new coding pattern that other code should follow?', category='F2'),
    TaxonomyQuestion(id='q07', text='Does this change modify or add validation rules, input constraints, or invariant checks?', category='F2'),
    TaxonomyQuestion(id='q08', text='Does this change introduce a new abstraction (interface, base class, trait) for others to implement?', category='F2'),
    TaxonomyQuestion(id='q09', text='Does this change add or modify test patterns, fixtures, or testing utilities?', category='F2'),
    TaxonomyQuestion(id='q10', text='Does this change establish conventions for error handling, logging, or observability?', category='F2'),
    TaxonomyQuestion(id='q11', text='Does this change add or modify documentation templates, style guides, or contribution guidelines?', category='F2'),
    # F3: Framework Mechanism Change
    TaxonomyQuestion(id='q12', text='Does this change modify the build system, package configuration, or dependency management?', category='F3'),
    TaxonomyQuestion(id='q13', text='Does this change alter CI/CD pipelines, GitHub Actions workflows, or automation scripts?', category='F3'),
    TaxonomyQuestion(id='q14', text='Does this change modify test infrastructure, test runners, or test configuration?', category='F3'),
    TaxonomyQuestion(id='q15', text='Does this change affect code generation, scaffolding, or templating tools?', category='F3'),
    TaxonomyQuestion(id='q16', text='Does this change modify linting rules, formatting configuration, or static analysis settings?', category='F3'),
    TaxonomyQuestion(id='q17', text='Does this change alter deployment configuration, infrastructure-as-code, or environment setup?', category='F3'),
    # F4: Governance or Architecture Shift
    TaxonomyQuestion(id='q18', text="Does this change restructure the project's directory layout or module organization?", category='F4'),
    TaxonomyQuestion(id='q19', text="Does this change modify the project's public API surface in a breaking way?", category='F4'),
    TaxonomyQuestion(id='q20', text="Does this change alter the project's versioning, release, or branching strategy?", category='F4'),
    TaxonomyQuestion(id='q21', text='Does this change modify governance documents (CODEOWNERS, MAINTAINERS, decision records)?', category='F4'),
    TaxonomyQuestion(id='q22', text='Does this change introduce or remove a major architectural component or subsystem?', category='F4'),
    TaxonomyQuestion(id='q23', text="Does this change alter the project's license, security policy, or compliance requirements?", category='F4'),
]
