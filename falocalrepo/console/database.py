from csv import writer as csv_writer
from datetime import datetime
from enum import Enum
from io import BytesIO
from json import dumps
from json import load
from os.path import getsize
from pathlib import Path
from re import sub
from shutil import get_terminal_size
from sys import stderr
from sys import stdout
from typing import Any
from typing import Callable
from typing import Iterable
from typing import TextIO

from click import Argument
from click import BadParameter
from click import Context
from click import File
from click import IntRange
from click import Option
from click import Path as PathClick
from click import argument
from click import confirmation_option
from click import echo
from click import group
from click import option
from click import pass_context
from click import secho
from click import style
from click.shell_completion import CompletionItem
from falocalrepo_database import Cursor
from falocalrepo_database import Database
from falocalrepo_database import Table
from falocalrepo_database import __version__ as __database_version__
from falocalrepo_database.database import query_to_sql
from falocalrepo_database.selector import SelectorBuilder as Sb
from falocalrepo_database.tables import HistoryColumns
from falocalrepo_database.tables import JournalsColumns
from falocalrepo_database.tables import SubmissionsColumns
from falocalrepo_database.tables import UsersColumns
from falocalrepo_database.tables import journals_table
from falocalrepo_database.tables import submissions_table
from falocalrepo_database.tables import users_table
from wcwidth import wcswidth

from .colors import *
from .util import CompleteChoice
from .util import CustomHelpColorsGroup
from .util import EnvVars
from .util import add_history
from .util import color_option
from .util import database_callback
from .util import database_exists_option
from .util import docstring_format
from .util import help_option
from .. import __name__ as __prog_name__
from ..__version__ import __version__


class Output(str, Enum):
    csv = "csv"
    tsv = "tsv"
    json = "json"
    table = "table"
    none = "none"


class ClearChoice(CompleteChoice):
    completion_items: list[CompletionItem] = [
        CompletionItem("clear", "Clear history")
    ]


class TableChoice(CompleteChoice):
    completion_items: list[CompletionItem] = [
        CompletionItem(submissions_table),
        CompletionItem(journals_table),
        CompletionItem(users_table),
    ]


class SearchOrderChoice(CompleteChoice):
    completion_items: list[CompletionItem] = [
        CompletionItem("asc", "Ascending order"),
        CompletionItem("desc", "Descending order"),
    ]


class SearchOutputChoice(CompleteChoice):
    completion_items: list[CompletionItem] = [
        CompletionItem(Output.table.value, help="Table format"),
        CompletionItem(Output.csv.value, help="CSV format (comma separated)"),
        CompletionItem(Output.tsv.value, help="TSV format (tab separated)"),
        CompletionItem(Output.json.value, help="JSON format"),
        CompletionItem(Output.none.value, help="Do not print results to screen"),
    ]


class ExportOutputChoice(CompleteChoice):
    completion_items: list[CompletionItem] = [
        CompletionItem(Output.csv.value, help="CSV format (comma separated)"),
        CompletionItem(Output.tsv.value, help="TSV format (tab separated)"),
        CompletionItem(Output.json.value, help="JSON format"),
    ]


def column_callback(_ctx: Context, _param: Option, value: tuple[str]) -> list[tuple[str, int]]:
    return [((vs := v.split(",", 1))[0], int(vs[1])) if "," in v else (v, 0) for v in map(str.strip, value) if v]


def id_callback(ctx: Context, param: Argument, value: tuple[str, ...]) -> tuple[str | int, ...]:
    if (t := ctx.params["table"]).lower() == users_table.lower():
        return value
    elif any(not v.isdigit() for v in value):
        raise BadParameter(f"{param.metavar.upper().removesuffix('...')} must be of type INTEGER for {t} table.",
                           ctx, param, param.get_error_hint(ctx))
    return tuple(map(int, value))


def format_value(value: Any) -> str:
    return " ".join(value) if isinstance(value, (list, set)) else str(value)


def fit_string(value: str, width: int | None) -> str:
    return value.encode(errors="replace")[:width].decode(errors="replace") if width else value


def get_table(db: Database, table: str) -> Table:
    if (table := table.lower()) == users_table.lower():
        return db.users
    elif table == submissions_table.lower():
        return db.submissions
    elif table == journals_table.lower():
        return db.journals
    else:
        return db[table]


def print_table(ctx: Context, results: Cursor, headers: list[tuple[str, int]], ignore_width: bool) -> int:
    results_total: int = 0
    if ctx.color:
        terminal_width: int | None = None if ignore_width else get_terminal_size((0, 0)).columns or None
        terminal_width_total: int = terminal_width - (3 * (len(headers) - 1)) if terminal_width else None
        widths: list[int] = [w for _, w in headers]
        headers = [f"{h[:w or None]:^{w}}" for h, w in headers]
        headers = "\0".join(headers)[:terminal_width_total].split("\0")
        echo(style(" | ", fg="bright_black", bold=True).join(style(h, fg="yellow", bold=True) for h in headers))
        secho(("-+-".join("-" * len(h) for h in headers) + "-")[:terminal_width], fg="bright_black", bold=True)
        separator: str = style(" | ", fg="bright_black", bold=True)
        for entry in results:
            results_total += 1
            values: list[str] = [f"{format_value(v)[:w or None]:<{w}}" for v, w in zip(entry.values(), widths)]
            if terminal_width:
                values_length_wc: int = sum(map(wcswidth, values))
                if values_length_wc > terminal_width_total:
                    if sum(map(len, values)) != values_length_wc:
                        values = "\0".join(values).encode(errors="replace")[:terminal_width_total + len(values) - 1] \
                            .decode(errors="replace").split("\0")
                    else:
                        values = "\0".join(values)[:terminal_width_total + len(values) - 1].split("\0")
            echo(separator.join(values))
    else:
        terminal_width: int | None = None if ignore_width else get_terminal_size((0, 0)).columns or None
        widths: list[int] = [w for _, w in headers]
        headers = [f"{h[:w or None]:^{w}}" for h, w in headers]
        echo(" | ".join(headers)[:terminal_width], color=False)
        echo(("-+-".join("-" * len(h) for h in headers) + "-")[:terminal_width], color=False)
        for entry in results:
            results_total += 1
            line: str = " | ".join(f"{fit_string(format_value(v), w):<{w}}" for v, w in zip(entry.values(), widths))
            echo(fit_string(line, terminal_width), color=False)

    return results_total


def print_csv(results: Cursor, file: TextIO, delimiter: str) -> int:
    results_total: int = 0
    writer = csv_writer(file, delimiter=delimiter)
    writer.writerow(results.columns)
    for row in results.entries:
        results_total += 1
        writer.writerow(map(format_value, row.values()))
    return results_total


def print_json(results: Cursor, file: TextIO) -> int:
    results_total: int = 0
    file.write("[")
    if first := next(results.entries, None):
        results_total += 1
        file.write(dumps(first, separators=(",", ":")))
    for entry in results.entries:
        results_total += 1
        file.write("," + dumps(entry, separators=(",", ":")))
    file.write("]")
    return results_total


def search(table: Table, headers: list[str], query: str, sort: str, order: str, limit: int | None,
           offset: int | None, sql: bool) -> tuple[Cursor, tuple[str, list[str]]]:
    cols_table: list[str] = [c.name for c in table.columns]
    query_elems, values = ([query], []) if sql else query_to_sql(
        query, "any", [*map(str.lower, {*cols_table, "any"} - {"ID", "AUTHOR", "USERNAME"})],
        {"author": "replace(author, '_', '')", "any": f"({'||'.join(cols_table)})"})
    query = " ".join(query_elems)
    return (table.select_sql(query, values, headers, [f"{sort} {order}"], limit or 0, offset or 0),
            (query, values))


@group("database", cls=CustomHelpColorsGroup, short_help="Operate on the database.", no_args_is_help=True)
@color_option
@help_option
@docstring_format(
    users_columns="\n    ".join(f" * {c.name:<8} {c.type.__name__}" for c in UsersColumns.as_list()),
    submissions_columns="\n    ".join(f" * {c.name:<11} {c.type.__name__}" for c in SubmissionsColumns.as_list()),
    journals_columns="\n    ".join(f" * {c.name:<10} {c.type.__name__}" for c in JournalsColumns.as_list()),
    prog_name=__prog_name__, version=__version__)
def database_app():
    """
    Operate on the database to add, remove, or search entries.

    The following is a list of all the columns and their type. For specific details on the columns and their contents,
    see the README at {blue}https://pypi.org/project/{prog_name}/{version}{reset}.

    \b
    {cyan}Users{reset}
    {users_columns}

    \b
    {cyan}Submissions{reset}
    {submissions_columns}

    \b
    {cyan}Journals{reset}
    {journals_columns}
    """
    pass


# noinspection DuplicatedCode
@database_app.command("info", short_help="Show database information.")
@database_exists_option
@color_option
@help_option
@pass_context
def database_info(ctx: Context, database: Callable[..., Database]):
    """
    Show database information, statistics and version.
    """

    db: Database = database(check_version=False)
    err: Exception | None
    if err := db.check_version(raise_for_error=False):
        secho(f"Database version error: {' '.join(err.args)}" +
              f"\n\nUpgrade with {database_app.name} {database_upgrade.name}.",
              file=stderr, fg="red", color=ctx.color)
    echo(f"{bold}Database{reset}", color=ctx.color)
    echo(f"{blue}Location{reset}   : {yellow}{db.path}{reset}", color=ctx.color)
    echo(f"{blue}Version{reset}    : {yellow}{db.version}{reset}", color=ctx.color)
    echo(f"{blue}Size{reset}       : ", nl=False, color=ctx.color)
    echo(f"{yellow}{getsize(db.path) / 1e6:.1f}MB{reset}", color=ctx.color)
    if err:
        return
    last_history: dict | None = next(db.history.select(order=[db.history.key.name + ' desc'], limit=1), None)
    echo(f"{blue}Last update{reset}: ", nl=False, color=ctx.color)
    echo(f"{yellow}{(last_history or {}).get(HistoryColumns.TIME.value.name, None)}{reset}", color=ctx.color)
    echo(f"{blue}Users{reset}      : ", nl=False, color=ctx.color)
    echo(f"{yellow}{len(db.users)}{reset}", color=ctx.color)
    echo(f"{blue}Submissions{reset}: ", nl=False, color=ctx.color)
    echo(f"{yellow}{len(db.submissions)}{reset}", color=ctx.color)
    echo(f"{blue}Journals{reset}   : ", nl=False, color=ctx.color)
    echo(f"{yellow}{len(db.journals)}{reset}", color=ctx.color)
    echo(f"{blue}History{reset}    : ", nl=False, color=ctx.color)
    echo(f"{yellow}{len(db.history)}{reset}", color=ctx.color)


@database_app.command("history", short_help="Show database history.")
@option("--filter", "_filter", metavar="FILTER", type=str, default="", callback=lambda _c, _p, v: v.lower(),
        help=f"Show entries containing {yellow}FILTER{reset}.")
@option("--clear", is_flag=True, default=False, required=False, help="Clear entries.")
@database_exists_option
@color_option
@help_option
@pass_context
@docstring_format()
def database_history(ctx: Context, database: Callable[..., Database], clear: bool, _filter: str):
    """
    Show database history. History events can be filtered using the {yellow}--filter{reset} option to match events that
    contain {yellow}FILTER{reset} (the match is performed case-insensitively).

    Using the {yellow}--clear{reset} option will delete all history entries, or the ones containing
    {yellow}FILTER{reset} if the {yellow}--filter{reset} option is used.
    """

    db: Database = database()

    history: Iterable[tuple[datetime, str]]
    removed: int = 0

    if _filter:
        history = ((t, e) for t, e in db.history.select().tuples if _filter in e.lower())
    else:
        history = db.history.select().tuples

    try:
        for t, e in history:
            if clear:
                del db.history[t]
                removed += 1
            else:
                echo(f"{blue}{t:%Y-%m-%d %H:%M:%S}{reset} {yellow}{e}{reset}", color=ctx.color)
    finally:
        db.commit()

    if clear:
        echo(f"Removed {yellow}{removed}{reset} entries.")


@database_app.command("search", short_help="Search database entries.", no_args_is_help=True)
@argument("table", nargs=1, required=True, is_eager=True, type=TableChoice())
@argument("query", nargs=-1, required=True, callback=lambda _c, _p, v: " ".join(v))
@option("--column", metavar="<COLUMN[,WIDTH]>", type=str, multiple=True, callback=column_callback,
        help=f"Select {yellow}COLUMN{reset} and use {yellow}WIDTH{reset} in table output.")
@option("--sort", metavar="COLUMN", type=str, help=f"Sort by {yellow}COLUMN{reset}.")
@option("--order", type=SearchOrderChoice(), default="desc", show_default=True, help="Specify sorting order")
@option("--limit", type=IntRange(0, min_open=True), help="Limit query results.")
@option("--offset", type=IntRange(0, min_open=True), help="Offset query results.")
@option("--sql", is_flag=True, help="Treat query as SQLite WHERE statement.")
@option("--show-sql", is_flag=True, help="Show generated SQLite WHERE statement.")
@option("--output", default="table", type=SearchOutputChoice(), help="Specify output type.")
@option("--ignore-width", is_flag=True, help="Ignore terminal width when printing results in table format.")
@option("--total", is_flag=True, help="Print number of results.")
@database_exists_option
@color_option
@help_option
@pass_context
@docstring_format(c=cyan, i=italic, r=reset, prog_name=__prog_name__, version=__version__,
                  outputs="\n    ".join(f" * {s.value}\t{s.help}" for s in SearchOutputChoice.completion_items))
def database_search(ctx: Context, database: Callable[..., Database], table: str, query: str,
                    column: tuple[tuple[str, int]], sort: str | None, order: str, limit: int | None, offset: int | None,
                    sql: bool, show_sql: bool, output: str, ignore_width: bool, total: bool):
    """
    Search the database using queries, and output in different formats.

    The default output format is a table with only the most relevant columns displayed for each entry. To override the
    displayed column, or change their width, use the {yellow}--column{reset} option to select which columns will be
    displayed (SQLite statements are supported). The optional {yellow}WIDTH{reset} value can be added to format that
    specific column when the output is set to {cyan}table{reset}.

    To output all columns and entries of a table, {yellow}COLUMN{reset} and {yellow}QUERY{reset} values can be set to
    {cyan}@{reset} and {cyan}%{reset} respectively. However, the {yellow}database export{reset} command is better
    suited for this task.

    For a list of columns, see {yellow}database{reset} help.

    Search is performed case-insensitively.

    \b
    The output can be set to five different types:
    {outputs}

    {blue}Query Language{reset}

    The query language used for search queries is based and improves upon the search syntax currently used by the Fur
    Affinity website. Its basic elements are:

    \b
    * {c}@<field>{r} field specifier (e.g. {c}@title{r}), all database columns are
        available as search fields.
    * {c}(){r} parentheses, they can be used for better logic operations
    * {c}&{r} {i}AND{r} logic operator, used between search terms
    * {c}|{r} {i}OR{r} logic operator, used between search terms
    * {c}!{r} {i}NOT{r} logic operator, used as prefix of search terms
    * {c}""{r} quotes, allow searching for literal strings without needing to escape
    * {c}%{r} match 0 or more characters
    * {c}_{r} match exactly 1 character
    * {c}^{r} start of field, when used at the start of a search term it matches
        the beginning of the field
    * {c}${r} end of field, when used at the end of a search term it matches the
        end of the field

    All other strings are considered search terms.

    The search uses the {c}@any{r} field by default, allowing to do general searches without specifying a field.

    Search terms that are not separated by a logic operator are considered {i}AND{r} terms (i.e. {c}a b c{r} <->
    {c}a & b & c{r}).

    Except for the {c}ID{r}, {c}AUTHOR{r}, and {c}USERNAME{r} fields, all search terms are matched by fields containing
    the term: i.e. {c}@description cat{r} will match any item whose description field contains "cat". To match items
    that contain only "cat" (or start with, end with, etc.), the {c}%{r}, {c}_{r}, {c}^{r}, and {c}${r} operators need
    to be used (e.g. {c}@description ^cat{r}).

    Search terms for {c}ID{r}, {c}AUTHOR{r}, and {c}USERNAME{r} are matched exactly as they are: i.e. {c}@author tom{r}
    will match only items whose author field is exactly equal to "tom", to match items that contain "tom" the {c}%{r},
    {c}_{r}, {c}^{r}, and {c}${r} operators need to be used (e.g. {c}@author %tom%{r}).

    For examples, please read the full README at {blue}https://pypi.org/project/{prog_name}/{version}{reset}.
    """

    db: Database = database()
    db_table: Table = get_table(db, table)
    default_headers: list[tuple[str, int]] = []

    if table in (submissions_table, journals_table):
        default_headers = [("ID", 10), ("AUTHOR", 16), ("DATE", 16), ("TITLE", 0)]
    elif table == users_table:
        default_headers = [("USERNAME", 40), ("FOLDERS", 0)]

    headers: list[tuple[str, int]] = [(c.upper(), w) for c, w in column] if column else default_headers
    headers = [(c, 0) for c in db_table.columns] if any(h == "@" for h, _ in headers) else headers
    headers[-1] = (headers[-1][0], 0)
    results, [query, values] = search(db_table, [h for h, _ in headers], query, sort or db_table.key.name, order,
                                      limit, offset, sql)
    results_total: int = 0

    if output == Output.table:
        results_total = print_table(ctx, results, headers, ignore_width)
    elif output == Output.csv:
        results_total = print_csv(results, stdout, ",")
    elif output == Output.tsv:
        results_total = print_csv(results, stdout, "\t")
    elif output == Output.json:
        results_total = print_json(results, stdout, )
    elif output == Output.none:
        results_total = sum(1 for _ in results.cursor)

    if show_sql:
        echo(f"{blue}Query{reset}: {yellow}{sub(r'(?<=[()])[ ](?=[()])', '', query)}{reset}", color=ctx.color)
        echo(f"{blue}Items{reset}: {yellow}{dumps(values)}{reset}", color=ctx.color)
    if total:
        echo(f"{blue}Total{reset}: {yellow}{results_total}{reset}", color=ctx.color)


@database_app.command("export", short_help="Export all entries in a table.", no_args_is_help=True)
@argument("table", nargs=1, required=True, is_eager=True, type=TableChoice())
@argument("output", nargs=1, required=True, type=ExportOutputChoice())
@argument("file", nargs=1, required=False, default=stdout, type=File("w"))
@option("--column", metavar="COLUMN", type=str, multiple=True, help=f"Select {yellow}COLUMN{reset}.")
@option("--sort", metavar="COLUMN", type=str, help=f"Sort by {yellow}COLUMN{reset}.")
@option("--order", type=SearchOrderChoice(), default="asc", show_default=True, help="Specify sorting order.")
@option("--total", is_flag=True, help="Print number of results.")
@database_exists_option
@color_option
@help_option
@pass_context
@docstring_format(outputs="\n    ".join(f" * {s.value}\t{s.help}" for s in ExportOutputChoice.completion_items))
def database_export(ctx: Context, database: Callable[..., Database], table: str, output: str, file: TextIO,
                    column: tuple[str], sort: str | None, order: str, total: bool):
    """
    Export all entries in a table to a file. The {yellow}FILE{reset} argument can be omitted to print the results
    directly in the terminal. The results total is not printed to file if a file is used.

    By default, all columns of the table are selected, but this can be overridden with the {yellow}--column{reset}
    option (SQLite statements are supported).

    Only sort and order statements are supported for exporting, to filter results use the {yellow}database search{reset}
    command.

    \b
    The {yellow}OUTPUT{reset} can be set to four different types:
    {outputs}
    """
    db: Database = database()

    db_table: Table = get_table(db, table)
    column = column or db_table.columns

    results: Cursor = db_table.select(None, column, [f"{sort or db_table.key.name} {order}"])
    results_total: int = 0

    if output == Output.csv:
        results_total = print_csv(results, file, ",")
    elif output == Output.tsv:
        results_total = print_csv(results, file, "\t")
    elif output == Output.json:
        results_total = print_json(results, file)

    if total:
        echo(f"{blue}Total{reset}: {yellow}{results_total}{reset}", color=ctx.color)


@database_app.command("remove", no_args_is_help=True, short_help="Remove entries.")
@argument("table", nargs=1, required=True, is_eager=True, type=TableChoice())
@argument("ids", metavar="ID...", nargs=-1, required=True, type=str, callback=id_callback)
@confirmation_option("--yes", help="Confirm deletion without prompting.")
@database_exists_option
@color_option
@help_option
@pass_context
@docstring_format()
def database_remove(ctx: Context, database: Callable[..., Database], table: str, ids: tuple[str | int]):
    """
    Remove entries from the database using their IDs. The program will prompt for a confirmation before commencing
    deletion. To confirm deletion ahead, use the {yellow}--yes{reset} option.
    """
    db: Database = database()
    db_table: Table = get_table(db, table)

    add_history(db, ctx, table=table, ids=ids)

    for id_ in ids:
        if id_ not in db_table:
            secho(f"Entry {id_!r} could not be found in {db_table.name.lower()}", fg="red", color=ctx.color)
        elif db_table.name.lower() == submissions_table.lower():
            f, t = db.submissions.get_submission_files(id_)
            try:
                del db_table[id_]
                echo(f"Deleted entry {yellow}{id_}{reset} from {table}.", color=ctx.color)
            finally:
                db.commit()
                if f:
                    f.unlink(missing_ok=True)
                if t:
                    t.unlink(missing_ok=True)
        else:
            try:
                del db_table[id_]
                echo(f"Deleted entry {yellow}{id_}{reset} from {table}.", color=ctx.color)
            finally:
                db.commit()


@database_app.command("add", short_help="Add entries manually.")
@argument("table", nargs=1, required=True, is_eager=True, type=TableChoice())
@argument("file", nargs=1, required=True, type=File("r"))
@option("--submission-file", required=False, default=None, type=File("rb"))
@option("--submission-thumbnail", required=False, default=None, type=File("rb"))
@option("--replace", is_flag=True, default=False, show_default=True)
@database_exists_option
@color_option
@help_option
@pass_context
@docstring_format(prog_name=__prog_name__, version=__version__)
def database_add(ctx: Context, database: Callable[..., Database], table: str, file: TextIO,
                 submission_file: BytesIO | None, submission_thumbnail: BytesIO | None, replace: bool):
    """
    Add entries and submission files manually using a JSON file. Submission files/thumbnails can be added using the
    respective options.

    The JSON file must contain fields for all columns of the table. For a list of columns for each table, please see
    the README at {blue}https://pypi.org/project/{prog_name}/{version}{reset}.

    By default, the program will throw an error when trying to add an entry that already exists. To override this
    behaviour and ignore existing entries, use the {yellow}--replace{reset} option.
    """
    db: Database = database()

    add_history(db, ctx, table=table, file=file.name, submission_file=submission_file is not None,
                submission_thumbnail=submission_thumbnail is not None, replace=replace)

    data: dict = load(file)
    file.close()

    data = {k.upper(): v for k, v in data.items()}

    if table.lower() == submissions_table.lower():
        if any(c.name.upper() not in data for c in db.submissions.columns):
            raise BadParameter(f"Missing fields {set(map(str.upper, db.submissions.columns)) - set(data.keys())}"
                               f" for table {table}",
                               ctx, next((p for p in ctx.command.params if p.name == "file")))
        elif not replace and (id_ := data[idc := db.submissions.key.name.upper()]) in db.submissions:
            raise BadParameter(f"Entry with {idc} {id_!r} already exists in {table} table, but '--replace' is not set.",
                               ctx, next((p for p in ctx.command.params if p.name == "file")))
        sub_file_orig, sub_thumb_orig = db.submissions.get_submission_files(data["id"])
        sub_file: bytes | None = None
        sub_thumb: bytes | None = None
        if submission_file:
            sub_file: bytes = submission_file.read()
            submission_file.close()
        elif sub_file_orig:
            sub_file = sub_file_orig.read_bytes()
        if submission_thumbnail:
            sub_file: bytes = submission_thumbnail.read()
            submission_thumbnail.close()
        elif sub_thumb_orig:
            sub_file = sub_thumb_orig.read_bytes()
        try:
            db.submissions.save_submission(data, sub_file, sub_thumb, replace=replace)
        finally:
            db.commit()
    else:
        db_table: Table = get_table(db, table)
        if any(c.name.upper() not in data for c in db_table.columns):
            raise BadParameter(f"Missing fields {set(map(str.upper, db_table.columns)) - set(data.keys())}"
                               f" for table {table}",
                               ctx, next((p for p in ctx.command.params if p.name == "file")))
        elif not replace and (id_ := data[idc := db_table.key.name.upper()]) in db_table:
            raise BadParameter(f"Entry with {idc} {id_!r} already exists in {table} table, but '--replace' is not set.",
                               ctx, next((p for p in ctx.command.params if p.name == "file")))
        try:
            db_table.insert(db_table.format_entry(data), replace=replace)
        finally:
            db.commit()


@database_app.command("edit", short_help="Edit entries manually.")
@argument("table", nargs=1, required=True, is_eager=True, type=TableChoice())
@argument("_id", metavar="ID", nargs=1, required=True, is_eager=True)
@argument("file", nargs=1, required=False, type=File("r"))
@option("--submission-file", required=False, default=None, type=File("rb"))
@option("--submission-thumbnail", required=False, default=None, type=File("rb"))
@database_exists_option
@color_option
@help_option
@pass_context
def database_edit(ctx: Context, database: Callable[..., Database], table: str, _id: str | int, file: TextIO,
                  submission_file: BytesIO | None, submission_thumbnail: BytesIO | None):
    """
    Edit entries and submission files manually using a JSON file. Submission files/thumbnails can be added using the
    respective options.

    The JSON fields must match the column names of the selected table. For a list of columns for each table, please see
    the README at {blue}https://pypi.org/project/{prog_name}/{version}{reset}.

    If the {yellow}--submission-file{reset} and/or {yellow}--submission-thumbnail{reset} options are used, the
    {yellow}FILE{reset} argument can be omitted.
    """
    db: Database = database()
    db_table: Table = get_table(db, table)
    data: dict = load(file)
    file.close()

    if not data and table.lower() != db.submissions.name.lower():
        raise BadParameter(f"FILE cannot be empty for {table} table.", ctx,
                           next(p for p in ctx.command.params if p.name == "file"))
    elif not isinstance(data, dict):
        raise BadParameter(f"Data must be in JSON object format.", ctx,
                           next(p for p in ctx.command.params if p.name == "file"))

    add_history(db, ctx, table=table, id=_id, file=file.name,
                submission_file=submission_file.name if submission_file else None,
                submission_thumbnail=submission_thumbnail.name if submission_thumbnail else None)

    if (entry := db_table[_id]) is None:
        raise BadParameter(f"No entry with ID {_id} in {table}.", ctx,
                           next(p for p in ctx.command.params if p.name == "_id"))

    if submission_file:
        ext: str = db.submissions.save_submission_file(_id, submission_file.read(), "submission", "")
        data = data | {(f := SubmissionsColumns.FILESAVED.value.name): (entry[f] & 0b01) + 0b10,
                       SubmissionsColumns.FILEEXT.value.name: ext}
    if submission_thumbnail:
        db.submissions.save_submission_file(_id, submission_file.read(), "submission", "")
        data = data | {(f := SubmissionsColumns.FILESAVED.value.name): (entry[f] & 0b10) + 0b01}

    if data:
        db_table.update(Sb(db_table.key.name).__eq__(_id), data)


@database_app.command("clean", short_help="Clean database.")
@database_exists_option
@color_option
@help_option
def database_clean(database: Callable[..., Database]):
    """
    Clean database using the SQLite VACUUM function.
    """

    db: Database = database()
    echo("Cleaning database... ", nl=False)
    db.execute("VACUUM")
    db.commit()
    echo("Done")


# noinspection DuplicatedCode
@database_app.command("copy", short_help="Copy database entries.")
@argument("database_dest", nargs=1, callback=database_callback,
          type=PathClick(exists=True, dir_okay=False, writable=True, resolve_path=True, path_type=Path))
@option("--query", metavar="<TABLE QUERY>", multiple=True, type=(TableChoice(), str),
        help="Specify a table and query to copy.")
@option("--replace", is_flag=True, default=False, show_default=True, help="Replace entries already in database.")
@database_exists_option
@color_option
@help_option
@pass_context
@docstring_format(tables=', '.join(t.value for t in TableChoice.completion_items))
def database_copy(ctx: Context, database: Callable[..., Database], database_dest: Callable[..., Database],
                  query: tuple[tuple[str, str]], replace: bool):
    """
    Copy database to {yellow}DATABASE_DEST{reset}.

    Specific tables can be selected with the {yellow}--query{reset} option. For details on the syntax for the
    {yellow}QUERY{reset} value, see {yellow}database search{reset}. To select all entries in a table, use
    {cyan}%{reset} as query. The {yellow}TABLE{reset} value can be one of {tables}.

    If no {yellow}--query{reset} option is given, all major tables from the origin database are copied ({tables}).
    """

    db: Database = database()
    db2: Database = database_dest(print_envvar=False)
    cursors: list[Cursor]
    if query:
        cursors = [
            search(tb := get_table(db, t), [c.name for c in tb.columns], q, tb.key.name, "desc", None, None, False)[0]
            for t, q in query]
    else:
        cursors = [get_table(db, t.value).select() for t in TableChoice.completion_items]

    echo(f"Copying {', '.join(f'{yellow}{c.table.name}{reset}' for c in cursors)} to {yellow}{db2.path}{reset} ... ",
         nl=False, color=ctx.color)

    db.copy(db2, *cursors, replace=replace)
    db.commit()
    add_history(db2, ctx, query=query, origin=db.path)

    echo("Done")


# noinspection DuplicatedCode
@database_app.command("merge", short_help="Merge database entries.")
@argument("database_origin", nargs=1, callback=database_callback,
          type=PathClick(exists=True, dir_okay=False, writable=True, resolve_path=True, path_type=Path))
@option("--query", metavar="<TABLE QUERY>", multiple=True, type=(TableChoice(), str),
        help="Specify a table and query to merge.")
@option("--replace", is_flag=True, default=False, show_default=True, help="Replace entries already in database.")
@database_exists_option
@color_option
@help_option
@pass_context
@docstring_format(tables=', '.join(t.value for t in TableChoice.completion_items))
def database_copy(ctx: Context, database: Callable[..., Database], database_origin: Callable[..., Database],
                  query: tuple[tuple[str, str]], replace: bool):
    """
    Merge database from {yellow}DATABASE_ORIGIN{reset}.

    Specific tables can be selected with the {yellow}--query{reset} option. For details on the syntax for the
    {yellow}QUERY{reset} value, see {yellow}database search{reset}. To select all entries in a table, use
    {cyan}%{reset} as query. The {yellow}TABLE{reset} value can be one of {tables}.

    If no {yellow}--query{reset} option is given, all major tables from the origin database are copied ({tables}).
    """

    db: Database = database()
    db2: Database = database_origin(print_envvar=False)
    cursors: list[Cursor]
    if query:
        cursors = [
            search(tb := get_table(db2, t), [c.name for c in tb.columns], q, tb.key.name, "desc", None, None, False)[0]
            for t, q in query]
    else:
        cursors = [get_table(db2, t.value).select() for t in TableChoice.completion_items]

    echo(f"Copying {', '.join(f'{yellow}{c.table.name}{reset}' for c in cursors)} from {yellow}{db2.path}{reset} ... ",
         nl=False, color=ctx.color)

    db.merge(db2, *cursors, replace=replace)
    db.commit()
    add_history(db, ctx, query=query, origin=db2.path)

    echo("Done")


@database_app.command("upgrade", short_help="Upgrade database.")
@database_exists_option
@color_option
@help_option
@pass_context
@docstring_format(__database_version__)
def database_upgrade(ctx: Context, database: Callable[..., Database]):
    """
    Upgrade the database to the latest version ({yellow}{0}{reset}).
    """

    db: Database = database(check_version=False)
    if (version := db.version) != __database_version__:
        db.upgrade(check_connections=EnvVars.MULTI_CONNECTION)
        add_history(db, ctx, version_from=version, version_to=__database_version__)