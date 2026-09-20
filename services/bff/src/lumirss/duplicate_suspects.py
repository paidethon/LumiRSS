"""F004 重复订阅检查器 —— 只读的重复候选发现。

规则保守（只展示，无删除/合并副作用）：

- 以 :mod:`lumirss.url_normalize` 的受控规范化为分组键（小写 host、
  去尾斜杠、忽略 http/https、丢弃已知追踪参数；签名参数绝不丢弃、
  路径不同绝不合并）；
- 仅当规范化 URL 完全相同时才归入同组；标题差异作为「差异字段」
  呈现，不参与合并判定（避免误合并同名异源）。
"""

from dataclasses import dataclass, field

from lumirss.url_normalize import normalize_content_url


@dataclass
class DuplicateMember:
    """组内一个订阅成员。"""

    subscription_ref: str
    title: str
    feed_url: str
    category_label: str | None = None


@dataclass
class DuplicateGroup:
    """一组重复候选（≥2 个成员才有意义）。"""

    key: str
    members: list[DuplicateMember] = field(default_factory=list)
    differences: list[str] = field(default_factory=lambda: ["title"])


def find_duplicate_suspects(subscriptions: list[object]) -> list[DuplicateGroup]:
    """按规范化 URL 分组；返回成员数 ≥2 的组（按成员数降序）。"""
    groups: dict[str, DuplicateGroup] = {}
    order: list[str] = []
    for subscription in subscriptions:
        feed_url = str(getattr(subscription, "feed_url", ""))
        normalized = normalize_content_url(feed_url)
        if normalized is None:
            continue  # 无法解析的 URL 保守跳过，不伪造分组
        group = groups.get(normalized)
        if group is None:
            group = DuplicateGroup(key=normalized)
            groups[normalized] = group
            order.append(normalized)
        group.members.append(
            DuplicateMember(
                subscription_ref=str(getattr(subscription, "subscription_ref", "")),
                title=str(getattr(subscription, "title", "")),
                feed_url=feed_url,
                category_label=getattr(subscription, "category_label", None),
            )
        )
    result = [groups[key] for key in order if len(groups[key].members) >= 2]
    result.sort(key=lambda g: (-len(g.members), g.key))
    return result
