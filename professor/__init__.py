"""my-favorite-professor -- learn a subject from material you chose yourself.

Point it at your own references (.md, .txt, .pdf, or a web page you captured),
and it maps them into a course you read in the browser, with a Claude on the
right that you can ask about whatever section you're looking at.

The parts, roughly in the order material flows through them:

    capture/    a web page -> a readable note + a hidden, re-compilable archive
    ingest      a local file -> the same bundle shape, so everything downstream
                is identical whether it came from the web or your disk
    mirror      the second copy, into ~/Downloads
    course      the corpus -> a syllabus you can navigate
    professor   Professor-Claude: chat, expand, synthesise
    profile     what makes an explanation land for *you*, accumulated over time
    server      the local app the browser talks to

The API key lives in ~/.config/my-favorite-professor/config.json and is read
only by the server process. The browser never sees it.
"""

from __future__ import annotations

__version__ = "0.1.0"
