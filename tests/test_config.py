import os

from app.config import resolve_device, parse_env_text, load_dotenv


def test_resolve_device_auto_prefers_cuda():
    assert resolve_device("auto", cuda_available=True) == "cuda"


def test_resolve_device_auto_falls_back_to_cpu():
    assert resolve_device("auto", cuda_available=False) == "cpu"


def test_resolve_device_explicit_is_respected():
    assert resolve_device("cpu", cuda_available=True) == "cpu"
    assert resolve_device("cuda:0", cuda_available=True) == "cuda:0"


def test_parse_env_text_basic_pairs():
    env = parse_env_text("ANNOTATOR_DEVICE=cpu\nANNOTATOR_LOCK_TTL=90\n")
    assert env == {"ANNOTATOR_DEVICE": "cpu", "ANNOTATOR_LOCK_TTL": "90"}


def test_parse_env_text_ignores_comments_and_blanks():
    env = parse_env_text("# a comment\n\nKEY=value\n   # indented comment\n")
    assert env == {"KEY": "value"}


def test_parse_env_text_strips_quotes_and_whitespace():
    env = parse_env_text('PATH_A = "/data/best.pt" \nPATH_B=\'/tmp/x\'\n')
    assert env["PATH_A"] == "/data/best.pt"
    assert env["PATH_B"] == "/tmp/x"


def test_parse_env_text_keeps_equals_in_value():
    env = parse_env_text("KEY=a=b=c\n")
    assert env["KEY"] == "a=b=c"


def test_parse_env_text_supports_export_prefix():
    env = parse_env_text("export ANNOTATOR_DEVICE=cuda:0\n")
    assert env == {"ANNOTATOR_DEVICE": "cuda:0"}


def test_load_dotenv_does_not_override_existing_env(tmp_path, monkeypatch):
    # Use isolated keys so the test is independent of any real .env in the repo.
    monkeypatch.setenv("DOTENV_TEST_EXISTING", "keep-me")
    monkeypatch.delenv("DOTENV_TEST_NEW", raising=False)
    envfile = tmp_path / ".env"
    envfile.write_text("DOTENV_TEST_EXISTING=changed\nDOTENV_TEST_NEW=added\n")
    load_dotenv(envfile)
    # explicit process env wins; new keys are added
    assert os.environ["DOTENV_TEST_EXISTING"] == "keep-me"
    assert os.environ["DOTENV_TEST_NEW"] == "added"


def test_load_dotenv_missing_file_is_noop(tmp_path):
    load_dotenv(tmp_path / "nope.env")  # should not raise
