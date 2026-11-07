from harness_lab.tools import READ_FILE_TOOL, WORKSPACE, read_file


def test_reads_a_file_in_the_workspace(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    assert read_file("a.txt", tmp_path) == "hello"


def test_committed_sample_file_is_readable():
    assert read_file("hello.txt").startswith("This is a sample")
    assert (WORKSPACE / "hello.txt").is_file()


def test_missing_file(tmp_path):
    assert "not found" in read_file("nope.txt", tmp_path)


def test_dotdot_escape_refused(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "secret.txt").write_text("secret")
    result = read_file("../secret.txt", ws)
    assert "outside the workspace" in result
    assert "secret" not in result.replace("secret.txt", "")


def test_absolute_path_refused(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "secret.txt").write_text("secret")
    assert "outside the workspace" in read_file(str(tmp_path / "secret.txt"), ws)


def test_symlink_escape_refused(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "secret.txt").write_text("secret")
    (ws / "link.txt").symlink_to(tmp_path / "secret.txt")
    assert "outside the workspace" in read_file("link.txt", ws)


def test_tool_definition_shape():
    assert READ_FILE_TOOL["name"] == "read_file"
    assert READ_FILE_TOOL["input_schema"]["required"] == ["path"]
