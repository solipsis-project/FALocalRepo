from datetime import datetime
from inspect import cleandoc
from json import dumps
from json import load
from os import environ
from os.path import getsize
from pathlib import Path
from re import match
from sys import stderr
from typing import Callable
from typing import Iterable

from faapi import __version__ as __faapi_version__
from falocalrepo_database import FADatabase
from falocalrepo_database import FADatabaseCursor
from falocalrepo_database import FADatabaseTable
from falocalrepo_database import __version__ as __database_version__
from falocalrepo_database.database import clean_username
from falocalrepo_database.selector import Selector
from falocalrepo_server import __version__ as __server_version__
from falocalrepo_server import server
from psutil import AccessDenied
from psutil import NoSuchProcess
from psutil import process_iter

from .__version__ import __version__
from .commands import latest_version
from .commands import make_journal
from .commands import make_submission
from .commands import make_user
from .commands import parameters_to_selector
from .commands import print_items
from .commands import print_users
from .commands import search
from .download import download_journals as download_journals_
from .download import download_submissions as download_submissions_
from .download import download_users as download_users_
from .download import download_users_update
from .download import read_cookies
from .download import write_cookies
from .exceptions import MalformedCommand
from .exceptions import MultipleInstances
from .exceptions import UnknownCommand


class Flags:
    DEBUG: bool = environ.get("FALOCALREPO_DEBUG", None) is not None
    DATABASE: Path | None = Path(p) if (p := environ.get("FALOCALREPO_DATABASE", None)) is not None else None


def check_process(process: str):
    ps: int = 0
    for p in process_iter():
        try:
            ps += "python" in p.name().lower() and any(process in Path(cmd).parts for cmd in p.cmdline())
        except (NoSuchProcess, AccessDenied):
            pass
        if ps > 1:
            raise MultipleInstances(f"Another instance of {process} was detected")


def check_database_version(db: FADatabase, raise_for_error: bool = True):
    if (err := db.check_version(raise_for_error=False)) is not None:
        print(f"Database version is not latest: {db.version} != {__database_version__}")
        print("Use database upgrade command to upgrade database")
        if raise_for_error:
            raise err


def docstring_format(*args, **kwargs):
    def inner(obj: {__doc__}) -> {__doc__}:
        obj.__doc__ = (obj.__doc__ or "").format(*args, **kwargs)
        return obj

    return inner


def parameters_multi(args: Iterable[str]) -> dict[str, list[str]]:
    params: dict[str, list[str]] = {}
    for param, value in map(lambda p: p.split("=", 1), args):
        param = param.strip()
        params[param] = [*params.get(param, []), value]

    return params


def parameters(args: Iterable[str]) -> dict[str, str]:
    return {p: v for p, v in map(lambda p: p.split("=", 1), args)}


def parse_args(args_raw: Iterable[str]) -> tuple[dict[str, str], list[str]]:
    opts: list[str] = []
    args: list[str] = []

    for i, arg in enumerate(args_raw):
        if match(r"^[\w-]+=.*$", arg):
            opts.append(arg)
        elif arg == "--":
            args.extend(args_raw[i + 1:])
            break
        else:
            args.extend(args_raw[i:])
            break

    return parameters(opts), args


def check_update(version: str, package: str) -> str | None:
    return latest if (latest := latest_version(package)) and latest != version else None


# noinspection GrazieInspection
def help_(comm: str = "", op: str = "", *_rest) -> str:
    """
    USAGE
        falocalrepo help [<command> [<operation>]]

    ARGUMENTS
        <command>       Command to get the help of
        <operation>     Command operation to get the help of

    DESCRIPTION
        Get help for a specific command or operation. If no command is passed
        then a general help message is given instead.
    """

    match [comm, op]:
        case ["", ""]:
            return cleandoc(console.__doc__)
        case ["help", _]:
            return cleandoc(help_.__doc__)
        case ["update", _]:
            return cleandoc(update.__doc__)
        case ["init", _]:
            return cleandoc(init.__doc__)
        case ["config", ""]:
            return cleandoc(config.__doc__)
        case ["config", "list"]:
            return cleandoc(config_list.__doc__)
        case ["config", "cookies"]:
            return cleandoc(config_cookies.__doc__)
        case ["config", "files-folder"]:
            return cleandoc(config_files_folder.__doc__)
        case ["download", ""]:
            return cleandoc(download.__doc__)
        case ["download", "users"]:
            return cleandoc(download_users.__doc__)
        case ["download", "update"]:
            return cleandoc(download_update.__doc__)
        case ["download", "submissions"]:
            return cleandoc(download_submissions.__doc__)
        case ["download", "journals"]:
            return cleandoc(download_journals.__doc__)
        case ["database", ""]:
            return cleandoc(database.__doc__)
        case ["database", "info"]:
            return cleandoc(database_info.__doc__)
        case ["database", "history"]:
            return cleandoc(database_history.__doc__)
        case ["database", "search-users"]:
            return cleandoc(database_search_users.__doc__)
        case ["database", "search-submissions"]:
            return cleandoc(database_search_submissions.__doc__)
        case ["database", "search-journals"]:
            return cleandoc(database_search_journals.__doc__)
        case ["database", "add-submission"]:
            return cleandoc(database_add_submission.__doc__)
        case ["database", "add-journal"]:
            return cleandoc(database_add_journal.__doc__)
        case ["database", "add-user"]:
            return cleandoc(database_add_user.__doc__)
        case ["database", "remove-users"]:
            return cleandoc(database_remove_users.__doc__)
        case ["database", "remove-submissions"]:
            return cleandoc(database_remove_submissions.__doc__)
        case ["database", "remove-journals"]:
            return cleandoc(database_remove_journals.__doc__)
        case ["database", "server"]:
            return cleandoc(database_server.__doc__)
        case ["database", "merge"]:
            return cleandoc(database_merge.__doc__)
        case ["database", "copy"]:
            return cleandoc(database_copy.__doc__)
        case ["database", "clean"]:
            return cleandoc(database_clean.__doc__)
        case ["database", "upgrade"]:
            return cleandoc(database_upgrade.__doc__)
        case _:
            raise UnknownCommand(f"{comm} {op}".strip())


# noinspection GrazieInspection
def init(db: FADatabase):
    """
    USAGE
        falocalrepo init

    DESCRIPTION
        The init command initialises the database and then exits. It can be used to
        create the database without performing any other operation. If a database is
        already present, no operation is performed.
    """

    check_database_version(db)
    print("Database ready")


# noinspection GrazieInspection
def config_list(db: FADatabase, *_rest):
    """
    USAGE
        falocalrepo config list

    DESCRIPTION
        Prints a list of stored settings.
    """

    config_cookies(db)
    config_files_folder(db)


# noinspection GrazieInspection
def config_cookies(db: FADatabase, *args: str):
    """
    USAGE
        falocalrepo config cookies [<name1>=<value1> ... <nameN>=<valueN>]

    ARGUMENTS
        <name>   The name of the cookie (e.g. a)
        <value>  The value of the cookie

    DESCRIPTION
        Read or modify stored cookies.

    EXAMPLES
        falocalrepo config cookies a=a1b2c3d4-1234 b=e5f6g7h8-5678
    """

    match args:
        case []:
            for c in read_cookies(db):
                print(f"cookie {c['name']}:", c['value'])
        case [a, b]:
            write_cookies(db, **parse_args([a, b])[0])
        case _:
            raise MalformedCommand("cookies needs two arguments")


# noinspection GrazieInspection
def config_files_folder(db: FADatabase, *args: str):
    """
    USAGE
        falocalrepo config files-folder [move=<move-files>] [<new folder>]

    ARGUMENTS
        <new folder>    Path to new files folder
        <move-files>    Set to 'true' or ignore to move old files folder, set to
                        'false' to update files folder value without moving files

    DESCRIPTION
        Read or modify the folder used to store submission files. This can be any
        path relative to the folder of the database. If a new value is given, the
        program will move any files to the new location.
    """

    opts, args = parse_args(args)

    match args:
        case []:
            print(f"files folder: {db.settings['FILESFOLDER']} ({db.files_folder.resolve()})")
        case [dest]:
            if mv := opts.get("move", "true") == "false":
                print(f"Ignoring original files folder {db.settings['FILESFOLDER']} ({db.files_folder.resolve()})")
            print(f"Changing files folder to {dest}")
            db.move_files_folder(dest, move_files=not mv)
            print("Done")
        case _:
            raise MalformedCommand("files-folder needs one argument")


# noinspection GrazieInspection
def config(db: FADatabase, comm: str = "", *args: str):
    """
    USAGE
        falocalrepo config [<setting> [<value1>] ... [<valueN>]]

    ARGUMENTS
        <setting>       Setting to read/edit
        <value>         New setting value

    AVAILABLE SETTINGS
        list            List settings
        cookies         Cookies for the API
        files-folder    Files download folder

    DESCRIPTION
        The config command allows to change the settings used by the program.
    """

    check_database_version(db)

    match comm:
        case "" | "list":
            config_list(db)
        case "cookies":
            config_cookies(db, *args)
        case "files-folder":
            config_files_folder(db, *args)
        case _:
            UnknownCommand(f"config {comm}")


# noinspection GrazieInspection
def download_users(db: FADatabase, *args: str):
    """
    USAGE
        falocalrepo download users <user1>[,...,<userN>] <folder1>[,...,<folderN>]

    ARGUMENTS
        <user>      Username
        <folder>    One of gallery, scraps, favorites, journals

    DESCRIPTION
        Download specific user folders. Requires two arguments with comma separated
        users and folders. Prepending 'list-' to a folder allows to list all remote
        items in a user folder without downloading them. Supported folders are:
            * gallery
            * scraps
            * favorites
            * journals

    EXAMPLES
        falocalrepo download users tom,jerry gallery,scraps,journals
        falocalrepo download users tom list-favorites
    """

    match args:
        case [users, folders]:
            download_users_(db, users.split(","), folders.split(","))
        case _:
            raise MalformedCommand("users needs two arguments")


# noinspection GrazieInspection
def download_update(db: FADatabase, *args: str):
    """
    USAGE
        falocalrepo download update [stop=<stop n>] [deactivated=<deactivated>]
                    [<user1>,...,<userN> | @] [<folder1>,...,<folderN> | @]

    ARGUMENTS
        <stop n>       Number of submissions to find in database before stopping,
                       defaults to 1
        <deactivated>  Set to 'true' to check previously deactivated users, other
                       values are ignored
        <user>         Username
        <folder>       One of gallery, scraps, favorites, journals

    DESCRIPTION
        Update the repository by checking the previously downloaded folders
        (gallery, scraps, favorites or journals) of each user and stopping when it
        finds a submission that is already present in the database. If a list of
        users and/or folders is passed, the update will be limited to those. To
        limit the update to certain folders without skipping any user, use '@' in
        place of the users argument. The stop=<n> option allows to stop updating
        after finding n submissions in a user's database entry, defaults to 1. If a
        user is deactivated, the folders in the database will be prepended with a
        '!'. Deactivated users will be skipped during the update unless the
        <deactivated> option is set to 'true'.

    EXAMPLES
        falocalrepo download update stop=5
        falocalrepo download update deactivated=true @ gallery,scraps
        falocalrepo download update tom,jerry
    """

    opts, args = parse_args(args)
    users, folders = [], []

    match args:
        case [] | ["@", "@"]:
            pass
        case [_users, "@"]:
            users = _users.split(",")
        case ["@", _folders]:
            folders = _folders.split(",")
        case [_users, _folders]:
            users, folders = _users.split(","), _folders.split(",")

    download_users_update(db, users, folders, int(opts.get("stop", 1)), opts.get("deactivated", "").lower() == "true")


# noinspection GrazieInspection
def download_submissions(db: FADatabase, *args: str):
    """
    USAGE
        falocalrepo download submissions <id1> ... [<idN>]

    ARGUMENTS
        <id>    Submission ID

    DESCRIPTION
        Download specific submissions. Requires submission ID's provided as separate
        arguments. If the submission is already in the database it is ignored.

    EXAMPLES
        falocalrepo download submissions 12345678 13572468 87651234
    """

    if not args:
        raise MalformedCommand("submissions needs at least one argument")
    sub_ids_tmp: list[str] = list(filter(str.isdigit, args))
    sub_ids: list[str] = sorted(set(sub_ids_tmp), key=sub_ids_tmp.index)
    download_submissions_(db, sub_ids)


# noinspection GrazieInspection
def download_journals(db: FADatabase, *args: str):
    """
    USAGE
        falocalrepo download journals <id1> ... [<idN>]

    ARGUMENTS
        <id>    Journal ID

    DESCRIPTION
        Download specific journals. Requires journal ID's provided as separate
        arguments. If the journal is already in the database it is ignored.

    EXAMPLES
        falocalrepo download journals 123456 135724 876512
    """

    if not args:
        raise MalformedCommand("journals needs at least one argument")
    journal_ids_tmp: list[str] = list(filter(str.isdigit, args))
    journal_ids: list[str] = sorted(set(journal_ids_tmp), key=journal_ids_tmp.index)
    download_journals_(db, journal_ids)


# noinspection GrazieInspection
def download(db: FADatabase, comm: str = "", *args: str):
    """
    USAGE
        falocalrepo download <operation> [<option>=<value>] [<arg1>] ... [<argN>]

    ARGUMENTS
        <operation>     The download operation to execute
        <option>        Option for the download command
        <value>         Value of an option
        <arg>           Argument for the download command

    AVAILABLE COMMANDS
        users           Download users
        update          Update database using the users and folders already saved
        submissions     Download single submissions
        journals        Download single journals

    DESCRIPTION
        The download command performs all download operations to save and update
        users, submissions, and journals. Submissions are downloaded together with
        their thumbnails, if there are any.
    """

    check_database_version(db)
    check_process("falocalrepo")

    match comm:
        case "users":
            download_users(db, *args)
        case "update":
            download_update(db, *args)
        case "submissions":
            download_submissions(db, *args)
        case "journals":
            download_journals(db, *args)
        case _:
            raise UnknownCommand(f"download {comm}")


# noinspection GrazieInspection
def database_info(db: FADatabase):
    """
    USAGE
        falocalrepo database info

    DESCRIPTION
        Show database information, statistics and version.
    """

    print("Location    :", db.database_path)
    print("Size        :", f"{getsize(db.database_path) / 1e6:.1f}MB")
    print("Users       :", len(db.users))
    print("Submissions :", len(db.submissions))
    print("Journals    :", len(db.journals))
    print("History     :", (len(h) - 1) if (h := db.settings.read_history()) else 0)
    print("Version     :", db.version)


# noinspection GrazieInspection
def database_history(db: FADatabase):
    """
    USAGE
        falocalrepo database history

    DESCRIPTION
        Show commands history.
    """

    for time, command in db.settings.read_history():
        print(str(datetime.fromtimestamp(time)), command)


# noinspection GrazieInspection
def database_search(table: FADatabaseTable, print_func: Callable, *args: str):
    """
    USAGE
        falocalrepo database search-{0} [json=<json>] [columns=<columns>]
                    [<param1>=<value1>] ... [<paramN>=<valueN>]

    ARGUMENTS
        <json>      Set to 'true' to output metadata in JSON format
        <columns>   Comma-separated list of columns to select, only active for JSON
        <param>     Search parameter
        <value>     Value of the parameter

    DESCRIPTION
        Search the {0} entries using metadata fields. Search parameters can
        be passed multiple times to act as OR values. All columns of the {0}
        table are supported, the 'any' parameter can be used to match against any
        column. Parameters can be lowercase. If no parameters are supplied, a list
        of all {0} will be returned instead. If <json> is set to 'true', the
        results are printed as a list of objects in JSON format. If <columns> is
        passed, then the objects printed with the JSON option will only contain
        those fields.
    """

    opts = parameters_multi(args)
    json, cols = opts.get("json", [None])[0] == "true", opts["columns"][0].split(",") if "columns" in opts else None
    results: list[dict[str, int | str]] = search(table, opts, cols if cols and json else None)
    if json:
        print(dumps(results))
    else:
        print_func(results)
        print(f"Found {len(results)} {table.table.lower()}")


# noinspection GrazieInspection
@docstring_format("users")
@docstring_format(database_search.__doc__)
def database_search_users(db: FADatabase, *args: str):
    """
    {0}

    EXAMPLES
        falocalrepo database search-users json=true folders=%gallery%
    """

    database_search(db.users, print_users, *args)


# noinspection GrazieInspection
@docstring_format("submissions")
@docstring_format(database_search.__doc__)
def database_search_submissions(db: FADatabase, *args: str):
    """
    {0}

    EXAMPLES
        falocalrepo database search-submissions tags=%|cat|%|mouse|% date=2020-% \\
            category=%artwork% order="AUTHOR" order="ID"
        falocalrepo database search-submissions json=true columns=id,author,title \\
            tags=%|cat|% tags=%|mouse|% date=2020-% category=%artwork%
    """

    database_search(db.submissions, print_items, *args)


# noinspection GrazieInspection
@docstring_format("journals")
@docstring_format(database_search.__doc__)
def database_search_journals(db: FADatabase, *args: str):
    """
    {0}

    EXAMPLES
        falocalrepo database search-journals date=2020-% author=CatArtist \\
            order="ID DESC"
        falocalrepo database search-journals json=true columns=id,author,title \\
            date=2020-% date=2019-% content=%commission%
    """

    database_search(db.journals, print_items, *args)


# noinspection GrazieInspection
def database_add_user(db: FADatabase, *args):
    """
    USAGE
        falocalrepo database add-user <json>

    ARGUMENTS
        <json>  Path to a JSON file containing the user metadata

    DESCRIPTION
        Add or replace a user entry into the database using metadata from a JSON
        file. If the user already exists in the database, fields may be omitted from
        the JSON, except for the ID. Omitted fields will not be replaced in the
        database and will remain as they are. The following fields are supported:
            * 'username'
        The following fields are optional:
            * 'folders'

    EXAMPLES
        falocalrepo database add-user ./user.json
    """

    data: dict = load(open(args[0]))
    make_user(db, data)


# noinspection GrazieInspection
def database_add_submission(db: FADatabase, *args: str):
    """
    USAGE
        falocalrepo database add-submissions <json> [file=<file>] [thumb=<thumb>]

    ARGUMENTS
        <json>  Path to a JSON file containing the submission metadata
        <file>  Path to new file
        <thumb> Path to new thumbnail

    DESCRIPTION
        Add or replace a submission entry into the database using metadata from a
        JSON file. If the submission already exists in the database, fields may be
        omitted from the JSON, except for the ID. Omitted fields will not be
        replaced in the database and will remain as they are. The optional <file>
        and <thumb> parameters allow to add or replace the submission file and
        thumbnail respectively. The following fields are supported:
            * 'id'
            * 'title'
            * 'author'
            * 'date' date in the format YYYY-MM-DD
            * 'description'
            * 'category'
            * 'species'
            * 'gender'
            * 'rating'
            * 'type' image, text, music, or flash
            * 'folder' gallery or scraps
            * 'fileurl' the remote URL of the submission file
        The following fields are optional:
            * 'tags' list of tags, if omitted it defaults to existing entry or empty
            * 'favorite' list of users that faved the submission, if omitted it
                defaults to existing entry or empty
            * 'mentions' list of mentioned users, if omitted it defaults to existing
                entry or mentions are extracted from the description
            * 'userupdate' 1 if the submission is downloaded as part of a user
                gallery/scraps else 0, if omitted it defaults to entry or 0

    EXAMPLES
        falocalrepo database add-submission ./submission/metadata.json \\
            file=./submission/submission.pdf thumb=./submission/thumbnail.jpg
    """

    data: dict = load(open(args[0]))
    opts: dict = parameters(args[1:])
    make_submission(db, data, opts.get("file", None), opts.get("thumbnail", None))


# noinspection GrazieInspection
def database_add_journal(db: FADatabase, *args: str):
    """
    USAGE
        falocalrepo database add-journal <json>

    ARGUMENTS
        <json>  Path to a JSON file containing the journal metadata

    DESCRIPTION
        Add or replace a journal entry into the database using metadata from a JSON
        file. If the journal already exists in the database, fields may be omitted
        from the JSON, except for the ID. Omitted fields will not be replaced in the
        database and will remain as they are. The following fields are supported:
            * 'id'
            * 'title'
            * 'author'
            * 'date' date in the format YYYY-MM-DD
            * 'content' the body of the journal
        The following fields are optional:
             * 'mentions' list of mentioned users, if omitted it defaults to existing
                entry or mentions are extracted from the content

    EXAMPLES
        falocalrepo database add-journal ./journal.json"
    """

    data: dict = load(open(args[0]))
    make_journal(db, data)


# noinspection GrazieInspection
def database_remove_users(db: FADatabase, *args: str):
    """
    USAGE
        falocalrepo database remove-users <user1> ... [<userN>]

    ARGUMENTS
        <user>  Username

    DESCRIPTION
        Remove specific users from the database.
    """

    for user in map(clean_username, args):
        print("Deleting", user)
        del db.users[user]
        db.commit()


# noinspection GrazieInspection
def database_remove_submissions(db: FADatabase, *args: str):
    """
    USAGE
        falocalrepo database remove-submissions <id1> ... [<idN>]

    ARGUMENTS
        <id>    Submission ID

    DESCRIPTION
        Remove specific submissions from the database.
    """

    for sub in args:
        print("Deleting", sub)
        del db.submissions[int(sub)]
        db.commit()


# noinspection GrazieInspection
def database_remove_journals(db: FADatabase, *args: str):
    """
    USAGE
        falocalrepo database remove-journals <id1> ... [<idN>]

    ARGUMENTS
        <id>    Journal ID

    DESCRIPTION
        Remove specific journals from the database.
    """

    for jrn in args:
        print("Deleting", jrn)
        del db.journals[int(jrn)]
    db.commit()


# noinspection GrazieInspection
@docstring_format(__server_version__)
def database_server(db: FADatabase, *args: str):
    """
    USAGE
        falocalrepo database server [host=<host>] [port=<port>]
                    [ssl-cert=<ssl-cert>] [ssl-key=<ssl-key>]
                    [redirect-http=<redirect-port>]

    ARGUMENTS
        <host>          Host address
        <port>          Port
        <ssl-cert>      SSL certificate for HTTPS
        <ssl-key>       SSL key for HTTPS
        <redirect-port> Port for HTTP to HTTPS redirection

    DESCRIPTION
        Starts a server at <host>:<port> to navigate the database, defaults to
        0.0.0.0:80. The <ssl-cert> and <ssl-key> allow serving with HTTPS. Setting
        <redirect-http> to a value activates HTTP to HTTPS redirection. For more
        details on usage see https://pypi.org/project/falocalrepo-server/{0}.

    EXAMPLES
        falocalrepo database server host=127.0.0.1 port=5000
    """

    db.close()
    database_path, db = db.database_path, None
    opts, _ = parse_args(args)
    server(database_path,
           host=opts.get("host", "0.0.0.0"),
           port=int(p) if (p := opts.get("port", None)) and p != "0" else None,
           ssl_cert=opts.get("ssl-cert", None),
           ssl_key=opts.get("ssl-key", None),
           redirect_port=int(p) if (p := opts.get("redirect-http", None)) else None
           )


# noinspection GrazieInspection
def database_merge_copy(db: FADatabase, merge: bool = True, *args):
    """
    USAGE
        falocalrepo database {0} <path> [<table1>.<param1>=<value1> ...
                    <tableN>.<paramN>=<valueN>]

    ARGUMENTS
        <path>  Path to second database file
        <table> One of users, submissions, journals
        <param> Search parameter
        <value> Value of the parameter
    """
    if not args:
        raise MalformedCommand("copy needs at least a database argument")

    opts = parameters_multi(args[1:])
    usrs_opts: dict[str, list[str]] = {m.group(1): v for k, v in opts.items() if (m := match(r"users\.(.+)", k))}
    subs_opts: dict[str, list[str]] = {m.group(1): v for k, v in opts.items() if (m := match(r"submissions\.(.+)", k))}
    jrns_opts: dict[str, list[str]] = {m.group(1): v for k, v in opts.items() if (m := match(r"journals\.(.+)", k))}

    usrs_query: Selector | None = parameters_to_selector(usrs_opts) if usrs_opts else None
    subs_query: Selector | None = parameters_to_selector(subs_opts) if subs_opts else None
    jrns_query: Selector | None = parameters_to_selector(jrns_opts) if jrns_opts else None

    with FADatabase(args[0]) as db2:
        print(f"{'Merging with database' if merge else 'Copying entries to'} {db2.database_path}...")
        cursors: list[FADatabaseCursor] = []
        cursors.append((db2 if merge else db).users.select(usrs_query)) if usrs_opts else None
        cursors.append((db2 if merge else db).submissions.select(subs_query)) if subs_opts else None
        cursors.append((db2 if merge else db).journals.select(jrns_query)) if jrns_opts else None
        db.merge(db2, *cursors) if merge else db.copy(db2, *cursors)
        db.commit()
        print("Done")


# noinspection GrazieInspection
@docstring_format("merge")
@docstring_format(database_merge_copy.__doc__)
def database_merge(db: FADatabase, *args: str):
    """
    {0}

    DESCRIPTION
        Merge selected entries from a second database to the main database (the one
        opened with the program). To select entries, use the same parameters as the
        search commands precede by a table name. Search parameters can be passed
        multiple times to act as OR values. All columns of the entries table are
        supported. Parameters can be lowercase. If no parameters are passed then all
        the database entries are copied. If submissions entries are selected, their
        files are copied to the files' folder of the main database.

    EXAMPLES
        falocalrepo database merge ~/Documents/FA.backup/A/FA.db users.username=a% \\
            submissions.author=a% journals.author=a%
        falocalrepo database merge ~/Documents/FA2020/FA.db \\
            submissions.date=2020-% journals.date=2020-%
        falocalrepo database merge ~/Documents/FA.backup/FA.db
    """

    database_merge_copy(db, True, *args)


# noinspection GrazieInspection
@docstring_format("copy")
@docstring_format(database_merge_copy.__doc__)
def database_copy(db: FADatabase, *args: str):
    """
    {0}

    DESCRIPTION
        Copy selected entries to a new or existing database. To select entries, use
        the same parameters as the search commands precede by a table name. Search
        parameters can be passed multiple times to act as OR values. All columns of
        the entries table are supported. Parameters can be lowercase. If no
        parameters are passed then all the database entries are copied. If
        submissions entries are selected, their files are copied to the files'
        folder of the target database.

    EXAMPLES
        falocalrepo database copy ~/Documents/FA.backup/A/FA.db users.username=a% \\
            submissions.author=a% journals.author=a%
        falocalrepo database copy ~/Documents/FA2020/FA.db submissions.date=2020-% \\
            journals.date=2020-%
        falocalrepo database copy ~/Documents/FA.backup/FA.db
    """

    database_merge_copy(db, False, *args)


# noinspection GrazieInspection
def database_clean(db: FADatabase, *_rest):
    """
    USAGE
        falocalrepo database clean

    DESCRIPTION
        Clean the database using the SQLite VACUUM function.
    """

    db.vacuum()


# noinspection GrazieInspection
@docstring_format(__database_version__)
def database_upgrade(db: FADatabase):
    """
    USAGE
        falocalrepo database upgrade

    DESCRIPTION
        Upgrade the database to the latest version ({0}).
    """

    db.upgrade()


# noinspection GrazieInspection
@docstring_format(__database_version__)
def database(db: FADatabase, comm: str = "", *args: str):
    """
    USAGE
        falocalrepo database [<operation> [<param1>=<value1> ... <paramN>=<valueN>]]

    ARGUMENTS
        <operation>         The database operation to execute
        <param>             Parameter for the database operation
        <value>             Value of the parameter

    AVAILABLE COMMANDS
        info                Show database information
        history             Show commands history
        search-users        Search users
        search-submissions  Search submissions
        search-journals     Search journals
        add-user            Add a user to the database manually
        add-submission      Add a submission to the database manually
        add-journal         Add a journal to the database manually
        remove-users        Remove users from database
        remove-submissions  Remove submissions from database
        remove-journals     Remove submissions from database
        server              Start local server to browse database
        merge               Merge with a second database
        copy                Copy entries to a second database
        clean               Clean the database with the VACUUM function
        upgrade             Upgrade the database to the latest version.

    DESCRIPTION
        The database command allows to operate on the database. Calling the database
        command without an operation defaults to 'list'. For more details on tables
        see https://pypi.org/project/falocalrepo-database/{0}.

        All search operations are conducted case-insensitively using the SQLite like
        expression which allows for limited pattern matching. For example this
        expression can be used to search two words together separated by an unknown
        amount of characters '%cat%mouse%'. Fields missing wildcards will only match
        an exact result, i.e. 'cat' will only match a field equal to 'cat' whereas
        '%cat%' wil match a field that contains 'cat'. Bars ('|') can be used to
        isolate individual items in list fields.

        All search operations support the extra 'order', 'limit', and 'offset'
        parameters with values in SQLite 'ORDER BY', 'LIMIT', and 'OFFSET' clause
        formats. The 'order' parameter supports all fields of the searched table.
    """

    check_database_version(db, raise_for_error=comm not in ("", "info", "upgrade"))

    match comm:
        case "" | "info":
            database_info(db)
        case "history":
            database_history(db)
        case "search-users":
            database_search_users(db, *args)
        case "search-submissions":
            database_search_submissions(db, *args)
        case "search-journals":
            database_search_journals(db, *args)
        case "add-user":
            database_add_user(db, *args)
        case "add-submission":
            database_add_submission(db, *args)
        case "add-journal":
            database_add_journal(db, *args)
        case "remove-users":
            database_remove_users(db, *args)
        case "remove-submissions":
            database_remove_submissions(db, *args)
        case "remove-journals":
            database_remove_journals(db, *args)
        case "server":
            database_server(db, *args)
        case "merge":
            database_merge(db, *args)
        case "copy":
            database_copy(db, *args)
        case "clean":
            database_clean(db, *args)
        case "upgrade":
            database_upgrade(db)
        case _:
            raise UnknownCommand(f"database {comm}")


# noinspection GrazieInspection
def update(shell_arg: str = ""):
    """
    USAGE
        falocalrepo update [shell]

    AVAILABLE COMMANDS
        shell       Print shell command to upgrade components

    DESCRIPTION
        Check for updates to falocalrepo and its main dependencies on PyPi. The
        optional 'shell' command can be used to output the shell command to upgrade
        any component that has available updates.
    """
    import faapi
    import falocalrepo_database
    import falocalrepo_server
    from . import __name__
    packages: list[tuple[str, str]] = [
        (__version__, __name__),
        (__database_version__, falocalrepo_database.__name__),
        (__server_version__, falocalrepo_server.__name__),
        (__faapi_version__, faapi.__name__)
    ]
    updates: list[tuple[str, str, str]] = [
        (current, latest, package)
        for [current, package] in packages
        if (latest := check_update(current, package))
    ]
    if shell_arg == "shell":
        print(f"python3 -m pip install --upgrade {' '.join(package for [*_, package] in updates)}") if updates else None
        return
    for [current, latest, package] in updates:
        print(f"New {package} version available: {latest} (current {current})")
    if not packages:
        print("No updates available")


# noinspection GrazieInspection
@docstring_format(__version__, __database_version__, __server_version__, __faapi_version__)
def console(comm: str = "", *args: str) -> None:
    """
    falocalrepo: {0}
    falocalrepo-database: {1}
    falocalrepo-server: {2}
    faapi: {3}

    USAGE
        falocalrepo [-h | -v | -d | -s | -u] [<command> [<operation>] [<arg1> ...
                    <argN>]]

    ARGUMENTS
        <command>       The command to execute
        <operation>     The operation to execute for the given command
        <arg>           The arguments of the command or operation

    GLOBAL OPTIONS
        -h, --help      Display this help message
        -v, --version   Display version
        -d, --database  Display database version
        -s, --server    Display server version

    AVAILABLE COMMANDS
        help            Display the manual of a command
        update          Check for updates on PyPi
        init            Create/update the database and exit
        config          Manage settings
        download        Perform downloads
        database        Operate on the database
    """

    match comm:
        case "" | "-h" | "--help":
            return print(help_())
        case "help":
            return print(help_(*args))
        case "-v" | "--version":
            return print(__version__)
        case "-d" | "--database":
            return print(__database_version__)
        case "-s" | "--server":
            return print(__server_version__)
        case "update":
            return update()
        case init.__name__ | config.__name__ | download.__name__ | database.__name__:
            pass
        case _:
            raise UnknownCommand(comm)

    if Flags.DEBUG is not None:
        print(f"Using FALOCALREPO_DEBUG", file=stderr)

    # Initialise and prepare database
    database_path: Path = Path("FA.db")

    if db_path := Flags.DATABASE:
        db_path = Path(db_path)
        print(f"Using FALOCALREPO_DATABASE: {db_path}", file=stderr)
        database_path = db_path if db_path.name.endswith(".db") else db_path / database_path

    FADatabase.check_connection(database_path, raise_for_error=True)
    db: FADatabase = FADatabase(database_path)

    try:
        db.settings.add_history(f"{comm} {' '.join(args)}".strip())
        db.commit()

        if comm == init.__name__:
            init(db)
        elif comm == config.__name__:
            config(db, *args)
        elif comm == download.__name__:
            download(db, *args)
        elif comm == database.__name__:
            database(db, *args)
    finally:
        if db is not None and db.is_open():
            db.commit()
            db.close()
