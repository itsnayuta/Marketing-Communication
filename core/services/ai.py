import json
from collections import Counter
from difflib import SequenceMatcher

from django.conf import settings

from .import_pipeline import CANONICAL_FIELDS, PII_TOKENS, suggest_mapping_locally


class AIUnavailable(RuntimeError):
    pass


class AIService:
    def __init__(self, client=None):
        self.enabled = bool(settings.AI_ENABLED and settings.OPENAI_API_KEY)
        self.model = settings.OPENAI_MODEL
        self._client = client

    @property
    def client(self):
        if not self.enabled:
            raise AIUnavailable("AI đang tắt hoặc chưa có API key.")
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(api_key=settings.OPENAI_API_KEY)
        return self._client

    @staticmethod
    def redact_samples(samples: dict) -> dict:
        return {
            header: values[:3]
            for header, values in samples.items()
            if not any(token in header.lower() for token in PII_TOKENS)
        }

    def suggest_column_mapping(self, platform: str, headers: list[str], samples=None) -> dict:
        fallback = {
            "mappings": [
                {"source_column": source, "target_field": target, "confidence": 0.7, "reason": "Khớp tên cột cục bộ"}
                for target, source in suggest_mapping_locally(headers).items()
            ],
            "source": "local",
        }
        if not self.enabled:
            return fallback
        payload = {
            "platform": platform,
            "headers": headers,
            "samples": self.redact_samples(samples or {}),
            "allowed_target_fields": list(CANONICAL_FIELDS),
        }
        try:
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": "Suggest column mappings only. Never infer or return PII. Return valid JSON."},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "column_mapping",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "mappings": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "source_column": {"type": "string"},
                                            "target_field": {"type": "string"},
                                            "confidence": {"type": "number"},
                                            "reason": {"type": "string"},
                                        },
                                        "required": ["source_column", "target_field", "confidence", "reason"],
                                        "additionalProperties": False,
                                    },
                                }
                            },
                            "required": ["mappings"],
                            "additionalProperties": False,
                        },
                    }
                },
            )
            result = json.loads(response.output_text)
            result["source"] = "ai"
            return result
        except Exception:
            fallback["source"] = "fallback"
            return fallback

    def suggest_product_mapping(self, platform: str, external_sku: str, external_product_name: str, candidates: list[dict]) -> dict:
        safe_candidates = [
            {key: str(candidate.get(key, "")) for key in ("internal_sku", "product_name", "variant_name")}
            for candidate in candidates[:100]
        ]
        needle = f"{external_sku} {external_product_name}".strip().lower()
        ranked = sorted(
            safe_candidates,
            key=lambda item: SequenceMatcher(None, needle, f"{item['internal_sku']} {item['product_name']} {item['variant_name']}".lower()).ratio(),
            reverse=True,
        )[:3]
        fallback = {
            "suggestions": [
                {
                    "internal_sku": item["internal_sku"],
                    "confidence": round(SequenceMatcher(None, needle, f"{item['internal_sku']} {item['product_name']} {item['variant_name']}".lower()).ratio(), 4),
                    "reason": "Độ tương đồng tên/SKU cục bộ",
                }
                for item in ranked
            ],
            "source": "local",
        }
        if not self.enabled:
            return fallback
        payload = {
            "platform": platform,
            "external_sku": external_sku,
            "external_product_name": external_product_name,
            "candidates": safe_candidates,
        }
        try:
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": "Suggest up to 3 product mappings from the candidates only. Never commit a mapping. Return JSON."},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                text={"format": {"type": "json_schema", "name": "product_mapping", "strict": True, "schema": {
                    "type": "object", "properties": {"suggestions": {"type": "array", "items": {
                        "type": "object", "properties": {
                            "internal_sku": {"type": "string"}, "confidence": {"type": "number"}, "reason": {"type": "string"},
                        }, "required": ["internal_sku", "confidence", "reason"], "additionalProperties": False,
                    }}}, "required": ["suggestions"], "additionalProperties": False,
                }}},
            )
            result = json.loads(response.output_text)
            allowed = {item["internal_sku"] for item in safe_candidates}
            result["suggestions"] = [item for item in result["suggestions"] if item["internal_sku"] in allowed]
            result["source"] = "ai"
            return result
        except Exception:
            fallback["source"] = "fallback"
            return fallback

    def explain_data_quality_anomalies(self, issues: list[dict]) -> dict:
        safe_issues = [
            {key: str(issue.get(key, "")) for key in ("issue_type", "severity", "field_name")}
            for issue in issues[:200]
            if not any(token in str(issue.get("field_name", "")).lower() for token in PII_TOKENS)
        ]
        counts = Counter(issue["issue_type"] for issue in safe_issues)
        top = ", ".join(f"{name}: {count}" for name, count in counts.most_common(3)) or "không có vấn đề"
        fallback = {
            "summary": f"Các nhóm vấn đề nổi bật: {top}.",
            "recommendations": ["Kiểm tra mapping cột và dữ liệu nguồn của các field xuất hiện nhiều nhất."],
            "source": "local",
        }
        if not self.enabled:
            return fallback
        try:
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": "Explain aggregate data-quality anomalies. Do not request PII and do not propose direct database changes. Return JSON."},
                    {"role": "user", "content": json.dumps({"issues": safe_issues}, ensure_ascii=False)},
                ],
                text={"format": {"type": "json_schema", "name": "quality_explanation", "strict": True, "schema": {
                    "type": "object", "properties": {
                        "summary": {"type": "string"},
                        "recommendations": {"type": "array", "items": {"type": "string"}},
                    }, "required": ["summary", "recommendations"], "additionalProperties": False,
                }}},
            )
            result = json.loads(response.output_text)
            result["source"] = "ai"
            return result
        except Exception:
            fallback["source"] = "fallback"
            return fallback

    def summarize_import_batch(self, summary: dict) -> dict:
        safe_summary = {
            key: summary.get(key, 0)
            for key in ("platform", "total_rows", "success_rows", "warning_rows", "error_rows", "duplicate_rows", "status")
        }
        fallback = {
            "summary": (
                f"Batch {safe_summary['platform']}: {safe_summary['total_rows']} dòng, "
                f"{safe_summary['success_rows']} thành công, {safe_summary['warning_rows']} cảnh báo, "
                f"{safe_summary['error_rows']} lỗi và {safe_summary['duplicate_rows']} trùng."
            ),
            "source": "local",
        }
        if not self.enabled:
            return fallback
        try:
            response = self.client.responses.create(
                model=self.model,
                input=[
                    {"role": "system", "content": "Summarize this import batch operationally in Vietnamese. Do not suggest automatic data changes. Return JSON."},
                    {"role": "user", "content": json.dumps(safe_summary, ensure_ascii=False)},
                ],
                text={"format": {"type": "json_schema", "name": "batch_summary", "strict": True, "schema": {
                    "type": "object", "properties": {"summary": {"type": "string"}},
                    "required": ["summary"], "additionalProperties": False,
                }}},
            )
            result = json.loads(response.output_text)
            result["source"] = "ai"
            return result
        except Exception:
            fallback["source"] = "fallback"
            return fallback
