"""Judge orchestrator (M7, §7.1) — model judges as first-class annotators.

The package boundary matches the milestone: everything a *model* needs that a
human does not (providers, prompt assembly, reply parsing, response cache, budget
caps, cost accounting) lives here, and nothing else in the codebase grew a
``kind == "model"`` branch. Judges reach work through the ordinary assignment
engine, so balance, golds, exclusion and the quality pipeline apply unchanged.
"""

from app.services.judges.budget import (
    BudgetStatus,
    Spend,
    check_budget,
    judge_spend,
    project_costs,
)
from app.services.judges.cache import CacheKey
from app.services.judges.configs import (
    JudgeError,
    attach_judge,
    create_judge_config,
    detach_judge,
    enrolled_judges,
    judge_display_name,
    list_judge_configs,
    new_version,
    resolve_enrollment,
    validate_budget,
)
from app.services.judges.orchestrator import RunResult, dry_run_estimate, run_judge
from app.services.judges.parsing import ParsedAnswer, ParseError, parse_response
from app.services.judges.pricing import Price, estimate_cost, resolve_price
from app.services.judges.prompt import JudgePrompt, assemble_prompt, variant_key
from app.services.judges.providers import Provider, ProviderError, build_provider, provider_names

__all__ = [
    "BudgetStatus",
    "CacheKey",
    "JudgeError",
    "JudgePrompt",
    "ParseError",
    "ParsedAnswer",
    "Price",
    "Provider",
    "ProviderError",
    "RunResult",
    "Spend",
    "assemble_prompt",
    "attach_judge",
    "build_provider",
    "check_budget",
    "create_judge_config",
    "detach_judge",
    "dry_run_estimate",
    "enrolled_judges",
    "estimate_cost",
    "judge_display_name",
    "judge_spend",
    "list_judge_configs",
    "new_version",
    "parse_response",
    "project_costs",
    "provider_names",
    "resolve_enrollment",
    "resolve_price",
    "run_judge",
    "validate_budget",
    "variant_key",
]
