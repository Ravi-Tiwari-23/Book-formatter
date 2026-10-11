from truelogger.cache import DiskCache


def test_disk_cache_round_trips_python_value(tmp_path):
    cache = DiskCache(tmp_path)
    cache.set("document-key", {"text": "हिन्दी", "pages": 2})
    assert cache.get("document-key") == {"text": "हिन्दी", "pages": 2}


def test_disk_cache_skips_unpicklable_hot_reload_value(tmp_path):
    cache = DiskCache(tmp_path)
    assert cache.set("stale-enum", lambda: None) is False
    assert cache.get("stale-enum") is None
    assert not cache.path_for("stale-enum").exists()
    assert not cache.path_for("stale-enum").with_suffix(".tmp").exists()


def test_disk_cache_discards_incompatible_entry(tmp_path):
    cache = DiskCache(tmp_path)
    cache.path_for("broken").write_bytes(b"not a pickle")
    assert cache.get("broken") is None
    assert not cache.path_for("broken").exists()

