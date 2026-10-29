"""Load declarative guardrails without permitting weaker runtime isolation.

The policy is not a general security policy language: mandatory invariants are
pinned in code, while an operator can only narrow the implemented tool set or
reduce resource/snapshot limits. The trusted default is loaded at server boot.
"""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_POLICY_BYTES = 64 * 1024


class PolicyError(ValueError):
    """Missing, malformed, or unsafe guardrail policy; never fall back."""


class _UniqueSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate, non-string and merge keys."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        if not isinstance(node, yaml.MappingNode):
            raise PolicyError("policy mapping expected")
        result: dict = {}
        for key_node, value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise PolicyError("YAML merge keys are not allowed")
            key = self.construct_object(key_node, deep=deep)
            if type(key) is not str:
                raise PolicyError("policy keys must be strings")
            if key in result:
                raise PolicyError(f"duplicate policy key: {key}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


class ExecutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    backend: Literal["docker"]
    network: Literal["none"]
    host_mounts: Literal[False]
    host_process_environment: Literal[False]
    read_only_rootfs: Literal[True]
    no_new_privileges: Literal[True]
    drop_all_capabilities: Literal[True]
    process_fallback: Literal[False]
    user: Literal["65534:65534"]
    allowed_tools: tuple[Literal["bash"], ...]
    max_pids: int = Field(ge=1, le=128)
    max_output_bytes: int = Field(ge=1024, le=262144, multiple_of=1024)

    @field_validator(
        "host_mounts",
        "host_process_environment",
        "read_only_rootfs",
        "no_new_privileges",
        "drop_all_capabilities",
        "process_fallback",
        mode="before",
    )
    @classmethod
    def _strict_boolean(cls, value: Any) -> Any:
        if type(value) is not bool:
            raise ValueError("isolation flags must be booleans")
        return value

    @field_validator("allowed_tools", mode="before")
    @classmethod
    def _tool_tuple(cls, value: Any) -> tuple:
        if type(value) is not list or any(type(name) is not str for name in value):
            raise ValueError("allowed_tools must be a list of tool names")
        if len(value) != len(set(value)):
            raise ValueError("allowed_tools contains duplicates")
        return tuple(value)


class WorkspacePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    mode: Literal["input_snapshot"]
    follow_symlinks: Literal[False]
    copy_back: Literal[False]
    max_entries: int = Field(ge=0, le=10000)
    max_file_bytes: int = Field(ge=0, le=67108864)

    @field_validator("follow_symlinks", "copy_back", mode="before")
    @classmethod
    def _strict_boolean(cls, value: Any) -> Any:
        if type(value) is not bool:
            raise ValueError("workspace flags must be booleans")
        return value


class GuardrailPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    execution: ExecutionPolicy
    workspace: WorkspacePolicy

    @field_validator("schema_version", mode="before")
    @classmethod
    def _strict_version(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value

    def snapshot(self) -> dict:
        """A JSON-compatible copy; callers cannot mutate the active policy."""
        return self.model_dump(mode="json")


def load_policy(path: str | Path | None = None) -> GuardrailPolicy:
    """Load the packaged policy or a trusted explicit file; reject unsafe input."""
    item = (
        resources.files("arcen").joinpath("guardrails", "policy.yaml")
        if path is None
        else Path(path)
    )
    if isinstance(item, Path) and (item.is_symlink() or item.parent.is_symlink()):
        raise PolicyError("policy file and directory cannot be symlinks")
    try:
        with item.open("rb") as stream:
            raw = stream.read(MAX_POLICY_BYTES + 1)
    except OSError as exc:
        raise PolicyError("cannot read guardrail policy") from exc
    if len(raw) > MAX_POLICY_BYTES:
        raise PolicyError("guardrail policy is too large")
    try:
        text = raw.decode("utf-8")
        # Aliases/anchors make a security policy harder to audit and permit
        # expansion attacks; explicit YAML tags are unnecessary here.
        if any(
            isinstance(token, (yaml.AliasToken, yaml.AnchorToken, yaml.TagToken))
            for token in yaml.scan(text)
        ):
            raise PolicyError("YAML aliases, anchors and explicit tags are not allowed")
        data = yaml.load(text, Loader=_UniqueSafeLoader)
        return GuardrailPolicy.model_validate(data)
    except PolicyError:
        raise
    except (UnicodeDecodeError, yaml.YAMLError, ValidationError, ValueError) as exc:
        raise PolicyError(f"invalid guardrail policy: {exc}") from exc


@lru_cache(maxsize=1)
def default_policy() -> GuardrailPolicy:
    """One validated immutable packaged snapshot per process."""
    return load_policy()
