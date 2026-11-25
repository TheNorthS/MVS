"""细粒度授权：服务授权和服务白名单之外再与用户/角色规则相交。"""


from jsonschema.validators import validator_for

from mvs.core.schema_adapter import check_schema


def check_bounded_rule(schema: object) -> None:
    """权限规则限定为可预测的约束子集，避免在同步授权路径执行复杂正则/递归引用。"""
    if isinstance(schema, dict):
        if any(key in schema for key in ("$ref", "$dynamicRef", "pattern", "patternProperties")):
            raise ValueError("权限参数规则不允许递归引用或正则；使用enum/const/长度/数值范围等约束")
        for child in schema.values():
            check_bounded_rule(child)
    elif isinstance(schema, list):
        for child in schema:
            check_bounded_rule(child)


def validate_rules(rules: dict) -> None:
    if not isinstance(rules, dict):
        raise ValueError("权限规则必须为对象")
    for server, value in rules.items():
        if not isinstance(server, str) or not isinstance(value, dict):
            raise ValueError("服务权限规则无效")
        if set(value) - {"tools", "arguments", "resources", "prompts"}:
            raise ValueError("未知权限字段")
        for name in ("tools", "resources", "prompts"):
            if name in value and (
                not isinstance(value[name], list)
                or not all(isinstance(x, str) for x in value[name])
            ):
                raise ValueError("工具和资源授权必须为字符串列表")
        for schema in value.get("arguments", {}).values():
            check_schema(schema)
            check_bounded_rule(schema)


def permitted(
    rules: dict | None, server: str, kind: str, name: str, args: dict | None = None
) -> bool:
    if rules is None:
        return True  # 未配置细粒度规则时，沿用已有服务级授权。
    rule = rules.get(server)
    if rule is None or name not in rule.get(kind, []):
        return False
    schema = rule.get("arguments", {}).get(name)
    return args is None or schema is None or validator_for(schema)(schema).is_valid(args)
