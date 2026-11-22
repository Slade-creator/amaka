"""Account management CLI for the AMAKA API.

Run from the prototype root:

    python -m backend.users list
    python -m backend.users add <username> --role operator --name "Display Name"
    python -m backend.users passwd <username>
    python -m backend.users disable <username>
    python -m backend.users enable <username>
    python -m backend.users remove <username>

Passwords are read with a hidden prompt (or --password for scripted setup) and
stored as PBKDF2-SHA256 hashes in config/users.json.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from . import auth


def _ask_password(given: str | None) -> str:
    if given:
        return given
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Repeat password: ")
    if first != second:
        raise auth.AuthError("Passwords do not match")
    return first


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m backend.users",
                                description="Manage AMAKA accounts")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List accounts")

    add = sub.add_parser("add", help="Create or update an account")
    add.add_argument("username")
    add.add_argument("--role", required=True, choices=auth.ROLES)
    add.add_argument("--name", help="Display name")
    add.add_argument("--password", help="Password (prompted when omitted)")

    pw = sub.add_parser("passwd", help="Change a password")
    pw.add_argument("username")
    pw.add_argument("--password")

    for name in ("disable", "enable", "remove"):
        sp = sub.add_parser(name, help=f"{name.capitalize()} an account")
        sp.add_argument("username")

    args = p.parse_args(argv)
    try:
        if args.cmd == "list":
            users = auth.list_users()
            if not users:
                print(f"No accounts in {auth.USERS_PATH}")
            for u in users:
                flag = "  (disabled)" if u.disabled else ""
                print(f"{u.username:<16} {u.role:<10} {u.name}{flag}")
        elif args.cmd == "add":
            u = auth.upsert_user(args.username, _ask_password(args.password),
                                 args.role, args.name)
            print(f"Saved {u.username} ({u.role})")
        elif args.cmd == "passwd":
            u = auth.get_user(args.username)
            if u is None:
                raise auth.AuthError(f"No account '{args.username}'")
            auth.upsert_user(u.username, _ask_password(args.password), u.role,
                             u.name, u.disabled)
            print(f"Password changed for {u.username}")
        elif args.cmd in ("disable", "enable"):
            u = auth.get_user(args.username)
            if u is None:
                raise auth.AuthError(f"No account '{args.username}'")
            auth.upsert_user(u.username, None, u.role, u.name,
                             disabled=args.cmd == "disable")
            print(f"{args.cmd.capitalize()}d {u.username}")
        elif args.cmd == "remove":
            if not auth.remove_user(args.username):
                raise auth.AuthError(f"No account '{args.username}'")
            print(f"Removed {args.username}")
    except auth.AuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
