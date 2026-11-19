"""Deploy main's newest tested commit to the Azure copy of the app.

``.github/workflows/azure-deploy.yml`` runs this after Tests passes on main,
signed in to Azure as the deploy identity, so the Azure copy follows main the
way Render does. It is M9 of docs/AZURE_CUTOVER_PLAN.md done by a machine.

``choose``
    The release is main's head, and only when Tests passed on that exact
    commit, so a late run for an older commit never moves Azure backwards. A
    commit named by hand must be on main and have passed Tests too. Nothing is
    released when the app already runs it and the backup job has the same
    image: every deploy names its revision after the commit
    (``c<first 12 hex>-<run>-<attempt>``).
``deploy``
    Build the image from that commit (stamped with it, so About shows it),
    push it to the registry and repository the app already runs from, tagged
    with the commit, and update the app to it by digest. Wait until the new
    revision serves; otherwise put the previous image back and fail. Then
    point the backup job at the same image.

The repository is public. Resource names come only from the environment (the
``azure`` environment's secrets, which GitHub masks in logs), and every value
derived from them (registry, image references, digests, the app's address) is
masked before anything can print it. The data share is not snapshotted first;
the nightly backup job archives it.

Settings: GITHUB_REPOSITORY, AZURE_RESOURCE_GROUP, AZURE_APP, AZURE_BACKUP_JOB;
optional AZURE_PUBLIC_ORIGIN (https address for link previews, when it is not
the app's own Azure address), GITHUB_RUN_NUMBER and GITHUB_RUN_ATTEMPT. ``gh``
needs GH_TOKEN, and ``az`` a signed-in session.

Exit status: 0 when deployed or nothing to do, 1 on failure, 2 for bad settings.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Sequence, TextIO

TESTS_WORKFLOW = "tests.yml"
HEALTH_TIMEOUT_SECONDS = 15 * 60
POLL_SECONDS = 15
# With one replica allowed, a serving revision reports it runs at max scale.
RUNNING_STATES = ("Running", "RunningAtMaxScale")
REQUIRED_SETTINGS = ("GITHUB_REPOSITORY", "AZURE_RESOURCE_GROUP", "AZURE_APP", "AZURE_BACKUP_JOB")
FULL_SHA = re.compile(r"[0-9a-f]{40}")
COMMIT_INPUT = re.compile(r"[0-9a-f]{7,40}")
ACR_IMAGE = re.compile(
    r"(?P<server>(?P<registry>[a-z0-9]{5,50})\.azurecr\.io)/"
    r"(?P<repository>[a-z0-9][a-z0-9._/-]*?)"
    r"(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?(?:@sha256:[0-9a-f]{64})?"
)
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
ERROR_TAIL_LINES = 40

Runner = Callable[..., str]


class SettingsError(Exception):
    """A missing or malformed setting or argument (exit status 2)."""


class ReleaseError(Exception):
    """The release cannot go ahead or did not succeed (exit status 1)."""


class CommandError(Exception):
    def __init__(self, args: Sequence[str], returncode: int, output: str = "") -> None:
        words: list[str] = []
        for arg in args:
            if arg.startswith("-") or len(words) == 4:
                break
            words.append(arg)
        super().__init__(f"`{' '.join(words)}` failed with exit status {returncode}")
        self.output = output


def run_command(args: Sequence[str], *, stream: bool = False) -> str:
    """Run one command; with ``stream`` its output goes straight to the log."""
    if stream:
        completed = subprocess.run(list(args), text=True)
        if completed.returncode != 0:
            raise CommandError(args, completed.returncode)
        return ""
    completed = subprocess.run(list(args), capture_output=True, text=True)
    if completed.returncode != 0:
        raise CommandError(args, completed.returncode, completed.stderr or completed.stdout)
    return completed.stdout


@dataclass(frozen=True)
class Settings:
    repo: str
    group: str
    app: str
    job: str
    origin: str = ""
    run_number: str = "0"
    run_attempt: str = "1"


def settings_from(env: Mapping[str, str]) -> Settings:
    missing = [name for name in REQUIRED_SETTINGS if not env.get(name, "").strip()]
    if missing:
        raise SettingsError("Missing settings: " + ", ".join(missing) + ".")
    origin = env.get("AZURE_PUBLIC_ORIGIN", "").strip().rstrip("/")
    if origin and not origin.startswith("https://"):
        raise SettingsError("AZURE_PUBLIC_ORIGIN must be an https:// address.")
    run_number = env.get("GITHUB_RUN_NUMBER", "").strip() or "0"
    run_attempt = env.get("GITHUB_RUN_ATTEMPT", "").strip() or "1"
    if not (run_number.isdigit() and run_attempt.isdigit()):
        raise SettingsError("GITHUB_RUN_NUMBER and GITHUB_RUN_ATTEMPT must be numbers.")
    return Settings(
        repo=env["GITHUB_REPOSITORY"].strip(),
        group=env["AZURE_RESOURCE_GROUP"].strip(),
        app=env["AZURE_APP"].strip(),
        job=env["AZURE_BACKUP_JOB"].strip(),
        origin=origin,
        run_number=run_number,
        run_attempt=run_attempt,
    )


@dataclass(frozen=True)
class AppState:
    image: str
    ready_revision: str
    fqdn: str


@dataclass(frozen=True)
class Registry:
    server: str
    name: str
    repository: str


def parse_image(image: str) -> Registry:
    match = ACR_IMAGE.fullmatch(image)
    if not match:
        raise ReleaseError("The app's current image is not in an Azure Container Registry, so there is nowhere to push.")
    return Registry(server=match["server"], name=match["registry"], repository=match["repository"])


def revision_suffix(sha: str, settings: Settings) -> str:
    return f"c{sha[:12]}-{settings.run_number}-{settings.run_attempt}"


class Release:
    def __init__(
        self,
        settings: Settings,
        *,
        run: Runner = run_command,
        out: TextIO = sys.stdout,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        masking: bool = True,
        output_file: str = "",
        summary_file: str = "",
    ) -> None:
        self.s = settings
        self.run = run
        self.out = out
        self.sleep = sleep
        self.clock = clock
        self.masking = masking
        self.output_file = output_file
        self.summary_file = summary_file
        self._masked: set[str] = set()

    # -- log -----------------------------------------------------------------
    def say(self, text: str) -> None:
        print(text, file=self.out, flush=True)

    def mask(self, *values: str) -> None:
        if self.masking:
            for value in values:
                if value and value not in self._masked:
                    self._masked.add(value)
                    self.say(f"::add-mask::{value}")

    def output(self, name: str, value: str) -> None:
        if self.output_file:
            with open(self.output_file, "a", encoding="utf-8") as handle:
                handle.write(f"{name}={value}\n")

    def summary(self, text: str) -> None:
        if self.summary_file:
            with open(self.summary_file, "a", encoding="utf-8") as handle:
                handle.write(text + "\n")

    # -- GitHub ----------------------------------------------------------------
    def commit_sha(self, ref: str) -> str:
        sha = self.run(["gh", "api", f"repos/{self.s.repo}/commits/{ref}", "--jq", ".sha"]).strip()
        if not FULL_SHA.fullmatch(sha):
            raise ReleaseError(f"Could not resolve {ref} to a commit.")
        return sha

    def on_main(self, sha: str) -> bool:
        status = self.run(["gh", "api", f"repos/{self.s.repo}/compare/{sha}...main", "--jq", ".status"]).strip()
        return status in ("ahead", "identical")

    def tests_passed(self, sha: str) -> bool:
        total = self.run([
            "gh", "api", "-X", "GET", f"repos/{self.s.repo}/actions/workflows/{TESTS_WORKFLOW}/runs",
            "-f", f"head_sha={sha}", "-f", "branch=main", "-f", "event=push", "-f", "status=success",
            "--jq", ".total_count",
        ]).strip()
        return total.isdigit() and int(total) > 0

    # -- Azure -----------------------------------------------------------------
    def app_state(self) -> AppState:
        raw = self.run([
            "az", "containerapp", "show", "-n", self.s.app, "-g", self.s.group,
            "--query", "{image: properties.template.containers[0].image, "
            "ready: properties.latestReadyRevisionName, fqdn: properties.configuration.ingress.fqdn}",
            "-o", "json",
        ])
        data = json.loads(raw or "{}")
        state = AppState(image=str(data.get("image") or ""), ready_revision=str(data.get("ready") or ""),
                         fqdn=str(data.get("fqdn") or ""))
        self.mask(state.image, state.fqdn)
        return state

    def registry_of(self, state: AppState) -> Registry:
        registry = parse_image(state.image)
        self.mask(registry.server, registry.name)
        return registry

    def runs_commit(self, state: AppState, sha: str) -> bool:
        return state.ready_revision.startswith(f"{self.s.app}--c{sha[:12]}-")

    def job_image(self) -> str:
        image = self.run([
            "az", "containerapp", "job", "show", "-n", self.s.job, "-g", self.s.group,
            "--query", "properties.template.containers[0].image", "-o", "tsv",
        ]).strip()
        self.mask(image)
        return image

    def update_job(self, image: str, sha: str) -> None:
        try:
            self.run(["az", "containerapp", "job", "update", "-n", self.s.job, "-g", self.s.group,
                      "--image", image, "-o", "none", "--only-show-errors"])
        except CommandError:
            self.say(f"::error::The app runs {sha}, but the backup job still has the previous image. "
                     "Run this workflow again, or update the job by hand (M9 step 6).")
            raise

    def revision_state(self, revision: str) -> dict:
        raw = self.run([
            "az", "containerapp", "revision", "show", "-n", self.s.app, "-g", self.s.group, "--revision", revision,
            "--query", "{provisioning: properties.provisioningState, running: properties.runningState, "
            "health: properties.healthState, active: properties.active}",
            "-o", "json",
        ])
        return json.loads(raw or "{}")

    def wait_until_serving(self, revision: str) -> str:
        """'' once ``revision`` serves the app, else why not."""
        deadline = self.clock() + HEALTH_TIMEOUT_SECONDS
        seen = ""
        while True:
            try:
                state = self.revision_state(revision)
            except CommandError:
                state = {}  # not listed yet
            described = ", ".join(f"{key} {state.get(key)}" for key in ("provisioning", "running", "health"))
            if described != seen:
                self.say(f"New revision: {described}")
                seen = described
            if state.get("provisioning") == "Failed" or state.get("running") == "Failed":
                return described
            if (state.get("health") == "Healthy" and state.get("running") in RUNNING_STATES
                    and state.get("active") and self.app_state().ready_revision == revision):
                return ""
            if self.clock() >= deadline:
                return f"not serving after {HEALTH_TIMEOUT_SECONDS // 60} minutes ({described})"
            self.sleep(POLL_SECONDS)

    def update_app(self, image: str, suffix: str) -> None:
        self.run([
            "az", "containerapp", "update", "-n", self.s.app, "-g", self.s.group,
            "--image", image, "--revision-suffix", suffix, "-o", "none", "--only-show-errors",
        ])

    def roll_back(self, previous_image: str) -> None:
        suffix = f"back-{self.s.run_number}-{self.s.run_attempt}"
        try:
            self.update_app(previous_image, suffix)
        except CommandError as error:
            self.say(f"::error::Putting the previous image back failed ({error}). Restore it by hand: M9, Going back.")
            return
        problem = self.wait_until_serving(f"{self.s.app}--{suffix}")
        if problem:
            self.say(f"::error::The previous image is not serving either ({problem}). Check the app now.")
        else:
            self.say("The previous image is serving again.")

    # -- the two steps ---------------------------------------------------------
    def choose(self, requested: str = "") -> str:
        """The commit to deploy, or '' when there is nothing to do."""
        if requested:
            if not COMMIT_INPUT.fullmatch(requested):
                raise SettingsError("--commit must be 7 to 40 lowercase hex characters.")
            sha = self.commit_sha(requested)
            if not self.on_main(sha):
                raise ReleaseError(f"{sha} is not on main.")
            if not self.tests_passed(sha):
                raise ReleaseError(f"Tests has not passed on {sha}.")
        else:
            sha = self.commit_sha("main")
            if not self.tests_passed(sha):
                self.say(f"Nothing to deploy: Tests has not passed on main's head {sha}. "
                         "Azure stays on its current version until it does.")
                return ""
        state = self.app_state()
        self.registry_of(state)
        if self.runs_commit(state, sha) and self.job_image() == state.image:
            self.say(f"Nothing to deploy: Azure already runs {sha}.")
            return ""
        self.say(f"Release: {sha}")
        return sha

    def deploy(self, sha: str, context: str = ".") -> None:
        if not FULL_SHA.fullmatch(sha):
            raise SettingsError("--commit must be a full 40-character commit SHA.")
        built = self.run(["git", "-C", context, "rev-parse", "HEAD"]).strip()
        if built != sha:
            raise ReleaseError(f"The build folder holds {built or 'nothing'}, not {sha}.")
        state = self.app_state()
        registry = self.registry_of(state)
        if self.runs_commit(state, sha):
            if self.job_image() != state.image:  # an earlier run stopped before the job
                self.update_job(state.image, sha)
                self.say(f"The backup job now runs the same image as the app ({sha}).")
            else:
                self.say(f"Nothing to deploy: Azure already runs {sha}.")
            return
        if not (self.s.origin or state.fqdn):
            raise ReleaseError("The app has no public address and AZURE_PUBLIC_ORIGIN is not set.")
        origin = self.s.origin or f"https://{state.fqdn}"
        self.mask(origin)

        self.run(["az", "acr", "login", "-n", registry.name, "--only-show-errors"])
        tag = f"{registry.server}/{registry.repository}:{sha}"
        self.say(f"Building {sha}.")
        self.run([
            "docker", "build", "--build-arg", f"APP_GIT_COMMIT={sha}",
            "--build-arg", f"PUBLIC_SITE_ORIGIN={origin}", "-t", tag, context,
        ], stream=True)
        self.run(["docker", "push", tag])
        digests = json.loads(self.run(["docker", "inspect", "--format", "{{json .RepoDigests}}", tag]) or "[]")
        prefix = f"{registry.server}/{registry.repository}@"
        image = next((ref for ref in digests or [] if ref.startswith(prefix)
                      and DIGEST.fullmatch(ref[len(prefix):])), "")
        if not image:
            raise ReleaseError("The pushed image has no digest in the app's registry.")
        self.mask(image, image[len(prefix):])

        suffix = revision_suffix(sha, self.s)
        revision = f"{self.s.app}--{suffix}"
        self.say(f"Deploying {sha} as revision suffix {suffix}.")
        try:
            self.update_app(image, suffix)
        except CommandError:
            try:
                changed = self.app_state().image == image
            except CommandError:
                changed = False
            if changed:  # the update failed after it had changed the app
                self.say("::error::The update failed after changing the app; putting the previous image back.")
                self.roll_back(state.image)
            raise
        problem = self.wait_until_serving(revision)
        if problem:
            self.say(f"::error::The new revision is not serving ({problem}); putting the previous image back.")
            self.roll_back(state.image)
            raise ReleaseError(f"Deploying {sha} failed; the previous image was put back.")

        self.update_job(image, sha)
        when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.say(f"Deployed {sha} to Azure; the backup job runs the same image.")
        self.summary(f"Deployed `{sha}` to Azure at {when} (revision suffix `{suffix}`); "
                     "the backup job runs the same image.")


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    run: Runner = run_command,
    out: TextIO = sys.stdout,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    parser = argparse.ArgumentParser(description="Deploy main's newest tested commit to Azure.")
    actions = parser.add_subparsers(dest="action", required=True)
    choose = actions.add_parser("choose", help="Write the commit to deploy (or nothing) to GITHUB_OUTPUT as commit=.")
    choose.add_argument("--commit", default="", help="A commit on main to deploy instead of main's head.")
    deploy = actions.add_parser("deploy", help="Build, push and deploy one commit.")
    deploy.add_argument("--commit", required=True, help="Full SHA from the choose step.")
    deploy.add_argument("--context", default=".", help="Folder holding that commit's checkout.")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    try:
        settings = settings_from(env)
        release = Release(
            settings, run=run, out=out, sleep=sleep, clock=clock,
            masking=env.get("GITHUB_ACTIONS") == "true",
            output_file=env.get("GITHUB_OUTPUT", ""), summary_file=env.get("GITHUB_STEP_SUMMARY", ""),
        )
        if args.action == "choose":
            release.output("commit", release.choose(args.commit.strip().lower()))
        else:
            release.deploy(args.commit.strip().lower(), args.context)
    except SettingsError as error:
        print(f"::error::{error}", file=out)
        return 2
    except (ReleaseError, CommandError) as error:
        print(f"::error::{error}", file=out)
        if isinstance(error, CommandError) and error.output:
            print("\n".join(error.output.strip().splitlines()[-ERROR_TAIL_LINES:]), file=out)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
