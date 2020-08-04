from shutil import move
from typing import List

from faapi import FAAPI

from .database import Connection
from .menu import menu
from .settings import cookies_change
from .settings import cookies_load
from .settings import setting_read
from .settings import setting_write


def download_menu(api: FAAPI, db: Connection):
    dl_menu: List[str] = [
        "Users",
        "Submissions",
        "Update",
        "Exit",
    ]

    while choice := menu(dl_menu):
        if choice == len(dl_menu):
            break


def database_menu(db: Connection):
    db_menu: List[str] = [
        "Search",
        "Manual Entry"
        "Check for Errors",
        "Exit",
    ]

    while choice := menu(db_menu):
        if choice == len(db_menu):
            break


def settings_menu(api: FAAPI, db: Connection):
    menu_items: List[str] = [
        "Cookies",
        "Files Folder",
        "Exit",
    ]

    while choice := menu(menu_items):
        if choice == len(menu_items):
            break
        elif choice == 1:
            print("Insert new values for cookies 'a' and 'b'.")
            print("Leave empty to keep previous value.\n")

            cookie_a_old, cookie_b_old = cookies_load(db)

            cookie_a: str = input(f"[{cookie_a_old}]\na: ")
            cookie_b: str = input(f"[{cookie_b_old}]\nb: ")

            if cookie_a or cookie_b:
                cookies_change(db, cookie_a, cookie_b)
                api.load_cookies([{"name": "a", "value": cookie_a}, {"name": "b", "value": cookie_b}])
        elif choice == 2:
            print("Insert new files folder.")
            print("Leave empty to keep previous value.\n")

            folder_old: str = setting_read(db, "FILESFOLDER")
            folder: str = input(f"[{folder_old}]\n:folder: ")

            if folder:
                setting_write(db, "FILESFOLDER", folder)
                print("Moving files to new location... ", end="", flush=True)
                move(folder_old, folder)
                print("Done")


def main_menu(workdir: str, db: Connection):
    api: FAAPI = FAAPI()

    menu_items: List[str] = [
        "Download",
        "Database",
        "Settings",
        "Exit"
    ]

    while choice := menu(menu_items):
        if choice == len(menu_items):
            break
        elif choice == 1:
            download_menu(api, db)
        elif choice == 2:
            database_menu(db)
        elif choice == 3:
            settings_menu(api, db)
