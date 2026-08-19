import pytest

from insta_notify.extract.urls import (
    clean_url,
    extract_urls,
    guess_company,
    is_job_link,
    job_platform,
    rank_links,
    stitch_broken_urls,
    unwrap_redirect,
)


class TestExtract:
    def test_finds_scheme_url(self):
        assert extract_urls("apply at https://acme.com/jobs now") == [
            "https://acme.com/jobs"
        ]

    def test_finds_bare_domain_and_adds_scheme(self):
        assert extract_urls("see boards.greenhouse.io/stripe/jobs/1") == [
            "https://boards.greenhouse.io/stripe/jobs/1"
        ]

    def test_strips_trailing_sentence_punctuation(self):
        assert extract_urls("go to https://acme.com/jobs.") == ["https://acme.com/jobs"]
        assert extract_urls("(see https://acme.com/x)") == ["https://acme.com/x"]

    def test_ignores_prose_that_looks_like_a_domain(self):
        assert extract_urls("e.g. this vs. that, i.e. nothing") == []

    def test_ignores_email_addresses(self):
        assert extract_urls("mail me at foo@bar.com") == []

    def test_deduplicates_ignoring_trailing_slash_and_case(self):
        urls = extract_urls("https://a.com/x and https://a.com/x/ and https://A.com/x")
        assert urls == ["https://a.com/x"]

    def test_handles_empty_and_none_safely(self):
        assert extract_urls("") == []
        assert extract_urls(None) == []

    def test_rejects_malformed_host(self):
        assert clean_url("https://foo..com/x") == ""
        assert clean_url("notaurl") == ""
        assert clean_url("") == ""


class TestInstagramRedirect:
    def test_unwraps_l_instagram_com(self):
        wrapped = (
            "https://l.instagram.com/?u=https%3A%2F%2Fnvidia.wd5.myworkdayjobs.com"
            "%2Fen-US%2FSite%2Fjob%2FSWE_JR1&e=AT0"
        )
        assert unwrap_redirect(wrapped) == (
            "https://nvidia.wd5.myworkdayjobs.com/en-US/Site/job/SWE_JR1"
        )

    def test_unwrap_is_applied_by_clean_url(self):
        wrapped = "https://l.instagram.com/?u=https%3A%2F%2Fexample.com%2Fa"
        assert clean_url(wrapped) == "https://example.com/a"

    def test_leaves_normal_urls_alone(self):
        assert unwrap_redirect("https://acme.com/x") == "https://acme.com/x"

    def test_redirect_without_target_is_untouched(self):
        assert unwrap_redirect("https://l.instagram.com/") == "https://l.instagram.com/"


class TestStitching:
    def test_rejoins_url_split_across_lines(self):
        raw = "https://acme.wd5.myworkdayjobs.com/en-US/\nExternal/job/SWE_R9"
        assert extract_urls(stitch_broken_urls(raw)) == [
            "https://acme.wd5.myworkdayjobs.com/en-US/External/job/SWE_R9"
        ]

    def test_rejoins_space_after_scheme(self):
        assert extract_urls(stitch_broken_urls("https:// acme.com/jobs")) == [
            "https://acme.com/jobs"
        ]

    def test_empty_input(self):
        assert stitch_broken_urls("") == ""


class TestClassification:
    @pytest.mark.parametrize(
        "url,platform",
        [
            ("https://nvidia.wd5.myworkdayjobs.com/en-US/x/job/y", "Workday"),
            ("https://boards.greenhouse.io/stripe/jobs/1", "Greenhouse"),
            ("https://jobs.lever.co/figma/abc", "Lever"),
            ("https://jobs.ashbyhq.com/openai/xyz", "Ashby"),
            ("https://acme.com/careers", ""),
        ],
    )
    def test_job_platform(self, url, platform):
        assert job_platform(url) == platform
        assert is_job_link(url) is bool(platform)

    def test_guess_company_from_workday_tenant(self):
        assert guess_company("https://nvidia.wd5.myworkdayjobs.com/en-US/x") == "Nvidia"

    def test_guess_company_from_greenhouse_path(self):
        assert guess_company("https://boards.greenhouse.io/stripe/jobs/1") == "Stripe"

    def test_rank_puts_ats_links_first(self):
        ranked = rank_links(
            ["https://instagram.com/p/x", "https://jobs.lever.co/figma/a"]
        )
        assert ranked[0] == "https://jobs.lever.co/figma/a"
