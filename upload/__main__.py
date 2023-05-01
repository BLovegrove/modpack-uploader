import copy
from datetime import datetime
import socket
import paramiko
from paramiko import SFTPClient
import sys
import os
from pathlib import Path
from semver import Version
import toml
from tkinter import messagebox
from enum import Enum
import config as cfg
from stat import S_ISDIR, S_ISREG
from tqdm import tqdm


# ================================================================================================ #
# changelog schema                                                                                 #
# ================================================================================================ #
class ChangeType(Enum):
    MOD = 1
    CFG = 2


class Changes:
    def __init__(self, add: list[str] = None, rem: list[str] = None):
        self.add = add if add else []
        self.rem = rem if rem else []


class Update:
    def __init__(
        self,
        version: Version,
        changes: Changes,
    ):
        self.version = version
        self.changes = changes

    def to_dict(self):
        changes = {"add": self.changes.add, "rem": self.changes.rem}
        return {
            "version": f"{self.version.major}.{self.version.minor}.{self.version.patch}",
            "changes": changes,
        }


class Changelog:
    def __init__(self, updates: list[Update] = None):
        self.updates: list[Update] = updates if updates else []

    def from_dict(self, config: dict[str, any]):
        updates = []

        for update in config["updates"]:
            updates.append(
                Update(
                    Version.parse(update["version"]),
                    Changes(update["changes"]["add"], update["changes"]["rem"]),
                )
            )

        self.updates = updates
        return self

    def compile_changes(self):
        result: list[str] = []

        for update in self.updates:
            for item in update.changes.add:
                result.append(item)
            for item in update.changes.rem:
                try:
                    result.remove(item)
                except ValueError:
                    pass

        return result

    def add_update(
        self, version: Version, local_files: list[str], changed_files: list[str]
    ):
        remote_files = self.compile_changes()

        files_removed = [file for file in remote_files if file not in local_files]
        files_added = changed_files

        update = Update(
            version=version,
            changes=Changes(files_added, files_removed),
        )

        self.updates.insert(0, update)

        return

    def to_dict(self):
        updates = []
        for update in self.updates:
            updates.append(update.to_dict())

        return {"updates": updates}


# ================================================================================================ #
# helper methods                                                                                   #
# ================================================================================================ #
def sftp_list_recursive(sftp: SFTPClient, remote_dir: str, file_list: list[str] = None):
    files: list[str] = []

    for dir in sftp.listdir_attr(remote_dir):
        path = remote_dir + "/" + dir.filename
        mode = dir.st_mode
        if S_ISDIR(mode):
            sftp_list_recursive(sftp, path, files)
        elif S_ISREG(mode):
            if file_list:
                file_list.append(path)
            else:
                files.append(path)

    return files


def local_list_recursive(local_dir: str):
    files: list[str] = []

    for path in Path(local_dir).rglob("*"):
        if path.is_file() is False:
            continue
        if os.name == "nt":
            files.append(f"{path}".replace("..\\", "", 1).replace("\\", "/"))
        else:
            files.append(f"{path}".replace("../", "", 1))

    return files


def sftp_mkdirs(sftp: SFTPClient, remote: str):
    dirs = []
    dir = os.path.split(remote)[0]
    while len(dir) > 1:
        dirs.append(dir)
        dir = os.path.split(dir)[0]

    if len(dir) == 1 and not dir.startswith("/"):
        dirs.append(dir)  # For a remote path like y/x.txt

    while len(dirs):
        dir = dirs.pop()
        try:
            sftp.stat(dir)
        except:
            sftp.mkdir(dir)


# ================================================================================================ #
# main program                                                                                     #
# ================================================================================================ #
def main():
    # check for dry run arg -------------------------------------------------------------------------- #
    if "-d" in sys.argv or "--dryrun" in sys.argv:
        dry_run = True
        print("! == THIS IS A DRY RUN == !")
    else:
        dry_run = False

    # set current working dir to script dir ---------------------------------------------------------- #
    os.chdir(os.path.dirname(sys.argv[0]))

    # check connection to server --------------------------------------------------------------------- #
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect((cfg.server.host, int(cfg.server.port)))
        s.shutdown(socket.SHUT_RDWR)
        con_status = True
    except:
        con_status = False
    finally:
        s.close()

    if con_status == False:
        message = (
            f"FAILED TO CONNECT TO HOST SERVER {cfg.server.host} ON PORT {cfg.server.port}."
            + os.linesep * 2
            + "Please check your internet connection or talk to your server host about this issue."
        )
        messagebox.showerror(title="ERROR", message=message)

    # set up SFTP connection ------------------------------------------------------------------------- #
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        cfg.server.host,
        cfg.server.port,
        username=cfg.server.username,
        password=cfg.server.password,
    )

    sftp = ssh.open_sftp()
    sftp.chdir(cfg.server.filepath)

    # load changelog file or create new if one doesnt exist ------------------------------------------ #
    try:
        with sftp.open("changelog.toml", "r") as f:
            dict_changelog = toml.loads("".join(f.readlines()))
            changelog = Changelog().from_dict(dict_changelog)

    except FileNotFoundError:
        changelog = Changelog()
        changelog.add_update(Version(0, 0, 0), [], [])

    # get semantic version number -------------------------------------------------------------------- #
    version_current = changelog.updates[0].version

    # ask for new semantic version ------------------------------------------------------------------- #
    while True:
        version_target = input(
            os.linesep
            + f"Current version: {version_current}"
            + os.linesep
            + "Please enter a semantic version type to increase by 1 for this upload. (M)ajor, (m)inor (p)atch or a custom number with (c)ustom."
            + os.linesep
            + "> "
        )

        if version_target in ["M", "m", "p", "c"]:
            break
        elif version_target.lower() in ["major", "minor", "patch", "custom"]:
            version_target = version_target.lower()
            break
        else:
            print(
                f"{os.linesep}Please enter a valid option (full words or short-codes minus backets. Short-codes are case-sensitive).{os.linesep}"
            )

    match version_target:
        case "M" | "major":
            version_update = version_current.bump_major()

        case "m" | "minor":
            version_update = version_current.bump_minor()

        case "p" | "patch":
            version_update = version_current.bump_patch()

        case "c" | "custom":
            while True:
                version_custom = input(
                    "Please enter your custom semantic version (e.g. 1.2.3):"
                    + os.linesep
                    + "> "
                )

                try:
                    parsed_version = Version.parse(version_custom)
                    version_update = parsed_version
                    break
                except ValueError as e:
                    print(
                        "Invalid version number entered. Please stick to semantic verisoning I.E: 1.0.12"
                        + os.linesep
                    )

    print(os.linesep)

    # collate list of mods --------------------------------------------------------------------------- #
    if dry_run is False:
        try:
            sftp.mkdir("mods")
        except Exception:
            pass

    print("Finding remote mods...")
    if dry_run:
        mods_remote = []
    else:
        mods_remote = sftp_list_recursive(sftp, "mods")
    print(f"Found {len(mods_remote)} mods." + os.linesep)

    print("Finding local mods...")
    mods_local = local_list_recursive("../mods")
    mods_local = [mod for mod in mods_local if "mods/.index" not in mod]
    mods_changed = [mod for mod in mods_local if mod not in mods_remote]
    print(f"Found {len(mods_local)} mods.")

    print(os.linesep)

    # compile into upload queue ---------------------------------------------------------------------- #
    upload_queue = []

    print("Collating list of files to upload...")
    for mod in tqdm(
        mods_changed,
        "Mods",
        leave=True,
        position=0,
    ):
        upload_queue.append(mod)

    print(f"{len(upload_queue)} files need uploading.")

    print(os.linesep)

    # upload files from queue ------------------------------------------------------------------------ #
    print("Uploading files to server...")
    for file in tqdm(upload_queue, "Progress", leave=True, position=0):
        if dry_run is False:
            try:
                sftp.put("../" + file, file)
            except FileNotFoundError:
                sftp_mkdirs(sftp, file)
                sftp.put("../" + file, file)

    print(os.linesep)

    # add new update to changelog -------------------------------------------------------------------- #
    print("Adding update to changelog...")
    changelog_old = copy.deepcopy(changelog)
    changelog.add_update(version_update, mods_local, mods_changed)

    print(os.linesep)

    # dump changelog and override remote ------------------------------------------------------------- #
    print("Dumping new changelog and uploading to server...")
    if dry_run:
        with open("dryrun_old.toml", "w") as f:
            f.write(toml.dumps(changelog_old.to_dict()))
        with open("dryrun_new.toml", "w") as f:
            f.write(toml.dumps(changelog.to_dict()))
    else:
        with open("changelog.toml", "w") as f:
            toml.dump(changelog.to_dict(), f)

        sftp.put("changelog.toml", "changelog.toml")

    # clean up and end script ------------------------------------------------------------------------ #
    if dry_run is False:
        os.remove("changelog.toml")

    sftp.close()
    ssh.close()
    messagebox.showinfo(
        title="SUCCESS!",
        message=f"Version {version_update} uploaded. Changelog Updated.",
    )


if __name__ == "__main__":
    main()
