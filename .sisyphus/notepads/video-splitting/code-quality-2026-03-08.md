Static analysis evidence

- mypy: PASS - Success: no issues found in 18 source files
- ruff: PASS - All checks passed
- pytest: PASS expected-baseline - 260 passed, 1 failed
- known pytest failure only: tests/test_youtube.py::TestAssignPlaylist::test_assign_playlist_success

Code review findings

- src/yt_recorder/pipeline.py: primary-account split uploads leave the original registry entry with account_id "-" and transcript_status PENDING; fetch_transcripts only processes entries with a real primary video id, so split-primary originals can never reach terminal transcript state or be cleaned.
- src/yt_recorder/adapters/youtube.py: DOM error detection treats any page text containing "daily" as a daily upload limit error, which is too broad and can false-positive on unrelated text.

Verdict

- REJECT
