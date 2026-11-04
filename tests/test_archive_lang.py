"""Archive the old work, and speak Chinese to the people who need it."""
import os

from test_cli import init_agents, run


def _finished_task(tmp_path, roots, title="old job"):
    created = run(roots["alice"], "new", "--to", "bob", "--title", title,
                  "--ask", "do the thing", expect=0)
    task_id = created.stdout.split("\t")[0]
    run(roots["bob"], "ack", task_id, expect=0)
    body = tmp_path / (title.replace(" ", "-") + ".md")
    body.write_text("delivered\n", encoding="utf-8")
    run(roots["bob"], "result", task_id, "--text",
        "finished, file attached, checked against the source", "--artifact", str(body),
        "--verified", expect=0)
    return task_id


def test_archive_is_a_dry_run_by_default(tmp_path):
    roots, shared = init_agents(tmp_path)
    task_id = _finished_task(tmp_path, roots)

    dry = run(roots["alice"], "archive", "--days", "0", expect=0)
    assert "would move" in dry.stdout
    assert task_id.split("-")[0] not in ""  # sanity: nothing moved yet
    assert not os.path.isdir(os.path.join(shared, "_archive"))
    assert task_id in run(roots["alice"], "ls", "--all").stdout


def test_archive_moves_the_files_and_hides_the_task(tmp_path):
    roots, shared = init_agents(tmp_path)
    task_id = _finished_task(tmp_path, roots)

    run(roots["alice"], "archive", "--days", "0", "--apply", expect=0)

    archive = os.path.join(shared, "_archive")
    assert os.path.isdir(archive)
    month_dir = os.path.join(archive, os.listdir(archive)[0])
    names = os.listdir(month_dir)
    assert any("TASK-" in n for n in names)
    assert any("_ACK_" in n for n in names)
    assert any("_RESULT_" in n for n in names)
    # the live queue no longer carries it, and nothing is left at the top level
    assert task_id not in run(roots["alice"], "ls", "--all").stdout
    assert not [n for n in os.listdir(shared) if task_id in n]


def test_archive_leaves_unfinished_work_alone(tmp_path):
    roots, shared = init_agents(tmp_path)
    created = run(roots["alice"], "new", "--to", "bob", "--title", "still open",
                  "--ask", "not done yet", expect=0)
    task_id = created.stdout.split("\t")[0]
    run(roots["bob"], "ack", task_id, expect=0)

    run(roots["alice"], "archive", "--days", "0", "--apply", expect=0)
    assert task_id in run(roots["alice"], "ls", "--all").stdout


def test_errors_speak_chinese_when_asked(tmp_path):
    roots, _shared = init_agents(tmp_path)
    created = run(roots["alice"], "new", "--to", "bob", "--title", "t", "--ask", "a", expect=0)
    task_id = created.stdout.split("\t")[0]
    run(roots["bob"], "ack", task_id, expect=0)

    en = run(roots["bob"], "ack", task_id, expect=3)
    assert "already accepted" in en.stderr

    zh = run(roots["bob"], "--lang", "zh", "ack", task_id, expect=3)
    assert "认领" in zh.stderr


def test_init_lang_is_remembered(tmp_path):
    root = str(tmp_path / "chinese")
    os.makedirs(root)
    out = run(root, "--lang", "zh", "init", "--transport", "local",
              "--path", "./mail", "--agent", "小明", expect=0)
    assert "已初始化" in out.stdout
    # later commands read `lang` from the config, no flag needed
    assert "这里没有待办" in run(root, "inbox").stdout
