#!/usr/bin/env python3

import os
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

import pygit2 as git
from jinja2 import Environment, FileSystemLoader, select_autoescape


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


def generate_commits_html(template_env: Environment, metadata):
    commits = get_commits(repo)[:100]
    commits.sort(key=lambda commit: commit.commit_time)
    commits.reverse()
    data = []
    for commit in commits:
        if len(commit.parents) > 0:
            stats = commit.tree.diff_to_tree(commit.parents[0].tree).stats
        else:
            stats = commit.tree.diff_to_tree(swap=True).stats
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
    )
    with open(os.path.join(args.outdir, "commits.html"), "w") as f:
        print(render, file=f)


def generate_refs_html(template_env: Environment, metadata):
    raw_data = [get_branches(repo)[:100], get_tags(repo)[:100]]
    data = []
    for i in range(len(raw_data)):
        tmp = raw_data[i]
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
    )
    with open(os.path.join(args.outdir, "refs.html"), "w") as f:
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

    generate_commits_html(template_env, metadata)
    generate_refs_html(template_env, metadata)

    if not os.path.exists(os.path.join(args.outdir, "index.html")):
        os.symlink(
            os.path.realpath(os.path.join(args.outdir, "commits.html")),
            os.path.join(args.outdir, "index.html"),
        )
