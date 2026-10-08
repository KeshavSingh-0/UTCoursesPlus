from utcoursesplus.session import is_schedule_page

BASE = "https://utdirect.utexas.edu/apps/registrar/course_schedule/20272/"
TITLE = "UT Austin Registrar: Spring 2027 Course Search"


def test_detects_schedule_pages():
    assert is_schedule_page(BASE, TITLE)
    assert is_schedule_page(BASE.rstrip("/"), TITLE)
    assert is_schedule_page(
        BASE + "results/?x=1", "UT Austin Registrar: Spring 2027 Course Search"
    )


def test_rejects_login_and_other_pages():
    assert not is_schedule_page(
        "https://enterprise.login.utexas.edu/idp/profile/SAML2/Redirect/SSO", "UT Login"
    )
    assert not is_schedule_page(BASE, "Sign in")
    assert not is_schedule_page("https://utdirect.utexas.edu/apps/other/", TITLE)
