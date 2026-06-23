from __future__ import annotations

from typing import Any

from sqlalchemy import select

from ..persistence.database import Database
from ..persistence.models import ModelRoute, Project, ProviderProfile
from ..persistence.repositories import RuntimeRepository, new_id
from ..providers import (
    ModelRequest,
    ModelResponse,
    ProviderCapabilities,
    ProviderConnection,
    ProviderRegistry,
)
from ..providers.base import ProviderError
from ..providers.secrets import SecretNotFound, SecretStore
from .core import BudgetExceeded, DomainError, NotFound


class ProviderService:
    def __init__(
        self,
        database: Database,
        *,
        registry: ProviderRegistry | None = None,
        secrets: SecretStore | None = None,
    ) -> None:
        self.database = database
        self.registry = registry or ProviderRegistry()
        self.secrets = secrets or SecretStore()

    def list_adapters(self) -> list[str]:
        return self.registry.names()

    def save_profile(
        self,
        *,
        project_id: str,
        key: str,
        provider: str,
        model: str,
        base_url: str = "",
        secret_ref: str = "",
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
        capabilities: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        self.registry.get(provider)
        key = key.strip()
        provider = provider.strip()
        model = model.strip()
        base_url = base_url.strip()
        secret_ref = secret_ref.strip()
        api_key = api_key.strip() if api_key else None
        if not key:
            raise DomainError("Provider 配置键不能为空")
        if not model:
            raise DomainError("模型名不能为空")
        sensitive_headers = {
            "authorization",
            "proxy-authorization",
            "x-api-key",
            "api-key",
            "anthropic-api-key",
        }
        if any(name.lower() in sensitive_headers for name in (headers or {})):
            raise DomainError("敏感请求头不能写入数据库，请改用 secret_ref")
        if secret_ref and not self._is_secret_reference(secret_ref):
            if api_key:
                raise DomainError(
                    "密钥引用不能填写明文。请使用 env:变量名 / keyring:服务/用户名，"
                    "或把 API Key 填入一次性密钥字段并留空引用。"
                )
            if self._looks_like_plain_secret(secret_ref):
                api_key = secret_ref
                secret_ref = ""
            else:
                raise DomainError(
                    "密钥引用格式无效。请填写 env:DEEPSEEK_API_KEY、"
                    "keyring:novelloom/deepseek-main，或把 API Key 填入一次性密钥字段。"
                )
        if api_key:
            reference = secret_ref or f"keyring:novelloom/{project_id}-{key}"
            try:
                self.secrets.set_keyring(reference, api_key)
            except Exception as error:
                raise DomainError(
                    "无法写入系统 Keyring。请改用环境变量引用 env:VARIABLE_NAME，"
                    "或确认当前系统凭据服务可用后重试。"
                ) from error
            secret_ref = reference
        if secret_ref and not self._is_secret_reference(secret_ref):
            raise DomainError("密钥只能保存为 env: 或 keyring: 引用")
        with self.database.session() as session:
            if session.get(Project, project_id) is None:
                raise NotFound("项目不存在")
            profile = session.scalar(
                select(ProviderProfile).where(
                    ProviderProfile.project_id == project_id, ProviderProfile.key == key
                )
            )
            if profile is None:
                profile = ProviderProfile(id=new_id(), project_id=project_id, key=key)
                session.add(profile)
            profile.provider = provider
            profile.model = model
            profile.base_url = base_url
            profile.secret_ref = secret_ref
            profile.headers = headers or {}
            profile.capabilities = ProviderCapabilities.model_validate(
                capabilities or {}
            ).model_dump()
            profile.enabled = enabled
            session.flush()
            return self._profile_dict(profile)

    def list_profiles(self, project_id: str) -> list[dict[str, Any]]:
        with self.database.session() as session:
            profiles = session.scalars(
                select(ProviderProfile)
                .where(ProviderProfile.project_id == project_id)
                .order_by(ProviderProfile.key)
            )
            return [self._profile_dict(profile) for profile in profiles]

    def set_route(
        self,
        *,
        project_id: str,
        role: str,
        primary_profile_id: str,
        fallback_profile_ids: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        fallback_profile_ids = fallback_profile_ids or []
        with self.database.session() as session:
            profile_ids = [primary_profile_id, *fallback_profile_ids]
            profiles = list(
                session.scalars(
                    select(ProviderProfile).where(
                        ProviderProfile.project_id == project_id,
                        ProviderProfile.id.in_(profile_ids),
                    )
                )
            )
            if len({profile.id for profile in profiles}) != len(set(profile_ids)):
                raise DomainError("模型路由只能引用当前项目中的 Provider Profile")
            route = session.scalar(
                select(ModelRoute).where(
                    ModelRoute.project_id == project_id, ModelRoute.role == role
                )
            )
            if route is None:
                route = ModelRoute(id=new_id(), project_id=project_id, role=role)
                session.add(route)
            route.primary_profile_id = primary_profile_id
            route.fallback_profile_ids = fallback_profile_ids
            route.parameters = parameters or {}
            session.flush()
            return {
                "id": route.id,
                "project_id": project_id,
                "role": role,
                "primary_profile_id": primary_profile_id,
                "fallback_profile_ids": fallback_profile_ids,
                "parameters": route.parameters,
            }

    async def test_profile(self, profile_id: str) -> dict[str, Any]:
        profile = self._load_profile(profile_id)
        try:
            connection = self._connection(profile)
            response = await self.registry.get(profile["provider"]).test_connection(connection)
        except (SecretNotFound, ProviderError, OSError, TimeoutError, KeyError) as error:
            return {
                "ok": False,
                "content": self._safe_error(str(error), profile["secret_ref"]),
                "input_tokens": 0,
                "output_tokens": 0,
            }
        return {
            "ok": response.content.strip().upper().startswith("OK"),
            "content": response.content[:200],
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
        }

    async def generate(
        self,
        *,
        project_id: str,
        role: str,
        request: ModelRequest,
        run_id: str | None = None,
    ) -> ModelResponse:
        route, profiles, project = self._load_route(project_id, role)
        route_parameters = route["parameters"]
        request = request.model_copy(
            update={
                "temperature": route_parameters.get("temperature", request.temperature),
                "max_output_tokens": route_parameters.get(
                    "max_output_tokens", request.max_output_tokens
                ),
                "extra": {**request.extra, **route_parameters.get("extra", {})},
            }
        )
        estimated_input = sum(len(message.content) for message in request.messages) // 3
        estimated_tokens = estimated_input + request.max_output_tokens
        self._assert_budget(project, estimated_tokens)
        errors: list[str] = []
        for profile in profiles:
            estimated_cost = self._estimate_request_cost(
                profile, estimated_input, request.max_output_tokens
            )
            if (
                project["cost_budget"] is not None
                and project["cost_used"] + estimated_cost > project["cost_budget"]
            ):
                errors.append(f"{profile['key']}: 预计费用超过项目金额硬预算")
                continue
            try:
                connection = self._connection(profile)
                response = await self.registry.get(profile["provider"]).generate(
                    connection, request
                )
                cost = self._estimate_cost(profile, response)
                self._record_usage(
                    project_id=project_id,
                    role=role,
                    profile=profile,
                    response=response,
                    cost=cost,
                    run_id=run_id,
                )
                return response
            except (ProviderError, OSError, TimeoutError, KeyError) as error:
                errors.append(f"{profile['key']}: {error}")
        if errors and all("预算" in error for error in errors):
            raise BudgetExceeded("所有模型路由的预计费用均超过项目金额硬预算")
        raise ProviderError("所有模型路由均失败: " + " | ".join(errors))

    def _load_profile(self, profile_id: str) -> dict[str, Any]:
        with self.database.session() as session:
            profile = session.get(ProviderProfile, profile_id)
            if profile is None:
                raise NotFound("Provider Profile 不存在")
            return self._profile_internal(profile)

    def _load_route(
        self, project_id: str, role: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        with self.database.session() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise NotFound("项目不存在")
            route = session.scalar(
                select(ModelRoute).where(
                    ModelRoute.project_id == project_id, ModelRoute.role == role
                )
            )
            if route is None:
                raise DomainError(f"尚未配置模型角色: {role}")
            ids = [route.primary_profile_id, *route.fallback_profile_ids]
            by_id = {
                profile.id: profile
                for profile in session.scalars(
                    select(ProviderProfile).where(ProviderProfile.id.in_(ids))
                )
            }
            profiles = [
                self._profile_internal(by_id[profile_id])
                for profile_id in ids
                if profile_id in by_id and by_id[profile_id].enabled
            ]
            if not profiles:
                raise DomainError(f"模型角色没有启用的 Provider: {role}")
            project_data = {
                "id": project.id,
                "token_budget": project.token_budget,
                "cost_budget": project.cost_budget,
                "tokens_used": project.tokens_used,
                "cost_used": project.cost_used,
            }
            return {"parameters": route.parameters}, profiles, project_data

    def _connection(self, profile: dict[str, Any]) -> ProviderConnection:
        return ProviderConnection(
            key=profile["key"],
            provider=profile["provider"],
            model=profile["model"],
            base_url=profile["base_url"],
            api_key=self.secrets.resolve(profile["secret_ref"]) if profile["secret_ref"] else "",
            headers=profile["headers"],
            capabilities=ProviderCapabilities.model_validate(profile["capabilities"]),
        )

    @staticmethod
    def _assert_budget(project: dict[str, Any], estimated_tokens: int) -> None:
        if project["tokens_used"] + estimated_tokens > project["token_budget"]:
            raise BudgetExceeded("预计调用将超过项目 token 硬预算")
        if project["cost_budget"] is not None and project["cost_used"] >= project["cost_budget"]:
            raise BudgetExceeded("项目金额预算已用尽")

    @staticmethod
    def _estimate_cost(profile: dict[str, Any], response: ModelResponse) -> float:
        capabilities = profile["capabilities"]
        input_rate = float(capabilities.get("input_cost_per_million", 0) or 0)
        output_rate = float(capabilities.get("output_cost_per_million", 0) or 0)
        return (
            response.input_tokens * input_rate + response.output_tokens * output_rate
        ) / 1_000_000

    @staticmethod
    def _estimate_request_cost(
        profile: dict[str, Any], input_tokens: int, output_tokens: int
    ) -> float:
        capabilities = profile["capabilities"]
        input_rate = float(capabilities.get("input_cost_per_million", 0) or 0)
        output_rate = float(capabilities.get("output_cost_per_million", 0) or 0)
        return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000

    def _record_usage(
        self,
        *,
        project_id: str,
        role: str,
        profile: dict[str, Any],
        response: ModelResponse,
        cost: float,
        run_id: str | None,
    ) -> None:
        with self.database.session() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise NotFound("项目不存在")
            if project.cost_budget is not None and project.cost_used + cost > project.cost_budget:
                raise BudgetExceeded("本次调用费用超过项目金额硬预算")
            RuntimeRepository(session).record_usage(
                project=project,
                role=role,
                provider_key=profile["key"],
                model=profile["model"],
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost=cost,
                run_id=run_id,
            )

    @staticmethod
    def _profile_dict(profile: ProviderProfile) -> dict[str, Any]:
        return {
            "id": profile.id,
            "project_id": profile.project_id,
            "key": profile.key,
            "provider": profile.provider,
            "model": profile.model,
            "base_url": profile.base_url,
            "secret_ref": profile.secret_ref,
            "has_secret": bool(profile.secret_ref),
            "headers": profile.headers,
            "capabilities": profile.capabilities,
            "enabled": profile.enabled,
        }

    @staticmethod
    def _profile_internal(profile: ProviderProfile) -> dict[str, Any]:
        return {
            "id": profile.id,
            "project_id": profile.project_id,
            "key": profile.key,
            "provider": profile.provider,
            "model": profile.model,
            "base_url": profile.base_url,
            "secret_ref": profile.secret_ref,
            "headers": profile.headers,
            "capabilities": profile.capabilities,
            "enabled": profile.enabled,
        }

    @staticmethod
    def _is_secret_reference(value: str) -> bool:
        return value.startswith(("env:", "keyring:"))

    @staticmethod
    def _looks_like_plain_secret(value: str) -> bool:
        stripped = value.strip()
        if not stripped or any(character.isspace() for character in stripped):
            return False
        if "_" in stripped and stripped.upper() == stripped:
            return False
        lowered = stripped.lower()
        return (
            lowered.startswith(("sk-", "sk_", "gsk_", "skant-", "sk-ant-", "aiza"))
            or lowered.startswith(("glpat-", "ghp_", "bearer "))
        )

    @staticmethod
    def _safe_error(message: str, secret_ref: str = "") -> str:
        safe = message[:300]
        if secret_ref:
            safe = safe.replace(secret_ref, "[secret-ref]")
        return safe
