from fbmp.browser import detect_block

OK = "https://www.facebook.com/marketplace/seattle/search?query=drill"


def test_normal_page():
    assert detect_block(OK, "Marketplace\nDeWalt drill\n$60", False) is None


def test_block_signals():
    assert detect_block("https://www.facebook.com/checkpoint/1501092823525282/", "", False) == "account checkpoint"
    assert detect_block("https://www.facebook.com/login/?next=x", "", False) == "redirected to login"
    assert "temporarily blocked" in detect_block(OK, "You’re Temporarily Blocked\nIt looks like…", False)
    assert detect_block(OK, "Please complete the CAPTCHA", False) == "CAPTCHA shown"
    assert detect_block(OK, "See more on Facebook", True).startswith("login form")
