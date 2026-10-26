from oso.core.i18n import translations


def test_all_languages_have_same_keys():
    expected = set(translations("en"))
    for language in ("es", "pt"):
        assert set(translations(language)) == expected
