"""FIX-235 — feed URL 保守规范化：不删有业务意义的参数，不误合订阅。

缺陷：重复订阅候选分组（F004）沿用内容 URL 的归一化规则——丢弃
utm_* 等查询参数、路径尾部多个斜杠一律压平。对 feed 而言查询参数
常是业务配置（RSSHub 路由的任意 query），丢参数会把两个不同订阅
错误归并为一组重复候选。

承诺：

- feed URL 分组键：host 小写、忽略 http/https、路径只折一个尾斜杠、
  查询参数逐字符保留（保守：宁可漏合并，不可错合并）；
- 参数不同 = 不同订阅，绝不归并；
- 内容 URL 的归一化（normalize_content_url，丢追踪参数）只属于内容
  域（F018 相同链接聚合 / library 疑似重复），本修复不改动其语义，
  但多尾斜杠压缩同样收敛为「只去一个」（与其 docstring 一致）。
"""

from lumirss.duplicate_suspects import DuplicateMember, find_duplicate_suspects
from lumirss.url_normalize import normalize_feed_url


def sub(feed_url: str, title: str = "源") -> DuplicateMember:
    return DuplicateMember(subscription_ref=f"s1.{title}", title=title, feed_url=feed_url)


def members_of(groups, key: str) -> set[str]:
    group = next(g for g in groups if g.key == key)
    return {m.feed_url for m in group.members}


# --- normalize_feed_url ------------------------------------------------------


def test_fix235_feed_url_folds_trailing_slash_and_case_and_scheme():
    assert (
        normalize_feed_url("https://EXAMPLE.com/feed/")
        == normalize_feed_url("http://example.com/feed")
        == "example.com/feed"
    )


def test_fix235_feed_url_keeps_query_params_verbatim():
    assert (
        normalize_feed_url("https://rsshub.example/twitter/user/a?limit=50&thread=t")
        == "rsshub.example/twitter/user/a?limit=50&thread=t"
    )


def test_fix235_feed_url_only_one_trailing_slash_is_folded():
    """只折一个尾斜杠：``/feed//`` 折成 ``/feed/`` 而非 ``/feed``
    （不过度压缩，多斜杠路径保持可区分）。"""
    double = normalize_feed_url("https://example.com/feed//")
    single = normalize_feed_url("https://example.com/feed/")
    assert double == "example.com/feed/"
    assert single == "example.com/feed"
    assert double != single


def test_fix235_feed_url_non_http_or_broken_returns_none():
    assert normalize_feed_url("ftp://example.com/feed") is None
    assert normalize_feed_url("not a url") is None
    assert normalize_feed_url("") is None


# --- 重复订阅候选分组 ---------------------------------------------------------


def test_fix235_same_feed_with_param_differs_stays_distinct():
    """查询参数有业务意义：参数不同 = 不同订阅，绝不归并。"""
    groups = find_duplicate_suspects(
        [
            sub("https://rsshub.example/twitter/user/a?limit=50", "路由 50"),
            sub("https://rsshub.example/twitter/user/a?limit=100", "路由 100"),
        ]
    )
    assert groups == []


def test_fix235_trailing_slash_and_case_still_group_together():
    groups = find_duplicate_suspects(
        [
            sub("https://EXAMPLE.com/feed/", "源 A"),
            sub("http://example.com/feed", "源 A2"),
        ]
    )
    assert len(groups) == 1
    assert members_of(groups, "example.com/feed") == {
        "https://EXAMPLE.com/feed/",
        "http://example.com/feed",
    }


def test_fix235_tracking_param_only_diff_is_also_distinct_for_feeds():
    """feed 的任意 query 都可能有业务意义：utm_* 也不丢（与内容域不同）。"""
    groups = find_duplicate_suspects(
        [
            sub("https://example.com/feed?utm_source=x", "源 A"),
            sub("https://example.com/feed", "源 A2"),
        ]
    )
    assert groups == [], "参数差异 = 不同订阅，不得归并"


def test_fix235_unparseable_urls_are_skipped_without_fabricating_groups():
    groups = find_duplicate_suspects(
        [
            sub("not a url", "坏源"),
            sub("https://example.com/feed", "好源"),
        ]
    )
    assert groups == []
