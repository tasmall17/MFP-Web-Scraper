"""Fixture URLs for `mfp --self-test`.

The point of this list is to make the coverage claim falsifiable. Each entry
names the *kind* of page it stands for, so a regression tells you which class
of site broke rather than just moving a percentage.

Two entries are expected to fail. That is deliberate: a tool that claims to
capture everything is lying, and the failure path is a feature here -- those
URLs should land in failed-attempts.csv rather than silently producing an
empty note.
"""

FIXTURES = [
    {"kind": "wikipedia", "url": "https://en.wikipedia.org/wiki/Decorator_pattern"},
    {"kind": "static-blog", "url": "https://realpython.com/primer-on-python-decorators/"},
    {"kind": "docs", "url": "https://docs.python.org/3/library/functools.html"},
    {"kind": "github-readme", "url": "https://github.com/psf/requests"},
    {"kind": "arxiv", "url": "https://arxiv.org/abs/1706.03762"},
    {"kind": "news-avif", "url": "https://www.bbc.com/news"},
    {"kind": "mdn", "url": "https://developer.mozilla.org/en-US/docs/Web/CSS/position"},
    {"kind": "blog-images", "url": "https://jvns.ca/blog/2022/04/12/a-list-of-new-ish--command-line-tools/"},
    # An article, not the /archive index -- an index page has almost no prose
    # by design, so it would fail a word-count check for the wrong reason.
    {"kind": "substack", "url": "https://astralcodexten.substack.com/p/your-book-review-the-family-that"},
    # Blocks headless browsers hard; exercises the T3 stealth tier.
    {"kind": "bot-walled", "url": "https://stackoverflow.com/questions/739654/how-do-i-make-function-decorators",
     "expect_fail": True},
    {"kind": "spa", "url": "https://react.dev/learn"},
    {"kind": "long-form", "url": "https://www.gutenberg.org/files/1342/1342-h/1342-h.htm"},
    {"kind": "pep", "url": "https://peps.python.org/pep-0318/"},
    # Expected failures -- these exercise the CSV path, not the capture path.
    {"kind": "dead-link", "url": "https://example.com/this-page-does-not-exist-404",
     "expect_fail": True},
    {"kind": "hard-paywall", "url": "https://www.wsj.com/articles/nonexistent-test-article",
     "expect_fail": True},
]
