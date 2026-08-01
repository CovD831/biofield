from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from biofield.a0_runner import ModelInvocationAudit, ProbeResponse
from biofield.evidence_task import EvidenceTaskError, load_task_bundle, score_answer
from biofield.model_probe import ProbeArm
from biofield.resources import fixture_root

MessageRole = Literal["user", "assistant"]
A0_RESPONSE_SCHEMA_VERSION = "a0.r1-plus-behavior.v1"
A0_REQUIREMENT_IDS = (
    "fact_extraction",
    "contradiction_resolution",
    "decision_synthesis",
)
A0_ACTION_TYPES = ("inspect", "cross_check", "synthesize", "escalate")


class ProbeAssetError(ValueError):
    """Raised when an A0 asset cannot be resolved without changing semantics."""


def _default_asset_path() -> Path:
    return fixture_root() / "a0" / "assets.v1.json"


def _default_r1_root() -> Path:
    return fixture_root() / "r1"


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProbeAssetError(f"{field_name} must be a non-empty string")
    return value


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProbeAssetError(f"{field_name} must be an object")
    return value


@dataclass(frozen=True)
class ModelMessage:
    role: MessageRole
    content: str

    def __post_init__(self) -> None:
        if self.role not in ("user", "assistant"):
            raise ProbeAssetError("history message role must be user or assistant")
        _require_text(self.content, "history message content")


@dataclass(frozen=True)
class RequestMaterial:
    material_id: str
    title: str
    text: str

    def __post_init__(self) -> None:
        _require_text(self.material_id, "material_id")
        _require_text(self.title, "material title")
        _require_text(self.text, "material text")


def history_length_units(messages: tuple[ModelMessage, ...]) -> int:
    """Count deterministic provider-neutral non-whitespace history units."""

    if not all(isinstance(message, ModelMessage) for message in messages):
        raise ProbeAssetError("history must contain ModelMessage values")
    return sum(
        1
        for message in messages
        for character in message.content
        if not character.isspace()
    )


@dataclass(frozen=True)
class ModelRequest:
    """Fully resolved request with no provider SDK or network dependency."""

    run_id: str
    task_asset_id: str
    task_id: str
    task_version: str
    task_title: str
    task_prompt: str
    response_schema_version: str
    response_schema_json: str
    materials: tuple[RequestMaterial, ...]
    system_prompt_id: str
    system_prompt: str
    input_id: str
    history_id: str
    history: tuple[ModelMessage, ...]
    role_induction: str
    agent_label: str
    sample_id: int
    user_prompt: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "materials", tuple(self.materials))
        object.__setattr__(self, "history", tuple(self.history))
        for field_name in (
            "run_id",
            "task_asset_id",
            "task_id",
            "task_version",
            "task_title",
            "task_prompt",
            "response_schema_version",
            "response_schema_json",
            "system_prompt_id",
            "system_prompt",
            "input_id",
            "history_id",
            "role_induction",
            "agent_label",
            "user_prompt",
        ):
            _require_text(getattr(self, field_name), field_name)
        if not self.materials or not all(
            isinstance(material, RequestMaterial) for material in self.materials
        ):
            raise ProbeAssetError("materials must contain RequestMaterial values")
        if len({material.material_id for material in self.materials}) != len(
            self.materials
        ):
            raise ProbeAssetError("request material IDs must be unique")
        if not all(isinstance(message, ModelMessage) for message in self.history):
            raise ProbeAssetError("history must contain ModelMessage values")
        if (
            isinstance(self.sample_id, bool)
            or not isinstance(self.sample_id, int)
            or self.sample_id < 0
        ):
            raise ProbeAssetError("sample_id must be a non-negative integer")
        try:
            schema = json.loads(self.response_schema_json)
        except json.JSONDecodeError as error:
            raise ProbeAssetError("response_schema_json must be valid JSON") from error
        if not isinstance(schema, dict) or schema.get("type") != "object":
            raise ProbeAssetError("response schema must describe an object")

    @property
    def messages(self) -> tuple[ModelMessage, ...]:
        return self.history + (ModelMessage(role="user", content=self.user_prompt),)

    @property
    def request_fingerprint(self) -> str:
        payload = {
            "task_asset_id": self.task_asset_id,
            "task_id": self.task_id,
            "task_version": self.task_version,
            "system_prompt_id": self.system_prompt_id,
            "system_prompt": self.system_prompt,
            "input_id": self.input_id,
            "history_id": self.history_id,
            "role_induction": self.role_induction,
            "agent_label": self.agent_label,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in self.messages
            ],
            "response_schema_version": self.response_schema_version,
            "response_schema_json": self.response_schema_json,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ProbeAssetResolver:
    """Resolve versioned ProbeArm IDs into deterministic ModelRequest values."""

    def __init__(
        self,
        *,
        asset_path: str | Path | None = None,
        r1_fixture_root: str | Path | None = None,
    ) -> None:
        self._asset_path = (
            Path(asset_path) if asset_path is not None else _default_asset_path()
        )
        self._r1_fixture_root = (
            Path(r1_fixture_root)
            if r1_fixture_root is not None
            else _default_r1_root()
        )
        self._assets = self._read_assets()
        self._validate_history_contract()

    def _read_assets(self) -> Mapping[str, Any]:
        try:
            value = json.loads(self._asset_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ProbeAssetError(
                f"A0 asset fixture not found: {self._asset_path}"
            ) from error
        except (OSError, json.JSONDecodeError) as error:
            raise ProbeAssetError(
                f"A0 asset fixture is not readable JSON: {self._asset_path}"
            ) from error
        assets = _require_mapping(value, "A0 asset fixture")
        if assets.get("asset_version") != "1":
            raise ProbeAssetError("unsupported A0 asset version")
        for category in (
            "system_prompts",
            "inputs",
            "histories",
            "role_inductions",
            "tasks",
        ):
            _require_mapping(assets.get(category), category)
        return assets

    def _category(self, name: str) -> Mapping[str, Any]:
        return _require_mapping(self._assets.get(name), name)

    def _lookup(self, category: str, asset_id: str, label: str) -> Any:
        values = self._category(category)
        try:
            return values[asset_id]
        except KeyError as error:
            raise ProbeAssetError(f"unknown {label} asset: {asset_id}") from error

    def _history(self, history_id: str) -> tuple[ModelMessage, ...]:
        raw = self._lookup("histories", history_id, "history")
        if not isinstance(raw, list):
            raise ProbeAssetError(f"history asset {history_id} must be an array")
        messages: list[ModelMessage] = []
        for item in raw:
            message = _require_mapping(item, f"history asset {history_id} message")
            messages.append(
                ModelMessage(
                    role=cast(
                        MessageRole,
                        _require_text(message.get("role"), "history role"),
                    ),
                    content=_require_text(message.get("content"), "history content"),
                )
            )
        return tuple(messages)

    def _validate_history_contract(self) -> None:
        common = self._history("history.common.v1")
        specialized = self._history("history.specialized.v1")
        neutral = self._history("history.neutral.v1")
        empty = self._history("history.empty.v1")
        if not common or not specialized or not neutral:
            raise ProbeAssetError(
                "common, specialized, and neutral histories cannot be empty"
            )
        if empty:
            raise ProbeAssetError("history.empty.v1 must contain no messages")
        lengths = tuple(
            history_length_units(history)
            for history in (common, specialized, neutral)
        )
        relative_difference = (max(lengths) - min(lengths)) / max(lengths)
        if relative_difference > 0.05:
            raise ProbeAssetError(
                "common, specialized, and neutral history lengths must be within 5%"
            )

    def resolve(self, arm: ProbeArm) -> ModelRequest:
        if not isinstance(arm, ProbeArm):
            raise ProbeAssetError("arm must be a ProbeArm")

        task_asset = _require_mapping(
            self._lookup("tasks", arm.task_id, "task"),
            f"task asset {arm.task_id}",
        )
        r1_task_id = _require_text(task_asset.get("r1_task_id"), "r1_task_id")
        task_version = _require_text(
            task_asset.get("task_version"),
            "task_version",
        )
        try:
            bundle = load_task_bundle(
                r1_task_id,
                task_version=task_version,
                fixture_root=self._r1_fixture_root,
            )
        except EvidenceTaskError as error:
            raise ProbeAssetError(
                f"cannot resolve R1 task for asset {arm.task_id}: {error}"
            ) from error

        base_system_prompt = _require_text(
            self._lookup(
                "system_prompts",
                arm.system_prompt_id,
                "system prompt",
            ),
            f"system prompt {arm.system_prompt_id}",
        )
        role_asset = _require_mapping(
            self._lookup(
                "role_inductions",
                arm.role_induction,
                "role induction",
            ),
            f"role induction {arm.role_induction}",
        )
        role_suffix = _require_text(
            role_asset.get("system_suffix"),
            "role induction system_suffix",
        )
        system_prompt = (
            f"{base_system_prompt}\n\n"
            f"运行身份标签：{arm.agent_label}。"
            "该标签仅用于实验识别，不代表预设职责。\n\n"
            f"{role_suffix}"
        )

        input_asset = _require_mapping(
            self._lookup("inputs", arm.input_id, "input"),
            f"input asset {arm.input_id}",
        )
        material_order = _require_text(
            input_asset.get("material_order"),
            "material_order",
        )
        heading = _require_text(input_asset.get("heading"), "input heading")
        source_materials = tuple(
            RequestMaterial(
                material_id=material.material_id,
                title=material.title,
                text=material.text,
            )
            for material in bundle.task.materials
        )
        if material_order == "source":
            materials = source_materials
        elif material_order == "reverse":
            materials = tuple(reversed(source_materials))
        else:
            raise ProbeAssetError(
                f"unsupported material_order for input asset {arm.input_id}"
            )

        schema_json = json.dumps(
            self._a0_response_schema(bundle.task.answer_schema),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        user_prompt = self._build_user_prompt(
            task_prompt=bundle.task.prompt,
            heading=heading,
            materials=materials,
            response_schema_json=schema_json,
        )
        history = self._history(arm.history_id)
        if arm.clear_history and history:
            raise ProbeAssetError("clear_history arm resolved to non-empty history")

        return ModelRequest(
            run_id=arm.run_id,
            task_asset_id=arm.task_id,
            task_id=bundle.task.task_id,
            task_version=bundle.task.task_version,
            task_title=bundle.task.title,
            task_prompt=bundle.task.prompt,
            response_schema_version=A0_RESPONSE_SCHEMA_VERSION,
            response_schema_json=schema_json,
            materials=materials,
            system_prompt_id=arm.system_prompt_id,
            system_prompt=system_prompt,
            input_id=arm.input_id,
            history_id=arm.history_id,
            history=history,
            role_induction=arm.role_induction,
            agent_label=arm.agent_label,
            sample_id=arm.sample_id,
            user_prompt=user_prompt,
        )

    @staticmethod
    def _a0_response_schema(task_schema: Mapping[str, Any]) -> dict[str, Any]:
        """Augment the scored R1 answer with one explicit A0 behavior choice."""

        schema = json.loads(json.dumps(task_schema, ensure_ascii=False))
        if not isinstance(schema, dict):
            raise ProbeAssetError("R1 response schema must be an object")
        properties = schema.get("properties")
        required = schema.get("required")
        if not isinstance(properties, dict) or not isinstance(required, list):
            raise ProbeAssetError("R1 response schema is missing properties or required")
        if "behavior_signature" in properties:
            raise ProbeAssetError("R1 schema already defines behavior_signature")
        properties["behavior_signature"] = {
            "type": "object",
            "additionalProperties": False,
            "required": ["requirement_id", "action_type"],
            "properties": {
                "requirement_id": {
                    "type": "string",
                    "enum": list(A0_REQUIREMENT_IDS),
                },
                "action_type": {
                    "type": "string",
                    "enum": list(A0_ACTION_TYPES),
                },
            },
        }
        required.append("behavior_signature")
        return schema

    def normalize_response(
        self,
        request: ModelRequest,
        *,
        model_id: str,
        structured_output: Mapping[str, Any],
        input_tokens: int | None,
        output_tokens: int | None,
        audit: ModelInvocationAudit | None = None,
    ) -> ProbeResponse:
        """Validate A0 behavior coordinates and score the same output as R1."""

        if not isinstance(request, ModelRequest):
            raise ProbeAssetError("request must be a ModelRequest")
        if not isinstance(structured_output, Mapping):
            raise ProbeAssetError("structured_output must be an object")
        try:
            schema = json.loads(request.response_schema_json)
            validator = Draft202012Validator(schema)
            validator.validate(dict(structured_output))
        except (json.JSONDecodeError, SchemaError) as error:
            raise ProbeAssetError("request response schema is invalid") from error
        except ValidationError as error:
            location = ".".join(str(item) for item in error.absolute_path) or "<root>"
            raise ProbeAssetError(
                f"structured_output violates response schema at {location}: "
                f"{error.message}"
            ) from error
        for field_name in ("decision", "key_facts", "contradictions"):
            if field_name not in structured_output:
                raise ProbeAssetError(
                    f"structured_output is missing R1 field {field_name}"
                )
        signature = _require_mapping(
            structured_output.get("behavior_signature"),
            "behavior_signature",
        )
        requirement_id = _require_text(
            signature.get("requirement_id"),
            "behavior_signature requirement_id",
        )
        action_type = _require_text(
            signature.get("action_type"),
            "behavior_signature action_type",
        )
        if requirement_id not in A0_REQUIREMENT_IDS:
            raise ProbeAssetError("unsupported behavior_signature requirement_id")
        if action_type not in A0_ACTION_TYPES:
            raise ProbeAssetError("unsupported behavior_signature action_type")

        try:
            bundle = load_task_bundle(
                request.task_id,
                task_version=request.task_version,
                fixture_root=self._r1_fixture_root,
            )
        except EvidenceTaskError as error:
            raise ProbeAssetError("cannot reload R1 task for scoring") from error
        score = score_answer(bundle, structured_output)
        content = json.dumps(
            dict(structured_output),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return ProbeResponse(
            model_id=model_id,
            requirement_id=requirement_id,
            action_type=action_type,
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            evidence_score=score.total_score,
            critical_fact_score=score.critical_fact_score,
            citation_score=score.citation_score,
            contradiction_score=score.contradiction_score,
            decision_score=score.decision_score,
            scoring_issues=score.issues,
            audit=audit,
        )

    @staticmethod
    def _build_user_prompt(
        *,
        task_prompt: str,
        heading: str,
        materials: tuple[RequestMaterial, ...],
        response_schema_json: str,
    ) -> str:
        sections = [task_prompt, heading]
        sections.extend(
            (
                f"[material_id={material.material_id}]\n"
                f"标题：{material.title}\n"
                f"正文：{material.text}"
            )
            for material in materials
        )
        sections.append(
            "behavior_signature 必须描述本轮形成答案时主要投入的需求维度"
            "和主要执行的动作：fact_extraction 表示事实提取，"
            "contradiction_resolution 表示矛盾解决，decision_synthesis 表示"
            "决策综合；inspect 表示检查，cross_check 表示交叉核验，"
            "synthesize 表示综合，escalate 表示升级。它不是任务主题或固定身份，"
            "也不能仅因题目提到某类工作就机械选择；请按本轮实际工作重点各选一项。"
        )
        sections.append(
            "仅返回符合以下 JSON Schema 的对象：\n" + response_schema_json
        )
        return "\n\n".join(sections)
