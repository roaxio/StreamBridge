from streambridge import settings


def test_password_never_saved(tmp_path):
    p = tmp_path / "s.json"
    settings.save({"video_url": "https://user:pass@10.0.2.16:4747/video", "audio_url": "",
                   "username": "user", "password": "pass", "size": "Auto", "fps": 30,
                   "strict_tls": False, "remember_password": False}, p)
    text = p.read_text()
    assert ":pass@" not in text and '"pass"' not in text
    d = settings.load(p)
    assert d["video_url"] == "https://10.0.2.16:4747/video" and d["password"] == ""


def test_parse_size():
    assert settings.parse_size("Auto") is None
    assert settings.parse_size("1280x720") == (1280, 720)


def test_size_choices():
    assert [settings.parse_size(c) for c in settings.SIZE_CHOICES] == [None, (1920, 1080), (1280, 720), (640, 480)]
    assert settings.parse_size("720p") == (1280, 720)


def test_recent_lists_stripped(tmp_path):
    p = tmp_path / "s.json"
    settings.save(dict(settings.DEFAULTS, recent_video=["https://a:secret@10.0.0.2/video"]), p)
    assert "secret" not in p.read_text()


def test_log_file_masks_credentials(tmp_path, monkeypatch):
    import logging
    from pathlib import Path
    from streambridge import cli, logging_setup
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    cli.setup_logging()
    logging.getLogger("streambridge").warning("open %s failed", "https://user:pass@10.0.2.16:4747/video")
    for h in logging.getLogger("streambridge").handlers:
        h.flush()
    text = Path(logging_setup.log_file()).read_text()
    assert ":pass@" not in text and '"pass"' not in text and "https://***@10.0.2.16:4747/video" in text


def test_mic_delay_default_low_and_saved_value_kept(tmp_path):
    from streambridge import cli, jitter
    from streambridge.session import Options
    assert settings.DEFAULTS["audio_latency"] == "low" and Options().audio_latency == "low"
    assert jitter.mode(None).name == "low"
    assert cli.build_parser().parse_args([]).audio_latency == "low"
    p = tmp_path / "s.json"
    assert settings.load(p)["audio_latency"] == "low"           # new install
    settings.save(dict(settings.DEFAULTS, audio_latency="normal"), p)
    assert settings.load(p)["audio_latency"] == "normal"        # existing choice kept
