"""
cli.py
------
The `cr` command line. Commands are grouped: `cr <group> <command> [args]`,
e.g. `cr fleet report data/pinned/20261010T1358Z-celestrak`.

How to add a command (for every owner, so no one has to touch argparse code):

  1. In your module, write
         def register(registry):
             parser = registry.command("export", "crpos", help="...", func=run)
             parser.add_argument(...)
     where run(args) returns an exit code (0 = success). args.argv holds the
     full argument list, handy for provenance manifests.
  2. Add your module's dotted name to COMMAND_MODULES below.

Modules are imported only when `cr` starts, and a module that fails to import
does not break the other commands: its group prints the import error instead.
"""

import argparse
import importlib
import sys

from . import __version__

# Project convention: never write __pycache__ next to the sources (what
# `python -B` / PYTHONDONTWRITEBYTECODE=1 do). venv/bin/cr starts Python
# without -B, so switch it off here, before the command modules (topo, orbit,
# route, export, data, proto) are imported. Only chronoroute/__init__.py and
# this file are compiled before this line can run; export
# PYTHONDONTWRITEBYTECODE=1 (the Makefile does) to cover those two as well.
sys.dont_write_bytecode = True

# Modules that provide commands (each defines register(registry)).
COMMAND_MODULES = (
    "chronoroute.data.fleet_report",       # cr fleet report
    "chronoroute.route.command",           # cr route --from A --to B
    "chronoroute.export.command",          # cr export bundle | web | sids
    "chronoroute.fwd.command",             # cr run --config FILE --seed N --out DIR
    "chronoroute.viz.command",             # cr viz globe | map2d, cr trace from-ns3
    "chronoroute.eval.command",            # cr eval scheme | score | roc (baselines, offline evaluation)
)


class CommandRegistry:
    """Collects command groups and their commands on one argparse parser."""

    def __init__(self, parser):
        self._groups_action = parser.add_subparsers(dest="group", metavar="<group>")
        self._groups = {}

    def group(self, name, help=None):
        """The sub-parser collection of a group, created on first use."""
        if name not in self._groups:
            group_parser = self._groups_action.add_parser(name, help=help, description=help)
            self._groups[name] = (group_parser,
                                  group_parser.add_subparsers(dest="command", metavar="<command>"))
        return self._groups[name][1]

    def command(self, group, name, *, help, func, group_help=None):
        """Add `cr <group> <name>`; returns its argparse parser for add_argument()."""
        parser = self.group(group, group_help).add_parser(name, help=help, description=help)
        parser.set_defaults(func=func)
        return parser

    def group_parser(self, name):
        return self._groups[name][0] if name in self._groups else None


def build_parser():
    parser = argparse.ArgumentParser(
        prog="cr", description="ChronoRoute command line (deadline-based source routing for LEO).")
    parser.add_argument("--version", action="version", version=f"chronoroute {__version__}")
    registry = CommandRegistry(parser)
    failures = {}
    for module_name in COMMAND_MODULES:
        try:
            importlib.import_module(module_name).register(registry)
        except Exception as exc:              # report, but keep the other commands usable
            failures[module_name] = f"{type(exc).__name__}: {exc}"
    return parser, registry, failures


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser, registry, failures = build_parser()
    for module_name, error in failures.items():
        print(f"cr: warning: commands from {module_name} are unavailable ({error})", file=sys.stderr)
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        group = getattr(args, "group", None)
        target = registry.group_parser(group) if group else parser
        (target or parser).print_help()
        return 2
    args.argv = argv
    return int(func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
