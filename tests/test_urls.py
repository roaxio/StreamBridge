import pytest

from streambridge import urls


@pytest.mark.parametrize("u", ["http://192.168.1.5:8080/video", "https://10.0.2.16:4747/video",
                               "https://10.0.2.16:4747/audio.wav", "rtsp://cam.local/live", "rtmp://example.com/app",
                               "hls://example.com/a.m3u8", "http://[fe80::1]:8080/video"])
def test_allowed(u):
    assert urls.parse(u).host


@pytest.mark.parametrize("u", ["file:///etc/passwd", "pipe:0", "concat:a|b", "ftp://x/y", "javascript:alert(1)",
                               "", "   ", "http://", "http://a b/c", "http://x:99999/",
                               "http://x/\nHost: y", "data://text"])
def test_refused(u):
    with pytest.raises(urls.UrlError):
        urls.parse(u)


def test_credentials_in_url_masked():
    p = urls.parse("https://user:pass@10.0.2.16:4747/video")
    assert p.url == "https://user:pass@10.0.2.16:4747/video"
    assert ":pass@" not in p.display and "user:" not in p.display
    assert ":pass@" not in repr(p) and ":pass@" not in str(p)


def test_login_fields_merge_and_escape():
    p = urls.parse("https://10.0.2.16:4747/video", "ad min", "p@ss:w/rd")
    assert p.url == "https://ad%20min:p%40ss%3Aw%2Frd@10.0.2.16:4747/video"
    assert p.display == "https://***@10.0.2.16:4747/video"


@pytest.mark.parametrize("text", ["open https://user:pass@10.0.2.16:4747/video failed",
                                  "rtsp://u:p@h/x and http://a:b@c/d"])
def test_mask_text(text):
    out = urls.mask(text)
    assert ":pass@" not in out and ":p@" not in out and ":b@" not in out and "***@" in out


@pytest.mark.parametrize("h,priv", [("192.168.1.5", True), ("10.0.2.16", True), ("172.16.0.1", True),
                                    ("127.0.0.1", True), ("phone.local", True), ("169.254.1.1", True),
                                    ("8.8.8.8", False), ("example.com", False), ("fd00::1", True)])
def test_private(h, priv):
    assert urls.is_private_host(h) is priv


def test_tls_policy():
    lan = urls.parse("https://10.0.2.16:4747/video")
    pub = urls.parse("https://example.com/video")
    assert urls.ffmpeg_options(lan)["tls_verify"] == "0"
    assert urls.ffmpeg_options(lan, strict_tls=True)["tls_verify"] == "1"
    assert urls.ffmpeg_options(pub)["tls_verify"] == "1"
    assert "file" not in urls.ffmpeg_options(lan)["protocol_whitelist"].split(",")


def test_auto_http_and_helpers():
    assert urls.parse("192.168.1.5:8080/video").url == "http://192.168.1.5:8080/video"
    assert urls.normalize("  10.0.2.16:4747/video ") == "http://10.0.2.16:4747/video"
    assert urls.guess_audio_url("https://user:x@10.0.2.16:4747/video") == "https://10.0.2.16:4747/audio.wav"
    assert urls.split_credentials("https://ad:pw@h:1/v") == ("https://h:1/v", "ad", "pw")
    rec = urls.add_recent(["http://a/v"], "http://u:p@b/v")
    assert rec == ["http://b/v", "http://a/v"]


def test_out_loud_rule():
    from streambridge.platform import plays_out_loud
    assert not plays_out_loud("auto") and not plays_out_loud("CABLE Input (VB-Audio Virtual Cable)")
    assert not plays_out_loud("BlackHole 2ch") and plays_out_loud("Speakers (Realtek(R) Audio)")
