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


# TODO: rewrite all of this to abstract changes away from mods/config and just read the start of the change entry to determine what goes where


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

    def from_comparison(self, active_state: list[str], target_state: list[str]):
        for item in target_state:
            if item not in active_state:
                self.add.append(item)

        for item in active_state:
            if item not in target_state:
                self.rem.append(item)

        return self


class Update:
    def __init__(
        self,
        version: Version,
        timestamp: float,
        mods: Changes,
        cfgs: Changes,
    ):
        self.version = version
        self.timestamp = timestamp
        self.mods = mods
        self.cfgs = cfgs

    def to_dict(self):
        mods = {"add": self.mods.add, "rem": self.mods.rem}
        cfgs = {"add": self.cfgs.add, "rem": self.cfgs.rem}
        return {
            "version": f"{self.version.major}.{self.version.minor}.{self.version.patch}",
            "timestamp": self.timestamp,
            "mods": mods,
            "cfgs": cfgs,
        }


class Changelog:
    def __init__(self, updates: Update = None):
        self.updates: list[Update] = updates if updates else []

    def from_dict(self, config: dict[str, any]):
        updates = []

        for update in config["updates"]:
            updates.append(
                Update(
                    Version.parse(update["version"]),
                    update["timestamp"],
                    Changes(update["mods"]["add"], update["mods"]["rem"]),
                    Changes(update["cfgs"]["add"], update["cfgs"]["rem"]),
                )
            )

        self.updates = updates
        return self

    def compile_changes(self, target: ChangeType):
        result: list[str] = []

        for update in self.updates:
            for item in (
                update.mods.add if target == ChangeType.MOD else update.cfgs.add
            ):
                result.append(item)
            for item in (
                update.mods.rem if target == ChangeType.MOD else update.cfgs.rem
            ):
                try:
                    result.remove(item)
                except ValueError:
                    pass

        return result

    def add_update(self, version: str, new_mods: list[str], new_cfgs: list[str]):
        active_mods = self.compile_changes(ChangeType.MOD)
        active_cfgs = self.compile_changes(ChangeType.CFG)

        update = Update(
            version=version,
            timestamp=datetime.timestamp(datetime.now()),
            mods=Changes().from_comparison(active_mods, new_mods),
            cfgs=Changes().from_comparison(active_cfgs, new_cfgs),
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
def sftp_list_recursive(sftp: SFTPClient, remote_dir: str):
    files: list[str] = []

    for dir in sftp.listdir_attr(remote_dir):
        path = remote_dir + "/" + dir.filename
        mode = dir.st_mode
        if S_ISDIR(mode):
            sftp_list_recursive(sftp, path)
        elif S_ISREG(mode):
            files.append(path)

    return files


def local_list_recursive(local_dir: str):
    files: list[str] = []

    for path in Path(local_dir).rglob("*"):
        if not path.is_file():
            continue
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
            print(f"making {dir} dir"),
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
    os.chdir(os.path.dirname(__file__))

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

    # load changelog file ---------------------------------------------------------------------------- #
    with sftp.open("changelog.toml", "r") as f:
        dict_changelog = toml.loads("".join(f.readlines()))
        changelog = Changelog().from_dict(dict_changelog)

    # get semantic version number -------------------------------------------------------------------- #
    version_current = changelog.updates[0].version

    # get timestamp of most recent update ------------------------------------------------------------ #
    timestamp_current = changelog.updates[0].timestamp

    # ask for new semantic version ------------------------------------------------------------------- #
    while True:
        config_all = input(
            os.linesep
            + "Please enter a semantic version type to increase by 1 for this upload. (M)ajor, (m)inor (p)atch or a custom number with (c)ustom."
            + os.linesep
            + "> "
        )

        if config_all in ["M", "m", "p", "c"]:
            break
        elif config_all.lower() in ["major", "minor", "patch", "custom"]:
            config_all = config_all.lower()
            break
        else:
            print(
                f"{os.linesep}Please enter a valid option (full words or short-codes minus backets. Short-codes are case-sensitive).{os.linesep}"
            )

    match config_all:
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
                    v = Version.parse(version_custom)
                    version_update = version_custom
                    break
                except ValueError as e:
                    print(
                        "Invalid version number entered. Please stick to semantic verisoning I.E: 1.0.12"
                        + os.linesep
                    )

    # find out if user wants *all* configs, or only ones changed since last update ------------------- #
    while True:
        config_all = input(
            os.linesep
            + "Would you like to upload *all* config files? Please enter (Y)es for all, or (N)o for updated only."
            + os.linesep
            + "> "
        )

        if config_all.lower() in ["y", "n"]:
            config_all = config_all.lower()
            break
        elif config_all.lower() in ["yes", "no"]:
            config_all = config_all.lower()
            break
        else:
            print(
                os.linesep
                + f"Please enter a valid option (full words or short-codes minus backets)."
                + os.linesep
            )

    # collate list of mods --------------------------------------------------------------------------- #
    mods_remote = sftp_list_recursive(sftp, "mods")
    mods_local = local_list_recursive("../mods")

    # collate list of configs (all, or only updates, depending on config_all) ------------------------ #
    configs_local = local_list_recursive("../config")

    if not config_all:
        for config in configs_local:
            modified = os.path.getmtime("../config/" + config)
            t1 = datetime.fromtimestamp(modified)
            t2 = datetime.fromtimestamp(timestamp_current)
            latest = max((t1, t2))

            if latest == t2:
                configs_local.remove(config)

    # compile into upload queue ---------------------------------------------------------------------- #

    upload_queue = []

    for mod in mods_local:
        if mod not in mods_remote:
            upload_queue.append(mod)

    for config in configs_local:
        upload_queue.append(config)

    print(f"Upload queue:{upload_queue}")

    # upload files from queue ------------------------------------------------------------------------ #
    if dry_run:
        for file in upload_queue:
            print(f"Uploading {'../' + file} to {file}")
    else:
        for file in upload_queue:
            try:
                sftp.put("../" + file, file)
            except FileNotFoundError:
                sftp_mkdirs(sftp, file)
                sftp.put("../" + file, file)

    # add new update to changelog -------------------------------------------------------------------- #
    changelog_old = copy.deepcopy(changelog)
    changelog.add_update(version_update, mods_local, configs_local)

    # dump changelog and override remote ------------------------------------------------------------- #
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
    if not dry_run:
        os.remove("changelog.toml")

    sftp.close()
    ssh.close()
    messagebox.showinfo(
        title="SUCCESS!",
        message=f"Version {version_update} uploaded. Changelog Updated.",
    )


if __name__ == "__main__":
    main()
