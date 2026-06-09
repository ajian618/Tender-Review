from bid_agent.storage import sanitize_filename, sha256_bytes


def test_sha256_bytes_is_stable():
    assert sha256_bytes(b"bid-agent") == sha256_bytes(b"bid-agent")
    assert sha256_bytes(b"bid-agent") != sha256_bytes(b"other")


def test_sanitize_filename_keeps_chinese_and_removes_separators():
    assert sanitize_filename("资质/证书?.txt") == "资质_证书_.txt"
