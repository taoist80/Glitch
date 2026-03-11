"""GitHub tools for Sentinel.

Provides tools for creating fix branches, committing files, and opening pull
requests as part of automated incident remediation. Uses a GitHub PAT stored
in Secrets Manager at glitch/github-token.
"""

import logging
from base64 import b64decode
from typing import Optional

from github import Github, GithubException
from strands import tool

from sentinel.aws_utils import get_client

logger = logging.getLogger(__name__)

SECRET_NAME = "glitch/github-token"
SSM_PARAM_REPO = "/glitch/sentinel/github-repo"

_github_client: Optional[Github] = None
_github_repo_name: Optional[str] = None


def _get_github() -> Github:
    global _github_client
    if _github_client is None:
        sm = get_client("secretsmanager")
        resp = sm.get_secret_value(SecretId=SECRET_NAME)
        token = resp["SecretString"].strip()
        _github_client = Github(token)
    return _github_client


def _get_repo_name() -> str:
    global _github_repo_name
    if _github_repo_name:
        return _github_repo_name
    try:
        ssm = get_client("ssm")
        resp = ssm.get_parameter(Name=SSM_PARAM_REPO)
        _github_repo_name = resp["Parameter"]["Value"].strip()
        return _github_repo_name
    except Exception as e:
        raise RuntimeError(f"Could not load GitHub repo from SSM {SSM_PARAM_REPO}: {e}") from e


@tool
def github_get_file(file_path: str, branch: str = "main") -> str:
    """Read a file from the GitHub repository.

    Args:
        file_path: Path to the file within the repository (e.g., "agent/src/glitch/tools/deploy_tools.py").
        branch: Branch to read from (default "main").

    Returns:
        JSON with file content, sha, and encoding info.
    """
    try:
        g = _get_github()
        repo = g.get_repo(_get_repo_name())
        contents = repo.get_contents(file_path, ref=branch)
        if isinstance(contents, list):
            return json.dumps({"error": f"{file_path} is a directory, not a file"})
        decoded = b64decode(contents.content).decode("utf-8") if contents.encoding == "base64" else contents.decoded_content.decode("utf-8")
        return json.dumps({
            "path": file_path,
            "branch": branch,
            "sha": contents.sha,
            "size": contents.size,
            "content": decoded,
        })
    except GithubException as e:
        return json.dumps({"error": str(e), "status": e.status})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def github_create_branch(branch_name: str, from_branch: str = "main") -> str:
    """Create a new branch in the GitHub repository.

    Args:
        branch_name: Name for the new branch (e.g., "fix/sentinel-nginx-proxy-config").
        from_branch: Source branch to branch from (default "main").

    Returns:
        JSON with branch name and SHA on success, or error.
    """
    try:
        g = _get_github()
        repo = g.get_repo(_get_repo_name())
        source = repo.get_branch(from_branch)
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=source.commit.sha)
        return json.dumps({
            "created": branch_name,
            "from": from_branch,
            "sha": source.commit.sha,
        })
    except GithubException as e:
        return json.dumps({"error": str(e), "status": e.status})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def github_commit_file(
    file_path: str,
    content: str,
    commit_message: str,
    branch: str,
    existing_sha: Optional[str] = None,
) -> str:
    """Commit a file to a branch in the GitHub repository (create or update).

    Args:
        file_path: Path within the repository (e.g., "agent/src/glitch/tools/deploy_tools.py").
        content: Full file content as a string.
        commit_message: Git commit message.
        branch: Branch to commit to.
        existing_sha: SHA of the existing file (required when updating an existing file).
                      Get this from github_get_file first. Omit when creating a new file.

    Returns:
        JSON with commit SHA on success, or error.
    """
    try:
        g = _get_github()
        repo = g.get_repo(_get_repo_name())

        if existing_sha:
            result = repo.update_file(
                path=file_path,
                message=commit_message,
                content=content,
                sha=existing_sha,
                branch=branch,
            )
        else:
            result = repo.create_file(
                path=file_path,
                message=commit_message,
                content=content,
                branch=branch,
            )

        commit = result.get("commit")
        return json.dumps({
            "committed": file_path,
            "branch": branch,
            "commit_sha": commit.sha if commit else "unknown",
            "message": commit_message,
        })
    except GithubException as e:
        return json.dumps({"error": str(e), "status": e.status})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def github_create_pr(
    title: str,
    body: str,
    head_branch: str,
    base_branch: str = "main",
    labels: Optional[list] = None,
) -> str:
    """Create a pull request in the GitHub repository.

    Args:
        title: PR title.
        body: PR description (markdown supported). Include root cause, fix summary, and testing notes.
        head_branch: The branch containing the fix.
        base_branch: The branch to merge into (default "main").
        labels: Optional list of label names to apply (e.g., ["bug", "sentinel-auto"]).

    Returns:
        JSON with PR number and URL on success, or error.
    """
    try:
        g = _get_github()
        repo = g.get_repo(_get_repo_name())
        pr = repo.create_pull(
            title=title,
            body=body,
            head=head_branch,
            base=base_branch,
        )
        if labels:
            try:
                pr.add_to_labels(*labels)
            except Exception as label_err:
                logger.warning(f"Could not add labels to PR: {label_err}")

        return json.dumps({
            "pr_number": pr.number,
            "url": pr.html_url,
            "title": pr.title,
            "head": head_branch,
            "base": base_branch,
        })
    except GithubException as e:
        return json.dumps({"error": str(e), "status": e.status})
    except Exception as e:
        return json.dumps({"error": str(e)})
