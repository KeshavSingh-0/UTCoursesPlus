import httpx
import pytest

from utcoursesplus.fetch import BlockedError, Fetcher, SessionExpired


def make(handler, tmp_path, sleeps=None):
    sleeps = sleeps if sleeps is not None else []
    t = {"now": 0.0}
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    f = Fetcher(
        cache_dir=tmp_path,
        client=client,
        sleep=lambda s: (sleeps.append(s), t.update(now=t["now"] + s)),
        clock=lambda: t["now"],
    )
    return f, sleeps


def test_cache_prevents_second_request_and_throttles(tmp_path):
    calls = []
    f, sleeps = make(
        lambda r: (calls.append(1), httpx.Response(200, text="<html>ok</html>"))[1],
        tmp_path,
    )
    assert not f.get("https://x/a").from_cache
    assert f.get("https://x/a").from_cache
    f.get("https://x/b")
    assert len(calls) == 2 and sleeps and sleeps[0] >= 3.0 - 1e-9


@pytest.mark.parametrize("code", [403, 429])
def test_block_stops(tmp_path, code):
    f, _ = make(lambda r: httpx.Response(code), tmp_path)
    with pytest.raises(BlockedError):
        f.get("https://x/a")


def test_captcha_stops_and_is_not_cached(tmp_path):
    f, _ = make(lambda r: httpx.Response(200, text="Please solve this CAPTCHA"), tmp_path)
    with pytest.raises(BlockedError):
        f.get("https://x/a")
    assert not list(tmp_path.iterdir())


def test_login_redirect_means_session_expired(tmp_path):
    f, _ = make(
        lambda r: httpx.Response(302, headers={"location": "https://enterprise.login.utexas.edu/idp/x"}),
        tmp_path,
    )
    with pytest.raises(SessionExpired):
        f.get("https://x/a")
