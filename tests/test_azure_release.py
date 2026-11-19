"""scripts/azure_release.py: Azure follows main's newest tested commit, safely.

Every Azure, GitHub, git and docker command is answered by a fake, so these
tests change nothing anywhere. Names are synthetic.
"""
from __future__ import annotations

import io
import json

import pytest

from scripts import azure_release

HEAD = "a" * 40
OLDER = "b" * 40
SERVER = "registryexample.azurecr.io"
CURRENT_IMAGE = f"{SERVER}/web@sha256:{'1' * 64}"
NEW_IMAGE = f"{SERVER}/web@sha256:{'2' * 64}"
FQDN = "app-example.example.test"
ENV = {
    "GITHUB_REPOSITORY": "example/repo",
    "AZURE_RESOURCE_GROUP": "group-example",
    "AZURE_APP": "app-example",
    "AZURE_BACKUP_JOB": "job-example",
    "GITHUB_RUN_NUMBER": "57",
    "GITHUB_RUN_ATTEMPT": "1",
    "GITHUB_ACTIONS": "true",
}
SUFFIX = f"c{HEAD[:12]}-57-1"
NEW_REVISION = f"app-example--{SUFFIX}"
SERVING = {"provisioning": "Provisioned", "running": "RunningAtMaxScale", "health": "Healthy", "active": True}


class FakeWorld:
    """GitHub, Azure, git and docker as the release sees them."""

    def __init__(self, *, head=HEAD, passed=(HEAD,), image=CURRENT_IMAGE, ready="app-example--0000004",
                 job_image=None, fqdn=FQDN, on_main=True, built=HEAD, revisions=None, fail=()):
        self.head, self.passed, self.image, self.ready = head, set(passed), image, ready
        self.job = CURRENT_IMAGE if job_image is None else job_image
        self.fqdn, self.on_main_status, self.built = fqdn, on_main, built
        # revision name -> list of states returned one poll at a time (the last repeats)
        self.revisions = revisions if revisions is not None else {}
        self.fail = set(fail)
        self.calls: list[list[str]] = []
        self.pushed = ""

    def __call__(self, args, *, stream=False):
        args = list(args)
        self.calls.append(args)
        key = " ".join(args[:4])
        for word in self.fail:
            if word in key:
                raise azure_release.CommandError(args, 1, "simulated failure")
        if args[:2] == ["gh", "api"]:
            return self._github(args)
        if args[:2] == ["git", "-C"]:
            return self.built + "\n"
        if args[:3] == ["az", "containerapp", "show"]:
            return json.dumps({"image": self.image, "ready": self.ready, "fqdn": self.fqdn})
        if args[:4] == ["az", "containerapp", "job", "show"]:
            return self.job + "\n"
        if args[:4] == ["az", "containerapp", "revision", "show"]:
            name = args[args.index("--revision") + 1]
            states = self.revisions.get(name)
            if not states:
                raise azure_release.CommandError(args, 3, "not found")
            state = states.pop(0) if len(states) > 1 else states[0]
            if state == SERVING:
                self.ready = name
            return json.dumps(state)
        if args[:3] == ["az", "containerapp", "update"]:
            self.image = args[args.index("--image") + 1]
            return ""
        if args[:4] == ["az", "containerapp", "job", "update"]:
            self.job = args[args.index("--image") + 1]
            return ""
        if args[:3] == ["az", "acr", "login"]:
            return "Login Succeeded\n"
        if args[:2] == ["docker", "build"]:
            assert stream is True
            return ""
        if args[:2] == ["docker", "push"]:
            self.pushed = args[2]
            return ""
        if args[:2] == ["docker", "inspect"]:
            return json.dumps(["other.example/web@sha256:" + "9" * 64, NEW_IMAGE])
        raise AssertionError(f"unexpected command {args}")

    def _github(self, args):
        path = next(a for a in args[2:] if a.startswith("repos/"))
        if path.endswith("/commits/main"):
            return self.head + "\n"
        if "/commits/" in path:
            short = path.rsplit("/", 1)[1]
            return next((sha for sha in (HEAD, OLDER) if sha.startswith(short)), "") + "\n"
        if "/compare/" in path:
            return ("ahead" if self.on_main_status else "diverged") + "\n"
        if path.endswith("/actions/workflows/tests.yml/runs"):
            sha = next(a.split("=", 1)[1] for a in args if a.startswith("head_sha="))
            assert {"branch=main", "event=push", "status=success"} <= set(args)
            return ("1" if sha in self.passed else "0") + "\n"
        raise AssertionError(f"unexpected GitHub call {args}")

    def commands(self, *prefix):
        return [call for call in self.calls if call[:len(prefix)] == list(prefix)]


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def release(world, action, *extra, env=None, tmp_path=None):
    out = io.StringIO()
    clock = Clock()
    environment = dict(ENV if env is None else env)
    if tmp_path is not None:
        environment["GITHUB_OUTPUT"] = str(tmp_path / "output")
        environment["GITHUB_STEP_SUMMARY"] = str(tmp_path / "summary")
    code = azure_release.main([action, *extra], env=environment, run=world, out=out,
                              sleep=clock.sleep, clock=clock)
    return code, out.getvalue()


def chosen(tmp_path):
    return (tmp_path / "output").read_text(encoding="utf-8")


# -- choose -----------------------------------------------------------------

def test_choose_releases_mains_head_once_tests_passed_on_it(tmp_path):
    world = FakeWorld()
    code, log = release(world, "choose", tmp_path=tmp_path)
    assert code == 0
    assert chosen(tmp_path) == f"commit={HEAD}\n"
    assert f"Release: {HEAD}" in log
    assert not world.commands("docker") and not world.commands("az", "containerapp", "update")


def test_a_late_run_for_an_older_commit_never_moves_azure_backwards(tmp_path):
    # Tests passed on an older commit, but not (yet) on main's head.
    world = FakeWorld(passed=(OLDER,))
    code, log = release(world, "choose", tmp_path=tmp_path)
    assert code == 0
    assert chosen(tmp_path) == "commit=\n"
    assert "Tests has not passed on main's head" in log
    assert not world.commands("az")


def test_nothing_to_do_when_app_and_backup_job_already_run_the_commit(tmp_path):
    world = FakeWorld(ready=f"app-example--c{HEAD[:12]}-56-1")
    code, log = release(world, "choose", tmp_path=tmp_path)
    assert code == 0
    assert chosen(tmp_path) == "commit=\n"
    assert "already runs" in log


def test_a_backup_job_left_behind_still_gets_released(tmp_path):
    world = FakeWorld(ready=f"app-example--c{HEAD[:12]}-56-1", job_image=f"{SERVER}/web@sha256:{'0' * 64}")
    code, _ = release(world, "choose", tmp_path=tmp_path)
    assert code == 0
    assert chosen(tmp_path) == f"commit={HEAD}\n"


def test_a_commit_named_by_hand_must_be_on_main_and_tested(tmp_path):
    world = FakeWorld(passed=(HEAD, OLDER))
    code, _ = release(world, "choose", "--commit", OLDER[:9], tmp_path=tmp_path)
    assert code == 0
    assert chosen(tmp_path) == f"commit={OLDER}\n"

    code, log = release(FakeWorld(passed=(HEAD,)), "choose", "--commit", OLDER[:9], tmp_path=tmp_path)
    assert code == 1 and "Tests has not passed" in log

    code, log = release(FakeWorld(passed=(OLDER,), on_main=False), "choose", "--commit", OLDER,
                        tmp_path=tmp_path)
    assert code == 1 and "is not on main" in log


@pytest.mark.parametrize("bad", ["main", "abc123", "g" * 40, "a" * 41, "../../x"])
def test_a_commit_named_by_hand_must_be_hex(bad, tmp_path):
    world = FakeWorld()
    code, log = release(world, "choose", "--commit", bad, tmp_path=tmp_path)
    assert code == 2
    assert not world.calls


def test_missing_settings_are_named_without_values():
    env = {key: value for key, value in ENV.items() if key not in ("AZURE_APP", "AZURE_BACKUP_JOB")}
    world = FakeWorld()
    code, log = release(world, "choose", env=env)
    assert code == 2
    assert "Missing settings: AZURE_APP, AZURE_BACKUP_JOB." in log
    assert not world.calls


def test_an_image_outside_azure_container_registry_stops_the_release(tmp_path):
    world = FakeWorld(image="docker.io/library/web:latest")
    code, log = release(world, "deploy", "--commit", HEAD, tmp_path=tmp_path)
    assert code == 1
    assert "not in an Azure Container Registry" in log
    assert not world.commands("docker")


# -- deploy -----------------------------------------------------------------

def test_deploy_builds_the_commit_and_moves_app_then_backup_job_to_its_digest(tmp_path):
    world = FakeWorld(revisions={NEW_REVISION: [{"provisioning": "Provisioning"}, SERVING]})
    code, log = release(world, "deploy", "--commit", HEAD, "--context", "build", tmp_path=tmp_path)
    assert code == 0, log

    assert world.commands("az", "acr", "login") == [["az", "acr", "login", "-n", "registryexample", "--only-show-errors"]]
    [build] = world.commands("docker", "build")
    assert f"APP_GIT_COMMIT={HEAD}" in build
    assert f"PUBLIC_SITE_ORIGIN=https://{FQDN}" in build
    assert build[-3:] == ["-t", f"{SERVER}/web:{HEAD}", "build"]
    assert world.pushed == f"{SERVER}/web:{HEAD}"

    [update] = world.commands("az", "containerapp", "update")
    assert update[update.index("--image") + 1] == NEW_IMAGE  # by digest, never by tag
    assert update[update.index("--revision-suffix") + 1] == SUFFIX
    assert world.image == NEW_IMAGE and world.job == NEW_IMAGE
    calls = [" ".join(call[:4]) for call in world.calls]
    assert calls.index("az containerapp update -n") < calls.index("az containerapp job update")

    summary = (tmp_path / "summary").read_text(encoding="utf-8")
    assert f"Deployed `{HEAD}` to Azure" in summary and SUFFIX in summary
    assert "registryexample" not in summary and FQDN not in summary


def test_every_derived_value_is_masked_before_it_can_be_printed(tmp_path):
    world = FakeWorld(revisions={NEW_REVISION: [SERVING]})
    code, log = release(world, "deploy", "--commit", HEAD, tmp_path=tmp_path)
    assert code == 0, log
    lines = log.splitlines()
    for value in (SERVER, "registryexample", CURRENT_IMAGE, NEW_IMAGE, "sha256:" + "2" * 64,
                  FQDN, f"https://{FQDN}"):
        own_mask = lines.index(f"::add-mask::{value}")
        printed = [i for i, line in enumerate(lines) if value in line and not line.startswith("::add-mask::")]
        assert all(i > own_mask for i in printed), value
    masks = [line for line in lines if line.startswith("::add-mask::")]
    assert len(masks) == len(set(masks))  # each value once


def test_masks_are_not_printed_outside_github_actions(tmp_path):
    world = FakeWorld(revisions={NEW_REVISION: [SERVING]})
    env = {key: value for key, value in ENV.items() if key != "GITHUB_ACTIONS"}
    code, log = release(world, "deploy", "--commit", HEAD, env=env, tmp_path=tmp_path)
    assert code == 0
    assert "::add-mask::" not in log


def test_a_company_address_overrides_the_app_address_for_link_previews(tmp_path):
    world = FakeWorld(revisions={NEW_REVISION: [SERVING]})
    env = dict(ENV, AZURE_PUBLIC_ORIGIN="https://tool.example.org/")
    code, _ = release(world, "deploy", "--commit", HEAD, env=env, tmp_path=tmp_path)
    assert code == 0
    [build] = world.commands("docker", "build")
    assert "PUBLIC_SITE_ORIGIN=https://tool.example.org" in build


def test_deploy_refuses_a_build_folder_holding_another_commit(tmp_path):
    world = FakeWorld(built=OLDER)
    code, log = release(world, "deploy", "--commit", HEAD, tmp_path=tmp_path)
    assert code == 1
    assert f"holds {OLDER}, not {HEAD}" in log
    assert not world.commands("az") and not world.commands("docker")


def test_a_failed_revision_puts_the_previous_image_back_and_leaves_the_job_alone(tmp_path):
    back = "app-example--back-57-1"
    world = FakeWorld(revisions={
        NEW_REVISION: [{"provisioning": "Provisioning"}, {"provisioning": "Failed", "running": "Failed"}],
        back: [SERVING],
    })
    code, log = release(world, "deploy", "--commit", HEAD, tmp_path=tmp_path)
    assert code == 1
    updates = world.commands("az", "containerapp", "update")
    assert [u[u.index("--image") + 1] for u in updates] == [NEW_IMAGE, CURRENT_IMAGE]
    assert updates[1][updates[1].index("--revision-suffix") + 1] == "back-57-1"
    assert world.image == CURRENT_IMAGE and world.ready == back
    assert not world.commands("az", "containerapp", "job", "update")
    assert "The previous image is serving again." in log
    assert "the previous image was put back" in log


def test_a_revision_that_never_serves_is_rolled_back_after_the_timeout(tmp_path):
    back = "app-example--back-57-1"
    world = FakeWorld(revisions={
        NEW_REVISION: [{"provisioning": "Provisioned", "running": "Activating", "health": "None"}],
        back: [SERVING],
    })
    code, log = release(world, "deploy", "--commit", HEAD, tmp_path=tmp_path)
    assert code == 1
    assert "not serving after 15 minutes" in log
    polls = [c for c in world.commands("az", "containerapp", "revision", "show") if NEW_REVISION in c]
    assert len(polls) == azure_release.HEALTH_TIMEOUT_SECONDS // azure_release.POLL_SECONDS + 1
    assert world.image == CURRENT_IMAGE


def test_an_update_that_fails_after_changing_the_app_is_rolled_back(tmp_path):
    back = "app-example--back-57-1"

    class FailingUpdate(FakeWorld):
        def __call__(self, args, *, stream=False):
            result = super().__call__(args, stream=stream)
            if list(args[:3]) == ["az", "containerapp", "update"] and NEW_IMAGE in args:
                raise azure_release.CommandError(args, 1, "provisioning failed")
            return result

    world = FailingUpdate(revisions={back: [SERVING]})
    code, log = release(world, "deploy", "--commit", HEAD, tmp_path=tmp_path)
    assert code == 1
    assert world.image == CURRENT_IMAGE
    assert "putting the previous image back" in log
    assert "provisioning failed" in log


def test_an_update_refused_outright_changes_nothing(tmp_path):
    world = FakeWorld(fail={"az containerapp update"})
    code, log = release(world, "deploy", "--commit", HEAD, tmp_path=tmp_path)
    assert code == 1
    assert "`az containerapp update` failed" in log
    assert len(world.commands("az", "containerapp", "update")) == 1
    assert not world.commands("az", "containerapp", "job", "update")


def test_a_job_update_failure_is_reported_and_a_rerun_finishes_it(tmp_path):
    world = FakeWorld(revisions={NEW_REVISION: [SERVING]}, fail={"az containerapp job update"})
    code, log = release(world, "deploy", "--commit", HEAD, tmp_path=tmp_path)
    assert code == 1
    assert "the backup job still has the previous image" in log
    assert world.image == NEW_IMAGE and world.job == CURRENT_IMAGE

    world.fail.clear()
    code, _ = release(world, "choose", tmp_path=tmp_path)
    assert code == 0 and chosen(tmp_path).endswith(f"commit={HEAD}\n")
    code, log = release(world, "deploy", "--commit", HEAD, tmp_path=tmp_path)
    assert code == 0
    assert world.job == NEW_IMAGE
    assert len(world.commands("docker", "build")) == 1  # nothing rebuilt
    assert "The backup job now runs the same image as the app" in log


def test_deploy_skips_a_commit_azure_already_runs(tmp_path):
    world = FakeWorld(ready=f"app-example--c{HEAD[:12]}-56-1")
    code, log = release(world, "deploy", "--commit", HEAD, tmp_path=tmp_path)
    assert code == 0
    assert "Nothing to deploy" in log
    assert not world.commands("docker") and not world.commands("az", "containerapp", "update")


def test_revision_suffix_is_a_valid_container_apps_suffix():
    settings = azure_release.settings_from(dict(ENV, GITHUB_RUN_NUMBER="123456", GITHUB_RUN_ATTEMPT="12"))
    suffix = azure_release.revision_suffix(HEAD, settings)
    assert suffix == f"c{HEAD[:12]}-123456-12"
    assert suffix[0].isalpha() and suffix[-1].isalnum() and "--" not in suffix
    assert suffix == suffix.lower() and len(suffix) <= 30
