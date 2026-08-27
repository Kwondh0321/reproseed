import pytest

from reproseed.source import normalize_github_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("owner/repository", "https://github.com/owner/repository.git"),
        ("https://github.com/owner/repository", "https://github.com/owner/repository.git"),
        ("https://github.com/owner/repository.git", "https://github.com/owner/repository.git"),
    ],
)
def test_normalize_github_url(value: str, expected: str) -> None:
    assert normalize_github_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://github.com/owner/repository",
        "https://example.com/owner/repository",
        "https://github.com/owner/repository/issues",
        "not a repository",
    ],
)
def test_normalize_github_url_rejects_unsafe_or_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_github_url(value)

