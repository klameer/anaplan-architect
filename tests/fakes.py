"""Made-up keys for the tests that need something key-shaped (the tracer's start-up check, the mask that redacts keys).

They are assembled from pieces on purpose. Written out whole, a made-up key looks exactly like a real one to anything
that scans a repository for secrets: this project's own export scan, and GitHub's push protection, which refused the
first publish over them. No file in the repository holds a key-shaped literal."""

FAKE_PT = "lsv2_" + "pt_" + "0123456789abcdef" * 2 + "_" + "0123456789"          # a personal access token's shape
FAKE_SK = "lsv2_" + "sk_" + "abcdef" * 5 + "ab" + "_" + "abcdefabcd"             # a service key's shape
FAKE_TR = "lsv2_" + "tr_" + "0123456789abcdef" * 2 + "_" + "0123456789"          # a tracing-only key's shape
FAKE_ANT = "sk-" + "ant-" + "abcdefghijklmnopqrstuvwxyz"                         # a model provider key's shape
