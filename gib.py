#!/usr/bin/env python3

import os
import stat
from argparse import ArgumentParser
from collections.abc import MutableMapping
from datetime import datetime
from pathlib import Path

import magic
import pygit2 as git
from jinja2 import Environment, FileSystemLoader, select_autoescape


MAX_COMMITS = 100
MAX_REFS = 100
MAX_FILES = 100


def is_mime_viewable(mime):
    if mime.startswith("text/"):
        return True
    elif mime in [
        "application/json",
    ]:
        return True
    return False


# https://stackoverflow.com/questions/6027558/
def flatten(dictionary, parent_key="", separator="/"):
    items = []
    for key, value in dictionary.items():
        new_key = parent_key + separator + key if parent_key else key
        if isinstance(value, MutableMapping):
            items.extend(flatten(value, new_key, separator=separator).items())
        else:
            items.append((new_key, value))
    return dict(items)


def format_time(timestamp):
    return datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def get_commit_message(commit: git.Commit):
    return commit.message.split("\n")[0].strip()


def get_branch_name(ref: git.Branch):
    return "/".join(ref.shorthand.split("/")[1:])


def get_commits(repo: git.Repository, oid: git.Oid = None):
    if oid != None:
        walker = repo.walk(oid, git.GIT_SORT_TOPOLOGICAL)
    else:
        walker = repo.walk(repo.head.target, git.GIT_SORT_TOPOLOGICAL)
    return [commit for commit in walker]


def list_files(repo: git.Repository, tree: git.Tree = None):
    files = {}
    if tree == None:
        tree = repo.get(repo.head.target).tree
    for e in tree:
        if isinstance(e, git.Tree):
            files[e.name] = list_files(repo, e)
        else:
            files[e.name] = e
    return files


def get_tags(repo: git.Repository):
    tags = []
    for ref_name in repo.references:
        if not ref_name.startswith("refs/tags/"):
            continue
        ref = repo.references[ref_name]
        target = repo.get(ref.target)
        if isinstance(target, git.Tag):  # annotated tag
            commit = repo.get(target.target)
        else:  # lightweight tag
            commit = target
        tags.append((ref, commit))
    return tags


def get_branches(repo: git.Repository):
    branches = []
    for branch_name in list(repo.branches.remote):
        branch = repo.branches.remote[branch_name]
        if not isinstance(branch, git.Branch):
            continue
        if not isinstance(branch.target, git.Oid):
            continue
        commit = repo.get(branch.target)
        branches.append((branch, commit))
    return branches


def generate_commits_html(repo: git.Repository, template_env: Environment, metadata):
    commits = get_commits(repo)
    commits.sort(key=lambda commit: commit.commit_time)
    commits.reverse()
    data = []
    for i in range(len(commits)):
        commit = commits[i]
        parent = None
        if len(commit.parents) > 0:
            parent = commit.parents[0]
            stats = commit.tree.diff_to_tree(parent.tree).stats
        else:
            stats = commit.tree.diff_to_tree(swap=True).stats
        if i < MAX_COMMITS:
            data.append(
                {
                    "commit_author_name": commit.author.name,
                    "commit_author_email": commit.author.email,
                    "commit_time": format_time(commit.commit_time),
                    "commit_id": commit.id,
                    "commit_message": get_commit_message(commit),
                    "commit_insertions": stats.insertions,
                    "commit_deletions": stats.deletions,
                }
            )

    tpl = template_env.get_template("commits.html")
    render = tpl.render(
        title=f"Commits - {metadata['name']}",
        metadata=metadata,
        commits=data,
        n_commits=len(commits),
    )
    with open(os.path.join(args.outdir, "commits.html"), "w") as f:
        print(render, file=f)


def generate_refs_html(repo: git.Repository, template_env: Environment, metadata):
    raw_data = [get_branches(repo), get_tags(repo)]
    data = []
    for i in range(len(raw_data)):
        tmp = raw_data[i][:MAX_REFS]
        tmp.sort(key=lambda x: x[1].commit_time)
        tmp.reverse()
        data.append(
            [
                {
                    "name": get_branch_name(ref) if i == 0 else ref.shorthand,
                    "commit_id": commit.id,
                    "commit_message": get_commit_message(commit),
                }
                for ref, commit in tmp
            ]
        )
    tpl = template_env.get_template("refs.html")
    render = tpl.render(
        title=f"Refs - {metadata['name']}",
        metadata=metadata,
        branches=data[0],
        tags=data[1],
        n_branches=len(data[0]),
        n_tags=len(data[1]),
    )
    with open(os.path.join(args.outdir, "refs.html"), "w") as f:
        print(render, file=f)


def generate_files_html(
    repo: git.Repository,
    template_env: Environment,
    metadata,
    tree: git.Tree = None,
):
    raw_data = [(k, v) for k, v in flatten(list_files(repo, tree)).items()]
    raw_data.sort(key=lambda x: x[0])
    data = []
    tpl = template_env.get_template("file.html")
    for i in range(len(raw_data)):
        file_path, file = raw_data[i]
        file_mode = stat.filemode(file.filemode)[1:]
        mime = magic.from_buffer(file.data, mime=True)
        if i < MAX_FILES:
            data.append(
                {
                    "mode": file_mode,
                    "path": file_path,
                    "viewable": is_mime_viewable(mime),
                }
            )
        if is_mime_viewable(mime):
            render = tpl.render(
                title=f"{file_path} - {metadata['name']}",
                metadata=metadata,
                file_mode=file_mode,
                file_path=file_path,
                content=file.data.decode("utf-8"),
            )
            out_path = os.path.join(
                args.outdir,
                "file",
                *f"{file_path}.html".split("/"),
            )
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w") as f:
                print(render, file=f)
    tpl = template_env.get_template("files.html")
    render = tpl.render(
        title=f"Files - {metadata['name']}",
        metadata=metadata,
        files=data,
        n_files=len(raw_data),
    )
    with open(os.path.join(args.outdir, "files.html"), "w") as f:
        print(render, file=f)


def parse_args():
    parser = ArgumentParser(description="dumb git repository static site generator")
    parser.add_argument(
        "repodir",
        metavar="REPOSITORY",
        type=Path,
        help="the git repository directory",
    )
    parser.add_argument(
        "outdir",
        metavar="OUTPUT",
        type=Path,
        help="the output directory",
    )
    parser.add_argument("-n", "--name", type=str, help="name of the git repository")
    parser.add_argument(
        "-d", "--desc", type=str, help="short description of the git repository"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    repo = git.Repository(args.repodir)

    template_env = Environment(
        loader=FileSystemLoader(searchpath="./templates"),
        autoescape=select_autoescape(),
    )

    metadata = {
        "name": os.path.basename(os.path.abspath(args.repodir))
        if not args.name
        else args.name,
        "description": "no description provided." if not args.desc else args.desc,
    }

    os.makedirs(args.outdir, exist_ok=True)

    generate_commits_html(repo, template_env, metadata)
    generate_refs_html(repo, template_env, metadata)
    generate_files_html(repo, template_env, metadata)

    if os.path.exists(os.path.join(args.outdir, "index.html")):
        os.remove(os.path.join(args.outdir, "index.html"))
    os.symlink(
        os.path.realpath(os.path.join(args.outdir, "files.html")),
        os.path.join(args.outdir, "index.html"),
    )
